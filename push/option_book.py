"""The `option_book` panel: the Options Book of one expiry, its summary and the options lean.

Read from State: one expiry of the published chain with each contract's newest values, as the
chain screens show them (push.chain.expiry_asked), each contract's newest OPTIONS_BOOK (the
order-flow state), the daemon's heartbeat and the live price. Computed once by calc.option_book;
every text is formatted here. Sent again on each streamed quote or book of the ticker or its
contracts (server.FLOW_PANELS, OPTION_PANELS) and on each publication of its levels
(server.LEVELS_PANELS). The Options Book subview asks it at the selected expiry, the Trade Desk's
Options Positioning card at the front one.
"""

from __future__ import annotations

from typing import Any

import live_market_plane as lmp
from app.options.order_flow.state import newest_book
from calc.option_book import (
    ZONES,
    BookRow,
    BookSummary,
    Lean,
    Leg,
    Split,
    book_rows,
    leg,
    scales,
    summary,
)
from calc.order_flow import Book, book_age_sec
from calc.terrain_engine import nearest_strike
from numeric_contract import count_text, price_text, strike_text
from push.answers import unavailable
from push.book import when_age
from push.chain import expiry_asked
from push.spot import resolve_spot
from push.strike_rows import MARK_LABELS, window, window_asked
from time_et import age_text, ct_label

#: Schwab's service for an option contract's book
OPTIONS_BOOK = "OPTIONS_BOOK"


def _share_text(share: float | None) -> str | None:
    """Return a share of a whole as the screen shows it: a whole percent ("62%")."""
    return None if share is None else f"{share:.0%}"


def _lean_text(value: float | None) -> str | None:
    """Return a lean, -1 to +1, as the screen shows it: signed, two decimals ("+0.23")."""
    return None if value is None else f"{value:+.2f}"


def _book_when(book: Book | None, now: float) -> str | None:
    """Return a book's time, as Schwab sent BOOK_TIME, with its age; None with no time sent."""
    ms = None if book is None else book.book_time_ms
    return None if ms is None else when_age(ct_label(ms / 1000.0), book_age_sec(ms, now))


def _served_leg(
    cells: Leg | None, books: dict[str, Book], live: set[str], now: float
) -> dict[str, Any] | None:
    """Return one contract's cells as the page draws them; None where no contract is listed."""
    if cells is None:
        return None
    book = books.get(cells.symbol)
    return {
        "symbol": cells.symbol,
        "bid": cells.bid,
        "ask": cells.ask,
        "volume": cells.volume,
        "bid_text": count_text(cells.bid),
        "ask_text": count_text(cells.ask),
        "volume_text": count_text(cells.volume),
        "book_live": None if book is None else cells.symbol in live,
        "book_when_text": _book_when(book, now),
    }


def _served_row(
    row: BookRow, spot_strike: float | None, books: dict[str, Book], live: set[str], now: float
) -> dict[str, Any]:
    """Return one row as the page draws it, the row at the price marked."""
    return {
        "strike": row.strike,
        "strike_text": strike_text(row.strike),
        "summed": row.summed,
        "marks": [{"kind": "spot", "label": MARK_LABELS["spot"]}]
        if row.strike == spot_strike
        else [],
        "call": _served_leg(row.call, books, live, now),
        "put": _served_leg(row.put, books, live, now),
    }


def _served_split(s: Split) -> dict[str, Any]:
    """Return one summary bar: its two totals and their shares, with their texts."""
    return {
        "left": s.left,
        "right": s.right,
        "left_share": s.left_share,
        "right_share": s.right_share,
        "left_text": count_text(s.left),
        "right_text": count_text(s.right),
        "left_share_text": _share_text(s.left_share),
        "right_share_text": _share_text(s.right_share),
    }


def _served_lean(x: Lean) -> dict[str, Any]:
    """Return the lean, its zone and the needle's angle, and its three readings, with texts."""
    return {
        "value": x.value,
        "value_text": _lean_text(x.value),
        "zone": x.zone,
        "zone_index": x.zone_index,
        "needle_deg": x.needle_deg,
        "calls": x.calls,
        "calls_text": _lean_text(x.calls),
        "puts": x.puts,
        "puts_text": _lean_text(x.puts),
        "volume": x.volume,
        "volume_text": _lean_text(x.volume),
    }


