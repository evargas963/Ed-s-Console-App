"""Hydrate option L1/book content from the one stream-capture store.

Does not mutate the in-memory live plane. Callers pass the reconstructed
content into ``order_flow_engine`` — the same computation as the live path.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from instrument_identity import ticker_storage_key
from stream_spine import resolve_stream_db_path


def hydrate_option_content(
    contract: str,
    *,
    since_ts: float,
    db_path: str | Path | None = None,
    limit: int = 400,
) -> list[dict[str, Any]]:
    """Replay persisted LEVELONE_OPTIONS + OPTIONS_BOOK rows into content items."""
    sym = ticker_storage_key(contract) or str(contract or "").strip()
    if not sym:
        return []
    path = resolve_stream_db_path(db_path)
    if not path.is_file():
        return []
    try:
        con = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    except sqlite3.Error:
        return []
    items: list[dict[str, Any]] = []
    try:
        l1 = con.execute(
            "SELECT ts_recv, native_json FROM stream_options_quotes_raw "
            "WHERE symbol = ? AND ts_recv >= ? ORDER BY ts_recv DESC LIMIT ?",
            (sym, float(since_ts), int(limit)),
        ).fetchall()
        book = con.execute(
            "SELECT ts_recv, native_json FROM stream_book_raw "
            "WHERE symbol = ? AND service = 'OPTIONS_BOOK' AND ts_recv >= ? "
            "ORDER BY ts_recv DESC LIMIT ?",
            (sym, float(since_ts), int(limit)),
        ).fetchall()
    except sqlite3.Error:
        con.close()
        return []
    con.close()
    # Restore receive order (queries are DESC for a bounded tail).
    for ts_recv, native_json in reversed(l1):
        try:
            item = json.loads(native_json)
        except (TypeError, ValueError):
            continue
        if isinstance(item, dict):
            item = dict(item)
            item["_ts_recv"] = float(ts_recv)
            items.append(item)
    for _ts_recv, native_json in reversed(book):
        try:
            item = json.loads(native_json)
        except (TypeError, ValueError):
            continue
        if isinstance(item, dict):
            items.append(item)
    return items
