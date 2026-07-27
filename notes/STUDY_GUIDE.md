# PJM FTR Topology Divergence — Complete Study Guide

**Project:** `github.com/eloibernier/SIG_Power`
**Built for:** Susquehanna International Group — Power Analyst interview, 29 July 2026
**Purpose of this document:** everything the project does, the mathematics underneath it, why
it matters commercially, and how it was engineered. Written to be studied, not skimmed.

---

## Table of contents

**Part 0 — [Executive summary](#part-0--executive-summary)**
**Part I — [The domain: how power markets create the thing we measured](#part-i--the-domain)**
**Part II — [The mathematics](#part-ii--the-mathematics)**
**Part III — [The data: what PJM publishes and what it withholds](#part-iii--the-data)**
**Part IV — [Data management practice](#part-iv--data-management-practice)** ← *the largest section*
**Part V — [The analysis and what it found](#part-v--the-analysis-and-what-it-found)**
**Part VI — [Where the value is: trading and risk](#part-vi--where-the-value-is)**
**Part VII — [Limitations, failures, and next steps](#part-vii--limitations-failures-and-next-steps)**
**Appendix A — [Interview question bank](#appendix-a--interview-question-bank)**
**Appendix B — [Glossary](#appendix-b--glossary)**
**Appendix C — [Command reference](#appendix-c--command-reference)**

---

# Part 0 — Executive summary

## What was built

A reproducible data pipeline and interactive map that compares **two congestion surfaces PJM
publishes for the same grid**, one of which incorporates planned transmission upgrades, and
then tests whether the FTR auction bid stack prices the difference.

| Layer | What it is |
|---|---|
| **Ingest** | Rate-limited, resumable Python ETL against the PJM Data Miner 2 REST API |
| **Warehouse** | PostgreSQL 16 + PostGIS 3.4 in Docker — 2.7 GB, 9.7M fact rows |
| **Model** | Staging → dimensions → facts → analysis views |
| **Validation** | Independent reconciliation against raw hourly LMPs |
| **Presentation** | FastAPI + a zero-dependency SVG map (Albers conic, no CDN, no tile server) |

## The headline number

For **July 2025, on-peak**, PJM's upgrade-adjusted congestion case sits:

| Zone | Baseline $/MWh | Upgrade-adjusted $/MWh | Difference |
|---|---:|---:|---:|
| **BGE** (Baltimore) | 23.97 | 29.84 | **+5.87** |
| **PEPCO** (Washington DC) | 16.24 | 20.55 | **+4.31** |
| **DOM** (Virginia) | 5.67 | 7.04 | +1.37 |
| **APS** (Allegheny) | 1.34 | 2.48 | +1.14 |
| PECO (Philadelphia) | −4.47 | −5.11 | −0.64 |
| AEP (Ohio/WV/IN) | −2.66 | −3.45 | −0.79 |
| **COMED** (Chicago) | −5.12 | −6.33 | **−1.20** |
| EKPC (Kentucky) | −3.17 | −4.64 | −1.47 |

**The east goes up, the west goes down.** The upgrade case does not relieve the Mid-Atlantic
load pocket — it *widens* the east–west congestion spread across it. A ComEd → BGE FTR
obligation is worth roughly **$7.08/MWh more** under the modelled topology than the baseline,
which over July 2025's 352 on-peak hours is **≈ $2,491 per MW held**.

## The three claims, ranked by how well they are established

1. **Established.** The two published congestion surfaces differ, the difference is
   geographically coherent, and it concentrates in stressed months. This is arithmetic on
   published data.
2. **Established with a caveat.** Within-zone dispersion is largest where the adjustment is
   largest. In BGE the same month spans **+15.85** (`WHITEROC 13.8 KV`) to **−2.84**
   (`CONASTONE 500 KV`) — an 18.7 $/MWh range inside one zone.
3. **A lead, not a result.** Bids track the baseline more than the upgrade case (0.458 vs
   0.400 correlation overall in July 2025; +0.166 in DOM, +0.165 in AEP). One month, modest
   effect size.

## What the project explicitly does *not* claim

Neither published series is realized outturn. This was tested, not assumed — see
[Part IV §7](#7-validation-the-part-that-changed-the-project). The comparison is
**topology versus topology**, which is precisely the job description's phrasing, and a
narrower claim than the one the project set out to make.

---

# Part I — The domain

*If you already know LMP and FTR mechanics cold, skip to [Part II](#part-ii--the-mathematics).*

## 1. Why electricity prices differ by location

Electricity obeys physics, not contracts. Power injected at a generator does not flow along
the path someone sold it on — it distributes across every parallel path according to
impedance (Kirchhoff's laws). Transmission lines have thermal, voltage and stability limits.
When the cheapest dispatch would overload a line, the system operator must **redispatch**:
back down cheap generation behind the constraint and start more expensive generation in
front of it.

The cost of that redispatch is **congestion**, and it is location-specific. The price of
energy at each of PJM's ~14,000 pricing nodes is the **Locational Marginal Price (LMP)** —
the marginal cost of serving one more MW of load *at that specific node*.

## 2. The three components of LMP

PJM decomposes every LMP into three additive parts:

```
LMP_i  =  λ  +  C_i  +  L_i
          ↑     ↑       ↑
          |     |       marginal loss component at node i
          |     congestion component at node i
          system energy price (the same everywhere)
```

**This identity was verified, not assumed**: over 3,720 node-hours pulled from
`da_hrl_lmps`, `system_energy_price_da + congestion_price_da + marginal_loss_price_da`
equals `total_lmp_da` for **100.0%** of rows. That matters because the sign convention of
`C_i` determines the sign of every FTR payoff computed downstream.

Only `C_i` matters for this project. FTRs settle on the congestion component alone.

## 3. Day-ahead and real-time

PJM runs two settlement markets:

- **Day-Ahead (DA):** a financially binding forward auction cleared the day before
  operations, on a *forecast* network model and forecast load.
- **Real-Time (RT):** balancing settlement at five-minute intervals against what actually
  happened.

**FTRs settle exclusively on day-ahead congestion.** This is not a detail — it means an FTR
is a hedge against the *day-ahead market's model of the grid*, not against physical reality.
Anyone hedging physical delivery with FTRs retains DA-to-RT basis risk.

## 4. What an FTR actually is

A **Financial Transmission Right** is a financial contract defined by:

| Attribute | Meaning |
|---|---|
| **Source** | Point of injection (a node, hub, or zone aggregate) |
| **Sink** | Point of withdrawal |
| **MW** | Quantity |
| **Class type** | Which hours it covers — OnPeak, OffPeak, DailyOffPeak, WkndOnPeak, 24H |
| **Hedge type** | **Obligation** (pays the spread, positive or negative) or **Option** (pays only when positive) |
| **Period** | The delivery month(s) |

It entitles the holder to the **day-ahead congestion price difference between sink and
source**, summed over every hour in the class, times the MW held. It conveys no physical
right to move power and no physical delivery obligation.

**Who holds them, and why:**

- **Load-serving entities** hedge the congestion cost of delivering from generation to load.
  A utility buying at a hub and serving load at its own nodes is exposed to that spread.
- **Generators** hedge the risk of being locked behind a constraint and receiving a
  depressed nodal price.
- **Proprietary traders** — a desk like SIG's — take positions on where congestion will
  materialise, without any physical asset. The FTR is a pure view on grid topology, outage
  scheduling, load growth, and fuel prices.

**Options versus obligations matters for the maths.** An obligation is linear in the spread;
an option is a call on the spread with a strike of zero. Only obligations are directly
comparable to a congestion difference, which is why every path calculation in this project
filters `hedge_type = 'Obligation'`. In the loaded data, obligations are 96% of bids by
count and 79% by MW.

## 5. How FTRs are sold

PJM runs several auction types. This project uses the **monthly Balance-of-Planning-Period
auctions**.

A critical structural fact, discovered from the data rather than the documentation: **PJM's
planning period runs 1 June to 31 May, and a monthly auction sells the entire remainder of
that period, not just the next month.**

| Auction | Delivery months sold | Bids in our data |
|---|---|---:|
| JAN 2025 | Jan–May 2025 (5) | 1,439,469 |
| JUL 2025 | Jul 2025–May 2026 (11) | 3,429,029 |
| OCT 2025 | Oct 2025–May 2026 (8) | 2,596,751 |

The bid records carry `period_type` as a bare month name (`'JAN'`, `'JUL'`) with no year. The
delivery year has to be derived:

```
delivery_year = auction_year + (1 if auction_month ≥ 6 and period_month ≤ 5 else 0)
```

Getting this wrong silently misaligns every bid with the wrong month of congestion data —
a class of error that produces plausible-looking output and no exception.

---

# Part II — The mathematics

## 1. Where the congestion component comes from

The system operator solves a security-constrained economic dispatch. In its linearised
(DC-OPF) form:

$$
\min_{g} \sum_i c_i(g_i)
\quad \text{s.t.} \quad
\sum_i g_i = \sum_i d_i \;\; (\lambda), \qquad
\sum_i \mathrm{GSF}_{k,i}\,(g_i - d_i) \le F_k \;\; (\mu_k \ge 0)
$$

where

- $g_i$ = generation at node $i$, $d_i$ = load at node $i$
- $\lambda$ = dual of the system energy balance → **the system energy price**
- $\mathrm{GSF}_{k,i}$ = **generation shift factor**: the fraction of a 1 MW injection at
  node $i$ (withdrawn at the reference bus) that flows on constrained element $k$
- $F_k$ = limit on element $k$
- $\mu_k$ = dual of that constraint → **the shadow price**, the $/MWh saving from relaxing
  the limit by 1 MW

The congestion component of LMP at node $i$ is then a **linear combination of binding
constraint shadow prices, weighted by shift factors**:

$$
\boxed{\;C_i \;=\; -\sum_{k \in \mathcal{B}} \mathrm{GSF}_{k,i}\;\mu_k\;}
$$

where $\mathcal{B}$ is the set of binding constraints. (Sign conventions on $\mu$ and GSF
vary between ISOs; PJM reports $C_i$ such that the three components sum additively to LMP,
which is what was verified empirically.)

### Why this equation is the whole point of the project

Look at what $C_i$ depends on:

- $\mu_k$ — **which constraints bind, and how hard.** A function of load, fuel prices,
  outages, and generation mix.
- $\mathrm{GSF}_{k,i}$ — **the shift factors.** These are determined *entirely by network
  topology*: line impedances, which lines exist, their ratings, and the contingency set.

**Change the topology and you change every shift factor, and therefore the entire congestion
surface across all 14,000 nodes simultaneously.** That is why "compare different electricity
topologies to identify differences that could lead to divergence between nodal costs and
payoffs" is a coherent and important question — and why a project that quantifies it has
something to say.

PJM publishes $\mu_k$ directly in the `da_marginal_value` feed (by monitored facility and
contingency). It does not publish $\mathrm{GSF}$ — the shift-factor matrix *is* the network
model, and it is confidential.

## 2. FTR payoff

For an **obligation** from source $s$ to sink $k$, quantity $q$ MW, over hour set $H$:

$$
\boxed{\;\Pi_{\text{obl}} \;=\; q \sum_{h \in H}\bigl(C_{k,h} - C_{s,h}\bigr)\;}
$$

For an **option**, the negative side is truncated:

$$
\Pi_{\text{opt}} \;=\; q \sum_{h \in H}\max\bigl(0,\; C_{k,h} - C_{s,h}\bigr)
$$

An obligation is linear and symmetric — it can lose money. An option is a strip of hourly
calls on the congestion spread struck at zero, which is why it clears at a premium and why
its price is not comparable to a raw spread.

**Profit and loss** for a position bought at auction clearing price $P$ (per MW for the
period):

$$
\text{P\&L} \;=\; \Pi - qP \;=\; q\left[\sum_{h \in H}\bigl(C_{k,h} - C_{s,h}\bigr) - P\right]
$$

The bracketed term is the quantity an FTR trader is actually forecasting: **realized
congestion spread minus what the market charged for it.**

## 3. The auction: a simultaneous feasibility test

FTRs are not cleared pairwise. PJM solves:

$$
\max_{x} \sum_b p_b x_b
\quad\text{s.t.}\quad
\sum_b x_b\,\mathrm{GSF}_{k,\,\text{sink}(b)} - x_b\,\mathrm{GSF}_{k,\,\text{source}(b)} \le F_k \;\;\forall k,
\qquad 0 \le x_b \le q_b
$$

The awarded portfolio must be **simultaneously feasible**: if every FTR were exercised as a
physical schedule at once, no modelled constraint would be violated. The clearing price of a
path is the dual of that programme — again a shift-factor-weighted combination of
constraint shadow prices.

**Topology enters twice**, and this is the crux:

1. It determines the **network model in the auction** (what can be sold, and at what price).
2. It determines the **realized congestion** (what gets paid out).

If those two topologies differ — because upgrades come into service, or outages hit — the
auction sells a portfolio priced on one grid that pays out on another.

## 4. Revenue adequacy

PJM funds FTR payouts from day-ahead congestion rent — the surplus it collects because load
pays more than generation receives when constraints bind:

$$
\text{Congestion rent}_h \;=\; \sum_i \bigl(d_{i,h} - g_{i,h}\bigr) C_{i,h} \;=\; \sum_{k}\mu_{k,h} F_k
$$

The system is **revenue adequate** when

$$
\sum_{\text{FTRs}} \Pi \;\le\; \sum_h \sum_k \mu_{k,h} F_{k,h}
$$

The SFT is designed to guarantee this **if the delivered network matches the auction model**.
When the real grid has *less* capacity than the model assumed — an unplanned outage, a
derate — rent collected falls short of obligations owed and PJM **prorates payouts**.

This is a first-order risk that a topology comparison speaks to directly: the same
divergence that changes what your FTR is worth also changes whether PJM can pay you in full.

## 5. The metric this project computes

PJM's `ftr_cong_lmp` feed publishes, for each node $i$, month $m$, and class $c$, two
congestion series: a baseline $C^{\text{base}}$ and a PROMOD case adjusted for planned
transmission upgrades, $C^{\text{upg}}$.

**Node-level topology gap:**

$$
\boxed{\;G(i,m,c) \;=\; C^{\text{upg}}(i,m,c) - C^{\text{base}}(i,m,c)\;}
$$

**Path spread gap** — how much the topology moves an FTR path:

$$
\boxed{\;\Delta S(s\!\to\!k,m,c) \;=\; \bigl[C^{\text{upg}}_k - C^{\text{upg}}_s\bigr] - \bigl[C^{\text{base}}_k - C^{\text{base}}_s\bigr] \;=\; G(k) - G(s)\;}
$$

The path gap is simply **the difference of the two node gaps** — the shared system energy
and loss terms cancel, and so does anything common to both nodes. This is why a zonal
choropleth of $G$ is directly readable as a path map: any two zones you pick, the vertical
distance between their colours *is* the spread change.

**Dollar value per MW held:**

$$
V(s\!\to\!k,m,c) \;=\; \Delta S(s\!\to\!k,m,c)\;\times\;H(m,c)
$$

where $H(m,c)$ is the number of hours in that class and month.

### Worked example — ComEd → BGE, July 2025, on-peak

$$
\Delta S = G(\text{BGE}) - G(\text{COMED}) = (+5.8748) - (-1.2023) = +7.0771\ \text{\$/MWh}
$$

July 2025 on-peak hours: weekdays, HE 0800–2300, excluding 4 July (a NERC holiday):

$$
H = 22\ \text{days} \times 16\ \text{h} = 352\ \text{h}
$$

$$
V = 7.0771 \times 352 = \mathbf{\$2{,}491\ \text{per MW}}
$$

On a 100 MW position that is **$249,114 for one month** of difference between two topology
assumptions — for a contract whose entire economics is the congestion spread.

### Hours per class, July 2025

Computed from a NERC-holiday-aware calendar, and cross-checked against the 352 on-peak hours
the validator independently counted from hourly LMP timestamps:

| Class | Hours | Definition |
|---|---:|---|
| OnPeak | 352 | Weekdays HE 0800–2300, excl. NERC holidays |
| DailyOffPeak | 176 | Weekday hours outside the peak window |
| WkndOnPeak | 144 | Weekend/holiday HE 0800–2300 |
| OffPeak | 216 | All non-weekday-peak hours |
| 24H | 744 | Every hour in the month |

## 6. Why the bid analysis uses correlation, not dollars

This is a small piece of mathematical care worth understanding, because it is the kind of
thing an interviewer will probe.

`ftr_cong_lmp` is in **$/MWh**. `ftr_bids_mnt.quoted_price` is in **$ per MW for the whole
delivery period**. They differ by the factor $H(m,c)$ — which requires an exact
NERC-holiday-aware calendar to compute, and a silent error there would corrupt every
comparison.

Correlation avoids the conversion entirely. For any constant $a>0$:

$$
\mathrm{corr}(aX,\,Y) \;=\; \mathrm{corr}(X,\,Y)
$$

Within a fixed $(m,c)$ group, $H$ **is** constant, so

$$
\mathrm{corr}\!\left(\text{quoted\_price},\, S\right) \;=\; \mathrm{corr}\!\left(\tfrac{\text{quoted\_price}}{H},\, S\right)
$$

The comparison of interest —

$$
\text{anchoring edge} \;=\; \mathrm{corr}\bigl(\text{bid},\,S^{\text{base}}\bigr) - \mathrm{corr}\bigl(\text{bid},\,S^{\text{upg}}\bigr)
$$

— is therefore **exactly invariant** to the missing conversion, provided the grouping fixes
$(m,c)$. That is why `v_bid_anchoring` groups by `zone, month, class_type` and not by zone
alone. Aggregating across months would mix different $H$ values and break the invariance.

## 7. Basis risk: why zonal hedges leak

An LSE at node $k$ hedging with a **zonal** FTR to zone $Z$ carries residual exposure:

$$
\varepsilon_k \;=\; C_k - C_Z
$$

The hedge is only as good as $\mathrm{Var}(\varepsilon_k)$ is small. The **within-zone
standard deviation** of the node gap is a direct measure of how much a topology change
disturbs that residual.

For BGE in July 2025 on-peak: **sd = 3.46**, p10 **+1.06**, p90 **+11.71**, with individual
nodes spanning:

| Node | kV | Baseline | Upgrade-adjusted | Gap |
|---|---:|---:|---:|---:|
| `WHITEROC 13.8 KV 110-2LD` | 13.8 | 30.62 | 46.47 | **+15.85** |
| `WESMSTER 13.8 KV 110-3LD` | 13.8 | 30.62 | 46.44 | +15.82 |
| `WHITEROC 115 KV COL PIPE` | 115 | 30.62 | 46.41 | +15.79 |
| `BAGLEY 34 KV 230-1LD` | 34 | 28.34 | 28.31 | −0.03 |
| `CONASTONE 500 KV` | 500 | −5.34 | −8.18 | **−2.84** |

**An 18.7 $/MWh range inside a single zone in a single month.** A zonal FTR is a materially
different instrument from a nodal one exactly when and where topology matters most — and the
zone mean (+5.87) conceals all of it.

Note the physical intuition in that table: the 500 kV node (`CONASTONE`, a major transmission
substation) moves *down*, while the 13.8 kV distribution-level load nodes move sharply *up*.
The upgrade case changes how power reaches load pockets, not the bulk backbone.

---

# Part III — The data

## 1. Sources

| Source | Feed | Rows | Role |
|---|---|---:|---|
| PJM Data Miner 2 | `ftr_cong_lmp` | 448,850 | **Core.** Nodal congestion by FTR class, baseline + upgrade-adjusted |
| PJM Data Miner 2 | `ftr_bids_mnt` | 7,465,249 | **Core.** Every bid into 3 monthly auctions (164M rows exist in total) |
| PJM Data Miner 2 | `pnode` | 23,711 | Node master; carries transmission zone |
| PJM Data Miner 2 | `da_hrl_lmps` | 3,720 | **Validation only.** Raw hourly DA LMPs for 5 nodes |
| HIFLD (ArcGIS) | Electric Retail Service Territories | 721 | Utility polygons → PJM zones |
| Census TIGERweb | States | 49 | National context for the map |

## 2. API access and the rate limit

Data Miner 2 requires a subscription key. Its own web application publishes an anonymous key
in its client config at `https://dataminer2.pjm.com/config/settings.json` — the same access
an unauthenticated browser gets. **PJM caps non-member users at 6 requests/minute.**

The client throttles to **5.5 requests/minute** — deliberately under the ceiling — with a
shared token bucket, exponential backoff on 429/5xx, and per-page checkpointing. A cold load
is ~25 minutes, dominated by the bid stack.

**Design consequence:** at 50,000 rows per request, the rate limit is the binding constraint
on scope, not storage or compute. That is what drove taking 3 auctions rather than 12 — and
`ftr_bids_mnt` accepts **no node-level filter** (`sink_pnode_name` is rejected as an invalid
filter field), so geography cannot reduce the download. Only auction count can.

## 3. What PJM will not publish, and how the map works anyway

> PJM classifies the location of nodes, substations and transmission lines as **Critical
> Energy Infrastructure Information (CEII)**. It publishes no coordinates and no shapefiles
> for any of them.

There is therefore **no honest way to plot a node at its true location.** Any project that
shows you PJM nodes as dots on a map either bought proprietary data or invented positions.

What every node *does* carry is its **transmission zone**. PJM's zones follow utility service
territories almost exactly, and those territories are public via HIFLD. So the map is a
**zone choropleth** built from a hand-verified crosswalk:

```
pnode.zone  →  utility NAME(s)  →  HIFLD polygon  →  ST_Union  →  dim_zone.geom
```

All 27 utility names in the crosswalk matched HIFLD records. Several zones are unions of
multiple operating companies:

| Zone | Utilities unioned |
|---|---|
| AEP | Ohio Power, Appalachian Power, Indiana Michigan Power, Kentucky Power, Wheeling Power |
| ATSI | Ohio Edison, Cleveland Electric Illuminating, Toledo Edison, Pennsylvania Power |
| APS | Monongahela Power, West Penn Power, Potomac Edison |
| DEOK | Duke Energy Ohio, Duke Energy Kentucky |
| PPL | PPL Electric Utilities, UGI Utilities |

**RECO** (Rockland Electric) is a real PJM zone with ~24 nodes but does not appear in HIFLD's
coverage of these states. It carries **no geometry and does not render** — left visibly
absent rather than drawn somewhere invented. Choosing to show a gap rather than a guess is a
data-integrity decision, and a defensible one to be asked about.

## 4. What is not available at all

**FTR auction clearing prices** sit behind `connect.pjm.com` authentication (returns HTTP
403). PJM publishes the **bid stack**, not the clearing prices. Every path calculation here
uses `mw_wavg_price` — the MW-weighted average quoted price — as a *proxy*.

This should be stated plainly rather than glossed. The counter-argument worth making: the
bid stack is arguably the richer object, because it is the entire demand and supply curve
rather than the single point where they crossed. But it is not the clearing price.

---

# Part IV — Data management practice

*This is the section to know cold. Everything here is a decision that was made, tested, and
in two cases corrected after it failed.*

## 1. Architecture: three layers, one direction

```
   PJM Data Miner 2 API                 HIFLD / TIGERweb (ArcGIS)
            │                                     │
            ▼                                     ▼
   ┌──────────────────────────────────────────────────────────┐
   │ STAGING — mirrors each source's shape exactly, no logic   │
   │ stg_pnode · stg_ftr_cong_lmp · stg_ftr_bid_mnt            │
   │ stg_da_hrl_lmp · stg_utility_territory                    │
   └──────────────────────────────────────────────────────────┘
            │  sql/03_transform.sql  (typed, normalised, derived)
            ▼
   ┌──────────────────────────────────────────────────────────┐
   │ DIMENSIONS            │  FACTS                            │
   │ dim_pnode  (21,237)   │  fact_nodal_cong_monthly (2.24M)  │
   │ dim_zone   (21)       │  fact_ftr_bid            (7.47M)  │
   │ dim_state  (49)       │                                   │
   └──────────────────────────────────────────────────────────┘
            │  sql/04_analysis_views.sql
            ▼
   v_node_gap → v_zone_gap → v_path_expectation → v_path_divergence → v_bid_anchoring
            │
            ▼
   FastAPI (read-only)  →  SVG choropleth
```

**Why staging is separate from facts.** Staging holds the feed exactly as PJM shaped it —
same column names, same nulls, no interpretation. This means:

- A re-transform never requires re-downloading. At 5.5 requests/minute, that is the
  difference between 25 minutes and 20 seconds when a modelling decision changes.
- The raw response is auditable. When the validation refuted an assumption, the untouched
  staging data was still there to re-interpret.
- Transform bugs are recoverable; ingest bugs are expensive. Keeping them in separate layers
  keeps the expensive one rare.

## 2. Physical footprint

| Table | Rows | Total | Indexes |
|---|---:|---:|---:|
| `fact_ftr_bid` | 7,465,249 | 1,349 MB | 322 MB |
| `stg_ftr_bid_mnt` | 7,460,945 | 939 MB | — |
| `fact_nodal_cong_monthly` | 2,242,555 | 318 MB | 149 MB |
| `stg_ftr_cong_lmp` | 448,850 | 59 MB | — |
| `stg_utility_territory` | 721 | 23 MB | — |
| `dim_pnode` | 21,237 | 4.4 MB | 1.8 MB |
| **Database total** | | **2,719 MB** | |

Note `stg_ftr_bid_mnt` (7,460,945) is smaller than `fact_ftr_bid` (7,465,249) — because
staging is truncated and reloaded per auction partition while the fact table is rebuilt from
all partitions at once; the counts reconcile per-partition against the API's own `totalRows`.

## 3. Why PostgreSQL and not a cloud warehouse

A deliberate choice, and one worth being able to defend both ways.

| Consideration | Verdict |
|---|---|
| **Volume** | 9.7M fact rows / 2.7 GB. Postgres handles this without strain; BigQuery's advantages start two or three orders of magnitude higher. |
| **Geospatial** | PostGIS gives real `ST_Union`, `ST_SimplifyPreserveTopology`, `ST_AsGeoJSON`, GIST indexes. BigQuery GIS is workable but clumsier for a choropleth. |
| **Demo reliability** | Runs offline. A live demo cannot be broken by network, auth, or quota. |
| **Cost** | Zero. |
| **Iteration speed** | Sub-second query loop locally versus network round-trips. |
| **The honest counter** | If this scaled to full-nodal hourly LMPs (~122M rows/year) or the complete 164M-row bid stack, the calculus flips and BigQuery becomes the right tool. |

**The general principle:** right-size the tool to the problem. Reaching for distributed
infrastructure at 2.7 GB is a signal of poor judgement, not sophistication. Being able to
say *when* it would flip is the actual competence.

Apple Silicon detail: the official `postgis/postgis` images are amd64-only and run under QEMU
emulation on ARM, which is punishing for bulk `COPY`. Switched to `imresamu/postgis:16-3.4`,
a multi-arch build of the same PostGIS — same Postgres 16 / PostGIS 3.4, native `aarch64`.

## 4. Schema design decisions

### 4.1 The join key problem

PJM's FTR feeds key on **`pnode_name`, not `pnode_id`** — and the names carry internal runs
of spaces:

```
'02AMSTED138 KV  TR2'     ← two spaces before TR2
```

Every join therefore goes through a normalisation function, declared `IMMUTABLE` so it can be
indexed and used in expression indexes:

```sql
CREATE OR REPLACE FUNCTION norm_name(t text) RETURNS text
  LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
$$ SELECT upper(regexp_replace(btrim(coalesce(t, '')), '\s+', ' ', 'g')) $$;
```

Normalised names are **materialised** into `dim_pnode.pnode_name_norm` and
`fact_*.{pnode,source,sink}_name_norm`, then indexed — rather than normalising at query time,
which would defeat the index on every join.

### 4.2 A worse trap: the same node has different names in different feeds

Node **48821** is:

| Feed | Name |
|---|---|
| `da_hrl_lmps` | `BALA` |
| `ftr_cong_lmp` | `BALA    13 KV   LD1` |

Whitespace normalisation does not save you here — these are genuinely different strings for
the same physical node. **Rule adopted:** join on `pnode_id` where both feeds carry it; join
on normalised names only *within* a feed family. This bug initially made the validator return
`NaN` for BALA, which is exactly how it was found.

*(`BALA` is a PECO bus about two miles from SIG's Bala Cynwyd office — a useful concrete
example of what a pricing node physically is.)*

### 4.3 Unpivoting the class types

`ftr_cong_lmp` arrives wide — one column per FTR class, twice over. It is unpivoted to long
form so it joins to the bid stack directly:

```sql
CROSS JOIN LATERAL (VALUES
    ('OnPeak',       s.onpeak_clmp,        s.lt_sim_onpeak_clmp),
    ('OffPeak',      s.offpeak_clmp,       s.lt_sim_offpeak_clmp),
    ('DailyOffPeak', s.dailyoffpeak_clmp,  s.lt_sim_dailyoffpeak_clmp),
    ('WkndOnPeak',   s.wkndonpeak_clmp,    s.lt_sim_wkndonpeak_clmp),
    ('24H',          s.h24_clmp,           s.lt_sim_clmp)
  ) AS v(class_type, realized, sim)
```

Two details that would silently corrupt the join if missed:

1. **PJM's naming is asymmetric.** The baseline 24-hour column is `24hour_clmp`; its
   upgrade-adjusted twin is `lt_sim_clmp`, *not* `lt_sim_24hour_clmp`.
2. **The class labels are chosen to match `ftr_bids_mnt.class_type` exactly** — `'24H'`, not
   `'24Hour'`. This lets the two facts join with no lookup table. Matching a foreign
   vocabulary rather than inventing a local one removes a whole class of mapping bug.

(`24hour_clmp` becomes `h24_clmp` in the schema because a SQL identifier cannot start with a
digit unquoted.)

### 4.4 Indexing

```sql
CREATE INDEX idx_dim_pnode_norm  ON dim_pnode (pnode_name_norm);      -- the join key
CREATE INDEX idx_dim_pnode_zone  ON dim_pnode (zone);                 -- zonal aggregation
CREATE INDEX idx_fnc_month_class ON fact_nodal_cong_monthly (month, class_type);
CREATE INDEX idx_fb_path  ON fact_ftr_bid (source_name_norm, sink_name_norm, class_type);
CREATE INDEX idx_fb_month ON fact_ftr_bid (auction_month);
CREATE INDEX idx_dim_zone_geom ON dim_zone USING GIST (geom);         -- spatial
```

`fact_nodal_cong_monthly` uses a **composite primary key** `(pnode_name_norm, month,
class_type)` — the natural key. This makes the grain explicit and structurally prevents
double-loading a month, which `ON CONFLICT DO NOTHING` then makes idempotent.

Index overhead is 24% on the bid fact and 47% on the congestion fact — acceptable for a
read-heavy analytical workload where every query filters on month and class.

## 5. Ingest: rate limiting, pagination, resumability

### 5.1 Token-bucket throttle

Shared process-wide, because PJM rate-limits **per key**, not per caller:

```python
class _Throttle:
    def __init__(self, per_minute):
        self._interval = 60.0 / per_minute
        self._lock = threading.Lock()
        self._next_at = 0.0

    def wait(self):
        with self._lock:
            now = time.monotonic()
            sleep_for = self._next_at - now
            self._next_at = max(now, self._next_at) + self._interval
        if sleep_for > 0:
            time.sleep(sleep_for)
```

Retries distinguish **transient** (429, 5xx → exponential backoff, honouring `Retry-After`)
from **permanent** (4xx → raise immediately, because retrying a malformed request just burns
quota).

### 5.2 Partitioned, resumable loading

Every unit of work is a `(feed, partition)` pair recorded in `ingest_log`:

```sql
CREATE TABLE ingest_log (
  feed        text NOT NULL,
  partition   text NOT NULL,
  rows_loaded bigint,
  api_total   bigint,          -- the API's own totalRows, for assertion
  loaded_at   timestamptz DEFAULT now(),
  PRIMARY KEY (feed, partition)
);
```

- `ftr_cong_lmp` partitions **by quarter** (each quarter fits one 50k-row page)
- `ftr_bids_mnt` partitions **by auction**, checkpointing every 50k-row page — a 69-page pull
  never restarts from zero
- Re-running skips anything already logged

### 5.3 Row-count assertion

Every partition compares rows written against the API's declared `totalRows`:

```
[ok] ftr_bids_mnt/JAN 2025 Auction: 1,439,469 rows (API said 1,439,469)
[ok] ftr_bids_mnt/JUL 2025 Auction: 3,429,029 rows (API said 3,429,029)
[ok] ftr_bids_mnt/OCT 2025 Auction: 2,596,751 rows (API said 2,596,751)
```

Silent truncation from a dropped page is the single most likely ingest failure and the
hardest to notice downstream. Asserting against the source's own count catches it for free.

## 6. Data quality gates

### 6.1 Join-rate assertion

```
distinct_nodes | matched | pct
         16367 |   16207 | 99.0
```

**99.0%** of node names in the congestion fact resolve to the node dimension. The 160
unmatched are reported, not silently dropped. A 30% join miss that nobody measured would
invalidate every zonal aggregate while producing perfectly plausible output — this is the
check that makes the difference between a number and a number you can defend.

### 6.2 Structural verification

The planning-period rule is asserted, not assumed:

```
   market_name    | first_delivery | last_delivery | n_months |  bids
------------------+----------------+---------------+----------+---------
 JAN 2025 Auction | 2025-01-01     | 2025-05-01    |        5 | 1439469
 JUL 2025 Auction | 2025-07-01     | 2026-05-01    |       11 | 3429029
 OCT 2025 Auction | 2025-10-01     | 2026-05-01    |        8 | 2596751
```

Jan → 5 months, Jul → 11, Oct → 8. Exactly what a 1 June–31 May planning period predicts.

### 6.3 Geospatial verification

- Every crosswalk utility name must match a HIFLD record — **0 unmatched**
- Zone areas sanity-checked against expectation: AEP 50,532 sq mi > APS 27,755 > DOM 24,294
- Inter-zone overlaps checked: largest is ATSI/PENELEC at 918 sq mi, normal for
  service-territory boundary data
- Zones with nodes but no geometry are listed explicitly — RECO, by design

## 7. Validation: the part that changed the project

**This is the most important thing in the project, and it is the answer to "tell me about
working with large data sets."**

### The assumption

`ftr_cong_lmp` publishes `onpeak_clmp` and `lt_sim_onpeak_clmp`. PJM's own description says
the adjusted series is "historical cLMPs adjusted by PROMOD production cost simulation, which
considers certain transmission upgrades."

The natural reading: **baseline = what actually happened, adjusted = what the model says.**
That would have made this a model-versus-reality study.

### The test

`da_hrl_lmps` accepts a `pnode_id` filter, so one node-month costs a single API request (744
rows). Pull the raw hourly day-ahead LMPs, recompute the on-peak mean congestion
independently using a NERC-holiday-aware calendar, and compare.

### The result — July 2025

| Node | Hourly on-peak (computed) | Feed baseline | Difference |
|---|---:|---:|---:|
| `BALA 13 KV LD1` | −7.077 | −1.230 | +5.847 |
| `BGE` | 18.797 | 24.140 | +5.343 |
| `PEPCO` | 26.725 | 16.810 | **−9.915** |
| `COMED` | −8.507 | −4.930 | +3.577 |
| `WESTERN HUB` | 5.066 | 4.680 | −0.386 |

**REFUTED.** The differences are large *and vary in sign* — so this is not an hour-definition
error, a rounding artefact, or a constant offset. Both column families are modelled inputs to
PJM's FTR credit calculator. Neither is realized outturn.

### What survived

The **sign convention** validated cleanly: `system_energy + congestion + loss == total_lmp`
for **100.0%** of 3,720 hours. So an obligation from source to sink pays
`C(sink) − C(source)`, and every payoff equation in Part II rests on tested ground.

### What changed, and what didn't

| | Before | After |
|---|---|---|
| **Claim** | Model vs. reality | **Topology vs. topology** |
| **Quantity computed** | `lt_sim − baseline` | `lt_sim − baseline` — *unchanged* |
| **Map** | unchanged | unchanged |
| **Every number** | unchanged | unchanged |

The measured quantity never moved. Only the *label* on it — and the label is what makes a
result true or false. Had the validation been skipped, every figure would still have been
arithmetically correct and the conclusion would have been wrong.

**The lesson to articulate:** a column name is a claim made by someone else. Reconcile it
against an independent source before you build on it. And note the honest self-criticism —
this should have been done *before* the schema was designed, not after. The analysis survived
because the quantity being mapped didn't change, and that was luck.

## 8. Reproducibility: the second failure

The README promised the pipeline was reproducible. Testing that promise broke the warehouse.

### Bug 1 — destructive DDL

`01_schema.sql` opened every table with `DROP TABLE ... CASCADE`. Re-running it against a
loaded database destroyed 8 million rows.

### Bug 2 — the one that would have been dangerous

`ingest_log` was created with `CREATE TABLE IF NOT EXISTS`, so it **survived that drop**. The
bookkeeping then claimed all 14 partitions were loaded while their tables sat empty — and the
next `ingest.py` would have **skipped every feed and reported success against an empty
warehouse**.

Silent, and it would have looked fine.

### The fix

- `01_schema.sql` is now `CREATE ... IF NOT EXISTS` throughout — **non-destructive by
  construction**, safe to run against a loaded database.
- Teardown moved to `00_reset.sql`, which drops the tables **and** clears `ingest_log`
  **in one transaction**, because those two things are not independent.
- The join-rate check was guarded with `nullif(count(*), 0)` — a division-by-zero on an empty
  table is how the failure surfaced at all.

### The verification

Full cycle re-run: `00_reset` → `01_schema` → re-ingest → `load_geo` → crosswalk → transform
→ views. **Every figure returned identical**: 7,465,249 bids, 2,242,555 node-months, 99.0%
join rate, BGE +5.87, PEPCO +4.31, EKPC −1.47.

**The principle:** a pipeline you have never re-run from empty is not a system, it is a
one-off. And state that lives outside the thing it describes — bookkeeping that outlives its
own data — is a bug waiting for a quiet moment.

## 9. Presentation-layer engineering

The map is deliberately **zero-dependency**: no CDN, no mapping library, no tile server. The
Albers conic projection is ~20 lines of inline JavaScript and the polygons come from PostGIS.
It renders with the network off, which removes an entire category of live-demo failure.

**Albers equal-area conic** (standard parallels 29.5°/45.5°, central meridian −96°):

$$
n = \tfrac{\sin\varphi_1 + \sin\varphi_2}{2}, \qquad
C = \cos^2\varphi_1 + 2n\sin\varphi_1, \qquad
\rho = \tfrac{\sqrt{C - 2n\sin\varphi}}{n}
$$

$$
x = \rho\sin\bigl(n(\lambda - \lambda_0)\bigr), \qquad
y = -\bigl(\rho_0 - \rho\cos(n(\lambda-\lambda_0))\bigr)
$$

Equal-area matters for a choropleth: an equal-area projection does not distort the visual
weight of a zone relative to its neighbours, so a large pale zone and a small saturated one
are compared honestly.

**Two rendering bugs, both found only by looking at the screen:**

1. **The country rendered upside down.** The raw conic puts north at $+y$ by mathematical
   convention; SVG's $y$ axis grows *downward*. The negation in the $y$ equation above is the
   fix. It was wrong from the first version — with only the 14 PJM states drawn it merely
   looked odd; the whole country made it unmistakable.
2. **Clicking a zone did nothing.** `svg.setPointerCapture()` during drag retargets every
   subsequent pointer event — *and the click it generates* — to the capturing element, so
   per-path click handlers never fired. Drag state moved to `window` listeners with a 3px
   movement threshold.

Both passed every automated check: valid JSON, parsed JS, correct projection fit, all
endpoints HTTP 200. **Neither was detectable without a human looking at the output.**

Other presentation decisions worth defending:

- **Diverging blue↔red with a grey midpoint.** The metric has a true zero (the upgrade case
  leaves this node unchanged) and a meaningful sign either side. Sequential would be wrong;
  a rainbow would be wrong; a hue at the midpoint would be wrong.
- **Labels are laid out greedily largest-zone-first with collision rejection in screen
  space.** This gives progressive disclosure for free — zoom into the Mid-Atlantic and the
  small-zone labels that were rejected find room and appear.
- **Direct value labels on every zone**, so magnitude is never carried by colour alone.
- **Auto colour scale by default**, so quiet months are not amplified into false drama; a
  fixed ±6 toggle allows honest cross-month comparison.
- **Errors surface in a banner.** An API failure shows what failed and which command fixes
  it, rather than a blank page.

---

# Part V — The analysis and what it found

## 1. The analysis views

```
v_node_gap          node × month × class  →  baseline, upgraded, gap
       │
       ├─► v_zone_gap        zonal mean, sd, p10/p50/p90, count beyond ±$1
       │
v_path_expectation  (source, sink, class, auction) → MW-weighted bid, buy/sell sides
       │
       └─► v_path_divergence   bid vs baseline spread vs upgraded spread
                    │
                    └─► v_bid_anchoring   corr(bid, base) − corr(bid, upgraded)
```

`v_path_expectation` filters `hedge_type = 'Obligation'` — an option's price contains
optionality and is not comparable to a raw spread (Part I §4). Buy and sell sides are kept
separately because they straddle the unpublished clearing price.

## 2. Finding 1 — the adjustment is bimodal, not smooth

Mean zonal adjustment, on-peak, by month:

| Month | BGE | PEPCO | DOM | APS | PECO | COMED | AEP |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2025-04 | −0.01 | 0.00 | −0.01 | 0.00 | 0.00 | 0.00 | 0.00 |
| 2025-06 | +0.50 | +0.41 | −0.21 | −0.01 | +0.05 | −0.02 | −0.01 |
| **2025-07** | **+5.87** | **+4.31** | **+1.37** | **+1.14** | **−0.64** | **−1.20** | **−0.79** |
| 2025-08 | −0.12 | −0.08 | −0.51 | +0.30 | +0.45 | +0.01 | −0.17 |
| 2025-10 | 0.00 | 0.00 | −0.03 | 0.00 | +0.02 | −0.01 | −0.01 |

Across 30 months the adjustment sits within ±$0.05/MWh most of the time. **It is not noise
spread thinly — it is concentrated.** July 2025 dominates the sample.

**The interpretation that fits:** the adjustment scales with system stress. July 2025 was the
tightest month in the Mid-Atlantic in the sample — BGE baseline congestion ran $23.97/MWh
against $12.38 in June and $16.29 in August. A topology change is worth little when nothing
binds; when constraints bind hard, changing the shift factors re-prices everything. This is
exactly what the equation $C_i = -\sum_k \mathrm{GSF}_{k,i}\mu_k$ predicts: if all $\mu_k
\approx 0$, no change to GSF matters.

## 3. Finding 2 — the geography is coherent

The July 2025 pattern is not scattered. Every zone in the Baltimore–Washington–Northern
Virginia corridor moves **up**; the western zones move **down**. The upgrade case widens the
east–west price separation rather than relieving the load pocket.

That corridor is where the data-centre load growth is concentrated.

## 4. Finding 3 — zonal hedges are weakest where the adjustment is largest

Covered quantitatively in [Part II §7](#7-basis-risk-why-zonal-hedges-leak). BGE sd 3.46,
range +15.85 to −2.84 within one zone in one month.

## 5. Finding 4 — bidders track the baseline (a lead, not a result)

| Delivery month (on-peak) | Paths | corr(bid, base) | corr(bid, upgraded) | Edge |
|---|---:|---:|---:|---:|
| 2025-03 | 29,075 | 0.4620 | 0.4620 | 0.0000 |
| **2025-07** | **73,128** | **0.4583** | **0.4002** | **+0.0581** |
| 2025-08 | 31,709 | 0.5772 | 0.5650 | +0.0121 |
| 2025-10 | 101,010 | 0.2779 | 0.2777 | +0.0002 |

**In months where the two surfaces agree, the two correlations are identical — as they must
be.** The test only has statistical power in July 2025. There, the bid stack tracks the
baseline more closely. By sink zone that month:

| Sink zone | Paths | MW | corr(base) | corr(upgraded) | Edge |
|---|---:|---:|---:|---:|---:|
| DOM | 9,058 | 126,069 | 0.3496 | 0.1839 | **+0.1657** |
| AEP | 14,889 | 148,189 | 0.3247 | 0.1595 | **+0.1653** |
| DAY | 1,560 | 14,372 | 0.2336 | 0.1510 | +0.0826 |
| ATSI | 4,677 | 52,244 | 0.3823 | 0.3453 | +0.0370 |

**Be disciplined about this one.** One month, modest effect, and a competing explanation that
cannot be ruled out: the baseline may simply be the better predictor of what the bid is
proxying, independent of any behavioural anchoring. Twelve auctions instead of three would
tell you whether it recurs at planning-period boundaries. Calling it a lead rather than a
result is the correct posture.

## 6. Path-level examples

Most-traded July 2025 on-peak paths where the topology moves the spread most (≥50 MW):

| Source → Sink | Zone | MW | Baseline | Upgraded | Δ |
|---|---|---:|---:|---:|---:|
| `WESTGLOW 138` → `WURNO 138` | AEP → AEP | 83 | 0.05 | 68.65 | **+68.60** |
| `WURNO 138` → `AMOS 26` | AEP → AEP | 62 | −1.24 | −38.03 | −36.79 |
| `ELKRUNDP 230` → `REMNTNCT 18` | DOM → DOM | 82 | 2.39 | −31.14 | −33.53 |
| `MTZI APS 138` → `WESTVACO 138` | APS → APS | 191 | 1.65 | 29.32 | +27.67 |
| `ROXBURY 23` → `ASPENSLR 34.5` | PENELEC → PENELEC | 146 | 0.00 | −26.80 | −26.80 |

Note these are **intra-zonal** paths — source and sink in the same zone. The largest topology
effects are local, between nodes a zonal instrument cannot distinguish. That is the same
finding as §4 seen from the path side rather than the node side.

---

# Part VI — Where the value is

## 1. The direct trade

If you believed the upgrade case, the trade is mechanical: **buy the paths whose spread the
new topology widens, sell those it narrows.**

ComEd → BGE, July 2025 on-peak: $7.0771/MWh × 352 h = **$2,491 per MW**. On 100 MW,
**$249,114** for a single month.

The honest caveats, which matter more than the number:

- You do not have clearing prices, so you cannot compute realized P&L — only the difference
  between two published forecasts.
- The `lt_sim` series is used by PJM for **long-term auction credit**, so its horizon and
  purpose may not align with a monthly trade.
- The adjustment is only large in stressed months, and you must know *ex ante* which those
  will be. That is a weather and load forecasting problem, not a data problem — which is
  precisely why SIG describes its energy desk as weather- and fundamentals-driven.

## 2. Relative value between instruments

The within-zone dispersion is a **zonal-versus-nodal relative value signal**. In BGE July
2025, the zone mean says +5.87 but `WHITEROC` says +15.85 and `CONASTONE` says −2.84.

A trader long the zone and short specific nodes (or vice versa) is expressing a view on
*intra-zonal* topology that the zonal instrument cannot see. The zone mean is not a summary
of the nodes — it is a different instrument.

## 3. Risk management: the hedger's problem

An LSE holding zonal FTRs against nodal load exposure carries residual $\varepsilon_k = C_k -
C_Z$. This project quantifies how a topology change *disturbs that residual*, which is
directly a hedge-effectiveness question:

- Which nodes drift furthest from their zone under the new topology?
- Is the existing hedge portfolio still effective after the upgrade energises?
- Where should nodal FTRs replace zonal ones?

## 4. Revenue adequacy exposure

From [Part II §4](#4-revenue-adequacy): when the delivered network has less capacity than the
auction model assumed, congestion rent falls short and **PJM prorates payouts**. A holder can
be right about the spread and still be paid less than the contract says.

A systematic topology-divergence measure is an early indicator of where that risk
concentrates. This is a portfolio-construction input, not a directional trade.

## 5. Adjacent markets

The same framework transfers directly:

| Market | Instrument | Notes |
|---|---|---|
| **MISO** | FTR | Open data; M2M flowgates shared with PJM (`m2m_rt_ffe`) |
| **NYISO** | TCC | Fully open data, no API key required at all |
| **ERCOT** | CRR | Different topology dynamics, heavy renewable-driven congestion |
| **CAISO** | CRR | |

And **seams**: PJM/MISO market-to-market coordination means a topology change on one side
re-prices flowgates on the other — a structurally under-covered area because it requires
joining two ISOs' data.

## 6. How this connects to the rest of the energy complex

Congestion is one term in a larger structure:

$$
\text{Delivered power cost} = \underbrace{\lambda}_{\text{gas, coal, carbon}} + \underbrace{C_i}_{\text{topology, outages}} + \underbrace{L_i}_{\text{distance, loading}}
$$

- $\lambda$ moves with **natural gas futures** — the marginal unit in PJM is usually gas, so
  the system energy price is roughly heat-rate × gas price. That links power directly to
  Henry Hub and basis.
- $C_i$ is the topology term — **this project**.
- A **spark spread** trade (power minus fuel) at a specific node is exposed to all three.

An FTR is the cleanest available instrument for isolating the middle term, which is why it is
where a fundamentals-driven desk expresses topology views.

---

# Part VII — Limitations, failures, and next steps

## Limitations, stated plainly

1. **Both series are modelled.** Neither is realized outturn. Established by validation, not
   assumed.
2. **No clearing prices.** PJM publishes the bid stack; clearing prices are behind
   authentication. `mw_wavg_price` is a proxy.
3. **Three auctions, not twelve.** The bid feed accepts no node-level filter, so auction count
   was the only scope lever available under a 6 requests/minute cap.
4. **One month with signal.** The anchoring result rests on July 2025 alone.
5. **Approximate geometry.** Zone shapes are utility service territories, not PJM's network
   model. RECO has no geometry at all.
6. **99.0% join rate.** 160 of 16,367 node names do not resolve and are excluded from zonal
   aggregates.
7. **Four-month publication delay** on `ftr_bids_mnt` — this cannot be run against a live
   auction.
8. **The `lt_sim` horizon is not pinned down.** PJM states the adjustment differs between
   annual and long-term auctions. Which is reflected here has not been established.

## The two failures, and what they teach

| Failure | Root cause | Lesson |
|---|---|---|
| Column-name assumption refuted | Trusted a name instead of reconciling it | Validate feed semantics *before* designing the schema |
| Re-run wiped the warehouse | Destructive DDL + bookkeeping that outlived its data | A pipeline never re-run from empty is not a system |

A third, smaller one worth remembering: **the map was upside down and every automated check
passed.** Valid JSON, parsed JS, correct projection fit, all endpoints 200. Some classes of
error are only visible to a human looking at the output.

## Next steps, in priority order

1. **Pin down the baseline series.** It is processed, not raw. Test it against multi-year
   historical averages of the same calendar month to identify the lookback PJM's credit
   calculator uses. This would upgrade the whole project's claim.
2. **Widen to twelve auctions.** Determine whether the July effect recurs at planning-period
   boundaries or is specific to that month's system stress.
3. **Attribute to named constraints.** `da_marginal_value` gives $\mu_k$ by monitored
   facility and contingency (166 rows/day). Joining the largest zonal adjustments to the
   constraints binding in those hours would name the specific facilities the upgrade case
   relieves — turning "BGE moves +5.87" into "the 500 kV Conastone–Peach Bottom path
   re-rates."
4. **Add the DA-versus-RT basis.** `rt_da_monthly_lmps` carries both components in one row
   (323 rows/hour). FTRs settle on day-ahead; the grid clears in real time. That gap is the
   other half of the divergence between nodal cost and payoff.
5. **Scale the bid stack.** The full 164M rows is where BigQuery would genuinely earn its
   place.

---

# Appendix A — Interview question bank

### On data management

**"Walk me through your pipeline."**
Three layers, one direction. Staging mirrors each feed's exact shape with no interpretation,
so a modelling change never costs another download — which matters when the source is capped
at six requests a minute. Transforms build typed dimensions and facts with explicit grain.
Views carry the analysis. Every stage is idempotent; teardown is a separate, deliberate step.

**"How do you know the data loaded correctly?"**
Three gates. Row counts asserted against the API's own `totalRows` per partition — silent
truncation from a dropped page is the likeliest failure and the hardest to spot later. A
join-rate assertion, currently 99.0%, with the 160 misses reported rather than dropped. And
structural verification: the planning-period rule predicts Jan→5 months, Jul→11, Oct→8, and
the data agrees exactly.

**"Tell me about a time the data wasn't what you expected."**
*This is the validation story.* I assumed the unprefixed columns were realized congestion.
Before building on it, I pulled raw hourly LMPs and recomputed the on-peak mean myself. It
didn't reconcile — BALA read −1.23 against −7.08, PEPCO was off by ten dollars in the other
direction, and the errors varied in sign so it wasn't an hour-definition artefact. Both series
are modelled. I re-framed the claim from model-versus-reality to topology-versus-topology.
The measured quantity never changed, so the map survived — but that was luck, and the right
sequencing would have been to validate before designing the schema.

**"How do you know it's reproducible?"**
Because I ran it end to end and it broke. My schema file opened with `DROP TABLE CASCADE`, so
re-running it wiped eight million rows. Worse, `ingest_log` used `CREATE IF NOT EXISTS` and
survived the drop — so the bookkeeping claimed everything was loaded while the tables were
empty, and the next ingest would have skipped every feed and reported success on an empty
database. Silent. Schema is now non-destructive; teardown drops tables and clears the log in
one transaction, because those aren't independent.

**"Why Postgres and not Snowflake/BigQuery?"**
2.7 GB and 9.7 million fact rows. Postgres handles that without strain, PostGIS gives me real
spatial SQL for the choropleth, and it runs offline so a live demo can't be broken by network
or quota. I'd flip to BigQuery at the full-nodal hourly scale — 122 million rows a year — or
the complete 164-million-row bid stack. Reaching for distributed infrastructure at this size
would be poor judgement, not sophistication.

**"What's the hardest data quality issue you hit?"**
Join keys. PJM's FTR feeds key on node *name*, not ID, and names carry internal double spaces.
Worse, the same node has different names in different feeds — node 48821 is `BALA` in the
hourly LMP feed and `BALA    13 KV   LD1` in the congestion feed. Normalisation doesn't save
you there. The rule is: join on `pnode_id` where both feeds carry it, on normalised names only
within a feed family.

### On the analysis

**"What does the number actually mean?"**
For a given node and month, how much PJM's own upgrade-adjusted congestion case differs from
its baseline, in $/MWh. Because an FTR pays the *difference* between sink and source, the
difference of two node values is directly the change in that path's spread — the shared terms
cancel. So the map is readable as a path map.

**"Why is that tradeable?"**
An FTR obligation pays the day-ahead congestion spread, summed over the hours in its class. If
the topology changes the spread by $7.08/MWh and there are 352 on-peak hours, that's $2,491
per MW held. The whole instrument is a bet on the congestion surface, and the congestion
surface is a function of shift factors, which are a function of topology.

**"How confident are you in the anchoring result?"**
Not very, and deliberately so. The test only has power in one month — where the two surfaces
agree, the correlations are identical by construction. In July 2025 the edge is +0.058
overall, +0.166 in Dominion. That's suggestive but it's one month, and I can't rule out that
the baseline is simply the better predictor independent of any behavioural story. Twelve
auctions would tell you.

**"Why correlation instead of dollars?"**
Congestion is $/MWh; the bid is $ per MW for the whole period. They differ by hours-in-class,
which needs a NERC-holiday-aware calendar. Correlation is invariant to positive scaling, and
within a fixed month and class that factor is constant — so the comparison is exactly
unaffected by not converting. It's why the view groups by month *and* class; aggregating
across months would mix different factors and break the invariance.

**"What surprised you?"**
That the adjustment is bimodal. I expected a smooth re-rating and found it's essentially zero
in most months and very large in one. It fits the physics — congestion is a shift-factor-
weighted sum of shadow prices, so if nothing binds, no topology change matters.

### On the domain

**"Why can't you put nodes on a map?"**
PJM classifies node, substation and line locations as Critical Energy Infrastructure
Information. No coordinates, no shapefiles. Anyone showing you PJM nodes as dots either
bought proprietary data or invented positions. What every node carries is its transmission
zone, and PJM zones follow utility service territories, which are public through HIFLD. So
it's a zone choropleth off a hand-verified crosswalk — all 27 names matched. RECO isn't in
HIFLD's coverage, so it has no geometry and doesn't render; I'd rather show a gap than a
guess.

**"What's the difference between an FTR obligation and an option?"**
An obligation pays the spread whether positive or negative — it's linear and can lose money.
An option pays only when the spread is positive; it's a strip of hourly calls struck at zero.
That's why every path calculation here filters to obligations: an option's price contains
optionality and isn't comparable to a raw congestion difference.

**"What is revenue adequacy?"**
PJM funds FTR payouts from day-ahead congestion rent. The simultaneous feasibility test
guarantees the awarded portfolio is fundable *if the delivered network matches the auction
model*. When the real grid has less capacity — an unplanned outage — rent falls short and PJM
prorates payouts. So you can be right about the spread and still be paid less than the
contract says. It's the same topology divergence, seen from the credit side.

---

# Appendix B — Glossary

| Term | Definition |
|---|---|
| **ARR** | Auction Revenue Right. Entitles the holder to a share of FTR auction revenue; allocated to load-serving entities, convertible to FTRs |
| **Basis risk** | Residual exposure when the hedge instrument's reference point differs from the actual exposure point |
| **CEII** | Critical Energy Infrastructure Information. Regulatory classification restricting publication of grid facility locations |
| **cLMP** | Congestion component of LMP |
| **Congestion rent** | Surplus collected by the ISO when load pays more than generation receives under binding constraints |
| **Contingency** | A modelled equipment failure the dispatch must remain secure against (N−1) |
| **DA / RT** | Day-Ahead / Real-Time markets |
| **DC-OPF** | Linearised optimal power flow, the standard market-clearing formulation |
| **FTR** | Financial Transmission Right |
| **GSF** | Generation Shift Factor. Fraction of a 1 MW injection at a node that flows on a given element |
| **Hub** | An aggregate pricing point (e.g. WESTERN HUB), typically the most liquid trading reference |
| **LMP** | Locational Marginal Price — marginal cost of serving 1 MW at a specific node |
| **LSE** | Load-Serving Entity |
| **Monitored facility** | The transmission element whose limit is being enforced |
| **NERC holiday** | Holidays excluded from on-peak definitions: New Year's, Memorial, Independence, Labor, Thanksgiving, Christmas |
| **Nodal / zonal** | Pricing at an individual bus vs. a load-weighted aggregate |
| **On-peak** | Weekdays HE 0800–2300 EPT excluding NERC holidays |
| **Planning period** | PJM's FTR year: 1 June – 31 May |
| **pnode** | Pricing node |
| **PROMOD** | Commercial production-cost simulation software used for transmission planning studies |
| **SFT** | Simultaneous Feasibility Test — the FTR auction's network constraint set |
| **Shadow price (μ)** | Dual variable on a transmission constraint; $/MWh value of relaxing it by 1 MW |
| **Shift factor matrix** | The full GSF set — effectively *is* the network model; confidential |
| **TCC / CRR** | NYISO / CAISO-ERCOT equivalents of FTRs |

---

# Appendix C — Command reference

## Running it

```bash
cd ~/Developer/SIG/ftr-topology

cp .env.example .env                 # optional: add PJM_KEY
docker compose up -d db
docker exec -i ftr_db psql -U ftr -d ftr -v ON_ERROR_STOP=1 -f /sql/01_schema.sql

python etl/ingest.py                 # ~25 min cold, resumable
python etl/load_geo.py

docker exec -i ftr_db psql -U ftr -d ftr -f /sql/02_zone_crosswalk.sql
docker exec -i ftr_db psql -U ftr -d ftr -f /sql/03_transform.sql
docker exec -i ftr_db psql -U ftr -d ftr -f /sql/04_analysis_views.sql

python etl/validate.py               # characterise the feed
docker compose up -d api             # http://localhost:8080
```

Rebuild from empty: run `sql/00_reset.sql` **first**.

## Useful queries

```sql
-- The headline table
SELECT zone, n_nodes, mean_realized AS baseline, mean_sim AS upgraded,
       mean_gap, sd_gap, n_nodes_gap_over_1
FROM v_zone_gap
WHERE month = '2025-07-01' AND class_type = 'OnPeak'
ORDER BY mean_gap DESC;

-- Is the adjustment concentrated in time?
SELECT month, round(avg(mean_gap) FILTER (WHERE zone='BGE'), 2) AS bge,
              round(avg(mean_gap) FILTER (WHERE zone='COMED'), 2) AS comed
FROM v_zone_gap WHERE class_type='OnPeak' GROUP BY month ORDER BY month;

-- Within-zone dispersion: where zonal hedges leak
SELECT pnode_name, voltage_level, clmp_realized, clmp_sim, gap
FROM v_node_gap
WHERE zone='BGE' AND month='2025-07-01' AND class_type='OnPeak'
ORDER BY gap DESC LIMIT 10;

-- Do bids track the baseline or the upgrade case?
SELECT zone, n_paths, corr_bid_realized, corr_bid_sim, anchoring_edge
FROM v_bid_anchoring
WHERE month='2025-07-01' AND class_type='OnPeak'
ORDER BY anchoring_edge DESC;

-- Data quality: node-name join rate
SELECT count(*) AS nodes,
       count(*) FILTER (WHERE d.pnode_id IS NOT NULL) AS matched,
       round(100.0*count(*) FILTER (WHERE d.pnode_id IS NOT NULL)/nullif(count(*),0),1) AS pct
FROM (SELECT DISTINCT pnode_name_norm FROM fact_nodal_cong_monthly) f
LEFT JOIN dim_pnode d USING (pnode_name_norm);
```

## Repository map

```
ftr-topology/
├── docker-compose.yml          postgis + api; API_PORT defaults to 8080
├── Dockerfile                  api image
├── sql/
│   ├── 00_reset.sql            deliberate teardown (tables + ingest_log, one txn)
│   ├── 01_schema.sql           non-destructive DDL, norm_name()
│   ├── 02_zone_crosswalk.sql   PJM zone → HIFLD utility, hand-verified
│   ├── 03_transform.sql        staging → dims/facts, with quality gates
│   └── 04_analysis_views.sql   the five analysis views
├── etl/
│   ├── pjm_client.py           throttled paged API client
│   ├── db.py                   connection + COPY helpers + ingest_log
│   ├── ingest.py               partitioned resumable loader
│   ├── load_geo.py             HIFLD + TIGERweb → PostGIS
│   └── validate.py             independent reconciliation
├── app/
│   ├── main.py                 read-only FastAPI
│   └── static/index.html       zero-dependency Albers choropleth
└── notes/
    ├── STUDY_GUIDE.md          this document
    ├── findings.md             the analytical write-up
    └── demo_script.md          5-minute walkthrough
```

---

## The three sentences to have ready

1. **What it is:** *"PJM publishes two congestion surfaces for the same grid — a baseline and
   one adjusted for planned transmission upgrades — and I mapped the difference across all
   twenty transmission zones, then checked whether the FTR bid stack prices it."*

2. **What it found:** *"The adjustment is near-zero most months and then very large in
   stressed ones. In July 2025 it moved Baltimore +$5.87/MWh and ComEd −$1.20 — the upgrade
   case widens the east–west spread rather than relieving the load pocket. That's about
   $2,500 per MW on a ComEd-to-BGE obligation."*

3. **What it taught:** *"I assumed the baseline was realized congestion. I checked it against
   raw hourly LMPs before building on it, and it isn't — so I narrowed the claim to
   topology-versus-topology. Then I tried to re-run the pipeline from empty and it wiped
   itself, which found a bug where the ingest bookkeeping outlived its own data."*
