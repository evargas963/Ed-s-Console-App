"""
Governed operational runbook, alert routing, and failure-handling state.

Consumes only approved artifacts: evaluation manifest, promotion record, live drift monitoring,
and governance audit records. Does not promote, rollback, or change production defaults.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ml_horizon import normalize_ml_horizon_slug

from arch_competition.live_drift_monitoring import (
    DRIFT_SEVERITY_CRITICAL,
    DRIFT_SEVERITY_PROMOTION_BLOCKER,
    DRIFT_SEVERITY_ROLLBACK_WATCH,
    DRIFT_SEVERITY_WARNING,
    REASON_BASELINE_MANIFEST_MISSING,
    REASON_CALIBRATION_DRIFT_MATERIAL,
    REASON_DATA_FINGERPRINT_DRIFT,
    REASON_DATA_FINGERPRINT_COMPARE_UNAVAILABLE,
    REASON_EVALUATION_STALE,
    REASON_LINEAGE_INCOMPLETE,
    REASON_MODEL_MANIFEST_STALE,
)

OPERATIONAL_POLICY_SCHEMA_VERSION = "1"
ALERT_ROUTING_SCHEMA_VERSION = "1"

ROUTING_INFO = "info"
ROUTING_OPS = "ops"
ROUTING_URGENT = "urgent"
ROUTING_GOVERNANCE = "governance"

ACTION_REVIEW_GOVERNANCE = "Review governance panel and lineage; do not promote until artifacts valid."
ACTION_REVIEW_ROLLBACK = "Consider rollback checkpoint; verify active vs candidate parity."
ACTION_RETRAIN = "Schedule governed retrain + full evaluation; refresh manifests before promotion."
ACTION_REVIEW_DRIFT = "Review live drift artifact; compare recent slice to baseline manifest."
ACTION_REVIEW_AUDIT = "Review governance_audit.jsonl failure record; retry manual action or escalate."


def operational_policy_artifact_path(model_dir: Path, ml_horizon_slug: str, ticker: str) -> Path:
    hz = str(ml_horizon_slug).strip().lower()
    return model_dir / "arch_competition" / hz / ticker.upper() / "operational_policy_state.json"


def persist_operational_policy_payload(
    model_dir: Path,
    ml_horizon_slug: str,
    ticker: str,
    payload: dict[str, Any],
) -> Path:
    p = operational_policy_artifact_path(model_dir, ml_horizon_slug, ticker)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return p


def _alert_id(suppression_key: str) -> str:
    return hashlib.sha256(suppression_key.encode("utf-8")).hexdigest()[:16]


def _evidence_paths(
    model_dir: Path,
    hz: str,
    tku: str,
    *,
    eval_path: Path | None,
    prom_path: Path | None,
    drift_loaded: bool,
) -> dict[str, Any]:
    from arch_competition.live_drift_monitoring import live_drift_monitoring_artifact_path
    from arch_competition.scheduler_integration import evaluation_manifest_path, promotion_decision_path

    ev = eval_path or evaluation_manifest_path(model_dir, hz, tku)
    pr = prom_path or promotion_decision_path(model_dir, hz, tku)
    out: dict[str, Any] = {
        "evaluation_manifest": str(ev.resolve()) if ev.is_file() else None,
        "promotion_decision": str(pr.resolve()) if pr.is_file() else None,
        "live_drift_monitoring": str(live_drift_monitoring_artifact_path(model_dir, hz, tku).resolve())
        if drift_loaded
        else None,
        "governance_audit_log": str((model_dir / "arch_competition" / "governance_audit.jsonl").resolve()),
        "operational_policy_state": str(operational_policy_artifact_path(model_dir, hz, tku).resolve()),
    }
    return out


def build_operational_policy_payload(
    *,
    model_dir: Path,
    ml_horizon_slug: str,
    ticker: str,
    live_drift_monitoring: dict[str, Any] | None,
    evaluation_manifest: dict[str, Any] | None,
    promotion_record: dict[str, Any] | None,
    recent_audit_records: list[dict[str, Any]],
    evaluation_manifest_path: Path | None = None,
    promotion_decision_path: Path | None = None,
) -> dict[str, Any]:
    """
    Derive operational policy state and alert routing from governed inputs only.

    If ``live_drift_monitoring`` is None, drift-derived conditions are not inferred (explicit unavailable
    for those dimensions in ``drift_dependency``).
    """
    hz = normalize_ml_horizon_slug(ml_horizon_slug)
    tku = ticker.upper()
    now = datetime.now(timezone.utc).isoformat()

    out: dict[str, Any] = {
        "schema_version": OPERATIONAL_POLICY_SCHEMA_VERSION,
        "state": "ok",
        "error": None,
        "last_policy_evaluation_timestamp": now,
        "drift_dependency": {
            "live_drift_monitoring_loaded": live_drift_monitoring is not None,
            "note": "Drift-based flags require build_live_drift_monitoring_payload output; omitting yields partial policy.",
        },
        "operational_policy_state": {},
        "alert_routing": {},
        "runbook_recommendations": [],
        "evidence_references": {},
    }

    if evaluation_manifest is None or promotion_record is None:
        out["state"] = "error"
        out["error"] = "missing evaluation_manifest or promotion_record for governed policy"
        out["operational_policy_state"] = {
            "schema_version": OPERATIONAL_POLICY_SCHEMA_VERSION,
            "state": "error",
            "reason_code": "MISSING_GOVERNED_ARTIFACTS_FOR_POLICY",
            "promotion_frozen": True,
            "rollback_watch_active": False,
            "retraining_required": False,
            "system_degraded": True,
            "system_untrusted": True,
            "active_policy_reasons": [
                {
                    "code": "MISSING_GOVERNED_ARTIFACTS_FOR_POLICY",
                    "source": "operational_policy.build_operational_policy_payload",
                    "evidence": "evaluation_manifest or promotion_record not provided",
                }
            ],
        }
        sk_miss = f"{tku}|{hz}|missing_governed_artifacts_for_policy"
        out["alert_routing"] = {
            "schema_version": ALERT_ROUTING_SCHEMA_VERSION,
            "alerts": [
                {
                    "alert_id": _alert_id(sk_miss),
                    "reason_code": "MISSING_GOVERNED_ARTIFACTS_FOR_POLICY",
                    "severity": DRIFT_SEVERITY_CRITICAL,
                    "routing_class": ROUTING_GOVERNANCE,
                    "recommended_operator_action": ACTION_REVIEW_GOVERNANCE,
                    "evidence_refs": [
                        {
                            "kind": "evaluation_manifest",
                            "path": str(evaluation_manifest_path.resolve()) if evaluation_manifest_path else "",
                        },
                        {
                            "kind": "promotion_decision",
                            "path": str(promotion_decision_path.resolve()) if promotion_decision_path else "",
                        },
                    ],
                    "suppression_key": sk_miss,
                }
            ],
            "dedup_semantics": "suppression_key coalesces alerts per logical condition; UTC-day dedup is consumer responsibility",
        }
        return out

    promotion_frozen = False
    rollback_watch_active = False
    retraining_required = False
    system_degraded = False
    system_untrusted = False
    reasons: list[dict[str, str]] = []
    alerts: list[dict[str, Any]] = []
    runbook: list[dict[str, Any]] = []

    blocked = promotion_record.get("blocked_promotion_flags") or []
    if blocked:
        promotion_frozen = True
        reasons.append(
            {
                "code": "PROMOTION_RECORD_BLOCKED_FLAGS",
                "source": "promotion_decision.json",
                "evidence": str(blocked)[:2000],
            }
        )
        sk = f"{tku}|{hz}|blocked_promotion_flags"
        alerts.append(
            {
                "alert_id": _alert_id(sk),
                "reason_code": "PROMOTION_RECORD_BLOCKED_FLAGS",
                "severity": DRIFT_SEVERITY_PROMOTION_BLOCKER,
                "routing_class": ROUTING_GOVERNANCE,
                "recommended_operator_action": "Resolve blocked_promotion_flags via retrain/eval or policy change before promotion.",
                "evidence_refs": [
                    {
                        "kind": "promotion_decision",
                        "path": str(promotion_decision_path.resolve()) if promotion_decision_path else "",
                    }
                ],
                "suppression_key": sk,
            }
        )
        runbook.append(
            {
                "condition_code": "promotion_blocker",
                "severity": DRIFT_SEVERITY_PROMOTION_BLOCKER,
                "operator_action_recommendation": "Do not promote until blocked flags cleared in new evaluation cycle.",
                "promotion_frozen": True,
                "consider_rollback": False,
                "retraining_required": True,
                "system_mark": "degraded",
            }
        )

    # Audit failures (governed log only)
    for a in recent_audit_records:
        if str(a.get("ticker", "")).upper() != tku:
            continue
        act = str(a.get("action") or "")
        oc = str(a.get("outcome") or "").lower()
        if act.endswith("_failure") or oc in ("failure", "failed"):
            system_degraded = True
            reasons.append(
                {
                    "code": "AUDIT_FAILURE",
                    "source": "governance_audit.jsonl",
                    "evidence": f"action={act} outcome={oc}",
                }
            )
            sk = f"{tku}|{hz}|audit_failure|{act}"
            alerts.append(
                {
                    "alert_id": _alert_id(sk),
                    "reason_code": "MANUAL_GOVERNANCE_ACTION_FAILURE",
                    "severity": DRIFT_SEVERITY_CRITICAL,
                    "routing_class": ROUTING_URGENT,
                    "recommended_operator_action": ACTION_REVIEW_AUDIT,
                    "evidence_refs": [{"kind": "governance_audit", "path": str((model_dir / "arch_competition" / "governance_audit.jsonl").resolve())}],
                    "suppression_key": sk,
                }
            )
            is_rb = "rollback" in act.lower()
            runbook.append(
                {
                    "condition_code": "failed_rollback" if is_rb else "failed_manual_promotion",
                    "severity": "critical",
                    "operator_action_recommendation": ACTION_REVIEW_AUDIT,
                    "promotion_frozen": True,
                    "consider_rollback": is_rb,
                    "retraining_required": False,
                    "system_mark": "degraded",
                }
            )

    drift_loaded = live_drift_monitoring is not None and live_drift_monitoring.get("ok") is True
    ld = live_drift_monitoring or {}

    if live_drift_monitoring is not None and live_drift_monitoring.get("ok") is not True:
        err = live_drift_monitoring.get("error") or ""
        reasons.append(
            {
                "code": "LIVE_DRIFT_MONITORING_NOT_OK",
                "source": "live_drift_monitoring",
                "evidence": err[:2000],
            }
        )
        system_degraded = True
        lds = str((ld.get("live_drift_summary") or {}).get("reason_code") or "")
        if REASON_LINEAGE_INCOMPLETE in err or REASON_BASELINE_MANIFEST_MISSING in err or lds == REASON_BASELINE_MANIFEST_MISSING:
            system_untrusted = True
            promotion_frozen = True
        runbook.append(
            {
                "condition_code": "missing_governed_artifacts_or_lineage",
                "severity": "critical",
                "operator_action_recommendation": ACTION_REVIEW_GOVERNANCE,
                "promotion_frozen": True,
                "consider_rollback": False,
                "retraining_required": False,
                "system_mark": "untrusted",
            }
        )

    if drift_loaded:
        for sig in ld.get("signals") or []:
            sev = str(sig.get("severity") or "")
            rc = str(sig.get("reason_code") or "")
            ev = str(sig.get("evidence") or "")
            src = str(sig.get("source") or "")

            if sev == DRIFT_SEVERITY_PROMOTION_BLOCKER or rc == REASON_DATA_FINGERPRINT_DRIFT:
                promotion_frozen = True
                retraining_required = True
                system_untrusted = rc == REASON_DATA_FINGERPRINT_DRIFT or system_untrusted
            if sev == DRIFT_SEVERITY_ROLLBACK_WATCH or rc == "ROLLBACK_WATCH_COMPOSITE":
                rollback_watch_active = True
            if sev in (DRIFT_SEVERITY_CRITICAL, DRIFT_SEVERITY_WARNING):
                system_degraded = True
            if rc == REASON_DATA_FINGERPRINT_COMPARE_UNAVAILABLE:
                system_untrusted = True
                promotion_frozen = True
            if rc == REASON_CALIBRATION_DRIFT_MATERIAL and sev == DRIFT_SEVERITY_CRITICAL:
                system_untrusted = True
                promotion_frozen = True
            if rc in (REASON_EVALUATION_STALE, REASON_MODEL_MANIFEST_STALE):
                retraining_required = True
                system_degraded = True

            routing = ROUTING_OPS
            if sev in (DRIFT_SEVERITY_PROMOTION_BLOCKER, DRIFT_SEVERITY_ROLLBACK_WATCH):
                routing = ROUTING_GOVERNANCE
            if sev == DRIFT_SEVERITY_CRITICAL and rc in (REASON_DATA_FINGERPRINT_DRIFT, REASON_DATA_FINGERPRINT_COMPARE_UNAVAILABLE):
                routing = ROUTING_URGENT

            sk = f"{tku}|{hz}|{rc}|{sev}"
            alerts.append(
                {
                    "alert_id": _alert_id(sk),
                    "reason_code": rc or "DRIFT_SIGNAL",
                    "severity": sev or DRIFT_SEVERITY_WARNING,
                    "routing_class": routing,
                    "recommended_operator_action": ACTION_REVIEW_DRIFT if "drift" in rc.lower() or "calibration" in rc.lower() else ACTION_RETRAIN,
                    "evidence_refs": [{"kind": "live_drift_monitoring", "path": str(_evidence_paths(model_dir, hz, tku, eval_path=evaluation_manifest_path, prom_path=promotion_decision_path, drift_loaded=True).get("live_drift_monitoring") or "")}],
                    "suppression_key": sk,
                }
            )
            reasons.append({"code": rc, "source": src or "live_drift_monitoring.signals", "evidence": ev[:2000]})

            cond = None
            if rc == REASON_EVALUATION_STALE:
                cond = "stale_evaluation"
            elif rc == REASON_MODEL_MANIFEST_STALE:
                cond = "stale_model"
            elif sev == DRIFT_SEVERITY_ROLLBACK_WATCH or rc == "ROLLBACK_WATCH_COMPOSITE":
                cond = "rollback_watch"
            elif sev == DRIFT_SEVERITY_CRITICAL and rc == REASON_CALIBRATION_DRIFT_MATERIAL:
                cond = "critical_drift"
            elif sev == DRIFT_SEVERITY_PROMOTION_BLOCKER or rc == REASON_DATA_FINGERPRINT_DRIFT:
                cond = "promotion_blocker"
            if cond:
                runbook.append(
                    {
                        "condition_code": cond,
                        "severity": sev or DRIFT_SEVERITY_WARNING,
                        "operator_action_recommendation": ACTION_REVIEW_DRIFT,
                        "promotion_frozen": sev == DRIFT_SEVERITY_PROMOTION_BLOCKER or rc == REASON_DATA_FINGERPRINT_DRIFT,
                        "consider_rollback": cond == "rollback_watch",
                        "retraining_required": rc in (REASON_EVALUATION_STALE, REASON_MODEL_MANIFEST_STALE, REASON_DATA_FINGERPRINT_DRIFT),
                        "system_mark": "untrusted"
                        if (sev == DRIFT_SEVERITY_CRITICAL and rc in (REASON_CALIBRATION_DRIFT_MATERIAL, REASON_DATA_FINGERPRINT_DRIFT))
                        else ("degraded" if sev in (DRIFT_SEVERITY_CRITICAL, DRIFT_SEVERITY_WARNING) else "none"),
                    }
                )

        evf = (ld.get("evaluation_freshness_summary") or {}).get("db_fingerprint_check") or {}
        if evf.get("state") == "unavailable":
            reasons.append(
                {
                    "code": "DB_FINGERPRINT_CHECK_UNAVAILABLE",
                    "source": "live_drift_monitoring",
                    "evidence": str(evf.get("evidence") or ""),
                }
            )
            runbook.append(
                {
                    "condition_code": "insufficient_evidence_monitoring",
                    "severity": "info",
                    "operator_action_recommendation": "Provide ED_CONSOLE_DB or db_path so fingerprint drift can be evaluated.",
                    "promotion_frozen": False,
                    "consider_rollback": False,
                    "retraining_required": False,
                    "system_mark": "none",
                }
            )

        cal = ld.get("calibration_drift_summary") or {}
        if cal.get("state") == "unavailable" and cal.get("reason_code") == "RECENT_SLICE_EVALUATION_DISABLED":
            # Expected when recent slice off — not an error
            pass
        elif cal.get("state") == "unavailable" and cal.get("reason_code") not in (
            "RECENT_SLICE_EVALUATION_DISABLED",
            None,
        ):
            reasons.append(
                {
                    "code": "CALIBRATION_DRIFT_SUMMARY_UNAVAILABLE",
                    "source": "live_drift_monitoring",
                    "evidence": str(cal.get("reason_code") or ""),
                }
            )

    # Lineage: manifest horizon must be present and match request (cross-check)
    mhz_raw = evaluation_manifest.get("ml_horizon_slug")
    if mhz_raw is None or not str(mhz_raw).strip():
        horizon_reason_code = "MANIFEST_HORIZON_MISSING"
        horizon_evidence = "evaluation_manifest.ml_horizon_slug is missing or empty"
        sk_lm = f"{tku}|{hz}|manifest_horizon_missing"
    else:
        mhz = str(mhz_raw).strip().lower()
        if mhz == hz:
            horizon_reason_code = None
        else:
            horizon_reason_code = "MANIFEST_HORIZON_MISMATCH_POLICY"
            horizon_evidence = f"manifest={mhz!r} policy={hz!r}"
            sk_lm = f"{tku}|{hz}|lineage_mismatch_horizon"

    if horizon_reason_code:
        system_untrusted = True
        promotion_frozen = True
        reasons.append(
            {
                "code": horizon_reason_code,
                "source": "evaluation_manifest",
                "evidence": horizon_evidence,
            }
        )
        alerts.append(
            {
                "alert_id": _alert_id(sk_lm),
                "reason_code": horizon_reason_code,
                "severity": DRIFT_SEVERITY_CRITICAL,
                "routing_class": ROUTING_GOVERNANCE,
                "recommended_operator_action": ACTION_REVIEW_GOVERNANCE,
                "evidence_refs": [
                    {
                        "kind": "evaluation_manifest",
                        "path": str(evaluation_manifest_path.resolve()) if evaluation_manifest_path else "",
                    }
                ],
                "suppression_key": sk_lm,
            }
        )
        runbook.append(
            {
                "condition_code": "lineage_mismatch",
                "severity": "critical",
                "operator_action_recommendation": ACTION_REVIEW_GOVERNANCE,
                "promotion_frozen": True,
                "consider_rollback": False,
                "retraining_required": False,
                "system_mark": "untrusted",
            }
        )

    ops = {
        "schema_version": OPERATIONAL_POLICY_SCHEMA_VERSION,
        "state": "ok",
        "promotion_frozen": promotion_frozen,
        "rollback_watch_active": rollback_watch_active,
        "retraining_required": retraining_required,
        "system_degraded": system_degraded,
        "system_untrusted": system_untrusted,
        "active_policy_reasons": reasons,
    }

    out["operational_policy_state"] = ops
    out["alert_routing"] = {
        "schema_version": ALERT_ROUTING_SCHEMA_VERSION,
        "alerts": alerts,
        "dedup_semantics": "Each alert has suppression_key; coalesce notifications by suppression_key per UTC calendar day (consumer responsibility).",
    }
    out["runbook_recommendations"] = runbook
    out["evidence_references"] = _evidence_paths(
        model_dir,
        hz,
        tku,
        eval_path=evaluation_manifest_path,
        prom_path=promotion_decision_path,
        drift_loaded=drift_loaded,
    )

    if live_drift_monitoring is None:
        out["drift_dependency"]["policy_partial"] = True
        out["operational_policy_state"]["note"] = (
            "live_drift_monitoring omitted — drift-based runbook entries not derived; use governance + audit only."
        )

    return out


def build_recent_policy_evaluation_section(
    operational_policy_payload: dict[str, Any],
    *,
    max_alerts: int = 20,
) -> dict[str, Any]:
    """Compact section for governance panel: recent alerts + flags."""
    ar = operational_policy_payload.get("alert_routing") or {}
    alerts = ar.get("alerts") or []
    return {
        "schema_version": "1",
        "last_policy_evaluation_timestamp": operational_policy_payload.get("last_policy_evaluation_timestamp"),
        "recent_alerts_preview": alerts[:max_alerts],
        "flags": {
            "promotion_frozen": (operational_policy_payload.get("operational_policy_state") or {}).get(
                "promotion_frozen"
            ),
            "rollback_watch_active": (operational_policy_payload.get("operational_policy_state") or {}).get(
                "rollback_watch_active"
            ),
            "retraining_required": (operational_policy_payload.get("operational_policy_state") or {}).get(
                "retraining_required"
            ),
            "system_degraded": (operational_policy_payload.get("operational_policy_state") or {}).get(
                "system_degraded"
            ),
            "system_untrusted": (operational_policy_payload.get("operational_policy_state") or {}).get(
                "system_untrusted"
            ),
        },
    }
