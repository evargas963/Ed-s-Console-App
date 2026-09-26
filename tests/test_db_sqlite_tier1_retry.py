"""db.py tier-1 snapshot write: sqlite busy/locked retry via sqlite_errorcode."""

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
    out = tier1_db._tier1_snapshot_write("insert_snapshot", "SPY", lambda: "ok")
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




















def _collect_window_session_open_ts() -> float:
    """RC-183: price_bars_1m persists ET bar-END minutes (555, min(975, close+15)] on trading
    days only — the ONE write seam. Fixtures must therefore use REAL in-window minutes; the
    old synthetic 1970 stamps (t0=1_020_000) were silently dropped by that gate, which is the
    gate working, not a bug. Returns the epoch-second bar_start for 09:30 ET on a known
    trading Monday, leaving ~6.5h of in-window minutes for multi-bar fixtures."""
    import datetime as _dt
    from zoneinfo import ZoneInfo

    et = _dt.datetime(2026, 6, 15, 9, 30, tzinfo=ZoneInfo("America/New_York"))
    return et.timestamp()


def test_live_bar_upsert_is_incremental_bulk_path_full(tmp_path):
    """Console usability slice 2026-07-03: the live path must not rewrite the whole
    multi-day bars list every cycle (17.8s first-cycle exec observed live) — only bars
    at/after (per-ticker MAX bar_start − overlap) are written. Bulk backfills
    (refresh_governed_outcomes=False) keep the full write for hole repairs."""
    from db import EdDB, LIVE_BARS_REUPSERT_OVERLAP_SEC

    db = EdDB(tmp_path / "bars.db")
    t0 = _collect_window_session_open_ts()
    bars = [
        {"datetime": t0 + i * 60.0, "open": 100.0, "high": 101.0,
         "low": 99.0, "close": 100.0 + 0.1 * i, "volume": 1.0}
        for i in range(100)
    ]
    # First live write: ticker has no rows -> full backfill lands.
    assert db.upsert_1m_bars("SPY", bars) == 100

    # Second live write, same list + one new bar: only the overlap tail + the new bar.
    bars2 = bars + [{"datetime": t0 + 100 * 60.0, "open": 100.0, "high": 101.0,
                     "low": 99.0, "close": 110.0, "volume": 1.0}]
    n2 = db.upsert_1m_bars("SPY", bars2)
    expected_tail = int(LIVE_BARS_REUPSERT_OVERLAP_SEC // 60) + 1 + 1  # overlap bars + db-max bar + new
    assert n2 <= expected_tail, f"live re-upsert must be tail-only, wrote {n2}"
    with db._connect() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM price_bars_1m WHERE ticker='SPY'"
        ).fetchone()[0]
    assert total == 101, "the new bar must land; persisted history stays intact"

    # Bulk path: full rewrite preserved (hole repair semantics).
    n3 = db.upsert_1m_bars("SPY", bars2, refresh_governed_outcomes=False)
    assert n3 == 101


def test_live_bar_upsert_covers_downtime_gap(tmp_path):
    """Bars above the persisted MAX (server downtime) must all land incrementally."""
    from db import EdDB

    db = EdDB(tmp_path / "gap.db")
    t0 = _collect_window_session_open_ts()
    early = [
        {"datetime": t0 + i * 60.0, "open": 100.0, "high": 101.0,
         "low": 99.0, "close": 100.0, "volume": 1.0}
        for i in range(10)
    ]
    assert db.upsert_1m_bars("QQQ", early) == 10
    # 2h downtime, then the accumulator re-seeds the full history including the gap.
    late = early + [
        {"datetime": t0 + (120 + i) * 60.0, "open": 100.0, "high": 101.0,
         "low": 99.0, "close": 101.0, "volume": 1.0}
        for i in range(10)
    ]
    db.upsert_1m_bars("QQQ", late)
    with db._connect() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM price_bars_1m WHERE ticker='QQQ'"
        ).fetchone()[0]
    assert total == 20, "gap bars above the persisted MAX must all land"










