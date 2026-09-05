"""Replay persisted option observations through the canonical state owner.

This module owns only historical I/O, bounds, and receive chronology. State
transition semantics live in ``app.options.order_flow.state.OrderFlowState``.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from instrument_identity import ticker_storage_key
from app.options.order_flow.state import OrderFlowState
from stream_spine import resolve_stream_db_path


def hydrate_option_content(
    contract: str,
    *,
    since_ts: float,
    db_path: str | Path | None = None,
    limit: int = 400,
) -> list[dict[str, Any]]:
    """Return isolated canonical content from persisted L1 and book observations."""
    sym = ticker_storage_key(contract) or str(contract or "").strip()
    if not sym:
        return []
    try:
        bounded_limit = max(0, int(limit))
        lower_bound = float(since_ts)
    except (TypeError, ValueError):
        return []
    if bounded_limit == 0:
        return []
    path = resolve_stream_db_path(db_path)
    if not path.is_file():
        return []
    try:
        con = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    except sqlite3.Error:
        return []
    try:
        con.execute("PRAGMA query_only=ON")
        con.execute("BEGIN")
        l1 = con.execute(
            "SELECT rowid, ts_recv, native_json FROM stream_options_quotes_raw "
            "WHERE symbol = ? AND ts_recv >= ? "
            "ORDER BY ts_recv DESC, rowid DESC LIMIT ?",
            (sym, lower_bound, bounded_limit),
        ).fetchall()
        book = con.execute(
            "SELECT rowid, ts_recv, native_json FROM stream_book_raw "
            "WHERE symbol = ? AND service = 'OPTIONS_BOOK' AND ts_recv >= ? "
            "ORDER BY ts_recv DESC, rowid DESC LIMIT ?",
            (sym, lower_bound, bounded_limit),
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        con.close()

    # Existing live DB replay applies L1 before book when receive timestamps tie.
    # rowid preserves deterministic insertion order only within its own table; it
    # is not assigned financial meaning across services.
    events: list[tuple[float, int, int, str, dict[str, Any]]] = []
    for kind, service_order, rows in (("l1", 0, l1), ("book", 1, book)):
        for rowid, ts_recv, native_json in rows:
            try:
                item = json.loads(native_json)
            except (TypeError, ValueError):
                continue
            if isinstance(item, dict):
                events.append(
                    (float(ts_recv), service_order, int(rowid), kind, dict(item))
                )
    events.sort(key=lambda event: event[:3])

    state = OrderFlowState()
    for ts_recv, _service_order, _rowid, kind, item in events:
        if kind == "l1":
            state.push_level_one(sym, item, ts_recv=ts_recv)
        else:
            state.push_book(sym, item)
    return state.get_content_for_symbol(sym)
