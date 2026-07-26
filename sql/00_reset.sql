-- Deliberate teardown. Run this only when you want to re-ingest from scratch.
--
-- Kept separate from 01_schema.sql on purpose: the schema file has to be safe to re-run
-- against a loaded warehouse, so it must not drop anything. Dropping the staging tables
-- without also clearing ingest_log would leave the bookkeeping claiming feeds are loaded
-- when their tables are empty, and the next `python etl/ingest.py` would skip them all.
-- These two things belong in the same transaction, so they live in the same file.

BEGIN;

DROP TABLE IF EXISTS stg_pnode CASCADE;
DROP TABLE IF EXISTS stg_ftr_cong_lmp CASCADE;
DROP TABLE IF EXISTS stg_ftr_bid_mnt CASCADE;
DROP TABLE IF EXISTS stg_da_hrl_lmp CASCADE;
DROP TABLE IF EXISTS stg_utility_territory CASCADE;

DROP TABLE IF EXISTS dim_pnode CASCADE;
DROP TABLE IF EXISTS dim_zone CASCADE;
DROP TABLE IF EXISTS dim_state CASCADE;

DROP TABLE IF EXISTS fact_nodal_cong_monthly CASCADE;
DROP TABLE IF EXISTS fact_ftr_bid CASCADE;

DROP TABLE IF EXISTS ingest_log CASCADE;

COMMIT;

\echo 'Reset complete. Next: 01_schema.sql, then etl/ingest.py and etl/load_geo.py.'
