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


def test_sqlite_contention_lock_wait_recorded(tier1_db):
    import threading

    from db import _TIER1_SNAPSHOT_WRITE_LOCK, sqlite_contention_metrics_snapshot

    hold = threading.Event()
    release = threading.Event()

    def blocker():
        _TIER1_SNAPSHOT_WRITE_LOCK.acquire()
        hold.set()
        release.wait(timeout=2.0)
        _TIER1_SNAPSHOT_WRITE_LOCK.release()

    t = threading.Thread(target=blocker, name="tier1-blocker")
    t.start()
    assert hold.wait(timeout=2.0)
    before = int(sqlite_contention_metrics_snapshot().get("sqlite_lock_wait_count", 0))
    out = tier1_db._tier1_snapshot_write("insert_snapshot", "SPY", lambda: "ok")
    release.set()
    t.join(timeout=2.0)
    assert out == "ok"
    snap = sqlite_contention_metrics_snapshot()
    assert snap["sqlite_lock_wait_count"] > before
    assert snap["sqlite_lock_wait_max_ms"] > 0
    assert "insert_snapshot" in snap.get("operations_affected", {})


def test_sqlite_contention_database_locked_counted(tier1_db, monkeypatch):
    from db import sqlite_contention_metrics_snapshot

    def fn():
        err = sqlite3.OperationalError("database is locked")
        err.sqlite_errorcode = sqlite3.SQLITE_LOCKED
        raise err

    monkeypatch.setattr("db.SQLITE_BUSY_MAX_RETRIES", 1)
    monkeypatch.setattr("db._wall_time.sleep", lambda _s: None)
    before = int(sqlite_contention_metrics_snapshot().get("sqlite_database_locked_count", 0))
    with pytest.raises(sqlite3.OperationalError):
        tier1_db._tier1_snapshot_write("insert_snapshot", "QQQ", fn)
    after = int(sqlite_contention_metrics_snapshot().get("sqlite_database_locked_count", 0))
    assert after >= before + 1


def test_lock_wait_classification_not_harmless_by_default():
    from verification.db_sqlite_contention_impact_audit import (
        classify_contention_findings,
        lock_wait_is_harmless_classification,
        SqliteContentionMetrics,
    )

    metrics = SqliteContentionMetrics(sqlite_lock_wait_count=3, sqlite_lock_wait_max_ms=748.6)
    tags = classify_contention_findings(
        metrics,
        ui_surfaces={"operator_db_degraded_surface": False},
        writer_map={"tier_c_reads_db": True, "tier1_serializes_hot_writes": True},
        correlation={"offline_correlation_gap": True},
    )
    assert "LOCK_WAIT_ONLY_BUT_SUCCESSFUL" in tags
    assert "UI_DEGRADED_STATE_MISSING" in tags
    assert "TRANSPORT_FRESHNESS_RISK" in tags
    assert lock_wait_is_harmless_classification(tags) is False
    assert "NO_IMPACT_PROVEN" not in tags


def test_contention_metrics_preserve_operation_ticker_thread():
    from verification.db_sqlite_contention_impact_audit import parse_sqlite_contention_log_text

    sample = (
        "sqlite_tier1_lock_wait op=insert_snapshot ticker=SPY db_path=/data/ed_console.db "
        "wait_ms=748.6 attempt=1/8 thread=ed-base-money-path-logger\n"
        "sqlite_tier1_busy_retry op=upsert_1m_bars ticker=QQQ db_path=/data/ed_console.db "
        "attempt=2/8 sleep_s=0.040 thread=MainThread err=database is locked\n"
    )
    m = parse_sqlite_contention_log_text(sample)
    assert m.sqlite_lock_wait_count == 1
    assert m.operations_affected.get("insert_snapshot") == 1
    assert m.tickers_affected.get("SPY") == 1
    assert m.threads_affected.get("ed-base-money-path-logger") == 1
    assert m.sqlite_busy_retry_count == 1


def test_report_flags_ui_degraded_state_missing():
    from verification.db_sqlite_contention_impact_audit import (
        build_contention_impact_report,
        scan_ui_db_degraded_surfaces,
    )

    ui = scan_ui_db_degraded_surfaces()
    assert ui.get("lane_stale_without_db_cause") is True
    report = build_contention_impact_report(
        audit_date="2026-06-18",
        log_text="",
        log_paths=[],
        db_path=None,
    )
    assert "UI_DEGRADED_STATE_MISSING" in report.get("classifications", [])
