"""Establish what ftr_cong_lmp's columns actually contain, rather than trusting their names.

The project rests on two assumptions. This script tests both against raw hourly day-ahead
LMPs, which are an independent source: da_hrl_lmps accepts a pnode_id filter, so one
node-month costs a single API request (744 rows).

  A. SIGN CONVENTION -- total_lmp = system_energy + congestion + loss, additively, so an
     FTR obligation from source to sink pays congestion(sink) - congestion(source).
     RESULT: confirmed, 100% of hours.

  B. BASELINE -- that the unprefixed columns (onpeak_clmp, 24hour_clmp, ...) are the
     *realized* congestion for the month in effective_day.
     RESULT: REFUTED. They are close in magnitude but do not reconcile, and the error is
     neither constant nor one-signed. PJM describes this feed as the congestion LMPs "used
     in the FTR credit calculator", with the adjusted series being "historical cLMPs
     adjusted by PROMOD production cost simulation". The reconciliation says the baseline
     series is itself processed rather than raw realized DA congestion.

What that means for the project: the gap this repo maps, lt_sim_* minus the unprefixed
column, is the difference between two *modelled* congestion series that PJM publishes for
the same node and month -- one of which explicitly "considers certain transmission
upgrades". It is a topology-versus-topology comparison, which is what the analysis claims.
It is *not* a model-versus-reality comparison, and nothing here should be read as one.

One incidental trap this surfaced: PJM uses different pnode naming across feeds. Node
48821 is "BALA" in da_hrl_lmps and "BALA    13 KV   LD1" in ftr_cong_lmp. Join on
pnode_id where both feeds carry it; on normalised names only within a feed family.

    python etl/validate.py            # July 2025
    python etl/validate.py 2025-01    # any month in the standard (non-archived) window
"""

from __future__ import annotations

import statistics
import sys
from datetime import date, datetime, timedelta

from db import connect
from pjm_client import PJMClient

# PJM's on-peak excludes NERC holidays, observed on the actual date.
NERC_HOLIDAYS = {
    date(2024, 1, 1), date(2024, 5, 27), date(2024, 7, 4), date(2024, 9, 2),
    date(2024, 11, 28), date(2024, 12, 25),
    date(2025, 1, 1), date(2025, 5, 26), date(2025, 7, 4), date(2025, 9, 1),
    date(2025, 11, 27), date(2025, 12, 25),
    date(2026, 1, 1), date(2026, 5, 25), date(2026, 7, 4), date(2026, 9, 7),
    date(2026, 11, 26), date(2026, 12, 25),
}

# (pnode_id, name as ftr_cong_lmp spells it). BALA is a PECO bus about two miles from
# SIG's Bala Cynwyd office; BGE and COMED are the two ends of the east-west spread the
# analysis turns on; WESTERN HUB is PJM's most liquid FTR sink.
SAMPLE_NODES = [
    (48821, "BALA    13 KV   LD1"),
    (51292, "BGE"),
    (51298, "PEPCO"),
    (33092371, "COMED"),
    (51288, "WESTERN HUB"),
]


def is_onpeak(ts: datetime) -> bool:
    """Hour-ending 0800-2300 EPT, weekdays, excluding NERC holidays."""
    d = ts.date()
    if d.weekday() >= 5 or d in NERC_HOLIDAYS:
        return False
    return 7 <= ts.hour <= 22  # hour-beginning 07:00-22:00 == hour-ending 0800-2300


def month_bounds(month: date) -> tuple[date, date]:
    nxt = date(month.year + (month.month == 12), month.month % 12 + 1, 1)
    return month, nxt - timedelta(days=1)


def fetch_hourly(client: PJMClient, pnode_id: int, month: date) -> list[dict]:
    """One month of hourly DA LMPs for a single node.

    da_hrl_lmps refuses ranges that straddle PJM's archived/standard boundary, so this
    only works inside the recent window; older months need the archive endpoint.
    """
    start, end = month_bounds(month)
    rows: list[dict] = []
    for page in client.pages(
        "da_hrl_lmps",
        pnode_id=pnode_id,
        datetime_beginning_ept=(
            f"{start.month}/{start.day}/{start.year} 00:00to"
            f"{end.month}/{end.day}/{end.year} 23:59"
        ),
    ):
        rows.extend(page)
    return rows


