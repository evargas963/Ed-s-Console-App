"""While the tick-writer thread runs, the capture daemon has ONE SQLite writer connection.

2026-09-25: two writer connections in one process (control writes on the event loop, ticks on
the writer thread) raced for the lock; one lost race wedged the control connection for 43
minutes (tests/test_stream_control_txn_v1.py). Control writes now run on the writer thread's
own connection while it runs, taken ahead of queued ticks.
"""
from __future__ import annotations

import asyncio
import sqlite3
import threading
import time

import pytest

import stream_spine
from stream_spine import CaptureWriter, MessageBus, bar_msg


def _run_with_writer(tmp_path, body):
    """Start CaptureWriter.run on a real bus, run `body(writer, bus)` on the loop, stop."""
    w = CaptureWriter(tmp_path / "cap.db", batch_rows=50, batch_sec=0.05)

    async def main():
        bus = MessageBus()
        sub = bus.subscribe("", maxsize=100_000, name="writer")
        stop = asyncio.Event()
        task = asyncio.create_task(w.run(sub, stop=stop))
        for _ in range(100):
            if w._writer_accepting:
                break
            await asyncio.sleep(0.01)
        try:
            return await body(w, bus)
        finally:
            stop.set()
            await task

    try:
        return w, asyncio.run(main())
    finally:
        w.close()


def test_control_writes_run_on_the_writer_thread_and_land(tmp_path, monkeypatch):
    seen_threads: list[str] = []
    real_run = CaptureWriter._run_control_ops

    def spy(self, conn):
        seen_threads.append(threading.current_thread().name)
        return real_run(self, conn)
    monkeypatch.setattr(CaptureWriter, "_run_control_ops", spy)

    async def body(w, bus):
        # the control connection must not be used while the thread runs
        monkeypatch.setattr(w, "_control_txn", lambda: (_ for _ in ()).throw(
            AssertionError("control write took the second connection")))
        for i in range(300):                               # a steady tick stream
            bus.publish(f"bar1m.ZZ{i % 5}", bar_msg(symbol=f"ZZ{i % 5}", src="t"))
        opened, refused = w.open_coverage_epochs(["ZZ0", "ZZ1"], "LEVELONE_OPTIONS", reason="t")
        w.write_heartbeat(claimed_coverage={"LEVELONE_OPTIONS": list(opened.values())})
        w.close_coverage_epochs([opened["ZZ0"]], reason="t")
        for i in range(300):
            bus.publish(f"bar1m.ZZ{i % 5}", bar_msg(symbol=f"ZZ{i % 5}", src="t"))
        await asyncio.sleep(0.3)
        return opened, refused

    w, (opened, refused) = _run_with_writer(tmp_path, body)
    assert set(opened) == {"ZZ0", "ZZ1"} and not refused
    assert seen_threads and all(t == "stream-capture-writer" for t in seen_threads)
    con = sqlite3.connect(str(tmp_path / "cap.db"))
    try:
        epochs = dict(con.execute("SELECT symbol, ended_ts IS NULL FROM stream_coverage_epochs"))
        assert epochs == {"ZZ0": 0, "ZZ1": 1}
        assert con.execute("SELECT COUNT(*) FROM stream_bars_raw").fetchone()[0] == 600
        assert con.execute("SELECT claimed_coverage_json FROM stream_producer_heartbeat").fetchone()
    finally:
        con.close()


def test_a_failed_control_write_is_rolled_back_on_the_thread_and_reported(tmp_path):
    async def body(w, bus):
        opened, _ = w.open_coverage_epochs(["ZZ"], "LEVELONE_OPTIONS", reason="t")
        # a refused second open is a report, not a failure; a SQL error is a failure
        _, refused = w.open_coverage_epochs(["ZZ"], "LEVELONE_OPTIONS", reason="t")
        assert "ZZ" in refused
        with pytest.raises(sqlite3.OperationalError, match="no such table"):   # raised back
            w._control_write(lambda con: con.execute("INSERT INTO no_such_table VALUES (1)"))
        w.close_coverage_epochs(list(opened.values()), reason="t")   # the thread is not wedged
        return opened

    _run_with_writer(tmp_path, body)


def test_a_write_the_thread_never_starts_is_cancelled_not_run_later(tmp_path, monkeypatch):
    monkeypatch.setattr(stream_spine, "CONTROL_WRITE_WAIT_SEC", 0.2)
    ran = []

    async def body(w, bus):
        # hold the writer thread inside another control write so the next one cannot start
        release = threading.Event()
        blocker = threading.Thread(target=lambda: w._control_write(lambda con: release.wait(5)))
        blocker.start()
        time.sleep(0.1)
        with pytest.raises(sqlite3.OperationalError, match="cancelled, nothing written"):
            w._control_write(lambda con: ran.append("late"))
        release.set()
        blocker.join()
        await asyncio.sleep(0.2)
        return None

    _run_with_writer(tmp_path, body)
    assert ran == [], "a cancelled control write must never run afterwards"


def test_before_and_after_the_thread_control_writes_use_the_control_connection(tmp_path):
    w = CaptureWriter(tmp_path / "cap.db", batch_rows=1, batch_sec=10.0)
    try:
        assert w._writer_accepting is False
        assert w.reconcile_orphan_coverage_epochs() == 0       # startup path, no thread yet
        opened, _ = w.open_coverage_epochs(["ZZ"], "LEVELONE_OPTIONS", reason="t")
        assert opened
    finally:
        w.close()
