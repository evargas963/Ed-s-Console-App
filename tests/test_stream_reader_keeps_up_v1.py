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
import sys
import threading
from pathlib import Path

from schwab.streaming import StreamClient

import live_market_plane as lmp
import server
import time_et
from app.market_data.schwab.streaming import capture
from app.options.order_flow import streaming as ofs
from calibration.complete_chain_capture import chain_messages
from option_contract import read_chain, read_contract
from stream_spine import HealthRegistry, MessageBus, quote_msg
from tests.real_chains import MRVL
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


def test_a_delivered_chain_is_read_once_for_the_levels_and_the_option_rule():
    """MRVL's whole chain as the sweep delivers it: each contract is read once, for both readers.

    The console prices it into the levels and the daemon's option rule orders it; both take the
    one read the sweep makes as it puts the chain on the bus (chain_messages). Each call of
    option_contract.read_contract is counted with Python's own monitoring (sys.monitoring), the
    code itself untouched.
    """
    tk, now = MRVL.ticker, MRVL.now.timestamp()
    bus = MessageBus()
    daemon = capture.Daemon(bus, HealthRegistry(), [tk], clock=lambda: now)
    mon = sys.monitoring
    tool = next(i for i in range(6) if mon.get_tool(i) is None)
    reads: list[None] = []
    mon.use_tool_id(tool, "read count")
    mon.register_callback(tool, mon.events.PY_START, lambda _code, _offset: reads.append(None))
    mon.set_local_events(tool, read_contract.__code__, mon.events.PY_START)

    async def go():
        stop = asyncio.Event()
        ofs.bind_daemon(daemon)
        assert ofs.start_order_flow_stream(**server.FEED_CALLBACKS)
        follower = asyncio.create_task(daemon.follow_market(stop))
        try:
            bus.publish(
                f"quote.{tk}",
                quote_msg(
                    symbol=tk,
                    last=MRVL.spot,
                    src="schwab_l1",
                    native={"key": tk, "LAST_PRICE": MRVL.spot},
                ),
            )
            delivered = await asyncio.to_thread(
                chain_messages, tk, [dict(c) for c in MRVL.chain], now, MRVL.spot, now
            )
            for topic, msg in delivered:
                bus.publish(topic, msg)
            await _until(
                lambda: tk in daemon._ranked and server.published_levels(tk) is not None, 120
            )
            return [ct for _topic, msg in delivered for ct in msg["contracts"]]
        finally:
            stop.set()
            ofs.stop_order_flow_stream()
            ofs.bind_daemon(None)
            await asyncio.wait_for(follower, 10)

    try:
        read = asyncio.run(go())
    finally:
        mon.set_local_events(tool, read_contract.__code__, 0)
        mon.free_tool_id(tool)
        for kept in (lmp._by_ticker, lmp._fields_by_ticker):
            kept.pop(tk, None)
        levels = server.published_levels(tk)
        with server._terrain_cache_lock:
            server._terrain_cache.pop(tk, None)
        server._last_feed_stamp.clear()
    assert len(reads) == len(MRVL.chain) == len(read), "each contract read once"
    assert all(a is b for a, b in zip(levels.chain, read, strict=True)), "the levels: that read"
    assert daemon._ranked[tk] == capture.by_gamma(read, MRVL.spot, now), "the rule: that read"


class _TimerCountingLoop(asyncio.SelectorEventLoop):
    """asyncio's own event loop, counting each timer scheduled on it (call_at); nothing else."""

    timers = 0

    def call_at(self, when, callback, *args, context=None):
        self.timers += 1
        return super().call_at(when, callback, *args, context=context)


def test_the_reader_takes_each_frame_with_no_timer_of_its_own(tmp_path):
    """Schwab's heartbeat every 10 ms for 2 s: about 200 frames, each read as it comes.

    The reader raced each frame against the wake for a request to send, with a timeout: two
    tasks and a timer on the event loop for every frame. It now awaits each frame alone, a
    task of its own sends what is asked, and the connection is checked once a second (READ_SEC):
    over 2 s the loop schedules at most that check's timers and the websockets library's own
    (its keepalive), never one per frame.
    """
    streamer = LocalStreamer({}, data={}, beat=0.01)
    rest = LocalSchwab(streamer.url)
    client = rest.client(tmp_path)
    daemon = capture.Daemon(MessageBus(), HealthRegistry(), [])
    loop = _TimerCountingLoop()

    async def go() -> tuple[int, float]:
        stop = asyncio.Event()
        run = asyncio.create_task(daemon.run_connection(client, stop))
        await _until(lambda: daemon.stream is not None and daemon.stream.schwab_ts is not None, 30)
        before, started = loop.timers, time_et.now()
        await time_et.set_within(stop, 2.0)  # this wait's own timer: one
        scheduled = loop.timers - before - 1
        behind = time_et.now() - daemon.stream.schwab_ts
        assert time_et.now() - started >= 2.0
        stop.set()
        await asyncio.wait_for(run, 30)
        return scheduled, behind

    try:
        scheduled, behind = loop.run_until_complete(go())
    finally:
        loop.close()
        streamer.close()
        rest.close()
    assert behind < 0.5, f"the frames were not read as they came: {behind:.2f} s behind"
    assert scheduled <= 2 / capture.READ_SEC + 2, f"{scheduled} timers in 2 s of ~200 frames"


async def _until(cond, seconds: float, state=lambda: None) -> None:
    deadline = time_et.elapsed() + seconds
    while not cond():
        assert time_et.elapsed() < deadline, f"not reached in time: {state()}"
        await asyncio.sleep(0.05)


def test_the_reader_keeps_up_while_spys_whole_chain_is_read_and_priced(tmp_path):
    """SPY's 12,904 contracts reach the option rule and the console: the reader keeps up.

    The sweep reads the chain once as it delivers it, the daemon's option rule orders it and the
    console prices it and stamps its heatmap. Production (2026-11-09) ran those on the event loop
    that reads Schwab's stream, and the reader fell up to 17.97 s behind Schwab. Here no stretch
    of that work holds the reader as long as reading the chain takes (_read_sec).
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
            # made on a thread of its own, as the chain sweep makes them
            delivered = await asyncio.to_thread(
                chain_messages,
                "SPY",
                SPY["chain"],
                SPY["capture_ts_utc"],
                SPY["spot"],
                SPY["capture_ts_utc"],
            )
            for topic, msg in delivered:
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
