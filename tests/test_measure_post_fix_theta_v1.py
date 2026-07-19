"""Unit tests for tools/measure_post_fix_theta_v1.py (read-only S008 measurement helper)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tools.measure_post_fix_theta_v1 import run_measure


def _mk_db(path: Path) -> None:
    # institutional-synthetic-ok: theta-classification measurement needs a chain with
    # controlled theta states (numeric / null / missing key) to assert exact bucket rates.
    conn = sqlite3.connect(str(path))
    conn.execute(
        """
        CREATE TABLE snapshots (
            snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            created_at TEXT NOT NULL,
            ts_utc REAL NOT NULL,
            option_chain_json TEXT
        );
        """
    )
    chain = [
        {
            "putCall": "CALL",
            "strikePrice": 500.0,
            "daysToExpiration": 0,
            "theta": -0.05,
            "quoteTimeInLong": 1_700_000_000_000,
            "tradeTimeInLong": 1_700_000_000_001,
        },
        {
            "putCall": "CALL",
            "strikePrice": 501.0,
            "daysToExpiration": 0,
            "theta": None,
            "quoteTimeInLong": 1,
            "tradeTimeInLong": None,
        },
        {
            "putCall": "PUT",
            "strikePrice": 499.0,
            "daysToExpiration": 1,
            "delta": 0.1,
        },
    ]
    conn.execute(
        "INSERT INTO snapshots (ticker, created_at, ts_utc, option_chain_json) VALUES (?,?,?,?)",
        (
            "SPY",
            "2026-05-10 12:00:00",
            1_717_948_800.0,
            json.dumps(chain),
        ),
    )
    conn.commit()
    conn.close()


def test_run_measure_theta_rates_and_zero_dte_scope(tmp_path: Path) -> None:
    db = tmp_path / "t.db"
    _mk_db(db)
    r_all = run_measure(
        db,
        since="2026-05-09 00:00:00",
        tickers=["SPY"],
        contract_scope="all",
        date_source="ts_utc",
        row_limit=None,
    )
    assert r_all["totals"]["contract_observations"] == 3
    assert r_all["totals"]["theta_key_missing_rate"] == pytest.approx(1 / 3)
    assert r_all["totals"]["theta_present_null_rate"] == pytest.approx(1 / 3)
    assert r_all["totals"]["theta_present_numeric_rate"] == pytest.approx(1 / 3)
    assert r_all["totals"]["quoteTimeInLong_present_rate"] == pytest.approx(2 / 3)
    assert r_all["totals"]["tradeTimeInLong_present_rate"] == pytest.approx(1 / 3)

    r_zd = run_measure(
        db,
        since="2026-05-09 00:00:00",
        tickers=["SPY"],
        contract_scope="zero_dte",
        date_source="ts_utc",
        row_limit=None,
    )
    assert r_zd["totals"]["contract_observations"] == 2


def test_classify_theta_buckets_minus_999_as_present_sentinel() -> None:
    """Schwab's -999.0 'missing greek' sentinel must not inflate present_numeric."""
    from tools.measure_post_fix_theta_v1 import _classify_theta

    assert _classify_theta({"theta": -999.0}) == "present_sentinel"
    assert _classify_theta({"theta": "-999.0"}) == "present_sentinel"
    assert _classify_theta({"theta": -999}) == "present_sentinel"
    assert _classify_theta({"theta": -0.05}) == "present_numeric"
    assert _classify_theta({"theta": None}) == "present_null"
    assert _classify_theta({}) == "key_missing"


