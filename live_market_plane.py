"""The live quote per ticker, from Schwab's streamed LEVEL_ONE_EQUITY rows
(`record_from_level_one_equity`), with its live rule (`spot_is_fresh`, `quote_is_fresh`)."""

from __future__ import annotations

import logging
import threading
from datetime import date, datetime, timedelta
from typing import Any, Optional

from instrument_identity import ticker_storage_key
from numeric_contract import float_finite_or_none, schwab_count, schwab_number
from time_et import ET, is_capturable_session

log = logging.getLogger(__name__)



_lock = threading.RLock()
# ticker UPPER -> last plane payload (streaming and/or REST fast quote)
_by_ticker: dict[str, dict[str, Any]] = {}



#: Schwab LEVELONE_EQUITIES sends only the fields that CHANGED since the last message for a
#: symbol. Measured on 4,039 real captured messages (stream_quotes_raw, 2026-09-24): only 11%
#: carried bid, ask and last together; 17% were ask-only, 15% bid-only, 23% none of the three.
#: So a field absent from a message is UNCHANGED, not missing -- the current value of each
#: field is the last one Schwab sent, and its age is the age of THAT message. This table holds
#: exactly that, per ticker, per field: {field: (value, received_ts)}.
_PRICE_FIELDS = ("LAST_PRICE", "BID_PRICE", "ASK_PRICE", "MARK", "CLOSE_PRICE",
                 "OPEN_PRICE", "HIGH_PRICE", "LOW_PRICE", "REGULAR_MARKET_LAST_PRICE")
#: the fields of the day's candle (live_price_rows.day_candle), read with their receive times
#: and the last trade's time (TRADE_TIME_MILLIS, in seconds), which says whose session they are
DAY_FIELDS = ("OPEN_PRICE", "HIGH_PRICE", "LOW_PRICE", "LAST_PRICE", "REGULAR_MARKET_LAST_PRICE", "TOTAL_VOLUME",
              "TRADE_TIME_MILLIS")
_COUNT_FIELDS = ("BID_SIZE", "ASK_SIZE", "LAST_SIZE", "TOTAL_VOLUME")
#: Schwab's own clocks (epoch ms, read in seconds): the quote's, the last trade's, and the bid's
#: and the ask's -- each value is shown with, and judged by, its own
_CLOCK_FIELDS = ("QUOTE_TIME_MILLIS", "TRADE_TIME_MILLIS", "BID_TIME_MILLIS", "ASK_TIME_MILLIS")
#: signed values (any finite number): Schwab's own change of the LAST_PRICE vs the prior close.
#: Measured: NET_CHANGE_PERCENT arrives with every LAST_PRICE; REGULAR_MARKET_CHANGE_PERCENT
#: with every LAST_PRICE in the regular session (2026-09-28: SPY 113/113, MU 112/112, PCG 17/17)
#: and outside it only on a full refresh; CHANGE_PERCENT never.
_SIGNED_FIELDS = ("NET_CHANGE", "NET_CHANGE_PERCENT", "REGULAR_MARKET_CHANGE_PERCENT")
_fields_by_ticker: dict[str, dict[str, tuple[float, float]]] = {}


def session_day(ts: float) -> date:
    """The trading date an instant (epoch seconds) belongs to: sessions start at 04:00 ET, so an
    instant before 04:00 ET belongs to the previous date's (a Schwab trade at Friday 19:59 ET is
    Friday's post-market). The live rules' session (spot_is_fresh, quote_is_fresh); never a
    label on a displayed value, which carries its own time."""
    return (datetime.fromtimestamp(ts, ET) - timedelta(hours=4)).date()


def _read_stream_field(name: str, raw: Any) -> Optional[float]:
    """Each field as Schwab sent it; a reported 0 is 0."""
    if name in _COUNT_FIELDS:
        return schwab_count(raw)
    v = schwab_number(raw)
    return v / 1000.0 if v is not None and name in _CLOCK_FIELDS else v


