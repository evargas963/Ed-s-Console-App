"""Live drift surveillance: governed baselines, stable schema, no production runtime change."""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest



def _write_minimal_governed(model_dir: Path, *, with_lineage: bool = True):
    hz = "1c"
    tku = "SPY"
    pdir = model_dir / "parallel" / tku
    cdir = model_dir / "cascade" / tku
    pdir.mkdir(parents=True)
    cdir.mkdir(parents=True)
    common = {
        "schema_version": "2",
        "ticker": "SPY",
        "ml_horizon_suffix": "1c",
        "trained_at": "2026-01-15T00:00:00+00:00",
        "data_fingerprint": {
            "min_ts_utc": 1.0,
            "max_ts_utc": 2.0,
            "row_count": 100,
            "table": "snapshots_1m_normalized",
            "timeframe": "1m",
            "ticker": "SPY",
        },
        "training_code_fingerprint": "fp_test",
        "feature_cache_key": "fk",
    }
    (pdir / "scheduler_run_manifest.json").write_text(json.dumps(common), encoding="utf-8")
    (cdir / "scheduler_run_manifest.json").write_text(json.dumps(common), encoding="utf-8")

    lineage = {
        "feature_cache_key": "fk",
        "data_fingerprint": common["data_fingerprint"],
        "ml_horizon_suffix": "1c",
        "training_code_fingerprint": "fp_test",
        "canonical_feature_contract_version": "v1",
        "canonical_timeframe": "1m",
    }
    if not with_lineage:
        lineage = {"feature_cache_key": "fk", "data_fingerprint": common["data_fingerprint"], "ml_horizon_suffix": "1c"}

    ev = {
        "schema_version": "1",
        "created_at_utc": "2026-01-10T00:00:00+00:00",
        "ticker": "SPY",
        "ml_horizon_slug": "1c",
        "target_column": "outcome_1c",
        "db_path": str(model_dir / "db.sqlite"),
        "parallel_model_dir": str(pdir.resolve()),
        "cascade_model_dir": str(cdir.resolve()),
        "lineage": lineage,
        "metrics": {
            "parallel": {"n_rows_scored": 100, "calibration_ece": 0.08},
            "cascade": {"n_rows_scored": 100, "calibration_ece": 0.09},
        },
        "rolling_oos_windows": [],
        "architecture_comparison_summary": {},
        "confidence_reliability_summary": {
            "schema_version": "1",
            "by_architecture": {
                "parallel": {"confidence_hit_correlation": 0.1},
                "cascade": {"confidence_hit_correlation": 0.1},
            },
        },
        "calibration_summary": {"schema_version": "1", "regime_conditional_ece": {}},
        "rolling_stability_summary": {"schema_version": "1", "by_architecture": {}},
        "empirical_validation": {"schema_version": "1"},
        "lineage_fingerprints": {},
        "metric_breakdown": {},
    }
    pr = {
        "schema_version": "1",
        "created_at_utc": "2026-01-10T00:00:00+00:00",
        "incumbent_architecture": "parallel",
        "challenger_architecture": "cascade",
        "promotion_decision": "keep_incumbent",
        "would_promote_challenger": False,
        "auto_promote_executed": False,
        "policy": {},
        "reason_codes": [],
        "blocked_promotion_flags": [],
        "rollback_demotion_ready": True,
        "evaluation_manifest_reference": {},
    }
    ed = model_dir / "arch_competition" / hz / tku
    ed.mkdir(parents=True)
    (ed / "evaluation_manifest.json").write_text(json.dumps(ev), encoding="utf-8")
    (ed / "promotion_decision.json").write_text(json.dumps(pr), encoding="utf-8")


































def test_live_drift_module_does_not_call_run_unified_stack_ml_once():
    root = Path(__file__).resolve().parents[1] / "arch_competition" / "live_drift_monitoring.py"
    tree = ast.parse(root.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "run_unified_stack_ml_once":
                pytest.fail("live_drift_monitoring must not call run_unified_stack_ml_once")
            if isinstance(node.func, ast.Attribute) and node.func.attr == "run_unified_stack_ml_once":
                pytest.fail("live_drift_monitoring must not call run_unified_stack_ml_once")




