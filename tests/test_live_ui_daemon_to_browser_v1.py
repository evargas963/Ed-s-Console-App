"""Prices straight from the capture daemon to the browser (live_ui.py), end to end.

The REAL daemon-side server (serve_live_ui on a real stream_spine.MessageBus) and a REAL
WebSocket client standing in for the browser, over a real local socket. No console process,
no database. Proves:

  * a subscribed symbol gets its current row at once, then a row for every Schwab change;
  * the row is the one producer's row (live_price_rows.price_row): spot, feed verdict,
    Schwab trade age, and no bar (charts show Schwab's completed bars only);
  * a symbol nobody subscribed to is never sent;
  * a symbol the daemon does not hold reads feed_live False (a closed Schwab socket within one
    beat: tests/test_live_ui_beat_survives_v1.py);
  * a slow browser gets the newest row per symbol, never a backlog of stale ones;
  * shutdown is not held up by a connected browser.
"""
from __future__ import annotations

import asyncio
import json
import socket
import time

import pytest

import live_market_plane as lmp
from app.market_data.schwab.streaming import live_ui
from stream_spine import MessageBus, quote_msg


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(autouse=True)
def _fresh_plane(monkeypatch):
    monkeypatch.setattr(lmp, "_by_ticker", {})
    monkeypatch.setattr(lmp, "_fields_by_ticker", {})
    monkeypatch.setattr(live_ui, "HEARTBEAT_SEC", 0.2)


def _trade(sym: str, last: float, ts: float, **extra) -> dict:
    native = {"key": sym, "BID_PRICE": last - 0.01, "ASK_PRICE": last + 0.01,
              "LAST_PRICE": last, "TRADE_TIME_MILLIS": int(ts * 1000),
              "QUOTE_TIME_MILLIS": int(ts * 1000), **extra}
    return quote_msg(symbol=sym, bid=last - 0.01, ask=last + 0.01, last=last,
                     src="schwab_l1", ts_recv=ts, native=native)


class _Feed:
    def __init__(self, held=("SPY", "AAPL")):
        self.open = True
        self.held = list(held)

    def __call__(self) -> dict:
        return {"ts": time.time(), "schwab_socket_open": self.open,
                "held": {"LEVELONE_EQUITIES": self.held}, "health": {}}


async def _run(body, feed=None):
    from websockets.asyncio.client import connect

    port = _free_port()
    bus = MessageBus()
    stop = asyncio.Event()
    stats: dict = {}
    feed = feed if feed is not None else _Feed()
    server = asyncio.create_task(live_ui.serve_live_ui(
        bus, stop, heartbeat_fn=feed, host="127.0.0.1", port=port, stats=stats))
    end = time.monotonic() + 5
    while not stats.get("listening") and time.monotonic() < end:
        await asyncio.sleep(0.01)
    assert stats.get("listening")
    try:
        async with connect(f"ws://127.0.0.1:{port}") as ws:
            await body(bus, ws, feed, stats)
    finally:
        stop.set()
        await asyncio.wait_for(asyncio.gather(server, return_exceptions=True), 5)


