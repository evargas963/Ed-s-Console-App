"""Test helper: put live_market_plane's feed state where a real daemon heartbeat would.

Liveness is the FEED's (live_market_plane.feed_live_for): a daemon heartbeat < 3 s old that
reports the Schwab socket open and holds the symbol. Tests that exercise a live price mark
exactly the symbols the daemon would hold -- through the production entry point."""
from __future__ import annotations

import itertools
import json
import time
from pathlib import Path

import live_market_plane as lmp

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def daemon_bars(name: str, *symbols: str) -> list[dict]:
    """The capture daemon's recorded receipts of Schwab's CHART_EQUITY bars in fixture `name`
    (tests/fixtures/real_daemon_bars_*.json), of `symbols` (every symbol when none is named)."""
    rows = json.loads((_FIXTURES / name).read_text(encoding="utf-8"))["rows"]
    return [r for r in rows if not symbols or r["symbol"] in symbols]


def stream_daemon_bars(rows: list[dict]) -> None:
    """What the capture daemon pushes of Schwab's bars: each captured receipt, in the order the
    daemon received them, through the console's own streamed-bar writer (server._write_streamed_bar),
    so each minute holds Schwab's newest bar for it."""
    import server
    for r in sorted(rows, key=lambda r: r["ts_recv"]):
        server._write_streamed_bar(r)


def price_history(symbol: str, series: str) -> dict:
    """Schwab's captured /pricehistory answer for `symbol`'s `series` ("1m", "15m", "1d")
    (tests/fixtures/real_pricehistory_spy_tsla_2026_10_07.json): {params, status, date, sent_utc,
    answered_utc, body}."""
    fx = json.loads((_FIXTURES / "real_pricehistory_spy_tsla_2026_10_07.json").read_text(encoding="utf-8"))
    return next(a for a in fx["answers"] if a["symbol"] == symbol and a["series"] == series)


def mark_feed_live(*tickers: str) -> None:
    """The daemon's heartbeat now, holding `tickers` on LEVELONE_EQUITIES on its connection begun
    at CONNECTED_AT."""
    lmp.record_feed_heartbeat({"ts": time.time(), "schwab_socket_open": True, "connected_at": CONNECTED_AT,
                               "held": {"LEVELONE_EQUITIES": list(tickers)}})


def mark_feed_down() -> None:
    lmp.record_feed_down()


def price_sent(ticker: str, price: float, trade_ts: float) -> None:
    """The LEVELONE_EQUITIES fields the daemon's Schwab push hands the console for `ticker` (its
    last trade and trade time), taken into the console's price record as _rows_loop takes them.
    STAND-IN: the price and trade time are the test's."""
    lmp.record_from_level_one_equity(ticker, {"LAST_PRICE": price, "TRADE_TIME_MILLIS": int(trade_ts * 1000)},
                                     received_ts=trade_ts)


def forget_price(ticker: str) -> None:
    """The console holds no price for `ticker`."""
    lmp._by_ticker.pop(ticker, None)
    lmp._fields_by_ticker.pop(ticker, None)
    lmp._posted.pop((ticker, "LEVELONE_EQUITIES"), None)


#: when the daemon's one connection to Schwab in these tests began (STAND-IN: 2026-08-01 00:00 ET,
#: before every captured message the tests replay)
CONNECTED_AT = 1785556800.0


def daemon_holds(at: float, held: dict, *, socket_open: bool = True, connected_at: float = CONNECTED_AT,
                 picks: "dict | None" = None) -> None:
    """The daemon's heartbeat stamped `at`, holding `held` ({Schwab service: [symbols]}) on its
    connection to Schwab begun at `connected_at`, its option rule picking `picks` (the option
    contracts it holds, when not given) having ranked every ticker it holds on LEVELONE_EQUITIES,
    as the console's feed loop applies it (streaming.apply_heartbeat)."""
    from app.market_data.schwab.streaming.live_ui import OPTION_SERVICES
    from app.options.order_flow import streaming as ofs
    options = {s: (held if picks is None else picks).get(s, []) for s in OPTION_SERVICES}
    ofs.apply_heartbeat({"ts": at, "schwab_socket_open": socket_open, "connected_at": connected_at, "held": held,
                         "options": options, "ranked": held.get("LEVELONE_EQUITIES", [])})


