"""calibration/schema migrations and DDL constant alignment."""

from __future__ import annotations

import logging
import sqlite3

import pytest

from calibration.schema import (
    CALIBRATION_TABLE_SQL,
    _migrate_calibration_unique_ticker_decision_ts,
    ensure_calibration_schema,
)
from calibration.trust import CALIBRATION_TRUST_LEGACY
from timeframe_config import CANONICAL_TIMEFRAME


class _SqliteConnExecuteHook:
    """Delegate sqlite3.Connection; override execute (read-only on Connection in Py 3.13)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def execute(self, sql, params=(), /):
        return self._conn.execute(sql, params)

    def __getattr__(self, name: str):
        return getattr(self._conn, name)


def _fresh_conn_without_unique_index() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(CALIBRATION_TABLE_SQL)
    conn.commit()
    return conn


def _insert_duplicate_pair(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO calibration_decision_log (decision_ts_utc, ticker) VALUES (?, ?)",
        (1_900_000_000.0, "SPY"),
    )
    conn.execute(
        "INSERT INTO calibration_decision_log (decision_ts_utc, ticker) VALUES (?, ?)",
        (1_900_000_000.0, "SPY"),
    )
    conn.commit()


def _wrap(conn: sqlite3.Connection) -> _SqliteConnExecuteHook:
    return _SqliteConnExecuteHook(conn)


def test_calibration_table_sql_contains_canonical_constants():
    assert f"DEFAULT '{CANONICAL_TIMEFRAME}'" in CALIBRATION_TABLE_SQL
    assert f"DEFAULT '{CALIBRATION_TRUST_LEGACY}'" in CALIBRATION_TABLE_SQL


def test_unique_migration_dedupes_and_logs_deleted_count(caplog):
    caplog.set_level(logging.WARNING)
    conn = _fresh_conn_without_unique_index()
    _insert_duplicate_pair(conn)

    _migrate_calibration_unique_ticker_decision_ts(conn)

    n = conn.execute("SELECT COUNT(*) FROM calibration_decision_log").fetchone()[0]
    assert n == 1
    idx = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name = 'uq_calib_ticker_decision_ts_utc'"
    ).fetchone()
    assert idx is not None
    assert any("removed 1 duplicate" in r.message for r in caplog.records)


def test_unique_migration_rolls_back_when_create_index_fails():
    conn = _fresh_conn_without_unique_index()
    _insert_duplicate_pair(conn)
    wrapped = _wrap(conn)
    real_execute = wrapped._conn.execute

    def execute(sql, params=(), /):
        s = str(sql)
        if "CREATE UNIQUE INDEX" in s and "uq_calib_ticker_decision_ts_utc" in s:
            raise sqlite3.OperationalError("simulated create index failure")
        return real_execute(sql, params)

    wrapped.execute = execute  # type: ignore[method-assign]

    with pytest.raises(sqlite3.OperationalError, match="simulated create index failure"):
        _migrate_calibration_unique_ticker_decision_ts(wrapped)

    n = conn.execute("SELECT COUNT(*) FROM calibration_decision_log").fetchone()[0]
    assert n == 2
    idx = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name = 'uq_calib_ticker_decision_ts_utc'"
    ).fetchone()
    assert idx is None


def test_drop_legacy_index_failure_logs_warning_and_migration_continues(caplog):
    caplog.set_level(logging.WARNING)
    conn = _fresh_conn_without_unique_index()
    _insert_duplicate_pair(conn)
    wrapped = _wrap(conn)
    real_execute = wrapped._conn.execute

    def execute(sql, params=(), /):
        if "DROP INDEX IF EXISTS idx_calib_ticker_ts" in str(sql):
            raise sqlite3.OperationalError("simulated drop failure")
        return real_execute(sql, params)

    wrapped.execute = execute  # type: ignore[method-assign]
    _migrate_calibration_unique_ticker_decision_ts(wrapped)

    assert any("DROP INDEX idx_calib_ticker_ts failed" in r.message for r in caplog.records)
    n = conn.execute("SELECT COUNT(*) FROM calibration_decision_log").fetchone()[0]
    assert n == 1


def test_ensure_calibration_schema_idempotent(tmp_path):
    db_path = tmp_path / "schema_idempotent.db"
    conn = sqlite3.connect(str(db_path))
    ensure_calibration_schema(conn)
    ensure_calibration_schema(conn)
    idx = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name = 'uq_calib_ticker_decision_ts_utc'"
    ).fetchone()
    conn.close()
    assert idx is not None
