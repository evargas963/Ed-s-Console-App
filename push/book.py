"""The `book` panel: a ticker's quote and one Schwab book, and the Desk Liquidity card's readout.

Read from State: the venue's newest book (the order-flow state), the price row, and the readouts
the intake kept (history.LEAN).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, TypedDict

import live_market_plane as lmp
from app.options.order_flow.history import LEAN
from app.options.order_flow.state import newest_book
from app.options.order_flow.streaming import price_state
from calc.order_flow import (
    BOOK_VENUES,
    COMPOSITE,
    STATE_WORDS,
    BookAges,
    BookMicrostructure,
    BookProvenance,
    FlowInput,
    Points,
    VenueCard,
    book_age_sec,
    book_readout,
    compute_book_microstructure,
    readout_card,
)
from instrument_identity import ticker_storage_key
from live_price_rows import price_row
from option_contract import NO_TOP, StreamedTop
from push.asked import venue_asked
from time_et import CLOSE_AUCTION, ET, NO_AUCTION, OPEN_AUCTION, age_text, auction, ct_label


class BookTimes(TypedDict):
    """Schwab's quote clock and book clock as the screen shows them, each with its age."""

    quote_time_ct: str | None
    book_time_ct: str | None
    book_age_text: str | None
    book_when_age_text: str | None
    quote_when_age_text: str | None


class ServedVenue(VenueCard):
    """A venue on the Liquidity card as served (liquidity_readout).

    The engine's values, then its live verdict, its book's time and age, and every word the
    card shows for it.
    """

    feed_label: str
    live: bool
    book_time_ct: str | None
    book_age_text: str | None
    source_text: str
    no_number_text: str | None
    no_number_head: str | None
    dedup_partial_text: str | None
    name: str


class LiquidityCard(TypedDict):
    """The Desk Liquidity card's readout (liquidity_readout)."""

    venues: dict[str, ServedVenue]
    disagree: dict[str, bool]
    detail: dict[str, str]
    auction: str | None
    auction_text: str | None


class BookPanel(BookMicrostructure, BookTimes):
    """The `book` panel (order_flow_microstructure).

    The engine's microstructure of one Schwab book, then the page's words for the quote's and
    the book's state, the ticker and venue, each side of the ladder that shows no level (None
    while it shows one), the two clocks as the screen shows them (BookTimes), and the Liquidity
    card's readout.
    """

    top_outage: str | None
    top_feed_label: str
    book_feed_label: str
    ticker: str
    venue: str
    no_book_text: str | None
    state_word: str | None
    asks_none_said: str | None
    bids_none_said: str | None
    readout: LiquidityCard


#: what the Book's ladder says for a side with no displayed level (AGENTS.md rule 4)
NO_ASKS, NO_BIDS = "no displayed asks", "no displayed bids"


def book(ticker: str, now: float, params: dict[str, Any]) -> BookPanel:
    """Return the `book` panel at `now`: the ticker's quote and Schwab book `venue`."""
    return order_flow_microstructure(ticker, venue_asked(params), now)


def when_age(when: str | None, sec: float | None) -> str | None:
    """Return a clock's time and its age as the screen shows them ("Fri 09/25 06:59 PM CT · 4s").

    Either alone when the other is missing; None when both are.
    """
    shown = [x for x in (when, None if sec is None else age_text(sec)) if x is not None]
    return " · ".join(shown) or None


def book_times(provenance: BookProvenance, ages: BookAges) -> BookTimes:
    """Return Schwab's quote clock and book clock as the screen shows them, each with its age.

    The clocks are the engine's `provenance` and the ages its `ages`
    (compute_book_microstructure). Absent stays absent.
    """
    quote_ts, book_ms = provenance["exchange_quote_ts"], provenance["book_time_ms"]
    quote_time_ct = ct_label(quote_ts) if quote_ts is not None else None
    book_time_ct = ct_label(book_ms / 1000.0) if book_ms is not None else None
    return {
        "quote_time_ct": quote_time_ct,
        "book_time_ct": book_time_ct,
        "book_age_text": None if ages["book_age_sec"] is None else age_text(ages["book_age_sec"]),
        "book_when_age_text": when_age(book_time_ct, ages["book_age_sec"]),
        "quote_when_age_text": when_age(quote_time_ct, ages["quote_age_sec"]),
    }


