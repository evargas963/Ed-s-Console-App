"""
Adaptive shadow similarity — analysis-only path; heuristic authority unchanged.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db import EdDB
from timeframe_config import CANONICAL_TIMEFRAME


def _seed_rows(conn, ticker: str, zone: str, n: int, base_ts: float) -> None:
    for i in range(n):
        conn.execute(
            """
            INSERT INTO snapshots (
              ticker, timeframe, ts_utc, ts_et, spot, zone, vwap_side,
              nearest_above_dist, nearest_below_dist,
              outcome_1c, outcome_5c, outcome_15c, outcome_60c,
              horizon_outcome_schema_version
            )
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                ticker,
                CANONICAL_TIMEFRAME,
                base_ts + i * 60,
                "t",
                100.0,
                zone,
                "above" if i % 2 == 0 else "below",
                1.0,
                1.0,
                "up",
                "up",
                "up",
                "up",
                3,
            ),
        )


def test_heuristic_engine_regression_untouched_signature(tmp_path):
    dbp = tmp_path / "ash6.db"
    db = EdDB(dbp)
    with db._connect() as c:
        _seed_rows(c, "SH6", "z6", 10, 3_500_000_000.0)
        c.commit()
    out = db.get_similar_setups(
        "SH6",
        CANONICAL_TIMEFRAME,
        "z6",
        "above",
        1.0,
        1.0,
        5,
        return_trace=False,
    )
    assert isinstance(out, list)
    assert len(out) <= 5


def test_trace_shadow_extension_additive(tmp_path):
    from similarity_audit import merge_trace_with_shadow_extension

    base_trace = {"trace_schema": "similarity_trace_issue21_v1", "chosen_tier": 2}
    merged = merge_trace_with_shadow_extension(base_trace, {"foo": 1})
    assert merged["trace_schema"] == "similarity_trace_issue21_v1"
    assert merged["chosen_tier"] == 2
    assert merged["shadow_extension"]["extension_schema"] == "similarity_trace_shadow_extension_v1"
    assert merged["shadow_extension"]["foo"] == 1

