"""
Tier 3 design artifacts — shadow / documentation only; production similarity unchanged.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from timeframe_config import CANONICAL_TIMEFRAME


def _seed_ctx(conn, *, ticker: str, zone: str, vs: str, ts: float, rp: str, vb: str, ms: str) -> None:
    conn.execute(
        """
        INSERT INTO snapshots (
          ticker, timeframe, ts_utc, ts_et, et_hour, et_minute, market_session, spot,
          zone, vwap_side, nearest_above_dist, nearest_below_dist,
          regime_primary, vix_bucket,
          outcome_1c, outcome_5c, outcome_15c, outcome_60c,
          horizon_outcome_schema_version
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            ticker,
            CANONICAL_TIMEFRAME,
            ts,
            "t",
            10,
            30,
            ms,
            100.0,
            zone,
            vs,
            1.0,
            1.0,
            rp,
            vb,
            "up",
            "up",
            "up",
            "up",
            3,
        ),
    )




def test_eddb_has_unchanged_similarity_authority():
    import inspect

    from db import EdDB

    src = inspect.getsource(EdDB.get_similar_setups)
    assert "def get_similar_setups" in src
    # TEST_SYSTEM_REHAB_V2: was `"similarity_tier_stop_viable" in src or "tier_stop" in
    # src` -- "tier_stop" is a bare substring of "similarity_tier_stop_viable", so if
    # the real field were renamed away, an incidental "tier_stop" occurrence anywhere
    # (a comment, an unrelated variable) would still satisfy the OR and hide exactly
    # the "unchanged similarity authority" regression this test claims to catch.
    assert "similarity_tier_stop_viable" in src
