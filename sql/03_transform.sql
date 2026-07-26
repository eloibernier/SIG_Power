-- staging -> dimensions and facts. Idempotent; safe to re-run after any ingest.

-- ============================== dim_pnode ==============================
-- A pnode_id can appear more than once when PJM re-issues it with new effective dates;
-- keep the most recent record.
TRUNCATE dim_pnode CASCADE;
INSERT INTO dim_pnode (pnode_id, pnode_name, pnode_name_norm, pnode_type, pnode_subtype,
                       zone, voltage_level, effective_date, termination_date, is_active)
SELECT DISTINCT ON (pnode_id)
       pnode_id,
       pnode_name,
       norm_name(pnode_name),
       pnode_type,
       pnode_subtype,
       nullif(btrim(zone, '"'), '') AS zone,
       nullif(voltage_level, '')    AS voltage_level,
       effective_date,
       termination_date,
       (termination_date IS NULL OR termination_date >= now()) AS is_active
FROM stg_pnode
WHERE pnode_id IS NOT NULL
ORDER BY pnode_id, effective_date DESC NULLS LAST;


-- ====================== fact_nodal_cong_monthly ========================
-- Unpivot ftr_cong_lmp's five FTR class types into rows. PJM's own naming is asymmetric:
-- the realized 24-hour column is "24hour_clmp" (h24_clmp here) but its simulated twin is
-- "lt_sim_clmp", not "lt_sim_24hour_clmp". Class labels match ftr_bids_mnt.class_type
-- exactly ('24H', not '24Hour') so the two facts join without a lookup table.
TRUNCATE fact_nodal_cong_monthly;
INSERT INTO fact_nodal_cong_monthly (pnode_name_norm, month, class_type, clmp_realized, clmp_sim)
SELECT norm_name(s.pnode_name),
       date_trunc('month', s.effective_day)::date,
       v.class_type,
       v.realized,
       v.sim
FROM stg_ftr_cong_lmp s
CROSS JOIN LATERAL (VALUES
    ('OnPeak',       s.onpeak_clmp,        s.lt_sim_onpeak_clmp),
    ('OffPeak',      s.offpeak_clmp,       s.lt_sim_offpeak_clmp),
    ('DailyOffPeak', s.dailyoffpeak_clmp,  s.lt_sim_dailyoffpeak_clmp),
    ('WkndOnPeak',   s.wkndonpeak_clmp,    s.lt_sim_wkndonpeak_clmp),
    ('24H',          s.h24_clmp,           s.lt_sim_clmp)
  ) AS v(class_type, realized, sim)
WHERE v.realized IS NOT NULL OR v.sim IS NOT NULL
ON CONFLICT (pnode_name_norm, month, class_type) DO NOTHING;


-- ============================= fact_ftr_bid =============================
-- A PJM monthly FTR auction sells the *balance of the planning period*, which runs June 1
-- to May 31 -- so the "JAN 2025 Auction" clears JAN through MAY 2025, and the "OCT 2025
-- Auction" clears OCT 2025 through MAY 2026. period_type carries only a month name, so the
-- delivery year has to be derived: an auction held in Jun-Dec that sells a Jan-May period
-- is selling into the following calendar year.
TRUNCATE fact_ftr_bid;
INSERT INTO fact_ftr_bid (market_name, auction_month, period_type, source_name_norm,
                          sink_name_norm, class_type, trade_type, hedge_type,
                          quoted_mw, quoted_price)
SELECT b.market_name,
       make_date(
         parsed.auction_year + CASE WHEN parsed.auction_mon >= 6 AND parsed.period_mon <= 5
                                    THEN 1 ELSE 0 END,
         parsed.period_mon, 1),
       b.period_type,
       norm_name(b.source_pnode_name),
       norm_name(b.sink_pnode_name),
       b.class_type,
       b.trade_type,
       b.hedge_type,
       b.quoted_mw,
       b.quoted_price
FROM stg_ftr_bid_mnt b
CROSS JOIN LATERAL (
  SELECT to_number(substring(b.market_name from '(\d{4})'), '9999')      AS auction_year,
         to_char(to_date(split_part(b.market_name, ' ', 1), 'MON'), 'MM')::int AS auction_mon,
         to_char(to_date(b.period_type, 'MON'), 'MM')::int               AS period_mon
) AS parsed
WHERE b.quoted_mw IS NOT NULL AND b.quoted_price IS NOT NULL;

ANALYZE dim_pnode;
ANALYZE fact_nodal_cong_monthly;
ANALYZE fact_ftr_bid;


-- =============================== checks ================================
\echo '=== row counts ==='
SELECT 'dim_pnode' AS t, count(*) FROM dim_pnode
UNION ALL SELECT 'fact_nodal_cong_monthly', count(*) FROM fact_nodal_cong_monthly
UNION ALL SELECT 'fact_ftr_bid', count(*) FROM fact_ftr_bid;

\echo '=== node-name join rate: congestion fact -> pnode dimension ==='
SELECT count(*)                                                       AS distinct_nodes,
       count(*) FILTER (WHERE d.pnode_id IS NOT NULL)                 AS matched,
       round(100.0 * count(*) FILTER (WHERE d.pnode_id IS NOT NULL) / count(*), 1) AS pct
FROM (SELECT DISTINCT pnode_name_norm FROM fact_nodal_cong_monthly) f
LEFT JOIN dim_pnode d ON d.pnode_name_norm = f.pnode_name_norm;

\echo '=== auction -> delivery month mapping (verify the planning-period rule) ==='
SELECT market_name, min(auction_month) AS first_delivery, max(auction_month) AS last_delivery,
       count(DISTINCT auction_month) AS n_months, count(*) AS bids
FROM fact_ftr_bid GROUP BY market_name ORDER BY 1;
