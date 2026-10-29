"""The quote per ticker, from Schwab's streamed LEVEL_ONE_EQUITY rows
(`record_from_level_one_equity`): each field the last value Schwab sent, at any hour, and
whether the symbol's values are live now (`live_state`): the feed delivers it and its market
trades."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from instrument_identity import ticker_storage_key
from numeric_contract import float_finite_or_none, schwab_count, schwab_number
from time_et import CLOSED, ET, UNKNOWN, option_market_open, session_label

#: the services the capture daemon streams the option rule's contracts on (capture.Daemon.pick_options):
#: they trade only while an option market is open
OPTION_SERVICES = ("LEVELONE_OPTIONS", "OPTIONS_BOOK")
#: the words of a value's state, served to the page: updating now; its feed down; its market not trading
LIVE, OFFLINE, NOT_LIVE = "LIVE", "OFFLINE", "NOT LIVE"


_lock = threading.RLock()
# ticker UPPER -> last plane payload (streaming and/or REST fast quote)
_by_ticker: dict[str, dict[str, Any]] = {}


#: Schwab LEVELONE_EQUITIES sends only the fields that CHANGED since the last message for a
#: symbol. Measured on 4,039 real captured messages (stream_quotes_raw): only 11%
#: carried bid, ask and last together; 17% were ask-only, 15% bid-only, 23% none of the three.
#: So a field absent from a message is UNCHANGED, not missing -- the current value of each
#: field is the last one Schwab sent, and its age is the age of THAT message. This table holds
#: exactly that, per ticker, per field: {field: (value, received_ts)}.
_PRICE_FIELDS = (
    "LAST_PRICE",
    "BID_PRICE",
    "ASK_PRICE",
    "MARK",
    "CLOSE_PRICE",
    "OPEN_PRICE",
    "HIGH_PRICE",
    "LOW_PRICE",
)
_COUNT_FIELDS = ("BID_SIZE", "ASK_SIZE", "LAST_SIZE", "TOTAL_VOLUME")
_CLOCK_FIELDS = ("QUOTE_TIME_MILLIS", "TRADE_TIME_MILLIS")
#: signed values (any finite number): Schwab's own change of the LAST_PRICE vs the prior close.
#: Measured: NET_CHANGE_PERCENT arrives with every LAST_PRICE; REGULAR_MARKET_CHANGE_PERCENT
#: with every LAST_PRICE in the regular session (SPY 113/113, MU 112/112, PCG 17/17)
#: and outside it only on a full refresh; CHANGE_PERCENT never.
_SIGNED_FIELDS = ("NET_CHANGE", "NET_CHANGE_PERCENT", "REGULAR_MARKET_CHANGE_PERCENT")
#: text as sent: Schwab's SECURITY_STATUS (field 32: "Normal, Halted, Closed"), the symbol's own
#: trading status (measured: $SPX Closed outside regular hours, stocks Closed 20:00-04:00 ET, SPY
#: Normal on a Saturday)
_TEXT_FIELDS = ("SECURITY_STATUS",)
_fields_by_ticker: dict[str, dict[str, tuple[float, float]]] = {}


def _read_stream_field(name: str, raw: Any) -> "float | str | None":
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
    field_received: "dict[str, float] | None" = None,
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
    if not item or not isinstance(item, dict):
        return False
    t = ticker_storage_key(ticker)  # the plane's key
    if not t:
        return False
    rts = float(received_ts)
    seen = False
    with _lock:
        fs = _fields_by_ticker.setdefault(t, {})
        for name in _PRICE_FIELDS + _COUNT_FIELDS + _CLOCK_FIELDS + _SIGNED_FIELDS + _TEXT_FIELDS:
            if name not in item:
                continue
            seen = True
            v = _read_stream_field(name, item.get(name))
            if v is None:
                fs.pop(name, None)  # not a number (-999, text, NaN): cleared
            else:
                fs[name] = (v, rts if field_received is None else float(field_received[name]))
        snapshot = dict(fs)
    if not seen:
        return False

    def val(name: str) -> "float | str | None":
        return snapshot[name][0] if name in snapshot else None

    spot_f = val("LAST_PRICE")
    bid, ask, mark = val("BID_PRICE"), val("ASK_PRICE"), val("MARK")
    quote_ts = val("QUOTE_TIME_MILLIS")  # exchange quote clock; TRADE_TIME never stands in
    out = {
        "ticker": t,
        "spot": spot_f,
        "bid": bid,
        "ask": ask,
        "mark": mark,
        "bid_size": val("BID_SIZE"),
        "ask_size": val("ASK_SIZE"),
        "last_size": val("LAST_SIZE"),
        "total_volume": val("TOTAL_VOLUME"),
        "open_price": val("OPEN_PRICE"),
        "high_price": val("HIGH_PRICE"),
        "low_price": val("LOW_PRICE"),
        "prior_close": val("CLOSE_PRICE"),
        # Schwab's own change vs the prior close (0 hops): NET_CHANGE_PERCENT is the last price's,
        # extended hours included; REGULAR_MARKET_CHANGE_PERCENT is the regular session's
        "chg_pct": val("NET_CHANGE_PERCENT"),
        "chg_pct_regular": val("REGULAR_MARKET_CHANGE_PERCENT"),
        "net_change": val("NET_CHANGE"),
        "exchange_quote_ts": quote_ts,
        #: TRADE_TIME_MILLIS (epoch s): the exchange time of the last trade -- the clock a
        #: LAST_PRICE tick belongs to (candles); never used as the quote time.
        "trade_ts": val("TRADE_TIME_MILLIS"),
        "security_status": val("SECURITY_STATUS"),
        "quote_time_source": "schwab_streaming_level_one"
        if quote_ts is not None
        else "unavailable",
        "server_received_ts": rts,
        "spot_received_ts": snapshot["LAST_PRICE"][1] if "LAST_PRICE" in snapshot else None,
        "quote_ingestion": "schwab_streaming_level_one",
        "quote_source_detail": {
            "spot": "LAST_PRICE",
            "bid": "BID_PRICE" if bid is not None else None,
            "ask": "ASK_PRICE" if ask is not None else None,
            "mid": "schwab_streaming_mark" if mark is not None else "unavailable_missing_mark",
            "quote_ts": "QUOTE_TIME_MILLIS" if quote_ts is not None else "unavailable",
        },
    }
    with _lock:
        _by_ticker[t] = out
    for fn in list(_row_listeners):
        fn(t)
    return True


#: callables told the ticker of every published row, in the process that owns this plane: the
#: capture daemon's browser push (live_ui).
_row_listeners: list = []


def add_row_listener(fn) -> None:
    if fn not in _row_listeners:
        _row_listeners.append(fn)


def remove_row_listener(fn) -> None:
    if fn in _row_listeners:
        _row_listeners.remove(fn)


def get_quote(ticker: str) -> Optional[dict[str, Any]]:
    """Copy of latest plane row for ticker, or None."""
    t = ticker_storage_key(ticker)  # the plane's key, the same as the write's
    with _lock:
        row = _by_ticker.get(t)
        return dict(row) if row else None


def plane_row_is_streamed(row: dict) -> bool:
    """True only for a row the Schwab LEVELONE_EQUITIES stream wrote. Rows the REST
    refreshers write carry their own quote_ingestion tag and are NOT stream identity."""
    return (row or {}).get(
        "quote_ingestion"
    ) == "schwab_streaming_level_one"  # caps-ok: fail-closed -- no row is not a streamed row


def plane_spot_is_last_price(row: dict[str, Any] | None) -> bool:
    """True only when this plane row's spot is a native Schwab LAST_PRICE."""
    if not row or not isinstance(row, dict):
        return False
    if float_finite_or_none(row.get("spot")) is None:
        return False
    qsd = row.get("quote_source_detail")
    if not isinstance(qsd, dict):
        return False
    return qsd.get("spot") == "LAST_PRICE"


