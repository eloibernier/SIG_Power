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

PAGE = 500  # well under the layer's maxRecordCount of 2000; geometry payloads are large


def _fetch_geojson(url: str, where: str, out_fields: str, offset: int) -> dict:
    resp = requests.get(
        url,
        params={
            "where": where,
            "outFields": out_fields,
            "returnGeometry": "true",
            "outSR": "4326",
            "f": "geojson",
            "resultOffset": offset,
            "resultRecordCount": PAGE,
        },
        timeout=180,
    )
    resp.raise_for_status()
    return resp.json()


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
    states = ", ".join(f"'{s}'" for s in PJM_STATES)
    where = f"STUSAB IN ({states})"

    with conn.cursor() as cur:
        cur.execute("TRUNCATE dim_state")

    payload = _fetch_geojson(TIGERWEB_STATES, where, "STUSAB,NAME", 0)
    rows = []
    for f in payload.get("features") or []:
        gj = _as_multipolygon(f.get("geometry"))
        if gj is None:
            continue
        p = f.get("properties", {})
        rows.append((p.get("STUSAB"), p.get("NAME"), gj))

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO dim_state (state_abbr, state_name, geom)
            VALUES (%s, %s, ST_Multi(ST_MakeValid(ST_GeomFromGeoJSON(%s))))
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
