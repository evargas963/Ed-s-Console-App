"""Governed active promotion execution (PR4 P3-3) — shared manual + scheduler path."""
from __future__ import annotations

import contextvars
import json
import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Literal

from ml_horizon import normalize_ml_horizon_slug, outcome_column

from arch_competition.audit import append_audit_record, build_audit_record, governance_audit_log_path
from arch_competition.exceptions import ManualGovernanceError, PromotionGovernanceError
from arch_competition.lineage import validate_parallel_cascade_manifest_lineage
from arch_competition.scheduler_auto_promote_policy import (
    scheduler_auto_promote_require_verify,
    scheduler_auto_promote_to_active_enabled,
    ticker_eligible_for_auto_promote,
)
from arch_competition.scheduler_integration import (
    evaluation_manifest_path,
    promotion_decision_path,
    validate_persisted_governed_artifacts_or_raise,
)

log = logging.getLogger(__name__)

SCHEDULER_AUTO_OPERATOR_ID = "ED_SCHEDULER_AUTO_PROMOTE_V1"

_governed_active_write_token: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "governed_active_write_token",
    default=None,
)


@contextmanager
def governed_active_write_scope(executor_id: str) -> Iterator[None]:
    token = _governed_active_write_token.set(executor_id)
    try:
        yield
    finally:
        _governed_active_write_token.reset(token)


def assert_active_writes_use_governed_executor(caller: str) -> None:
    if _governed_active_write_token.get():
        return
    raise ManualGovernanceError(
        f"{caller}: active/ writes require governed_active_write_scope "
        "(execute_promotion_if_eligible or manual_promote_to_active_explicit)"
    )


