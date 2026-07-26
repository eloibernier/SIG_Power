# Findings

Data: PJM Data Miner 2. 30 months of nodal congestion (2024-01 to 2026-06), the full bid
stack from three monthly FTR auctions (JAN / JUL / OCT 2025), 21,237 pricing nodes, 20
transmission zones with geometry. 7,465,249 bids and 2,242,555 node-month-class congestion
records in Postgres.

---

## 0. What the data actually is — established before using it

`ftr_cong_lmp` publishes, for each node and month, congestion under two labels: an
unprefixed series (`onpeak_clmp`, `24hour_clmp`, …) and an `lt_sim_*` series that PJM
describes as "historical cLMPs adjusted by PROMOD production cost simulation, which
considers certain transmission upgrades."

The obvious reading is "realized vs modelled." **That reading is wrong**, and
`etl/validate.py` shows it. Reconciling against raw hourly day-ahead LMPs for July 2025:

| Node | Hourly on-peak congestion | Feed baseline | Difference |
|---|---:|---:|---:|
| BALA 13 KV LD1 | −7.077 | −1.230 | +5.847 |
| BGE | 18.797 | 24.140 | +5.343 |
| PEPCO | 26.725 | 16.810 | −9.915 |
| COMED | −8.507 | −4.930 | +3.577 |
| WESTERN HUB | 5.066 | 4.680 | −0.386 |

The errors are large and vary in sign, so this is not an hour-definition or rounding
artefact. **Both column families are modelled inputs to PJM's FTR credit calculator.**

What *did* validate: the sign convention. `total_lmp = system_energy + congestion + loss`
holds additively for 100.0% of 3,720 hours checked, so an FTR obligation from source to
sink pays `congestion(sink) − congestion(source)`.

So this project measures **topology versus topology** — the difference between two
congestion surfaces PJM publishes for the same grid, one of which includes planned
transmission upgrades. It makes no claim about what congestion actually turned out to be.
That is a narrower claim than the one I set out to make, and it is the one the data
supports.

---

## 1. The upgrade adjustment is near-zero almost always, and then it isn't

Across 30 months, the mean zonal adjustment sits within ±$0.05/MWh for most months. It is
not noise spread thinly — it is concentrated. July 2025 dominates the sample.

| Month (on-peak) | BGE | PEPCO | DOM | APS | PECO | COMED | AEP |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2025-04 | −0.01 | 0.00 | −0.01 | 0.00 | 0.00 | 0.00 | 0.00 |
| 2025-06 | +0.50 | +0.41 | −0.21 | −0.01 | +0.05 | −0.02 | −0.01 |
| **2025-07** | **+5.87** | **+4.31** | **+1.37** | **+1.14** | **−0.64** | **−1.20** | **−0.79** |
| 2025-08 | −0.12 | −0.08 | −0.51 | +0.30 | +0.45 | +0.01 | −0.17 |
| 2025-10 | 0.00 | 0.00 | −0.03 | 0.00 | +0.02 | −0.01 | −0.01 |

The adjustment scales with system stress. July 2025 was the tightest month in the
Mid-Atlantic in the sample — BGE baseline congestion ran $23.97/MWh against $12.38 in June
and $16.29 in August. The upgrade case does not shift a calm system; it re-prices a
stressed one.

## 2. Where it bites is geographically coherent — it widens the east–west spread

July 2025, on-peak, by zone:

| Zone | Baseline | Upgrade-adjusted | Adjustment | Nodes | Nodes beyond ±$1 |
|---|---:|---:|---:|---:|---:|
| BGE | 23.97 | 29.84 | **+5.87** | 263 | 255 |
| PEPCO | 16.24 | 20.55 | **+4.31** | 223 | 223 |
| DOM | 5.67 | 7.04 | +1.37 | 1,729 | 1,150 |
| APS | 1.34 | 2.48 | +1.14 | 880 | 338 |
| PECO | −4.47 | −5.11 | −0.64 | 444 | 84 |
| AEP | −2.66 | −3.45 | −0.79 | 2,858 | 1,962 |
| COMED | −5.12 | −6.33 | −1.20 | 1,421 | 1,411 |
| EKPC | −3.17 | −4.64 | −1.47 | 423 | 420 |

