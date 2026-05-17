"""operational_policy handling for all live_drift_monitoring REASON_* codes."""

from __future__ import annotations

import json
from pathlib import Path

from arch_competition.live_drift_monitoring import (
    DRIFT_SEVERITY_CRITICAL,
    DRIFT_SEVERITY_WARNING,
    REASON_CODE_FINGERPRINT_DRIFT,
    REASON_CONFIDENCE_DRIFT_MATERIAL,
    REASON_MODEL_DIR_UNAVAILABLE,
)
from arch_competition.operational_policy import ROUTING_URGENT, build_operational_policy_payload
from tests.test_operational_policy import _manifest_and_promotion


def test_confidence_drift_critical_freezes_promotion():
    ev, pr = _manifest_and_promotion()
    ld = {
        "ok": True,
        "signals": [
            {
                "severity": DRIFT_SEVERITY_CRITICAL,
                "reason_code": REASON_CONFIDENCE_DRIFT_MATERIAL,
                "evidence": "ece delta",
                "source": "live_drift_monitoring",
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
    assert ops["promotion_frozen"] is True
    assert ops["system_untrusted"] is True
    conds = {r["condition_code"] for r in out["runbook_recommendations"]}
    assert "confidence_drift" in conds
    drift_alerts = [a for a in out["alert_routing"]["alerts"] if a["reason_code"] == REASON_CONFIDENCE_DRIFT_MATERIAL]
    assert drift_alerts[0]["routing_class"] == ROUTING_URGENT


def test_code_fingerprint_drift_sets_retraining():
    ev, pr = _manifest_and_promotion()
    ld = {
        "ok": True,
        "signals": [
            {
                "severity": DRIFT_SEVERITY_WARNING,
                "reason_code": REASON_CODE_FINGERPRINT_DRIFT,
                "evidence": "hash mismatch",
                "source": "live_drift_monitoring",
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
    assert ops["retraining_required"] is True
    assert "code_fingerprint_drift" in {r["condition_code"] for r in out["runbook_recommendations"]}


def test_model_dir_unavailable_untrusted_and_json_blocked_evidence():
    ev, pr = _manifest_and_promotion(blocked=True)
    ld = {
        "ok": True,
        "signals": [
            {
                "severity": DRIFT_SEVERITY_WARNING,
                "reason_code": REASON_MODEL_DIR_UNAVAILABLE,
                "evidence": "missing dir",
                "source": "live_drift_monitoring",
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
    blocked = [r for r in ops["active_policy_reasons"] if r["code"] == "PROMOTION_RECORD_BLOCKED_FLAGS"]
    assert blocked
    parsed = json.loads(blocked[0]["evidence"])
    assert isinstance(parsed, list)
