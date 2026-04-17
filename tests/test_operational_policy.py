"""Operational runbook policy, alert routing, and failure state — governed inputs only."""
from __future__ import annotations

import json
from pathlib import Path

from arch_competition.governance_visibility import build_governance_panel_payload
from arch_competition.live_drift_monitoring import (
    DRIFT_SEVERITY_CRITICAL,
    DRIFT_SEVERITY_PROMOTION_BLOCKER,
    DRIFT_SEVERITY_ROLLBACK_WATCH,
    REASON_CALIBRATION_DRIFT_MATERIAL,
    REASON_EVALUATION_STALE,
    REASON_MODEL_MANIFEST_STALE,
)
from arch_competition.operational_policy import (
    ALERT_ROUTING_SCHEMA_VERSION,
    OPERATIONAL_POLICY_SCHEMA_VERSION,
    build_operational_policy_payload,
    build_recent_policy_evaluation_section,
)


def _minimal_governed_files_for_panel(model_dir: Path, *, cascade_ok: bool = True) -> None:
    """Mirrors tests.test_governance_dashboard._minimal_governed_files (panel + audit)."""
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
        "trained_at": "2026-01-01T00:00:00+00:00",
        "data_fingerprint": {
            "min_ts_utc": 1577836800.0,
            "max_ts_utc": 1590998400.0,
            "row_count": 1000,
            "table": "snapshots_1m_normalized",
            "timeframe": "1m",
            "ticker": "SPY",
        },
        "training_code_fingerprint": "trainfp_shared",
        "feature_cache_key": "fk_shared",
    }
    (pdir / "scheduler_run_manifest.json").write_text(json.dumps(common), encoding="utf-8")
    (cdir / "scheduler_run_manifest.json").write_text(json.dumps(common), encoding="utf-8")
    ev = {
        "schema_version": "1",
        "created_at_utc": "2026-01-01T00:00:00+00:00",
        "ticker": "SPY",
        "ml_horizon_slug": "1c",
        "target_column": "outcome_1c",
        "db_path": str(model_dir / "db.sqlite"),
        "parallel_model_dir": str(pdir.resolve()),
        "cascade_model_dir": str(cdir.resolve()),
        "lineage": {
            "feature_cache_key": "fk_shared",
            "data_fingerprint": common["data_fingerprint"],
            "ml_horizon_suffix": "1c",
            "training_code_fingerprint": "trainfp_shared",
            "canonical_feature_contract_version": "v1",
            "canonical_timeframe": "1m",
        },
        "confidence_reliability_summary": {"schema_version": "1", "by_architecture": {}},
        "calibration_summary": {"schema_version": "1", "by_architecture": {}},
        "rolling_stability_summary": {"schema_version": "1", "by_architecture": {}},
        "empirical_validation": {"schema_version": "1"},
        "metrics": {
            "parallel": {"n_rows_scored": 10, "calibration_ece": 0.1},
            "cascade": {"n_rows_scored": 10, "calibration_ece": 0.1},
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
        "reason_codes": [{"code": "OK", "detail": ""}] if cascade_ok else [],
        "blocked_promotion_flags": [] if cascade_ok else [{"code": "BLOCK", "detail": "x"}],
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
    (model_dir / "arch_competition" / "governance_audit.jsonl").write_text(
        json.dumps(
            {
                "schema_version": "1",
                "action": "manual_promote_attempt",
                "outcome": "pending",
                "timestamp_utc": "2026-01-01T00:00:00+00:00",
                "operator_id": "t",
                "ticker": "SPY",
                "ml_horizon_suffix": "1c",
                "prior_active_architecture": "parallel",
                "target_architecture": "cascade",
                "new_active_architecture": None,
                "evaluation_manifest_path": "/e",
                "promotion_decision_path": "/p",
                "checkpoint_id": "ck",
                "detail": "",
            }
        )
        + "\n",
        encoding="utf-8",
    )


def _manifest_and_promotion(*, blocked: bool = False, horizon: str = "1c"):
    ev = {
        "schema_version": "1",
        "created_at_utc": "2026-01-01T00:00:00+00:00",
        "ticker": "SPY",
        "ml_horizon_slug": horizon,
        "target_column": "outcome_1c",
        "db_path": "/x",
        "parallel_model_dir": "/p",
        "cascade_model_dir": "/c",
        "lineage": {},
        "metrics": {"parallel": {}, "cascade": {}},
        "rolling_oos_windows": [],
        "architecture_comparison_summary": {},
        "confidence_reliability_summary": {"schema_version": "1", "by_architecture": {}},
        "calibration_summary": {"schema_version": "1"},
        "rolling_stability_summary": {"schema_version": "1", "by_architecture": {}},
        "empirical_validation": {"schema_version": "1"},
        "lineage_fingerprints": {},
        "metric_breakdown": {},
    }
    pr = {
        "schema_version": "1",
        "created_at_utc": "2026-01-01T00:00:00+00:00",
        "incumbent_architecture": "parallel",
        "challenger_architecture": "cascade",
        "promotion_decision": "keep_incumbent",
        "would_promote_challenger": False,
        "auto_promote_executed": False,
        "policy": {},
        "reason_codes": [],
        "blocked_promotion_flags": [{"code": "X"}] if blocked else [],
        "rollback_demotion_ready": False,
        "evaluation_manifest_reference": {},
    }
    return ev, pr


def test_stable_policy_and_alert_schema_keys():
    ev, pr = _manifest_and_promotion()
    out = build_operational_policy_payload(
        model_dir=Path("/tmp"),
        ml_horizon_slug="1c",
        ticker="SPY",
        live_drift_monitoring=None,
        evaluation_manifest=ev,
        promotion_record=pr,
        recent_audit_records=[],
    )
    assert out["schema_version"] == OPERATIONAL_POLICY_SCHEMA_VERSION
    assert out["operational_policy_state"]["schema_version"] == OPERATIONAL_POLICY_SCHEMA_VERSION
    ar = out["alert_routing"]
    assert ar["schema_version"] == ALERT_ROUTING_SCHEMA_VERSION
    assert "dedup_semantics" in ar
    assert "last_policy_evaluation_timestamp" in out
    assert "evidence_references" in out


def test_missing_evidence_error_state():
    out = build_operational_policy_payload(
        model_dir=Path("/tmp"),
        ml_horizon_slug="1c",
        ticker="SPY",
        live_drift_monitoring=None,
        evaluation_manifest=None,
        promotion_record=None,
        recent_audit_records=[],
    )
    assert out["state"] == "error"
    ops = out["operational_policy_state"]
    assert ops["promotion_frozen"] is True
    assert ops["system_degraded"] is True
    assert ops["system_untrusted"] is True
    assert out["alert_routing"]["alerts"]


def test_promotion_blocker_sets_promotion_frozen():
    ev, pr = _manifest_and_promotion(blocked=True)
    out = build_operational_policy_payload(
        model_dir=Path("/tmp"),
        ml_horizon_slug="1c",
        ticker="SPY",
        live_drift_monitoring=None,
        evaluation_manifest=ev,
        promotion_record=pr,
        recent_audit_records=[],
    )
    assert out["operational_policy_state"]["promotion_frozen"] is True
    codes = {r["condition_code"] for r in out["runbook_recommendations"]}
    assert "promotion_blocker" in codes


def test_rollback_watch_active_from_drift_signal():
    ev, pr = _manifest_and_promotion()
    ld = {
        "ok": True,
        "signals": [
            {
                "severity": DRIFT_SEVERITY_ROLLBACK_WATCH,
                "reason_code": "ROLLBACK_WATCH_COMPOSITE",
                "evidence": "x",
                "source": "live_drift",
            }
        ],
    }
    out = build_operational_policy_payload(
        model_dir=Path("/tmp"),
        ml_horizon_slug="1c",
        ticker="SPY",
        live_drift_monitoring=ld,
        evaluation_manifest=ev,
        promotion_record=pr,
        recent_audit_records=[],
    )
    assert out["operational_policy_state"]["rollback_watch_active"] is True
    assert any(r["condition_code"] == "rollback_watch" for r in out["runbook_recommendations"])


def test_critical_calibration_drift_marks_untrusted():
    ev, pr = _manifest_and_promotion()
    ld = {
        "ok": True,
        "signals": [
            {
                "severity": DRIFT_SEVERITY_CRITICAL,
                "reason_code": REASON_CALIBRATION_DRIFT_MATERIAL,
                "evidence": "ece",
                "source": "live_drift",
            }
        ],
    }
    out = build_operational_policy_payload(
        model_dir=Path("/tmp"),
        ml_horizon_slug="1c",
        ticker="SPY",
        live_drift_monitoring=ld,
        evaluation_manifest=ev,
        promotion_record=pr,
        recent_audit_records=[],
    )
    ops = out["operational_policy_state"]
    assert ops["system_untrusted"] is True
    assert ops["promotion_frozen"] is True
    assert ops["system_degraded"] is True


def test_stale_evaluation_requires_retraining():
    ev, pr = _manifest_and_promotion()
    ld = {
        "ok": True,
        "signals": [
            {
                "severity": DRIFT_SEVERITY_PROMOTION_BLOCKER,
                "reason_code": REASON_EVALUATION_STALE,
                "evidence": "age",
                "source": "live_drift",
            }
        ],
    }
    out = build_operational_policy_payload(
        model_dir=Path("/tmp"),
        ml_horizon_slug="1c",
        ticker="SPY",
        live_drift_monitoring=ld,
        evaluation_manifest=ev,
        promotion_record=pr,
        recent_audit_records=[],
    )
    assert out["operational_policy_state"]["retraining_required"] is True
    assert any(r["condition_code"] == "stale_evaluation" for r in out["runbook_recommendations"])


def test_stale_model_requires_retraining():
    ev, pr = _manifest_and_promotion()
    ld = {
        "ok": True,
        "signals": [
            {
                "severity": DRIFT_SEVERITY_PROMOTION_BLOCKER,
                "reason_code": REASON_MODEL_MANIFEST_STALE,
                "evidence": "age",
                "source": "live_drift",
            }
        ],
    }
    out = build_operational_policy_payload(
        model_dir=Path("/tmp"),
        ml_horizon_slug="1c",
        ticker="SPY",
        live_drift_monitoring=ld,
        evaluation_manifest=ev,
        promotion_record=pr,
        recent_audit_records=[],
    )
    assert out["operational_policy_state"]["retraining_required"] is True
    assert any(r["condition_code"] == "stale_model" for r in out["runbook_recommendations"])


def test_policy_evaluation_summary_preview():
    ev, pr = _manifest_and_promotion()
    out = build_operational_policy_payload(
        model_dir=Path("/tmp"),
        ml_horizon_slug="1c",
        ticker="SPY",
        live_drift_monitoring=None,
        evaluation_manifest=ev,
        promotion_record=pr,
        recent_audit_records=[],
    )
    sec = build_recent_policy_evaluation_section(out)
    assert sec["schema_version"] == "1"
    assert sec["last_policy_evaluation_timestamp"] == out["last_policy_evaluation_timestamp"]
    assert "flags" in sec


def test_operational_policy_module_does_not_touch_production_runtime():
    import arch_competition.operational_policy as op

    src = Path(op.__file__).read_text(encoding="utf-8")
    assert "production_default_runtime" not in src
    assert "run_base_models_once" not in src


def test_governance_visibility_consumes_operational_policy(tmp_path: Path):
    _minimal_governed_files_for_panel(tmp_path, cascade_ok=True)
    (tmp_path / "arch_state.json").write_text('{"SPY": {"active_architecture": "parallel"}}', encoding="utf-8")
    p = build_governance_panel_payload(tmp_path, "1c", "SPY", include_live_drift=False)
    assert p["ok"] is True
    assert "operational_policy" in p
    assert p["operational_policy"]["schema_version"] == OPERATIONAL_POLICY_SCHEMA_VERSION
    assert "policy_evaluation_summary" in p
    assert p["policy_evaluation_summary"]["flags"]["promotion_frozen"] is not None


def test_governance_panel_error_path_includes_operational_policy(tmp_path: Path):
    p = build_governance_panel_payload(tmp_path, "1c", "SPY", include_live_drift=False)
    assert p["ok"] is False
    assert p["operational_policy"]["state"] == "error"
    assert p["policy_evaluation_summary"]["flags"]["promotion_frozen"] is True