Every zone in the Baltimore–Washington–Northern Virginia corridor moves **up**; the western
zones move **down**. The upgrade case does not relieve the load pocket, it deepens the
price separation across it. A ComEd → BGE obligation carries a spread roughly **$7/MWh
wider** under the upgraded topology than under the baseline — on the same path, same month,
same class, from PJM's own two published surfaces.

That corridor is where the data-center load growth is.

## 3. Zonal hedges are weakest exactly where the adjustment is largest

The zone mean hides the within-zone spread, and the spread is not small. BGE in July 2025:
standard deviation 3.46, p10 +1.06, p90 +11.71. One BGE node — `WHITEROC 13.8 KV 110-2LD` —
moves from 30.62 to 46.47, an adjustment of **+15.85/MWh**, nearly three times its own zone's
mean.

So a zonal FTR is a materially different instrument from a nodal one in precisely the month
and place where the topology assumption matters most.

## 4. Bidders price off the baseline, not the upgrade case

Correlation between the MW-weighted bid price on a path and each congestion spread.
Correlation rather than a dollar difference because congestion is $/MWh while
`quoted_price` is per MW for the whole delivery period, and converting needs a
NERC-holiday-aware class-hours calendar — correlation is invariant to that scale factor.

| Delivery month (on-peak) | Paths | corr(bid, baseline) | corr(bid, upgraded) | Edge |
|---|---:|---:|---:|---:|
| 2025-03 | 29,075 | 0.4620 | 0.4620 | 0.0000 |
| **2025-07** | **73,128** | **0.4583** | **0.4002** | **+0.0581** |
| 2025-08 | 31,709 | 0.5772 | 0.5650 | +0.0121 |
| 2025-10 | 101,010 | 0.2779 | 0.2777 | +0.0002 |

In months where the two surfaces agree, the two correlations are identical — as they must
be. **The test only has power in July 2025, and there the bid stack tracks the baseline
more closely.** By sink zone that month: DOM +0.166 (0.350 vs 0.184, 9,058 paths), AEP
+0.165 (0.325 vs 0.160, 14,889 paths).

Effect size is modest and this is one month, so it is a signal worth pursuing rather than a
result. It is consistent with bidders anchoring on historical congestion where PJM's own
upgrade case says the grid is about to behave differently — but a single stressed month
cannot separate that from the simpler story that the baseline is just a better predictor.

---

## What I would do next

1. **Pin down the baseline.** It is a processed series, not raw outturn. Testing it against
   multi-year historical averages of the same calendar month would identify the lookback
   PJM's credit calculator actually uses.
2. **Widen the auction sample.** Three auctions gives one month with real signal.
   Twelve would show whether the July effect recurs at planning-period boundaries.
3. **Attribute to constraints.** `da_marginal_value` gives binding constraints and shadow
   prices by monitored facility. Joining the largest zonal adjustments to the constraints
   binding in those hours would name the specific facilities the upgrade case relieves.
4. **Add the DA-vs-RT basis.** `rt_da_monthly_lmps` carries both components in one row.
   FTRs settle on day-ahead congestion while the grid clears in real time; that gap is the
   other half of the divergence between nodal cost and payoff.

## Caveats

- Both congestion series are modelled. Neither is realized outturn. See §0.
- Zone geometry is built from utility service territories, not PJM's network model — PJM
  classifies node and line locations as CEII and publishes neither coordinates nor
  shapefiles. Zone boundaries are therefore approximate at the edges.
- RECO is a real PJM zone but absent from HIFLD's coverage of these states; it has no
  geometry and does not render.
- 99.0% of node names in the congestion feed resolve to the node dimension; 160 of 16,367
  do not and are excluded from zonal aggregates.
- PJM publishes the FTR **bid stack**, not clearing prices — those sit behind FTR Center
  authentication. `mw_wavg_price` is a proxy for where a path cleared, not the clearing
  price.
- `ftr_bids_mnt` is posted on a four-month delay, so this cannot be run on a live auction.
