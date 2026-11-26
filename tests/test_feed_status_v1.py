"""Once a minute the daemon records the state of each feed.

Per feed: checked at X, socket open, when Schwab last sent anything, subscribed symbols, and when
the feed last carried data -- a quiet feed and a dead one read differently in the database
(operator question 2026-09-27).
"""

from __future__ import annotations

import asyncio
import sqlite3
from contextlib import closing

import server
import time_et
from app.market_data.schwab.streaming import capture
from feed import connection
from stream_spine import LOG, CaptureWriter, HealthRegistry, MessageBus
from tests.schwab_rest_standin import LocalSchwab
from tests.schwab_stream_standin import LocalStreamer
from tests.shared_helpers import fixture_json, until

#: Schwab's NEWS_HEADLINE frame for $SPX at the regular open of 2026-11-20, its items as stored
_NEWS = fixture_json("real_schwab_news_one_frame_spx_2026_11_20.json")


def test_every_feed_gets_one_row_with_the_same_checked_at(tmp_path):
    """One round of the feed status, while the daemon's connection reads Schwab's frames.

    Schwab's streamer (tests/schwab_stream_standin.py, through the real schwab-py client) sends
    Schwab's recorded NEWS_HEADLINE frame
    (tests/fixtures/real_schwab_news_one_frame_spx_2026_11_20.json) once the news SUBS is taken,
    and no data on any other service. Every feed gets one row at the same time, each with the time
    the stream last read a frame; the news feed's last data is when its items reached the bus,
    every other feed's None: no data is None, not a time.
    """
    entry = {
        "service": "NEWS_HEADLINE",
        "timestamp": _NEWS["messages"][0]["schwab_ts"],
        "command": "SUBS",
        "content": [m["content"] for m in _NEWS["messages"]],
    }
    streamer = LocalStreamer({}, {"NEWS_HEADLINE": entry})
    rest = LocalSchwab(streamer.url)
    db = tmp_path / "stream_capture.db"
    writer = CaptureWriter(db)
    bus, health = MessageBus(), HealthRegistry()
    daemon = capture.Daemon(bus, health, ["SPY"])
    log = bus.subscribe("", policy=LOG)  # as the database writer reads the bus

    async def go():
        stop = asyncio.Event()
        run = asyncio.create_task(daemon.connection.run_connection(rest.client(tmp_path), stop))
        await until(lambda: run.done() or health.last("NEWS_HEADLINE"), state=lambda: run)
        one = asyncio.Event()
        one.set()  # one round, then stop
        await capture.record_feed_status(daemon, one)
        stop.set()
        await asyncio.wait_for(run, 10)

    try:
        asyncio.run(go())
    finally:
        streamer.close()
        rest.close()

    while not log.queue.empty():
        writer.insert(*log.queue.get_nowait())
    with closing(sqlite3.connect(db)) as c, c:
        rows = c.execute(
            "SELECT ts, service, schwab_last_frame_ts, last_data_ts "
            "FROM stream_feed_status ORDER BY service"
        ).fetchall()
    news_at = health.last("NEWS_HEADLINE")
    assert news_at is not None
    assert {r[1] for r in rows} == set(connection.SERVICES)
    assert len({r[0] for r in rows}) == 1, "every feed is checked at the same X"
    assert len({r[2] for r in rows}) == 1 and rows[0][2] >= news_at, "the stream's last frame"
    news = [r for r in rows if r[1] == "NEWS_HEADLINE"][0]
    assert news[3] == news_at
    assert all(r[3] is None for r in rows if r[1] != "NEWS_HEADLINE"), "no data is None, not a time"


def test_the_console_reports_the_recorders_own_line(tmp_path):
    """The console's status line takes the Recorder's word from the heartbeat, not the database.

    A writer with one row committed: the line is its own (state, rows, what it holds); with no
    heartbeat, or a daemon with no writer, the line says nothing was reported.
    """
    writer = CaptureWriter(tmp_path / "ed.db")
    writer.insert(
        "feedstatus.NEWS_HEADLINE",
        {
            "ts": time_et.now(),
            "service": "NEWS_HEADLINE",
            "socket_open": True,
            "schwab_last_frame_ts": None,
            "held": 1,
            "last_data_ts": None,
        },
    )
    status = writer.status()
    assert server._record_state({"writer": status}) == f"record: {status['line']}"
    assert "1 rows" in status["line"] and "held in memory: 0 messages" in status["line"]
    assert server._record_state(None) == server._record_state({"writer": None})
    assert server._record_state(None) == "record: NOT REPORTED"


class _StreamFailingOnce:
    """A stream whose first read of its last frame's time fails (an induced condition)."""

    def __init__(self):
        self.reads = 0

    @property
    def last_frame_ts(self):
        self.reads += 1
        if self.reads == 1:
            raise RuntimeError("boom")
        return 1000.0


def test_a_failed_round_is_logged_and_the_next_round_runs(caplog):
    bus, health = MessageBus(), HealthRegistry()
    daemon = capture.Daemon(bus, health)
    daemon.connection.stream = _StreamFailingOnce()

    async def go():
        stop = asyncio.Event()
        task = asyncio.create_task(capture.record_feed_status(daemon, stop, every=0.01))
        # the round after the failed one has read the stream; a round runs with no pause in it,
        # so it has ended when this looks
        deadline = time_et.elapsed() + 10
        while daemon.connection.stream.reads < 2 and time_et.elapsed() < deadline:
            await asyncio.sleep(0.01)
        stop.set()
        await task

    asyncio.run(go())
    written = {topic for topic, _record in bus.current.values() if topic.startswith("feedstatus.")}
    assert "feed status round failed: RuntimeError: boom" in caplog.text
    assert written == {f"feedstatus.{svc}" for svc in connection.SERVICES}, (
        "the round after the failure still wrote"
    )
