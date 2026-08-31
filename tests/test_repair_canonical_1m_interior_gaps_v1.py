"""repair_canonical_1m_interior_gaps_v1 fail-closed contracts."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from calibration.repair_canonical_1m_interior_gaps_v1 import run_repair
from horizon_outcomes import AUTHORITATIVE_1M_SOURCE, SYNTHETIC_INTERIOR_GRID_REPAIR_V1


def test_run_repair_empty_db_errors(tmp_path: Path):
    # institutional-duplicate-ok: same-shaped test against a DIFFERENT production
    # module (calibration.repair_canonical_1m_interior_gaps_v1.run_repair, not
    # edge_carry_v1) -- TEST_SYSTEM_REHAB_V2 semantic review kept both deliberately.
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


def test_apply_repair_batch_writes_with_snapshot_refresh(tmp_path: Path):
    """Regression: shared repair conn must use sqlite3.Row for governed refresh."""
    from calibration.repair_canonical_1m_shared import apply_repair_1m_bar_batch_writes
    from timeframe_config import CANONICAL_TIMEFRAME

    db_path = tmp_path / "refresh.db"
    base = 1_785_506_400.0  # 2026-07-31 10:00 ET — in-window session (RC-183 collect-window law)
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        f"""
        CREATE TABLE price_bars_1m (
            ticker TEXT NOT NULL,
            bar_start_ts_utc REAL NOT NULL,
            bar_end_ts_utc REAL NOT NULL,
            open REAL, high REAL, low REAL, close REAL, volume REAL,
            source TEXT,
            PRIMARY KEY (ticker, bar_start_ts_utc)
        );
        CREATE TABLE snapshots (
            snapshot_id INTEGER PRIMARY KEY,
            ticker TEXT, timeframe TEXT, ts_utc REAL, atr REAL,
            horizon_outcome_schema_version INTEGER,
            outcome_1c TEXT, outcome_5c TEXT, outcome_15c TEXT, outcome_60c TEXT,
            outcome_1c_pts REAL, outcome_5c_pts REAL, outcome_15c_pts REAL, outcome_60c_pts REAL,
            outcome_filled INTEGER DEFAULT 0
        );
        INSERT INTO price_bars_1m VALUES
          ('SPY', {base}, {base + 60.0}, 10,10,10,10,1,'schwab'),
          ('SPY', {base + 120.0}, {base + 180.0}, 20,20,20,20,1,'schwab');
        INSERT INTO snapshots (ticker, timeframe, ts_utc, atr, horizon_outcome_schema_version)
        VALUES ('SPY', '{CANONICAL_TIMEFRAME}', {base + 50.0}, 1.0, 3);
        """
    )
    conn.commit()
    conn.close()
    n_written, n_tickers = apply_repair_1m_bar_batch_writes(
        db_path,
        {
            "SPY": [
                {
                    "ts": base + 60.0,
                    "open": 15.0,
                    "high": 15.0,
                    "low": 15.0,
                    "close": 15.0,
                    "volume": 0.0,
                    "source": SYNTHETIC_INTERIOR_GRID_REPAIR_V1,
                }
            ]
        },
        tz=base + 2000.0,
        default_source=SYNTHETIC_INTERIOR_GRID_REPAIR_V1,
    )
    assert n_written == 1 and n_tickers == 1
    conn = sqlite3.connect(str(db_path))
    assert conn.execute(
        "SELECT COUNT(*) FROM price_bars_1m WHERE bar_start_ts_utc=?", (base + 60.0,)
    ).fetchone()[0] == 1
    conn.close()
