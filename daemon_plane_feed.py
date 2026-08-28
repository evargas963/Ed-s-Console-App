"""Route the canonical Collect daemon's captured L1 + equity books into the live plane — Section 2.

The daemon (a SEPARATE process) is the ONE Schwab StreamClient. It captures equity L1
(stream_quotes_raw, src='schwab_l1') and equity book-depth (equity_book_frames, Section 1) into
stream_capture.db. This module runs IN THE SERVER process, READS the latest captured row per ticker,
and hydrates the two in-process live-plane surfaces:
  * live_market_plane.record_from_level_one_equity  (the quote plane: spot/bid/ask)
  * order_flow_live_state.push_level_one / push_book (top-of-book, tape, book snapshots)
so consumers no longer NEED the UI's own competing Schwab socket.

INVARIANTS this module holds:
  * ONE StreamClient — it opens NO Schwab connection; it only READS the daemon's db.
  * DATA MEANING — the stored L1 columns map 1:1 to the vendor L1 field NAMES the plane already
    ingests (bid->BID_PRICE, last->LAST_PRICE, quote_time_ms->QUOTE_TIME_MILLIS, ...); book frames
    are pushed as the vendor content item (BIDS/ASKS/BOOK_TIME) verbatim. Fields the daemon does not
    capture (e.g. MARK) are honestly ABSENT, never fabricated — parity for those is a Section-3
    precondition, tracked, before the UI socket is retired.
  * BACKPRESSURE/SAFETY — a small periodic read off the request path via a READ-ONLY connection;
    it never touches the quote hot path and each plane surface keeps its own locking.
  * DYNAMIC TICKER VIEWING — it feeds ONLY the tickers the daemon actually captured; any other
    ticker stays on its existing path (UI socket / REST fast-quote), unchanged.

GATE: ED_DAEMON_PLANE_FEED (default OFF). This section adds the capability; enabling the live feed
and retiring the UI socket are later, deliberate steps. Options are not handled here (they stay OFF
and outside Decide).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import time
from typing import Any

log = logging.getLogger(__name__)

ED_DAEMON_PLANE_FEED_ENV = "ED_DAEMON_PLANE_FEED"
_L1_SRC = "schwab_l1"

#: stream_quotes_raw column -> vendor LEVEL_ONE_EQUITY field name. 1:1, no reinterpretation.
_L1_COLUMN_TO_VENDOR = {
    "last": "LAST_PRICE", "bid": "BID_PRICE", "ask": "ASK_PRICE",
    "bid_size": "BID_SIZE", "ask_size": "ASK_SIZE", "last_size": "LAST_SIZE",
    "total_volume": "TOTAL_VOLUME",
    "quote_time_ms": "QUOTE_TIME_MILLIS", "trade_time_ms": "TRADE_TIME_MILLIS",
}


def daemon_plane_feed_enabled() -> bool:
    return str(os.environ.get(ED_DAEMON_PLANE_FEED_ENV, "")).strip().lower() in (
        "1", "true", "yes", "on")


def open_capture_ro(db_path: str) -> sqlite3.Connection:
    """Read-only connection to the daemon's capture db (never writes it).

    check_same_thread=False: the lifespan loop reuses ONE connection but runs each read via
    asyncio.to_thread (a worker thread), while the connection is opened on the event-loop thread.
    Access is strictly SERIAL — each tick is awaited to completion before the next — so this is safe
    (SQLite forbids concurrent use across threads, not sequential use); it is only ever read.
    """
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5.0,
                          check_same_thread=False)
    con.row_factory = sqlite3.Row
    return con


def latest_l1_content(conn: sqlite3.Connection, tickers: list[str]) -> dict[str, dict[str, Any]]:
    """{ticker -> vendor L1 content dict} from the LATEST captured schwab_l1 quote per ticker.

    Uses SQLite's bare-column-with-MAX rule: the non-aggregated columns come from the row whose
    ts_recv is the maximum, i.e. the newest quote. Only NON-NULL captured fields are carried, so an
    absent field never lands as a fabricated value the plane could age.
    """
    if not tickers:
        return {}
    col_items = list(_L1_COLUMN_TO_VENDOR.items())          # [(db_column, vendor_field), ...]
    cols_sql = ", ".join(c for c, _ in col_items)
    placeholders = ", ".join(["?"] * len(tickers))
    q = (f"SELECT symbol, {cols_sql}, MAX(ts_recv) FROM stream_quotes_raw "
         f"WHERE src = ? AND symbol IN ({placeholders}) GROUP BY symbol")
    out: dict[str, dict[str, Any]] = {}
    for row in conn.execute(q, (_L1_SRC, *tickers)):        # POSITIONAL access — no row_factory dependency
        item: dict[str, Any] = {}
        for i, (_col, vendor) in enumerate(col_items, start=1):
            v = row[i]
            if v is not None:
                item[vendor] = v
        if item:
            out[str(row[0])] = item
    return out


def latest_book_items(conn: sqlite3.Connection,
                      tickers: list[str]) -> dict[str, list[dict[str, Any]]]:
    """{ticker -> [latest book content item per service]} from equity_book_frames.

    The daemon captures NASDAQ_BOOK and NYSE_BOOK separately; the UI socket pushed BOTH, so this
    carries the newest of EACH service per ticker. The content item (BIDS/ASKS/BOOK_TIME) is lifted
    verbatim from the stored frame — no reshaping.
    """
    if not tickers:
        return {}
    placeholders = ", ".join(["?"] * len(tickers))
    try:
        rows = conn.execute(
            "SELECT s.symbol_key, f.service, f.payload_json, MAX(f.frame_ts_ms) "
            "FROM equity_book_frames f JOIN equity_book_frame_symbols s ON s.frame_id = f.id "
            f"WHERE s.symbol_key IN ({placeholders}) "
            "GROUP BY s.symbol_key, f.service", tuple(tickers)).fetchall()
    except sqlite3.OperationalError:
        return {}  # equity_book_frames absent (books never captured) — nothing to feed, not an error
    out: dict[str, list[dict[str, Any]]] = {}
    for sym, _service, payload, _ts in rows:               # POSITIONAL — no row_factory dependency
        try:
            frame = json.loads(payload)
        except (TypeError, ValueError):
            continue
        content = frame.get("content") if isinstance(frame, dict) else None
        if not isinstance(content, list):
            continue
        entry = next((c for c in content if isinstance(c, dict)
                      and str(c.get("key", "")).upper() == str(sym).upper()), None)
        if entry is None and content and isinstance(content[0], dict):
            entry = content[0]
        if isinstance(entry, dict) and entry.get("BIDS") and entry.get("ASKS"):
            out.setdefault(str(sym), []).append(entry)
    return out


def feed_once(conn: sqlite3.Connection, tickers: list[str]) -> dict[str, int]:
    """Hydrate BOTH plane surfaces from the daemon's latest captures for `tickers`. Returns counts.

    Isolated per surface: importing the plane locally keeps this module load-order-safe and lets the
    feed be tested against the pure db-read helpers without pulling the whole server graph.
    """
    from live_market_plane import record_from_level_one_equity
    from order_flow_live_state import push_book, push_level_one

    l1 = latest_l1_content(conn, tickers)
    books = latest_book_items(conn, tickers)
    n_quote = n_book = 0
    for sym, item in l1.items():
        try:
            push_level_one(sym, item)            # order-flow: top-of-book + tape + volume
            if record_from_level_one_equity(sym, item):  # quote plane: spot/bid/ask
                n_quote += 1
        except Exception as e:                    # noqa: BLE001 — a feed error must not crash the loop
            log.debug("daemon plane L1 feed %s: %s", sym, e)
    for sym, items in books.items():
        for entry in items:
            try:
                push_book(sym, entry)
                n_book += 1
            except Exception as e:                # noqa: BLE001
                log.debug("daemon plane book feed %s: %s", sym, e)
    return {"l1": len(l1), "quote_updates": n_quote, "book": n_book}


def captured_tickers(conn: sqlite3.Connection, *, lookback_s: float = 300.0) -> list[str]:
    """Tickers the daemon has captured L1 for in the last `lookback_s` — a small fixed set. The feed
    touches ONLY these, so a dynamically-viewed ticker the daemon never captured stays on its
    existing path (UI socket / REST), untouched."""
    since = time.time() - lookback_s
    try:
        return [str(r[0]) for r in conn.execute(
            "SELECT DISTINCT symbol FROM stream_quotes_raw WHERE src = ? AND ts_recv > ?",
            (_L1_SRC, since)) if r[0]]
    except sqlite3.OperationalError:
        return []


async def run_daemon_plane_feed(db_path: str, *, interval_s: float = 3.0,
                                lookback_s: float = 300.0) -> None:
    """Server-lifespan background loop (started only when ED_DAEMON_PLANE_FEED is on): every
    `interval_s`, hydrate the plane from the daemon's most recent captures for the tickers it
    actually captured. Backpressure-safe — ONE reused READ-ONLY connection, the db read + plane
    writes run OFF the event loop via asyncio.to_thread, a tick error is logged and retried (never
    crashes the loop), and the loop exits cleanly on cancellation at shutdown."""
    conn: sqlite3.Connection | None = None
    log.info("daemon->plane feed loop started (db=%s, interval=%.1fs)", db_path, interval_s)
    try:
        while True:
            try:
                if conn is None:
                    conn = open_capture_ro(db_path)

                def _tick(c: sqlite3.Connection) -> dict[str, int]:
                    tks = captured_tickers(c, lookback_s=lookback_s)
                    return feed_once(c, tks) if tks else {"l1": 0, "quote_updates": 0, "book": 0}

                await asyncio.to_thread(_tick, conn)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 — a tick error must never crash the loop
                log.debug("daemon plane feed tick: %s", e)
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:  # noqa: BLE001
                        pass
                    conn = None
            await asyncio.sleep(interval_s)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