def _no_book_text(label: str, outage: str | None, ticker: str, venue: str) -> str | None:
    """Why no book of `venue` is held for `ticker`, as the screen says it.

    While the venue's book is live (its feed up, the symbol held on it, its market trading),
    Schwab has sent none; otherwise the live rule's own reason (live_market_plane.live_state).
    """
    match label:
        case lmp.LIVE:
            return f"Schwab has sent no {venue} book for {ticker}"
        case _:
            return outage


def order_flow_microstructure(ticker: str, venue: str, now: float) -> BookPanel:
    """Canonical L2 book microstructure at `now` (ORDER_FLOW_MARKET_MICROSTRUCTURE_V1).

    Top-of-book, spread, microprice, Top 1/3/5 depth totals + imbalance, depth-pressure curve,
    and ages — every field classified
    NATIVE/DERIVED/PROXY. SERIALIZER, not a second producer: it delegates to the ONE canonical
    calc.order_flow.compute_book_microstructure, which reads this ticker's book once, and adds
    the page's words for it. No Schwab REST quote call; the client
    renders, never recomputes. `venue` is the one Schwab book the payload's book fields show:
    NYSE_BOOK (exchanges) or NASDAQ_BOOK (market makers); those fields never combine the two.
    `readout` is the Desk Liquidity card's, whatever the venue: both books and their deduped
    composite (liquidity_readout).
    """
    t = ticker_storage_key(ticker)
    # the venue's newest book, as the order-flow state holds it
    # top of book: the daemon's price row. The last bid and ask stand when it is not live;
    # top_outage says why and top_feed_label is the page's word for it (docs/DATA_FLOW.md §2 D5)
    top_label, top_outage = price_state(t, now)
    _row = price_row(t, now)
    # the venue's book: the same verdict on its own service (price_state), its word served
    book_label, book_outage = price_state(t, now, venue)
    data = FlowInput(
        book=newest_book(t, venue),
        top=(
            StreamedTop(
                bid=_row["bid"],
                ask=_row["ask"],
                bid_size=_row["bid_size"],
                ask_size=_row["ask_size"],
                mark=_row["mark"],
            )
            if _row["bid"] is not None or _row["ask"] is not None
            else NO_TOP
        ),
        book_live=book_label == lmp.LIVE,
        exchange_quote_ts=_row["quote_ts"],
    )
    micro = compute_book_microstructure(data, now_ts=now)
    return {
        **micro,
        "top_outage": top_outage,
        "top_feed_label": top_label,
        "book_feed_label": book_label,
        "ticker": t,
        "venue": venue,
        "no_book_text": (
            None if micro["status"] == "ok" else _no_book_text(book_label, book_outage, t, venue)
        ),
        # the book's state as every screen says it when that state is why it has nothing to
        # show (STATE_WORDS); None while it has levels
        "state_word": None if micro["status"] == "ok" else STATE_WORDS[micro["status"]],
        "asks_none_said": None if micro["depth_pressure"]["ask"] else NO_ASKS,
        "bids_none_said": None if micro["depth_pressure"]["bid"] else NO_BIDS,
        **book_times(micro["provenance"], micro["ages"]),
        "readout": liquidity_readout(t, now),
    }


#: the amber line inside an exchange auction window, by window (time_et.auction): the continuous
#: book's number stays. Outside a window, or with today's windows unknown (None), there is none.
_AUCTION_TEXT: dict[str | None, str | None] = {
    OPEN_AUCTION: "Opening auction window — auction imbalance is a different number, not shown"
    " here.",
    CLOSE_AUCTION: "Closing auction window — auction imbalance is a different number, not shown"
    " here.",
    NO_AUCTION: None,
    None: None,
}


#: the readout before any book has arrived: every venue no_book
_NO_BOOKS = book_readout(dict.fromkeys(BOOK_VENUES))
#: each venue of the Liquidity card as the card names it (the hover of its dot)
VENUE_NAMES = {"NYSE_BOOK": "NYSE", "NASDAQ_BOOK": "Nasdaq", COMPOSITE: "Aggregate"}
_LIVE_BOOK = "live book"


def _source(venue: str, books: list[str] | None) -> str:
    """Whose book: Schwab's book of `venue`, or for the composite the books it is built from.

    The composite is the one venue whose readout names its books.
    """
    if books is None:
        return f"Schwab {venue}"
    return f"Schwab {' + '.join(books)} · aggregate, newest quote of each exchange"


