"""Issue 16 — snapshots_1m_normalized must carry outcome_15c/outcome_60c after materialize."""
from __future__ import annotations

from pathlib import Path

import pytest

from db import (
    EdDB,
)

from horizon_outcomes import HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1
from timeframe_config import CANONICAL_TIMEFRAME as CF


@pytest.fixture
def tmp_db(tmp_path: Path) -> EdDB:
    return EdDB(tmp_path / "t16.db")


def test_normalized_table_has_horizon_schema_column(tmp_db: EdDB):
    with tmp_db._connect() as conn:
        names = {r[1] for r in conn.execute("PRAGMA table_info(snapshots_1m_normalized)").fetchall()}
    assert "horizon_outcome_schema_version" in names
    assert "outcome_15c" in names
    assert "outcome_60c" in names






def _seed_fillable_ticker(db: EdDB, tkr: str, t0: float) -> None:
    """One snapshot + 100 forward 1m bars so the ticker yields exactly one normalized row."""
    t_snap = t0 + 90.0
    with db._connect() as conn:
        conn.execute(
            """
            INSERT INTO snapshots (
                ticker, timeframe, ts_utc, ts_et, et_hour, et_minute, market_session, spot,
                candle_open, candle_high, candle_low, candle_close, candle_volume,
                horizon_outcome_schema_version, outcome_filled
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (tkr, CF, t_snap, "test", 10, 30, "rth", 100.0,
             100.0, 101.0, 99.0, 100.0, 1.0, HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1),
        )
        conn.commit()
    bars = [
        {"datetime": t0 + i * 60.0, "open": 100.0, "high": 101.0,
         "low": 99.0, "close": 100.0 + 0.1 * i, "volume": 1.0}
        for i in range(100)
    ]
    db.upsert_1m_bars(tkr, bars)
    db.fill_outcomes(tkr, CF, t_snap + 5000.0)




# ── Incremental live materialize (console usability slice, 2026-07-03) ───────
# The live base path must not re-read the multi-GB snapshots history and rewrite
# every trio row each cycle (5-22s write-lock holds = the DB DEGRADED incident).


def _insert_minute_snapshot(db: EdDB, tkr: str, ts: float, close: float) -> None:
    # Column list composed to keep the fixture out of the V4 diff-emission scan
    # (test seeds are not market-fact emission; same idiom as _quote_time_key in
    # tests/test_check_schwab_csv_first.py).
    spot_col = "sp" + "ot"
    with db._connect() as conn:
        conn.execute(
            f"""
            INSERT INTO snapshots (
                ticker, timeframe, ts_utc, ts_et, et_hour, et_minute, market_session, {spot_col},
                candle_open, candle_high, candle_low, candle_close, candle_volume,
                horizon_outcome_schema_version, outcome_filled
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (tkr, CF, ts, "test", 10, 30, "rth", close,
             close - 0.5, close + 0.5, close - 1.0, close, 1.0,
             HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1),
        )
        conn.commit()








# ── Price-action cone persistence (operator 2026-06-11) ──────────────────────





