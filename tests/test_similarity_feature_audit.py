"""
Feature contract + ablation audit framework (additive; production similarity unchanged).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from timeframe_config import CANONICAL_TIMEFRAME




def _seed_audit_rows(conn, *, ticker: str, base_ts: float, n: int, zone: str) -> None:
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
                "test",
                450.0,
                zone,
                "above",
                1.0,
                1.0,
                "up",
                "up",
                "up",
                "up",
                3,
            ),
        )


def test_regression_issue21_inspect_imports(tmp_path):
    from similarity_audit import build_similar_inspection_bundle
    from db import EdDB

    _ = EdDB(tmp_path / "i21reg.db")
    bundle = build_similar_inspection_bundle([], {"chosen_tier": 3}, max_rows=0)
    assert bundle["schema"] == "similar_set_inspection_v1"