def _skip_result(reason: str, **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {
        "executed": False,
        "skipped_reason": reason,
        "checkpoint_id": None,
        "post_promote_verify_passed": None,
        "verify_failed_rolled_back": False,
    }
    out.update(extra)
    return out


def _mark_promotion_record_executed(pr_path: Path) -> None:
    from arch_competition.atomic_io import write_json_file_atomically

    data = json.loads(pr_path.read_text(encoding="utf-8"))
    data["auto_promote_executed"] = True
    write_json_file_atomically(pr_path, data, indent=2)


def _candidate_ensemble_metrics(
    manifest: dict[str, Any], target_architecture: str
) -> tuple[float | None, float | None]:
    """Ensemble eval accuracy + balanced_accuracy for the chosen architecture.

    Single source of truth for the metric BASIS the auto-promote gate decides on
    (xgb+lstm+transformer fused on full RTH), so the gate and the incumbent-score
    stamp use the same number. Returns (None, None) when accuracy is absent/non-numeric.
    """
    metrics = (manifest.get("metrics") or {}).get(target_architecture) or {}
    raw_acc = metrics.get("accuracy")
    raw_bal = metrics.get("balanced_accuracy")
    if raw_acc is None:
        return None, None
    try:
        acc = float(raw_acc)
        bal = float(raw_bal) if raw_bal is not None else None
    except (TypeError, ValueError):
        return None, None
    return acc, bal


def _stamp_active_incumbent_ensemble_score(
    active_ticker_dir: Path,
    tku: str,
    hz: str,
    ensemble_acc: float,
    ensemble_bal: float | None,
) -> None:
    """A2 basis-consistency: overwrite the freshly-promoted active bundle meta's
    ``promotion_score`` / ``balanced_accuracy`` with the ENSEMBLE eval metrics the
    gate decided on.

    Active metas otherwise store the XGB-only ``val_accuracy`` (copied verbatim from
    the candidate xgb meta), while the gate's candidate side reads the ENSEMBLE
    accuracy from the manifest. Without this stamp, generation N+1 compares
    ensemble-vs-xgb-only — systematically biased toward over-promotion. Stamping here
    makes the next generation compare ensemble-vs-ensemble and self-heals the existing
    xgb-only incumbents over one cycle. Must run inside the governed active-write scope.
    """
    from arch_competition.atomic_io import write_json_file_atomically

    meta_path = Path(active_ticker_dir) / f"xgb_{tku}_{hz}_meta.json"
    if not meta_path.is_file():
        return
    data = json.loads(meta_path.read_text(encoding="utf-8"))
    data["promotion_score"] = float(ensemble_acc)
    data["promotion_metric"] = "ensemble_eval_accuracy"
    if ensemble_bal is not None:
        data["balanced_accuracy"] = float(ensemble_bal)
    write_json_file_atomically(meta_path, data, indent=2)


def _auto_promote_score_row_gate(
    manifest: dict[str, Any],
    target_architecture: str,
    src: Path,
    active_ticker_dir: Path,
    tku: str,
    hz: str,
) -> tuple[bool, str]:
    """Workstream A2 — candidate score + rows_used gate on the scheduler auto path.

    Routes the copy-to-active decision through
    ``training_provenance.validate_for_promotion`` so the score check
    (candidate eval-accuracy >= existing active ``promotion_score``) and the
    ``rows_used`` floor actually gate (they were previously never called on the
    auto path; parallel train-success-live refreshed regardless of score).

    Candidate ensemble eval accuracy/balanced_accuracy come from the evaluation
    manifest metrics for the chosen architecture; candidate provenance from the
    candidate bundle; existing provenance from active/. Fail-closed when metrics
    or candidate provenance are missing. ``force_replace_non_compliant`` is
    allowed only when the incumbent is itself non-compliant (e.g. schema-v1).
    Returns (ok, reason).
    """
    from training_provenance import (
        is_provenance_compliant,
        load_provenance,
        validate_for_promotion,
    )

    cand_acc, cand_bal = _candidate_ensemble_metrics(manifest, target_architecture)
    if cand_acc is None:
        return False, f"missing/non-numeric metrics.{target_architecture}.accuracy in evaluation manifest"

    cand_meta = Path(src) / f"xgb_{tku}_{hz}_meta.json"
    cand_prov = load_provenance(cand_meta)
    if cand_prov is None:
        return False, f"missing candidate provenance ({cand_meta.name})"

    existing_prov = load_provenance(Path(active_ticker_dir) / f"xgb_{tku}_{hz}_meta.json")
    force_replace = bool(existing_prov) and not is_provenance_compliant(existing_prov, horizon_slug=hz)

    return validate_for_promotion(
        cand_prov,
        cand_acc,
        existing_provenance=existing_prov,
        balanced_accuracy=cand_bal,
        force_replace_non_compliant=force_replace,
        horizon_slug=hz,
    )


def execute_promotion_if_eligible(
    model_dir: Path,
    ticker: str,
    ml_horizon_slug: str,
    *,
    manifest: dict[str, Any] | None = None,
    promotion_record: dict[str, Any] | None = None,
    target_architecture: Literal["cascade", "parallel"] | None = None,
    operator_id: str | None = None,
    manual_intent: str | None = None,
    scheduler_run_id: str | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    """
    Copy governed candidate artifacts to production active when eligible.

    Manual path: operator_id + manual_intent + explicit target_architecture.
    Scheduler path: scheduler_run_id + env-gated auto-promote from promotion_record.

    Workstream A1 (operator brief 2026-05-29): when ``db_path`` is provided on the
    scheduler (auto) path, a fail-closed per-ticker DATA floor is enforced before any
    copy — the ticker must clear ``training_provenance.meets_per_ticker_data_floor``
    (>=500 labeled rows AND >=5 usable RTH days). Below floor → no copy, recorded skip
    (``data_floor_not_met``). Manual operator promotion is intentionally not gated here.
    """
    from arch_competition.manual_control import (
        MANUAL_PROMOTE_CASCADE_INTENT,
        MANUAL_PROMOTE_PARALLEL_INTENT,
        MANUAL_ROLLBACK_INTENT,
        _canonical_candidate_dirs,
        _clear_promotion_pending,
        _copy_candidate_to_active,
        _load_arch_state,
        _snapshot_active_to_checkpoint,
        _validate_manifest_paths_match_canonical,
        _validate_manifest_record_lineage,
        _write_arch_state,
        _write_promotion_pending,
        manual_rollback_to_checkpoint_explicit,
        scheduler_active_root,
    )

    is_manual = manual_intent is not None
    hz = normalize_ml_horizon_slug(ml_horizon_slug)
    tku = ticker.upper()

    if manifest is None or promotion_record is None:
        manifest, promotion_record = validate_persisted_governed_artifacts_or_raise(model_dir, hz, tku)

    if is_manual:
        if not operator_id or not str(operator_id).strip():
            raise ManualGovernanceError("operator_id is required")
        if target_architecture is None:
            raise ManualGovernanceError("target_architecture required for manual promotion")
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
    else:
        if not scheduler_auto_promote_to_active_enabled():
            return _skip_result("auto_promote_disabled")
        if not ticker_eligible_for_auto_promote(tku):
            return _skip_result("core_only_scope")
        decision = str(promotion_record.get("promotion_decision") or "")
        would_promote = bool(promotion_record.get("would_promote_challenger"))
        blocked = promotion_record.get("blocked_promotion_flags") or []
        if decision == "promote_cascade" and would_promote and not blocked:
            target_architecture = "cascade"
        else:
            # Train-success-live: governed train completes → refresh incumbent parallel in active/.
            target_architecture = "parallel"

    assert target_architecture is not None

    # Workstream A1 — fail-closed per-ticker DATA floor (scheduler/auto path only).
    if not is_manual and db_path:
        from training_cache import db_training_floor_stats
        from training_provenance import meets_per_ticker_data_floor

        label_col = outcome_column(hz)
        floor_stats = db_training_floor_stats(db_path, tku, label_column=label_col)
        floor_ok, floor_reason = meets_per_ticker_data_floor(
            floor_stats["labeled_rows"], floor_stats["usable_days"]
        )
        if not floor_ok:
            append_audit_record(
                model_dir,
                build_audit_record(
                    action="scheduler_auto_promote_skipped",
                    outcome="data_floor_not_met",
                    operator_id=SCHEDULER_AUTO_OPERATOR_ID,
                    ticker=tku,
                    ml_horizon_suffix=hz,
                    prior_active_architecture=None,
                    target_architecture=target_architecture,
                    new_active_architecture=None,
                    evaluation_manifest_path=None,
                    promotion_decision_path=None,
                    checkpoint_id=None,
                    detail=f"data_floor_not_met: {floor_reason}",
                ),
            )
            log.warning(
                "auto-promote skipped %s/%s: data floor not met (%s)", tku, hz, floor_reason
            )
            return _skip_result(
                "data_floor_not_met",
                target_architecture=target_architecture,
                data_floor_reason=floor_reason,
                data_floor_stats=floor_stats,
            )

    _validate_manifest_record_lineage(manifest, promotion_record)
    _validate_manifest_paths_match_canonical(manifest, model_dir, tku)

    parallel_dir, cascade_dir = _canonical_candidate_dirs(model_dir, tku)
    validate_parallel_cascade_manifest_lineage(
        parallel_dir, cascade_dir, ticker=tku, expected_ml_horizon_suffix=hz
    )

    if is_manual and target_architecture == "cascade":
        if promotion_record.get("promotion_decision") != "promote_cascade":
            raise ManualGovernanceError("promotion_decision must be promote_cascade for cascade active promotion")
        if not promotion_record.get("would_promote_challenger"):
            raise ManualGovernanceError("would_promote_challenger must be true for cascade promotion")

    active_root = scheduler_active_root(model_dir, hz)
    active_ticker_dir = (active_root / tku).resolve()
    parallel_dir_r = parallel_dir.resolve()
    cascade_dir_r = cascade_dir.resolve()
    src = cascade_dir_r if target_architecture == "cascade" else parallel_dir_r

    # Workstream A2 — candidate score + rows_used gate (scheduler/auto path only).
    if not is_manual:
        gate_ok, gate_reason = _auto_promote_score_row_gate(
            manifest, target_architecture, src, active_ticker_dir, tku, hz
        )
        if not gate_ok:
            append_audit_record(
                model_dir,
                build_audit_record(
                    action="scheduler_auto_promote_skipped",
                    outcome="promotion_gate_failed",
                    operator_id=SCHEDULER_AUTO_OPERATOR_ID,
                    ticker=tku,
                    ml_horizon_suffix=hz,
                    prior_active_architecture=None,
                    target_architecture=target_architecture,
                    new_active_architecture=None,
                    evaluation_manifest_path=None,
                    promotion_decision_path=None,
                    checkpoint_id=None,
                    detail=f"promotion_gate_failed: {gate_reason}",
                ),
            )
            log.warning(
                "auto-promote skipped %s/%s: score/row gate failed (%s)", tku, hz, gate_reason
            )
            return _skip_result(
                "promotion_gate_failed",
                target_architecture=target_architecture,
                promotion_gate_reason=gate_reason,
            )

    ev_path = evaluation_manifest_path(model_dir, hz, tku)
    pr_path = promotion_decision_path(model_dir, hz, tku)
    ev_s = str(ev_path.resolve())
    pr_s = str(pr_path.resolve())

    prior = _load_arch_state(model_dir, hz).get(tku) or {}
    prior_arch = str(prior.get("active_architecture") or "none")
    audit_operator = operator_id if is_manual else SCHEDULER_AUTO_OPERATOR_ID
    checkpoint_id = f"{hz}_{tku}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    from arch_competition.manual_control import rollback_checkpoints_dir

    ck_dir = rollback_checkpoints_dir(model_dir, hz, tku) / checkpoint_id

    attempt_action = "manual_promote_attempt" if is_manual else "scheduler_auto_promote_attempt"
    append_audit_record(
        model_dir,
        build_audit_record(
            action=attempt_action,
            outcome="pending",
            operator_id=audit_operator,
            ticker=tku,
            ml_horizon_suffix=hz,
            prior_active_architecture=prior_arch,
            target_architecture=target_architecture,
            new_active_architecture=None,
            evaluation_manifest_path=ev_s,
            promotion_decision_path=pr_s,
            checkpoint_id=checkpoint_id,
            detail=f"scheduler_run_id={scheduler_run_id}" if scheduler_run_id else "validation passed; checkpointing",
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

    executor_id = f"manual:{audit_operator}" if is_manual else f"scheduler:{scheduler_run_id or 'auto'}"
    try:
        with governed_active_write_scope(executor_id):
            _snapshot_active_to_checkpoint(active_ticker_dir, ck_dir, prior_arch)
            _copy_candidate_to_active(
                src,
                active_ticker_dir,
                ticker=tku,
                hz=hz,
                model_dir=model_dir,
            )
            # A2 basis-consistency: stamp the new incumbent's promotion_score with the
            # ENSEMBLE eval metrics (active metas otherwise store xgb-only val_accuracy),
            # so generation N+1 compares ensemble-vs-ensemble. Symmetric across auto +
            # manual paths — manual stays ungated (the score/row GATE above is auto-only),
            # but a manually-promoted incumbent must still carry the ensemble basis so the
            # next auto challenger is compared like-for-like.
            ens_acc, ens_bal = _candidate_ensemble_metrics(manifest, target_architecture)
            if ens_acc is not None:
                _stamp_active_incumbent_ensemble_score(
                    active_ticker_dir, tku, hz, ens_acc, ens_bal
                )
    except Exception as e:
        try:
            _clear_promotion_pending(model_dir, hz, tku)
        except ManualGovernanceError:
            pass
        fail_action = "manual_promote_failure" if is_manual else "scheduler_auto_promote_failure"
        append_audit_record(
            model_dir,
            build_audit_record(
                action=fail_action,
                outcome="failure",
                operator_id=audit_operator,
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
        if is_manual:
            raise ManualGovernanceError(f"promotion copy failed: {e}") from e
        return _skip_result("promotion_copy_failed", error=str(e), checkpoint_id=checkpoint_id)

    post_promote_verify_passed: bool | None = None
    verify_failed_rolled_back = False
    if not is_manual and scheduler_auto_promote_require_verify():
        from verify_active_models import verify_single_bundle

        vresult = verify_single_bundle(tku, hz, models_dir=model_dir)
        post_promote_verify_passed = bool(vresult.get("compliant"))
        if not post_promote_verify_passed:
            try:
                manual_rollback_to_checkpoint_explicit(
                    model_dir,
                    tku,
                    hz,
                    operator_id=SCHEDULER_AUTO_OPERATOR_ID,
                    manual_intent=MANUAL_ROLLBACK_INTENT,
                    checkpoint_id=checkpoint_id,
                )
                verify_failed_rolled_back = True
            except ManualGovernanceError as rb_err:
                log.error("verify-fail rollback failed for %s/%s: %s", tku, hz, rb_err)
            _clear_promotion_pending(model_dir, hz, tku)
            append_audit_record(
                model_dir,
                build_audit_record(
                    action="scheduler_auto_promote_verify_failed",
                    outcome="failure",
                    operator_id=SCHEDULER_AUTO_OPERATOR_ID,
                    ticker=tku,
                    ml_horizon_suffix=hz,
                    prior_active_architecture=prior_arch,
                    target_architecture=target_architecture,
                    new_active_architecture=None,
                    evaluation_manifest_path=ev_s,
                    promotion_decision_path=pr_s,
                    checkpoint_id=checkpoint_id,
                    detail=json.dumps(vresult.get("issues") or []),
                ),
            )
            return {
                "executed": False,
                "skipped_reason": "verify_failed",
                "checkpoint_id": checkpoint_id,
                "post_promote_verify_passed": False,
                "verify_failed_rolled_back": verify_failed_rolled_back,
                "verify_issues": vresult.get("issues"),
            }

    state = _load_arch_state(model_dir, hz)
    tick = state.get(tku) if isinstance(state.get(tku), dict) else {}
    tick = dict(tick)
    tick.pop("promotion_pending", None)
    tick["active_architecture"] = target_architecture
    if is_manual:
        tick["manual_promotion"] = {
            "schema_version": "1",
            "operator_id": operator_id,
            "target_architecture": target_architecture,
            "checkpoint_id": checkpoint_id,
            "evaluation_manifest_path": ev_s,
            "promotion_decision_path": pr_s,
        }
    else:
        tick["scheduler_auto_promotion"] = {
            "schema_version": "1",
            "scheduler_run_id": scheduler_run_id,
            "target_architecture": target_architecture,
            "checkpoint_id": checkpoint_id,
            "evaluation_manifest_path": ev_s,
            "promotion_decision_path": pr_s,
        }
    gc = tick.get("governed_competition")
    if isinstance(gc, dict):
        gc = dict(gc)
        gc["production_write_held"] = False
        gc["auto_promote_executed"] = True
        tick["governed_competition"] = gc
    state[tku] = tick
    _write_arch_state(model_dir, hz, state)

    try:
        _mark_promotion_record_executed(pr_path)
    except (OSError, json.JSONDecodeError, PromotionGovernanceError) as e:
        log.warning("could not mark promotion_record auto_promote_executed: %s", e)

    success_action = "manual_promote_success" if is_manual else "scheduler_auto_promote_success"
    append_audit_record(
        model_dir,
        build_audit_record(
            action=success_action,
            outcome="success",
            operator_id=audit_operator,
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
        "executed": True,
        "skipped_reason": None,
        "checkpoint_id": checkpoint_id,
        "active_dir": str(active_ticker_dir),
        "source_dir": str(src),
        "target_architecture": target_architecture,
        "post_promote_verify_passed": post_promote_verify_passed,
        "verify_failed_rolled_back": verify_failed_rolled_back,
        "audit_log": str(governance_audit_log_path(model_dir).resolve()),
    }
