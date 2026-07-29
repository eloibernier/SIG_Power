# Demo narration — what to say, in order, and what every number means

Interview: Wednesday 29 July 2026, 10:30 EST.
Open on a second screen. `docker compose up -d`, then **http://localhost:8080**.

---

## The one-sentence version

> *"PJM publishes two congestion forecasts for the same grid — one on today's network, one
> on the network after planned transmission upgrades. I mapped the difference across all
> 20 transmission zones and then checked whether the FTR auction bid stack prices it."*

## The 60-second version, if that's all you get

> *"The job description mentions comparing electricity topologies to find divergence between
> nodal costs and payoffs. It turns out PJM publishes both sides of that themselves, one
> column apart, in the feed they use for FTR credit.*
>
> *For most months the two agree almost exactly. Then in July 2025 they diverge hard, and
> the divergence has a shape: Baltimore up $5.87 a megawatt-hour, DC up $4.31, while ComEd
> is down $1.20 and AEP down $0.79. Four zones up, eighteen down. The upgrade case doesn't
> relieve the Mid-Atlantic load pocket — it widens the east–west spread across it.*
>
> *An FTR pays the congestion difference between two points, so that's about seven dollars
> a megawatt-hour on a ComEd-to-Baltimore path — roughly $2,500 per megawatt for the month.*
>
> *The important caveat, which I tested rather than assumed: neither of those series is
> what actually happened. I reconciled them against raw hourly LMPs and they don't match.
> So it's topology versus topology, not model versus reality."*

---

# The story, in five acts

**The arc is: here's a question → here's what I had to establish before I could answer it →
here's the answer → here's what it's worth → here's what I don't know.**

Do **not** open with Docker, Postgres or PostGIS. That's the answer to "how", and it comes
when they ask.

| Act | Beat | Time |
|---|---|---|
| **1** | Their sentence, and the data that answers it | 30 s |
| **2** | The thing I got wrong, and how I found it | 60 s ← **the most important minute** |
| **3** | The map: geography, then honesty | 90 s |
| **4** | The drill-down: why zonal ≠ nodal | 60 s |
| **5** | The bid layer, and what I won't claim | 45 s |

---

## Act 1 — Open with their sentence (30 s)

> *"One line in the job description stood out — comparing different electricity topologies
> to identify differences that could lead to divergence between nodal costs and payoffs. I
> wanted to know whether that was answerable with public data.*
>
> *It is, and more directly than I expected. PJM's FTR credit feed publishes congestion for
> every node and every month twice: a baseline, and a PROMOD production-cost case adjusted
> for planned transmission upgrades. Same node, same month, two different networks, one
> column apart."*

**Point at the header counts as you say it:**

> *"That's 2.2 million node-month congestion records and 7.5 million FTR auction bids across
> 14,450 pricing nodes."*

---

## Act 2 — What I got wrong (60 s) ⭐

**This is the single most valuable minute of the demo.** HR told you to be ready on large
data sets. This is that answer — not the row count.

> *"Before I built anything on it, I wanted to know what those two columns actually are. The
> obvious reading is that the baseline is realized congestion — what actually happened — and
> the other is the model.*
>
> *So I tested it. The hourly day-ahead LMP feed lets you filter to a single node, so one
> node-month costs one API call. I pulled the raw hourly prices for five nodes, recomputed
> the on-peak average congestion myself with a NERC-holiday calendar, and compared.*
>
> *It doesn't reconcile. BALA reads minus 1.23 in the feed against minus 7.08 from the hourly
> data. PEPCO is off by ten dollars in the other direction. The errors are large and they
> vary in sign, so it's not an hour-definition mistake or rounding — both series are modelled
> inputs to PJM's credit calculator. Neither is outturn.*
>
> *What did check out was the sign convention: energy plus congestion plus loss equals total
> LMP for 100% of the 3,720 hours I tested. So an FTR obligation pays sink minus source, and
> every payoff calculation downstream rests on tested ground.*
>
> *So I narrowed the claim. This is topology versus topology, which is what the job
> description actually asks about — and it's a narrower claim than the one I set out to make."*

**If they push — "so was your analysis wrong?":**

> *"No, and that's the lucky part. The quantity I was computing never changed — it's still
> the difference between the two columns. What changed was the label on it, and the label is
> what makes a result true or false. Honestly, I should have validated the feed semantics
> before designing the schema rather than after."*

---

## Act 3 — The map (90 s)

Default view: **2025-07-01, OnPeak, PJM**.

### First the geography

