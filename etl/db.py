"""Postgres connection helper shared by the ETL scripts."""

from __future__ import annotations

import os
from typing import Any, Iterable, Sequence

import psycopg

from pjm_client import _load_dotenv


def connect() -> psycopg.Connection:
    _load_dotenv()
    return psycopg.connect(
        host=os.environ.get("PGHOST", "localhost"),
        port=int(os.environ.get("PGPORT", "5433")),
        dbname=os.environ.get("PGDATABASE", "ftr"),
        user=os.environ.get("PGUSER", "ftr"),
        password=os.environ.get("PGPASSWORD", "ftr_local_dev"),
        autocommit=False,
    )


def copy_rows(
    conn: psycopg.Connection, table: str, columns: Sequence[str], rows: Iterable[Sequence[Any]]
) -> int:
    """Bulk-load via COPY. Returns the row count written."""
    collist = ", ".join(columns)
    written = 0
    with conn.cursor() as cur:
        with cur.copy(f"COPY {table} ({collist}) FROM STDIN") as copy:
            for row in rows:
                copy.write_row(row)
                written += 1
    return written


def already_loaded(conn: psycopg.Connection, feed: str, partition: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM ingest_log WHERE feed = %s AND partition = %s", (feed, partition)
        )
        return cur.fetchone() is not None


def log_partition(
    conn: psycopg.Connection, feed: str, partition: str, rows_loaded: int, api_total: int | None
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ingest_log (feed, partition, rows_loaded, api_total, loaded_at)
            VALUES (%s, %s, %s, %s, now())
            ON CONFLICT (feed, partition) DO UPDATE
              SET rows_loaded = EXCLUDED.rows_loaded,
                  api_total   = EXCLUDED.api_total,
                  loaded_at   = EXCLUDED.loaded_at
            """,
            (feed, partition, rows_loaded, api_total),
        )
