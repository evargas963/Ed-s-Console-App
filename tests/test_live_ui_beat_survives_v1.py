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
