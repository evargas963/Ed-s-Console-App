"""Point 12 remains NOT_PROVEN. Deleting tests that referenced deleted code is not
retirement proof. This file inventories every deleted test/metric from eb41983a
and records whether its responsibility is still required, replaced, or still
depended on without a canonical owner.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LINEAGE = ROOT / "reports" / "point12_deleted_responsibility_lineage.json"

# Live dependents that still name retired horizon_7 / deleted-test responsibilities.
_LIVE_DOC_DEPENDENTS = {
    "docs/UNIVERSAL_TICKER_READINESS_ENFORCEMENT_V1.md": "tools/enforce_universal_ticker_readiness_v1.py",
    "docs/PIPELINE_COMPLETION_MOVEMENT_V1_REPORT.md": "validate_movement_prediction_coverage_v1.py",
    "docs/FINAL_COVERAGE_COMPLETION_REPORT_V1.md": "validate_movement_prediction_coverage_v1.py",
}


def test_lineage_artifact_exists_and_is_honest():
    assert LINEAGE.is_file(), "point-12 lineage artifact missing"
    report = json.loads(LINEAGE.read_text(encoding="utf-8"))
    assert report["verdict"] == "NOT_PROVEN"
    rows = report["deleted_responsibilities"]
    assert len(rows) >= 6
    required = {
        "deleted_symbol",
        "deleted_from",
        "responsibility",
        "still_required",
        "canonical_replacement",
        "live_dependents",
        "classification",
    }
    for row in rows:
        assert required <= set(row)
        if row["still_required"] and not row["canonical_replacement"]:
            assert row["classification"] in {
                "STILL_REQUIRED_NO_CANONICAL_OWNER",
                "STILL_REFERENCED_NOT_RESTORED",
            }
            assert row["live_dependents"], row["deleted_symbol"]


def test_deleted_batch_backfill_sanitizer_not_restored_as_abs_clamp():
    """Invalid spread must stay fail-closed None, not the deleted abs() sanitizer."""
    server = (ROOT / "server.py").read_text(encoding="utf-8")
    assert "raw_spread if raw_spread >= 0.0 else None" in server
    assert "_sanitize_snapshot_dict_for_mvp" not in server
    assert not (ROOT / "tests" / "test_batch_movement_backfill_contract_v1.py").exists()


def test_pred_1c_coverage_responsibility_has_canonical_owner():
    health = (ROOT / "verification" / "daily_health.py").read_text(encoding="utf-8")
    assert "def _snapshot_pred_coverage" in health
    persist = (ROOT / "tests" / "test_pred_1c_horizon_persistence_v1.py").read_text(encoding="utf-8")
    assert "pred_1c_up_prob" in persist


def test_policy_validator_does_not_require_deleted_horizon_7_files():
    src = (ROOT / "tools" / "validate_governed_stack_policy_compliance_v1.py").read_text(encoding="utf-8")
    assert "tools" + "/" + "legacy" + "/" + "horizon_7" not in src.replace("\\", "/")
    import tools.validate_governed_stack_policy_compliance_v1 as v
    assert v.main() == 0


def test_live_docs_still_name_deleted_tools_so_point12_is_not_proven():
    missing_owners = []
    for doc, named in _LIVE_DOC_DEPENDENTS.items():
        text = (ROOT / doc).read_text(encoding="utf-8")
        assert named.split("/")[-1] in text
        tool = ROOT / "tools" / named.split("/")[-1]
        if not tool.is_file():
            missing_owners.append(named)
    assert missing_owners, "if every named tool exists, update the lineage"
    assert not (ROOT / "tools" / "enforce_universal_ticker_readiness_v1.py").exists()
    assert not (ROOT / "tools" / "validate_movement_prediction_coverage_v1.py").exists()
    assert not (ROOT / "tools" / "run_phase9_decision_policy_v1.py").exists()
