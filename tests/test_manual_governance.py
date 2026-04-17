"""Manual promotion / rollback governance, audit, visibility."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from arch_competition.audit import AUDIT_RECORD_REQUIRED_KEYS, AUDIT_RECORD_SCHEMA_VERSION, build_audit_record
from arch_competition.exceptions import ManualGovernanceError, PromotionGovernanceError
from arch_competition.manual_control import (
    MANUAL_PROMOTE_CASCADE_INTENT,
    MANUAL_PROMOTE_PARALLEL_INTENT,
    MANUAL_ROLLBACK_INTENT,
    assert_active_mutation_only_via_manual_control,
    load_governance_visibility,
    manual_promote_to_active_explicit,
    manual_rollback_to_checkpoint_explicit,
)
from arch_competition.scheduler_integration import evaluation_manifest_path, scheduler_auto_promote_to_active_enabled
from ml_scheduler import _scheduler_auto_promote_to_active


def _dfp():
    return {
        "min_ts_utc": "2020-01-01",
        "max_ts_utc": "2020-06-01",
        "row_count": 1000,
        "table": "snap",
        "timeframe": "1m",
        "ticker": "SPY",
    }


def _write_candidate_manifests(parallel_dir: Path, cascade_dir: Path):
    common = {
        "schema_version": "2",
        "ticker": "SPY",
        "ml_horizon_suffix": "1c",
        "data_fingerprint": _dfp(),
        "training_code_fingerprint": "trainfp_shared",
        "feature_cache_key": "fk_shared",
    }
    (parallel_dir / "scheduler_run_manifest.json").write_text(json.dumps({**common}), encoding="utf-8")
    (cascade_dir / "scheduler_run_manifest.json").write_text(json.dumps({**common}), encoding="utf-8")


def _minimal_governed_files(model_dir: Path, *, cascade_ok: bool = True):
    hz = "1c"
    tku = "SPY"
    pdir = model_dir / "parallel" / tku
    cdir = model_dir / "cascade" / tku
    pdir.mkdir(parents=True)
    cdir.mkdir(parents=True)
    _write_candidate_manifests(pdir, cdir)
    (pdir / "xgb_SPY_1c.pkl").write_bytes(b"x")
    (cdir / "xgb_SPY_1c.pkl").write_bytes(b"y")

    ev = {
        "schema_version": "1",
        "created_at_utc": "2026-01-01T00:00:00+00:00",
        "ticker": "SPY",
        "ml_horizon_slug": "1c",
        "target_column": "outcome_1c",
        "db_path": str(model_dir / "db.sqlite"),
        "parallel_model_dir": str((pdir).resolve()),
        "cascade_model_dir": str((cdir).resolve()),
        "lineage": {
            "feature_cache_key": "fk_shared",
            "data_fingerprint": _dfp(),
            "ml_horizon_suffix": "1c",
            "training_code_fingerprint": "trainfp_shared",
            "canonical_feature_contract_version": "v1",
            "canonical_timeframe": "1m",
        },
        "metrics": {
            "parallel": {"n_rows_scored": 10, "realized_contract_metrics": {}},
            "cascade": {"n_rows_scored": 10, "realized_contract_metrics": {}},
        },
        "rolling_oos_windows": [],
        "architecture_comparison_summary": {},
        "lineage_fingerprints": {},
        "metric_breakdown": {},
    }
    pr = {
        "schema_version": "1",
        "created_at_utc": "2026-01-01T00:00:00+00:00",
        "incumbent_architecture": "parallel",
        "challenger_architecture": "cascade",
        "promotion_decision": "promote_cascade" if cascade_ok else "keep_incumbent",
        "would_promote_challenger": cascade_ok,
        "auto_promote_executed": False,
        "policy": {},
        "reason_codes": [],
        "blocked_promotion_flags": [] if cascade_ok else [{"code": "X", "detail": "y"}],
        "rollback_demotion_ready": True,
        "evaluation_manifest_reference": {
            "evaluation_manifest_schema": "1",
            "ticker": "SPY",
            "ml_horizon_slug": "1c",
            "lineage_feature_cache_key": "fk_shared",
        },
    }
    ed = model_dir / "arch_competition" / hz / tku
    ed.mkdir(parents=True)
    (ed / "evaluation_manifest.json").write_text(json.dumps(ev), encoding="utf-8")
    (ed / "promotion_decision.json").write_text(json.dumps(pr), encoding="utf-8")


def test_scheduler_never_auto_promotes():
    assert scheduler_auto_promote_to_active_enabled() is False
    assert _scheduler_auto_promote_to_active() is False


def test_manual_promote_wrong_intent_fails(tmp_path: Path):
    _minimal_governed_files(tmp_path, cascade_ok=True)
    with pytest.raises(ManualGovernanceError, match="manual_intent"):
        manual_promote_to_active_explicit(
            tmp_path,
            "SPY",
            "1c",
            target_architecture="cascade",
            operator_id="op1",
            manual_intent="WRONG",
        )


def test_manual_promote_cascade_blocked_by_record(tmp_path: Path):
    _minimal_governed_files(tmp_path, cascade_ok=False)
    with pytest.raises(ManualGovernanceError, match="promote_cascade"):
        manual_promote_to_active_explicit(
            tmp_path,
            "SPY",
            "1c",
            target_architecture="cascade",
            operator_id="op1",
            manual_intent=MANUAL_PROMOTE_CASCADE_INTENT,
        )


def test_manual_promote_cascade_success_writes_active_and_audit(tmp_path: Path):
    _minimal_governed_files(tmp_path, cascade_ok=True)
    active = tmp_path / "active" / "SPY"
    active.mkdir(parents=True)
    (active / "old.pkl").write_bytes(b"old")

    out = manual_promote_to_active_explicit(
        tmp_path,
        "SPY",
        "1c",
        target_architecture="cascade",
        operator_id="op1",
        manual_intent=MANUAL_PROMOTE_CASCADE_INTENT,
    )
    assert (active / "xgb_SPY_1c.pkl").read_bytes() == b"y"
    assert (tmp_path / "arch_competition" / "governance_audit.jsonl").is_file()
    assert "checkpoint_id" in out


def test_missing_governed_files_fail_closed(tmp_path: Path):
    with pytest.raises(PromotionGovernanceError, match="missing evaluation manifest"):
        manual_promote_to_active_explicit(
            tmp_path,
            "SPY",
            "1c",
            target_architecture="parallel",
            operator_id="op1",
            manual_intent=MANUAL_PROMOTE_PARALLEL_INTENT,
        )


def test_lineage_mismatch_record_vs_manifest(tmp_path: Path):
    _minimal_governed_files(tmp_path, cascade_ok=True)
    evp = evaluation_manifest_path(tmp_path, "1c", "SPY")
    ev = json.loads(evp.read_text(encoding="utf-8"))
    ev["lineage"]["feature_cache_key"] = "OTHER"
    evp.write_text(json.dumps(ev), encoding="utf-8")
    with pytest.raises(ManualGovernanceError, match="lineage_feature_cache_key"):
        manual_promote_to_active_explicit(
            tmp_path,
            "SPY",
            "1c",
            target_architecture="cascade",
            operator_id="op1",
            manual_intent=MANUAL_PROMOTE_CASCADE_INTENT,
        )


def test_audit_record_schema_stable():
    r = build_audit_record(
        action="manual_promote_attempt",
        outcome="pending",
        operator_id="a",
        ticker="SPY",
        ml_horizon_suffix="1c",
        prior_active_architecture="parallel",
        target_architecture="cascade",
        new_active_architecture=None,
        evaluation_manifest_path="/e",
        promotion_decision_path="/p",
        checkpoint_id="ck",
        detail="",
    )
    assert r["schema_version"] == AUDIT_RECORD_SCHEMA_VERSION
    assert AUDIT_RECORD_REQUIRED_KEYS <= r.keys()


def test_rollback_fails_without_checkpoint(tmp_path: Path):
    with pytest.raises(ManualGovernanceError, match="no rollback checkpoints"):
        manual_rollback_to_checkpoint_explicit(
            tmp_path,
            "SPY",
            "1c",
            operator_id="op1",
            manual_intent=MANUAL_ROLLBACK_INTENT,
        )


def test_load_governance_visibility(tmp_path: Path):
    _minimal_governed_files(tmp_path, cascade_ok=True)
    hz_path = tmp_path / "arch_state.json"
    hz_path.write_text(
        json.dumps({"SPY": {"active_architecture": "parallel", "governed_competition": {"rollback_demotion_ready": True}}}),
        encoding="utf-8",
    )
    v = load_governance_visibility(tmp_path, "1c", ticker="SPY", audit_limit=5)
    assert v["production_default_runtime"] == "parallel"
    assert "recent_audit_actions" in v


def test_assert_active_mutation_guard():
    assert_active_mutation_only_via_manual_control()


def test_no_implicit_promote_without_operator(tmp_path: Path):
    _minimal_governed_files(tmp_path, cascade_ok=True)
    with pytest.raises(ManualGovernanceError, match="operator_id"):
        manual_promote_to_active_explicit(
            tmp_path,
            "SPY",
            "1c",
            target_architecture="cascade",
            operator_id="   ",
            manual_intent=MANUAL_PROMOTE_CASCADE_INTENT,
        )


def test_run_base_models_once_still_parallel_default():
    import inspect
    from ml_predict import run_base_models_once

    assert "parallel_runtime=True" in inspect.getsource(run_base_models_once)


def test_manual_rollback_restores_after_promote(tmp_path: Path):
    _minimal_governed_files(tmp_path, cascade_ok=True)
    active = tmp_path / "active" / "SPY"
    active.mkdir(parents=True)
    (active / "prior.pkl").write_bytes(b"prior")

    manual_promote_to_active_explicit(
        tmp_path,
        "SPY",
        "1c",
        target_architecture="cascade",
        operator_id="op1",
        manual_intent=MANUAL_PROMOTE_CASCADE_INTENT,
    )
    assert (active / "xgb_SPY_1c.pkl").exists()

    manual_rollback_to_checkpoint_explicit(
        tmp_path,
        "SPY",
        "1c",
        operator_id="op2",
        manual_intent=MANUAL_ROLLBACK_INTENT,
    )
    assert (active / "prior.pkl").read_bytes() == b"prior"
