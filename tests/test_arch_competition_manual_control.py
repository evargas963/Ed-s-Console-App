"""manual_control manifest ↔ promotion-record cross-reference (Finding BB)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from arch_competition.exceptions import ManualGovernanceError
from arch_competition.manual_control import (
    MANUAL_PROMOTE_CASCADE_INTENT,
    manual_promote_to_active_explicit,
)
from tests.test_manual_governance import _minimal_governed_files


def _load_promotion_record(model_dir: Path) -> dict:
    path = model_dir / "arch_competition" / "1c" / "SPY" / "promotion_decision.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _save_promotion_record(model_dir: Path, record: dict) -> None:
    path = model_dir / "arch_competition" / "1c" / "SPY" / "promotion_decision.json"
    path.write_text(json.dumps(record), encoding="utf-8")


def test_manual_promote_requires_lineage_feature_cache_key_in_record(tmp_path: Path):
    _minimal_governed_files(tmp_path, cascade_ok=True)
    record = _load_promotion_record(tmp_path)
    ref = dict(record.get("evaluation_manifest_reference") or {})
    ref.pop("lineage_feature_cache_key", None)
    record["evaluation_manifest_reference"] = ref
    _save_promotion_record(tmp_path, record)
    with pytest.raises(ManualGovernanceError, match="lineage_feature_cache_key required"):
        manual_promote_to_active_explicit(
            tmp_path,
            "SPY",
            "1c",
            target_architecture="cascade",
            operator_id="op1",
            manual_intent=MANUAL_PROMOTE_CASCADE_INTENT,
        )


def test_manual_promote_requires_ml_horizon_slug_in_record_reference(tmp_path: Path):
    _minimal_governed_files(tmp_path, cascade_ok=True)
    record = _load_promotion_record(tmp_path)
    ref = dict(record.get("evaluation_manifest_reference") or {})
    ref.pop("ml_horizon_slug", None)
    record["evaluation_manifest_reference"] = ref
    _save_promotion_record(tmp_path, record)
    with pytest.raises(ManualGovernanceError, match="ml_horizon_slug required"):
        manual_promote_to_active_explicit(
            tmp_path,
            "SPY",
            "1c",
            target_architecture="cascade",
            operator_id="op1",
            manual_intent=MANUAL_PROMOTE_CASCADE_INTENT,
        )
