"""Prices and the board straight from the capture daemon to the browser (live_ui.py), end to end.

The REAL daemon-side server (serve_live_ui on a real stream_spine.MessageBus, with the REAL
capture.Daemon holding the board in a real logging_universe table) and a REAL WebSocket client
standing in for the browser, over a real local socket. No console process. Proves:

  * a page gets the board and every board ticker's current row at once, then a row for every
    Schwab change;
  * the row is the one producer's row (live_price_rows.price_row): spot, feed verdict,
    Schwab trade age, and no bar (charts show Schwab's completed bars only);
  * a ticker not on the board is never sent;
  * a page's board edit is answered with the symbol's key, reaches every page, is written to the
    board table and is streamed (the daemon's own wanted list);
  * the feed verdict rides every beat: a closed Schwab socket reads feed_live False within one
    beat, with no message needed from Schwab, beside the values Schwab last sent;
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
from app.market_data.schwab.streaming import capture, live_ui
from calibration.complete_chain_capture import board_tickers
from db import EdDB
from stream_spine import HealthRegistry, MessageBus, quote_msg


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


@pytest.fixture
def daemon(tmp_path):
    """The real daemon holding a real board: SPY and TSLA on the logging_universe table."""
    db = tmp_path / "ed_console.db"
    EdDB(db)
    d = capture.Daemon(MessageBus(), HealthRegistry(), tmp_path / "stream_wanted.json", board_db=db)
    for sym in ("SPY", "TSLA"):
        d.edit_board("board_add", sym, time.time())
    return d


class _Feed:
    """The daemon's status, with Schwab's socket open or closed and SPY and the indexes held
    (TSLA is on the board and not held)."""

    def __init__(self, daemon):
        self.daemon = daemon
        self.open = True

    def __call__(self) -> dict:
        return {**self.daemon.status(), "ts": time.time(), "schwab_socket_open": self.open,
                "held": {"LEVELONE_EQUITIES": ["SPY", "AAPL", "$SPX"]}}


async def _run(daemon, body):
    from websockets.asyncio.client import connect

    port = _free_port()
    stop = asyncio.Event()
    stats: dict = {}
    feed = _Feed(daemon)
    server = asyncio.create_task(live_ui.serve_live_ui(
        daemon.bus, stop, heartbeat_fn=feed, daemon=daemon, host="127.0.0.1", port=port, stats=stats))
    end = time.monotonic() + 5
    while not stats.get("listening") and time.monotonic() < end:
        await asyncio.sleep(0.01)
    assert stats.get("listening")
    try:
        async with connect(f"ws://127.0.0.1:{port}") as ws:
            await body(daemon.bus, ws, feed, stats)
    finally:
        stop.set()
        await asyncio.wait_for(asyncio.gather(server, return_exceptions=True), 5)


async def _next(ws, kind, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        msg = json.loads(await asyncio.wait_for(ws.recv(), max(0.01, end - time.monotonic())))
        if msg.get("type") == kind:
            return msg
    raise AssertionError(f"no {kind} message within {timeout}s")


async def _next_row(ws, sym, pred=lambda r: True, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        msg = json.loads(await asyncio.wait_for(ws.recv(), max(0.01, end - time.monotonic())))
        for r in msg.get("rows") or []:
            if r["ticker"] == sym and pred(r):
                return msg, r
    raise AssertionError(f"no matching {sym} row within {timeout}s")


def test_a_schwab_trade_reaches_the_browser_as_a_finished_live_row(daemon):
    async def body(bus, ws, feed, stats):
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
    asyncio.run(_run(daemon, body))


def test_a_ticker_not_on_the_board_is_never_sent(daemon):
    async def body(bus, ws, feed, stats):
        bus.publish("quote.AAPL", _trade("AAPL", 230.0, time.time()))
        bus.publish("quote.SPY", _trade("SPY", 583.0, time.time()))
        end = time.monotonic() + 0.6
        while time.monotonic() < end:
            msg = json.loads(await asyncio.wait_for(ws.recv(), 1))
            assert all(r["ticker"] in ("SPY", "TSLA") for r in msg.get("rows") or []), msg
    asyncio.run(_run(daemon, body))


def test_a_page_gets_the_board_first_with_each_tickers_key_and_display(daemon):
    async def body(bus, ws, feed, stats):
        first = json.loads(await asyncio.wait_for(ws.recv(), 2))
        assert first == {"type": "board", "board": [{"key": "SPY", "display": "SPY"},
                                                    {"key": "TSLA", "display": "TSLA"}]}
    asyncio.run(_run(daemon, body))


def test_adding_a_ticker_answers_its_key_reaches_every_page_is_stored_and_streamed(daemon):
    """ONE-14 (2026-09-28 audit): the page kept its own list of index roots to match a row to what
    it asked for. The daemon answers the edit with the key its rows carry ("SPX" is "$SPX") and
    display name; the new board goes to every page with the ticker's current row at once; the
    board table holds it and the daemon streams it -- one list, from one edit."""
    async def body(bus, ws, feed, stats):
        from websockets.asyncio.client import connect
        await _next(ws, "board")
        async with connect(f"ws://127.0.0.1:{ws.remote_address[1]}") as other:
            await _next(other, "board")
            bus.publish("quote.$SPX", _trade("$SPX", 6512.25, time.time()))
            await ws.send(json.dumps({"op": "board_add", "symbol": "SPX"}))
            assert await _next(ws, "board_edit") == {
                "type": "board_edit", "op": "board_add", "requested": "SPX", "key": "$SPX",
                "display": "SPX", "error": None}
            seen = await _next(other, "board")
            assert [b["key"] for b in seen["board"]] == ["$SPX", "SPY", "TSLA"]
            _, row = await _next_row(other, "$SPX", lambda r: r["spot"] == 6512.25, timeout=0.5)
            assert row["feed_live"] is True
    asyncio.run(_run(daemon, body))
    assert board_tickers(daemon.board_db) == ["$SPX", "SPY", "TSLA"]
    assert daemon.all_wanted()["LEVELONE_EQUITIES"] == frozenset({"$SPX", "SPY", "TSLA"})
    assert daemon.all_wanted()["CHART_EQUITY"] == daemon.all_wanted()["NEWS_HEADLINE"] \
        == frozenset({"$SPX", "SPY", "TSLA"})


def test_removing_a_ticker_stops_its_rows_and_its_stream_and_keeps_nothing_else(daemon):
    async def body(bus, ws, feed, stats):
        await _next(ws, "board")
        await ws.send(json.dumps({"op": "board_remove", "symbol": "TSLA"}))
        assert (await _next(ws, "board"))["board"] == [{"key": "SPY", "display": "SPY"}]
        assert (await _next(ws, "board_edit"))["key"] == "TSLA"
        bus.publish("quote.TSLA", _trade("TSLA", 400.0, time.time()))
        end = time.monotonic() + 0.5
        while time.monotonic() < end:
            msg = json.loads(await asyncio.wait_for(ws.recv(), 1))
            assert all(r["ticker"] == "SPY" for r in msg.get("rows") or []), msg
    asyncio.run(_run(daemon, body))
    assert board_tickers(daemon.board_db) == ["SPY"]
    assert daemon.all_wanted()["LEVELONE_EQUITIES"] == frozenset({"SPY"})


def test_a_symbol_that_is_not_a_symbol_is_refused_with_why(daemon):
    async def body(bus, ws, feed, stats):
        await _next(ws, "board")
        await ws.send(json.dumps({"op": "board_add", "symbol": "NOT A SYMBOL"}))
        edit = await _next(ws, "board_edit")
        assert edit["key"] is None and edit["error"] == "not a symbol: 'NOT A SYMBOL'"
    asyncio.run(_run(daemon, body))
    assert board_tickers(daemon.board_db) == ["SPY", "TSLA"]


def test_pages_are_told_the_headers_context_slots_with_their_display_names() -> None:
    """TICK-06: the page kept its own ['SPX','NDX','VIX']; the console serves the header's slots,
    each with its display name (each shows its board ticker's row)."""
    import html as _html
    import re
    import server as srv
    page = srv.root().body.decode("utf-8")
    served = json.loads(_html.unescape(re.search(r'<meta name="ed-market-context" content="([^"]*)">', page).group(1)))
    assert served == [{"key": "$SPX", "display": "SPX"}, {"key": "$NDX", "display": "NDX"},
                      {"key": "$VIX", "display": "VIX"}]


def test_a_closed_schwab_socket_reads_feed_down_within_one_beat_and_keeps_what_schwab_sent(daemon):
    """The feed's state is stated beside Schwab's last values, never in place of them (operator
    2026-10-01: "From Schwab's mouth to our UI's ears. Period.")."""
    async def body(bus, ws, feed, stats):
        bus.publish("quote.SPY", _trade("SPY", 583.41, time.time()))
        await _next_row(ws, "SPY", lambda r: r["feed_live"] is True)
        feed.open = False                      # nothing from Schwab; only the beat knows
        msg, row = await _next_row(ws, "SPY", lambda r: r["feed_live"] is False, timeout=1.0)
        assert msg["type"] == "feed" and msg["feed"]["schwab_socket_open"] is False
        assert row["spot"] == 583.41 and row["bid"] == pytest.approx(583.40)
    asyncio.run(_run(daemon, body))


def test_a_board_ticker_the_daemon_does_not_hold_reads_feed_not_live(daemon):
    async def body(bus, ws, feed, stats):
        bus.publish("quote.TSLA", _trade("TSLA", 400.0, time.time()))
        msg, row = await _next_row(ws, "TSLA", lambda r: r["spot"] == 400.0)
        assert row["feed_live"] is False
    asyncio.run(_run(daemon, body))


def test_a_burst_is_conflated_to_the_newest_row_per_symbol(daemon):
    """A browser that is behind gets the newest value of each symbol, never a stale backlog
    (latest-value-per-symbol per client)."""
    async def body(bus, ws, feed, stats):
        await _next_row(ws, "SPY")                      # the (empty) snapshot
        for i in range(500):
            now = time.time()
            bus.publish("quote.SPY", _trade("SPY", 500 + i / 100, now))
            bus.publish("quote.TSLA", _trade("TSLA", 200 + i / 100, now))
        _, spy = await _next_row(ws, "SPY", lambda r: r["spot"] == pytest.approx(504.99))
        _, tsla = await _next_row(ws, "TSLA", lambda r: r["spot"] == pytest.approx(204.99))
        # 1000 messages, far fewer frames: the browser was never handed the backlog
        assert stats["rows_sent"] < 200, stats
    asyncio.run(_run(daemon, body))


def test_shutdown_is_not_held_up_by_a_connected_browser(daemon):
    async def body(bus, ws, feed, stats):
        await _next_row(ws, "SPY")
    t0 = time.monotonic()
    asyncio.run(_run(daemon, body))
    assert time.monotonic() - t0 < 5