> *"Each zone is coloured by the upgrade adjustment — the upgrade case minus the baseline, in
> dollars per megawatt-hour. Red means PJM's upgraded grid is more congested there, not less.*
>
> *The pattern is the story. Baltimore plus 5.87, Pepco plus 4.31, Dominion plus 1.37,
> Allegheny plus 1.14. Everything west — ComEd, AEP, Dayton, East Kentucky — is negative.
> Four zones up, eighteen down.*
>
> *The upgrade case doesn't relieve the Mid-Atlantic load pocket. It widens the east–west
> separation across it. And that corridor — Baltimore, Washington, northern Virginia — is
> where the data-centre load growth is."*

### Then click "United States"

> *"For scale: PJM is about 8% of the country's footprint but roughly a fifth of US
> electricity demand."*

Then **"Mid-Atlantic"** to come back in — the labels progressively reveal as you zoom, which
is worth letting them notice.

### Then the honest half — switch month to 2025-10

> *"And here's the part I'd want a trader to hear. Most months this is flat. October is
> essentially zero everywhere. Across 30 months the adjustment sits inside plus or minus five
> cents most of the time. It's not noise spread thinly — it's concentrated, and July 2025
> dominates the sample.*
>
> *That actually fits the physics. The congestion component at a node is a shift-factor-
> weighted sum of binding-constraint shadow prices. If nothing is binding, the shadow prices
> are near zero, and changing the network topology moves nothing. July 2025 was the tightest
> month in the Mid-Atlantic in my data — Baltimore's baseline congestion ran $23.97 against
> $12.38 in June. The upgrade case re-prices a stressed system, not a calm one."*

**Switch back to 2025-07 before continuing.**

---

## Act 4 — The drill-down (60 s)

**Click DOM** (or BGE). DOM is the better example because its mean hides more.

> *"Zone averages hide a lot, and this is where FTR traders actually live.*
>
> *Dominion's zone mean is plus 1.37. But the within-zone standard deviation is 2.90 — more
> than twice the mean. Of 1,729 nodes priced, 1,150 move by more than a dollar. The tenth
> percentile is minus 0.90 and the ninetieth is plus 4.46, so the zone contains nodes moving
> in both directions at once.*
>
> *At the top of that list, ROLNSFRD 230 kV goes from plus 14.80 to plus 41.95 — a 27 dollar
> move at a single node inside a zone whose average moved 1.37.*
>
> *Which means a zonal FTR and a nodal FTR are materially different instruments, exactly in
> the month and the place where the topology assumption matters most. If you're a load-serving
> entity hedged at the zone, your basis risk is not what the zone number tells you."*

**Scroll to the paths table:**

> *"And here are the traded paths sinking into Dominion, ranked by how far the topology moves
> them. Warrenton to ElkRun Depot: the spread goes from minus 2.57 on the baseline to plus 31
> on the upgrade case — a 33-dollar swing on a path with 20 megawatts bid into it.*
>
> *Notice the row below it is the same pair reversed, at minus 33.57. That's a consistency
> check — the spread from A to B has to be exactly the negative of B to A, and it is."*

*(That antisymmetry is a genuinely good detail to point out. It shows you know what the number
should do, not just what it is.)*

---

## Act 5 — The bid layer, and the limits (45 s)

> *"Last piece: does the market price this? I pulled the complete bid stack from three monthly
> auctions — 7.5 million bids — and correlated the megawatt-weighted bid on each path against
> both congestion spreads.*
>
> *In months where the two surfaces agree, the two correlations come out identical — as they
> must, so the test has no power there. In July 2025 it does: bids correlate 0.458 with the
> baseline and 0.400 with the upgrade case. In Dominion and AEP the gap is about 0.17.*
>
> *That's suggestive of bidders anchoring on history. But it's one month, the effect is
> modest, and I can't rule out that the baseline is simply the better predictor independent of
> any behavioural story. I'd call it a lead, not a result. Twelve auctions instead of three
> would tell you whether it recurs at planning-period boundaries."*

**Close:**

> *"Four things I'd do next: pin down what the baseline series actually is, widen to twelve
> auctions, attribute the biggest moves to named binding constraints using the marginal-value
> feed, and add the day-ahead versus real-time basis — FTRs settle day-ahead but the grid
> clears in real time, and that's the other half of the same question."*

---

# Every number on screen, decoded

## Header strip

| What you see | What it means | If asked |
|---|---|---|
| **2,242,555 node-months of congestion** | One row per node × month × FTR class where both series exist. 30 months, ~15k nodes, 5 classes | "That's the fact table grain — node, month, class type" |
| **7,465,249 FTR auction bids** | Every bid into the JAN, JUL and OCT 2025 monthly auctions | "The full feed is 164 million rows; PJM accepts no node-level filter on it, so auction count was the only scope lever under a 6-request-per-minute cap" |
| **14,450 active pricing nodes** | Nodes not terminated as of today | "PJM prices about 14,000 nodes each hour" |

## The colour scale

