"""The capture daemon's control connection can never be wedged by one failed write.

MEASURED 2026-09-25 12:50-13:40 CT on the production stream_capture.db: a control write lost
the lock race to the tick-writer thread and raised with its implicit transaction still open.
The next control call's SELECT read inside that leftover transaction (a pinned snapshot), the
tick writer committed, and from then on every control write failed INSTANTLY with "database is
locked" -- 3,302 failures in 43 minutes, every option coverage epoch refused, the WAL
checkpoint stuck at frame 624 while the log grew past 176,000 frames.
"""
from __future__ import annotations

import sqlite3
import time

from stream_spine import CaptureWriter, CoverageWriteError


def _tick_writer(db):
    """The daemon's tick-writer thread: its own connection, committing batches."""
    con = sqlite3.connect(str(db), timeout=30.0)
    return con


def _tick_batch(con, n=5):
    for i in range(n):
        con.execute("INSERT INTO stream_bars_raw(ts_recv,symbol,src) VALUES(?,?,?)",
                    (time.time(), "ZZ", "test"))
    con.commit()


def test_a_write_that_loses_the_lock_race_does_not_wedge_later_writes(tmp_path):
    db = tmp_path / "cap.db"
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    ticks = _tick_writer(db)
    try:
        w._conn.execute("PRAGMA busy_timeout=200")          # keep the lost race short
        ticks.execute("INSERT INTO stream_bars_raw(ts_recv,symbol,src) VALUES(1,'ZZ','t')")
        started = time.monotonic()
        try:
            w.write_heartbeat(claimed_coverage={})
            raise AssertionError("the heartbeat should have lost the lock race")
        except CoverageWriteError as e:
            assert "locked" in str(e)
        assert time.monotonic() - started >= 0.15, "a busy database must be waited for"
        assert not w._conn.in_transaction, "a failed control write must not leave a transaction open"
        ticks.commit()

        # the production sequence after the loss: the tick writer keeps committing between
        # control calls, and the next control call reads (the open-epoch SELECT) then writes
        for i in range(4):
            _tick_batch(ticks)
            opened, refused = w.open_coverage_epochs([f"ZZ{i}"], "LEVELONE_OPTIONS", reason="t")
            assert opened and not refused
            _tick_batch(ticks)
            w.write_heartbeat(claimed_coverage={"LEVELONE_OPTIONS": list(opened.values())})

        # and the checkpoint is not pinned by a leftover snapshot
        busy, log_frames, done = ticks.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
        assert busy == 0 and done == log_frames, (busy, log_frames, done)
    finally:
        ticks.close()
        w.close()


def test_a_transaction_left_open_by_anything_is_cleared_before_the_next_control_write(tmp_path):
    db = tmp_path / "cap.db"
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    ticks = _tick_writer(db)
    try:
        # a leftover read snapshot on the control connection (the wedge's precondition)
        w._conn.execute("BEGIN")
        w._conn.execute("SELECT COUNT(*) FROM stream_coverage_epochs").fetchone()
        _tick_batch(ticks)                                   # the snapshot is now stale
        opened, _ = w.open_coverage_epochs(["ZZ"], "LEVELONE_OPTIONS", reason="t")
        assert opened, "a stale leftover transaction must be discarded, not written through"
        w.close_coverage_epochs(list(opened.values()), reason="t")
        assert w.reconcile_orphan_coverage_epochs() == 0
    finally:
        ticks.close()
        w.close()
