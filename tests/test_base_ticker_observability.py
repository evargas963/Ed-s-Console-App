"""Tests for base/guest ticker tiers and RTH observability checker."""
from __future__ import annotations

import datetime
import sqlite3
from pathlib import Path

from money_path_ticker_tiers import (
    BASE_MONEY_PATH_TICKERS,
    TRUST_BASE,
    TRUST_GUEST_UNPROVEN,
    is_base_money_path_ticker,
    is_guest_ticker,
    load_base_ticker_contract,
    ticker_trust_class,
)
from verification.base_ticker_observability import (
    FAIL_SPARSE_SNAPSHOTS,
    PASS_BASE_OBSERVABILITY,
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