| What you see | What it means |
|---|---|
| **−6.0 ← blue … grey … red → +6.0 $/MWh** | Upgrade-adjusted minus baseline congestion. **Grey is a true zero** — the upgrade case leaves that node unchanged. Diverging, because the sign is meaningful |
| **Auto / Fixed ±6 toggle** | Auto rescales per month so quiet months aren't amplified into false drama. Fixed ±6 lets you compare months honestly |

> If asked why diverging: *"The metric has a real zero and a meaningful sign either side, so a
> sequential ramp would be wrong and a rainbow would be much worse. Grey in the middle means
> 'the upgrade changes nothing here'."*

## Zone labels on the map

**`DOM +1.37`** — the zone code and the **mean** upgrade adjustment across its nodes, $/MWh.

> *"Every zone carries its number directly, so the magnitude is never carried by colour alone
> — that matters for anyone reading this who's colour-blind, and it matters on a projector."*

## The four stat tiles

Using your DOM screenshot:

| Tile | Value | What it actually means |
|---|---|---|
| **Upgrade adjustment** | **+1.37** $/MWh | The headline. Mean of (upgrade-adjusted − baseline) across the zone's nodes. **Positive = PJM's upgraded grid is *more* congested here.** This is the number the map colours |
| **Within-zone spread** | **2.90** sd | Standard deviation of that adjustment across the zone's 1,729 nodes. **The bigger this is relative to the mean, the worse a zonal FTR is as a hedge for any individual node.** Here it's more than double the mean |
| **Baseline congestion** | **+5.67** $/MWh | The congestion component of LMP under PJM's baseline network, averaged over the zone. Positive means power is expensive to deliver here — a load pocket |
| **Upgrade-adjusted** | **+7.04** $/MWh | The same thing on the upgraded network. **7.04 − 5.67 = 1.37**, which is the tile above. Say that out loud — it shows the tiles reconcile |

## The distribution line

> *"1,729 nodes priced; 1,150 move by more than $1/MWh. p10 −0.90 · median +1.28 · p90 +4.46."*

| Term | Meaning |
|---|---|
| **1,729 nodes priced** | How many nodes in this zone have both series for this month/class |
| **1,150 move by more than $1** | **Two-thirds of the zone.** This isn't a couple of outliers dragging an average |
| **p10 −0.90** | The bottom decile actually moves *down* |
| **median +1.28** | Close to the mean 1.37, so the distribution isn't badly skewed |
| **p90 +4.46** | The top decile moves more than three times the zone mean |

> *"p10 negative and p90 at plus 4.46 means this zone contains nodes moving in opposite
> directions. The zone mean isn't a summary of the nodes — it's a different instrument."*

## "Nodes furthest from the zonal average" table

| Column | Meaning |
|---|---|
| **Node** | PJM's pricing-node name. Usually substation + voltage + equipment |
| **kV** | Voltage level. **Worth reading**: 230 kV and above is transmission backbone; 13–34 kV is distribution-level load |
| **Base** | Baseline congestion at that node, $/MWh |
| **Adj.** | Upgrade-adjusted congestion at that node, $/MWh |
| **Δ** | Adj. − Base. The node's own topology gap |

From your screenshot: `ROLNSFRD230 KV DP_Y54` — base **+14.80**, adjusted **+41.95**,
Δ **+27.15**.

> *"One node moving 27 dollars inside a zone whose average moved 1.37."*

**The voltage pattern is worth a sentence if they seem engaged.** In BGE the 500 kV node
(`CONASTONE`) moves *down* while the 13.8 kV load nodes move sharply *up* — the upgrade case
changes how power reaches load pockets, not the bulk backbone.

## "Traded FTR paths sinking here" table

| Column | Meaning |
|---|---|
| **Source → sink** | The FTR path. An obligation pays congestion(sink) − congestion(source) |
| **MW** | Total megawatts bid on that path in the auction — **liquidity, not position** |
| **Base** | The path's congestion spread under the baseline network |
| **Adj.** | The same spread under the upgraded network |
| **Δ** | How much the topology moves this path's payoff, $/MWh |

From your screenshot:

| Path | MW | Base | Adj. | Δ |
|---|---:|---:|---:|---:|
| `WARRENTN35 KV FAUQUIER` → `ELKRUNDP230 KV TX1` | 20 | −2.57 | +31.00 | **+33.57** |
| `ELKRUNDP230 KV TX1` → `WARRENTN35 KV TX2` | 2 | +2.57 | −31.00 | **−33.57** |

> *"Same pair of substations, opposite directions, exactly opposite numbers. The spread from A
> to B has to be the negative of B to A — that's a free consistency check on the whole
> calculation, and it passes."*

**Why paths are only filtered to obligations:** an FTR option pays `max(0, spread)` — it's a
strip of hourly calls struck at zero, so its price contains optionality and isn't comparable
to a raw congestion difference. Obligations are 96% of bids by count.

