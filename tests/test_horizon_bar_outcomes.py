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
        "outcome_5c",
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
                outcome_5c TEXT, outcome_5c_pts REAL,
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


# ── Phase 1 (horizon-collapse fix): per-horizon vol-scaled outcome threshold ──────


def test_classify_direction_pts_threshold_and_fail_closed():
    """classify_direction_pts uses a points threshold and fails closed without a valid scale."""
    from math_probabilities import classify_direction, classify_direction_pts

    # up / down / flat by the supplied points threshold (strict inequality; boundary = flat)
    assert classify_direction_pts(0.6, 0.5) == "up"
    assert classify_direction_pts(-0.6, 0.5) == "down"
    assert classify_direction_pts(0.4, 0.5) == "flat"
    assert classify_direction_pts(-0.4, 0.5) == "flat"
    assert classify_direction_pts(0.5, 0.5) == "flat"

    # Fail-closed: no directional claim without a valid (>0) volatility scale.
    assert classify_direction_pts(10.0, 0.0) == "flat"
    assert classify_direction_pts(10.0, -1.0) == "flat"
    assert classify_direction_pts(10.0, None) == "flat"

    # Phase 1 substance: a per-horizon vol-scaled threshold disagrees with the legacy
    # fixed 0.05%-of-spot cut for the same move — the label is no longer a single uniform cut.
    spot = 100.0
    pts = 0.1
    fixed = classify_direction(pts, spot)          # thr = spot*0.0005 = 0.05 -> "up"
    perhz = classify_direction_pts(pts, 0.55)       # vol-scaled thr 0.55 -> "flat"
    assert fixed == "up"
    assert perhz == "flat"
    assert fixed != perhz


def test_outcome_fill_uses_per_horizon_threshold_all_horizons(tmp_db: EdDB):
    """Stored outcome_Nc matches the per-horizon ATR-scaled formula (not the fixed 0.05% cut),
    across 1c/5c/15c/60c, computed via the same public helpers the writer uses."""
    from math_probabilities import classify_direction_pts
    from movement_target_threshold import (
        load_movement_thresholds_by_horizon_v1,
        threshold_move_pts_for_slug,
    )

    t0 = 1_020_000.0
    t_snap = t0 + 90.0
    atr_v = 1.0
    with tmp_db._connect() as conn:
        conn.execute(
            """
            INSERT INTO snapshots (
                ticker, timeframe, ts_utc, ts_et, et_hour, et_minute, market_session, spot, atr,
                horizon_outcome_schema_version, outcome_filled
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
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
                atr_v,
                HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
            ),
        )
    bars = []
    for i in range(120):
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
    tmp_db.fill_outcomes("SPY", CF, t_snap + 8000.0)

    cfg = load_movement_thresholds_by_horizon_v1()
    anchor_close = 100.0  # last bar with bar_end <= t_snap is bar i=0 (end t0+60)
    with tmp_db._connect() as conn:
        row = conn.execute(
            get_snapshot_sql("tests/test_horizon_bar_outcomes.py:per_horizon"),
            (CF,),
        ).fetchone()
    assert row is not None

    directional_seen = False
    for slug, n_min in (("1c", 1), ("5c", 5), ("15c", 15), ("60c", 60)):
        b = forward_bar_start_utc(t_snap, n_min)
        i_fwd = int(round((b - t0) / 60.0))
        forward_close = 100.0 + 0.1 * float(i_fwd)
        pts = forward_close - anchor_close
        thr = threshold_move_pts_for_slug(slug, anchor_close=anchor_close, atr=atr_v, cfg=cfg)
        expected = classify_direction_pts(pts, thr)
        assert row[f"outcome_{slug}"] == expected, (
            slug,
            pts,
            thr,
            row[f"outcome_{slug}"],
            expected,
        )
        if expected in ("up", "down"):
            directional_seen = True

    # The longest horizon has a large monotone move; the per-horizon path must still emit a
    # directional label (guards against an all-flat regression / classifier wired to a bad scale).
    assert directional_seen
    assert row["outcome_60c"] == "up"
