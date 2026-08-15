"""Append-only override registry (I-30 / R-017) — records before decision is affected."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

from instrument_identity import ticker_storage_key

OVERRIDE_REGISTRY_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS decision_override_registry (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    recorded_at_utc     REAL NOT NULL,
    ticker              TEXT NOT NULL,
    route               TEXT NOT NULL,
    override_source     TEXT NOT NULL,
    override_direction  TEXT,
    override_payload_json TEXT NOT NULL,
    decision_id_before  TEXT,
    release_id          TEXT
);
CREATE INDEX IF NOT EXISTS idx_override_registry_ticker_ts
    ON decision_override_registry (ticker, recorded_at_utc DESC);
"""


def ensure_override_registry_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(OVERRIDE_REGISTRY_TABLE_SQL)


def append_override_record(
    *,
    ticker: str,
    route: str,
    override_source: str,
    override_direction: Optional[str],
    override_payload: dict[str, Any],
    db_path: Path | str,
    decision_id_before: Optional[str] = None,
    release_id: Optional[str] = None,
) -> int:
    """Append-only — returns row id."""
    path = Path(db_path)
    conn = sqlite3.connect(str(path), timeout=30.0)
    try:
        ensure_override_registry_schema(conn)
        cur = conn.execute(
            """
            INSERT INTO decision_override_registry (
                recorded_at_utc, ticker, route, override_source, override_direction,
                override_payload_json, decision_id_before, release_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                time.time(),
                ticker_storage_key(ticker),  # RC-345/F25: canonical override identity (WRITE)
                route,
                override_source,
                override_direction,
                json.dumps(override_payload, sort_keys=True, default=str),
                decision_id_before,
                release_id,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def count_override_records(db_path: Path | str, *, ticker: Optional[str] = None) -> int:
    path = Path(db_path)
    if not path.is_file():
        return 0
    conn = sqlite3.connect(str(path), timeout=30.0)
    try:
        ensure_override_registry_schema(conn)
        if ticker:
            row = conn.execute(
                "SELECT COUNT(*) FROM decision_override_registry WHERE ticker = ?",
                (ticker_storage_key(ticker),),  # RC-345/F25: canonical override identity (READ matches WRITE)
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) FROM decision_override_registry").fetchone()
        return int(row[0]) if row else 0  # caps-ok: COUNT(*) always returns one row; the else-0 is unreachable defensive and equals the true count of an empty registry
    finally:
        conn.close()
