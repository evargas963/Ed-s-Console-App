"""The price socket's heartbeat survives any one browser (2026-09-26: it stopped for every
browser and the whole screen read "no live feed" on a healthy Schwab socket)."""
from __future__ import annotations

import asyncio

from app.market_data.schwab.streaming import live_ui
from stream_spine import MessageBus


class _Ws:
    def __init__(self, hang: bool = False):
        self.hang, self.sent, self.closed = hang, [], False

    async def send(self, text):
        if self.hang:
            await asyncio.sleep(3600)          # a browser that stopped reading
        self.sent.append(text)

    async def close(self):
        self.closed = True


def test_a_stuck_browser_is_closed_and_the_others_keep_their_beat(monkeypatch):
    monkeypatch.setattr(live_ui, "HEARTBEAT_SEC", 0.05)

    async def go():
        srv = live_ui.LiveUiServer(MessageBus(), lambda: {"ts": 1.0, "schwab_socket_open": True}, {
            "frames_sent": 0, "rows_sent": 0, "last_send_ms": 0.0, "beat_send_failures": 0},
            clock=lambda: 1.0, history_fn=lambda *a: [], daily_fn=lambda *a: [])   # no bar here: Schwab's history unused
        stuck, ok = live_ui._Client(_Ws(hang=True)), live_ui._Client(_Ws())
        srv.clients.update({stuck, ok})
        beat = asyncio.create_task(srv.beat_loop())
        await asyncio.sleep(0.4)
        beat.cancel()
        return stuck, ok, beat

    stuck, ok, beat = asyncio.run(go())
    assert len(ok.ws.sent) >= 3, "the healthy browser stopped getting its beat"
    assert stuck.ws.closed, "the browser that stopped reading was not closed"


def test_the_held_minutes_digest_is_computed_when_they_change_not_every_beat(monkeypatch):
    """The bar verdict's digest of a symbol's held minutes was recomputed for every symbol on
    every beat (45 symbols x up to 780 minutes, each second). It is computed when a minute is
    held, and each beat publishes the held one. Three real SPY minutes of 2026-09-25, then ten
    beats with none."""
    import json
    from pathlib import Path

    import live_price_rows
    from stream_spine import bar_msg

    bars = json.loads((Path(__file__).resolve().parent / "fixtures" / "real_spy_1m_bars_2026_09_24_25.json")
                      .read_text(encoding="utf-8"))["bars"][-30:-27]
    clock = {"now": bars[-1]["timestamp"] / 1000.0 + 62.7}
    calls = []
    real = live_price_rows.minutes_digest
    monkeypatch.setattr(live_price_rows, "minutes_digest", lambda m: calls.append(1) or real(m))

    async def go():
        bus = MessageBus()
        states = bus.subscribe("barstate.", maxsize=64, name="test_console")
        srv = live_ui.LiveUiServer(bus, lambda: {}, {}, clock=lambda: clock["now"], history_fn=lambda *a: [],
                                   daily_fn=lambda *a: [])
        for b in bars:
            srv.on_bar(bar_msg(symbol="SPY", bar_start_ms=b["timestamp"], open=b["open"], high=b["high"],
                               low=b["low"], close=b["close"], volume=b["volume"], src="schwab_chart",
                               ts_recv=clock["now"]))
        held = len(calls)
        for k in range(10):
            srv.publish_states(clock["now"] + k)
        for t in list(srv._asks):
            t.cancel()
        last = None
        while not states.queue.empty():
            last = states.queue.get_nowait()[1]
        return held, len(calls), last, srv.days["SPY"]
    held, total, last, day = asyncio.run(go())
    assert held == total == 3 + 1                      # one per held minute (and the new day's empty set)
    assert last["digest"] == live_price_rows.minutes_digest(day.minutes)


def test_a_failing_daemon_clock_neither_stops_the_beat_nor_the_daemon(monkeypatch):
    """A failure in the daemon's clock (`tick`) ended the beat loop, and with it the daemon,
    which start_capture_daemon.bat restarted every 5 s for as long as the cause lasted. It is
    counted and logged, and the beat goes on. The failing clock is the stand-in."""
    monkeypatch.setattr(live_ui, "HEARTBEAT_SEC", 0.05)

    async def go():
        srv = live_ui.LiveUiServer(MessageBus(), lambda: {"ts": 1.0, "schwab_socket_open": True}, {},
                                   clock=lambda: 1.0, history_fn=lambda *a: [], daily_fn=lambda *a: [])

        def tick(now):
            raise KeyError("a symbol's day")
        monkeypatch.setattr(srv, "tick", tick)
        browser = live_ui._Client(_Ws())
        srv.clients.add(browser)
        beat = asyncio.create_task(srv.beat_loop())
        await asyncio.sleep(0.4)
        alive = not beat.done()
        beat.cancel()
        return srv.stats, browser, alive

    stats, browser, alive = asyncio.run(go())
    assert alive and stats["tick_failures"] >= 3 and len(browser.ws.sent) >= 3
