-- PJM FTR topology-divergence warehouse.
-- Idempotent and non-destructive. `docker exec -i ftr_db psql -U ftr -d ftr -f /sql/01_schema.sql`

CREATE EXTENSION IF NOT EXISTS postgis;

-- Non-destructive by design: every object here is CREATE ... IF NOT EXISTS so the file can
-- be re-run against a loaded warehouse without wiping it. To rebuild from scratch, run
-- 00_reset.sql first -- that also clears ingest_log, which otherwise keeps claiming feeds
-- are loaded after their tables have been dropped.

-- PJM keys ftr_cong_lmp and ftr_bids_mnt on pnode_name, not pnode_id, and the names carry
-- internal runs of spaces ('02AMSTED138 KV  TR2'). Every join goes through this.
CREATE OR REPLACE FUNCTION norm_name(t text) RETURNS text
  LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT upper(regexp_replace(btrim(coalesce(t, '')), '\s+', ' ', 'g')) $$;


-- ========================= staging: mirrors the PJM feed shapes =========================

CREATE TABLE IF NOT EXISTS stg_pnode (
  pnode_id          bigint,
  pnode_name        text,
  pnode_type        text,
  pnode_subtype     text,
  zone              text,
  voltage_level     text,
  effective_date    timestamp,
  termination_date  timestamp
);

-- ftr_cong_lmp. Note the asymmetry in PJM's own column naming: the realized 24-hour column
-- is "24hour_clmp" but its simulated counterpart is "lt_sim_clmp", not "lt_sim_24hour_clmp".
-- Renamed to h24_clmp here because an identifier cannot start with a digit unquoted.
CREATE TABLE IF NOT EXISTS stg_ftr_cong_lmp (
  effective_day             date,
  terminate_day             date,
  pnode_name                text,
  offpeak_clmp              numeric,
  dailyoffpeak_clmp         numeric,
  onpeak_clmp               numeric,
  wkndonpeak_clmp           numeric,
  h24_clmp                  numeric,
  lt_sim_offpeak_clmp       numeric,
  lt_sim_dailyoffpeak_clmp  numeric,
  lt_sim_onpeak_clmp        numeric,
  lt_sim_wkndonpeak_clmp    numeric,
  lt_sim_clmp               numeric
);

CREATE TABLE IF NOT EXISTS stg_ftr_bid_mnt (
  market_name        text,
  period_type        text,
  source_pnode_name  text,
  sink_pnode_name    text,
  class_type         text,
  trade_type         text,
  quoted_mw          numeric,
  quoted_price       numeric,
  hedge_type         text
);

-- Hourly DA LMPs, pulled for a handful of nodes only. Validation input, not analysis input.
CREATE TABLE IF NOT EXISTS stg_da_hrl_lmp (
  datetime_beginning_ept  timestamp,
  pnode_id                bigint,
  pnode_name              text,
  type                    text,
  zone                    text,
  system_energy_price_da  numeric,
  total_lmp_da            numeric,
  congestion_price_da     numeric,
  marginal_loss_price_da  numeric
);

-- Raw HIFLD utility service territories, before the crosswalk collapses them into PJM zones.
CREATE TABLE IF NOT EXISTS stg_utility_territory (
  objectid    bigint,
  name        text,
  state       text,
  plan_area   text,
  cntrl_area  text,
  holding_co  text,
  geom        geometry(MultiPolygon, 4326)
);


-- ================================= dimensions =================================

CREATE TABLE IF NOT EXISTS dim_pnode (
  pnode_id          bigint PRIMARY KEY,
  pnode_name        text NOT NULL,
  pnode_name_norm   text NOT NULL,
  pnode_type        text,
  pnode_subtype     text,
  zone              text,
  voltage_level     text,
  effective_date    timestamp,
  termination_date  timestamp,
  is_active         boolean
);
CREATE INDEX IF NOT EXISTS idx_dim_pnode_norm ON dim_pnode (pnode_name_norm);
CREATE INDEX IF NOT EXISTS idx_dim_pnode_zone ON dim_pnode (zone);

-- One row per PJM transmission zone. geom is the union of that zone's HIFLD utility
-- territories; see 02_zone_crosswalk.sql for the hand-built mapping.
CREATE TABLE IF NOT EXISTS dim_zone (
  zone_code      text PRIMARY KEY,
  zone_label     text NOT NULL,
  utility_names  text[] NOT NULL,
  geom           geometry(MultiPolygon, 4326)
);
CREATE INDEX IF NOT EXISTS idx_dim_zone_geom ON dim_zone USING GIST (geom);

-- State outlines, so the map has context without any external tile server.
CREATE TABLE IF NOT EXISTS dim_state (
  state_abbr  text PRIMARY KEY,
  state_name  text,
  geom        geometry(MultiPolygon, 4326)
);
CREATE INDEX IF NOT EXISTS idx_dim_state_geom ON dim_state USING GIST (geom);


-- =================================== facts ===================================

-- ftr_cong_lmp unpivoted: one row per node / month / FTR class type, carrying the baseline
-- congestion LMP and its upgrade-adjusted (lt_sim_*) counterpart. This is the core table.
-- Column names kept as clmp_realized/clmp_sim for continuity; see etl/validate.py -- the
-- baseline is NOT realized outturn, both series are modelled.
CREATE TABLE IF NOT EXISTS fact_nodal_cong_monthly (
  pnode_name_norm  text NOT NULL,
  month            date NOT NULL,
  class_type       text NOT NULL,
  clmp_realized    numeric,
  clmp_sim         numeric,
  PRIMARY KEY (pnode_name_norm, month, class_type)
);
CREATE INDEX IF NOT EXISTS idx_fnc_month_class ON fact_nodal_cong_monthly (month, class_type);

CREATE TABLE IF NOT EXISTS fact_ftr_bid (
  bid_id             bigserial PRIMARY KEY,
  market_name        text,
  auction_month      date,
  period_type        text,
  source_name_norm   text,
  sink_name_norm     text,
  class_type         text,
  trade_type         text,
  hedge_type         text,
  quoted_mw          numeric,
  quoted_price       numeric
);
CREATE INDEX IF NOT EXISTS idx_fb_path  ON fact_ftr_bid (source_name_norm, sink_name_norm, class_type);
CREATE INDEX IF NOT EXISTS idx_fb_month ON fact_ftr_bid (auction_month);

-- Bookkeeping so a partial ingest can be resumed and row counts checked against the API.
CREATE TABLE IF NOT EXISTS ingest_log (
  feed         text NOT NULL,
  partition    text NOT NULL,
  rows_loaded  bigint,
  api_total    bigint,
  loaded_at    timestamptz DEFAULT now(),
  PRIMARY KEY (feed, partition)
);