def _no_number(status: str) -> tuple[str, str, str] | None:
    """Why a venue has no number, as the source line, the card's line and the card's heading say it.

    None when it has one.
    """
    if status == "no_book":
        return (
            "no book for this symbol right now",
            "No book for this symbol right now",
            STATE_WORDS[status],
        )
    if status == "empty":
        return (
            "the book Schwab sent has no levels",
            "The book Schwab sent has no levels",
            STATE_WORDS[status],
        )
    return None


def _source_text(
    venue: str,
    r: VenueCard,
    live: bool,
    book_time_ct: str | None,
    book_age_text: str | None,
    window: str | None,
) -> str:
    """Return the card's source line for `venue`.

    Schwab's book, then why it has no number, or live, or its time and not live; and, when today's
    auction windows are not known, that.
    """
    parts = [_source(venue, r["books"])]
    why = _no_number(r["status"])
    if why is not None:
        parts.append(why[0])
    elif live:
        if venue != COMPOSITE:
            parts.append(_LIVE_BOOK)
    elif book_time_ct is not None:
        parts.append(f"book {book_time_ct} · {book_age_text} old · not live")
    else:
        parts.append("not live, no book time sent")
    if window is None:
        parts.append("auction windows unknown: no Schwab market hours held for today")
    return " · ".join(parts)


def _stood_from(points: Points, venue: str) -> float:
    """Return the receive time of the first reading from which `venue`'s readout has stood as now.

    That is where a venue that is not live is read to (a book that stopped stands from its last
    arrival; the composite of a stopped book and a running one still changes with the running
    one).
    """
    newest, k = points[-1][1][venue], len(points) - 1
    while k > 0 and points[k - 1][1][venue] == newest:
        k -= 1
    return points[k][0]


def liquidity_readout(t: str, now: float) -> LiquidityCard:
    """Return the Desk Liquidity card's order-imbalance readout for ticker `t` at `now`.

    The newest readout of both Schwab books and their deduped composite the console's intake
    computed (engine.book_readout, kept in history.LEAN), read over the readouts kept
    (engine.readout_card). Each book is judged by the one live rule on its own service, the
    composite live only while both are; a venue that is not live keeps its last values, read to
    the reading its readout has stood from (`_stood_from`), with its book's time and age. With the
    exchange auction window of today's session as Schwab sent it (time_et.auction; None while
    Schwab's answer for today is not held), and every word the card shows.
    """
    points = LEAN.points(t)
    readout = points[-1][1] if points else _NO_BOOKS
    labels = {v: price_state(t, now, v)[0] for v in BOOK_VENUES}
    labels[COMPOSITE] = next((labels[v] for v in BOOK_VENUES if labels[v] != lmp.LIVE), lmp.LIVE)
    # with no reading kept, no venue has an end
    ends: dict[str, float | None] = dict.fromkeys(readout)
    if points:
        ends = {v: now if labels[v] == lmp.LIVE else _stood_from(points, v) for v in readout}
    card = readout_card(readout, points, ends)
    window = auction(datetime.fromtimestamp(now, ET))
    venues: dict[str, ServedVenue] = {}
    for v, r in card["venues"].items():
        book_ms = r["book_time_ms"]
        live = labels[v] == lmp.LIVE
        book_time_ct = None if book_ms is None else ct_label(book_ms / 1000.0)
        age = book_age_sec(book_ms, now)
        book_age_text = None if age is None else age_text(age)
        why = _no_number(r["status"])
        venues[v] = {
            **r,
            "feed_label": labels[v],
            "live": live,
            "book_time_ct": book_time_ct,
            "book_age_text": book_age_text,
            "source_text": _source_text(v, r, live, book_time_ct, book_age_text, window),
            "no_number_text": None if why is None else why[1],
            "no_number_head": None if why is None else why[2],
            "dedup_partial_text": (
                "Dedup partial: a level came without per-exchange sizes (its total taken whole), or"
                " a quote in both books without its quote time (a timed copy counts over it)"
                if r["dedup_partial"]
                else None
            ),
            "name": VENUE_NAMES[v],
        }
    return {
        "venues": venues,
        "disagree": card["disagree"],
        "detail": card["detail"],
        "auction": window,
        "auction_text": _AUCTION_TEXT[window],
    }
