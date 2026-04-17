"""Issue 3 — universal bar-based horizon math and DB fill."""
from __future__ import annotations

import math
import sqlite3
from pathlib import Path

import pytest

from horizon_outcomes import (
    HORIZON_OUTCOME_SCHEMA_BAR_V1,
    HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
    bar_complete_by_utc,
    forward_bar_start_utc,
    OUTCOME_BAR_SPECS,
)
from db import EdDB, get_snapshot_sql
from timeframe_config import CANONICAL_TIMEFRAME as CF


def test_forward_bar_start_grid():
    assert forward_bar_start_utc(100.0, 1) == math.floor(160.0 / 60.0) * 60.0
    t0 = 1700000000.0
    assert forward_bar_start_utc(t0, 60) == math.floor((t0 + 3600.0) / 60.0) * 60.0


def test_bar_complete():
    assert not bar_complete_by_utc(120.0, 179.0)
    assert bar_complete_by_utc(120.0, 180.0)


def test_outcome_specs_cover_all_nc():
    names = [s[0] for s in OUTCOME_BAR_SPECS]
    assert names == [
        "outcome_1c",
        "outcome_3c",
        "outcome_5c",
        "outcome_8c",
        "outcome_13c",
        "outcome_15c",
        "outcome_60c",
    ]
    assert HORIZON_OUTCOME_SCHEMA_BAR_V1 == 2
    assert HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1 == 3


@pytest.fixture
def tmp_db(tmp_path: Path) -> EdDB:
    return EdDB(tmp_path / "t.db")


def test_fill_outcomes_bar_based_anchor_matches_last_completed_bar(tmp_db: EdDB):
    """Anchor = close of last bar with bar_end <= ts_utc; forward close unchanged (Issue 4)."""
    t0 = 1_020_000.0  # on 1m grid
    t_snap = t0 + 90.0  # after first bar ends (t0+60), inside second bar
    with tmp_db._connect() as conn:
        conn.execute(
            """
            INSERT INTO snapshots (
                ticker, timeframe, ts_utc, ts_et, et_hour, et_minute, market_session, spot,
                horizon_outcome_schema_version, outcome_filled
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                "SPY",
                CF,
                t_snap,
                "test",
                10,
                30,
                "rth",
                9999.0,
                HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
            ),
        )
    bars = []
    for i in range(100):
        bs = t0 + i * 60.0
        bars.append(
            {
                "datetime": bs,
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0 + 0.1 * i,
                "volume": 1.0,
            }
        )
    tmp_db.upsert_1m_bars("SPY", bars)
    tmp_db.fill_outcomes("SPY", CF, t_snap + 5000.0)

    with tmp_db._connect() as conn:
        row = conn.execute(
            get_snapshot_sql("tests/test_horizon_bar_outcomes.py:94"),
            (CF,),
        ).fetchone()
    assert row is not None
    assert row["outcome_1c"] is not None
    anchor_close = 100.0 + 0.1 * 0.0
    b1 = forward_bar_start_utc(t_snap, 1)
    i_fwd = int(round((b1 - t0) / 60.0))
    forward_close = 100.0 + 0.1 * float(i_fwd)
    pts = forward_close - anchor_close
    assert abs(float(row["outcome_1c_pts"]) - pts) < 1e-6


def test_migration_issue4_clears_v2_labels(tmp_path: Path):
    """Opening DB runs Issue 4 migration once: v2 rows lose derived outcomes, version -> 3."""
    db_path = tmp_path / "preissue4.db"
    with sqlite3.connect(str(db_path)) as conn:
        conn.executescript(
            """
            CREATE TABLE snapshots (
                snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT, timeframe TEXT, ts_utc REAL, ts_et TEXT,
                et_hour INTEGER, et_minute INTEGER, market_session TEXT, spot REAL,
                outcome_1c TEXT, outcome_1c_pts REAL,
                outcome_3c TEXT, outcome_3c_pts REAL,
                outcome_5c TEXT, outcome_5c_pts REAL,
                outcome_8c TEXT, outcome_8c_pts REAL,
                outcome_13c TEXT, outcome_13c_pts REAL,
                outcome_15c TEXT, outcome_15c_pts REAL,
                outcome_60c TEXT, outcome_60c_pts REAL,
                horizon_outcome_schema_version INTEGER DEFAULT 2,
                outcome_filled INTEGER DEFAULT 0
            );
            INSERT INTO snapshots (
                ticker, timeframe, ts_utc, ts_et, et_hour, et_minute,
                market_session, spot, outcome_1c, horizon_outcome_schema_version,
                outcome_filled
            ) VALUES ('X', '1m', 1.0, 't', 0, 0, 'rth', 1.0, 'up', 2, 1);
            CREATE TABLE ed_schema_flags (
                flag_key TEXT PRIMARY KEY, flag_value TEXT NOT NULL, set_ts_utc REAL
            );
            INSERT INTO ed_schema_flags VALUES ('horizon_bar_v1_legacy_poll_invalidated', '1', 1.0);
            """
        )
        conn.commit()

    EdDB(db_path)

    with sqlite3.connect(str(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            get_snapshot_sql("tests/test_horizon_bar_outcomes.py:145")
        ).fetchone()
        flag = conn.execute(
            "SELECT 1 FROM ed_schema_flags WHERE flag_key='horizon_outcome_anchor_bar_close_v1'"
        ).fetchone()
    assert row["outcome_1c"] is None
    assert int(row["horizon_outcome_schema_version"]) == HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1
    assert flag is not None
