"""
Feature contract + ablation audit framework (additive; production similarity unchanged).
"""
from __future__ import annotations

import json
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
              outcome_1c, outcome_3c, outcome_5c, outcome_8c, outcome_13c, outcome_15c, outcome_60c,
              horizon_outcome_schema_version
            )
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
                "up",
                "up",
                "up",
                3,
            ),
        )


def test_ablation_audit_deterministic_and_structured(tmp_path):
    from db import EdDB

    dbp = tmp_path / "faudit.db"
    db = EdDB(dbp)
    base_ts = 2_000_000_000.0
    with db._connect() as conn:
        _seed_audit_rows(conn, ticker="AUD", base_ts=base_ts, n=35, zone="fa_zone")
        conn.commit()

    from verification.similarity_feature_audit import run_feature_impact_audit

    def run():
        return run_feature_impact_audit(
            db,
            ticker="AUD",
            timeframe=CANONICAL_TIMEFRAME,
            zone="fa_zone",
            vwap_side="above",
            nearest_above_dist=50.0,
            nearest_below_dist=50.0,
            n_similar=500,
        )

    a = run()
    b = run()
    assert a["schema"] == b["schema"] == "similarity_feature_audit_report_v1"
    assert a == b
    assert "ablation_limited_pools" in a
    assert len(a["ablation_limited_pools"]) == 5
    for entry in a["ablation_limited_pools"]:
        assert "ablation_id" in entry
        assert "metrics" in entry
        m = entry["metrics"]
        assert "row_count" in m
        assert "tier_stop_viable" in m
        assert "labeled_counts" in m
        assert "overlap_vs_production_baseline_limited_pool" in entry
    assert "adaptive_shadow_readiness" in a
    assert a["adaptive_shadow_readiness"]["verdict"] in (
        "baseline_acceptable_for_adaptive_shadow",
        "baseline_acceptable_with_cautions",
        "investigate_before_shadow",
    )


def test_bucket_audit_has_schema_and_edges():
    from verification.similarity_feature_audit import audit_bucket_definitions

    b = audit_bucket_definitions()
    assert b["schema"] == "distance_bucket_audit_v1"
    assert b["DIST_BUCKET_EDGES"] == [1.0, 2.0, 5.0]
    assert len(b["assignment_samples"]) >= 5


def test_interaction_audit_symmetry_note_structured():
    from verification.similarity_feature_audit import audit_above_below_symmetry_hint

    h = audit_above_below_symmetry_hint(nearest_above_dist=1.0, nearest_below_dist=-2.5)
    assert h["schema"] == "distance_symmetry_note_v1"
    assert h["above_bucket"] == "0-1"
    assert h["below_bucket"] == "2-5"


def test_regression_issue21_inspect_imports(tmp_path):
    from similarity_audit import build_similar_inspection_bundle
    from db import EdDB

    _ = EdDB(tmp_path / "i21reg.db")
    bundle = build_similar_inspection_bundle([], {"chosen_tier": 3}, max_rows=0)
    assert bundle["schema"] == "similar_set_inspection_v1"


def test_emit_contract_json_roundtrip(tmp_path):
    from verification.similarity_feature_audit import emit_contract_json

    outp = tmp_path / "contract.json"
    emit_contract_json(outp)
    data = json.loads(outp.read_text(encoding="utf-8"))
    assert data["schema"] == "similarity_feature_contract_v1"
    assert data["production_authority"] == "db.EdDB.get_similar_setups"
