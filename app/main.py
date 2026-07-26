"""Read-only API over the FTR topology-divergence warehouse.

Geometry and values are served separately: the map fetches polygons once, then swaps only
numbers when the month or class filter changes. Everything is generated from Postgres --
there is no build step and no external tile server, so the page renders with the network
off.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import date
from pathlib import Path

import psycopg
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from psycopg.rows import dict_row

STATIC = Path(__file__).parent / "static"

app = FastAPI(title="PJM FTR Topology Divergence", docs_url="/api/docs")


def parse_month(value: str) -> date:
    """Reject a bad month with 400 rather than letting Postgres raise a 500.

    Starlette renders an unhandled exception as *plain text*, which means a browser doing
    `res.json()` gets a parse error rather than a status code -- and an uncaught rejection
    takes the whole page down. Validate at the edge so failures stay structured.
    """
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        raise HTTPException(
            400, f"month must be an ISO date such as 2025-07-01; got {value!r}"
        )


@contextmanager
def db():
    conn = psycopg.connect(
        host=os.environ.get("PGHOST", "localhost"),
        port=int(os.environ.get("PGPORT", "5433")),
        dbname=os.environ.get("PGDATABASE", "ftr"),
        user=os.environ.get("PGUSER", "ftr"),
        password=os.environ.get("PGPASSWORD", "ftr_local_dev"),
        row_factory=dict_row,
    )
    try:
        yield conn
    finally:
        conn.close()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/meta")
def meta() -> JSONResponse:
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT month FROM fact_nodal_cong_monthly ORDER BY month DESC
            """
        )
        months = [r["month"].isoformat() for r in cur.fetchall()]

        cur.execute(
            """
            SELECT class_type, count(*) AS n
            FROM fact_nodal_cong_monthly GROUP BY 1 ORDER BY n DESC
            """
        )
        classes = [r["class_type"] for r in cur.fetchall()]

        cur.execute("SELECT count(*) AS n FROM fact_ftr_bid")
        n_bids = cur.fetchone()["n"]
        cur.execute("SELECT count(*) AS n FROM fact_nodal_cong_monthly")
        n_cong = cur.fetchone()["n"]
        cur.execute("SELECT count(*) AS n FROM dim_pnode WHERE is_active")
        n_nodes = cur.fetchone()["n"]

    return JSONResponse(
        {
            "months": months,
            "class_types": classes,
            "counts": {"bids": n_bids, "node_months": n_cong, "active_nodes": n_nodes},
        }
    )


@app.get("/api/geo")
def geo() -> JSONResponse:
    """Zone and state polygons. Fetched once; simplified to keep the payload small."""
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT zone_code, zone_label,
                   ST_AsGeoJSON(ST_SimplifyPreserveTopology(geom, 0.01))::json AS geometry
            FROM dim_zone WHERE geom IS NOT NULL ORDER BY zone_code
            """
        )
        zones = [
            {
                "type": "Feature",
                "properties": {"zone": r["zone_code"], "label": r["zone_label"]},
                "geometry": r["geometry"],
            }
            for r in cur.fetchall()
        ]

        cur.execute(
            """
            SELECT state_abbr, state_name, in_pjm,
                   ST_AsGeoJSON(ST_SimplifyPreserveTopology(geom, 0.03))::json AS geometry
            FROM dim_state ORDER BY state_abbr
            """
        )
        states = [
            {
                "type": "Feature",
                "properties": {
                    "state": r["state_abbr"],
                    "name": r["state_name"],
                    "in_pjm": r["in_pjm"],
                },
                "geometry": r["geometry"],
            }
            for r in cur.fetchall()
        ]

        # Bounds of the PJM footprint, so the map can open zoomed to it and still let you
        # pull back to the whole country for context.
        cur.execute(
            """
            SELECT ST_XMin(e) AS w, ST_YMin(e) AS s, ST_XMax(e) AS e2, ST_YMax(e) AS n
            FROM (SELECT ST_Extent(geom)::geometry AS e FROM dim_zone WHERE geom IS NOT NULL) q
            """
        )
        b = cur.fetchone()

    return JSONResponse(
        {
            "zones": {"type": "FeatureCollection", "features": zones},
            "states": {"type": "FeatureCollection", "features": states},
            "pjm_bounds": (
                [b["w"], b["s"], b["e2"], b["n"]] if b and b["w"] is not None else None
            ),
        }
    )


@app.get("/api/gap")
def gap(
    month: str = Query(...),
    class_type: str = Query("OnPeak"),
) -> JSONResponse:
    """Per-zone simulated-minus-realized congestion for one month and FTR class."""
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT zone, n_nodes, mean_gap, sd_gap, p10_gap, median_gap, p90_gap,
                   mean_realized, mean_sim, n_nodes_gap_over_1
            FROM v_zone_gap
            WHERE month = %s AND class_type = %s
            ORDER BY mean_gap DESC
            """,
            (parse_month(month), class_type),
        )
        rows = [dict(r) for r in cur.fetchall()]
    for r in rows:
        for k, v in r.items():
            if hasattr(v, "is_finite"):
                r[k] = float(v)
    return JSONResponse({"month": month, "class_type": class_type, "zones": rows})


