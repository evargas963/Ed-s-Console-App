"""schwab-py's own dispatch (StreamClient.handle_message) calls `label_message` on every handler of
every data entry, then the handler (schwab/streaming.py, handle_message). The daemon registers
NEWS_HEADLINE through `_RawHandler`, as `connect` does: captured SPY and TSLA headlines pass that
dispatch and reach the bus as Schwab sent them. Without `label_message` the call raises and the
rest of the frame is not dispatched.

Stand-ins, named: the record keeps each item and its frame's Schwab timestamp, not the frame, so
each frame is rebuilt as {service, timestamp, content: [item]}; the frames enter through
StreamClient's own queue of messages read before the socket (`_overflow_items`), and `_socket` is
set so that `_receive` reads that queue instead of refusing an unopened socket."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from schwab.streaming import StreamClient

from app.market_data.schwab.streaming.capture import _RawHandler, _publisher
from stream_spine import LOG, HealthRegistry, MessageBus

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "real_spy_tsla_news_headlines.json"


def test_captured_news_frames_pass_schwab_pys_dispatch_into_the_bus():
    rows = json.loads(FIXTURE.read_text(encoding="utf-8"))["rows"]
    assert {r["symbol"] for r in rows} == {"SPY", "TSLA"}
    bus, health = MessageBus(), HealthRegistry()
    log = bus.subscribe("news.", policy=LOG)
    stream = StreamClient(None)
    stream._handlers["NEWS_HEADLINE"].append(_RawHandler(_publisher("NEWS_HEADLINE", bus, health)))
    stream._socket = "frames come from _overflow_items"
    for r in rows:
        stream._overflow_items.appendleft(
            {"data": [{"service": "NEWS_HEADLINE", "timestamp": r["schwab_ts"], "content": [r["native"]]}]})

    async def dispatch() -> None:
        for _ in rows:
            await stream.handle_message()
    asyncio.run(dispatch())

    published = []
    while not log.queue.empty():
        published.append(log.queue.get_nowait())
    assert [(t, m["symbol"], m["schwab_ts"], m["content"]) for t, m in published] == [
        (f"news.{r['symbol']}", r["symbol"], r["schwab_ts"], r["native"]) for r in rows]
    assert health.last("NEWS_HEADLINE") is not None
