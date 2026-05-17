"""
Explicit operator-controlled promotion to models/active/ and rollback. No scheduler or env-only path.

All mutations require manual_promote_to_active_explicit / manual_rollback_to_checkpoint_explicit with intent strings.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

log = logging.getLogger(__name__)

from ml_horizon import DEFAULT_ML_HORIZON_SLUG, normalize_ml_horizon_slug

from arch_competition.audit import (
    append_audit_record,
    build_audit_record,
    load_recent_audit_records,
    governance_audit_log_path,
)
from arch_competition.exceptions import ManualGovernanceError, PromotionGovernanceError
from arch_competition.lineage import validate_parallel_cascade_manifest_lineage
from arch_competition.scheduler_integration import (
    evaluation_manifest_path,
    promotion_decision_path,
    validate_persisted_governed_artifacts_or_raise,
    arch_competition_ticker_dir,
)

# Caller must pass the exact string (explicit operator intent).
MANUAL_PROMOTE_CASCADE_INTENT = "MANUAL_GOVERNANCE_PROMOTE_CASCADE_EXPLICIT_V1"
MANUAL_PROMOTE_PARALLEL_INTENT = "MANUAL_GOVERNANCE_PROMOTE_PARALLEL_EXPLICIT_V1"
MANUAL_ROLLBACK_INTENT = "MANUAL_GOVERNANCE_ROLLBACK_EXPLICIT_V1"

CONTROL_RECORD_SCHEMA_VERSION = "1"


def scheduler_active_root(model_dir: Path, ml_horizon_slug: str) -> Path:
    su = normalize_ml_horizon_slug(ml_horizon_slug)
    if su == DEFAULT_ML_HORIZON_SLUG:
        return model_dir / "active"
    return model_dir / f"active_{su}"


def arch_state_path_for_horizon(model_dir: Path, ml_horizon_slug: str) -> Path:
    su = normalize_ml_horizon_slug(ml_horizon_slug)
    if su == DEFAULT_ML_HORIZON_SLUG:
        return model_dir / "arch_state.json"
    return model_dir / f"arch_state_{su}.json"


def rollback_checkpoints_dir(model_dir: Path, ml_horizon_slug: str, ticker: str) -> Path:
    return arch_competition_ticker_dir(model_dir, ml_horizon_slug, ticker) / "rollback_checkpoints"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_manifest_record_lineage(manifest: dict[str, Any], record: dict[str, Any]) -> None:
    ref = record.get("evaluation_manifest_reference") or {}
    m_lineage = manifest.get("lineage") or {}
    fk = ref.get("lineage_feature_cache_key")
    if not fk:
        raise ManualGovernanceError(
            "promotion_record.evaluation_manifest_reference.lineage_feature_cache_key required"
        )
    if fk != m_lineage.get("feature_cache_key"):
        raise ManualGovernanceError("lineage_feature_cache_key mismatch between promotion record and manifest")
    hz_m_raw = manifest.get("ml_horizon_slug")
    hz_r_raw = ref.get("ml_horizon_slug")
    if not (hz_m_raw and str(hz_m_raw).strip()):
        raise ManualGovernanceError("manifest.ml_horizon_slug required")
    if not (hz_r_raw and str(hz_r_raw).strip()):
        raise ManualGovernanceError(
            "promotion_record.evaluation_manifest_reference.ml_horizon_slug required"
        )
    if str(hz_m_raw).strip().lower() != str(hz_r_raw).strip().lower():
        raise ManualGovernanceError("ml_horizon mismatch between promotion record and manifest")


def _canonical_candidate_dirs(model_dir: Path, ticker: str) -> tuple[Path, Path]:
    tku = ticker.upper()
    return (model_dir / "parallel" / tku).resolve(), (model_dir / "cascade" / tku).resolve()


def _validate_manifest_paths_match_canonical(manifest: dict[str, Any], model_dir: Path, ticker: str) -> None:
    p_can, c_can = _canonical_candidate_dirs(model_dir, ticker)
    p = Path(str(manifest.get("parallel_model_dir", ""))).resolve()
    c = Path(str(manifest.get("cascade_model_dir", ""))).resolve()
    if p != p_can or c != c_can:
        raise ManualGovernanceError(
            f"evaluation manifest paths must match {p_can} and {c_can} (got {p} / {c})"
        )


def _replace_active_dir_from_source(
    src: Path,
    active_ticker_dir: Path,
    *,
    exclude_names: frozenset[str] = frozenset(),
) -> None:
    """Atomically replace active ticker directory contents from src (staging + os.replace)."""
    parent = active_ticker_dir.parent
    parent.mkdir(parents=True, exist_ok=True)
    staging = parent / f".{active_ticker_dir.name}.staging.tmp"
    backup = parent / f".{active_ticker_dir.name}.old.tmp"

    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    try:
        for f in src.glob("*"):
            if f.is_file() and f.name not in exclude_names:
                shutil.copy2(f, staging / f.name)

        if backup.exists():
            shutil.rmtree(backup)
        if active_ticker_dir.exists():
            os.replace(active_ticker_dir, backup)
        try:
            os.replace(staging, active_ticker_dir)
        except Exception:
            if not active_ticker_dir.exists() and backup.exists():
                os.replace(backup, active_ticker_dir)
            raise
        finally:
            if backup.exists():
                shutil.rmtree(backup, ignore_errors=True)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise


def _copy_candidate_to_active(src: Path, active_ticker_dir: Path) -> None:
    _replace_active_dir_from_source(src, active_ticker_dir)


def _snapshot_active_to_checkpoint(
    active_ticker_dir: Path,
    checkpoint_dir: Path,
    prior_active_architecture: str,
) -> dict[str, Any]:
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    files: list[str] = []
    if active_ticker_dir.is_dir():
        for f in active_ticker_dir.glob("*"):
            if f.is_file():
                shutil.copy2(f, checkpoint_dir / f.name)
                files.append(f.name)
    meta = {
        "files": files,
        "snapshot_empty": len(files) == 0,
        "prior_active_architecture": prior_active_architecture,
    }
    (checkpoint_dir / "checkpoint_manifest.json").write_text(
        json.dumps(meta, indent=2),
        encoding="utf-8",
    )
    return meta


def _load_arch_state(model_dir: Path, hz: str) -> dict[str, Any]:
    p = arch_state_path_for_horizon(model_dir, hz)
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
        quarantine = p.with_suffix(f"{p.suffix}.corrupt.{int(time.time())}")
        try:
            p.rename(quarantine)
        except OSError:
            log.warning("could not quarantine corrupt arch_state at %s", p)
        raise ManualGovernanceError(
            f"arch_state at {p} is corrupt or unreadable ({e}); "
            f"quarantined to {quarantine.name if quarantine.exists() else 'n/a'}; "
            "manual recovery required before further promotions or rollbacks"
        ) from e


def _write_arch_state(model_dir: Path, hz: str, state: dict[str, Any]) -> None:
    from arch_competition.atomic_io import write_json_file_atomically

    p = arch_state_path_for_horizon(model_dir, hz)
    write_json_file_atomically(p, state, indent=2)


def _write_promotion_pending(
    model_dir: Path,
    hz: str,
    tku: str,
    *,
    checkpoint_id: str,
    target_architecture: str,
    prior_active_architecture: str,
) -> None:
    state = _load_arch_state(model_dir, hz)
    tick = dict(state.get(tku) or {}) if isinstance(state.get(tku), dict) else {}
    tick["promotion_pending"] = {
        "schema_version": CONTROL_RECORD_SCHEMA_VERSION,
        "checkpoint_id": checkpoint_id,
        "target_architecture": target_architecture,
        "prior_active_architecture": prior_active_architecture,
    }
    state[tku] = tick
    _write_arch_state(model_dir, hz, state)


def _clear_promotion_pending(model_dir: Path, hz: str, tku: str) -> None:
    state = _load_arch_state(model_dir, hz)
    tick = dict(state.get(tku) or {}) if isinstance(state.get(tku), dict) else {}
    tick.pop("promotion_pending", None)
    state[tku] = tick
    _write_arch_state(model_dir, hz, state)


def manual_promote_to_active_explicit(
    model_dir: Path,
    ticker: str,
    ml_horizon_slug: str,
    *,
    target_architecture: Literal["cascade", "parallel"],
    operator_id: str,
    manual_intent: str,
) -> dict[str, Any]:
    """
    Copy governed candidate artifacts to production active dir after validation + audit.

    Raises:
        ManualGovernanceError, PromotionGovernanceError: fail-closed.
    """
    if not str(operator_id).strip():
        raise ManualGovernanceError("operator_id is required")
    hz = normalize_ml_horizon_slug(ml_horizon_slug)
    tku = ticker.upper()
    ev_path = evaluation_manifest_path(model_dir, hz, tku)
    pr_path = promotion_decision_path(model_dir, hz, tku)

    if target_architecture == "cascade":
        if manual_intent != MANUAL_PROMOTE_CASCADE_INTENT:
            raise ManualGovernanceError(
                f"manual_intent must be exactly {MANUAL_PROMOTE_CASCADE_INTENT!r} for cascade promotion"
            )
    elif target_architecture == "parallel":
        if manual_intent != MANUAL_PROMOTE_PARALLEL_INTENT:
            raise ManualGovernanceError(
                f"manual_intent must be exactly {MANUAL_PROMOTE_PARALLEL_INTENT!r} for parallel promotion"
            )
    else:
        raise ManualGovernanceError("target_architecture must be cascade or parallel")

    manifest, record = validate_persisted_governed_artifacts_or_raise(model_dir, hz, tku)

    _validate_manifest_record_lineage(manifest, record)
    _validate_manifest_paths_match_canonical(manifest, model_dir, tku)

    parallel_dir, cascade_dir = _canonical_candidate_dirs(model_dir, tku)
    validate_parallel_cascade_manifest_lineage(parallel_dir, cascade_dir, ticker=tku, expected_ml_horizon_suffix=hz)

    if target_architecture == "cascade":
        if record.get("promotion_decision") != "promote_cascade":
            raise ManualGovernanceError("promotion_decision must be promote_cascade for cascade active promotion")
        if not record.get("would_promote_challenger"):
            raise ManualGovernanceError("would_promote_challenger must be true for cascade promotion")
    # parallel: explicit intent only; governed artifacts must still validate (lineage + paths).

    active_root = scheduler_active_root(model_dir, hz)
    active_ticker_dir = (active_root / tku).resolve()
    parallel_dir_r = parallel_dir.resolve()
    cascade_dir_r = cascade_dir.resolve()
    src = cascade_dir_r if target_architecture == "cascade" else parallel_dir_r

    prior = _load_arch_state(model_dir, hz).get(tku) or {}
    prior_arch = str(prior.get("active_architecture") or "none")

    checkpoint_id = f"{hz}_{tku}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    ck_dir = rollback_checkpoints_dir(model_dir, hz, tku) / checkpoint_id

    ev_s = str(ev_path.resolve())
    pr_s = str(pr_path.resolve())

    append_audit_record(
        model_dir,
        build_audit_record(
            action="manual_promote_attempt",
            outcome="pending",
            operator_id=operator_id,
            ticker=tku,
            ml_horizon_suffix=hz,
            prior_active_architecture=prior_arch,
            target_architecture=target_architecture,
            new_active_architecture=None,
            evaluation_manifest_path=ev_s,
            promotion_decision_path=pr_s,
            checkpoint_id=checkpoint_id,
            detail="validation passed; checkpointing",
        ),
    )

    _write_promotion_pending(
        model_dir,
        hz,
        tku,
        checkpoint_id=checkpoint_id,
        target_architecture=target_architecture,
        prior_active_architecture=prior_arch,
    )

    try:
        _snapshot_active_to_checkpoint(active_ticker_dir, ck_dir, prior_arch)
        _copy_candidate_to_active(src, active_ticker_dir)
    except Exception as e:
        try:
            _clear_promotion_pending(model_dir, hz, tku)
        except ManualGovernanceError:
            pass
        append_audit_record(
            model_dir,
            build_audit_record(
                action="manual_promote_failure",
                outcome="failure",
                operator_id=operator_id,
                ticker=tku,
                ml_horizon_suffix=hz,
                prior_active_architecture=prior_arch,
                target_architecture=target_architecture,
                new_active_architecture=None,
                evaluation_manifest_path=ev_s,
                promotion_decision_path=pr_s,
                checkpoint_id=checkpoint_id,
                detail=str(e),
            ),
        )
        raise ManualGovernanceError(f"promotion copy failed: {e}") from e

    state = _load_arch_state(model_dir, hz)
    tick = state.get(tku) if isinstance(state.get(tku), dict) else {}
    tick = dict(tick)
    tick.pop("promotion_pending", None)
    tick["active_architecture"] = target_architecture
    tick["manual_promotion"] = {
        "schema_version": CONTROL_RECORD_SCHEMA_VERSION,
        "operator_id": operator_id,
        "target_architecture": target_architecture,
        "checkpoint_id": checkpoint_id,
        "evaluation_manifest_path": ev_s,
        "promotion_decision_path": pr_s,
    }
    state[tku] = tick
    _write_arch_state(model_dir, hz, state)

    append_audit_record(
        model_dir,
        build_audit_record(
            action="manual_promote_success",
            outcome="success",
            operator_id=operator_id,
            ticker=tku,
            ml_horizon_suffix=hz,
            prior_active_architecture=prior_arch,
            target_architecture=target_architecture,
            new_active_architecture=target_architecture,
            evaluation_manifest_path=ev_s,
            promotion_decision_path=pr_s,
            checkpoint_id=checkpoint_id,
            detail="active directory updated",
        ),
    )

    return {
        "control_record_schema": CONTROL_RECORD_SCHEMA_VERSION,
        "checkpoint_id": checkpoint_id,
        "active_dir": str(active_ticker_dir),
        "source_dir": str(src),
        "audit_log": str(governance_audit_log_path(model_dir).resolve()),
    }


def manual_rollback_to_checkpoint_explicit(
    model_dir: Path,
    ticker: str,
    ml_horizon_slug: str,
    *,
    operator_id: str,
    manual_intent: str,
    checkpoint_id: str | None = None,
) -> dict[str, Any]:
    if not str(operator_id).strip():
        raise ManualGovernanceError("operator_id is required")
    if manual_intent != MANUAL_ROLLBACK_INTENT:
        raise ManualGovernanceError(f"manual_intent must be exactly {MANUAL_ROLLBACK_INTENT!r}")
    hz = normalize_ml_horizon_slug(ml_horizon_slug)
    tku = ticker.upper()
    base = rollback_checkpoints_dir(model_dir, hz, tku)

    if not base.is_dir():
        raise ManualGovernanceError(f"no rollback checkpoints directory: {base}")

    if checkpoint_id:
        ck = (base / checkpoint_id).resolve()
        if not ck.is_dir() or not (ck / "checkpoint_manifest.json").is_file():
            raise ManualGovernanceError(f"invalid checkpoint_id: {checkpoint_id}")
    else:
        # latest by name sort (ISO-like prefix)
        cks = sorted([p for p in base.iterdir() if p.is_dir() and (p / "checkpoint_manifest.json").is_file()])
        if not cks:
            raise ManualGovernanceError("no rollback checkpoints available")
        ck = cks[-1]
        checkpoint_id = ck.name

    prior = _load_arch_state(model_dir, hz).get(tku) or {}
    prior_arch = str(prior.get("active_architecture") or "none")

    active_root = scheduler_active_root(model_dir, hz)
    active_ticker_dir = (active_root / tku).resolve()

    ev_path = evaluation_manifest_path(model_dir, hz, tku)
    pr_path = promotion_decision_path(model_dir, hz, tku)
    ev_s = str(ev_path.resolve()) if ev_path.is_file() else None
    pr_s = str(pr_path.resolve()) if pr_path.is_file() else None

    append_audit_record(
        model_dir,
        build_audit_record(
            action="rollback_attempt",
            outcome="pending",
            operator_id=operator_id,
            ticker=tku,
            ml_horizon_suffix=hz,
            prior_active_architecture=prior_arch,
            target_architecture=None,
            new_active_architecture=None,
            evaluation_manifest_path=ev_s,
            promotion_decision_path=pr_s,
            checkpoint_id=checkpoint_id,
            detail="restoring from checkpoint",
        ),
    )

    try:
        meta = _read_json(ck / "checkpoint_manifest.json")
        if meta.get("snapshot_empty"):
            raise ManualGovernanceError(
                "checkpoint has no prior active files; rollback requires a non-empty prior snapshot"
            )
        _replace_active_dir_from_source(
            ck,
            active_ticker_dir,
            exclude_names=frozenset({"checkpoint_manifest.json"}),
        )
    except ManualGovernanceError:
        raise
    except Exception as e:
        append_audit_record(
            model_dir,
            build_audit_record(
                action="rollback_failure",
                outcome="failure",
                operator_id=operator_id,
                ticker=tku,
                ml_horizon_suffix=hz,
                prior_active_architecture=prior_arch,
                target_architecture=None,
                new_active_architecture=None,
                evaluation_manifest_path=ev_s,
                promotion_decision_path=pr_s,
                checkpoint_id=checkpoint_id,
                detail=str(e),
            ),
        )
        raise ManualGovernanceError(f"rollback failed: {e}") from e

    restored_arch = meta.get("prior_active_architecture")
    if not restored_arch:
        raise ManualGovernanceError("checkpoint_manifest missing prior_active_architecture")

    state = _load_arch_state(model_dir, hz)
    tick = state.get(tku) if isinstance(state.get(tku), dict) else {}
    tick = dict(tick)
    tick["active_architecture"] = restored_arch
    tick["manual_rollback"] = {
        "schema_version": CONTROL_RECORD_SCHEMA_VERSION,
        "operator_id": operator_id,
        "checkpoint_id": checkpoint_id,
    }
    state[tku] = tick
    _write_arch_state(model_dir, hz, state)

    append_audit_record(
        model_dir,
        build_audit_record(
            action="rollback_success",
            outcome="success",
            operator_id=operator_id,
            ticker=tku,
            ml_horizon_suffix=hz,
            prior_active_architecture=prior_arch,
            target_architecture=None,
            new_active_architecture=restored_arch,
            evaluation_manifest_path=ev_s,
            promotion_decision_path=pr_s,
            checkpoint_id=checkpoint_id,
            detail="active directory restored from checkpoint",
        ),
    )

    return {
        "checkpoint_id": checkpoint_id,
        "active_dir": str(active_ticker_dir),
        "restored_architecture": restored_arch,
        "audit_log": str(governance_audit_log_path(model_dir).resolve()),
    }


def load_governance_visibility(
    model_dir: Path,
    ml_horizon_slug: str,
    *,
    ticker: str | None = None,
    audit_limit: int = 30,
) -> dict[str, Any]:
    """Diagnostics/UI: arch_state governed fields + recent audit + manifest paths."""
    from arch_competition.scheduler_integration import load_architecture_competition_visibility

    hz = normalize_ml_horizon_slug(ml_horizon_slug)
    vis = load_architecture_competition_visibility(model_dir, hz, ticker=ticker)
    audits = load_recent_audit_records(model_dir, limit=audit_limit)
    out: dict[str, Any] = {
        "schema_version": "1",
        "ml_horizon_suffix": hz,
        "production_default_runtime": "parallel",
        "competition_visibility": vis,
        "recent_audit_actions": audits,
        "audit_log_path": str(governance_audit_log_path(model_dir).resolve()),
    }
    if ticker:
        st = _load_arch_state(model_dir, hz).get(ticker.upper()) or {}
        gc = st.get("governed_competition") if isinstance(st, dict) else None
        out["manual_promotion"] = st.get("manual_promotion")
        out["manual_rollback"] = st.get("manual_rollback")
        out["rollback_readiness"] = bool(gc.get("rollback_demotion_ready")) if isinstance(gc, dict) else None
    return out


def assert_active_mutation_only_via_manual_control(caller: str = "test") -> None:
    """Guards against accidental active/ writes outside manual_control (e.g. scheduler)."""
    from arch_competition.scheduler_integration import scheduler_auto_promote_to_active_enabled

    if scheduler_auto_promote_to_active_enabled():
        raise ManualGovernanceError(f"{caller}: scheduler auto-promote must remain disabled")
