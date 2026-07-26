# PJM FTR Topology Divergence

PJM publishes two different congestion pictures for the same node and the same month: what
congestion **actually was**, and what its PROMOD simulation says it **would be** on a grid
with planned transmission upgrades. Both live in the same Data Miner 2 feed
(`ftr_cong_lmp`), one column apart.

This project loads both, maps where they diverge across PJM's transmission zones, and then
checks the FTR auction bid stack to see whether traders priced the difference in.

## Stack

- **PostGIS 16 / 3.4** in Docker — warehouse and all spatial work
- **Python** ETL against the PJM Data Miner 2 REST API (rate-limited to 6 req/min)
- **FastAPI + MapLibre GL JS** — self-hosted map, renders with **no external tiles** and no
  network access

## Quick start

```bash
cp .env.example .env          # then put your PJM_KEY in it (optional; see below)
docker compose up -d db
docker exec -i ftr_db psql -U ftr -d ftr -v ON_ERROR_STOP=1 -f /sql/01_schema.sql
python etl/ingest.py
python etl/load_geo.py
docker exec -i ftr_db psql -U ftr -d ftr -f /sql/02_zone_crosswalk.sql
docker exec -i ftr_db psql -U ftr -d ftr -f /sql/03_analysis_views.sql
docker compose up -d api      # http://localhost:8000
```

`PJM_KEY` is optional. Without it the ETL falls back to the anonymous subscription key that
Data Miner 2's own web app publishes in its client config — the same access an
unauthenticated browser gets, shared across all anonymous users at 6 requests/minute. A
personal key from <https://apiportal.pjm.com/> gets you that budget to yourself.

## Data sources

| Source | Role |
|---|---|
| `ftr_cong_lmp` | Nodal congestion LMP bucketed by FTR class type, realized **and** PROMOD-simulated |
| `ftr_bids_mnt` | Every bid into the monthly FTR auctions (164M rows total; 1.44M per auction) |
| `pnode` | Node master — carries the transmission zone for each of ~23.7k nodes |
| `da_hrl_lmps` | Hourly day-ahead LMPs, used only to validate the above |
| HIFLD Electric Retail Service Territories | Utility polygons, collapsed into PJM zones |

## A note on geography

PJM classifies the locations of nodes, substations and transmission lines as Critical
Energy Infrastructure Information and does not publish coordinates or shapefiles for them.
So there is no honest way to put a dot on a map at a node's true location.

What every node *does* carry is its transmission zone. PJM's zones follow utility service
territories almost exactly, and those territories are public (HIFLD). The map is therefore
a **zone choropleth**, built from a hand-checked crosswalk in `sql/02_zone_crosswalk.sql`
from PJM zone code to utility name. Within a zone, node-level detail is shown as
distribution rather than location.