def record_from_level_one_equity(ticker: str, item: dict[str, Any], *,
                                 received_ts: float) -> bool:
    """
    Ingest one Schwab streaming LEVELONE_EQUITIES content item into the plane.
    Returns True when a plane row was (re)published.

    Per-field state (see _fields_by_ticker): each field present in the message replaces
    that field's value and receive time; absent fields stand (Schwab sends changes only), kept
    with their time whatever the hour (operator 2026-10-01: "if we have it we display it"; the
    price row shows each with its time). A field sent as not a number (-999, text, NaN) holds no
    value from then, with the time Schwab sent it (`not_numbers`); a reported 0 is 0. A row
    is published on any field; spot is LAST_PRICE only (MARK never stands in), None until one
    is sent, and its age is the age of the last LAST_PRICE message, never of the bid/ask tick
    arriving now.

    `received_ts` is REQUIRED: the capture daemon's own receive time for this message -- the
    time of a value only where Schwab sends no time field for it (each value with one -- the last
    trade, the bid, the ask -- is shown with and judged by Schwab's own).
    """
    if not item or not isinstance(item, dict):
        return False
    t = ticker_storage_key(ticker)  # RC-345/F25: canonical quote-plane key
    if not t:
        return False
    rts = float(received_ts)
    seen = False
    with _lock:
        fs = _fields_by_ticker.setdefault(t, {})
        for name in _PRICE_FIELDS + _COUNT_FIELDS + _CLOCK_FIELDS + _SIGNED_FIELDS:
            if name not in item:
                continue
            seen = True
            fs[name] = (_read_stream_field(name, item.get(name)), rts)   # None: not a number
        snapshot = dict(fs)
    if not seen:
        return False

    def val(name: str) -> Optional[float]:
        return snapshot[name][0] if name in snapshot else None

    def when(name: str) -> Optional[float]:
        """The receive time of the message that set `name`'s value (None: no value)."""
        return snapshot[name][1] if val(name) is not None else None

    spot_f = val("LAST_PRICE")
    bid, ask, mark = val("BID_PRICE"), val("ASK_PRICE"), val("MARK")
    quote_ts = val("QUOTE_TIME_MILLIS")   # exchange quote clock; TRADE_TIME never stands in
    out = {
        "ticker": t,
        "spot": spot_f,
        "bid": bid,
        "ask": ask,
        "mark": mark,
        "bid_size": val("BID_SIZE"),
        "ask_size": val("ASK_SIZE"),
        "last_size": val("LAST_SIZE"),
        "prior_close": val("CLOSE_PRICE"),
        "prior_close_received_ts": when("CLOSE_PRICE"),
        # Schwab's own change vs the prior close (0 hops): NET_CHANGE_PERCENT is the last price's,
        # extended hours included; REGULAR_MARKET_CHANGE_PERCENT is the regular session's
        "chg_pct": val("NET_CHANGE_PERCENT"),
        "chg_pct_received_ts": when("NET_CHANGE_PERCENT"),
        "chg_pct_regular": val("REGULAR_MARKET_CHANGE_PERCENT"),
        "chg_pct_regular_received_ts": when("REGULAR_MARKET_CHANGE_PERCENT"),
        # Schwab's own time of the bid and of the ask (BID_TIME_MILLIS, ASK_TIME_MILLIS, epoch s):
        # what each is shown with and what the quote's live rule judges
        "bid_ts": val("BID_TIME_MILLIS"),
        "ask_ts": val("ASK_TIME_MILLIS"),
        # the fields Schwab last sent as not a number (-999, text, NaN)
        "not_numbers": sorted(n for n, (v, _t) in snapshot.items() if v is None),
        "net_change": val("NET_CHANGE"),
        "exchange_quote_ts": quote_ts,
        #: TRADE_TIME_MILLIS (epoch s): the exchange time of the last trade -- the clock a
        #: LAST_PRICE tick belongs to (candles); never used as the quote time.
        "trade_ts": val("TRADE_TIME_MILLIS"),
        "quote_time_source": "schwab_streaming_level_one" if quote_ts is not None else "unavailable",
        "server_received_ts": rts,
        "spot_received_ts": when("LAST_PRICE"),
        "quote_ingestion": "schwab_streaming_level_one",
        "quote_source_detail": {
            "spot": "LAST_PRICE" if spot_f is not None else None,
            "bid": "BID_PRICE" if bid is not None else None,
            "ask": "ASK_PRICE" if ask is not None else None,
            "mid": "schwab_streaming_mark" if mark is not None else "unavailable_missing_mark",
            "quote_ts": "QUOTE_TIME_MILLIS" if quote_ts is not None else "unavailable",
        },
    }
    with _lock:
        _by_ticker[t] = out
    for fn in list(_row_listeners):
        try:
            fn(t)
        except Exception as e:  # noqa: BLE001 -- counted + WARNING; one bad listener never stops ingest
            _row_listener_failures[0] += 1
            n = _row_listener_failures[0]
            if n & (n - 1) == 0:
                log.warning("plane row listener %s failed for %s (%s failures): %s",
                            getattr(fn, "__name__", fn), t, n, e)
    return True


