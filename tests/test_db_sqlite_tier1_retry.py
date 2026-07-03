"""db.py tier-1 snapshot write: sqlite busy/locked retry via sqlite_errorcode."""

from __future__ import annotations

import sqlite3

from pathlib import Path

import pytest

from db import EdDB, _sqlite_busy_or_locked

ROOT = Path(__file__).resolve().parent.parent
INDEX_HTML = ROOT / "static" / "index.html"


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
        classify_contention_findings,
        scan_ui_db_degraded_surfaces,
        SqliteContentionMetrics,
    )

    ui = scan_ui_db_degraded_surfaces()
    assert ui.get("operator_db_degraded_surface") is True
    assert "ub-pill-db" in INDEX_HTML.read_text(encoding="utf-8")
    assert "dr-db-contention-chip" in INDEX_HTML.read_text(encoding="utf-8")
    tags = classify_contention_findings(
        SqliteContentionMetrics(sqlite_lock_wait_count=1),
        ui_surfaces=ui,
        writer_map={"tier_c_reads_db": True},
        correlation={"offline_correlation_gap": True},
    )
    assert "UI_DEGRADED_STATE_MISSING" not in tags
    report = build_contention_impact_report(
        audit_date="2026-06-18",
        log_text="",
        log_paths=[],
        db_path=None,
    )
    assert "UI_DEGRADED_STATE_MISSING" not in report.get("classifications", [])


def test_no_contention_operator_status_ok():
    from verification.db_sqlite_contention_impact_audit import derive_db_contention_operator_status

    status = derive_db_contention_operator_status(
        {
            "sqlite_lock_wait_count": 0,
            "sqlite_lock_wait_max_ms": 0.0,
            "sqlite_busy_retry_count": 0,
            "sqlite_database_locked_count": 0,
            "sqlite_tier1_fail_count": 0,
            "recent_events": [],
        }
    )
    assert status["state"] == "OK"
    assert status["show"] is False


def test_recent_lock_wait_event_yields_db_waiting():
    """DB pill truth decay fix: WAITING derives from recent-window events, not lifetime."""
    from verification.db_sqlite_contention_impact_audit import derive_db_contention_operator_status

    now = 1_700_000_100.0
    status = derive_db_contention_operator_status(
        {
            "sqlite_lock_wait_count": 1,
            "sqlite_lock_wait_max_ms": 120.0,
            "sqlite_busy_retry_count": 0,
            "sqlite_database_locked_count": 0,
            "sqlite_tier1_fail_count": 0,
            "recent_events": [
                {"kind": "lock_wait", "wait_ms": 120.0, "ts_utc": now - 10.0}
            ],
        },
        now_utc=now,
    )
    assert status["state"] == "DB_WAITING"
    assert status["show"] is True
    assert "snapshot writes delayed" in status["detail"]


def test_recent_high_lock_wait_yields_db_degraded():
    """Recent contention still degrades: one >=500ms wait OR >=3 waits in the window."""
    from verification.db_sqlite_contention_impact_audit import derive_db_contention_operator_status

    now = 1_700_000_100.0
    big = derive_db_contention_operator_status(
        {
            "sqlite_lock_wait_count": 1,
            "sqlite_lock_wait_max_ms": 748.6,
            "recent_events": [
                {"kind": "lock_wait", "wait_ms": 748.6, "ts_utc": now - 5.0}
            ],
        },
        now_utc=now,
    )
    assert big["state"] == "DB_DEGRADED"
    assert "cards may lag" in big["detail"]
    # Ticker-agnostic / process-global: three MEANINGFUL waits across trio AND guest tickers.
    many = derive_db_contention_operator_status(
        {
            "sqlite_lock_wait_count": 3,
            "sqlite_lock_wait_max_ms": 180.0,
            "recent_events": [
                {"kind": "lock_wait", "wait_ms": 150.0, "ticker": "SPY", "ts_utc": now - 30.0},
                {"kind": "lock_wait", "wait_ms": 160.0, "ticker": "QQQ", "ts_utc": now - 20.0},
                {"kind": "lock_wait", "wait_ms": 180.0, "ticker": "XLE", "ts_utc": now - 10.0},
            ],
        },
        now_utc=now,
    )
    assert many["state"] == "DB_DEGRADED"


def test_sub_warn_write_telemetry_never_classifies():
    """The tier-1 recorder emits a lock_wait event for EVERY write (sub-ms uncontended
    acquires included) — normal per-minute trio writes must read OK, not DB_DEGRADED.
    This was the pill's permanent-degraded artifact: any 3 recorded writes tripped it."""
    from verification.db_sqlite_contention_impact_audit import derive_db_contention_operator_status

    now = 1_700_000_100.0
    status = derive_db_contention_operator_status(
        {
            "sqlite_lock_wait_count": 6,
            "sqlite_lock_wait_max_ms": 0.02,
            "recent_events": [
                {"kind": "lock_wait", "wait_ms": 0.002, "ticker": t, "ts_utc": now - i * 10.0}
                for i, t in enumerate(("SPY", "SPY", "QQQ", "QQQ", "IWM", "IWM"))
            ],
        },
        now_utc=now,
    )
    assert status["state"] == "OK"
    assert status["show"] is False
    assert status["recent_window_summary"]["lock_wait_count"] == 0