#: the receive time of a tick given none, one second after the last
_RECEIVED = itertools.count(1000)


def through_the_daemons_bus(bus, sym: str, ticks: list, ts: "list[float] | None" = None) -> None:
    """Each LEVELONE_OPTIONS tick of `sym` (received at `ts`, else a second after the last; STAND-IN:
    its Schwab frame time is its receive time, in ms) posted to the contract's record on `bus` as
    the daemon's handler posts it (option_ledger.from_stream, capture._publisher), and the record
    pushed to the console as the daemon pushes it."""
    import option_ledger
    from app.options.order_flow import streaming as ofs
    from stream_spine import current_key
    for i, tick in enumerate(ticks):
        rx = ts[i] if ts is not None else float(next(_RECEIVED))
        ms = int(rx * 1000)
        topic, msg = option_ledger.posting(sym, option_ledger.from_stream({"key": sym, **tick}, ms), ms, rx)
        bus.publish(topic, msg)
        ofs._ingest_pushed(topic, bus.current[current_key(topic, msg)][1])


def daemon_round(bus, ticker: str, contracts: list, round_ts: float) -> None:
    """`ticker`'s round as the chain sweep posts it to the daemon's bus: each captured contract's
    record opened from the chain and its Greeks posted as its /quotes answer posts them, then the
    round's message (calibration.complete_chain_capture.chain_round_message). STAND-IN (named):
    the quote's Greeks are the capture's own (Schwab's quotes' in a daemon capture, the chain's
    rounded ones in a raw chain answer)."""
    import option_ledger
    from calibration.complete_chain_capture import chain_round_message
    for ct in contracts:
        greeks = {g: ct[g] for g in option_ledger.GREEK_FIELDS if g in ct}
        for fields in (option_ledger.opening(ct, ticker), greeks):
            bus.publish(*option_ledger.posting(ct["symbol"], fields, ct.get("quoteTimeInLong"), round_ts))
    bus.publish(*chain_round_message(ticker, round_ts))


def ledger_open(ticker: str, contracts: list, round_ts: float, bus=None):
    """The daemon's ledger (`bus`, a new one when None) holding `ticker`'s captured contracts:
    each record opened from the chain (option_ledger.opening) and its Greeks posted as the sweep's
    /quotes answer posts them, each record pushed to the console as the daemon pushes it. Returns
    the bus. STAND-IN (named): the quote's Greeks are the capture's own (Schwab's quotes' in a
    daemon capture, the chain's rounded ones in a raw chain answer)."""
    import option_ledger
    from app.options.order_flow import streaming as ofs
    from stream_spine import MessageBus, current_key
    bus = bus if bus is not None else MessageBus()
    for ct in contracts:
        greeks = {g: ct[g] for g in option_ledger.GREEK_FIELDS if g in ct}
        for fields in (option_ledger.opening(ct, ticker), greeks):
            topic, msg = option_ledger.posting(ct["symbol"], fields, ct.get("quoteTimeInLong"), round_ts)
            bus.publish(topic, msg)
        ofs._ingest_pushed(topic, bus.current[current_key(topic, msg)][1])
    return bus


def ledger_round(ticker: str, contracts: list, round_ts: float, *, now):
    """`ticker`'s round as the daemon delivers it (ledger_open), priced (server._publish_levels)."""
    import server
    ledger_open(ticker, contracts, round_ts)
    return server._publish_levels(ticker, round_ts, now=now)


def no_daemon() -> None:
    """No daemon: it holds nothing (every contract it held released) and nothing is live."""
    daemon_holds(0.0, {})
    lmp.record_feed_down()


def feed_live_during(monkeypatch, *tickers: str) -> None:
    """For route tests that start the app (TestClient): the app's own push feed loop cannot
    reach a daemon in CI and marks the feed down on every retry, racing the test. Hold the
    feed live for this test by stubbing that mark-down; the feed loop's own behaviour is
    covered end-to-end in tests/test_live_push_channel_v1.py."""
    mark_feed_live(*tickers)
    monkeypatch.setattr(lmp, "record_feed_down", lambda: None)
    # importing/starting the app can take longer than the 3 s heartbeat bound on a loaded CI
    # worker; heartbeat AGE is not what these tests exercise (it has its own tests)
    monkeypatch.setattr(lmp, "FEED_HEARTBEAT_MAX_AGE_SEC", 3600.0)
