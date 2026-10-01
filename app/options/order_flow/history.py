"""Stored stream observations read for the options tape and the book heatmap."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from instrument_identity import ticker_storage_key
from numeric_contract import schwab_count, schwab_number
from stream_spine import resolve_stream_db_path
from time_et import ct_label

#: Schwab's LEVELONE_OPTIONS fields of the last trade: a message carrying one reports a print
_TRADE_FIELDS = ("TRADE_TIME_MILLIS", "LAST_PRICE", "LAST_SIZE")


def tape_rows_for_symbol(
    contract: str,
    *,
    since_ts: float,
    db_path: str | Path | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """The contract's trade prints from the stored LEVELONE_OPTIONS messages since `since_ts`.

    Schwab sends a field only when it changes, so each message is merged, field by field, onto
    the contract's fields as they stood: the last value sent is the value. A row is a message
    that changes the last trade's time, price or size; it carries the merged trade, the trade's
    own time (Schwab's TRADE_TIME_MILLIS, never the receive time: the first message after a
    subscription reports a trade that may be a day old) and the quote, volume, open interest
    and greeks as they stood then. A field Schwab has not sent inside the window is absent from
    the row. A message that repeats the same trade (a snapshot resent on a reconnect) is not a
    new row. The stream reports the LAST trade when it sends, not every trade: TOTAL_VOLUME
    moves by more than the rows' sizes. No side is inferred (docs/DATA_FLOW.md decision 9).

    Ordered newest-first, bounded by `limit`. `[]` on any read error."""
    sym = ticker_storage_key(contract)   # canonical key only -- no raw-string stand-in
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

    fields: dict[str, Any] = {}                      # the contract's fields as they stand
    last_trade: tuple[Any, Any, Any] | None = None   # the last print's (time, price, size)
    out: list[dict[str, Any]] = []
    for ts_recv, native_json in rows:
        try:
            item = json.loads(native_json)
        except (TypeError, ValueError):
            continue
        if not isinstance(item, dict):
            continue
        fields.update(item)
        if not any(k in item for k in _TRADE_FIELDS):
            continue
        trade, size = schwab_number(fields.get("LAST_PRICE")), schwab_count(fields.get("LAST_SIZE"))
        trade_ms = schwab_number(fields.get("TRADE_TIME_MILLIS"))
        this_trade = (trade_ms, trade, size)
        if this_trade == last_trade:
            continue
        last_trade = this_trade
        y, m, d = fields.get("EXPIRATION_YEAR"), fields.get("EXPIRATION_MONTH"), fields.get("EXPIRATION_DAY")
        mult = schwab_number(fields.get("MULTIPLIER"))
        out.append({
            "ts_recv": float(ts_recv), "symbol": sym, "underlying": fields.get("UNDERLYING"),
            "trade_ts": None if trade_ms is None else trade_ms / 1000.0,
            "time": None if trade_ms is None else ct_label(trade_ms / 1000.0, seconds=True),
            "expiry": f"{y:04d}-{m:02d}-{d:02d}" if (y and m and d) else None,
            "type": put_call_side(fields.get("CONTRACT_TYPE")),
            "strike": schwab_number(fields.get("STRIKE_TYPE")),
            "bid": schwab_number(fields.get("BID_PRICE")), "bid_size": schwab_count(fields.get("BID_SIZE")),
            "ask": schwab_number(fields.get("ASK_PRICE")), "ask_size": schwab_count(fields.get("ASK_SIZE")),
            "trade": trade, "size": size,
            "premium": (trade * size * mult
                        if (trade is not None and size is not None and mult is not None) else None),
            "volume": schwab_count(fields.get("TOTAL_VOLUME")), "oi": schwab_count(fields.get("OPEN_INTEREST")),
            "iv": schwab_number(fields.get("VOLATILITY")), "delta": schwab_number(fields.get("DELTA")),
            "multiplier": mult,
        })
        if len(out) > bounded_limit:
            out.pop(0)   # keep only the most recent `bounded_limit` — cheaper than re-slicing every append
    out.reverse()   # newest-first for display
    return out


def put_call_side(contract_type) -> "str | None":
    """Schwab's LEVELONE_OPTIONS CONTRACT_TYPE ('C' / 'P'), as CALL / PUT; None when not sent."""
    return {"C": "CALL", "P": "PUT"}.get(contract_type)


#: The default price window drops this share of displayed size at each end: one thin resting order
#: far from the touch would otherwise stretch the axis. Carried unchanged from the page
#: (2026-09-27); its origin is not recorded -- NOT_PROVEN.
DISPLAY_TAIL_SHARE = 0.01


def _display_window(cells: list[dict]) -> tuple[float, float]:
    """(lo, hi): the price window holding all but DISPLAY_TAIL_SHARE of displayed size at each end."""
    totals: dict[float, float] = {}
    for c in cells:
        totals[c["price"]] = totals.get(c["price"], 0.0) + c["bid"] + c["ask"]
    prices = sorted(totals)
    whole = sum(totals.values())
    if not whole:
        return prices[0], max(prices[-1], prices[0] + 0.01)
    lo = hi = None
    cum = 0.0
    for px in prices:
        cum += totals[px]
        if lo is None and cum / whole >= DISPLAY_TAIL_SHARE:
            lo = px
        if cum / whole <= 1 - DISPLAY_TAIL_SHARE:
            hi = px
    lo = prices[0] if lo is None else lo
    hi = prices[-1] if hi is None or hi <= lo else hi
    return lo, max(hi, lo + 0.01)


