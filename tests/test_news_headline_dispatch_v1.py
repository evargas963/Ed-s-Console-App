"""The daemon's NEWS_HEADLINE path end to end, as Schwab's socket delivers it: `Daemon.connect` logs
schwab-py in and registers its handlers, `Daemon.read_for` reads the frames, and schwab-py's own
dispatch calls `label_message` on every handler of every data entry, then the handler
(schwab/streaming.py, handle_message). Captured SPY and TSLA headlines reach the bus as Schwab sent
them. Without `_RawHandler.label_message` schwab-py's call raises, the frame is skipped, and none
of them arrives.

Stand-ins, named: Schwab's streamer is a websocket server on 127.0.0.1 that answers each request
with code 0 and, after LOGIN, sends the recorded frames; the Schwab client is a stand-in whose user
preferences point streamerSocketUrl at that server. The record keeps each item and its frame's
Schwab timestamp, not the frame, so each frame is rebuilt as {service, timestamp, command,
content: [item]}."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from websockets.asyncio.server import serve

from app.market_data.schwab.streaming.capture import Daemon
from stream_spine import LOG, HealthRegistry, MessageBus

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "real_spy_tsla_news_headlines.json"


class _Preferences:
    """GET /userPreference as the stand-in client returns it: the streamer at `url`."""

    status_code = 200

    def __init__(self, url: str) -> None:
        self.url = url

    def json(self) -> dict:
        return {"streamerInfo": [{"streamerSocketUrl": self.url, "schwabClientCustomerId": "stand-in",
                                  "schwabClientCorrelId": "stand-in", "schwabClientChannel": "N9",
                                  "schwabClientFunctionId": "APIAPP"}]}


def _stand_in_client(url: str) -> SimpleNamespace:
    """The Schwab client as schwab-py's StreamClient.login reads it: its user preferences and its
    token's access_token."""
    return SimpleNamespace(token_metadata=SimpleNamespace(token={"access_token": "stand-in"}),
                           get_user_preferences=lambda: _Preferences(url))


def _frames(rows: list[dict]) -> list[str]:
    return [json.dumps({"data": [{"service": "NEWS_HEADLINE", "timestamp": r["schwab_ts"], "command": "SUBS",
                                  "content": [r["native"]]}]}) for r in rows]


async def _streamer(ws, frames: list[str]) -> None:
    """Answer every request with code 0; after LOGIN, send the recorded frames."""
    async for text in ws:
        for req in json.loads(text)["requests"]:
            await ws.send(json.dumps({"response": [{
                "service": req["service"], "requestid": req["requestid"], "command": req["command"],
                "timestamp": 0, "content": {"code": 0, "msg": "stand-in"}}]}))
            if req["command"] == "LOGIN":
                for frame in frames:
                    await ws.send(frame)


def test_captured_news_frames_reach_the_bus_through_the_daemons_connection():
    rows = json.loads(FIXTURE.read_text(encoding="utf-8"))["rows"]
    assert {r["symbol"] for r in rows} == {"SPY", "TSLA"}
    bus, health = MessageBus(), HealthRegistry()
    log = bus.subscribe("news.", policy=LOG)

    async def run() -> None:
        async with serve(lambda ws: _streamer(ws, _frames(rows)), "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            daemon = Daemon(bus, health)
            await daemon.connect(_stand_in_client(f"ws://127.0.0.1:{port}"))
            try:
                await daemon.read_for(3.0)
            finally:
                await daemon.disconnect()
    asyncio.run(run())

    published = []
    while not log.queue.empty():
        published.append(log.queue.get_nowait())
    assert [(t, m["symbol"], m["schwab_ts"], m["content"]) for t, m in published] == [
        (f"news.{r['symbol']}", r["symbol"], r["schwab_ts"], r["native"]) for r in rows]
    assert health.last("NEWS_HEADLINE") is not None
