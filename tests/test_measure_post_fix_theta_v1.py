"""Unit tests for tools/measure_post_fix_theta_v1.py (read-only S008 measurement helper)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tools.measure_post_fix_theta_v1 import run_measure


def _mk_db(path: Path) -> None:
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