def test_run_measure_separates_sentinel_from_numeric_theta(tmp_path: Path) -> None:
    """Mixed chain (real, sentinel, null, missing) must report distinct rates per bucket."""
    # institutional-synthetic-ok: needs one contract per theta state (numeric/-999
    # sentinel/null/missing) to assert 1/4 each — not sourceable from real data.
    db = tmp_path / "t_sentinel.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        """
        CREATE TABLE snapshots (
            snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            created_at TEXT NOT NULL,
            ts_utc REAL NOT NULL,
            option_chain_json TEXT
        );
        """
    )
    chain = [
        {"putCall": "CALL", "strikePrice": 500.0, "daysToExpiration": 0, "theta": -0.05},
        {"putCall": "CALL", "strikePrice": 501.0, "daysToExpiration": 0, "theta": -999.0},
        {"putCall": "PUT", "strikePrice": 499.0, "daysToExpiration": 0, "theta": None},
        {"putCall": "PUT", "strikePrice": 498.0, "daysToExpiration": 0},
    ]
    conn.execute(
        "INSERT INTO snapshots (ticker, created_at, ts_utc, option_chain_json) VALUES (?,?,?,?)",
        ("SPY", "2026-05-10 12:00:00", 1_717_948_800.0, json.dumps(chain)),
    )
    conn.commit()
    conn.close()

    r = run_measure(
        db,
        since="2026-05-09 00:00:00",
        tickers=["SPY"],
        contract_scope="all",
        date_source="ts_utc",
        row_limit=None,
    )

    totals = r["totals"]
    assert totals["contract_observations"] == 4
    assert totals["theta_present_numeric_rate"] == pytest.approx(1 / 4)
    assert totals["theta_present_sentinel_rate"] == pytest.approx(1 / 4)
    assert totals["theta_present_null_rate"] == pytest.approx(1 / 4)
    assert totals["theta_key_missing_rate"] == pytest.approx(1 / 4)
    # Per-row matrix carries the same separation
    matrix = r["matrix"]
    assert len(matrix) == 1
    assert matrix[0]["theta_present_sentinel_rate"] == pytest.approx(1 / 4)
    assert matrix[0]["theta_present_numeric_rate"] == pytest.approx(1 / 4)


def test_branch_hint_flags_sentinel_pressure_as_branch_b_or_c() -> None:
    """A material -999 sentinel rate (>=5%) must steer the operator away from Branch A."""
    from tools.measure_post_fix_theta_v1 import _branch_hint

    hint = _branch_hint(
        miss_r=0.0,
        null_r=0.0,
        numeric_r=0.9,
        sentinel_r=0.10,
        n_contracts=1000,
    )
    assert hint["branch_hint"] == "Branch_B_or_C_likely"
    assert "sentinel" in hint["rationale"].lower()


def test_branch_hint_branch_a_requires_clean_sentinel_rate() -> None:
    """Branch A requires miss/null/sentinel all near zero; otherwise downshift."""
    from tools.measure_post_fix_theta_v1 import _branch_hint

    clean = _branch_hint(
        miss_r=0.0,
        null_r=0.0,
        numeric_r=1.0,
        sentinel_r=0.0,
        n_contracts=1000,
    )
    assert clean["branch_hint"] == "Branch_A_likely"

    dirty_sentinel = _branch_hint(
        miss_r=0.0,
        null_r=0.0,
        numeric_r=0.99,
        sentinel_r=0.01,
        n_contracts=1000,
    )
    # 1% sentinel is below the 5% Branch_B_or_C threshold but above the 0.1% Branch_A bar.
    assert dirty_sentinel["branch_hint"] == "Branch_C_possible"


def test_run_measure_skips_bad_json(tmp_path: Path) -> None:
    db = tmp_path / "t2.db"
    conn = sqlite3.connect(str(db))
    conn.execute(
        """
        CREATE TABLE snapshots (
            snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            created_at TEXT NOT NULL,
            ts_utc REAL NOT NULL,
            option_chain_json TEXT
        );
        """
    )
    conn.execute(
        "INSERT INTO snapshots (ticker, created_at, ts_utc, option_chain_json) VALUES (?,?,?,?)",
        ("QQQ", "2026-05-10 12:00:00", 1_717_948_800.0, "not-json-at-all!!"),
    )
    conn.commit()
    conn.close()

    r = run_measure(
        db,
        since="2026-05-09 00:00:00",
        tickers=["QQQ"],
        contract_scope="all",
        date_source="ts_utc",
        row_limit=None,
    )
    assert r["totals"]["chain_parse_errors"] == 1
    assert r["totals"]["contract_observations"] == 0
