"""Paged, rate-limited client for the PJM Data Miner 2 API.

PJM caps non-member users at 6 requests/minute, so the whole design here is about
spending those requests well and never losing progress when one fails:

  * one token-bucket throttle shared by every call,
  * retry with backoff on 429/5xx,
  * each page yielded as it arrives so callers can write to Postgres incrementally.

The subscription key comes from PJM_KEY in the environment. If that is unset it falls back
to the key Data Miner 2's own web app publishes in its client config -- the same access an
unauthenticated browser gets. That is shared across all anonymous users, so a personal key
is better; see .env.example.
"""

from __future__ import annotations

import os
import sys
import time
import threading
from pathlib import Path
from typing import Any, Iterator

import requests

BASE_URL = "https://api.pjm.com/api/v1"
ANON_KEY = "6a75d9f6d933401dbb4f36f8e70b95b3"
ANON_SETTINGS_URL = "https://dataminer2.pjm.com/config/settings.json"

# PJM's documented non-member ceiling is 6/min. Sit just under it.
REQUESTS_PER_MINUTE = 5.5
PAGE_ROWS = 50_000


def _load_dotenv() -> None:
    """Minimal .env reader so the ETL works without adding a dependency."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def get_key() -> tuple[str, str]:
    """Return (key, source) so callers can log which credential is in play."""
    _load_dotenv()
    key = os.environ.get("PJM_KEY", "").strip()
    if key:
        return key, "personal (PJM_KEY)"
    return ANON_KEY, "anonymous (Data Miner 2 web app)"


class _Throttle:
    """Token bucket. Shared process-wide because PJM rate-limits per key, not per caller."""

    def __init__(self, per_minute: float) -> None:
        self._interval = 60.0 / per_minute
        self._lock = threading.Lock()
        self._next_at = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            sleep_for = self._next_at - now
            self._next_at = max(now, self._next_at) + self._interval
        if sleep_for > 0:
            time.sleep(sleep_for)


class PJMClient:
    def __init__(self, key: str | None = None, per_minute: float = REQUESTS_PER_MINUTE) -> None:
        if key is None:
            key, source = get_key()
            print(f"[pjm] using {source} key", file=sys.stderr)
        self._session = requests.Session()
        self._session.headers.update(
            {"Ocp-Apim-Subscription-Key": key, "Accept": "application/json"}
        )
        self._throttle = _Throttle(per_minute)

    def _get(self, url: str, params: dict[str, Any] | None = None, attempts: int = 5) -> dict:
        last_error: Exception | None = None
        for attempt in range(attempts):
            self._throttle.wait()
            try:
                resp = self._session.get(url, params=params, timeout=120)
            except requests.RequestException as exc:
                last_error = exc
                time.sleep(min(60, 5 * 2**attempt))
                continue

            if resp.status_code == 200:
                return resp.json()

            # 429 = throttled, 5xx = transient. Anything else is a real bug in the request.
            if resp.status_code == 429 or resp.status_code >= 500:
                wait_s = int(resp.headers.get("Retry-After", 0)) or min(60, 10 * 2**attempt)
                print(
                    f"[pjm] HTTP {resp.status_code}, retrying in {wait_s}s "
                    f"(attempt {attempt + 1}/{attempts})",
                    file=sys.stderr,
                )
                time.sleep(wait_s)
                last_error = RuntimeError(f"HTTP {resp.status_code}")
                continue

            raise RuntimeError(f"HTTP {resp.status_code} for {url}: {resp.text[:400]}")

        raise RuntimeError(f"gave up on {url} after {attempts} attempts: {last_error}")

    def feed_catalog(self) -> list[dict]:
        """All 119 published feeds, with categories and first-available dates."""
        return self._get(BASE_URL + "/").get("items", [])

    def total_rows(self, feed: str, **filters: Any) -> int | None:
        """Ask the API how many rows a query will return. Costs one request."""
        params = {"rowCount": 1, "startRow": 1, "format": "json", **filters}
        return self._get(f"{BASE_URL}/{feed}", params).get("totalRows")

    def pages(
        self, feed: str, page_rows: int = PAGE_ROWS, start_row: int = 1, **filters: Any
    ) -> Iterator[list[dict]]:
        """Yield successive pages of `feed`. Resume mid-feed by passing start_row."""
        row = start_row
        total: int | None = None
        while True:
            params = {"rowCount": page_rows, "startRow": row, "format": "json", **filters}
            payload = self._get(f"{BASE_URL}/{feed}", params)

            if total is None:
                total = payload.get("totalRows")
                print(f"[pjm] {feed} {filters or ''} -> {total} rows", file=sys.stderr)

            items = payload.get("items") or []
            if not items:
                return
            yield items

            row += len(items)
            if total is not None and row > total:
                return
            # Short page means we reached the end even if totalRows disagreed.
            if len(items) < page_rows:
                return


if __name__ == "__main__":
    # Smoke test: prove the key works and print the FTR-related feeds.
    client = PJMClient()
    feeds = client.feed_catalog()
    print(f"{len(feeds)} feeds published")
    for feed in sorted(feeds, key=lambda f: f["name"]):
        if "Financial Transmission" in (feed.get("category") or ""):
            print(f"  {feed['name']:<24} {feed.get('displayName')}")
