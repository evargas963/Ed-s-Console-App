"""The program's one reader of Schwab's stream keeps up while a whole chain is read and priced.

The capture daemon's connection (capture.Daemon.run_connection) on the real schwab-py StreamClient,
logged in to Schwab's streamer played locally (tests/schwab_stream_standin.py), its market
follower (follow_market) and the console's feed bound to it (streaming.start_order_flow_stream
with server.FEED_CALLBACKS), all on one event loop as capture.run runs them. A thread samples how
far behind Schwab's stream the reader is: this computer's time less Schwab's newest time on the
frames read (capture._TimedStream.schwab_ts).

Real data: SPY's whole chain as Schwab sent it, every expiry, 12,904 contracts (production's
newest complete capture, 2026-11-09 10:06:10 CT), with the spot captured with it; Schwab's
LEVELONE_EQUITIES data entry of 2026-10-12 and stored SPY books of 2026-11-02, taken back to the
field numbers Schwab sends by schwab-py's own field enums. STAND-INS (named in the stand-ins):
the streamer's login, its heartbeat every 0.1 s (BEAT_SEC), each price reaching the daemon as a
LEVELONE_EQUITIES LAST_PRICE.
"""

from __future__ import annotations

import asyncio
import copy
import json
import threading
from pathlib import Path

from schwab.streaming import StreamClient

import live_market_plane as lmp
import server
import time_et
from app.market_data.schwab.streaming import capture
from app.options.order_flow import streaming as ofs
from calibration.complete_chain_capture import chain_messages
from option_contract import read_chain
from stream_spine import HealthRegistry, MessageBus, quote_msg
from tests.schwab_rest_standin import LocalSchwab
from tests.schwab_stream_standin import FIELD_REPLIES, LocalStreamer

_FX = Path(__file__).parent / "fixtures"
SPY = json.loads((_FX / "real_spy_full_chain_2026_11_09.json").read_text(encoding="utf-8"))
BOOKS = json.loads((_FX / "real_spy_books_2026_11_02.json").read_text(encoding="utf-8"))
#: the streamer's heartbeat: a frame every 0.1 s, so a reader held up shows within one
BEAT_SEC = 0.1


def _read_sec() -> float:
    """How long this computer takes to read SPY's chain (read_chain), alone, before the run.

    The bound on how far the reader may fall behind: the chain is read, ranked, priced and
    stamped while Schwab's frames arrive, and none of that work is the reader's, so no stretch
    of it may hold the reader for as long as reading the chain takes. The reader's own work on a
    frame is a small part of a millisecond; what remains is its turns at the interpreter lock
    with the pricing thread.
    """
    started = time_et.elapsed()
    read_chain(SPY["chain"])
    return time_et.elapsed() - started


def _numbered(item: dict, fields) -> dict:
    """An item schwab-py named, back to the field numbers Schwab sends (its enums' values)."""
    return {k if k == "key" else str(fields[k].value): v for k, v in item.items()}


def _book_numbered(item: dict) -> dict:
    out = _numbered(item, StreamClient.BookFields)
    for side, level_fields, venue_fields in capture.BOOK_SIDES:
        number = str(StreamClient.BookFields[side].value)
        if number in out:
            out[number] = [
                {
                    **_numbered({k: v for k, v in level.items() if k != side}, level_fields),
                    str(level_fields[side].value): [
                        _numbered(venue, venue_fields) for venue in level[side]
                    ],
                }
                for level in out[number]
            ]
    return out


def test_each_frame_is_named_as_schwab_pys_label_message_names_it_without_its_copy():
    """_label names an entry in place, as schwab-py's handlers name it after copying it whole."""
    stream = StreamClient(None)
    stream.add_level_one_equity_handler(lambda m: m)
    stream.add_nyse_book_handler(lambda m: m)
    stream.add_nasdaq_book_handler(lambda m: m)
    entries = [FIELD_REPLIES["level_one_equities_data"]]
    for svc in ("NYSE_BOOK", "NASDAQ_BOOK"):
        items = [_book_numbered(native) for _ts, s, native in BOOKS["rows"] if s == svc][:20]
        entries.append({"service": svc, "timestamp": 0, "command": "SUBS", "content": items})
    named = []
    for entry in entries:
        [handler] = stream._handlers[entry["service"]]
        theirs = handler.label_message(copy.deepcopy(entry))
        ours = copy.deepcopy(entry)
        assert capture._label(ours) is ours, "named in place, never copied"
        assert json.dumps(ours) == json.dumps(theirs), entry["service"]
        named.append(ours)
    assert any(level["BIDS"] for e in named[1:] for i in e["content"] for level in i["BIDS"])
    assert named[1]["content"][0] == BOOKS["rows"][0][2], "Schwab's book as stored"


