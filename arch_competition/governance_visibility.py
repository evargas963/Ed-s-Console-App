"""
Aggregated read-only governance panel payload for UI/diagnostics.

Uses only approved loaders and on-disk artifacts — no ad hoc derivation of governed metrics.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from ml_horizon import normalize_ml_horizon_slug

from arch_competition.audit import load_recent_audit_records
from arch_competition.exceptions import PromotionGovernanceError
from arch_competition.manual_control import (
    MANUAL_PROMOTE_CASCADE_INTENT,
    MANUAL_PROMOTE_PARALLEL_INTENT,
    MANUAL_ROLLBACK_INTENT,
    arch_state_path_for_horizon,
    rollback_checkpoints_dir,
)
from arch_competition.live_drift_monitoring import (
    LIVE_DRIFT_MONITORING_SCHEMA_VERSION,
    build_live_drift_monitoring_payload,
    persist_live_drift_monitoring,
)
from arch_competition.notification_delivery import (
    NOTIFICATION_DELIVERY_RECORD_SCHEMA_VERSION,
    load_notification_delivery_config_from_env,
    notification_delivery_log_path,
    process_notification_deliveries,
    read_recent_notification_delivery_records,
    summarize_notification_config_safe,
)
from arch_competition.operational_policy import (
    OPERATIONAL_POLICY_SCHEMA_VERSION,
    build_operational_policy_payload,
    build_recent_policy_evaluation_section,
    persist_operational_policy_payload,
)
from arch_competition.scheduler_integration import (
    evaluation_manifest_path,
    promotion_decision_path,
    validate_persisted_governed_artifacts_or_raise,
)

GOVERNANCE_PANEL_SCHEMA_VERSION = "1"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_arch_state_ticker(model_dir: Path, ml_horizon_slug: str, ticker: str) -> dict[str, Any]:
    p = arch_state_path_for_horizon(model_dir, ml_horizon_slug)
    if not p.is_file():
        return {}
    try:
        st = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    ent = st.get(ticker.upper())
    return ent if isinstance(ent, dict) else {}


def _rollback_checkpoint_available(model_dir: Path, ml_horizon_slug: str, ticker: str) -> bool:
    base = rollback_checkpoints_dir(model_dir, ml_horizon_slug, ticker)
    if not base.is_dir():
        return False
    for p in base.iterdir():
        if not p.is_dir():
            continue
        cm = p / "checkpoint_manifest.json"
        if not cm.is_file():
            continue
        try:
            m = json.loads(cm.read_text(encoding="utf-8"))
            if not m.get("snapshot_empty"):
                return True
        except Exception:
            continue
    return False


def build_governance_panel_payload(
    model_dir: Path,
    ml_horizon_slug: str,
    ticker: str,
    *,
    audit_limit: int = 40,
    db_path: str | Path | None = None,
    include_live_drift: bool = True,
    include_live_drift_recent_slice: bool = False,
    include_operational_policy: bool = True,
    include_notification_delivery_visibility: bool = True,
    emit_notification_delivery: bool = True,
) -> dict[str, Any]:
    """
    Single payload for the governance visibility panel.

    On missing/invalid governed artifacts, returns ok=False and omits fabricated fields.
    """
    hz = normalize_ml_horizon_slug(ml_horizon_slug)
    tku = ticker.upper()
    base: dict[str, Any] = {
        "schema_version": GOVERNANCE_PANEL_SCHEMA_VERSION,
        "ok": False,
        "error": None,
        "ml_horizon_suffix": hz,
        "ticker": tku,
        "production_default_runtime": "parallel",
        "live_drift_monitoring_schema_version": LIVE_DRIFT_MONITORING_SCHEMA_VERSION,
        "operational_policy_schema_version": OPERATIONAL_POLICY_SCHEMA_VERSION,
        "notification_delivery_schema_version": NOTIFICATION_DELIVERY_RECORD_SCHEMA_VERSION,
    }

    try:
        validate_persisted_governed_artifacts_or_raise(model_dir, hz, tku)
    except PromotionGovernanceError as e:
        base["error"] = str(e)
        base["actions_enabled"] = False
        base["manual_promote_cascade_enabled"] = False
        base["manual_promote_parallel_enabled"] = False
        base["manual_rollback_enabled"] = False
        ld_stub: dict[str, Any] | None = None
        if include_live_drift:
            ld_stub = {
                "schema_version": LIVE_DRIFT_MONITORING_SCHEMA_VERSION,
                "ok": False,
                "error": str(e),
                "live_drift_summary": {"state": "error", "reason_code": "GOVERNED_ARTIFACTS_INVALID"},
            }
            base["live_drift_monitoring"] = ld_stub
        if include_operational_policy:
            op = build_operational_policy_payload(
                model_dir=model_dir,
                ml_horizon_slug=hz,
                ticker=tku,
                live_drift_monitoring=ld_stub if include_live_drift else None,
                evaluation_manifest=None,
                promotion_record=None,
                recent_audit_records=[],
                evaluation_manifest_path=evaluation_manifest_path(model_dir, hz, tku),
                promotion_decision_path=promotion_decision_path(model_dir, hz, tku),
            )
            base["operational_policy"] = op
            base["policy_evaluation_summary"] = build_recent_policy_evaluation_section(op)
            try:
                persist_operational_policy_payload(model_dir, hz, tku, op)
            except OSError:
                pass
            if include_notification_delivery_visibility:
                nd_cfg = load_notification_delivery_config_from_env()
                base["notification_delivery_config_effective"] = summarize_notification_config_safe(nd_cfg)
                if emit_notification_delivery:
                    try:
                        process_notification_deliveries(
                            model_dir,
                            hz,
                            tku,
                            op,
                            config=nd_cfg,
                        )
                    except OSError:
                        pass
                base["recent_notification_deliveries"] = read_recent_notification_delivery_records(
                    model_dir, hz, tku, limit=50
                )
                base["notification_delivery_log_path"] = str(
                    notification_delivery_log_path(model_dir, hz, tku).resolve()
                )
        elif include_notification_delivery_visibility:
            nd_cfg = load_notification_delivery_config_from_env()
            base["notification_delivery_config_effective"] = summarize_notification_config_safe(nd_cfg)
            base["recent_notification_deliveries"] = read_recent_notification_delivery_records(
                model_dir, hz, tku, limit=50
            )
            base["notification_delivery_log_path"] = str(
                notification_delivery_log_path(model_dir, hz, tku).resolve()
            )
        return base

    ev_path = evaluation_manifest_path(model_dir, hz, tku)
    pr_path = promotion_decision_path(model_dir, hz, tku)
    manifest = _read_json(ev_path)
    record = _read_json(pr_path)

    arch_t = _load_arch_state_ticker(model_dir, hz, tku)
    gc = arch_t.get("governed_competition") if isinstance(arch_t.get("governed_competition"), dict) else None

    audits = load_recent_audit_records(model_dir, limit=audit_limit)
    audits_ticker = [a for a in audits if str(a.get("ticker", "")).upper() == tku] if audits else []

    rollback_ok = _rollback_checkpoint_available(model_dir, hz, tku)

    # Manual control eligibility (fail-closed: gated on governed artifacts + policy).
    prom_cascade = bool(
        record.get("would_promote_challenger")
        and record.get("promotion_decision") == "promote_cascade"
    )
    prom_parallel = True  # explicit refresh of parallel stack to active; still requires valid artifacts (above).

    base.update(
        {
            "ok": True,
            "error": None,
            "active_architecture_in_state": arch_t.get("active_architecture"),
            "incumbent_architecture": record.get("incumbent_architecture"),
            "challenger_architecture": record.get("challenger_architecture"),
            "governed_competition": gc,
            "latest_evaluation_timestamp": (gc or {}).get("latest_evaluation_at")
            or manifest.get("created_at_utc"),
            "latest_promotion_decision": record.get("promotion_decision"),
            "would_promote_challenger": record.get("would_promote_challenger"),
            "blocked_promotion_flags": record.get("blocked_promotion_flags"),
            "reason_codes": record.get("reason_codes"),
            "rollback_demotion_ready": (gc or {}).get("rollback_demotion_ready", record.get("rollback_demotion_ready")),
            "manifest_paths": {
                "evaluation_manifest": str(ev_path.resolve()),
                "promotion_decision": str(pr_path.resolve()),
            },
            "lineage_summary": {
                "from_manifest_lineage": manifest.get("lineage"),
                "from_manifest_fingerprints": manifest.get("lineage_fingerprints"),
            },
            "evaluation_manifest_ref": {
                "schema_version": manifest.get("schema_version"),
                "created_at_utc": manifest.get("created_at_utc"),
            },
            "promotion_decision_record_ref": {
                "schema_version": record.get("schema_version"),
                "created_at_utc": record.get("created_at_utc"),
            },
            "recent_audit_actions": audits_ticker or audits,
            "governance_audit_log_path": str((model_dir / "arch_competition" / "governance_audit.jsonl").resolve()),
            "manual_intent_constants": {
                "promote_cascade": MANUAL_PROMOTE_CASCADE_INTENT,
                "promote_parallel": MANUAL_PROMOTE_PARALLEL_INTENT,
                "rollback": MANUAL_ROLLBACK_INTENT,
            },
            "actions_enabled": True,
            "manual_promote_cascade_enabled": prom_cascade,
            "manual_promote_parallel_enabled": prom_parallel,
            "manual_rollback_enabled": rollback_ok,
        }
    )
    if include_live_drift:
        ld = build_live_drift_monitoring_payload(
            model_dir,
            hz,
            tku,
            db_path=db_path,
            include_recent_slice_evaluation=include_live_drift_recent_slice,
        )
        base["live_drift_monitoring"] = ld
        try:
            persist_live_drift_monitoring(model_dir, hz, tku, ld)
        except OSError:
            pass
    if include_operational_policy:
        op_payload = build_operational_policy_payload(
            model_dir=model_dir,
            ml_horizon_slug=hz,
            ticker=tku,
            live_drift_monitoring=base.get("live_drift_monitoring") if include_live_drift else None,
            evaluation_manifest=manifest,
            promotion_record=record,
            recent_audit_records=audits_ticker or audits,
            evaluation_manifest_path=ev_path,
            promotion_decision_path=pr_path,
        )
        base["operational_policy"] = op_payload
        base["policy_evaluation_summary"] = build_recent_policy_evaluation_section(op_payload)
        try:
            persist_operational_policy_payload(model_dir, hz, tku, op_payload)
        except OSError:
            pass
        if include_notification_delivery_visibility:
            nd_cfg = load_notification_delivery_config_from_env()
            base["notification_delivery_config_effective"] = summarize_notification_config_safe(nd_cfg)
            if emit_notification_delivery:
                try:
                    process_notification_deliveries(
                        model_dir,
                        hz,
                        tku,
                        op_payload,
                        config=nd_cfg,
                    )
                except OSError:
                    pass
            base["recent_notification_deliveries"] = read_recent_notification_delivery_records(
                model_dir, hz, tku, limit=50
            )
            base["notification_delivery_log_path"] = str(
                notification_delivery_log_path(model_dir, hz, tku).resolve()
            )
    elif include_notification_delivery_visibility:
        nd_cfg = load_notification_delivery_config_from_env()
        base["notification_delivery_config_effective"] = summarize_notification_config_safe(nd_cfg)
        base["recent_notification_deliveries"] = read_recent_notification_delivery_records(
            model_dir, hz, tku, limit=50
        )
        base["notification_delivery_log_path"] = str(
            notification_delivery_log_path(model_dir, hz, tku).resolve()
        )
    return base


def is_governance_ui_actions_enabled() -> bool:
    """POST /api/governance/* mutations require this env (and localhost unless allow-remote)."""
    import os

    return os.environ.get("ED_GOVERNANCE_UI_ACTIONS", "").strip().lower() in ("1", "true", "yes", "on")


def allow_governance_remote() -> bool:
    import os

    return os.environ.get("ED_GOVERNANCE_ALLOW_REMOTE", "").strip().lower() in ("1", "true", "yes", "on")


def client_may_run_governance_action(host: str | None) -> bool:
    from ops_runner import client_may_trigger

    if allow_governance_remote():
        return True
    return client_may_trigger(host)
