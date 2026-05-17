"""repair_canonical_1m_edge_carry_v1 fail-closed contracts."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from calibration.repair_canonical_1m_edge_carry_v1 import run_repair
from horizon_outcomes import AUTHORITATIVE_1M_SOURCE, SYNTHETIC_EDGE_CARRY_V1


def _seed_db(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE price_bars_1m (
            ticker TEXT NOT NULL,
            bar_start_ts_utc REAL NOT NULL,
            bar_end_ts_utc REAL NOT NULL,
            open REAL, high REAL, low REAL, close REAL, volume REAL,
            source TEXT,
            PRIMARY KEY (ticker, bar_start_ts_utc)
        );
        """
    )
    conn.execute(
        """
        INSERT INTO price_bars_1m
          (ticker, bar_start_ts_utc, bar_end_ts_utc, open, high, low, close, volume, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("SPY", 1000.0, 1060.0, 10.0, 10.0, 10.0, 10.0, 1.0, AUTHORITATIVE_1M_SOURCE),
    )
    conn.commit()
    conn.close()


def test_run_repair_empty_db_errors(tmp_path: Path):
    db_path = tmp_path / "empty.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE price_bars_1m (
            ticker TEXT NOT NULL,
            bar_start_ts_utc REAL NOT NULL,
            bar_end_ts_utc REAL NOT NULL,
            open REAL, high REAL, low REAL, close REAL, volume REAL,
            source TEXT,
            PRIMARY KEY (ticker, bar_start_ts_utc)
        );
        """
    )
    conn.close()
    rep = run_repair(db_path, dry_run=True)
    assert rep.get("error") == "no_bars_in_price_bars_1m"


def test_carry_basis_excludes_prior_synthetic_close(tmp_path: Path, monkeypatch):
    """Carry price must come from Schwab bar, not an earlier synthetic repair bar."""
    from calibration import repair_canonical_1m_edge_carry_v1 as edge

    db_path = tmp_path / "carry.db"
    _seed_db(db_path)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        INSERT INTO price_bars_1m
          (ticker, bar_start_ts_utc, bar_end_ts_utc, open, high, low, close, volume, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("SPY", 5000.0, 5060.0, 99.0, 99.0, 99.0, 99.0, 0.0, SYNTHETIC_EDGE_CARRY_V1),
    )
    conn.commit()
    conn.close()

    class _Rec:
        def __init__(self, ticker: str, required: float):
            self._d = {"ticker": ticker, "required_bar_start_ts_utc": required}

        def __getitem__(self, k):
            return self._d[k]

    monkeypatch.setattr(
        edge,
        "scan_db",
        lambda _db, tz_now_utc: type(
            "R",
            (),
            {"missing_forward": [_Rec("SPY", 4000.0)]},
        )(),
    )

    planned = edge._planned_edge_carries(db_path, tz_now=6000.0)
    assert planned
    _tkr, _g, close = planned[0]
    assert close == 10.0
