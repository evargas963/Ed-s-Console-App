"""Prices straight from the capture daemon to the browser (live_ui.py), end to end.

The REAL daemon-side server (serve_live_ui on a real stream_spine.MessageBus) and a REAL
WebSocket client standing in for the browser, over a real local socket. No console process,
no database. Proves:

  * a subscribed symbol gets its current row at once, then a row for every Schwab change;
  * the row is the one producer's row (live_price_rows.price_row): spot, feed verdict,
    Schwab trade age, forming 1m candle;
  * a symbol nobody subscribed to is never sent;
  * the feed verdict rides every beat: a closed Schwab socket turns the price UNAVAILABLE
    within one beat, with no message needed from Schwab;
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
import live_price_rows
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
    monkeypatch.setattr(live_price_rows, "_forming", {})
    monkeypatch.setattr(live_price_rows, "_forming_seen", {})
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
        assert row["spot_state"] == "live" and row["spot_disp"] == "583.41"
        assert row["feed_live"] is True and row["spot_source"] == "streaming_plane"
        assert row["bid"] == pytest.approx(583.40) and row["ask"] == pytest.approx(583.42)
        assert row["trade_ts"] == pytest.approx(now, abs=0.001)      # epoch SECONDS
        assert 0 <= row["trade_age_sec"] < 2
        bar = row["forming_1m"]
        assert bar["t"] == now - (now % 60) and bar["c"] == 583.41
        # the next trade moves it, pushed on its own (not on the beat)
        t0 = time.monotonic()
        bus.publish("quote.SPY", _trade("SPY", 583.90, time.time()))
        msg, row = await _next_row(ws, "SPY", lambda r: r["spot"] == 583.90)
        assert msg["type"] == "quotes"
        assert time.monotonic() - t0 < 0.15, "a change must go out immediately, not on the beat"
        assert row["forming_1m"]["h"] == 583.90
    asyncio.run(_run(body))


def test_an_unsubscribed_symbol_is_never_sent():
    async def body(bus, ws, feed, stats):
        await ws.send(json.dumps({"op": "subscribe", "symbols": ["SPY"]}))
        bus.publish("quote.AAPL", _trade("AAPL", 230.0, time.time()))
        bus.publish("quote.SPY", _trade("SPY", 583.0, time.time()))
        end = time.monotonic() + 0.6
        while time.monotonic() < end:
            msg = json.loads(await asyncio.wait_for(ws.recv(), 1))
            assert all(r["ticker"] == "SPY" for r in msg["rows"]), msg
    asyncio.run(_run(body))


def test_resubscribing_sends_the_new_symbols_current_rows_at_once():
    async def body(bus, ws, feed, stats):
        bus.publish("quote.AAPL", _trade("AAPL", 230.5, time.time()))
        await ws.send(json.dumps({"op": "subscribe", "symbols": ["SPY"]}))
        await ws.send(json.dumps({"op": "subscribe", "symbols": ["SPY", "AAPL"]}))
        msg, row = await _next_row(ws, "AAPL", lambda r: r["spot"] == 230.5, timeout=0.15)
        assert msg["type"] == "quotes"
    asyncio.run(_run(body))


def test_an_index_typed_bare_is_served_under_its_storage_key():
    """The operator types "SPX"; Schwab keys "$SPX". The subscription goes through
    ticker_storage_key, so the typed form gets the index's rows."""
    async def body(bus, ws, feed, stats):
        await ws.send(json.dumps({"op": "subscribe", "symbols": ["SPX"]}))
        bus.publish("quote.$SPX", _trade("$SPX", 6512.25, time.time()))
        _, row = await _next_row(ws, "$SPX", lambda r: r["spot"] == 6512.25)
        assert row["spot_state"] == "live"
    asyncio.run(_run(body, feed=_Feed(held=("$SPX",))))


def test_a_closed_schwab_socket_reads_unavailable_within_one_beat():
    async def body(bus, ws, feed, stats):
        await ws.send(json.dumps({"op": "subscribe", "symbols": ["SPY"]}))
        bus.publish("quote.SPY", _trade("SPY", 583.41, time.time()))
        await _next_row(ws, "SPY", lambda r: r["spot_state"] == "live")
        feed.open = False                      # nothing from Schwab; only the beat knows
        msg, row = await _next_row(ws, "SPY", lambda r: r["spot_state"] == "unavailable",
                                   timeout=1.0)
        assert msg["type"] == "feed" and msg["feed"]["schwab_socket_open"] is False
        assert row["spot"] is None and row["feed_live"] is False and row["bid"] is None
    asyncio.run(_run(body))


def test_a_symbol_the_daemon_does_not_hold_is_not_live():
    async def body(bus, ws, feed, stats):
        await ws.send(json.dumps({"op": "subscribe", "symbols": ["TSLA"]}))
        bus.publish("quote.TSLA", _trade("TSLA", 400.0, time.time()))
        msg, row = await _next_row(ws, "TSLA", lambda r: r["spot_state"] == "unavailable")
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