#: The daemon sends its status every second; the daemon, and everything it streams, is live
#: only while the latest one was stamped within this of the time judged. The one liveness limit.
FEED_HEARTBEAT_MAX_AGE_SEC: float = 3.0

#: The daemon's latest status (its heartbeat), the time the daemon stamped it, the symbols
#: it holds per Schwab service, and the last watchlist a beat carried. Written by
#: record_feed_heartbeat / record_feed_down only. A down feed keeps `held` and `watchlist`.
_feed: dict[str, Any] = {"rx": None, "status": None, "held": {}, "watchlist": None}


def record_feed_heartbeat(msg: dict[str, Any]) -> None:
    """Apply one daemon heartbeat (live_ui's ``feed`` beat), judged by the time the daemon
    stamped it (`ts`), never by when it arrived: a status that waited is as old as it is
    (docs/DATA_FLOW.md §2 D5). A status without its time is not applied."""
    if not isinstance(msg, dict) or not isinstance(msg.get("ts"), (int, float)):
        return
    held = {
        svc: frozenset(ticker_storage_key(s) for s in syms)
        for svc, syms in (msg.get("held") or {}).items()
        if isinstance(syms, list)
    }
    watchlist = msg.get("watchlist")
    with _lock:
        _feed.update(rx=float(msg["ts"]), status=msg, held=held)
        if isinstance(watchlist, list):
            _feed["watchlist"] = list(watchlist)


def record_feed_down() -> None:
    """The connection to the daemon ended: nothing is live until a heartbeat arrives.
    The symbols that beat last named stay, so the last streamed values still price.
    The last watchlist stays with them."""
    with _lock:
        _feed.update(rx=None, status=None)


def last_watchlist() -> list[str] | None:
    """The watchlist on the latest beat that carried one, current or not. None until a beat
    carries a list. A missing beat does not erase it."""
    with _lock:
        watchlist = _feed.get("watchlist")
    if not isinstance(watchlist, list):
        return None
    return list(watchlist)


