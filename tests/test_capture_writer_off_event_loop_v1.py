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
import threading

import time_et
from stream_spine import LOG, CaptureWriter, MessageBus, quote_msg


def _quote(i: int) -> dict:
    return quote_msg(symbol="SPY", bid=1.0, ask=1.1, last=1.05, ts_recv=1000.0 + i, src="schwab_l1")


def _hold_the_database(path, release: threading.Event) -> threading.Thread:
    """Another connection holds the database's write lock until `release` is set.

    It holds it as a reader of the file, a backup or the daily keep can: every write the writer
    makes meanwhile waits on it.
    """
    held = threading.Event()

    def hold():
        other = sqlite3.connect(str(path))
        try:
            other.execute("BEGIN EXCLUSIVE")
            held.set()
            release.wait(10)
            other.commit()
        finally:
            other.close()

    t = threading.Thread(target=hold, daemon=True)
    t.start()
    held.wait(10)
    return t


def test_a_slow_commit_does_not_stall_the_event_loop(tmp_path):
    writer = CaptureWriter(tmp_path / "cap.db", batch_rows=1, batch_sec=0.05)
    bus = MessageBus()
    sub = bus.subscribe("", policy=LOG)
    release = threading.Event()
    holder = _hold_the_database(tmp_path / "cap.db", release)

    async def go():
        stop = asyncio.Event()
        task = asyncio.create_task(writer.run(sub, stop=stop))
        gaps = []
        last = time_et.elapsed()
        for i in range(40):  # the lock is held through every tick: each commit waits on it
            bus.publish("quote.SPY", _quote(i))
            await asyncio.sleep(0.01)  # the loop's own tick, the gap measured
            now = time_et.elapsed()
            gaps.append(now - last)
            last = now
        release.set()
        stop.set()
        await task
        return max(gaps)

    worst = asyncio.run(go())
    holder.join(10)
    assert worst < 0.25, f"the event loop stalled {worst:.2f}s behind a held commit"
    n = (
        sqlite3.connect(str(tmp_path / "cap.db"))
        .execute("SELECT count(*) FROM stream_quotes_raw")
        .fetchone()[0]
    )
    assert n == 40, "every delivered message must still be written before run() returns"


def test_writes_happen_on_the_writer_thread_not_the_loop(tmp_path):
    seen: set = set()
    insert = CaptureWriter.insert.__code__

    def profile(frame, event, _arg):  # the interpreter's profiler: sees calls, changes nothing
        if event == "call" and frame.f_code is insert:
            seen.add(threading.current_thread().name)

    writer = CaptureWriter(tmp_path / "cap.db", batch_rows=5, batch_sec=0.05)
    bus = MessageBus()
    sub = bus.subscribe("", policy=LOG)

    async def go():
        stop = asyncio.Event()
        task = asyncio.create_task(writer.run(sub, stop=stop))
        for i in range(10):
            bus.publish("quote.SPY", _quote(i))
        deadline = time_et.elapsed() + 10  # written while the writer runs, before any stop
        while writer.status()["rows_written"] < 10 and time_et.elapsed() < deadline:
            await asyncio.sleep(0.01)
        stop.set()
        await task

    threading.setprofile_all_threads(profile)
    try:
        asyncio.run(go())
    finally:
        threading.setprofile_all_threads(None)
    assert seen == {"stream-capture-writer"}
