"""Pull the PJM feeds this project needs into Postgres staging tables.

Partitioned and resumable: every (feed, partition) that completes is recorded in
ingest_log, and re-running skips it. At ~5.5 requests/minute a cold run is roughly 20
minutes, almost all of it the FTR bid stack.

    python etl/ingest.py              # everything still outstanding
    python etl/ingest.py pnode        # just one feed
    python etl/ingest.py --force      # re-load even if logged
"""

from __future__ import annotations

import sys
from datetime import date

from db import already_loaded, connect, copy_rows, log_partition
from pjm_client import PJMClient

# ---------------------------------------------------------------------------------------
# What to pull.
#
# ftr_cong_lmp is cheap (~14.5k rows per month for all of PJM), so take a wide window and
# pull it a quarter at a time -- each quarter still fits inside a single 50k-row page.
#
# ftr_bids_mnt is the opposite: 164M rows total, ~1.44M per monthly auction, and PJM
# accepts no node-level filter on it (sink_pnode_name is rejected as an invalid filter
# field). So the only lever is auction count. Three auctions spanning winter peak, summer
# peak and shoulder is enough to test whether bidders track the simulation, at ~29 pages
# each instead of ~350 for a full year.
# ---------------------------------------------------------------------------------------

CONG_LMP_START = date(2024, 1, 1)
CONG_LMP_END = date(2026, 6, 30)

BID_AUCTIONS = ["JAN 2025 Auction", "JUL 2025 Auction", "OCT 2025 Auction"]


def _quarters(start: date, end: date) -> list[tuple[date, date]]:
    out: list[tuple[date, date]] = []
    y, q = start.year, (start.month - 1) // 3
    while True:
        q_start = date(y, q * 3 + 1, 1)
        ny, nq = (y + 1, 0) if q == 3 else (y, q + 1)
        q_end = date(ny, nq * 3 + 1, 1)
        if q_start > end:
            break
        out.append((max(q_start, start), min(q_end, end)))
        y, q = ny, nq
    return out


def _mdy(d: date) -> str:
    """PJM's date filters want M/D/YYYY."""
    return f"{d.month}/{d.day}/{d.year}"


def _num(v):
    return None if v in ("", None) else v


# ---------------------------------------------------------------------------------------


def ingest_pnode(client: PJMClient, conn, force: bool) -> None:
    feed, part = "pnode", "all"
    if already_loaded(conn, feed, part) and not force:
        print(f"[skip] {feed}/{part}")
        return

    cols = [
        "pnode_id", "pnode_name", "pnode_type", "pnode_subtype",
        "zone", "voltage_level", "effective_date", "termination_date",
    ]
    with conn.cursor() as cur:
        cur.execute("TRUNCATE stg_pnode")

    total = 0
    for page in client.pages(feed):
        total += copy_rows(
            conn, "stg_pnode", cols,
            ([
                r.get("pnode_id"), r.get("pnode_name"), r.get("pnode_type"),
                r.get("pnode_subtype"), r.get("zone"), r.get("voltage_level"),
                r.get("effective_date"), r.get("termination_date"),
            ] for r in page),
        )
    log_partition(conn, feed, part, total, total)
    conn.commit()
    print(f"[ok] {feed}/{part}: {total:,} rows")


