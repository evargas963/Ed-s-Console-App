"""The capture writer never blocks the event loop that reads the Schwab websocket.

MEASURED 2026-09-23: CaptureWriter.run executed every SQLite insert and commit on the same
asyncio loop as the websocket reads, so a slow commit stalled the socket (writer queue
6,565, 9,784 drops). The writer now runs on its own thread with its own connection. These
tests prove it at the real seam: a commit made artificially slow must not stop the loop
from ticking, and every delivered message is still written before run() returns.
"""
from __future__ import annotations

import asyncio
import sqlite3
import time

import stream_spine
from stream_spine import CaptureWriter, MessageBus, COUNT_DROPS, quote_msg


class _SlowCommitConn:
    """A real sqlite3 connection whose commit takes `delay` seconds."""

    def __init__(self, real: sqlite3.Connection, delay: float):
        self._real = real
        self._delay = delay

    def execute(self, *a, **k):
        return self._real.execute(*a, **k)

    def commit(self):
        time.sleep(self._delay)
        self._real.commit()

    def close(self):
        self._real.close()


def _quote(i: int) -> dict:
    return quote_msg(symbol="SPY", bid=1.0, ask=1.1, last=1.05, ts_recv=1000.0 + i, src="schwab_l1")


def test_a_slow_commit_does_not_stall_the_event_loop(tmp_path, monkeypatch):
    real_connect = sqlite3.connect
    main_thread = __import__("threading").get_ident()

    def _connect(path, *a, **k):
        conn = real_connect(path, *a, **k)
        # only the writer THREAD's connection is slowed; the control connection is normal
        if __import__("threading").get_ident() != main_thread:
            return _SlowCommitConn(conn, 0.6)
        return conn
    monkeypatch.setattr(stream_spine.sqlite3, "connect", _connect)

    writer = CaptureWriter(tmp_path / "cap.db", batch_rows=1, batch_sec=0.05)
    bus = MessageBus()
    sub = bus.subscribe("", policy=COUNT_DROPS, maxsize=8192)

    async def go():
        stop = asyncio.Event()
        task = asyncio.create_task(writer.run(sub, stop=stop))
        gaps = []
        last = time.monotonic()
        for i in range(40):
            bus.publish("quote.SPY", _quote(i))
            await asyncio.sleep(0.01)
            now = time.monotonic()
            gaps.append(now - last)
            last = now
        stop.set()
        await task
        return max(gaps)

    worst = asyncio.run(go())
    writer.close()
    assert worst < 0.25, f"the event loop stalled {worst:.2f}s behind a 0.6s commit"
    n = real_connect(str(tmp_path / "cap.db")).execute(
        "SELECT count(*) FROM stream_quotes_raw").fetchone()[0]
    assert n == 40, "every delivered message must still be written before run() returns"


def test_writes_happen_on_the_writer_thread_not_the_loop(tmp_path, monkeypatch):
    import threading
    seen: set = set()
    orig = CaptureWriter.insert

    def _spy(self, topic, msg, *, conn=None):
        seen.add(threading.current_thread().name)
        return orig(self, topic, msg, conn=conn)
    monkeypatch.setattr(CaptureWriter, "insert", _spy)
    writer = CaptureWriter(tmp_path / "cap.db", batch_rows=5, batch_sec=0.05)
    bus = MessageBus()
    sub = bus.subscribe("", policy=COUNT_DROPS, maxsize=8192)

    async def go():
        stop = asyncio.Event()
        task = asyncio.create_task(writer.run(sub, stop=stop))
        for i in range(10):
            bus.publish("quote.SPY", _quote(i))
        await asyncio.sleep(0.2)
        stop.set()
        await task
    asyncio.run(go())
    writer.close()
    assert seen == {"stream-capture-writer"}