#: callables told the ticker of every published row, in the process that owns this plane: the
#: capture daemon's browser push (live_ui).
_row_listeners: list = []
_row_listener_failures = [0]


def add_row_listener(fn) -> None:
    if fn not in _row_listeners:
        _row_listeners.append(fn)


def remove_row_listener(fn) -> None:
    if fn in _row_listeners:
        _row_listeners.remove(fn)


def get_quote(ticker: str) -> Optional[dict[str, Any]]:
    """Copy of latest plane row for ticker, or None."""
    t = ticker_storage_key(ticker)  # RC-345/F25: canonical quote-plane key (write+read consistent; idempotent on Schwab stream symbols)
    with _lock:
        row = _by_ticker.get(t)
        return dict(row) if row else None


def day_fields(ticker: str) -> dict[str, tuple[float, float]]:
    """The ticker's day fields (DAY_FIELDS) as Schwab last sent them: {field: (value,
    received_ts)}, each field only once sent; value None: Schwab sent it as not a number."""
    t = ticker_storage_key(ticker)
    with _lock:
        fs = _fields_by_ticker.get(t) or {}
        return {k: fs[k] for k in DAY_FIELDS if k in fs}




def plane_row_is_streamed(row: dict) -> bool:
    """True only for a row the Schwab LEVELONE_EQUITIES stream wrote. Rows the REST
    refreshers write carry their own quote_ingestion tag and are NOT stream identity."""
    return (row or {}).get("quote_ingestion") == "schwab_streaming_level_one"  # caps-ok: fail-closed -- no row is not a streamed row


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
#: only while the latest one is younger than this (console clock). The one liveness limit.
FEED_HEARTBEAT_MAX_AGE_SEC: float = 3.0

#: The daemon's latest status (its heartbeat), when it was received, and the symbols it
#: holds per Schwab service. Written by record_feed_heartbeat / record_feed_down only.
_feed: dict[str, Any] = {"rx": None, "status": None, "held": {}}


def record_feed_heartbeat(msg: dict[str, Any], received_at: float) -> None:
    """Apply one daemon heartbeat (topic ``daemon.heartbeat``)."""
    if not isinstance(msg, dict):
        return
    held = {svc: frozenset(ticker_storage_key(s) for s in syms)
            for svc, syms in (msg.get("held") or {}).items() if isinstance(syms, list)}
    with _lock:
        _feed.update(rx=float(received_at), status=msg, held=held)


def record_feed_down() -> None:
    """The connection to the daemon ended: nothing is live until a heartbeat arrives."""
    with _lock:
        _feed.update(rx=None, status=None, held={})


def in_session(now: float) -> bool:
    """The market is in session at `now` (epoch seconds): a trading day, 04:00-20:00 ET. The
    session rule of every live value (time_et.is_capturable_session)."""
    return is_capturable_session(datetime.fromtimestamp(now, ET))