def ingest_ftr_cong_lmp(client: PJMClient, conn, force: bool) -> None:
    feed = "ftr_cong_lmp"
    cols = [
        "effective_day", "terminate_day", "pnode_name",
        "offpeak_clmp", "dailyoffpeak_clmp", "onpeak_clmp", "wkndonpeak_clmp", "h24_clmp",
        "lt_sim_offpeak_clmp", "lt_sim_dailyoffpeak_clmp", "lt_sim_onpeak_clmp",
        "lt_sim_wkndonpeak_clmp", "lt_sim_clmp",
    ]

    for q_start, q_end in _quarters(CONG_LMP_START, CONG_LMP_END):
        part = q_start.strftime("%Yq") + str((q_start.month - 1) // 3 + 1)
        if already_loaded(conn, feed, part) and not force:
            print(f"[skip] {feed}/{part}")
            continue

        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM stg_ftr_cong_lmp WHERE effective_day >= %s AND effective_day < %s",
                (q_start, q_end),
            )

        filt = {"effective_day": f"{_mdy(q_start)}to{_mdy(q_end)}"}
        total = 0
        for page in client.pages(feed, **filt):
            total += copy_rows(
                conn, "stg_ftr_cong_lmp", cols,
                ([
                    r.get("effective_day"), r.get("terminate_day"), r.get("pnode_name"),
                    _num(r.get("offpeak_clmp")), _num(r.get("dailyoffpeak_clmp")),
                    _num(r.get("onpeak_clmp")), _num(r.get("wkndonpeak_clmp")),
                    # PJM names this column with a leading digit; see 01_schema.sql.
                    _num(r.get("24hour_clmp")),
                    _num(r.get("lt_sim_offpeak_clmp")), _num(r.get("lt_sim_dailyoffpeak_clmp")),
                    _num(r.get("lt_sim_onpeak_clmp")), _num(r.get("lt_sim_wkndonpeak_clmp")),
                    _num(r.get("lt_sim_clmp")),
                ] for r in page),
            )
        log_partition(conn, feed, part, total, total)
        conn.commit()
        print(f"[ok] {feed}/{part}: {total:,} rows")


def ingest_ftr_bids(client: PJMClient, conn, force: bool) -> None:
    feed = "ftr_bids_mnt"
    cols = [
        "market_name", "period_type", "source_pnode_name", "sink_pnode_name",
        "class_type", "trade_type", "quoted_mw", "quoted_price", "hedge_type",
    ]

    for market in BID_AUCTIONS:
        part = market
        if already_loaded(conn, feed, part) and not force:
            print(f"[skip] {feed}/{part}")
            continue

        with conn.cursor() as cur:
            cur.execute("DELETE FROM stg_ftr_bid_mnt WHERE market_name = %s", (market,))

        api_total = client.total_rows(feed, market_name=market)
        if not api_total:
            print(f"[warn] {feed}/{part}: API reports 0 rows -- check the market_name string")
            continue

        total = 0
        for page in client.pages(feed, market_name=market):
            total += copy_rows(
                conn, "stg_ftr_bid_mnt", cols,
                ([
                    r.get("market_name"), r.get("period_type"),
                    r.get("source_pnode_name"), r.get("sink_pnode_name"),
                    r.get("class_type"), r.get("trade_type"),
                    _num(r.get("quoted_mw")), _num(r.get("quoted_price")), r.get("hedge_type"),
                ] for r in page),
            )
            conn.commit()  # checkpoint each page; a 29-page pull should not restart from zero
            print(f"      {feed}/{part}: {total:,}/{api_total:,}", flush=True)

        log_partition(conn, feed, part, total, api_total)
        conn.commit()
        status = "ok" if total == api_total else "MISMATCH"
        print(f"[{status}] {feed}/{part}: {total:,} rows (API said {api_total:,})")


FEEDS = {
    "pnode": ingest_pnode,
    "ftr_cong_lmp": ingest_ftr_cong_lmp,
    "ftr_bids_mnt": ingest_ftr_bids,
}


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    force = "--force" in sys.argv
    wanted = args or list(FEEDS)

    unknown = [w for w in wanted if w not in FEEDS]
    if unknown:
        print(f"unknown feed(s): {unknown}. known: {list(FEEDS)}", file=sys.stderr)
        return 2

    client = PJMClient()
    with connect() as conn:
        for name in wanted:
            FEEDS[name](client, conn, force)

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT feed, partition, rows_loaded, api_total
                FROM ingest_log ORDER BY feed, partition
                """
            )
            print("\n=== ingest_log ===")
            for feed, part, loaded, api_total in cur.fetchall():
                flag = "" if api_total in (None, loaded) else "  <-- MISMATCH"
                print(f"  {feed:<16} {part:<18} {loaded:>10,}{flag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
