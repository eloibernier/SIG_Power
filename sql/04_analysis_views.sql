-- Analysis layer.
--
-- A note on units, because it drives the whole design here.
--
-- clmp_realized and clmp_sim are congestion prices in $/MWh. ftr_bids_mnt.quoted_price is
-- quoted per MW for the whole delivery period, so the two are not directly subtractable
-- without a class-hours conversion (and PJM's on-peak definition needs a NERC holiday
-- calendar to get right). Rather than bury an error in that conversion, the bid layer is
-- expressed as *correlation* between the bid and each congestion measure. Correlation is
-- invariant to the scale factor, so it answers the actual question -- do bidders track
-- realized history or PJM's simulation? -- without needing the conversion at all.

-- ======================================================================
-- v_node_gap: the core measure. Per node / month / FTR class, how far PJM's
-- PROMOD-simulated congestion sits from realized congestion.
-- ======================================================================
CREATE OR REPLACE VIEW v_node_gap AS
SELECT f.pnode_name_norm,
       d.pnode_name,
       d.pnode_id,
       d.zone,
       d.pnode_type,
       d.voltage_level,
       f.month,
       f.class_type,
       f.clmp_realized,
       f.clmp_sim,
       f.clmp_sim - f.clmp_realized AS gap
FROM fact_nodal_cong_monthly f
JOIN dim_pnode d ON d.pnode_name_norm = f.pnode_name_norm
WHERE f.clmp_realized IS NOT NULL
  AND f.clmp_sim IS NOT NULL;


-- ======================================================================
-- v_zone_gap: what the map draws. Mean gap is the choropleth value; the spread
-- columns matter just as much -- a zone whose nodes disagree internally is a zone
-- where a zonal FTR is a poor hedge for any particular node inside it.
-- ======================================================================
CREATE OR REPLACE VIEW v_zone_gap AS
SELECT zone,
       month,
       class_type,
       count(*)                                                          AS n_nodes,
       round(avg(gap)::numeric, 4)                                       AS mean_gap,
       round(stddev_samp(gap)::numeric, 4)                               AS sd_gap,
       round((percentile_cont(0.10) WITHIN GROUP (ORDER BY gap))::numeric, 4) AS p10_gap,
       round((percentile_cont(0.50) WITHIN GROUP (ORDER BY gap))::numeric, 4) AS median_gap,
       round((percentile_cont(0.90) WITHIN GROUP (ORDER BY gap))::numeric, 4) AS p90_gap,
       round(avg(clmp_realized)::numeric, 4)                             AS mean_realized,
       round(avg(clmp_sim)::numeric, 4)                                  AS mean_sim,
       count(*) FILTER (WHERE abs(gap) > 1.0)                            AS n_nodes_gap_over_1
FROM v_node_gap
WHERE zone IS NOT NULL
GROUP BY zone, month, class_type;


-- ======================================================================
-- v_path_expectation: collapse the bid stack to one row per traded path.
--
-- Obligations only. An FTR Option pays max(spread, 0) rather than the spread itself, so
-- its price carries optionality and is not comparable to a congestion difference.
-- Buy bids and sell offers straddle the (unpublished) clearing price, so both sides are
-- kept and a MW-weighted midpoint is offered as the proxy.
-- ======================================================================
CREATE OR REPLACE VIEW v_path_expectation AS
WITH sided AS (
  SELECT source_name_norm, sink_name_norm, class_type, auction_month, market_name,
         sum(quoted_mw) FILTER (WHERE trade_type = 'Buy')                       AS buy_mw,
         sum(quoted_mw * quoted_price) FILTER (WHERE trade_type = 'Buy')        AS buy_num,
         sum(quoted_mw) FILTER (WHERE trade_type = 'Sell')                      AS sell_mw,
         sum(quoted_mw * quoted_price) FILTER (WHERE trade_type = 'Sell')       AS sell_num,
         sum(quoted_mw)                                                         AS total_mw,
         sum(quoted_mw * quoted_price)                                          AS total_num,
         count(*)                                                               AS n_bids
  FROM fact_ftr_bid
  WHERE hedge_type = 'Obligation'
    AND quoted_mw > 0
  GROUP BY 1, 2, 3, 4, 5
)
SELECT source_name_norm,
       sink_name_norm,
       class_type,
       auction_month,
       market_name,
       n_bids,
       total_mw,
       buy_mw,
       sell_mw,
       round((buy_num  / nullif(buy_mw, 0))::numeric, 4)   AS buy_wavg_price,
       round((sell_num / nullif(sell_mw, 0))::numeric, 4)  AS sell_wavg_price,
       round((total_num / nullif(total_mw, 0))::numeric, 4) AS mw_wavg_price
FROM sided;


-- ======================================================================
-- v_path_divergence: the payoff question. For each traded path, what the market
-- quoted, what the path actually paid, and what PJM's simulation said it would pay.
-- Sign convention: an obligation source->sink pays congestion(sink) - congestion(source),
-- verified additively against da_hrl_lmps in etl/validate.py.
-- ======================================================================
CREATE OR REPLACE VIEW v_path_divergence AS
SELECT e.source_name_norm,
       e.sink_name_norm,
       src.pnode_name       AS source_name,
       snk.pnode_name       AS sink_name,
       snk.zone             AS sink_zone,
       src.zone             AS source_zone,
       e.class_type,
       e.auction_month,
       e.market_name,
       e.n_bids,
       e.total_mw,
       e.mw_wavg_price,
       e.buy_wavg_price,
       e.sell_wavg_price,
       round((cs.clmp_realized - co.clmp_realized)::numeric, 4) AS realized_spread,
       round((cs.clmp_sim      - co.clmp_sim)::numeric, 4)      AS sim_spread,
       round(((cs.clmp_sim - co.clmp_sim)
              - (cs.clmp_realized - co.clmp_realized))::numeric, 4) AS spread_gap
FROM v_path_expectation e
JOIN fact_nodal_cong_monthly co
  ON co.pnode_name_norm = e.source_name_norm
 AND co.month           = e.auction_month
 AND co.class_type      = e.class_type
JOIN fact_nodal_cong_monthly cs
  ON cs.pnode_name_norm = e.sink_name_norm
 AND cs.month           = e.auction_month
 AND cs.class_type      = e.class_type
LEFT JOIN dim_pnode src ON src.pnode_name_norm = e.source_name_norm
LEFT JOIN dim_pnode snk ON snk.pnode_name_norm = e.sink_name_norm
WHERE co.clmp_realized IS NOT NULL AND cs.clmp_realized IS NOT NULL
  AND co.clmp_sim      IS NOT NULL AND cs.clmp_sim      IS NOT NULL;


-- ======================================================================
-- v_bid_anchoring: the headline. Per sink zone, does the bid track realized
-- history more closely than PJM's simulation? Correlation, so the $/MWh vs
-- $/MW-period scale difference does not matter.
-- ======================================================================
CREATE OR REPLACE VIEW v_bid_anchoring AS
SELECT sink_zone                                        AS zone,
       auction_month                                    AS month,
       class_type,
       count(*)                                         AS n_paths,
       sum(total_mw)                                    AS total_mw,
       round(corr(mw_wavg_price, realized_spread)::numeric, 4) AS corr_bid_realized,
       round(corr(mw_wavg_price, sim_spread)::numeric, 4)      AS corr_bid_sim,
       round((corr(mw_wavg_price, realized_spread)
              - corr(mw_wavg_price, sim_spread))::numeric, 4)  AS anchoring_edge
FROM v_path_divergence
WHERE sink_zone IS NOT NULL
GROUP BY 1, 2, 3
HAVING count(*) >= 30;