def test_lifetime_counters_alone_recover_to_ok_after_window_clears():
    """Truth decay fix: historical contention must not pin the pill degraded forever.

    Lifetime counters (21 waits, 3.6s max — the 2026-07-03 live incident shape) with no
    event inside the 120s window -> OK, while the cumulative numbers stay visible in
    metrics_summary for diagnostics.
    """
    from verification.db_sqlite_contention_impact_audit import derive_db_contention_operator_status

    now = 1_700_000_600.0
    status = derive_db_contention_operator_status(
        {
            "sqlite_lock_wait_count": 21,
            "sqlite_lock_wait_max_ms": 3617.439,
            "sqlite_busy_retry_count": 2,
            "sqlite_database_locked_count": 0,
            "sqlite_tier1_fail_count": 0,
            "recent_events": [
                # Real events, but all older than the 120s recovery window.
                {"kind": "lock_wait", "wait_ms": 3617.439, "ts_utc": now - 300.0},
                {"kind": "busy_retry", "ts_utc": now - 280.0},
            ],
        },
        now_utc=now,
    )
    assert status["state"] == "OK"
    assert status["show"] is False
    # Cumulative diagnostics preserved — recovery is decay, not suppression.
    assert status["metrics_summary"]["sqlite_lock_wait_count"] == 21
    assert status["metrics_summary"]["sqlite_lock_wait_max_ms"] == 3617.439
    assert status["metrics_summary"]["sqlite_busy_retry_count"] == 2
    assert status["recent_window_summary"]["lock_wait_count"] == 0


def test_live_bar_upsert_is_incremental_bulk_path_full(tmp_path):
    """Console usability slice 2026-07-03: the live path must not rewrite the whole
    multi-day bars list every cycle (17.8s first-cycle exec observed live) — only bars
    at/after (per-ticker MAX bar_start − overlap) are written. Bulk backfills
    (refresh_governed_outcomes=False) keep the full write for hole repairs."""
    from db import EdDB, LIVE_BARS_REUPSERT_OVERLAP_SEC

    db = EdDB(tmp_path / "bars.db")
    t0 = 1_020_000.0
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
    t0 = 1_020_000.0
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


def test_db_locked_not_weakened_by_window_decay():
    """DB_LOCKED stays strict: lifetime locked/tier1-fail counters flag even with an
    empty recent window (a proven locked/failed write is a hard process flag)."""
    from verification.db_sqlite_contention_impact_audit import derive_db_contention_operator_status

    now = 1_700_000_600.0
    status = derive_db_contention_operator_status(
        {
            "sqlite_lock_wait_count": 0,
            "sqlite_lock_wait_max_ms": 0.0,
            "sqlite_busy_retry_count": 0,
            "sqlite_database_locked_count": 1,
            "sqlite_tier1_fail_count": 0,
            "recent_events": [],
        },
        now_utc=now,
    )
    assert status["state"] == "DB_LOCKED"
    assert status["severity"] == "bad"


def test_database_locked_yields_db_locked():
    from verification.db_sqlite_contention_impact_audit import derive_db_contention_operator_status

    status = derive_db_contention_operator_status(
        {
            "sqlite_lock_wait_count": 0,
            "sqlite_lock_wait_max_ms": 0.0,
            "sqlite_busy_retry_count": 0,
            "sqlite_database_locked_count": 1,
            "sqlite_tier1_fail_count": 1,
            "recent_events": [{"kind": "database_locked", "ts_utc": 1_700_000_000.0}],
        },
        now_utc=1_700_000_060.0,
    )
    assert status["state"] == "DB_LOCKED"
    assert "analytics freshness at risk" in status["detail"]


def test_build_db_contention_operator_surface_preserves_metadata():
    from verification.db_sqlite_contention_impact_audit import build_db_contention_operator_surface

    metrics = {
        "sqlite_lock_wait_count": 1,
        "sqlite_lock_wait_max_ms": 200.0,
        "operations_affected": {"insert_snapshot": 1},
        "tickers_affected": {"SPY": 1},
        "threads_affected": {"ed-base-money-path-logger": 1},
        "recent_events": [
            {
                "kind": "lock_wait",
                "op": "insert_snapshot",
                "ticker": "SPY",
                "thread": "ed-base-money-path-logger",
                "ts_utc": 1.0,
            }
        ],
    }
    surface = build_db_contention_operator_surface(metrics)
    assert surface["operations_affected"]["insert_snapshot"] == 1
    assert surface["tickers_affected"]["SPY"] == 1
    assert surface["threads_affected"]["ed-base-money-path-logger"] == 1
    assert surface["recent_events_sample"][-1]["op"] == "insert_snapshot"
    assert surface["diagnostics_source"] == "/api/diagnostics/sqlite-contention"


def test_attach_db_contention_operator_surface_preserves_mhap_rows():
    import copy

    from server import _attach_db_contention_operator_surface

    for ticker in ("SPY", "NVDA"):
        ms = {
            "ticker": ticker,
            "mhap_rows": [{"horizon": "1c", "call": "LONG", "conf": 0.82}],
        }
        before = copy.deepcopy(ms["mhap_rows"])
        _attach_db_contention_operator_surface(ms)
        assert ms["mhap_rows"] == before
        assert "db_contention_operator" in ms
        assert ms["db_contention_operator"].get("diagnostics_source")


def test_sqlite_contention_diagnostics_route_includes_operator():
    from fastapi.testclient import TestClient

    from server import app

    client = TestClient(app)
    resp = client.get("/api/diagnostics/sqlite-contention")
    assert resp.status_code == 200
    body = resp.json()
    assert "operator" in body
    assert body["operator"]["state"] in {"OK", "DB_WAITING", "DB_DEGRADED", "DB_LOCKED"}
    assert body["operator"]["diagnostics_source"] == "/api/diagnostics/sqlite-contention"