@app.get("/api/zone/{zone_code}")
def zone_detail(
    zone_code: str,
    month: str = Query(...),
    class_type: str = Query("OnPeak"),
) -> JSONResponse:
    """Drill-down: the node-level gap distribution inside a zone, plus its traded paths."""
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT zone_label FROM dim_zone WHERE zone_code = %s", (zone_code,))
        row = cur.fetchone()
        if row is None:
            raise HTTPException(404, f"unknown zone {zone_code}")
        label = row["zone_label"]

        # Widest-gap nodes: where a zonal hedge diverges most from the node itself.
        cur.execute(
            """
            SELECT pnode_name, voltage_level, clmp_realized, clmp_sim, gap
            FROM v_node_gap
            WHERE zone = %s AND month = %s AND class_type = %s
            ORDER BY abs(gap) DESC
            LIMIT 15
            """,
            (zone_code, parse_month(month), class_type),
        )
        nodes = [dict(r) for r in cur.fetchall()]

        # Histogram of the within-zone gap distribution.
        cur.execute(
            """
            SELECT width_bucket(gap, -8, 12, 40) AS bucket, count(*) AS n
            FROM v_node_gap
            WHERE zone = %s AND month = %s AND class_type = %s
            GROUP BY 1 ORDER BY 1
            """,
            (zone_code, parse_month(month), class_type),
        )
        hist = [{"bucket": r["bucket"], "n": r["n"]} for r in cur.fetchall()]

        # Traded paths sinking into this zone, ranked by how far the simulation moves them.
        cur.execute(
            """
            SELECT source_name, sink_name, total_mw, n_bids, mw_wavg_price,
                   realized_spread, sim_spread, spread_gap
            FROM v_path_divergence
            WHERE sink_zone = %s AND auction_month = %s AND class_type = %s
            ORDER BY abs(spread_gap) DESC
            LIMIT 15
            """,
            (zone_code, parse_month(month), class_type),
        )
        paths = [dict(r) for r in cur.fetchall()]

    def floats(rows: list[dict]) -> list[dict]:
        for r in rows:
            for k, v in r.items():
                if hasattr(v, "is_finite"):
                    r[k] = float(v)
        return rows

    return JSONResponse(
        {
            "zone": zone_code,
            "label": label,
            "month": month,
            "class_type": class_type,
            "nodes": floats(nodes),
            "histogram": hist,
            "paths": floats(paths),
        }
    )


@app.get("/api/anchoring")
def anchoring(month: str = Query(...), class_type: str = Query("OnPeak")) -> JSONResponse:
    """Do bid prices track realized history more closely than PJM's simulation?"""
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT zone, n_paths, total_mw, corr_bid_realized, corr_bid_sim, anchoring_edge
            FROM v_bid_anchoring
            WHERE month = %s AND class_type = %s
            ORDER BY abs(anchoring_edge) DESC NULLS LAST
            """,
            (parse_month(month), class_type),
        )
        rows = [dict(r) for r in cur.fetchall()]
    for r in rows:
        for k, v in r.items():
            if hasattr(v, "is_finite"):
                r[k] = float(v)
    return JSONResponse({"month": month, "class_type": class_type, "zones": rows})