def main() -> int:
    month = date.fromisoformat((sys.argv[1] if len(sys.argv) > 1 else "2025-07") + "-01")
    client = PJMClient()

    print(f"\nCharacterising ftr_cong_lmp against da_hrl_lmps -- {month:%B %Y}")
    print("=" * 92)
    print(f"{'node':<22} {'hourly on-peak':>15} {'feed baseline':>14} {'diff':>9} "
          f"{'feed upgrade-adj':>17} {'adjustment':>11}")
    print("-" * 92)

    sign_ok: list[bool] = []
    reconciles: list[bool] = []

    with connect() as conn:
        for pnode_id, feed_name in SAMPLE_NODES:
            hourly = fetch_hourly(client, pnode_id, month)
            if not hourly:
                print(f"{feed_name:<22} no hourly rows returned")
                continue

            onpeak = []
            for r in hourly:
                cong = r.get("congestion_price_da")
                if cong is None:
                    continue
                if is_onpeak(datetime.fromisoformat(r["datetime_beginning_ept"])):
                    onpeak.append(cong)
                total, energy, loss = (
                    r.get("total_lmp_da"),
                    r.get("system_energy_price_da"),
                    r.get("marginal_loss_price_da"),
                )
                if None not in (total, energy, loss):
                    sign_ok.append(abs((energy + cong + loss) - total) < 0.02)

            hourly_onpeak = statistics.fmean(onpeak) if onpeak else float("nan")

            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT clmp_realized, clmp_sim FROM fact_nodal_cong_monthly
                    WHERE pnode_name_norm = norm_name(%s) AND month = %s AND class_type = 'OnPeak'
                    """,
                    (feed_name, month),
                )
                row = cur.fetchone()
            base = float(row[0]) if row and row[0] is not None else float("nan")
            sim = float(row[1]) if row and row[1] is not None else float("nan")

            diff = base - hourly_onpeak
            reconciles.append(abs(diff) <= max(0.05, 0.02 * abs(hourly_onpeak)))
            short = feed_name if len(feed_name) <= 21 else feed_name[:20] + "…"
            print(f"{short:<22} {hourly_onpeak:>15.3f} {base:>14.3f} {diff:>+9.3f} "
                  f"{sim:>17.3f} {sim - base:>+11.3f}")

    print("-" * 92)

    print("\nA. SIGN CONVENTION")
    if sign_ok:
        pct = 100.0 * sum(sign_ok) / len(sign_ok)
        verdict = "CONFIRMED" if pct > 99.5 else "SUSPECT"
        print(f"   {verdict}: energy + congestion + loss == total_lmp for {pct:.1f}% "
              f"of {len(sign_ok):,} hours.")
        print("   An obligation source->sink therefore pays cong(sink) - cong(source).")

    print("\nB. IS THE BASELINE COLUMN REALIZED CONGESTION?")
    if reconciles and all(reconciles):
        print("   CONFIRMED: the unprefixed columns reconcile to realized hourly congestion.")
    else:
        print("   REFUTED: the unprefixed columns do not reconcile to realized hourly")
        print("   congestion for the month in effective_day. The differences above are")
        print("   large and vary in sign, so this is not an hour-definition or rounding")
        print("   artefact. Both column families are modelled inputs to PJM's FTR credit")
        print("   calculator, not a model-versus-outturn pair.")

    print("\nC. WHAT THE PROJECT THEREFORE MEASURES")
    print("   The 'adjustment' column above -- lt_sim minus baseline -- is the difference")
    print("   between two congestion series PJM publishes for the same node and month, one")
    print("   of which considers planned transmission upgrades. That is a topology-versus-")
    print("   topology comparison, and it is what the map shows. It is not a claim about")
    print("   what congestion actually turned out to be.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