async def _until(cond, seconds: float, state=lambda: None) -> None:
    deadline = time_et.elapsed() + seconds
    while not cond():
        assert time_et.elapsed() < deadline, f"not reached in time: {state()}"
        await asyncio.sleep(0.05)


def test_the_reader_keeps_up_while_spys_whole_chain_is_read_and_priced(tmp_path):
    """SPY's 12,904 contracts reach the option rule and the console: the reader keeps up.

    The daemon reads the chain for its option rule and the console prices it and stamps its
    heatmap. Production (2026-11-09) ran those on the event loop that reads Schwab's stream, and
    the reader fell up to 17.97 s behind Schwab. Here no stretch of that work holds the reader
    as long as reading the chain takes (_read_sec).
    """
    bound = _read_sec()
    streamer = LocalStreamer({}, data={}, beat=BEAT_SEC)
    rest = LocalSchwab(streamer.url)
    client = rest.client(tmp_path)
    bus = MessageBus()
    daemon = capture.Daemon(bus, HealthRegistry(), ["SPY"], clock=lambda: SPY["capture_ts_utc"])
    behind: list[float] = []
    sampled = threading.Event()

    def sample() -> None:
        while not sampled.wait(0.01):
            if daemon.stream is not None and daemon.stream.schwab_ts is not None:
                behind.append(time_et.now() - daemon.stream.schwab_ts)

    async def go():
        stop = asyncio.Event()
        ofs.bind_daemon(daemon)  # as capture.serve_console binds it
        assert ofs.start_order_flow_stream(**server.FEED_CALLBACKS)
        tasks = [
            asyncio.create_task(daemon.run_connection(client, stop)),
            asyncio.create_task(daemon.follow_market(stop)),
        ]
        sampler = threading.Thread(target=sample, daemon=True)
        try:
            await _until(lambda: daemon.held["LEVELONE_EQUITIES"], 30)
            sampler.start()
            bus.publish(
                "quote.SPY",
                quote_msg(
                    symbol="SPY",
                    last=SPY["spot"],
                    src="schwab_l1",
                    native={"key": "SPY", "LAST_PRICE": SPY["spot"]},
                ),
            )
            for topic, msg in chain_messages(
                "SPY", SPY["chain"], SPY["capture_ts_utc"], SPY["spot"], SPY["capture_ts_utc"]
            ):
                bus.publish(topic, msg)
            # the rule picked from the read chain and Schwab holds it; the console priced it
            # and stamped its heatmap
            await _until(
                lambda: (
                    daemon.held["LEVELONE_OPTIONS"]
                    and server.published_levels("SPY") is not None
                    and server.published_levels("SPY").gamma_surface is not None
                ),
                180,
                lambda: {
                    "held": len(daemon.held["LEVELONE_OPTIONS"]),
                    "options": len(daemon.options["LEVELONE_OPTIONS"]),
                    "levels": server.published_levels("SPY") is not None,
                    "why": server._terrain_refresh_last_error.get("SPY"),
                },
            )
            await asyncio.sleep(2 * ofs.HEARTBEAT_SEC)  # the beats that restamp it
        finally:
            sampled.set()
            sampler.join(5)
            stop.set()
            ofs.stop_order_flow_stream()
            ofs.bind_daemon(None)
            await asyncio.wait_for(asyncio.gather(*tasks), 30)

    try:
        asyncio.run(go())
    finally:
        streamer.close()
        rest.close()
        for kept in (lmp._by_ticker, lmp._fields_by_ticker):
            kept.pop("SPY", None)
        with server._terrain_cache_lock:
            server._terrain_cache.pop("SPY", None)
        server._last_feed_stamp.clear()
    assert len(daemon.options["LEVELONE_OPTIONS"]) == capture.OPTION_LIMITS["LEVELONE_OPTIONS"]
    assert len(behind) > 100, "the reader was sampled throughout"
    assert max(behind) < bound, (
        f"the reader fell {max(behind):.2f} s behind Schwab; reading the chain takes {bound:.2f} s"
    )
