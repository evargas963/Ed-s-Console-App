"""Schwab's messages straight from the capture daemon to the browser (live_ui.py), end to end, each
by its Schwab delivery type (Streamer API §1.1, §1.5).

The REAL daemon-side path: Schwab's frames into the daemon's own handler (capture._publisher), its
real bus (stream_spine.MessageBus), the real server (serve_live_ui), and a REAL WebSocket client
standing in for the browser, over a real local socket. Real data: every message Schwab sent
2026-10-05 14:00:00-14:00:03 CT (tests/fixtures/real_stream_mix_2026_10_05_1400ct.json: 7,420
LEVELONE_OPTIONS, 152 LEVELONE_EQUITIES, 12 book messages), SPY's CHART_EQUITY bars as Schwab sent
them (tests/fixtures/real_daemon_bars_spy_tsla_2026_10_01_02.json) and one NEWS_HEADLINE item
(tests/fixtures/real_schwab_news_headline_spx_2026_10_05.json). STAND-IN (named): the daemon's
status each beat reports (socket open, symbols held).
"""
from __future__ import annotations

import asyncio
import json
import socket
import time
from pathlib import Path

from app.market_data.schwab.streaming import capture, live_ui
from stream_spine import HealthRegistry, MessageBus

FX = Path(__file__).resolve().parent / "fixtures"
_MIX = json.loads((FX / "real_stream_mix_2026_10_05_1400ct.json").read_text(encoding="utf-8"))["messages"]
_BARS = [r for r in json.loads((FX / "real_daemon_bars_spy_tsla_2026_10_01_02.json").read_text(encoding="utf-8"))["rows"]
         if r["symbol"] == "SPY" and r.get("native")]
_NEWS = json.loads((FX / "real_schwab_news_headline_spx_2026_10_05.json").read_text(encoding="utf-8"))
_EVERY = sorted({m["item"]["key"] for m in _MIX})
#: Wednesday 2026-09-30, 11:00 ET (RTH) and 22:00 ET (Closed), as epoch seconds
_RTH, _CLOSED = 1790780400.0, 1790820000.0


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _Feed:
    """The daemon's status as its heartbeat reports it (STAND-IN)."""

    def __init__(self, held=()):
        self.open = True
        self.held = list(held)

    def __call__(self) -> dict:
        return {"ts": time.time(), "schwab_socket_open": self.open,
                "held": {"LEVELONE_EQUITIES": self.held}, "health": {}}


def _frame(bus, service: str, item: dict, schwab_ts) -> None:
    """One Schwab frame into the daemon's own handler for `service`, as schwab-py hands it."""
    capture._publisher(service, bus, HealthRegistry())({"timestamp": schwab_ts, "content": [item]})


async def _run(body, feed=None, clock=time.time, record_heartbeat=lambda _beat: None):
    from websockets.asyncio.client import connect

    port = _free_port()
    bus = MessageBus()
    stop = asyncio.Event()
    stats: dict = {}
    feed = feed if feed is not None else _Feed()
    server = asyncio.create_task(live_ui.serve_live_ui(
        bus, stop, heartbeat_fn=feed, host="127.0.0.1", port=port, stats=stats,
        record_heartbeat=record_heartbeat, clock=clock))
    end = time.monotonic() + 5
    while not stats.get("listening") and time.monotonic() < end:
        await asyncio.sleep(0.01)
    assert stats.get("listening")
    try:
        async with connect(f"ws://127.0.0.1:{port}", max_size=None) as ws:
            await body(bus, ws, feed, stats)
    finally:
        stop.set()
        await asyncio.wait_for(asyncio.gather(server, return_exceptions=True), 5)


async def _received(ws, quiet: float = 0.5, timeout: float = 20.0) -> "tuple[list[dict], list[dict]]":
    """(every Schwab message, every beat) the client receives until `quiet` s pass with no
    Schwab message."""
    messages, beats = [], []
    end, last = time.monotonic() + timeout, time.monotonic()
    while time.monotonic() < end and time.monotonic() - last < quiet:
        try:
            frame = json.loads(await asyncio.wait_for(ws.recv(), quiet))
        except (asyncio.TimeoutError, TimeoutError):
            break
        if frame["type"] == "schwab":
            messages += frame["messages"]
            last = time.monotonic()
        elif frame["type"] == "feed":
            beats.append(frame)
    return messages, beats


def test_every_schwab_service_reaches_the_client_by_its_delivery_type():
    """Every symbol of the real mix subscribed, then every message Schwab sent: each LEVELONE
    service's fields as the last Schwab sent each (Change: only fields Schwab sent, none lost),
    each book the newest whole book (Whole), every SPY bar with its SEQUENCE in Schwab's order (All
    Sequence) and the headline as sent."""
    async def body(bus, ws, feed, stats):
        await ws.send(json.dumps({"op": "subscribe", "symbols": [*_EVERY, "SPY", "$SPX"]}))
        assert json.loads(await asyncio.wait_for(ws.recv(), 5))["type"] == "symbols"
        for m in _MIX:
            _frame(bus, m["service"], m["item"], m["schwab_ts"])
        for b in _BARS:
            _frame(bus, "CHART_EQUITY", b["native"], b["schwab_ts"])
        _frame(bus, "NEWS_HEADLINE", _NEWS["content"], _NEWS["schwab_ts"])
        got, _beats = await _received(ws)

        want_fields, want_books = {}, {}
        for m in _MIX:
            k = (m["service"], m["item"]["key"])
            if m["service"].startswith("LEVELONE"):
                want_fields.setdefault(k, {}).update(m["item"])
            else:
                want_books[k] = m["item"]
        got_fields, got_books = {}, {}
        for m in got:
            k = (m["service"], m["key"])
            if m["service"].startswith("LEVELONE"):
                got_fields.setdefault(k, {}).update(m["content"])
            elif m["service"].endswith("BOOK"):
                got_books[k] = m["content"]
        assert got_fields == want_fields, "a LEVELONE field Schwab sent was lost or changed"
        assert got_books == want_books, "a book is not the newest whole book Schwab sent"
        bars = [m["content"] for m in got if m["service"] == "CHART_EQUITY"]
        assert bars == [b["native"] for b in _BARS], "a bar was dropped, merged or reordered"
        assert [b["SEQUENCE"] for b in bars] == [b["native"]["SEQUENCE"] for b in _BARS]
        assert [m["content"] for m in got if m["service"] == "NEWS_HEADLINE"] == [_NEWS["content"]]
        assert stats["frames_sent"] < len(_MIX), "a client behind is handed every message one frame each"
    asyncio.run(_run(body))


