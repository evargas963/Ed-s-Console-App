"""The quote per ticker, from Schwab's streamed LEVEL_ONE_EQUITY rows
(`record_from_level_one_equity`): each field the last value Schwab sent, at any hour, and
whether the feed is delivering the symbol now (`feed_live_for`)."""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Any, Optional

from instrument_identity import ticker_storage_key
from numeric_contract import float_finite_or_none, schwab_count, schwab_number
from time_et import ET, session_label



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
                 "OPEN_PRICE", "HIGH_PRICE", "LOW_PRICE")
_COUNT_FIELDS = ("BID_SIZE", "ASK_SIZE", "LAST_SIZE", "TOTAL_VOLUME")
_CLOCK_FIELDS = ("QUOTE_TIME_MILLIS", "TRADE_TIME_MILLIS")
#: signed values (any finite number): Schwab's own change of the LAST_PRICE vs the prior close.
#: Measured: NET_CHANGE_PERCENT arrives with every LAST_PRICE; REGULAR_MARKET_CHANGE_PERCENT
#: with every LAST_PRICE in the regular session (2026-09-28: SPY 113/113, MU 112/112, PCG 17/17)
#: and outside it only on a full refresh; CHANGE_PERCENT never.
_SIGNED_FIELDS = ("NET_CHANGE", "NET_CHANGE_PERCENT", "REGULAR_MARKET_CHANGE_PERCENT")
_fields_by_ticker: dict[str, dict[str, tuple[float, float]]] = {}


def _read_stream_field(name: str, raw: Any) -> Optional[float]:
    """Each field as Schwab sent it (AGENTS.md rule 2); a reported 0 is 0."""
    if name in _COUNT_FIELDS:
        return schwab_count(raw)
    v = schwab_number(raw)
    return v / 1000.0 if v is not None and name in _CLOCK_FIELDS else v


def last_trade(fields: dict[str, Any]) -> "tuple[Optional[float], Optional[float]]":
    """(price, trade time in epoch s): Schwab's LAST_PRICE and TRADE_TIME_MILLIS in a
    LEVELONE_EQUITIES record, each read as sent by the rule the console's price record reads them
    by (_read_stream_field); None for one not sent. The chain history's spot (the daemon's
    capture) and the console's spot are this one reading of the stock's record."""
    return (_read_stream_field("LAST_PRICE", fields.get("LAST_PRICE")),
            _read_stream_field("TRADE_TIME_MILLIS", fields.get("TRADE_TIME_MILLIS")))


def record_from_level_one_equity(ticker: str, item: dict[str, Any], *,
                                 received_ts: float, field_received: "dict[str, float] | None" = None) -> bool:
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

    The first message of a new Schwab connection (received after the daemon's `connected_at`,
    on a record holding only fields received before it) replaces the record whole: no field of
    the ended connection stays (operator 2026-10-13: "reconnect's opening replaces them").
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
        since = _feed["status"].get("connected_at") if _feed["status"] is not None else None
        if since is not None and rts >= since and fs and all(at < since for _v, at in fs.values()):
            fs.clear()                   # the new connection's opening: the whole record
        for name in _PRICE_FIELDS + _COUNT_FIELDS + _CLOCK_FIELDS + _SIGNED_FIELDS:
            if name not in item:
                continue
            seen = True
            v = _read_stream_field(name, item.get(name))
            if v is None:
                fs.pop(name, None)       # not a number (-999, text, NaN): cleared
            else:
                fs[name] = (v, rts if field_received is None else float(field_received[name]))
        snapshot = dict(fs)
    if not seen:
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
        "spot_disp": f"{spot_f:.2f}" if spot_f is not None else None,
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
        "quote_time_source": "schwab_streaming_level_one" if quote_ts is not None else "unavailable",
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
    return True


def get_quote(ticker: str) -> Optional[dict[str, Any]]:
    """Copy of latest plane row for ticker, or None."""
    t = ticker_storage_key(ticker)  # RC-345/F25: canonical quote-plane key (write+read consistent; idempotent on Schwab stream symbols)
    with _lock:
        row = _by_ticker.get(t)
        return dict(row) if row else None




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

#: The daemon's latest status (its heartbeat), the time the daemon stamped it, and the symbols
#: it holds per Schwab service. Written by record_feed_heartbeat / record_feed_down only.
_feed: dict[str, Any] = {"rx": None, "status": None, "held": {}}


def record_feed_heartbeat(msg: dict[str, Any]) -> "dict[str, frozenset[str]] | None":
    """Apply one daemon heartbeat (live_ui's ``feed`` beat), judged by the time the daemon
    stamped it (`ts`), never by when it arrived: a status that waited is as old as it is
    (docs/DATA_FLOW.md §2 D5). A status without its time is not applied. Returns what the daemon
    reported holding per service before this beat, or None when nothing was applied."""
    if not isinstance(msg, dict) or not isinstance(msg.get("ts"), (int, float)):
        return None
    held = {svc: frozenset(ticker_storage_key(s) for s in syms)
            for svc, syms in (msg.get("held") or {}).items() if isinstance(syms, list)}
    with _lock:
        previous = _feed["held"]
        _feed.update(rx=float(msg["ts"]), status=msg, held=held)
    return previous


def record_feed_down() -> None:
    """The connection to the daemon ended: nothing is live until a heartbeat arrives. What it
    last reported holding stands (held_reported) until a heartbeat replaces it."""
    with _lock:
        _feed.update(rx=None, status=None)


def held_reported(service: str) -> frozenset[str]:
    """The symbols the daemon last reported holding on Schwab `service`, its heartbeat live or
    not: their last values stand, marked not live (feed_live_for), until a heartbeat releases
    them (D5)."""
    with _lock:
        return _feed["held"].get(service, frozenset())


def daemon_status(now: float) -> dict[str, Any] | None:
    """The daemon's latest status while its heartbeat is live at `now` (younger than
    FEED_HEARTBEAT_MAX_AGE_SEC), else None: a daemon that stopped reporting holds nothing and
    streams nothing."""
    with _lock:
        rx, status = _feed["rx"], _feed["status"]
    if rx is None or not 0.0 <= now - rx < FEED_HEARTBEAT_MAX_AGE_SEC:
        return None
    return status


def held_by_daemon(service: str, now: float) -> frozenset[str]:
    """The symbols the daemon holds on Schwab `service` at `now`, as its live heartbeat reports
    them; none while its heartbeat is not live (unknown is never confirmation)."""
    if daemon_status(now) is None:
        return frozenset()
    with _lock:
        return _feed["held"].get(service, frozenset())


def feed_live_for(symbol: str | None, service: str, now: float) -> bool:
    """THE live rule, for every streamed value: is Schwab `service` delivering `symbol` right
    now -- the daemon's heartbeat is live (daemon_status), it reports the Schwab socket open,
    and it holds the symbol on that service.

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


def outage(symbol: str | None, service: str, now: float) -> str | None:
    """Why `symbol`'s values from Schwab `service` are not current at `now`, or None when they
    are (docs/DATA_FLOW.md §2 D5): in an open session (Pre-Market, RTH, After-Hours) a value is
    current only while its feed delivers it; while Closed, the values as of the close stand,
    the feed up or down."""
    session = session_label(datetime.fromtimestamp(now, ET))
    if session == "Closed" or feed_live_for(symbol, service, now):
        return None
    return f"Schwab {service} feed down during {session}"


