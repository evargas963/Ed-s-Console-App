"""Tests for base/guest ticker tiers and RTH observability checker."""
from __future__ import annotations

import datetime
import sqlite3
import time
from pathlib import Path

from money_path_ticker_tiers import (
    BASE_MONEY_PATH_TICKERS,
    TRUST_BASE,
    TRUST_GUEST_UNPROVEN,
    is_base_money_path_ticker,
    is_guest_ticker,
    load_base_ticker_contract,
    should_skip_background_full_snapshot,
    ticker_trust_class,
)
from verification.base_ticker_observability import (
    FAIL_SPARSE_SNAPSHOTS,
    PASS_BASE_OBSERVABILITY,
    base_ticker_observability_report,
    evaluate_ticker_observability,
    rth_window_utc,
)


def test_base_tickers_are_spy_qqq_iwm():
    assert BASE_MONEY_PATH_TICKERS == ("SPY", "QQQ", "IWM")
    contract = load_base_ticker_contract()
    assert contract["base_money_path_tickers"] == ["SPY", "QQQ", "IWM"]


def test_guest_ticker_not_universal_proof():
    assert is_guest_ticker("NVDA") is True
    assert is_guest_ticker("SPY") is False
    assert ticker_trust_class("PLTR") == TRUST_GUEST_UNPROVEN
    assert ticker_trust_class("SPY") == TRUST_BASE


def test_observability_passes_dense_spy_like_cadence(tmp_path: Path):
    db = tmp_path / "obs.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE snapshots (ticker TEXT, ts_utc REAL);
        CREATE TABLE snapshots_1m_normalized (ticker TEXT, ts_utc REAL);
        CREATE TABLE calibration_decision_log (ticker TEXT, decision_ts_utc REAL);
        """
    )
    day = datetime.date(2026, 6, 16)
    start, end = rth_window_utc(day)
    ts = start + 60
    while ts < end and ts <= start + 300 * 60:
        conn.execute("INSERT INTO snapshots VALUES ('SPY', ?)", (ts,))
        conn.execute("INSERT INTO snapshots_1m_normalized VALUES ('SPY', ?)", (ts,))
        conn.execute("INSERT INTO calibration_decision_log VALUES ('SPY', ?)", (ts,))
        ts += 60
    conn.commit()
    row = evaluate_ticker_observability(conn, "SPY", start, end)
    conn.close()
    assert row["coverage_status"] == PASS_BASE_OBSERVABILITY
    assert row["snapshot_count_rth"] >= 300


def test_observability_fails_sparse_qqq_like(tmp_path: Path):
    db = tmp_path / "sparse.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE snapshots (ticker TEXT, ts_utc REAL);
        CREATE TABLE snapshots_1m_normalized (ticker TEXT, ts_utc REAL);
        CREATE TABLE calibration_decision_log (ticker TEXT, decision_ts_utc REAL);
        """
    )
    day = datetime.date(2026, 6, 16)
    start, end = rth_window_utc(day)
    for i in range(19):
        ts = start + i * 1287
        conn.execute("INSERT INTO snapshots VALUES ('QQQ', ?)", (ts,))
        conn.execute("INSERT INTO snapshots_1m_normalized VALUES ('QQQ', ?)", (ts,))
        conn.execute("INSERT INTO calibration_decision_log VALUES ('QQQ', ?)", (ts,))
    conn.commit()
    row = evaluate_ticker_observability(conn, "QQQ", start, end)
    conn.close()
    assert row["coverage_status"] == FAIL_SPARSE_SNAPSHOTS


def test_replay_probe_imports_base_tier_helpers():
    from tools.replay_money_path_probe import run_probe  # noqa: F401

    assert is_base_money_path_ticker("IWM")


def test_base_tickers_never_skipped_for_panel_auto():
    """Base anchors must not be downgraded to confluence-only guest capture."""
    panel = frozenset({"SPY", "QQQ", "IWM", "WMT"})
    for anchor in BASE_MONEY_PATH_TICKERS:
        assert should_skip_background_full_snapshot(anchor, panel) is False
    assert should_skip_background_full_snapshot("WMT", panel) is True
    assert should_skip_background_full_snapshot("NVDA", frozenset()) is False


def test_filter_tickers_for_background_logging_keeps_base_anchors(tmp_path: Path):
    from db import EdDB
    from scheduler_user_tickers import filter_tickers_for_background_logging

    db = EdDB(tmp_path / "filter.db")
    now = time.time()
    db.logging_universe_sync_core(list(BASE_MONEY_PATH_TICKERS) + ["NVDA"], now)
    db.logging_universe_sync_panel_auto(["QQQ", "WMT"], now)
    tickers = filter_tickers_for_background_logging(
        list(BASE_MONEY_PATH_TICKERS) + ["NVDA", "WMT"],
        str(db.db_path),
    )
    for anchor in BASE_MONEY_PATH_TICKERS:
        assert anchor in tickers
    assert "WMT" not in tickers
    assert "NVDA" in tickers


def test_base_money_path_logger_tickers_match_anchors():
    import server as srv

    assert srv.base_money_path_logger_tickers() == BASE_MONEY_PATH_TICKERS
    assert len(srv.base_money_path_logger_tickers()) == 3


