"""
Feature contract + ablation audit framework (additive; production similarity unchanged).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from similarity_audit import (
    baseline_feature_contract_v1,
    contract_expected_structural_filter_keys,
    structured_constraints_for_tier,
)
from timeframe_config import CANONICAL_TIMEFRAME


def test_feature_contract_matches_structured_constraints_per_tier():
    ctx = {
        "ticker": "SPY",
        "timeframe": CANONICAL_TIMEFRAME,
        "zone": "z",
        "vwap_side": "above",
        "nearest_above_dist_raw": 1.0,
        "nearest_below_dist_raw": 1.0,
        "nearest_above_dist_bucket": "0-1",
        "nearest_below_dist_bucket": "0-1",
        "n_similar_limit": 500,
        "as_of_ts_utc": None,
    }
    for tier_num in range(1, 6):
        st = structured_constraints_for_tier(tier_num, ctx)
        keys = set((st.get("structural_filters") or {}).keys())
        assert keys == contract_expected_structural_filter_keys(tier_num), (
            tier_num,
            keys,
            contract_expected_structural_filter_keys(tier_num),
        )
    doc = baseline_feature_contract_v1()
    assert doc["schema"] == "similarity_feature_contract_v1"
    assert set(doc["tier_stop"]["outcome_columns"]) == {"outcome_1c", "outcome_5c", "outcome_15c"}


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