def _summed_text(s: BookSummary) -> str:
    """Return which strikes the summary sums, as the screen says it."""
    if not s.strikes:
        return "No strike shown has a Schwab book on both its call and its put"
    span = strike_text(s.strikes[0])
    if len(s.strikes) > 1:
        span += f"–{strike_text(s.strikes[-1])}"
    noun = "strike" if len(s.strikes) == 1 else "strikes"
    return f"{len(s.strikes)} {noun} {span}: those whose call and put both have a Schwab book"


def _left_out_text(s: BookSummary) -> str | None:
    """Return how many rows shown the summary leaves out, as the screen says it; None: none."""
    if not s.left_out:
        return None
    rows = "row" if s.left_out == 1 else "rows"
    return f"{s.left_out} {rows} shown without a Schwab book on both sides: not summed"


def _book_state(
    books: dict[str, Book], live: set[str], now: float
) -> tuple[str | None, str | None, str | None]:
    """Return the shown books' state (LIVE while every one is), why not, and the oldest's time.

    The state of the first book that is not live by the one live rule, with its reason; the
    oldest BOOK_TIME of them with its age. None for each with no book held.
    """
    if not books:
        return None, None, None
    stopped = next((s for s in books if s not in live), None)
    label, outage = (
        (lmp.LIVE, None) if stopped is None else lmp.live_state(stopped, OPTIONS_BOOK, now)
    )
    times = [b.book_time_ms for b in books.values() if b.book_time_ms is not None]
    oldest = min(times, default=None)
    when = (
        None
        if oldest is None
        else f"oldest book {ct_label(oldest / 1000.0)} · {age_text(now - oldest / 1000.0)}"
    )
    return label, outage, when


def option_book(ticker: str, now: float, params: dict[str, Any]) -> dict[str, Any]:
    """Return the Options Book of `ticker` at `now` in the window and expiry `params` ask for.

    One row per strike of the window (push.strike_rows.window: the scope's strikes around the
    listed strike nearest the live price, or the operator's pan), each with its call's and put's
    resting bid and ask (Schwab's newest OPTIONS_BOOK, every level summed) and volume today; the
    summary of the rows whose call and put both have a book; and the options lean of it.
    """
    win = window_asked(params)
    if isinstance(win, str):
        return unavailable(ticker, win)
    asked = expiry_asked(ticker, now, params)
    if asked.reason is not None:
        return unavailable(ticker, asked.reason, expiry=asked.expiry, **asked.verdict)
    spot, _src, _ts = resolve_spot(ticker, now=now)  # the one live price
    # each contract the ladder places (a strike, a side): the chain panel logs any other
    placed = [
        (c.strike, c.side, c.symbol, c.volume)
        for c in asked.contracts
        if c.strike is not None and c.side is not None and c.symbol
    ]
    strikes = sorted({p[0] for p in placed})
    spot_strike = nearest_strike(strikes, spot)
    lo, hi, view = window(strikes, spot_strike, *win)
    shown = set(strikes[lo : hi + 1])
    books: dict[str, Book] = {}
    listed: list[tuple[float, str, Leg]] = []
    for strike, side, symbol, volume in placed:
        if strike in shown:
            book = newest_book(symbol, OPTIONS_BOOK)
            if book is not None:
                books[symbol] = book
            listed.append((strike, side, leg(symbol, book, volume)))
    live = lmp.live_symbols(lmp.feed_now(now), books, OPTIONS_BOOK, now)
    rows = book_rows(listed)
    held = summary(rows)
    scale = scales(rows)
    state, outage, oldest = _book_state(books, live, now)
    return {
        "ticker": ticker,
        "available": True,
        "expiry": asked.expiry,
        "spot": spot,
        "spot_text": price_text(spot),
        **asked.verdict,
        "view": view,
        "rows": [_served_row(r, spot_strike, books, live, now) for r in rows],
        "scales": {"resting": scale.resting, "volume": scale.volume},
        "summary": {
            "summed_text": _summed_text(held),
            "left_out_text": _left_out_text(held),
            "calls": _served_split(held.calls),
            "puts": _served_split(held.puts),
            "volume": _served_split(held.volume),
        },
        "lean": _served_lean(held.lean),
        "zones": list(ZONES),
        "books_held_text": f"{len(books)} of {len(listed)} contracts shown have a Schwab book",
        "book_state": state,
        "book_outage": outage,
        "book_oldest_text": oldest,
    }
