"""Load the map's geometry: utility service territories and state outlines.

PJM classifies node, substation and line locations as Critical Energy Infrastructure
Information and publishes neither coordinates nor shapefiles for them, so there is no
honest way to plot a node where it physically sits. What each node does carry is its
transmission zone, and PJM's zones follow utility service territories almost exactly.

Two public sources, both ArcGIS REST, both returning GeoJSON:
  * HIFLD Electric Retail Service Territories -> utility polygons, collapsed into PJM zones
    by the hand-built crosswalk in sql/02_zone_crosswalk.sql
  * Census TIGERweb states -> outlines so the map has context with no tile server

Neither is rate-limited the way PJM is, so this can run alongside etl/ingest.py.
"""

from __future__ import annotations

import json
import sys

import requests

from db import connect

HIFLD_URL = (
    "https://services3.arcgis.com/OYP7N6mAJJCyH6hd/arcgis/rest/services/"
    "Electric_Retail_Service_Territories_HIFLD/FeatureServer/0/query"
)
TIGERWEB_STATES = (
    "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/State_County/"
    "MapServer/0/query"
)

# PJM's footprint is all or part of these 13 states plus DC. Pulling the whole footprint
# rather than a name list means the crosswalk can be checked against what actually exists.
PJM_STATES = ["PA", "NJ", "MD", "DE", "DC", "VA", "WV", "OH", "IN", "IL", "KY", "MI", "NC", "TN"]

# State outlines cover the whole lower 48, not just the PJM footprint: the map needs national
# context so you can see how small a slice of the country PJM actually is. Alaska, Hawaii and
# the territories are dropped -- an Albers conic centred on PJM cannot show them sensibly.
NON_CONUS = ["AK", "HI", "PR", "VI", "GU", "AS", "MP", "UM"]

PAGE = 500  # well under the layer's maxRecordCount of 2000; geometry payloads are large


def _fetch_geojson(
    url: str,
    where: str,
    out_fields: str,
    offset: int,
    page: int = PAGE,
    simplify: float | None = None,
) -> dict:
    """One page of GeoJSON from an ArcGIS REST layer.

    `simplify` maps to maxAllowableOffset, which generalises geometry *server-side* in
    degrees. State outlines at full census resolution are far more detail than a map this
    size can show, and asking for all fifty at once without it overruns the service and
    comes back as something that is not JSON.
    """
    params = {
        "where": where,
        "outFields": out_fields,
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "geojson",
        "resultOffset": offset,
        "resultRecordCount": page,
    }
    if simplify is not None:
        params["maxAllowableOffset"] = simplify

    resp = requests.get(url, params=params, timeout=180)
    resp.raise_for_status()
    try:
        return resp.json()
    except ValueError:
        raise RuntimeError(
            f"{url} returned non-JSON ({len(resp.content)} bytes). "
            f"Try a smaller page or a coarser simplify. First 200 chars: {resp.text[:200]!r}"
        )


def _as_multipolygon(geom: dict | None) -> str | None:
    """PostGIS columns are typed MultiPolygon; ArcGIS hands back either."""
    if not geom:
        return None
    if geom.get("type") == "Polygon":
        geom = {"type": "MultiPolygon", "coordinates": [geom["coordinates"]]}
    if geom.get("type") != "MultiPolygon":
        return None
    return json.dumps(geom)


def load_utilities(conn) -> int:
    states = ", ".join(f"'{s}'" for s in PJM_STATES)
    where = f"STATE IN ({states})"
    fields = "OBJECTID,NAME,STATE,PLAN_AREA,CNTRL_AREA,HOLDING_CO"

    with conn.cursor() as cur:
        cur.execute("TRUNCATE stg_utility_territory")

    offset, total = 0, 0
    while True:
        payload = _fetch_geojson(HIFLD_URL, where, fields, offset)
        feats = payload.get("features") or []
        if not feats:
            break

        rows = []
        for f in feats:
            gj = _as_multipolygon(f.get("geometry"))
            if gj is None:
                continue
            p = f.get("properties", {})
            rows.append(
                (p.get("OBJECTID"), p.get("NAME"), p.get("STATE"), p.get("PLAN_AREA"),
                 p.get("CNTRL_AREA"), p.get("HOLDING_CO"), gj)
            )

        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO stg_utility_territory
                  (objectid, name, state, plan_area, cntrl_area, holding_co, geom)
                VALUES (%s, %s, %s, %s, %s, %s,
                        ST_Multi(ST_MakeValid(ST_GeomFromGeoJSON(%s))))
                """,
                rows,
            )
        conn.commit()
        total += len(rows)
        print(f"  utilities: {total}", flush=True)

        if not payload.get("properties", {}).get("exceededTransferLimit") and len(feats) < PAGE:
            break
        offset += len(feats)

    return total


def load_states(conn) -> int:
    """All lower-48 states, flagged for whether PJM operates in them."""
    excluded = ", ".join(f"'{s}'" for s in NON_CONUS)
    where = f"STUSAB NOT IN ({excluded})"

    with conn.cursor() as cur:
        cur.execute("TRUNCATE dim_state")

    rows, offset = [], 0
    while True:
        payload = _fetch_geojson(
            TIGERWEB_STATES, where, "STUSAB,NAME", offset, page=10, simplify=0.02
        )
        feats = payload.get("features") or []
        if not feats:
            break
        for f in feats:
            gj = _as_multipolygon(f.get("geometry"))
            if gj is None:
                continue
            p = f.get("properties", {})
            abbr = p.get("STUSAB")
            rows.append((abbr, p.get("NAME"), abbr in PJM_STATES, gj))
        if len(feats) < 10:
            break
        offset += len(feats)

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO dim_state (state_abbr, state_name, in_pjm, geom)
            VALUES (%s, %s, %s, ST_Multi(ST_MakeValid(ST_GeomFromGeoJSON(%s))))
            ON CONFLICT (state_abbr) DO NOTHING
            """,
            rows,
        )
    conn.commit()
    return len(rows)


def main() -> int:
    with connect() as conn:
        n_state = load_states(conn)
        print(f"[ok] dim_state: {n_state} states")

        n_util = load_utilities(conn)
        print(f"[ok] stg_utility_territory: {n_util} utility territories")

        # Surface the candidates for the crosswalk rather than guessing at names.
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT name, state, plan_area
                FROM stg_utility_territory
                WHERE plan_area ILIKE '%PJM%'
                ORDER BY ST_Area(geom::geography) DESC
                """
            )
            print("\n=== utilities whose PLAN_AREA names PJM ===")
            for name, state, plan in cur.fetchall():
                print(f"  {name[:44]:<44} {state:<3} {plan}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
