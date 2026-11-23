"""The quote per ticker, from Schwab's streamed LEVEL_ONE_EQUITY rows.

The rows are taken by `record_from_level_one_equity`: each field the last value Schwab sent, at
any hour, and whether the symbol's values are live now (`live_state`): the feed delivers it and
its market trades.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Collection, Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, TypedDict

from calc.forming_bar import Built, BuiltMinute, next_built
from calc.l1_trade_observation import (
    VENDOR_LAST_PRICE,
    VENDOR_LAST_SIZE,
    VENDOR_TRADE_TIME,
    last_print,
)
from instrument_identity import ticker_storage_key
from numeric_contract import schwab_count, schwab_number
from time_et import CLOSED, ET, UNKNOWN, options_open, record_trade, session_label

#: the services the capture daemon streams the option rule's contracts on
#: (capture.Daemon.pick_options): live until the last option market closes (time_et.options_open)
OPTION_SERVICES = ("LEVELONE_OPTIONS", "OPTIONS_BOOK")
#: the words of a value's state, served to the page: updating now; its feed down; its market not
#: trading
LIVE, OFFLINE, NOT_LIVE = "LIVE", "OFFLINE", "NOT LIVE"


@dataclass(frozen=True)
class QuoteRow:
    """A symbol's LEVELONE_EQUITIES row: each field the last value Schwab sent for it.

    None until Schwab sends one, and when the one it sent is not a number (rule 2). `spot` is
    LAST_PRICE; `regular_last` the regular session's last trade; `chg_pct` and
    `chg_pct_regular` Schwab's NET_CHANGE_PERCENT and REGULAR_MARKET_CHANGE_PERCENT;
    `exchange_quote_ts` and `trade_ts` QUOTE_TIME and TRADE_TIME (epoch s);
    `server_received_ts` the daemon's receive time of the row's newest message.
    """

    ticker: str = ""
    spot: float | None = None
    bid: float | None = None
    ask: float | None = None
    mark: float | None = None
    bid_size: float | None = None
    ask_size: float | None = None
    last_size: float | None = None
    total_volume: float | None = None
    open_price: float | None = None
    high_price: float | None = None
    low_price: float | None = None
    regular_last: float | None = None
    chg_pct: float | None = None
    chg_pct_regular: float | None = None
    net_change: float | None = None
    exchange_quote_ts: float | None = None
    trade_ts: float | None = None
    security_status: str | None = None
    server_received_ts: float | None = None


#: a symbol no LEVELONE_EQUITIES message has reached: every field unknown
NO_QUOTE = QuoteRow()


_lock = threading.RLock()
# ticker UPPER -> its row
_by_ticker: dict[str, QuoteRow] = {}
# ticker UPPER -> its minutes built from its rows (calc.forming_bar), written with each row
_built: dict[str, Built] = {}


#: Schwab LEVELONE_EQUITIES sends only the fields that CHANGED since the last message for a
#: symbol. Measured on 4,039 real captured messages (stream_quotes_raw): only 11%
#: carried bid, ask and last together; 17% were ask-only, 15% bid-only, 23% none of the three.
#: So a field absent from a message is UNCHANGED, not missing -- the current value of each
#: field is the last one Schwab sent, and its age is the age of THAT message. This table holds
#: exactly that, per ticker, per field: {field: (value, received_ts)}.
_PRICE_FIELDS = (
    "BID_PRICE",
    "ASK_PRICE",
    "MARK",
    "OPEN_PRICE",
    "HIGH_PRICE",
    "LOW_PRICE",
    "REGULAR_MARKET_LAST_PRICE",
)
_COUNT_FIELDS = ("BID_SIZE", "ASK_SIZE", "TOTAL_VOLUME")
_CLOCK_FIELDS = ("QUOTE_TIME_MILLIS",)
#: signed values (any finite number): Schwab's own change of the LAST_PRICE vs the prior close.
#: Measured: NET_CHANGE_PERCENT arrives with every LAST_PRICE; REGULAR_MARKET_CHANGE_PERCENT
#: with every LAST_PRICE in the regular session (SPY 113/113, MU 112/112, PCG 17/17)
#: and outside it only on a full refresh; CHANGE_PERCENT never.
_SIGNED_FIELDS = ("NET_CHANGE", "NET_CHANGE_PERCENT", "REGULAR_MARKET_CHANGE_PERCENT")
#: text as sent: Schwab's SECURITY_STATUS (field 32: "Normal, Halted, Closed"), the symbol's own
#: trading status (measured: $SPX Closed outside regular hours, stocks Closed 20:00-04:00 ET, SPY
#: Normal on a Saturday)
_TEXT_FIELDS = ("SECURITY_STATUS",)
_fields_by_ticker: dict[str, dict[str, tuple[float | str, float]]] = {}


def _read_stream_field(name: str, raw: Any) -> float | str | None:
    """Each field as Schwab sent it (AGENTS.md rule 2); a reported 0 is 0."""
    if name in _TEXT_FIELDS:
        return raw if isinstance(raw, str) and raw else None
    if name in _COUNT_FIELDS:
        return schwab_count(raw)
    v = schwab_number(raw)
    return v / 1000.0 if v is not None and name in _CLOCK_FIELDS else v


def record_from_level_one_equity(
    ticker: str,
    item: dict[str, Any],
    *,
    received_ts: float,
    field_received: dict[str, float] | None = None,
) -> bool:
    """
    Ingest one Schwab streaming LEVELONE_EQUITIES content item into the plane.

    Returns True when a plane row was (re)published.

    Per-field state (see _fields_by_ticker): each field present in the message replaces
    that field's value and receive time; absent fields stand (Schwab sends changes only).
    A present field that is not a number (-999, text, NaN) CLEARS that field; a 0 is 0. The
    row is published with every message, each field the last one Schwab sent: spot is
    LAST_PRICE only (MARK never stands in; None until Schwab sends one), and its age is the
    age of the last LAST_PRICE message, never of the bid/ask tick arriving now.

    `received_ts` is REQUIRED: the capture daemon's own receive time for this message --
    what every freshness check judges. A current record merged from several messages (the
    daemon's bus) carries each field's own receive time in `field_received`.
    """
    if not item:
        return False
    t = ticker_storage_key(ticker)  # the plane's key
    if not t:
        return False
    rts = float(received_ts)
    own = _PRICE_FIELDS + _COUNT_FIELDS + _CLOCK_FIELDS + _SIGNED_FIELDS + _TEXT_FIELDS
    sent = {name: _read_stream_field(name, item[name]) for name in own if name in item}
    sent.update(last_print(item))  # the last trade's three fields: their one reader's
    if not sent:
        return False
    with _lock:
        fs = _fields_by_ticker.setdefault(t, {})
        for name, v in sent.items():
            if v is None:
                fs.pop(name, None)  # not a number (-999, text, NaN): cleared
            else:
                fs[name] = (v, rts if field_received is None else float(field_received[name]))
        snapshot = dict(fs)
    out, trade_ts = _plane_row(t, snapshot, rts)
    with _lock:
        _by_ticker[t] = out
        built = next_built(_built.get(t), out.spot, trade_ts)
        if built is not None:
            _built[t] = built
    if trade_ts is not None:
        # the last trade Schwab streamed: the day's first one starts its pre-market (session_label)
        record_trade(datetime.fromtimestamp(trade_ts, ET))
    for fn in _row_listeners:
        fn(t)
    return True


def _plane_row(
    t: str, snapshot: dict[str, tuple[float | str, float]], rts: float
) -> tuple[QuoteRow, float | None]:
    """Return the plane's row of `t` and its trade time (epoch s; None: none held).

    Each field of the row is the last one Schwab sent (`snapshot`).
    """

    def number(name: str) -> float | None:
        """Return a number field's value (a price, a count, a clock); None when not held."""
        v = snapshot[name][0] if name in snapshot else None
        return v if isinstance(v, float | int) else None

    trade_ms = number(VENDOR_TRADE_TIME)
    trade_ts = None if trade_ms is None else trade_ms / 1000.0
    status = snapshot["SECURITY_STATUS"][0] if "SECURITY_STATUS" in snapshot else None
    row = QuoteRow(
        ticker=t,
        spot=number(VENDOR_LAST_PRICE),
        bid=number("BID_PRICE"),
        ask=number("ASK_PRICE"),
        mark=number("MARK"),
        bid_size=number("BID_SIZE"),
        ask_size=number("ASK_SIZE"),
        last_size=number(VENDOR_LAST_SIZE),
        total_volume=number("TOTAL_VOLUME"),
        open_price=number("OPEN_PRICE"),
        high_price=number("HIGH_PRICE"),
        low_price=number("LOW_PRICE"),
        # the regular session's last trade: it stands from that session's close, while LAST_PRICE
        # goes on with the extended hours' trades (today's daily candle closes on it)
        regular_last=number("REGULAR_MARKET_LAST_PRICE"),
        # Schwab's own change vs the prior close (0 hops): NET_CHANGE_PERCENT is the last price's,
        # extended hours included; REGULAR_MARKET_CHANGE_PERCENT is the regular session's
        chg_pct=number("NET_CHANGE_PERCENT"),
        chg_pct_regular=number("REGULAR_MARKET_CHANGE_PERCENT"),
        net_change=number("NET_CHANGE"),
        exchange_quote_ts=number("QUOTE_TIME_MILLIS"),  # TRADE_TIME never stands in
        # the exchange time of the last trade: the clock a LAST_PRICE tick belongs to (candles)
        trade_ts=trade_ts,
        security_status=status if isinstance(status, str) else None,
        server_received_ts=rts,
    )
    return row, trade_ts


#: callables told the ticker of every published row, in the process that owns this plane: the
#: capture daemon's browser push (live_ui).
_row_listeners: list[Callable[[str], object]] = []


def add_row_listener(fn: Callable[[str], object]) -> None:
    if fn not in _row_listeners:
        _row_listeners.append(fn)


def remove_row_listener(fn: Callable[[str], object]) -> None:
    if fn in _row_listeners:
        _row_listeners.remove(fn)


def get_quote(ticker: str) -> QuoteRow:
    """Return the ticker's row (NO_QUOTE: no LEVELONE_EQUITIES message has reached it)."""
    t = ticker_storage_key(ticker)  # the plane's key, the same as the write's
    with _lock:
        return _by_ticker.get(t, NO_QUOTE)


def built_minutes(ticker: str) -> tuple[BuiltMinute, ...]:
    """Return the minutes built from the ticker's rows, oldest first (calc.forming_bar)."""
    t = ticker_storage_key(ticker)
    with _lock:
        return _built[t].minutes if t in _built else ()


#: The daemon sends its status every second; the daemon, and everything it streams, is live
#: only while the latest one was stamped within this of the time judged. The one liveness limit.
FEED_HEARTBEAT_MAX_AGE_SEC: float = 3.0


class _Feed(TypedDict):
    rx: float | None
    status: dict[str, Any] | None
    held: dict[str, frozenset[str]]


#: The daemon's latest status (its heartbeat), the time the daemon stamped it, and the symbols
#: it holds per Schwab service. Written by record_feed_heartbeat only. A late beat leaves the
#: status and `held`: what the daemon last reported stands, not live.
_feed: _Feed = {"rx": None, "status": None, "held": {}}


def record_feed_heartbeat(msg: dict[str, Any]) -> None:
    """Apply one daemon heartbeat (capture.Daemon.status, live_ui's beat).

    It is judged by the time the daemon stamped it (`ts`), never by when it arrived: a status that
    waited is as old as it is (docs/DATA_FLOW.md §2 D5).
    """
    held = {
        svc: frozenset(ticker_storage_key(s) for s in syms) for svc, syms in msg["held"].items()
    }
    with _lock:
        _feed.update(rx=float(msg["ts"]), status=msg, held=held)


def last_beat() -> dict[str, Any] | None:
    """Return the latest status the daemon sent, current or not; None until one arrives.

    What it reported stands while a beat is late or missing (its watchlist, its last round of
    chains); whether it is live is daemon_status's.
    """
    with _lock:
        return _feed["status"]


def watchlist() -> list[str] | None:
    """Return the watchlist: the tickers the capture daemon asks Schwab for.

    A current heartbeat that carries a list is that list; one that carries none is unknown. A late
    or missing heartbeat keeps the list of the last beat.
    """
    st = last_beat()
    return None if st is None else list(st["watchlist"])


@dataclass(frozen=True)
class FeedNow:
    """One read of the daemon's heartbeat at a time.

    `status` is None when that beat is not current. `held` is the symbols on the latest beat: they
    stand when that beat is missing or too old. A beat stamped after `now` contributes neither.
    """

    status: dict[str, Any] | None
    held: dict[str, frozenset[str]]


def feed_now(now: float) -> FeedNow:
    """Read the daemon's heartbeat at `now`, once.

    Current only when its stamp is not older than FEED_HEARTBEAT_MAX_AGE_SEC. A stamp after `now`
    is a later moment, not this one. A beat that is missing or too old is not live, and the symbols
    it last named still stand.
    """
    with _lock:
        rx, status, held = _feed["rx"], _feed["status"], dict(_feed["held"])
    if isinstance(rx, (int, float)) and now < float(rx):
        return FeedNow(None, {})
    current = (
        isinstance(rx, (int, float))
        and isinstance(status, dict)
        and 0.0 <= now - float(rx) < FEED_HEARTBEAT_MAX_AGE_SEC
    )
    return FeedNow(status, held) if current else FeedNow(None, held)


def feed_up(feed: FeedNow) -> bool:
    """Whether `feed` is a current heartbeat reporting the Schwab socket open."""
    return feed.status is not None and feed.status["schwab_socket_open"]


def live_on(feed: FeedNow, symbol: str, service: str) -> bool:
    """Whether `feed` says Schwab `service` is delivering `symbol`."""
    if not feed_up(feed):
        return False
    t = ticker_storage_key(symbol)
    symbols = feed.held.get(service)
    return bool(t) and symbols is not None and t in symbols


def daemon_status(now: float) -> dict[str, Any] | None:
    """Return the daemon's latest status while its heartbeat is current at `now`, else None."""
    return feed_now(now).status


def not_trading(symbol: str, service: str, now: float) -> str | None:
    """Why `symbol`'s values on Schwab `service` are not live at `now`, or None in a valid session.

    The session is time_et.session_label's. Why: no valid session, that /markets answer not held,
    for an option today's option markets closed (time_et.options_open), or for a stock or an index
    Schwab's own SECURITY_STATUS for it Closed or Halted.
    """
    at = datetime.fromtimestamp(now, ET)
    session = session_label(at)
    if session == UNKNOWN:
        return "the market session is unknown"
    if session == CLOSED:
        return "outside Schwab's market hours"
    if service in OPTION_SERVICES:
        return None if options_open(at) else "outside Schwab's option market hours"
    t = ticker_storage_key(symbol)
    status = get_quote(t).security_status
    return f"Schwab marks {t} {status}" if status in ("Closed", "Halted") else None


def live_state(symbol: str, service: str, now: float) -> tuple[str, str | None]:
    """Apply THE live rule, for every streamed value.

    Return `symbol`'s state on Schwab `service` at `now` and why it is not live
    (docs/DATA_FLOW.md §2 D5). LIVE while it is updating: the daemon's heartbeat current
    (feed_now) reporting the Schwab socket open, the symbol held on that service, and a valid
    session (not_trading). OFFLINE while the feed itself is down; NOT LIVE while the feed is
    up and this symbol is not held or no session is valid. The last values stand either way.

    Not "did a value arrive recently": Schwab sends a field only when it CHANGES (measured: 11%
    of 4,039 messages carried bid+ask+last together), so a quiet symbol's unchanged value is its
    current value; judging by arrival age blanks quiet names on a healthy feed.
    """
    return _judge(feed_now(now), symbol, service, now)


def held_option_symbols(
    listed: Collection[str], now: float, feed: FeedNow | None = None
) -> list[str]:
    """Every contract of a ticker's chain (`listed`) on the daemon's latest LEVELONE_OPTIONS beat.

    A missing or too-old beat keeps that set; it does not say the feed is live.
    `feed` is one read of that heartbeat; omitted, this call reads it.
    """
    if feed is None:
        feed = feed_now(now)
    opts = feed.held.get("LEVELONE_OPTIONS")
    if not opts:
        return []
    # each of `listed` looked up in the beat's set, never the beat's thousands in `listed`, which
    # a caller may pass as a list
    return [sym for sym in listed if sym in opts]


def live_symbols(feed: FeedNow, symbols: Iterable[str], service: str, now: float) -> set[str]:
    """Return the `symbols` live on Schwab `service` at `now` by the live rule.

    They are judged on one read of the heartbeat (`feed`).
    """
    return {s for s in symbols if _judge(feed, s, service, now)[0] == LIVE}


def _judge(feed: FeedNow, symbol: str, service: str, now: float) -> tuple[str, str | None]:
    if not feed_up(feed):
        return (
            OFFLINE,
            f"Schwab {service} feed down during {session_label(datetime.fromtimestamp(now, ET))}",
        )
    if not live_on(feed, symbol, service):
        return NOT_LIVE, f"{ticker_storage_key(symbol)} is not streamed on Schwab {service}"
    why = not_trading(symbol, service, now)
    return (LIVE, None) if why is None else (NOT_LIVE, why)


def feed_live_for(symbol: str, service: str, now: float) -> bool:
    """Whether `symbol` on Schwab `service` is live at `now` (live_state)."""
    return live_state(symbol, service, now)[0] == LIVE


def outage(symbol: str, service: str, now: float) -> str | None:
    """Why `symbol` on Schwab `service` is not live at `now`, or None when it is (live_state)."""
    return live_state(symbol, service, now)[1]
