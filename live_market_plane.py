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
_CLOCK_FIELDS = ("QUOTE_TIME_MILLIS", "TRADE_TIME_MILLIS")
#: signed values (any finite number): Schwab's own change of the LAST_PRICE vs the prior close.
#: Measured: NET_CHANGE_PERCENT arrives with every LAST_PRICE; REGULAR_MARKET_CHANGE_PERCENT
#: with every LAST_PRICE in the regular session (2026-09-28: SPY 113/113, MU 112/112, PCG 17/17)
#: and outside it only on a full refresh; CHANGE_PERCENT never.
_SIGNED_FIELDS = ("NET_CHANGE", "NET_CHANGE_PERCENT", "REGULAR_MARKET_CHANGE_PERCENT")
_fields_by_ticker: dict[str, dict[str, tuple[float, float]]] = {}


def session_day(ts: float) -> date:
    """The session an instant (epoch seconds) belongs to: sessions start at 04:00 ET, so an
    instant before 04:00 ET belongs to the previous date's. Schwab's overnight messages mix the
    old day (full snapshots after 20:00 ET, and after midnight: SPY 2026-09-08 00:02 ET re-sent
    Friday 09-04's volume, high, low and open) and the new (its overnight day roll) and cannot be
    told apart, so none is the new session's."""
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
    that field's value and receive time; absent fields stand (Schwab sends changes only)
    within one session (session_day): a field received in an earlier session is dropped by the
    first message of a new one, never carried into it. A field sent as not a number (-999, text, NaN) CLEARS it: the vendor said there is no such
    value now; a reported 0 is 0. A row is published once a LAST_PRICE is known; spot is
    LAST_PRICE only (MARK never stands in) and its age is the age of the last LAST_PRICE
    message, never of the bid/ask tick arriving now.

    `received_ts` is REQUIRED: the capture daemon's own receive time for this message --
    what every freshness check judges (2026-09-23 audit P0).
    """
    if not item or not isinstance(item, dict):
        return False
    t = ticker_storage_key(ticker)  # RC-345/F25: canonical quote-plane key
    if not t:
        return False
    rts = float(received_ts)
    day = session_day(rts)
    seen = False
    with _lock:
        fs = _fields_by_ticker.setdefault(t, {})
        for name in [n for n, (_v, ts) in fs.items() if session_day(ts) != day]:
            del fs[name]
        for name in _PRICE_FIELDS + _COUNT_FIELDS + _CLOCK_FIELDS + _SIGNED_FIELDS:
            if name not in item:
                continue
            seen = True
            v = _read_stream_field(name, item.get(name))
            if v is None:
                fs.pop(name, None)       # not a number (-999, text, NaN): cleared
            else:
                fs[name] = (v, rts)
        snapshot = dict(fs)
    if not seen or "LAST_PRICE" not in snapshot:
        return False

    def val(name: str) -> Optional[float]:
        return snapshot[name][0] if name in snapshot else None

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
        # Schwab's own change vs the prior close (0 hops): NET_CHANGE_PERCENT is the last price's,
        # extended hours included; REGULAR_MARKET_CHANGE_PERCENT is the regular session's
        "chg_pct": val("NET_CHANGE_PERCENT"),
        "chg_pct_regular": val("REGULAR_MARKET_CHANGE_PERCENT"),
        "net_change": val("NET_CHANGE"),
        "exchange_quote_ts": quote_ts,
        #: TRADE_TIME_MILLIS (epoch s): the exchange time of the last trade -- the clock a
        #: LAST_PRICE tick belongs to (candles); never used as the quote time.
        "trade_ts": val("TRADE_TIME_MILLIS"),
        "quote_time_source": "schwab_streaming_level_one" if quote_ts is not None else "unavailable",
        "server_received_ts": rts,
        "spot_received_ts": snapshot["LAST_PRICE"][1],
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
    received_ts)}, each field only once sent."""
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
    04:00-20:00 ET), the stream delivered a LAST_PRICE for it in THIS session
    (`spot_received_ts`; an earlier session's is a past observation) and the feed is live for
    its symbol (feed_live_for). Outside the session it is a past observation. Its age since the
    last trade is information (`trade_ts`), never a reason to blank it."""
    if not in_session(now):
        return False
    received = float_finite_or_none((q or {}).get("spot_received_ts"))
    if received is None or session_day(received) != session_day(now):
        return False
    return feed_live_for((q or {}).get("ticker"), "LEVELONE_EQUITIES", now)


def streamed_chg_pct(row: dict[str, Any] | None, now: float, key: str = "chg_pct") -> Optional[float]:
    """A Schwab LEVELONE_EQUITIES percent change (0 hops) from a row the stream wrote, while its
    LAST_PRICE is fresh at `now`: `chg_pct` (NET_CHANGE_PERCENT, extended hours included, sent
    with every LAST_PRICE -- measured on 4,039 messages) or `chg_pct_regular`
    (REGULAR_MARKET_CHANGE_PERCENT). Otherwise None: no REST value, no stale row (2026-09-24)."""
    if not (row and plane_row_is_streamed(row) and spot_is_fresh(row, now)):
        return None
    return float_finite_or_none(row.get(key))


def quote_is_fresh(q: dict[str, Any], now: float) -> bool:
    """Is this plane row's quote (bid/ask/sizes) live at `now`: the stream wrote the row
    (`server_received_ts`) and the feed is live for its symbol (feed_live_for). Under
    Schwab's changed-fields-only delivery an unchanged bid IS the current bid while the feed
    is live; a missing server_received_ts cannot be assumed live (fail closed), and a row
    written in an earlier session (session_day) is a past observation. Outside the session
    (is_capturable_session) the quote is a past observation."""
    if not in_session(now):
        return False
    received = float_finite_or_none(q.get("server_received_ts"))
    if received is None or session_day(received) != session_day(now):
        return False
    return feed_live_for(q.get("ticker"), "LEVELONE_EQUITIES", now)
