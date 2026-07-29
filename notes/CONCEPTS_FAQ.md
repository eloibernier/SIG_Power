# Concepts FAQ — the questions that expose whether you actually understand it

Seven things that are easy to say fluently and still get wrong. Each has a wrong reading that
sounds plausible, which is exactly why an interviewer probes them.

1. What the two networks are
2. Why upgrades can make congestion worse
3. Why $7.08 is a change, not a cost
4. Why an FTR is an asset, not a toll
5. Reading the zone panel — every tile
6. What kV means and why it is there
7. Whether generating at a high-congestion node pays

---

## 1. What are the "two networks"?

PJM approves transmission projects — new lines, reconductoring, larger transformers — that
take years to build. **PROMOD** is production-cost simulation software: feed it a network
model, a generator fleet, fuel prices and load, and it simulates hourly dispatch and produces
LMPs.

PJM runs it twice:

| Case | Network model | Everything else |
|---|---|---|
| **Baseline** | The grid roughly as it stands | load, fuel, fleet |
| **Upgrade-adjusted** (`lt_sim_*`) | Same grid **plus approved projects not yet energised** | *held identical* |

Because everything except the network is held constant, the difference **isolates the effect
of the steel in the ground.**

**Why PJM produces it:** long-term FTR auctions. Selling an FTR for delivery three years out
means the grid then is not the grid now, so the credit calculator needs congestion on the
*future* network to set collateral sensibly.

### The decisive evidence that neither column is history

The feed publishes **both** columns for months that have not happened yet:

| effective_day | `onpeak_clmp` (baseline) | `lt_sim_onpeak_clmp` (upgraded) |
|---|---:|---:|
| June 2027 | 1.13 | 4.51 |
| **May 2030** | **−1.17** | **−0.85** |

**There is no realized congestion for May 2030.** So the unprefixed column cannot be outturn —
it is a simulation on the *current* network, published forward. Both columns are forward-looking
models differing only in the network they assume.

> *"The feed publishes both columns for May 2030. Neither of them can be what happened."*

That is a cleaner proof than the hourly reconciliation in `validate.py`, and easier to say out
loud. The reconciliation remains the stronger evidence for a *historical* month, since it shows
the baseline does not match outturn even where outturn exists.

**Horizon:** `lt_sim_` = long-term simulation; the feed runs at least to May 2030, roughly four
years forward, consistent with PJM's long-term FTR auctions covering multiple future planning
periods.

**What is still not known:** which specific upgrade projects are in the adjusted case, and
whether a past month's values are revised after the fact. Answering that needs historical
snapshots of the feed. Say so rather than guessing.

---

## 1b. The three numbers people conflate

| Number | What it is | Where it lives | Public? |
|---|---|---|---|
| **Settled DA congestion** | What a generator is actually paid, and **what an FTR actually pays out** | `da_hrl_lmps` | Yes |
| **Auction clearing price** | What you **pay** to acquire the FTR | FTR Center | **No** — behind authentication |
| **`ftr_cong_lmp` base & adj** | What PJM uses to **size collateral** | this feed | Yes |

**Is an FTR priced off the baseline or the adjusted series? Neither.** It clears at the dual of
the auction's simultaneous feasibility test, given submitted bids and the *auction's* network
model. This feed's full name is **"FTR Credit Calculator Congestion LMPs"** — a credit and
collateral input, not a clearing input.

### Worked example

> System energy 115.80, baseline congestion 5, loss 0, adjusted congestion 20. What is received?

**Neither 5 nor 20.**

```
paid = 115.80 + actual settled congestion + 0
```

`actual settled congestion` is a **third number**, living in `da_hrl_lmps`, absent from this
feed. If it settles at 8, the node is paid $123.80 — not $120.80 and not $135.80.

### So who cares about the adjusted series?

**Not a generator.** It is paid settled LMP; this feed is irrelevant to its revenue.

**Two parties do:**

1. **Anyone posting collateral** — PJM sizes FTR margin off these numbers, regardless of what
   eventually settles.
2. **Anyone trading the congestion surface** — it is PJM's own free, published, multi-year view
   of what planned transmission does to every node. That is the thesis of this project.

---

## 2. Why would upgrades make congestion *worse*?