@dataclass(frozen=True)
class FeedNow:
    """One read of the daemon's heartbeat at a time. `status` is None when that beat is not
    current. `held` is the symbols on the latest beat: they stand when that beat is missing
    or too old. A beat stamped after `now` contributes neither."""

    status: dict[str, Any] | None
    held: dict[str, frozenset[str]]


def feed_now(now: float) -> FeedNow:
    """The daemon's heartbeat at `now`, read once. Current only when its stamp is not older
    than FEED_HEARTBEAT_MAX_AGE_SEC. A stamp after `now` is a later moment, not this one.
    A beat that is missing or too old is not live, and the symbols it last named still stand."""
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
    return feed.status is not None and feed.status.get("schwab_socket_open") is True


def live_on(feed: FeedNow, symbol: str | None, service: str) -> bool:
    """Whether `feed` says Schwab `service` is delivering `symbol`."""
    if symbol is None or not feed_up(feed):
        return False
    t = ticker_storage_key(symbol)
    symbols = feed.held.get(service)
    return bool(t) and symbols is not None and t in symbols


def daemon_status(now: float) -> dict[str, Any] | None:
    """The daemon's latest status while its heartbeat is current at `now`, else None."""
    return feed_now(now).status


def held_by_daemon(service: str, now: float) -> frozenset[str]:
    """The symbols the daemon holds on Schwab `service` at `now`; none while its heartbeat
    is not current (unknown is never confirmation)."""
    feed = feed_now(now)
    if feed.status is None:
        return frozenset()
    return feed.held.get(service, frozenset())


#: why an option contract is not trading, by whether its own option market is open (None: the
#: contract's market is not known, no chain held lists it)
_OPTION_MARKET_WHY = {
    True: None,
    False: "outside Schwab's option market hours",
    None: "the contract's option market is not known",
}


def not_trading(
    symbol: str | None, service: str, now: float, product: str | None = None
) -> str | None:
    """Why `symbol`'s values on Schwab `service` are not changing at `now`, or None while its
    market trades: the stock market outside the sessions Schwab's /markets answer sent for today
    (or that answer not held); an option contract outside its own option market's regular window
    (`product`, EQO or IND: time_et.option_close_product of the ticker whose chain lists it), or
    that market not known; or Schwab's own SECURITY_STATUS for the symbol Closed or Halted."""
    at = datetime.fromtimestamp(now, ET)
    session = session_label(at)
    if session == UNKNOWN:
        return "the market session is unknown"
    if session == CLOSED:
        return "outside Schwab's market hours"
    if service in OPTION_SERVICES:
        return _OPTION_MARKET_WHY[None if product is None else option_market_open(at, product)]
    t = ticker_storage_key(symbol)
    row = get_quote(t) if t else None
    status = row.get("security_status") if row is not None else None
    return f"Schwab marks {t} {status}" if status in ("Closed", "Halted") else None


def live_state(
    symbol: str | None, service: str, now: float, product: str | None = None
) -> tuple[str, str | None]:
    """THE live rule, for every streamed value: `symbol`'s state on Schwab `service` at `now` and
    why it is not live (docs/DATA_FLOW.md §2 D5). LIVE while it is updating: the daemon's heartbeat
    current (feed_now) reporting the Schwab socket open, the symbol held on that service, and its
    market trading (not_trading; an option contract by its own option market, `product`). OFFLINE while the feed itself is down; NOT LIVE while the feed is
    up and this symbol is not held or its market is not trading. The last values stand either way.

    Not "did a value arrive recently": Schwab sends a field only when it CHANGES (measured: 11%
    of 4,039 messages carried bid+ask+last together), so a quiet symbol's unchanged value is its
    current value; judging by arrival age blanks quiet names on a healthy feed."""
    return _judge(feed_now(now), symbol, service, now, product)


def live_symbols(
    feed: FeedNow, symbols, service: str, now: float, product: str | None = None
) -> set[str]:
    """The `symbols` live on Schwab `service` at `now` by the live rule, judged on one read of
    the heartbeat (`feed`)."""
    return {s for s in symbols if _judge(feed, s, service, now, product)[0] == LIVE}


def _judge(
    feed: FeedNow, symbol: str | None, service: str, now: float, product: str | None
) -> tuple[str, str | None]:
    if not feed_up(feed):
        return (
            OFFLINE,
            f"Schwab {service} feed down during {session_label(datetime.fromtimestamp(now, ET))}",
        )
    if not live_on(feed, symbol, service):
        return NOT_LIVE, f"{ticker_storage_key(symbol)} is not streamed on Schwab {service}"
    why = not_trading(symbol, service, now, product)
    return (LIVE, None) if why is None else (NOT_LIVE, why)


def feed_live_for(symbol: str | None, service: str, now: float, product: str | None = None) -> bool:
    """Whether `symbol` on Schwab `service` is live at `now` (live_state)."""
    return live_state(symbol, service, now, product)[0] == LIVE


def outage(symbol: str | None, service: str, now: float, product: str | None = None) -> str | None:
    """Why `symbol` on Schwab `service` is not live at `now`, or None when it is (live_state)."""
    return live_state(symbol, service, now, product)[1]