def test_start_logger_launches_base_money_path_thread(monkeypatch):
    import threading

    import server as srv

    started: list[str] = []

    class _FakeThread:
        def __init__(self, target=None, daemon=None, name=None):
            self._target = target
            self.name = name

        def start(self):
            started.append(self.name or "")

    monkeypatch.setattr(srv, "_hydrate_logger_tickers_from_db", lambda: None)
    monkeypatch.setattr(threading, "Thread", _FakeThread)
    monkeypatch.setattr(srv, "_logger_running", False)
    monkeypatch.setattr(srv, "_base_money_path_logger_running", False)
    try:
        srv.start_logger()
        assert "ed-ticker-logger" in started
        assert "ed-base-money-path-logger" in started
    finally:
        srv._logger_running = False
        srv._base_money_path_logger_running = False


def _seed_dense_rth_rows(conn: sqlite3.Connection, ticker: str, start: float) -> None:
    ts = start + 60
    while ts <= start + 300 * 60:
        conn.execute("INSERT INTO snapshots VALUES (?, ?)", (ticker, ts))
        conn.execute("INSERT INTO snapshots_1m_normalized VALUES (?, ?)", (ticker, ts))
        conn.execute("INSERT INTO calibration_decision_log VALUES (?, ?)", (ticker, ts))
        ts += 60


def test_observability_universe_ready_requires_all_three_base(tmp_path: Path):
    db = tmp_path / "universe.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE snapshots (ticker TEXT, ts_utc REAL);
        CREATE TABLE snapshots_1m_normalized (ticker TEXT, ts_utc REAL);
        CREATE TABLE calibration_decision_log (ticker TEXT, decision_ts_utc REAL);
        """
    )
    day = datetime.date(2026, 6, 16)
    start, _end = rth_window_utc(day)
    for anchor in BASE_MONEY_PATH_TICKERS:
        _seed_dense_rth_rows(conn, anchor, start)
    conn.commit()
    conn.close()

    report = base_ticker_observability_report(
        day=day,
        tickers=list(BASE_MONEY_PATH_TICKERS),
        db_path=db,
    )
    assert report["meta"]["base_universe_ready"] is True
    assert report["summary"]["pass_count"] == 3
    assert report["summary"]["fail_count"] == 0
    for row in report["tickers"]:
        assert row["coverage_status"] == PASS_BASE_OBSERVABILITY


def test_observability_universe_not_ready_when_one_base_sparse(tmp_path: Path):
    db = tmp_path / "partial.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE snapshots (ticker TEXT, ts_utc REAL);
        CREATE TABLE snapshots_1m_normalized (ticker TEXT, ts_utc REAL);
        CREATE TABLE calibration_decision_log (ticker TEXT, decision_ts_utc REAL);
        """
    )
    day = datetime.date(2026, 6, 16)
    start, end = rth_window_utc(day)
    _seed_dense_rth_rows(conn, "SPY", start)
    for i in range(19):
        ts = start + i * 1287
        conn.execute("INSERT INTO snapshots VALUES ('QQQ', ?)", (ts,))
        conn.execute("INSERT INTO snapshots_1m_normalized VALUES ('QQQ', ?)", (ts,))
        conn.execute("INSERT INTO calibration_decision_log VALUES ('QQQ', ?)", (ts,))
    _seed_dense_rth_rows(conn, "IWM", start)
    conn.commit()
    conn.close()

    report = base_ticker_observability_report(
        day=day,
        tickers=list(BASE_MONEY_PATH_TICKERS),
        db_path=db,
    )
    assert report["meta"]["base_universe_ready"] is False
    by_t = {r["ticker"]: r for r in report["tickers"]}
    assert by_t["SPY"]["coverage_status"] == PASS_BASE_OBSERVABILITY
    assert by_t["QQQ"]["coverage_status"] == FAIL_SPARSE_SNAPSHOTS
    assert by_t["IWM"]["coverage_status"] == PASS_BASE_OBSERVABILITY


def test_check_base_ticker_observability_cli_passes_on_dense_fixture(tmp_path: Path):
    """CLI gate exit 0 when all three base tickers meet RTH thresholds (deterministic fixture)."""
    import subprocess
    import sys

    db = tmp_path / "cli_pass.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE snapshots (ticker TEXT, ts_utc REAL);
        CREATE TABLE snapshots_1m_normalized (ticker TEXT, ts_utc REAL);
        CREATE TABLE calibration_decision_log (ticker TEXT, decision_ts_utc REAL);
        """
    )
    day = datetime.date(2026, 6, 17)
    start, _end = rth_window_utc(day)
    for anchor in BASE_MONEY_PATH_TICKERS:
        _seed_dense_rth_rows(conn, anchor, start)
    conn.commit()
    conn.close()

    repo = Path(__file__).resolve().parent.parent
    proc = subprocess.run(
        [
            sys.executable,
            str(repo / "tools" / "check_base_ticker_observability.py"),
            "--date",
            day.isoformat(),
            "--tickers",
            "SPY",
            "QQQ",
            "IWM",
            "--db",
            str(db),
        ],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "universe_ready=True" in proc.stdout
    assert "PASS_BASE_OBSERVABILITY" in proc.stdout
