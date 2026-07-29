# The 2½-minute screen walkthrough — word for word

Use this the moment you share your screen, after you've covered the data and validation.
It does two jobs: describes what's visible, then proves you understand *why anyone would
pay for it*.

**Start on: 2025-07-01 · OnPeak · PJM view. Nothing selected.**

Read it out loud three times before Wednesday. Not to memorise — to find where you breathe.

---

## [0:00 – 0:25] Orient them

> "So this is PJM — all twenty transmission zones, and PJM is roughly a fifth of US
> electricity demand.
>
> Each zone is coloured by one number: how much congestion changes between **two versions of
> the same grid**. PJM publishes both of them. A baseline network, and that network after
> planned transmission upgrades come into service. Same node, same month, one column apart
> in the feed they use for FTR credit.
>
> Red means the upgraded grid is *more* congested there. Blue means less."

*Don't rush this. They need the axis before they can read the picture.*

---

## [0:25 – 1:00] The pattern

> "And the pattern is the whole story.
>
> Baltimore is up five dollars eighty-seven a megawatt-hour. Washington DC up four thirty-one.
> Virginia and Allegheny up as well.
>
> Everything west of that — ComEd, AEP, Dayton, Kentucky — is negative. Four zones up,
> eighteen down.
>
> So the upgrades don't relieve the Mid-Atlantic. They **widen the gap across it**. The east
> gets more expensive relative to the west, not less."

*Pause here. It's the finding.*

---

## [1:00 – 1:50] Why it's money — the business context

> "Here's why that matters commercially.
>
> An FTR — a financial transmission right — pays you the congestion difference between two
> points. Sink minus source, every hour, for the whole month. That's the entire instrument.
> No physical power, no delivery obligation. It's a pure position on **where congestion shows
> up on the grid.**
>
> So if a topology change moves the ComEd-to-Baltimore spread by seven dollars a
> megawatt-hour, and July has 352 on-peak hours, that's about twenty-five hundred dollars per
> megawatt. On a hundred megawatts, a quarter of a million — for one month, out of a change
> in an assumption about the network.
>
> And the natural other side of that trade is a utility hedging what it costs them to
> deliver power to their own customers. They're not taking a view — they're laying off risk.
> Someone has to take it."

*That last line is the one that says "I understand who's in this market and why."*

---

## [1:50 – 2:20] The trap in the zone number

**→ Click DOM.**

> "But the zone average is a trap, and this is where FTR traders actually live.
>
> Dominion's average is plus one thirty-seven. Its standard deviation across nodes is two
> ninety — more than twice the mean. Of seventeen hundred nodes, eleven fifty move by more
> than a dollar. And this one at the top moves **twenty-seven**.
>
> So a zonal FTR and a nodal FTR are materially different instruments, exactly where the
> topology matters most. If you're a utility hedged at the zone, your basis risk is not what
> the zone number tells you."

---

## [2:20 – 2:40] Land it

> "And that corridor — Baltimore, Washington, northern Virginia — is where the data-centre
> load growth is going.
>
> So it's the part of PJM where this question is about to matter most, and it's the part
> where the zonal hedge is weakest."

**Stop talking.** Let them ask.

---

# The 90-second cut, if they're short on time

Drop the nodal section and the closing.

> "This is PJM's twenty transmission zones, coloured by how much congestion changes between
> two versions of the grid — a baseline, and the same network after planned transmission
> upgrades. PJM publishes both. Red means the upgraded grid is more congested.
>
> Baltimore's up five eighty-seven a megawatt-hour, DC up four thirty-one, while ComEd and
> AEP are negative. Four zones up, eighteen down — the upgrades widen the east–west gap
> rather than relieving the load pocket.
>
> That's tradeable because an FTR pays exactly this: the congestion difference between two
> points, every hour of the month. Seven dollars a megawatt-hour on a ComEd-to-Baltimore path
> over 352 on-peak hours is about twenty-five hundred dollars a megawatt — for one month, from
> a change in a network assumption.
>
> The caveat I'd flag: both of those series are PJM's models. I checked them against raw
> hourly prices and neither is what actually happened. So it's topology versus topology."

---

# If they interrupt

**"Wait — what's congestion, exactly?"**
> "When the cheapest generation can't reach the load because a line would overload, the
> operator has to back it down and start something more expensive nearer the load. The cost
> of that redispatch is congestion, and it's location-specific — that's why the price of
> power is different at every node."

**"Why would the upgrades make it *worse*?"**
> "That's the part I'd want to dig into with someone who knows the planning cases. My read is
> that it's relative, not absolute — the upgrades change how power reaches the load pocket,
> so the price separation across the constraint widens even where absolute cost falls. You
> can see it in the node table: the 500 kV backbone nodes move down while the distribution-
> level load nodes move up. But I'd want to confirm that against the specific binding
> constraints before I'd assert it."

**"Is this a trade you'd put on?"**
> "Not on this alone. It tells you where the topology assumption moves the value, not whether
> the market has already priced it — and I can't see clearing prices, only the bid stack. It's
> a screen for where to look, not a signal."

**"How big is the effect over a year?"**
> "Small most of the time. That's the honest answer — across thirty months it's inside plus or
> minus five cents in most of them. It concentrates in stressed months, and July 2025 dominates
> my sample. Which fits the physics: congestion is a shift-factor-weighted sum of constraint
> shadow prices, so if nothing's binding, changing the network moves nothing."

---

# The two sentences that do the most work

If you remember nothing else from this page:

1. **"An FTR pays the congestion difference between two points — sink minus source, every hour
   of the month. That's the whole instrument."**
   *Proves you know the product.*

2. **"The natural other side is a utility hedging its delivery cost. They're laying off risk;
   someone has to take it."**
   *Proves you know the market, not just the maths.*