### The setup

The congestion component is **relative**, not absolute. It measures how much more or less
expensive power is at that node than the system average, *because of transmission limits*.

| Sign | Meaning | Example (Jul-2025 on-peak) |
|---|---|---|
| **Positive** | Import-constrained — hard to get power in, so it's expensive | BGE **+23.97** |
| **Negative** | Export-constrained — power trapped behind a bottleneck, so it's cheap | COMED **−5.12** |

Under the upgrade case: BGE → **+29.84**, ComEd → **−6.33**. Both move *further from zero*.
The east becomes more import-constrained, the west more trapped.

### The leading hypothesis

**Relieving one bottleneck pushes flow onto the next one.** If you strengthen the path *to*
the edge of a load pocket while the constraints *inside* it are unchanged, more power reaches
the doorstep and the internal constraint binds harder.

### The supporting evidence — BGE nodes by voltage tier

| Tier | Nodes | Baseline | Upgraded | Change |
|---|---:|---:|---:|---:|
| Backbone (≥230 kV) | 12 | 16.04 | 20.29 | **+4.25** |
| Sub-transmission / load (<230 kV) | 251 | 24.35 | 30.30 | **+5.95** |

Delivery-level nodes move ~$1.70/MWh more than backbone nodes — consistent with the bulk
system improving relatively more than delivery into load.

### How to say it

> *"My read is that it's relative rather than absolute — the upgrades change how power reaches
> the load pocket, so the price separation across the constraint widens. You can see it in the
> voltage split: the sub-transmission nodes move about $1.70 more than the backbone. But
> confirming the mechanism needs the binding-constraint data, and I haven't joined that in
> yet."*

**Naming what you'd need to prove it is a stronger answer than asserting the mechanism.**

---

## 3. "So a solar farm selling to Baltimore pays $7/MW?" — No

Three corrections, most important first.

### (a) $7.08 is a *change*, not a *cost*

| | ComEd | BGE | **Spread** |
|---|---:|---:|---:|
| **Baseline forecast** | −5.12 | +23.97 | **$29.09/MWh** |
| **Upgrade-adjusted forecast** | −6.33 | +29.84 | **$36.17/MWh** |
| | | | **difference: $7.08** |

The congestion cost of ComEd→Baltimore exposure is **~$29/MWh**. The **$7.08 is how much
worse it gets** under the upgrade case. It is a difference of differences.

### (b) Generators don't pay a delivery charge

There is **no point-to-point shipping fee inside the energy price** in a nodal market.

- A generator **injects at its own node and is paid that node's LMP**
- Load **withdraws at its node and pays that node's LMP**
- The ISO collects the difference as **congestion rent** — which is what funds FTR payouts

So a solar farm in ComEd is simply paid ComEd's price, which sits $5.12/MWh **below** the
system energy price precisely because it is behind a constraint. **Congestion reaches a
generator as a haircut on the price it receives, not as a bill.**

You only face the $29 spread if you have contracted to deliver *at Baltimore's price* — a PPA
where you receive ComEd and owe BGE. Then the spread is your loss, and **an FTR is exactly the
instrument that hedges it**: buy ComEd→BGE, it pays the spread, the exposure nets out.

### (c) $/MWh versus $/MW

| Quantity | Unit | Why |
|---|---|---|
| Congestion price | **$/MWh** | Per unit of *energy* |
| FTR position | **MW** | *Capacity* |
| FTR payoff | **$/MW for the period** | $/MWh × hours |

$7.08/MWh × 352 on-peak hours in July = **$2,491 per MW held**.

Confusing these is a factor-of-352 error.

---

## 4. "Does the zonal FTR cost you the adjustment?" — No

**An FTR is an asset you buy, not a toll you pay.**

```
You pay:      the auction clearing price, upfront, $/MW for the period
You receive:  the realized day-ahead congestion spread, sink − source, every hour
P&L        =  received − paid
```

The "adjustment" is neither of those. It is **the difference between two forecasts of what you
would receive.**

### Zonal versus nodal

| | Source/sink is | Hedges |
|---|---|---|
| **Zonal FTR** | A zone aggregate — load-weighted average of every node in the zone | Zone-level exposure |
| **Nodal FTR** | One specific bus | That exact node |

