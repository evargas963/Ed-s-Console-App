"""Equity book-depth frames (NASDAQ_BOOK / NYSE_BOOK) — schema + one shared row shape.

Section 1 of the finding-#1 migration: the canonical Collect daemon OWNS equity book-depth on its
single StreamClient and persists it through the daemon's ONE CaptureWriter connection (the same
`register_topic_writer` seam options use), never a second connection to stream_capture.db.

This is the exact parallel of calibration/options_stream_frames.py — the Schwab book frame is
structurally identical to an options frame (top-level epoch-ms `timestamp`, a `content` list whose
entries carry `key` = symbol), with the full nested price-level / per-exchange depth inside each
entry. The frame is stored VERBATIM as decoded JSON (no projection); `service` and `symbol_key` are
indexed COPIES lifted from the frame so a reader finds frames without parsing every blob.

CLOCK CONTRACT (same as options): Schwab frame timestamps are epoch MILLISECONDS; our receive clock
(time.time()) is epoch SECONDS. Both are stored in explicit millisecond columns with the unit in the
name so the seconds/ms mix that broke the first options version cannot reappear.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

SERVICE_NASDAQ = "NASDAQ_BOOK"
SERVICE_NYSE = "NYSE_BOOK"
SUPPORTED_SERVICES = (SERVICE_NASDAQ, SERVICE_NYSE)

TABLE_SQL = """
CREATE TABLE IF NOT EXISTS equity_book_frames (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    service           TEXT NOT NULL,     -- NASDAQ_BOOK | NYSE_BOOK
    frame_ts_ms       INTEGER NOT NULL,  -- VENDOR frame timestamp, epoch MILLISECONDS, as sent
    received_ts_ms    INTEGER NOT NULL,  -- OUR receive clock, epoch MILLISECONDS
    ingest_lag_ms     INTEGER,           -- received_ts_ms - frame_ts_ms, computed once, unit-correct
    n_symbols         INTEGER NOT NULL,  -- len(content); >1 means a multi-symbol frame
    payload_json      TEXT NOT NULL,     -- the DECODED frame as received from the client library
    created_at        TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_ebf_service_ts ON equity_book_frames(service, frame_ts_ms);

-- One row per SYMBOL contained in a frame, so a multi-symbol frame stays discoverable for every
-- symbol it carries rather than only its first.
CREATE TABLE IF NOT EXISTS equity_book_frame_symbols (
    frame_id     INTEGER NOT NULL REFERENCES equity_book_frames(id),
    symbol_key   TEXT NOT NULL,
    content_idx  INTEGER NOT NULL,
    PRIMARY KEY (frame_id, content_idx)
);
CREATE INDEX IF NOT EXISTS idx_ebfs_symbol ON equity_book_frame_symbols(symbol_key);
"""


def ensure_equity_book_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(TABLE_SQL)
    conn.commit()


def frame_row_values(service: str, frame: dict[str, Any],
                     received_ts_ms: int) -> tuple | None:
    """Build the equity_book_frames INSERT tuple, or None if the frame is unusable.

    Returning None rather than raising keeps a malformed frame from aborting a batch of good frames
    or taking the daemon down — a rejected frame is counted (0 rows), never silently swallowed.
    """
    if service not in SUPPORTED_SERVICES or not isinstance(frame, dict):
        return None
    try:
        frame_ts_ms = int(frame.get("timestamp"))
        recv_ms = int(received_ts_ms)
    except (TypeError, ValueError):
        return None
    content = frame.get("content")
    return (
        service,
        frame_ts_ms,
        recv_ms,
        recv_ms - frame_ts_ms,
        len(content) if isinstance(content, list) else 0,
        json.dumps(frame, default=str, separators=(",", ":")),
    )


def frame_symbol_entries(frame: dict[str, Any]) -> list[tuple[int, str]]:
    """(content_idx, symbol_key) for EVERY symbol in the frame; entries without a key are skipped."""
    content = frame.get("content") if isinstance(frame, dict) else None
    if not isinstance(content, list):
        return []
    return [(i, c.get("key")) for i, c in enumerate(content)
            if isinstance(c, dict) and c.get("key")]


def frame_symbol_rows(frame_id: int, frame: dict[str, Any]) -> list[tuple[int, str, int]]:
    """equity_book_frame_symbols rows for one stored frame."""
    return [(frame_id, key, idx) for idx, key in frame_symbol_entries(frame)]