async def _next_row(ws, sym, pred=lambda r: True, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        msg = json.loads(await asyncio.wait_for(ws.recv(), max(0.01, end - time.monotonic())))
        for r in msg.get("rows") or []:
            if r["ticker"] == sym and pred(r):
                return msg, r
    raise AssertionError(f"no matching {sym} row within {timeout}s")


def test_a_schwab_trade_reaches_the_browser_as_a_finished_live_row():
    async def body(bus, ws, feed, stats):
        await ws.send(json.dumps({"op": "subscribe", "symbols": ["spy"]}))
        now = time.time()
        bus.publish("quote.SPY", _trade("SPY", 583.41, now))
        msg, row = await _next_row(ws, "SPY", lambda r: r["spot"] == 583.41)
        assert row["spot_disp"] == "583.41" and row["trade_time_ct"] is not None
        assert row["feed_live"] is True and row["spot_source"] == "streaming_plane"
        assert row["bid"] == pytest.approx(583.40) and row["ask"] == pytest.approx(583.42)
        assert row["trade_ts"] == pytest.approx(now, abs=0.001)      # epoch SECONDS
        assert 0 <= row["trade_age_sec"] < 2
        assert "forming_1m" not in row
        # the next trade moves it, pushed on its own (not on the beat)
        t0 = time.monotonic()
        bus.publish("quote.SPY", _trade("SPY", 583.90, time.time()))
        msg, row = await _next_row(ws, "SPY", lambda r: r["spot"] == 583.90)
        assert msg["type"] == "quotes"
        assert time.monotonic() - t0 < 0.15, "a change must go out immediately, not on the beat"
    asyncio.run(_run(body))


def test_an_unsubscribed_symbol_is_never_sent():
    async def body(bus, ws, feed, stats):
        await ws.send(json.dumps({"op": "subscribe", "symbols": ["SPY"]}))
        bus.publish("quote.AAPL", _trade("AAPL", 230.0, time.time()))
        bus.publish("quote.SPY", _trade("SPY", 583.0, time.time()))
        end = time.monotonic() + 0.6
        while time.monotonic() < end:
            msg = json.loads(await asyncio.wait_for(ws.recv(), 1))
            assert all(r["ticker"] == "SPY" for r in msg.get("rows") or []), msg
    asyncio.run(_run(body))


def test_resubscribing_sends_the_new_symbols_current_rows_at_once():
    async def body(bus, ws, feed, stats):
        bus.publish("quote.AAPL", _trade("AAPL", 230.5, time.time()))
        await ws.send(json.dumps({"op": "subscribe", "symbols": ["SPY"]}))
        await ws.send(json.dumps({"op": "subscribe", "symbols": ["SPY", "AAPL"]}))
        msg, row = await _next_row(ws, "AAPL", lambda r: r["spot"] == 230.5, timeout=0.15)
        assert msg["type"] == "quotes"
    asyncio.run(_run(body))


def test_a_subscribe_is_answered_with_what_each_symbol_is_before_its_rows():
    """ONE-14 (2026-09-28 audit): the page stripped "$" in eight places to match a row to what
    it asked for, and kept its own list of index roots. The daemon answers each subscribe with
    each asked-for symbol's key (what its rows carry) and display name, from instrument_identity,
    for an index typed bare or with "$", an ETF and a single name alike."""
    async def body(bus, ws, feed, stats):
        await ws.send(json.dumps({"op": "subscribe", "symbols": ["SPX", "$VIX", "spy", "MU"]}))
        first = json.loads(await asyncio.wait_for(ws.recv(), 2))
        assert first == {"type": "symbols", "symbols": [
            {"requested": "SPX", "key": "$SPX", "display": "SPX"},
            {"requested": "$VIX", "key": "$VIX", "display": "VIX"},
            {"requested": "spy", "key": "SPY", "display": "SPY"},
            {"requested": "MU", "key": "MU", "display": "MU"}]}
    asyncio.run(_run(body))


def test_pages_are_told_the_market_context_with_its_display_names() -> None:
    """TICK-06: the page kept its own ['SPX','NDX','VIX'] beside streaming.MARKET_CONTEXT_SYMBOLS;
    the console now serves the one list, each with its display name."""
    import html as _html
    import re
    import server as srv
    from app.options.order_flow.streaming import MARKET_CONTEXT_SYMBOLS
    page = srv.root().body.decode("utf-8")
    served = json.loads(_html.unescape(re.search(r'<meta name="ed-market-context" content="([^"]*)">', page).group(1)))
    assert [c["key"] for c in served] == list(MARKET_CONTEXT_SYMBOLS)
    assert [c["display"] for c in served] == [k.lstrip("$") for k in MARKET_CONTEXT_SYMBOLS]


def test_an_index_typed_bare_is_served_under_its_storage_key():
    """The operator types "SPX"; Schwab keys "$SPX". The subscription goes through
    ticker_storage_key, so the typed form gets the index's rows."""
    async def body(bus, ws, feed, stats):
        await ws.send(json.dumps({"op": "subscribe", "symbols": ["SPX"]}))
        bus.publish("quote.$SPX", _trade("$SPX", 6512.25, time.time()))
        _, row = await _next_row(ws, "$SPX", lambda r: r["spot"] == 6512.25)
        assert row["feed_live"] is True
    asyncio.run(_run(body, feed=_Feed(held=("$SPX",))))


#: Wednesday 2026-09-30, 11:00 ET (RTH) and 22:00 ET (Closed), as epoch seconds
_RTH, _CLOSED = 1790780400.0, 1790820000.0


def _clock_from(monkeypatch, start: float) -> None:
    """The wall clock running from `start` (the session the test is in); time still passes."""
    real, offset = time.time, start - time.time()
    monkeypatch.setattr(time, "time", lambda: real() + offset)


def test_a_symbol_the_daemon_does_not_hold_reads_feed_not_live(monkeypatch):
    _clock_from(monkeypatch, _CLOSED)

    async def body(bus, ws, feed, stats):
        await ws.send(json.dumps({"op": "subscribe", "symbols": ["TSLA"]}))
        bus.publish("quote.TSLA", _trade("TSLA", 400.0, time.time()))
        msg, row = await _next_row(ws, "TSLA", lambda r: r["spot"] == 400.0)
        assert row["feed_live"] is False
    asyncio.run(_run(body))


def test_a_burst_is_conflated_to_the_newest_row_per_symbol():
    """A browser that is behind gets the newest value of each symbol, never a stale backlog
    (latest-value-per-symbol per client)."""
    async def body(bus, ws, feed, stats):
        await ws.send(json.dumps({"op": "subscribe", "symbols": ["SPY", "AAPL"]}))
        await _next_row(ws, "SPY")                      # the (empty) snapshot
        for i in range(500):
            now = time.time()
            bus.publish("quote.SPY", _trade("SPY", 500 + i / 100, now))
            bus.publish("quote.AAPL", _trade("AAPL", 200 + i / 100, now))
        _, spy = await _next_row(ws, "SPY", lambda r: r["spot"] == pytest.approx(504.99))
        _, aapl = await _next_row(ws, "AAPL", lambda r: r["spot"] == pytest.approx(204.99))
        # 1000 messages, far fewer frames: the browser was never handed the backlog
        assert stats["rows_sent"] < 200, stats
    asyncio.run(_run(body))


def test_shutdown_is_not_held_up_by_a_connected_browser():
    async def body(bus, ws, feed, stats):
        await ws.send(json.dumps({"op": "subscribe", "symbols": ["SPY"]}))
        await _next_row(ws, "SPY")
    t0 = time.monotonic()
    asyncio.run(_run(body))
    assert time.monotonic() - t0 < 5
