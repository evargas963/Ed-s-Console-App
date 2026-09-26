"""Issue 3 — universal bar-based horizon math and DB fill."""
from __future__ import annotations

import math
from pathlib import Path

import pytest

from horizon_outcomes import (
    HORIZON_OUTCOME_SCHEMA_BAR_V1,
    HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
    bar_complete_by_utc,
    forward_bar_start_utc,
    OUTCOME_BAR_SPECS,
)
from db import (
    EdDB,
)
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




def test_fill_outcomes_live_batch_limit_caps_rows_per_call(tmp_db: EdDB, monkeypatch: pytest.MonkeyPatch):
    """Newest-first LIMIT bounds live fill_outcomes (no unbounded 14d scan)."""
    import db as dbmod

    monkeypatch.setattr(dbmod, "FILL_OUTCOMES_LIVE_BATCH_LIMIT", 2)
    t0 = 1_785_506_400.0  # 2026-07-31 10:00 ET
    # Bars first (no snapshots yet) so upsert mutation-refresh cannot pre-fill labels.
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
    with tmp_db._connect() as conn:
        for i in range(5):
            t_snap = t0 + 90.0 + i * 60.0
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
                    30 + i,
                    "rth",
                    100.0,
                    HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1,
                ),
            )
    # Eval far enough that 60c horizons are complete for all five.
    tmp_db.fill_outcomes("SPY", CF, t0 + 90.0 + 4 * 60.0 + 5000.0)
    with tmp_db._connect() as conn:
        n_touched = conn.execute(
            """
            SELECT COUNT(*) AS n FROM snapshots
            WHERE ticker='SPY' AND timeframe=? AND outcome_1c IS NOT NULL
            """,
            (CF,),
        ).fetchone()["n"]
        n_still = conn.execute(
            """
            SELECT COUNT(*) AS n FROM snapshots
            WHERE ticker='SPY' AND timeframe=? AND outcome_filled=0
            """,
            (CF,),
        ).fetchone()["n"]
    # One call with LIMIT 2 fills at most 2 rows; at least 3 remain unfilled.
    assert n_touched <= 2
    assert n_still >= 3


def test_upsert_1m_bars_normalizes_epoch_ms_for_candle_objects_and_dicts(tmp_db: EdDB):
    """2026-06-09 regression: Candle objects with epoch-ms .ts (Schwab quoteTime passthrough)
    were stored raw on an ms grid, so fill_outcomes (seconds grid) matched zero bars all day.
    Both input shapes must land on the canonical whole-minute epoch-seconds grid."""
    from types import SimpleNamespace

    sec_start = 1_785_506_400.0  # 2026-07-31 10:00 ET — already whole-minute, seconds, past in-window (RC-183)
    obj_bar = SimpleNamespace(
        ts=sec_start * 1000.0, open=10.0, high=11.0, low=9.0, close=10.5, volume=5.0
    )
    dict_bar = {
        "datetime": (sec_start + 60.0) * 1000.0,
        "open": 10.5,
        "high": 12.0,
        "low": 10.0,
        "close": 11.5,
        "volume": 7.0,
    }
    n = tmp_db.upsert_1m_bars("SPY", [obj_bar, dict_bar])
    assert n == 2
    with tmp_db._connect() as conn:
        rows = conn.execute(
            "SELECT bar_start_ts_utc, bar_end_ts_utc, close FROM price_bars_1m"
            " WHERE ticker='SPY' ORDER BY bar_start_ts_utc"
        ).fetchall()
    assert [float(r["bar_start_ts_utc"]) for r in rows] == [sec_start, sec_start + 60.0]
    assert all(float(r["bar_end_ts_utc"]) - float(r["bar_start_ts_utc"]) == 60.0 for r in rows)
    assert [float(r["close"]) for r in rows] == [10.5, 11.5]




# ── Phase 1 (horizon-collapse fix): per-horizon vol-scaled outcome threshold ──────






# ── BAR_PERSISTENCE_GAP_TRACE_AND_FIX_V1 — stale-seed guard + explicit window locks ──

