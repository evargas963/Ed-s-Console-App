"""db.py tier-1 snapshot write: sqlite busy/locked retry via sqlite_errorcode."""

from __future__ import annotations

import sqlite3

import pytest

from db import EdDB, _sqlite_busy_or_locked


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
