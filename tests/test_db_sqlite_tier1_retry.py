"""db.py tier-1 bar write: sqlite busy/locked retry via sqlite_errorcode."""

from __future__ import annotations

import sqlite3

from pathlib import Path

import pytest

from db import EdDB, _sqlite_busy_or_locked

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def tier1_db(tmp_path):
    return EdDB(tmp_path / "tier1_retry.db")


def test_sqlite_busy_or_locked_accepts_errorcode_without_message_keywords():
    e = sqlite3.OperationalError("opaque")
    e.sqlite_errorcode = sqlite3.SQLITE_BUSY
    assert _sqlite_busy_or_locked(e) is True
    e.sqlite_errorcode = sqlite3.SQLITE_LOCKED
    assert _sqlite_busy_or_locked(e) is True
    e.sqlite_errorcode = sqlite3.SQLITE_CONSTRAINT
    assert _sqlite_busy_or_locked(e) is False


def test_tier1_retries_on_busy_errorcode_without_busy_in_message(tier1_db, monkeypatch):
    attempts: list[int] = []

    def fn():
        attempts.append(1)
        if len(attempts) == 1:
            err = sqlite3.OperationalError("opaque")
            err.sqlite_errorcode = sqlite3.SQLITE_BUSY
            raise err
        return "ok"

    sleeps: list[float] = []
    monkeypatch.setattr("db._wall_time.sleep", lambda s: sleeps.append(s))

    out = tier1_db._tier1_snapshot_write("test_op", "SPY", fn)

    assert out == "ok"
    assert len(attempts) == 2
    assert len(sleeps) == 1


def test_tier1_retries_on_locked_errorcode(tier1_db, monkeypatch):
    attempts: list[int] = []

    def fn():
        attempts.append(1)
        if len(attempts) == 1:
            err = sqlite3.OperationalError("opaque")
            err.sqlite_errorcode = sqlite3.SQLITE_LOCKED
            raise err
        return "ok"

    monkeypatch.setattr("db._wall_time.sleep", lambda _s: None)

    out = tier1_db._tier1_snapshot_write("test_op", "SPY", fn)

    assert out == "ok"
    assert len(attempts) == 2


def test_tier1_does_not_retry_non_busy_sqlite_errorcode(tier1_db, monkeypatch):
    attempts: list[int] = []

    def fn():
        attempts.append(1)
        err = sqlite3.OperationalError("opaque")
        err.sqlite_errorcode = sqlite3.SQLITE_CONSTRAINT
        raise err

    monkeypatch.setattr("db._wall_time.sleep", lambda _s: None)

    with pytest.raises(sqlite3.OperationalError):
        tier1_db._tier1_snapshot_write("test_op", "SPY", fn)

    assert len(attempts) == 1




def _run_timed_lock_wait(tier1_db, hold_sec: float):
    """Hold the tier1 write lock for hold_sec, run one write, return log capture window."""
    import threading

    from db import _TIER1_SNAPSHOT_WRITE_LOCK

    hold = threading.Event()

    def blocker():
        _TIER1_SNAPSHOT_WRITE_LOCK.acquire()
        hold.set()
        import time as _t
        _t.sleep(hold_sec)
        _TIER1_SNAPSHOT_WRITE_LOCK.release()

    t = threading.Thread(target=blocker, name="tier1-cal-blocker")
    t.start()
    assert hold.wait(timeout=2.0)
    out = tier1_db._tier1_snapshot_write("upsert_1m_bars", "SPY", lambda: "ok")
    t.join(timeout=3.0)
    assert out == "ok"


def test_rc236_absorbed_lock_wait_logs_info_not_warning(tier1_db, caplog, monkeypatch):
    """RC-236: a wait over WARN_MS but under the distress bar on attempt 1 is routine WAL
    contention — INFO, so the quiet gate stops failing on absorbed mid-RTH lock traffic."""
    monkeypatch.setattr("db.SQLITE_LOCK_WAIT_WARN_MS", 50.0)
    monkeypatch.setattr("db.SQLITE_LOCK_WAIT_DISTRESS_MS", 10_000.0)
    with caplog.at_level("INFO", logger="db"):
        _run_timed_lock_wait(tier1_db, 0.15)
    hits = [r for r in caplog.records if "sqlite_tier1_lock_wait" in r.getMessage()]
    assert hits, "the wait must still be logged (visibility retained)"
    assert all(r.levelname == "INFO" for r in hits), [r.levelname for r in hits]


def test_rc236_distress_lock_wait_still_warns(tier1_db, caplog, monkeypatch):
    """Escalation retained: a wait past the distress bar keeps its WARNING."""
    monkeypatch.setattr("db.SQLITE_LOCK_WAIT_WARN_MS", 50.0)
    monkeypatch.setattr("db.SQLITE_LOCK_WAIT_DISTRESS_MS", 60.0)
    with caplog.at_level("INFO", logger="db"):
        _run_timed_lock_wait(tier1_db, 0.15)
    hits = [r for r in caplog.records if "sqlite_tier1_lock_wait" in r.getMessage()]
    assert hits and any(r.levelname == "WARNING" for r in hits), \
        [r.levelname for r in hits]
