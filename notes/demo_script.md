# Demo script — 5 minutes

Interview: Wednesday 29 July 2026, 10:30 EST, Zoom.

**Before the call:** `docker compose up -d` then open <http://localhost:8080> and click
BGE once, so the page is already warm. Have `notes/screens/` open in a second window as the
fallback. Turn wifi off once to prove to yourself the page still renders — it does, there
are no external tiles and no CDN.

---

## 0. The opening (30 seconds) — lead with their sentence, not the stack

> "One line in the job description stood out — comparing different electricity topologies
> to find divergence between nodal costs and payoffs. I went looking for whether that was
> answerable with public data, and it turns out PJM publishes both sides of it themselves.
> So I built something small to look at it."

Do **not** open with Postgres/PostGIS/Docker. That is the answer to "how", and it comes
later if they ask.

## 1. What the data is — and the thing I got wrong (60 seconds)

Share the map. Point at the header.

> "PJM's FTR credit feed gives you congestion for every node and month under two labels:
> a baseline, and a PROMOD case adjusted for planned transmission upgrades.
>
> My first assumption was that the baseline was realized congestion — what actually
> happened. So before building anything on it I pulled the raw hourly day-ahead LMPs for a
> handful of nodes and recomputed the on-peak average myself. It doesn't reconcile. BALA
> reads −1.23 in the feed against −7.08 from the hourly data; PEPCO is off by ten dollars
> in the other direction. Both series are modelled inputs to their credit calculator.
>
> What did check out was the sign convention — energy plus congestion plus loss equals
> total LMP for 100% of the hours I tested, so an obligation pays sink minus source.
>
> So this is topology versus topology, which is narrower than what I set out to measure,
> but it's the claim the data actually supports."

**This is the most important 60 seconds of the demo.** It is the answer to "tell me about
working with large data sets" — the answer is that you reconciled the feed before trusting
it, and you changed the claim when it didn't hold.

## 2. The map (90 seconds)

Default view is July 2025, on-peak.

> "Each zone is coloured by the upgrade adjustment — upgrade case minus baseline, in
> dollars per MWh. Red means PJM's upgraded grid is *more* congested there.
>
> The pattern is the story. Baltimore is +5.87, Pepco +4.31, Dominion +1.37, Allegheny
> +1.14. Everything west — ComEd, AEP, Dayton, East Kentucky — is negative. The upgrade
> case doesn't relieve the load pocket, it widens the east–west separation across it.
>
> So a ComEd-to-BGE obligation is worth about seven dollars a megawatt-hour more under the
> modelled topology than the baseline. Same path, same month, same class — just a
> different network."

Then change the month selector to **October 2025**.

> "And here's the honest part: most months this is flat. October is essentially zero
> everywhere. The adjustment isn't a constant re-rating, it scales with system stress —
> July was the tightest month in the Mid-Atlantic in my sample. It re-prices a stressed
> system, not a calm one."

## 3. The drill-down (60 seconds)

Click **BGE**.

> "Zone means hide a lot. Within BGE the standard deviation is 3.46 — p10 is +1.06, p90 is
> +11.71. This node, Whiterock 13.8kV, moves +15.85, nearly three times its own zone mean.
>
> Which means a zonal FTR and a nodal FTR are materially different instruments exactly in
> the month and the place where the topology assumption matters most."

If there is time, switch to **PECO** and note `BALA` — a bus a couple of miles from their
office — as the concrete example of what a node actually is.

## 4. The bid layer (45 seconds)

> "Last piece: does the market price this? I pulled the full bid stack from three monthly
> auctions — about 7.5 million bids — and correlated the MW-weighted bid on each path
> against both congestion spreads.
>
> In months where the two surfaces agree, the correlations are identical, so the test has
> no power. In July 2025 it does: bids correlate 0.458 with the baseline and 0.400 with the
> upgrade case. In Dominion and AEP the gap is about 0.17.
>
> That's suggestive of bidders anchoring on history — but it's one month and a modest
> effect, so I'd call it a lead, not a result. Twelve auctions instead of three would tell
> you whether it recurs."

Correlation not dollars, and say why: congestion is $/MWh, bids are per MW for the whole
period, and converting needs a NERC-holiday class-hours calendar. Correlation sidesteps it.

## 5. Close (20 seconds)

> "Four things I'd do next: pin down what the baseline series actually is, widen to twelve
> auctions, attribute the largest adjustments to specific binding constraints using the
> marginal value feed, and add the day-ahead versus real-time basis — FTRs settle on
> day-ahead but the grid clears in real time, and that's the other half of the same
> question."

---

## Likely questions, and the honest answers

**"Why zones and not nodes on the map?"**
PJM classifies node, substation and line locations as Critical Energy Infrastructure
Information — no coordinates, no shapefiles. But every node carries its transmission zone,
and PJM's zones follow utility service territories, which are public. So the geometry is a
hand-built crosswalk from zone code to utility name, unioned in PostGIS. All 27 names
matched. RECO isn't in the HIFLD coverage, so it has no geometry — I left it off the map
rather than draw it somewhere invented.

**"How big is this really?"**
7.5 million bids, 2.2 million node-month congestion records, 21 thousand nodes. The bid
feed is 164 million rows in total; I took three auctions because PJM rejects any node-level
filter on it — `sink_pnode_name` is not a valid filter field — so the only lever is auction
count. Everything runs on a laptop in Postgres; I didn't reach for a cloud warehouse
because at this size it would buy nothing and cost me a live demo dependency.

**"Did you get clearing prices?"**
No — PJM publishes the bid stack; clearing prices sit behind FTR Center authentication.
So `mw_wavg_price` is a proxy. Arguably the bid stack is the richer object since it's the
whole demand curve rather than just where it cleared, but I wouldn't claim it *is* the
clearing price.

**"What surprised you?"**
That the adjustment is bimodal — essentially zero in most months, then very large in one.
I expected a smooth re-rating and got a stress-conditional one.

**"What would you do differently?"**
Validate the feed semantics before building the schema, not after. I built the warehouse
around a column-name assumption and had to re-frame the claim once it didn't reconcile.
The analysis survived because the quantity I was mapping didn't change — but that was luck,
not planning.

**"How do you know the pipeline is reproducible?"**
Because I ran it end to end and it broke. My schema file opened with `DROP TABLE CASCADE`,
so re-running it wiped eight million rows. Worse, the `ingest_log` table used
`CREATE IF NOT EXISTS` and therefore *survived* the drop — so the bookkeeping still claimed
all fourteen partitions were loaded while the tables were empty, and the next ingest would
have skipped every feed and reported success against an empty warehouse. Silent, and it
would have looked fine.

The fix was to make the schema non-destructive and move teardown into `00_reset.sql`, which
drops the tables and clears the log in one transaction, because those two things are not
independent. That's the kind of thing the JD's "maintain internal data systems" bullet is
really about — a pipeline you can't safely re-run isn't a system, it's a one-off.

## Rate limits, if it comes up

PJM caps non-member API users at 6 requests/minute. The client throttles to 5.5, retries
429s with backoff, and checkpoints every page to Postgres so a 150-page pull never restarts
from zero. Cold load is about 25 minutes.