def test_a_symbol_nobody_asked_for_is_never_sent():
    async def body(bus, ws, feed, stats):
        await ws.send(json.dumps({"op": "subscribe", "symbols": ["SPY"]}))
        for m in _MIX:
            _frame(bus, m["service"], m["item"], m["schwab_ts"])
        got, _beats = await _received(ws)
        assert got and {m["key"] for m in got} == {"SPY"}
    asyncio.run(_run(body))


def test_a_new_subscription_gets_each_symbols_current_record_at_once():
    """Schwab sent AAPL's fields before the client asked for it: on subscribing it gets every
    field Schwab has sent, each the last one, without waiting for a new message."""
    aapl = [m for m in _MIX if m["service"] == "LEVELONE_EQUITIES" and m["item"]["key"] == "AAPL"]
    want: dict = {}
    for m in aapl:
        want.update(m["item"])

    async def body(bus, ws, feed, stats):
        for m in aapl:
            _frame(bus, m["service"], m["item"], m["schwab_ts"])
        await ws.send(json.dumps({"op": "subscribe", "symbols": ["AAPL"]}))
        got, _beats = await _received(ws, quiet=0.3)
        assert [m["content"] for m in got if m["service"] == "LEVELONE_EQUITIES"] == [want]
    asyncio.run(_run(body))


def test_a_subscribe_is_answered_with_what_each_symbol_is_before_its_messages():
    """ONE-14 (2026-09-28 audit): the page stripped "$" in eight places to match a row to what
    it asked for, and kept its own list of index roots. The daemon answers each subscribe with
    each asked-for symbol's key (what its messages carry) and display name, from
    instrument_identity, for an index typed bare or with "$", an ETF and a single name alike."""
    async def body(bus, ws, feed, stats):
        await ws.send(json.dumps({"op": "subscribe", "symbols": ["SPX", "$VIX", "spy", "MU"]}))
        first = json.loads(await asyncio.wait_for(ws.recv(), 2))
        assert first == {"type": "symbols", "symbols": [
            {"requested": "SPX", "key": "$SPX", "display": "SPX"},
            {"requested": "$VIX", "key": "$VIX", "display": "VIX"},
            {"requested": "spy", "key": "SPY", "display": "SPY"},
            {"requested": "MU", "key": "MU", "display": "MU"}]}
    asyncio.run(_run(body))


def test_each_beat_says_whether_each_symbol_is_delivering_and_why_not():
    """The feed state rides every beat, judged at the beat's time (docs/DATA_FLOW.md §2 D5): SPY
    held on an open socket is live; its socket closed during RTH, its values are absent with the
    outage reason; while Closed they stand (no outage); a symbol the daemon does not hold is not
    live."""
    import live_market_plane as lmp

    def l1_state(clock_at: float, socket_open: bool) -> dict:
        out = {}
        start = time.time()

        def clock() -> float:
            return clock_at + time.time() - start

        class Feed(_Feed):
            def __call__(self) -> dict:
                return {**super().__call__(), "ts": clock()}

        async def body(bus, ws, feed, stats):
            feed.open = socket_open
            await ws.send(json.dumps({"op": "subscribe", "symbols": ["SPY", "TSLA"]}))
            while True:
                frame = json.loads(await asyncio.wait_for(ws.recv(), 3))
                if frame["type"] == "feed" and frame["state"]:
                    out.update({k: v["LEVELONE_EQUITIES"] for k, v in frame["state"].items()})
                    return
        try:
            asyncio.run(_run(body, feed=Feed(held=("SPY",)), clock=clock, record_heartbeat=lmp.record_feed_heartbeat))
        finally:
            lmp.record_feed_down()
        return out

    rth_live, rth_down, closed_down = l1_state(_RTH, True), l1_state(_RTH, False), l1_state(_CLOSED, False)
    assert rth_live["SPY"] == {"live": True, "outage": None}
    assert rth_live["TSLA"]["live"] is False
    assert rth_down["SPY"]["live"] is False and rth_down["SPY"]["outage"]
    assert closed_down["SPY"] == {"live": False, "outage": None}


def test_shutdown_is_not_held_up_by_a_connected_browser():
    async def body(bus, ws, feed, stats):
        await ws.send(json.dumps({"op": "subscribe", "symbols": ["SPY"]}))
        await asyncio.wait_for(ws.recv(), 2)
    t0 = time.monotonic()
    asyncio.run(_run(body))
    assert time.monotonic() - t0 < 5
