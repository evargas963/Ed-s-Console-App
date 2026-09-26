"""
Adaptive Shadow v2 — strict tier-1 pool + Tier 3 context scoring (shadow only).
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from timeframe_config import CANONICAL_TIMEFRAME


def _insert_row(
    conn,
    *,
    ticker: str,
    zone: str,
    vwap_side: str,
    ts: float,
    nad: float,
    nbd: float,
    regime_primary: str,
    vix_bucket: str,
    market_session: str,
    regime_confidence: str,
) -> None:
    conn.execute(
        """
        INSERT INTO snapshots (
          ticker, timeframe, ts_utc, ts_et, et_hour, et_minute, market_session, spot,
          zone, vwap_side, nearest_above_dist, nearest_below_dist,
          regime_primary, vix_bucket, regime_confidence,
          outcome_1c, outcome_5c, outcome_15c, outcome_60c,
          horizon_outcome_schema_version
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            ticker,
            CANONICAL_TIMEFRAME,
            ts,
            "t",
            10,
            30,
            market_session,
            100.0,
            zone,
            vwap_side,
            nad,
            nbd,
            regime_primary,
            vix_bucket,
            regime_confidence,
            "up",
            "up",
            "up",
            "up",
            3,
        ),
    )


def test_get_similar_setups_untouched():
    from db import EdDB

    src = inspect.getsource(EdDB.get_similar_setups)
    assert "PROGRESSIVE RELAXATION" in src
    assert "Tier 1: zone + vwap_side + both distance buckets" in src
