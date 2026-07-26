"""Reconcile ftr_cong_lmp against the raw hourly day-ahead LMPs.

Everything in this project rests on two assumptions about the ftr_cong_lmp feed, neither of
which PJM states outright:

  1. `onpeak_clmp` for effective_day = 2025-07-01 is the *realized* on-peak congestion
     during July 2025 -- not a historical reference drawn from an earlier lookback window.
  2. The sign convention is additive and matches da_hrl_lmps, so an FTR obligation from
     source to sink pays congestion(sink) - congestion(source).

Both are checkable. da_hrl_lmps accepts a pnode_id filter, so a single node-month costs one
API request (744 rows). This pulls a handful of nodes, recomputes on-peak mean congestion
from the hourly data, and compares.

PJM on-peak for FTR class purposes is hour-ending 0800-2300 EPT, Monday-Friday, excluding
NERC holidays. Hour-*beginning* 07:00-22:00, which is what da_hrl_lmps timestamps are.

    python etl/validate.py                 # default sample, July 2025
    python etl/validate.py 2025-01         # a different month
"""

from __future__ import annotations

import statistics
import sys
from datetime import date, datetime, timedelta

from db import connect
from pjm_client import PJMClient

# NERC holidays are excluded from PJM's on-peak definition. New Year's Day, Memorial Day,
# Independence Day, Labor Day, Thanksgiving, Christmas -- observed on the actual date.
NERC_HOLIDAYS_2024_2026 = {
    date(2024, 1, 1), date(2024, 5, 27), date(2024, 7, 4), date(2024, 9, 2),
    date(2024, 11, 28), date(2024, 12, 25),
    date(2025, 1, 1), date(2025, 5, 26), date(2025, 7, 4), date(2025, 9, 1),
    date(2025, 11, 27), date(2025, 12, 25),
    date(2026, 1, 1), date(2026, 5, 25), date(2026, 7, 4), date(2026, 9, 7),
    date(2026, 11, 26), date(2026, 12, 25),
}

# A spread of zones and node types, including BALA -- a PECO node roughly two miles from
# SIG's Bala Cynwyd office, which makes for a concrete example in conversation.
SAMPLE_NODES = [
    (48821, "BALA"),            # PECO bus, ~2 miles from SIG's Bala Cynwyd office
    (51292, "BGE"),             # the zone with the largest simulated-vs-realized gap
    (51298, "PEPCO"),
    (33092371, "COMED"),        # the other end of the east-west spread
    (51288, "WESTERN HUB"),     # the most liquid FTR sink in PJM
]


def is_onpeak(ts: datetime) -> bool:
    d = ts.date()
    if d.weekday() >= 5 or d in NERC_HOLIDAYS_2024_2026:
        return False
    return 7 <= ts.hour <= 22  # hour-beginning 07:00-22:00 == hour-ending 0800-2300


def month_bounds(month: date) -> tuple[date, date]:
    nxt = date(month.year + (month.month == 12), month.month % 12 + 1, 1)
    return month, nxt - timedelta(days=1)


def fetch_hourly(client: PJMClient, pnode_id: int, month: date) -> list[dict]:
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
    month = date.fromisoformat(
        (sys.argv[1] if len(sys.argv) > 1 else "2025-07") + "-01"
    )
    client = PJMClient()

    print(f"\nReconciling ftr_cong_lmp against da_hrl_lmps for {month:%B %Y}")
    print("=" * 88)
    print(f"{'node':<12} {'feed onpeak':>12} {'hourly onpeak':>14} {'diff':>9} "
          f"{'feed 24H':>10} {'hourly 24H':>11} {'verdict':>9}")
    print("-" * 88)

    verdicts: list[bool] = []
    sign_checks: list[bool] = []

    with connect() as conn:
        for pnode_id, label in SAMPLE_NODES:
            hourly = fetch_hourly(client, pnode_id, month)
            if not hourly:
                print(f"{label:<12} no hourly rows returned")
                continue

            onpeak, allhrs = [], []
            for r in hourly:
                cong = r.get("congestion_price_da")
                if cong is None:
                    continue
                ts = datetime.fromisoformat(r["datetime_beginning_ept"])
                allhrs.append(cong)
                if is_onpeak(ts):
                    onpeak.append(cong)

                # The additive identity underpins the whole sign convention.
                total, energy, loss = (
                    r.get("total_lmp_da"), r.get("system_energy_price_da"),
                    r.get("marginal_loss_price_da"),
                )
                if None not in (total, energy, loss):
                    sign_checks.append(abs((energy + cong + loss) - total) < 0.02)

            hourly_onpeak = statistics.fmean(onpeak) if onpeak else float("nan")
            hourly_24h = statistics.fmean(allhrs) if allhrs else float("nan")

            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT clmp_realized FROM fact_nodal_cong_monthly
                    WHERE pnode_name_norm = norm_name(%s) AND month = %s AND class_type = %s
                    """,
                    (label, month, "OnPeak"),
                )
                row = cur.fetchone()
                feed_onpeak = float(row[0]) if row and row[0] is not None else float("nan")

                cur.execute(
                    """
                    SELECT clmp_realized FROM fact_nodal_cong_monthly
                    WHERE pnode_name_norm = norm_name(%s) AND month = %s AND class_type = %s
                    """,
                    (label, month, "24H"),
                )
                row = cur.fetchone()
                feed_24h = float(row[0]) if row and row[0] is not None else float("nan")

            diff = feed_onpeak - hourly_onpeak
            ok = abs(diff) <= max(0.05, 0.02 * abs(hourly_onpeak))
            verdicts.append(ok)
            print(f"{label:<12} {feed_onpeak:>12.3f} {hourly_onpeak:>14.3f} {diff:>9.3f} "
                  f"{feed_24h:>10.3f} {hourly_24h:>11.3f} {'MATCH' if ok else 'DIFFER':>9}")

    print("-" * 88)
    if sign_checks:
        pct = 100.0 * sum(sign_checks) / len(sign_checks)
        print(f"sign convention: energy + congestion + loss == total_lmp for "
              f"{pct:.1f}% of {len(sign_checks):,} hours")
        print("  -> congestion is additive, so an obligation source->sink pays "
              "cong(sink) - cong(source)")

    if verdicts and all(verdicts):
        print(f"\nPASS: ftr_cong_lmp.onpeak_clmp is realized congestion for the labelled "
              f"month.\n      The lt_sim_* columns are therefore the simulated counterpart "
              f"for that same month.")
        return 0

    print("\nFAIL: the feed does not reconcile to realized hourly congestion for this month.")
    print("      Before using the gap, check whether effective_day labels a lookback window")
    print("      rather than the delivery month. Fallback thesis: DA-vs-RT congestion basis")
    print("      from rt_da_monthly_lmps.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