def daemon_status(now: float) -> dict[str, Any] | None:
    """The daemon's latest status while its heartbeat is live at `now` (epoch seconds;
    FEED_HEARTBEAT_MAX_AGE_SEC), else None: a daemon that stopped reporting holds nothing and
    streams nothing."""
    with _lock:
        rx, status = _feed["rx"], _feed["status"]
    if rx is None or not 0.0 <= now - rx < FEED_HEARTBEAT_MAX_AGE_SEC:
        return None
    return status


def feed_live_for(symbol: str | None, service: str, now: float) -> bool:
    """THE live rule, for every streamed value: is Schwab `service` delivering `symbol` at `now`
    -- the daemon's heartbeat is live (daemon_status), it reports the Schwab socket open, and it
    holds the symbol on that service.

    Not "did a value arrive recently": Schwab sends a field only when it CHANGES (measured: 11%
    of 4,039 messages carried bid+ask+last together), so a quiet symbol's unchanged value is its
    current value; judging by arrival age blanked quiet names on a healthy feed (2026-09-24
    08:44 CT, DELL) and kept a dead feed's prices "live" for 30 s."""
    t = ticker_storage_key(symbol or "")
    status = daemon_status(now)
    if not t or status is None or status.get("schwab_socket_open") is not True:
        return False
    with _lock:
        return t in _feed["held"].get(service, ())


def refused_reason(symbol: str | None, service: str, now: float) -> str | None:
    """Schwab's answer when it refused the daemon's subscription of `symbol` on `service` (e.g.
    code 19 REACHED_SYMBOL_LIMIT), from the daemon's live status at `now`; None when not refused."""
    t = ticker_storage_key(symbol or "")
    refused = ((daemon_status(now) or {}).get("refused") or {}).get(service) or {}
    return next((why for sym, why in refused.items() if ticker_storage_key(sym) == t), None) if t else None


def book_is_live(symbol: str | None, service: str, now: float) -> bool:
    """Is `symbol`'s book on `service` live at `now`: the market is in session (trading day,
    04:00-20:00 ET) and the feed holds it (feed_live_for). Outside the session its last book is a
    past observation, as the price is (spot_is_fresh)."""
    return in_session(now) and feed_live_for(symbol, service, now)


def spot_is_fresh(q: dict[str, Any], now: float) -> bool:
    """Is this row's LAST_PRICE live at `now`: the market is in session (trading day,
    04:00-20:00 ET), the stream delivered a LAST_PRICE for it, its trade is in this session
    (TRADE_TIME_MILLIS, or else its receive time, on today's session_day: Schwab re-sends the
    prior day's last trade after midnight) and the feed is live for its symbol (feed_live_for).
    Otherwise it is a past observation, shown with Schwab's trade time (price_row `closed_last`),
    never as the current price. Its age since the last trade is information
    (`trade_ts`), never a reason to blank it."""
    if not in_session(now):
        return False
    received = float_finite_or_none((q or {}).get("spot_received_ts"))
    traded = float_finite_or_none((q or {}).get("trade_ts"))
    if received is None or session_day(traded if traded is not None else received) != session_day(now):
        return False
    return feed_live_for((q or {}).get("ticker"), "LEVELONE_EQUITIES", now)


def quote_is_fresh(q: dict[str, Any], now: float) -> bool:
    """Is this plane row's quote (bid/ask/sizes) live at `now`, for the computations that need
    a live quote: Schwab stamped its bid and its ask in this session (BID_TIME_MILLIS and
    ASK_TIME_MILLIS, the times the screen shows them with) and the feed is live for its symbol
    (feed_live_for). Under Schwab's changed-fields-only delivery an unchanged bid IS the current
    bid while the feed is live; a bid or ask with no time of Schwab's is not live (fail closed).
    Outside the session (is_capturable_session) the quote is a past observation. Display does not
    take this verdict: the price row shows the quote with its time."""
    if not in_session(now):
        return False
    stamped = [float_finite_or_none(q.get(k)) for k in ("bid_ts", "ask_ts")]
    if None in stamped or session_day(min(stamped)) != session_day(now):
        return False
    return feed_live_for(q.get("ticker"), "LEVELONE_EQUITIES", now)
