"""repair_canonical_1m_interior_gaps_v1 fail-closed contracts."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from calibration.repair_canonical_1m_interior_gaps_v1 import run_repair
from horizon_outcomes import AUTHORITATIVE_1M_SOURCE, SYNTHETIC_INTERIOR_GRID_REPAIR_V1


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


def test_interior_interp_uses_schwab_neighbors_not_synthetic(tmp_path: Path, monkeypatch):
    from calibration import repair_canonical_1m_interior_gaps_v1 as interior

    db_path = tmp_path / "interior.db"
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
        INSERT INTO price_bars_1m VALUES
        ('SPY', 1000.0, 1060.0, 10.0, 10.0, 10.0, 10.0, 1.0, ?),
        ('SPY', 1120.0, 1180.0, 20.0, 20.0, 20.0, 20.0, 1.0, ?),
        ('SPY', 1060.0, 1120.0, 99.0, 99.0, 99.0, 99.0, 0.0, ?)
        """,
        (
            AUTHORITATIVE_1M_SOURCE,
            AUTHORITATIVE_1M_SOURCE,
            SYNTHETIC_INTERIOR_GRID_REPAIR_V1,
        ),
    )
    conn.commit()
    conn.close()

    class _Rec:
        def __init__(self, ticker: str, required: float):
            self._d = {"ticker": ticker, "required_bar_start_ts_utc": required}

        def __getitem__(self, k):
            return self._d[k]

    monkeypatch.setattr(
        interior,
        "scan_db",
        lambda _db, tz_now_utc: type(
            "R",
            (),
            {"missing_forward": [_Rec("SPY", 1060.0)]},
        )(),
    )

    planned = interior._collect_interior_missing(db_path, tz_now=2000.0)
    assert len(planned) == 1
    _tkr, g, lo, hi, c_g = planned[0]
    assert g == 1060.0
    assert lo == 1000.0 and hi == 1120.0
    assert c_g == pytest.approx(15.0)
