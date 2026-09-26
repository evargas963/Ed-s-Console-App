"""
Aggregated read-only governance panel payload for UI/diagnostics.

Uses only approved loaders and on-disk artifacts — no ad hoc derivation of governed metrics.
"""

from __future__ import annotations

from instrument_identity import ticker_storage_key  # RC-345/F25: one canonical per-instrument identity

import json
import logging
from pathlib import Path
from typing import Any, Callable

from ml_horizon import normalize_ml_horizon_slug

from arch_competition.audit import governance_audit_log_path, load_recent_audit_records
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

# Parallel stack refresh is offered whenever governed artifacts validate (manual_control enforces intent).
MANUAL_PARALLEL_PROMOTE_ELIGIBLE_WHEN_GOVERNED = True

log = logging.getLogger(__name__)


def _record_persistence_failure(base: dict[str, Any], operation: str, error: OSError) -> None:
    log.warning("governance_visibility: %s failed: %s", operation, error)
    failures = base.setdefault("persistence_failures", [])
    failures.append({"operation": operation, "error": str(error)})


def _run_persist_side_effect(base: dict[str, Any], operation: str, fn: Callable[[], Any]) -> None:
    try:
        fn()
    except OSError as e:
        _record_persistence_failure(base, operation, e)


def _load_arch_state_ticker(
    model_dir: Path,
    ml_horizon_slug: str,
    ticker: str,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    p = arch_state_path_for_horizon(model_dir, ml_horizon_slug)
    if not p.is_file():
        return {}, None
    try:
        st = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
        log.warning(
            "_load_arch_state_ticker: arch_state %s unreadable for %s: %s",
            p,
            ticker,
            e,
        )
        return {}, {
            "code": "ARCH_STATE_UNREADABLE",
            "detail": str(e),
            "path": str(p),
        }
    ent = st.get(ticker_storage_key(ticker))
    return (ent if isinstance(ent, dict) else {}), None


def _rollback_checkpoint_available(model_dir: Path, ml_horizon_slug: str, ticker: str) -> bool:
    """Deterministic on every filesystem: checkpoints are scanned in sorted order
    and EVERY manifest is read — a corrupt manifest is always warned about, never
    silently skipped because a valid sibling happened to enumerate first (raw
    iterdir order is readdir/inode-order dependent and differs across platforms,
    which made the corrupt-manifest diagnostic nondeterministic)."""
    base = rollback_checkpoints_dir(model_dir, ml_horizon_slug, ticker)
    if not base.is_dir():
        return False
    available = False
    for p in sorted(base.iterdir()):
        if not p.is_dir():
            continue
        cm = p / "checkpoint_manifest.json"
        if not cm.is_file():
            continue
        try:
            m = json.loads(cm.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            log.warning(
                "governance_visibility: skipping corrupt checkpoint manifest %s: %s",
                cm,
                e,
            )
            continue
        if not m.get("snapshot_empty"):
            available = True
    return available


def _attach_notification_delivery_visibility(
    base: dict[str, Any],
    *,
    model_dir: Path,
    hz: str,
    tku: str,
    op_payload: dict[str, Any] | None,
    emit_notification_delivery: bool,
) -> None:
    nd_cfg = load_notification_delivery_config_from_env()
    base["notification_delivery_config_effective"] = summarize_notification_config_safe(nd_cfg)
    if emit_notification_delivery and op_payload is not None:
        _run_persist_side_effect(
            base,
            "process_notification_deliveries",
            lambda: process_notification_deliveries(
                model_dir,
                hz,
                tku,
                op_payload,
                config=nd_cfg,
            ),
        )
    base["recent_notification_deliveries"] = read_recent_notification_delivery_records(
        model_dir, hz, tku, limit=50
    )
    base["notification_delivery_log_path"] = str(
        notification_delivery_log_path(model_dir, hz, tku).resolve()
    )


def _attach_operational_policy_sections(
    base: dict[str, Any],
    *,
    model_dir: Path,
    hz: str,
    tku: str,
    include_live_drift: bool,
    ld_payload: dict[str, Any] | None,
    manifest: dict[str, Any] | None,
    record: dict[str, Any] | None,
    recent_audit_records: list[dict[str, Any]],
    persist: bool,
    include_notification_delivery_visibility: bool,
    emit_notification_delivery: bool,
) -> None:
    op = build_operational_policy_payload(
        model_dir=model_dir,
        ml_horizon_slug=hz,
        ticker=tku,
        live_drift_monitoring=ld_payload if include_live_drift else None,
        evaluation_manifest=manifest,
        promotion_record=record,
        recent_audit_records=recent_audit_records,
        evaluation_manifest_path=evaluation_manifest_path(model_dir, hz, tku),
        promotion_decision_path=promotion_decision_path(model_dir, hz, tku),
    )
    base["operational_policy"] = op
    base["policy_evaluation_summary"] = build_recent_policy_evaluation_section(op)
    if persist:
        _run_persist_side_effect(
            base,
            "persist_operational_policy_payload",
            lambda: persist_operational_policy_payload(model_dir, hz, tku, op),
        )
    if include_notification_delivery_visibility:
        _attach_notification_delivery_visibility(
            base,
            model_dir=model_dir,
            hz=hz,
            tku=tku,
            op_payload=op,
            emit_notification_delivery=emit_notification_delivery,
        )


def _prune_empty_persistence_failures(base: dict[str, Any]) -> None:
    if not base.get("persistence_failures"):
        base.pop("persistence_failures", None)


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
    recent_audit_actions contains only records matching the requested ticker (may be empty).
    """
    hz = normalize_ml_horizon_slug(ml_horizon_slug)
    tku = ticker_storage_key(ticker)
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
        "persistence_failures": [],
    }

    try:
        manifest, record = validate_persisted_governed_artifacts_or_raise(model_dir, hz, tku)
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
            _attach_operational_policy_sections(
                base,
                model_dir=model_dir,
                hz=hz,
                tku=tku,
                include_live_drift=include_live_drift,
                ld_payload=ld_stub,
                manifest=None,
                record=None,
                recent_audit_records=[],
                persist=True,
                include_notification_delivery_visibility=include_notification_delivery_visibility,
                emit_notification_delivery=emit_notification_delivery,
            )
        elif include_notification_delivery_visibility:
            _attach_notification_delivery_visibility(
                base,
                model_dir=model_dir,
                hz=hz,
                tku=tku,
                op_payload=None,
                emit_notification_delivery=False,
            )
        _prune_empty_persistence_failures(base)
        return base

    ev_path = evaluation_manifest_path(model_dir, hz, tku)
    pr_path = promotion_decision_path(model_dir, hz, tku)

    arch_t, arch_warning = _load_arch_state_ticker(model_dir, hz, tku)
    if arch_warning is not None:
        base["warnings"] = [arch_warning]
    gc = arch_t.get("governed_competition") if isinstance(arch_t.get("governed_competition"), dict) else None

    audits = load_recent_audit_records(model_dir, limit=audit_limit)
    audits_ticker = [a for a in audits if ticker_storage_key(str(a.get("ticker", ""))) == tku]  # RC-345/F25

    rollback_ok = _rollback_checkpoint_available(model_dir, hz, tku)

    prom_cascade = bool(
        record.get("would_promote_challenger")
        and record.get("promotion_decision") == "promote_cascade"
    )

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
            "recent_audit_actions": audits_ticker,
            "governance_audit_log_path": str(governance_audit_log_path(model_dir).resolve()),
            "manual_intent_constants": {
                "promote_cascade": MANUAL_PROMOTE_CASCADE_INTENT,
                "promote_parallel": MANUAL_PROMOTE_PARALLEL_INTENT,
                "rollback": MANUAL_ROLLBACK_INTENT,
            },
            "actions_enabled": True,
            "manual_promote_cascade_enabled": prom_cascade,
            "manual_promote_parallel_enabled": MANUAL_PARALLEL_PROMOTE_ELIGIBLE_WHEN_GOVERNED,
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
        _run_persist_side_effect(
            base,
            "persist_live_drift_monitoring",
            lambda: persist_live_drift_monitoring(model_dir, hz, tku, ld),
        )
    if include_operational_policy:
        _attach_operational_policy_sections(
            base,
            model_dir=model_dir,
            hz=hz,
            tku=tku,
            include_live_drift=include_live_drift,
            ld_payload=base.get("live_drift_monitoring") if include_live_drift else None,
            manifest=manifest,
            record=record,
            recent_audit_records=audits_ticker,
            persist=True,
            include_notification_delivery_visibility=include_notification_delivery_visibility,
            emit_notification_delivery=emit_notification_delivery,
        )
    elif include_notification_delivery_visibility:
        _attach_notification_delivery_visibility(
            base,
            model_dir=model_dir,
            hz=hz,
            tku=tku,
            op_payload=None,
            emit_notification_delivery=False,
        )
    _prune_empty_persistence_failures(base)
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