If your exposure is at *one node*, a zonal FTR leaves residual **basis risk**:

$$\varepsilon_k = C_k - C_Z$$

That residual is what the **within-zone spread** tile measures. Dominion's mean is **+1.37**
but its standard deviation across nodes is **2.90** — so the zone number tells you very little
about any individual node inside it.

> **"The zone mean isn't a summary of the nodes — it's a different instrument."**

---

## The four sentences worth memorising

1. **"The difference isolates the effect of the steel in the ground — everything except the
   network is held constant."**
2. **"Congestion is relative. Positive means import-constrained and expensive; negative means
   trapped behind a bottleneck and cheap."**
3. **"A generator is paid its own node's price. Congestion reaches it as a haircut on what it
   receives, not as a bill."**
4. **"An FTR is an asset you buy that pays the congestion spread — not a toll you pay to move
   power."**

---

## 5. Reading the zone panel — every tile, correctly

### Ground it first: a real nodal price

Hour beginning 16:00 EPT, 15 July 2025 (pulled live from `da_hrl_lmps`):

| | DOM | ComEd |
|---|---:|---:|
| System energy price | 115.80 | 115.80 | *identical everywhere in PJM* |
| Congestion component | **+9.04** | **+4.35** | *location-specific* |
| Loss component | +0.16 | −0.50 | |
| **Total LMP** | **$125.00** | **$119.64** | |

A generator injecting in DOM that hour was paid $125.00/MWh; one in ComEd $119.64. Same hour,
$5.36 apart, and congestion is most of the gap.

### The panel is not showing prices

It shows **only the congestion component**, and it shows **two forecasts of it side by side**
— not a price plus an adjustment.

| Tile | Common wrong reading | What it actually is |
|---|---|---|
| **Baseline congestion** +5.67 | "what we expected" | Modelled congestion across the zone's nodes for that month/class, on **the grid as it stands today** |
| **Upgrade-adjusted** +7.04 | ❌ "what actually happened" | The **same simulation on the network after planned upgrades**. Also a model |
| **Upgrade adjustment** +1.37 | ❌ "added to the LMP" | Simply **7.04 − 5.67**. A difference between two *scenarios*, never added to anything |
| **Within-zone spread** 2.90 sd | — | Standard deviation of (adj − base) across the zone's nodes. Measures how badly the zone average represents any individual node |

### The sentence never to say

> ~~"The adjusted column is what actually happened."~~

**Neither series is outturn** — that is exactly what `etl/validate.py` established. Saying
"actual" contradicts your own validation result. Always: **two models of the same month, on
two different networks.**

---

## 6. What does kV mean, and why is it in the table?

Kilovolts — the voltage of the equipment at that node.

| Voltage | What it is |
|---|---|
| **500 / 345 kV** | Bulk transmission backbone — long distance, high capacity |
| **230 / 138 kV** | Regional transmission |
| **34.5 / 18 / 13.8 kV** | Sub-transmission, distribution delivery points, generator step-up |

It matters because the upgrade case hits the tiers differently: in BGE, sub-transmission nodes
move ~$1.70/MWh more than backbone nodes — the evidence that upgrades improve the bulk system
more than they improve delivery *into* load.

---

## 7. "If I generate at a high-congestion node, do I get paid more?"

**Yes — that part is real, and it is the entire economic purpose of nodal pricing.** A node
with congestion of +14.80 pays a generator $14.80/MWh above the system energy price. High LMP
is the market shouting *"build generation here."*

Three corrections though:

1. **The Δ column is not money anyone receives.** It is the gap between two forecasts. What a
   generator is actually paid is the *level* (+14.80, or +41.95 under the upgrade case), not
   the difference between them.
2. **The sign flips depending on which side you are on.** High positive congestion is good if
   you **inject** there and bad if you **withdraw** there. Generator paid more; load pays more.
3. **You cannot execute that view by generating.** Building a plant means capital, land and
   years in the interconnection queue. The financial expression of *"this node's congestion
   will be higher than the market thinks"* **is to buy an FTR sinking at that node.** That is
   the instrument, and that is what a proprietary desk does.

> The instinct is right — someone who spots it early makes money. They do it by buying the
> FTR, not by pouring concrete.