---

# The three numbers to have memorised

| Number | What it is | The sentence |
|---|---|---|
| **+5.87 / −1.20** | BGE and ComEd, July 2025 on-peak | *"The upgrade case widens the east–west spread rather than relieving the load pocket"* |
| **$2,491 per MW** | 7.0771 $/MWh × 352 on-peak hours | *"That's what a ComEd-to-Baltimore obligation is worth differently under the two topologies, for one month"* |
| **0.458 vs 0.400** | corr(bid, baseline) vs corr(bid, upgraded), July 2025 | *"Bids track the baseline more closely — but it's one month, so a lead not a result"* |

**Where $2,491 comes from, if they ask you to show the arithmetic:**

```
ΔSpread = G(BGE) − G(COMED) = (+5.8748) − (−1.2023) = 7.0771 $/MWh
Hours    = July 2025 on-peak = 22 weekdays × 16 h = 352 h   (4 July is a NERC holiday)
Value    = 7.0771 × 352      = $2,491 per MW
```

---

# Likely interruptions, and the honest answer

**"Why are the zones shaped like utility territories, not the grid?"**
> *"Because PJM classifies node, substation and line locations as Critical Energy
> Infrastructure Information — no coordinates, no shapefiles, for anyone. But every node
> carries its transmission zone, and PJM's zones follow utility service territories, which
> are public through HIFLD. So it's a hand-built crosswalk, zone code to utility name, unioned
> in PostGIS. All 27 names matched. RECO isn't in HIFLD's coverage so it has no geometry and
> doesn't render — I'd rather show a gap than draw something invented."*

**"Is this real money or a modelling artefact?"**
> *"Both series are PJM's own published numbers, so the difference is real in the sense that
> it's what PJM's own planning model says. Whether it's tradeable depends on something I
> can't verify from public data — the clearing prices sit behind FTR Center authentication.
> PJM publishes the bid stack, not where it cleared."*

**"How do you know the data is right?"**
> *"Three gates. Row counts asserted against the API's own totalRows for every partition —
> silent truncation from a dropped page is the likeliest failure and the hardest to notice
> later. A node-name join rate, currently 99.0%, with the 160 misses reported rather than
> dropped. And structural checks: the planning-period rule predicts a January auction sells
> five months, July eleven, October eight — and the data agrees exactly."*

**"Could you run this on a bigger dataset?"**
> *"Yes, and I'd change tools to do it. This is 2.7 gigabytes and 9.7 million fact rows, which
> Postgres handles without strain, and PostGIS gives me real spatial SQL for the map. At full
> nodal hourly — 122 million rows a year — or the complete 164-million-row bid stack, I'd move
> to BigQuery. Reaching for distributed infrastructure at this size would be poor judgement,
> not sophistication."*

**"What would you do differently?"**
> *"Validate the feed semantics before designing the schema, not after. And I found a second
> one testing reproducibility — my schema file opened with DROP TABLE CASCADE, so re-running it
> wiped eight million rows. Worse, the ingest bookkeeping table used CREATE IF NOT EXISTS and
> survived the drop, so it still claimed everything was loaded against empty tables. The next
> ingest would have skipped every feed and reported success on an empty warehouse. Silent.
> Fixed by making the schema non-destructive and putting teardown in one transaction that
> drops the tables and clears the log together."*

---

# What not to do

- **Don't lead with the stack.** Postgres/PostGIS/Docker/FastAPI is the answer to "how", not
  the opening.
- **Don't say "realized" or "actual"** about the baseline series. It isn't. You tested it.
- **Don't oversell the bid anchoring.** One month, +0.058. "A lead, not a result."
- **Don't call `mw_wavg_price` a clearing price.** It's a proxy; PJM publishes bids only.
- **Don't hide the failures.** They're the strongest material you have — they're the evidence
  you check your own work.
- **Don't leave it on a flat month.** If you've been clicking around, reset to
  **2025-07 / OnPeak** before you hand back to them.

---

# Pre-flight, Wednesday morning

```bash
cd ~/Developer/SIG/ftr-topology
docker compose up -d          # wait ~20 s for the healthcheck
open http://localhost:8080
```

- [ ] Page loads, defaults to **2025-07-01 / OnPeak**
- [ ] Click **DOM** and **BGE** once each so the panel is warm
- [ ] Toggle to **2025-10** and back, so the month switch is smooth on the day
- [ ] Screenshots open in a second window as the fallback if screen-share fails
- [ ] Close other tabs — the tab bar is visible when you share

**If the live demo fails:** narrate the screenshots. Nothing in the story depends on the page
being interactive, and saying *"let me talk you through it from screenshots"* costs you
nothing.
