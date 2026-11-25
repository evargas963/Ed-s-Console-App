"""A frame Schwab sends that cannot be parsed is skipped; the connection carries on.

Feed's connection (feed.connection.Connection, run by capture.Daemon.run) on the real schwab-py
StreamClient, logged in to Schwab's streamer played locally (tests/schwab_stream_standin.py)
through Schwab's REST host played locally (tests/schwab_rest_standin.py).
Real data: Schwab's LEVELONE_EQUITIES data frame (tests/fixtures/
real_schwab_field_number_replies_2026_10_12.json, level_one_equities_data). STAND-INS (named in
the stand-ins): the streamer's login, a code-0 answer's message; the text that is not JSON, sent
on NYSE_BOOK, which no logged frame of Schwab's was.
"""

from __future__ import annotations

import asyncio
import logging

from app.market_data.schwab.streaming import capture
from stream_spine import HealthRegistry, MessageBus, held_key
from tests.schwab_rest_standin import LocalSchwab
from tests.schwab_stream_standin import FIELD_REPLIES, LocalStreamer
from tests.shared_helpers import until

#: what the streamer sends on NYSE_BOOK in place of a frame: text schwab-py cannot parse
NOT_JSON = "<html>Service Unavailable</html>"


def test_a_frame_that_cannot_be_parsed_is_skipped_and_the_connection_carries_on(tmp_path, caplog):
    """The quote before it is published, the answers after it are read, on one session."""
    quote = FIELD_REPLIES["level_one_equities_data"]
    streamer = LocalStreamer({}, {"LEVELONE_EQUITIES": quote, "NYSE_BOOK": NOT_JSON})
    rest = LocalSchwab(streamer.url)
    client = rest.client(tmp_path)
    bus = MessageBus()
    daemon = capture.Daemon(bus, HealthRegistry(), ["SPY"])
    symbols = [item["key"] for item in quote["content"]]

    async def go():
        stop = asyncio.Event()
        run = asyncio.create_task(daemon.run(lambda: client, stop))
        # NASDAQ_BOOK is answered after NYSE_BOOK's frame, so it is held once that frame was read
        await until(lambda: daemon.connection.held["NASDAQ_BOOK"])
        stop.set()
        await asyncio.wait_for(run, 10)

    try:
        with caplog.at_level(logging.WARNING, logger="capture"):
            asyncio.run(go())
    finally:
        streamer.close()
        rest.close()
    skipped = [r for r in caplog.records if "skipped a frame" in r.getMessage()]
    assert len(skipped) == 1 and "UnparsableMessage" in skipped[0].getMessage()
    assert [r["command"] for r in streamer.requests].count("LOGIN") == 1, "no reconnect"
    for sym in symbols:  # every quote of Schwab's frame before it, published
        assert held_key("LEVELONE_EQUITIES", sym) in bus.current, sym
