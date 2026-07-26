# PJM FTR Topology Divergence

PJM publishes two congestion surfaces for the same node and the same month: a **baseline**,
and a **PROMOD case adjusted for planned transmission upgrades**. Both live in the same Data
Miner 2 feed (`ftr_cong_lmp`), one column apart. The difference between them is PJM's own
estimate of what a set of transmission upgrades does to congestion at every pricing node.

This project loads both, maps where they diverge across PJM's transmission zones, and checks
the FTR auction bid stack to see whether traders price the difference in.

**Headline:** the adjustment is near-zero in ordinary months and then very large in stressed
ones. In July 2025 it moved Baltimore +$5.87/MWh and Pepco +$4.31 while ComEd went −$1.20 and
AEP −$0.79 — the upgrade case widens the east–west congestion spread rather than relieving
the Mid-Atlantic load pocket. See [notes/findings.md](notes/findings.md).

> **What this is not.** Both series are modelled inputs to PJM's FTR credit calculator.
> `etl/validate.py` reconciles them against raw hourly day-ahead LMPs and shows the baseline
> is *not* realized congestion — so this is a topology-versus-topology comparison, not
> model-versus-outturn. The sign convention *did* validate: energy + congestion + loss equals
> total LMP for 100% of hours tested.

## Stack

- **PostGIS 16 / 3.4** in Docker — warehouse and all spatial work
- **Python** ETL against the PJM Data Miner 2 REST API (throttled under PJM's 6 req/min cap)
- **FastAPI** + a **zero-dependency** front end — the Albers conic projection is ~20 lines of
  inline JS and the polygons come from PostGIS, so the page has no CDN, no tile server, and
  renders with the network off

## Quick start

```bash
cp .env.example .env          # then put your PJM_KEY in it (optional; see below)
docker compose up -d db
docker exec -i ftr_db psql -U ftr -d ftr -v ON_ERROR_STOP=1 -f /sql/01_schema.sql

python etl/ingest.py          # ~25 min cold; resumable, skips what is already logged
python etl/load_geo.py

docker exec -i ftr_db psql -U ftr -d ftr -f /sql/02_zone_crosswalk.sql
docker exec -i ftr_db psql -U ftr -d ftr -f /sql/03_transform.sql
docker exec -i ftr_db psql -U ftr -d ftr -f /sql/04_analysis_views.sql

python etl/validate.py        # characterises the feed against raw hourly LMPs
docker compose up -d api      # http://localhost:8080
```

`etl/ingest.py` records each completed `(feed, partition)` in `ingest_log` and skips it on
re-run, so an interrupted pull resumes rather than restarting. Row counts are asserted
against the API's own `totalRows`.

Every SQL file is safe to re-run against a loaded warehouse — `01_schema.sql` creates only
`IF NOT EXISTS`, and the transforms truncate and rebuild from staging. To rebuild from
scratch, run `sql/00_reset.sql` first: it drops the tables **and** clears `ingest_log` in one
transaction, because dropping staging without clearing the log leaves the bookkeeping
claiming feeds are loaded when their tables are empty — and the next ingest would then skip
everything and leave you with an empty warehouse.

`PJM_KEY` is optional. Without it the ETL falls back to the anonymous subscription key that
Data Miner 2's own web app publishes in its client config — the same access an
unauthenticated browser gets, shared across all anonymous users at 6 requests/minute. A
personal key from <https://apiportal.pjm.com/> gets you that budget to yourself.

## Data sources

| Source | Role |
|---|---|
| `ftr_cong_lmp` | Nodal congestion LMP bucketed by FTR class type — **baseline** and **upgrade-adjusted** (`lt_sim_*`) side by side |
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
