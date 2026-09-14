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


#: Operator field-inventory audit (2026-09-13) — required Options Flow tape columns, locked
#: to the operator's own schema: Time | Symbol | Expiry | Type | Strike | Bid x Size |
#: Ask x Size | Trade | Size | Premium | Volume | OI | IV | Delta | provenance. Trade / Size /
#: Time / Bid / Ask / BidSize / AskSize / Volume / OI / IV / Delta are the vendor's own native
#: LEVELONE_OPTIONS fields, read verbatim off whichever raw tick actually carried the trade —
#: never derived, never estimated. Premium = Trade x Size x native Multiplier (never assumed
#: 100). No buy/sell aggressor side is fabricated anywhere in this module; `classification`
#: states only the mechanical, unambiguous fact of where the print landed relative to the
#: SAME tick's own displayed bid/ask (at bid / at ask / inside spread / outside spread), which
#: is not an aggressor inference — it is a direct comparison of three native numbers.
def tape_rows_for_symbol(
    contract: str,
    *,
    since_ts: float,
    db_path: str | Path | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Discrete TRADE prints for one contract from the native LEVELONE_OPTIONS capture —
    each row is one genuinely NEW (TRADE_TIME_MILLIS, LAST_PRICE, LAST_SIZE) triple, never a
    re-emitted duplicate of the same trade caused by an unrelated field (e.g. a Greek)
    updating on the same underlying tick. Static per-contract context (expiry/strike/type/
    multiplier) is carried forward from the most recent tick that actually reported it — the
    vendor does not repeat that context on every partial update, and this must not silently
    read as if the contract identity were unknown on ticks that omit it.

    Ordered newest-first (tape convention: most recent print on top), bounded by `limit`.
    Fails closed to `[]` on any read/parse error — a tape that cannot be proven is empty,
    never a stale or partial one presented as complete."""
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
        # Read newest-first is not sufficient by itself: a genuinely-new trade must be
        # detected against whatever CAME BEFORE it chronologically (oldest-first), so the
        # scan runs oldest-to-newest and the final list is reversed for display only.
        rows = con.execute(
            "SELECT ts_recv, native_json FROM stream_options_quotes_raw "
            "WHERE symbol = ? AND ts_recv >= ? ORDER BY ts_recv ASC, rowid ASC",
            (sym, lower_bound),
        ).fetchall()
    except sqlite3.Error:
        return []
    finally:
        con.close()

    context: dict[str, Any] = {}
    last_trade_key: tuple[Any, Any, Any] | None = None
    out: list[dict[str, Any]] = []
    for ts_recv, native_json in rows:
        try:
            item = json.loads(native_json)
        except (TypeError, ValueError):
            continue
        if not isinstance(item, dict):
            continue
        for k in ("STRIKE_TYPE", "CONTRACT_TYPE", "EXPIRATION_YEAR", "EXPIRATION_MONTH",
                  "EXPIRATION_DAY", "MULTIPLIER", "UNDERLYING"):
            if item.get(k) is not None:
                context[k] = item[k]
        # A genuine trade print requires its OWN price and its OWN trade timestamp on the
        # SAME tick -- reproduced live against real captured Friday data: a partial update
        # can carry a fresh LAST_SIZE with no LAST_PRICE at all (a size-only field bumping
        # TOTAL_VOLUME on its own), which this loop's OWN de-dup key would otherwise treat
        # as a "new" trade because the tuple differs, emitting a tape row with trade=None
        # and a stray size attached to whatever price happened to print last. Required
        # fields absent -> not a trade print at all, skipped before the de-dup check even
        # runs (so it also never overwrites `last_trade_key`, protecting the NEXT genuine
        # trade's own comparison).
        if item.get("LAST_PRICE") is None or item.get("TRADE_TIME_MILLIS") is None:
            continue
        trade_key = (item["TRADE_TIME_MILLIS"], item["LAST_PRICE"], item.get("LAST_SIZE"))
        if trade_key == last_trade_key:
            continue
        last_trade_key = trade_key
        strike = context.get("STRIKE_TYPE")
        side = {"C": "CALL", "P": "PUT"}.get(context.get("CONTRACT_TYPE"))
        y, m, d = context.get("EXPIRATION_YEAR"), context.get("EXPIRATION_MONTH"), context.get("EXPIRATION_DAY")
        expiry = f"{y:04d}-{m:02d}-{d:02d}" if (y and m and d) else None
        mult = context.get("MULTIPLIER")
        trade, size = item.get("LAST_PRICE"), item.get("LAST_SIZE")
        premium = (float(trade) * float(size) * float(mult)
                   if (trade is not None and size is not None and mult is not None) else None)
        bid, ask = item.get("BID_PRICE"), item.get("ASK_PRICE")
        classification = "unknown"
        if trade is not None and bid is not None and ask is not None:
            if trade <= bid:
                classification = "at_bid" if trade == bid else "outside_spread_low"
            elif trade >= ask:
                classification = "at_ask" if trade == ask else "outside_spread_high"
            else:
                classification = "inside_spread"
        out.append({
            "ts_recv": float(ts_recv), "symbol": sym, "underlying": context.get("UNDERLYING"),
            "expiry": expiry, "type": side, "strike": strike,
            "bid": bid, "bid_size": item.get("BID_SIZE"),
            "ask": ask, "ask_size": item.get("ASK_SIZE"),
            "trade": trade, "size": size, "premium": premium,
            "volume": item.get("TOTAL_VOLUME"), "oi": item.get("OPEN_INTEREST"),
            "iv": item.get("VOLATILITY"), "delta": item.get("DELTA"),
            "multiplier": mult, "classification": classification,
        })
        if len(out) > bounded_limit:
            out.pop(0)   # keep only the most recent `bounded_limit` — cheaper than re-slicing every append
    out.reverse()   # newest-first for display
    return out


def book_heatmap_for_ticker(
    ticker: str,
    *,
    minutes: float = 60.0,
    max_rows: int = 20000,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Historical book-depth heatmap for one underlying ticker's own book (operator field-
    inventory audit, 2026-09-13 — "we don't have an order flow heatmap"). Bins the SAME
    persisted `stream_book_raw` rows the live `/api/order-flow/microstructure` ladder already
    reads (NASDAQ_BOOK + NYSE_BOOK, merged — the combined displayed liquidity across both
    venues, never one venue silently picked as "the" book) into a time x price grid, cell
    value = summed native TOTAL_VOLUME. This is genuinely historical (a real time dimension),
    which the live ladder's single current snapshot cannot show — the Bookmap-style view.

    The window ends at the LATEST row actually captured for this ticker, never wall-clock
    `now()`: outside RTH (weekends, after-hours with no fresh ticks) "now" would show an
    honestly-empty grid even though real historical data exists a few hours earlier. Anchoring
    to the data's own latest timestamp means a viewer always sees the most recent REAL
    session's shape, labelled with its own real as-of time — never a fabricated live illusion.
    Fails closed (available:false + a plain reason) at every stage; never returns a synthetic
    or interpolated cell.
    """
    sym = ticker_storage_key(ticker) or str(ticker or "").strip().upper()
    if not sym:
        return {"ticker": ticker, "available": False, "reason": "empty ticker"}
    path = resolve_stream_db_path(db_path)
    if not path.is_file():
        return {"ticker": sym, "available": False, "reason": "no stream capture database"}
    try:
        con = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    except sqlite3.Error:
        return {"ticker": sym, "available": False, "reason": "database unavailable"}
    try:
        con.execute("PRAGMA query_only=ON")
        latest = con.execute(
            "SELECT MAX(ts_recv) FROM stream_book_raw WHERE symbol = ? AND service IN (?, ?)",
            (sym, "NASDAQ_BOOK", "NYSE_BOOK"),
        ).fetchone()
        latest_ts = latest[0] if latest else None
        if latest_ts is None:
            return {"ticker": sym, "available": False, "reason": "no book history captured for this ticker"}
        lower_bound = float(latest_ts) - max(1.0, float(minutes)) * 60.0
        # DESC + LIMIT keeps the NEWEST max_rows rows in the window, then reversed below to
        # oldest-first for the binning loop -- an earlier ASC+LIMIT form kept the OLDEST rows
        # instead whenever a window's row count exceeded max_rows, silently pulling `until_ts`
        # (and every rendered cell) well short of `latest_captured_ts` even though the payload's
        # own metadata still correctly reported the true latest tick -- the exact "fabricated
        # live illusion" this function's docstring says it must never produce.
        # LIMIT max_rows+1: whether a (max_rows+1)-th row exists is what actually distinguishes
        # "the window had exactly max_rows rows" from "more existed and were cut off" -- the
        # earlier `len(rows) >= max_rows` check could never tell those apart (LIMIT already
        # guarantees len(rows) <= max_rows, so it degenerates to `== max_rows`) and reported
        # rows_capped:true on a window with no truncation at all.
        rows = con.execute(
            "SELECT ts_recv, native_json FROM stream_book_raw "
            "WHERE symbol = ? AND service IN (?, ?) AND ts_recv >= ? "
            "ORDER BY ts_recv DESC LIMIT ?",
            (sym, "NASDAQ_BOOK", "NYSE_BOOK", lower_bound, int(max_rows) + 1),
        ).fetchall()
        rows_capped = len(rows) > int(max_rows)
        rows = rows[:int(max_rows)]
        rows.reverse()
    except sqlite3.Error:
        return {"ticker": sym, "available": False, "reason": "database read failed"}
    finally:
        con.close()
    if not rows:
        return {"ticker": sym, "available": False, "reason": "no book rows in the requested window"}

    t0 = float(rows[0][0])
    span = float(rows[-1][0]) - t0 or 1.0
    n_buckets = 90
    bucket_sec = max(1.0, span / n_buckets)

    cells: dict[tuple[int, float], dict[str, float]] = {}
    prices_seen: set[float] = set()
    for ts_recv, native_json in rows:
        try:
            item = json.loads(native_json)
        except (TypeError, ValueError):
            continue
        if not isinstance(item, dict):
            continue
        bucket = min(n_buckets - 1, int((float(ts_recv) - t0) / bucket_sec))
        for leaf, price_key, side in (("BIDS", "BID_PRICE", "bid"), ("ASKS", "ASK_PRICE", "ask")):
            levels = item.get(leaf)
            # This vendor field is not reliably a list -- app.options.order_flow.state.
            # push_book already normalizes the identical BIDS/ASKS leaf the same way for
            # exactly this reason (a single-level book can arrive as one bare object).
            if not isinstance(levels, list):
                levels = [levels] if levels else []
            for lvl in levels:
                if not isinstance(lvl, dict):
                    continue
                px, vol = lvl.get(price_key), lvl.get("TOTAL_VOLUME")
                if px is None or vol is None:
                    continue
                px = round(float(px), 2)
                cell = cells.setdefault((bucket, px), {"bid": 0.0, "ask": 0.0})
                cell[side] += float(vol)
                prices_seen.add(px)

    if not prices_seen:
        return {"ticker": sym, "available": False, "reason": "captured rows carried no populated price levels in this window"}

    cell_list = sorted(
        ({"t": k[0], "price": k[1], "bid": round(v["bid"], 1), "ask": round(v["ask"], 1)} for k, v in cells.items()),
        key=lambda c: (c["t"], c["price"]),
    )
    return {
        "ticker": sym, "available": True,
        "since_ts": t0, "until_ts": float(rows[-1][0]), "latest_captured_ts": float(latest_ts),
        "n_buckets": n_buckets, "bucket_sec": round(bucket_sec, 2),
        "price_min": min(prices_seen), "price_max": max(prices_seen),
        "rows_scanned": len(rows), "rows_capped": rows_capped,
        "cells": cell_list,
        "method": ("stream_book_raw NASDAQ_BOOK+NYSE_BOOK rows for this ticker, oldest-to-newest in "
                   "the window ending at the data's own latest captured tick, binned into n_buckets "
                   "time columns x native BID_PRICE/ASK_PRICE rows; cell value = summed native "
                   "TOTAL_VOLUME (displayed size only, both venues merged)."),
    }