def book_heatmap_for_ticker(
    ticker: str,
    venue: str,
    *,
    minutes: float = 60.0,
    max_rows: int = 20000,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Historical book-depth heatmap for one underlying ticker's own book (operator field-
    inventory audit, 2026-09-13 — "we don't have an order flow heatmap"). Bins the SAME
    persisted `stream_book_raw` rows of one Schwab book, `venue` (NYSE_BOOK or NASDAQ_BOOK;
    the two are never merged), into a time x price grid, cell
    value = the LAST observed native TOTAL_VOLUME at that price within the bucket -- NOT a sum
    across every captured tick (NASDAQ_BOOK/NYSE_BOOK messages are full-book snapshots, so an
    unchanged resting level is re-transmitted every time any OTHER level moves; summing would
    make brightness track retransmission frequency instead of actual displayed size). This is
    genuinely historical (a real time dimension), which the live ladder's single current
    snapshot cannot show — the Bookmap-style view.

    The window ends at the LATEST row actually captured for this ticker, never wall-clock
    `now()`: outside RTH (weekends, after-hours with no fresh ticks) "now" would show an
    honestly-empty grid even though real historical data exists a few hours earlier. Anchoring
    to the data's own latest timestamp means a viewer always sees the most recent REAL
    session's shape, labelled with its own real as-of time — never a fabricated live illusion.
    Fails closed (available:false + a plain reason) at every stage; never returns a synthetic
    or interpolated cell.
    """
    sym = ticker_storage_key(ticker)   # canonical key only -- no raw-string stand-in
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
        # the newest message that carries a price level: after the close Schwab keeps sending
        # empty book snapshots, and anchoring on those showed an empty grid all weekend
        # (measured 2026-09-27: SPY and TSLA blank, their last populated book on 2026-09-25)
        latest = con.execute(
            "SELECT MAX(ts_recv) FROM stream_book_raw WHERE symbol = ? AND service = ? "
            "AND (native_json LIKE '%\"BID_PRICE\"%' OR native_json LIKE '%\"ASK_PRICE\"%')",
            (sym, venue),
        ).fetchone()
        latest_ts = latest[0] if latest else None
        if latest_ts is None:
            any_row = con.execute(
                "SELECT 1 FROM stream_book_raw WHERE symbol = ? AND service = ? LIMIT 1",
                (sym, venue),
            ).fetchone()
            return {"ticker": sym, "available": False,
                    "reason": ("captured rows carried no populated price levels in this window" if any_row
                               else "no book history captured for this ticker")}
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
            "WHERE symbol = ? AND service = ? AND ts_recv >= ? AND ts_recv <= ? "
            "ORDER BY ts_recv DESC LIMIT ?",
            (sym, venue, lower_bound, float(latest_ts), int(max_rows) + 1),
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
    span = float(rows[-1][0]) - t0   # binning floors at 1s below; no invented span
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
                px, vol = schwab_number(lvl.get(price_key)), schwab_count(lvl.get("TOTAL_VOLUME"))
                if px is None or vol is None:
                    continue
                cell = cells.setdefault((bucket, px), {"bid": 0.0, "ask": 0.0})
                # Operator-reproduced defect (2026-09-14): NASDAQ_BOOK/NYSE_BOOK messages are
                # full-book snapshots, not deltas -- an UNCHANGED 100-share resting level gets
                # re-transmitted (and re-captured into stream_book_raw) every time ANY other
                # level in the book moves. Accumulating with `+=` turned "the same 100 shares,
                # observed 10 times" into a displayed 1,000 -- brightness measured how often a
                # level was retransmitted, not how much size actually sat there. `rows` is
                # already oldest-to-newest (see the DESC+LIMIT+reverse() above), so a plain
                # overwrite leaves each cell holding the LAST observed size at that price within
                # the bucket -- a real captured value, never a sum across repeated observations.
                cell[side] = vol
                prices_seen.add(px)

    if not prices_seen:
        return {"ticker": sym, "available": False, "reason": "captured rows carried no populated price levels in this window"}

    cell_list = sorted(
        ({"t": k[0], "price": k[1], "bid": round(v["bid"], 1), "ask": round(v["ask"], 1),
          # the dominant displayed side at this price and bucket (the cell's colour)
          "side": "BID" if v["bid"] > v["ask"] else "ASK" if v["ask"] > v["bid"] else "EVEN"}
         for k, v in cells.items()),
        key=lambda c: (c["t"], c["price"]),
    )
    display_lo, display_hi = _display_window(cell_list)
    return {
        "ticker": sym, "venue": venue, "available": True,
        "since_ts": t0, "until_ts": float(rows[-1][0]), "latest_captured_ts": float(latest_ts),
        "n_buckets": n_buckets, "bucket_sec": round(bucket_sec, 2),
        "price_min": min(prices_seen), "price_max": max(prices_seen),
        # the default price window, and the largest displayed size (the colour scale's top)
        "display_lo": display_lo, "display_hi": display_hi,
        "max_size": max(max(c["bid"], c["ask"]) for c in cell_list),
        "rows_scanned": len(rows), "rows_capped": rows_capped,
        "cells": cell_list,
        "method": ("stream_book_raw NASDAQ_BOOK+NYSE_BOOK rows for this ticker, oldest-to-newest in "
                   "the window ending at the data's own latest captured tick, binned into n_buckets "
                   "time columns x native BID_PRICE/ASK_PRICE rows; cell value = the LAST observed "
                   "native TOTAL_VOLUME at that price within the bucket (displayed size only, both "
                   "venues merged) -- never summed across repeated observations of the same resting "
                   "size, which would measure retransmission frequency, not liquidity."),
    }
