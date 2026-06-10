"""
Governed live drift surveillance: baselines from evaluation manifests + optional recent-window re-eval.

Does not promote, rollback, or change ``run_unified_stack_ml_once`` / production defaults.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ml_horizon import normalize_ml_horizon_slug, outcome_column

from arch_competition.atomic_io import write_json_file_atomically
from arch_competition.eval_runner import run_architecture_pair_evaluation
from arch_competition.exceptions import (
    EvaluationLineageError,
    PromotionGovernanceError,
    PromotionGovernanceInvalidError,
    PromotionGovernanceMissingError,
)
from arch_competition.scheduler_integration import (
    arch_competition_ticker_dir,
    evaluation_manifest_path,
    promotion_decision_path,
    validate_persisted_governed_artifacts_or_raise,
)
from calibration.statistical_integrity import MIN_SAMPLES_STATISTICAL
from training_cache import (
    _normalize_data_fp,
    compute_training_code_fingerprint,
    db_distinct_rth_et_dates_for_ticker,
    db_training_fingerprint,
)

log = logging.getLogger(__name__)

LIVE_DRIFT_MONITORING_SCHEMA_VERSION = "1"

# Stable severity levels for alerts (consumers must not parse free-form strings).
DRIFT_SEVERITY_INFO = "info"
DRIFT_SEVERITY_WARNING = "warning"
DRIFT_SEVERITY_CRITICAL = "critical"
DRIFT_SEVERITY_PROMOTION_BLOCKER = "promotion_blocker"
DRIFT_SEVERITY_ROLLBACK_WATCH = "rollback_watch"

REASON_BASELINE_MANIFEST_MISSING = "GOVERNED_BASELINE_MANIFEST_MISSING"
REASON_BASELINE_MANIFEST_INVALID = "GOVERNED_BASELINE_MANIFEST_INVALID"
REASON_LINEAGE_INCOMPLETE = "LINEAGE_INCOMPLETE_FOR_DRIFT"
REASON_HORIZON_MISMATCH = "HORIZON_MISMATCH_BASELINE_VS_REQUEST"
REASON_DB_PATH_UNAVAILABLE = "DB_PATH_UNAVAILABLE"
REASON_DATA_FINGERPRINT_DRIFT = "DATA_FINGERPRINT_DRIFT_VS_LINEAGE"
REASON_DATA_FINGERPRINT_COMPARE_UNAVAILABLE = "DATA_FINGERPRINT_COMPARE_UNAVAILABLE"
REASON_CODE_FINGERPRINT_DRIFT = "TRAINING_CODE_FINGERPRINT_DRIFT_VS_LINEAGE"
REASON_EVALUATION_STALE = "EVALUATION_MANIFEST_STALE_AGE"
REASON_MODEL_MANIFEST_STALE = "CANDIDATE_MODEL_MANIFEST_STALE_AGE"
REASON_MODEL_MANIFEST_INVALID = "CANDIDATE_MODEL_MANIFEST_INVALID"
REASON_MODEL_DIR_UNAVAILABLE = "MODEL_DIR_UNAVAILABLE"
REASON_RECENT_SLICE_INSUFFICIENT = "RECENT_SLICE_INSUFFICIENT_REALIZED_ROWS"
REASON_RECENT_SLICE_DISABLED = "RECENT_SLICE_EVALUATION_DISABLED"
REASON_RECENT_SLICE_FAILED = "RECENT_SLICE_EVALUATION_FAILED"
REASON_CALIBRATION_DRIFT_MATERIAL = "CALIBRATION_DRIFT_MATERIAL_VS_BASELINE"
REASON_CONFIDENCE_DRIFT_MATERIAL = "CONFIDENCE_RELIABILITY_DRIFT_VS_BASELINE"
REASON_REGIME_SHIFT = "REGIME_CONDITIONAL_CALIBRATION_SHIFT"
REASON_ARCH_BASE_MISMATCH = "ARCHITECTURE_COMPARISON_BASE_MISMATCH"


def _parse_iso_utc(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        t = str(s).replace("Z", "+00:00")
        dt = datetime.fromisoformat(t)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError) as e:
        log.warning("live_drift_monitoring: could not parse iso utc %r: %s", s, e)
        return None


def _age_days_utc(dt: datetime | None, now: datetime | None = None) -> float | None:
    if dt is None:
        return None
    now = now or datetime.now(timezone.utc)
    return max(0.0, (now - dt).total_seconds() / 86400.0)


def _governed_baseline_failure_reason(error: PromotionGovernanceError) -> str:
    if isinstance(error, PromotionGovernanceMissingError):
        return REASON_BASELINE_MANIFEST_MISSING
    if isinstance(error, PromotionGovernanceInvalidError):
        return REASON_BASELINE_MANIFEST_INVALID
    return REASON_BASELINE_MANIFEST_INVALID


def _resolve_db_path(db_path: str | Path | None) -> Path | None:
    if db_path is not None:
        p = Path(db_path)
        if not str(p).strip():
            return None
        return p
    from db import DB_PATH

    if not str(DB_PATH or "").strip():
        return None
    return Path(DB_PATH)


def live_drift_monitoring_artifact_path(model_dir: Path, ml_horizon_slug: str, ticker: str) -> Path:
    return arch_competition_ticker_dir(model_dir, ml_horizon_slug, ticker) / "live_drift_monitoring.json"


def persist_live_drift_monitoring(
    model_dir: Path,
    ml_horizon_slug: str,
    ticker: str,
    payload: dict[str, Any],
) -> Path:
    """Write governed live drift snapshot for UI/diagnostics (file-backed)."""
    p = live_drift_monitoring_artifact_path(model_dir, ml_horizon_slug, ticker)
    write_json_file_atomically(p, payload, indent=2, default=str)
    return p


def build_live_drift_monitoring_payload(
    model_dir: Path,
    ml_horizon_slug: str,
    ticker: str,
    *,
    db_path: str | Path | None = None,
    include_recent_slice_evaluation: bool = False,
    recent_rth_sessions: int = 5,
    evaluation_stale_days_warning: float = 7.0,
    evaluation_stale_days_critical: float = 14.0,
    model_manifest_stale_days_warning: float = 14.0,
    calibration_ece_drift_warning: float = 0.06,
    calibration_ece_drift_critical: float = 0.12,
) -> dict[str, Any]:
    """
    Build stable-schema live drift monitoring payload using governed baselines only.

    Baselines: evaluation manifest + promotion decision + scheduler manifests under candidate dirs.
    Optional recent slice: ``run_architecture_pair_evaluation`` on last N RTH sessions (same lineage contract).

    Raises nothing: returns ``ok: False`` + error on missing prerequisites.
    """
    hz = normalize_ml_horizon_slug(ml_horizon_slug)
    tku = ticker.upper()
    target_column = outcome_column(hz)

    out: dict[str, Any] = {
        "schema_version": LIVE_DRIFT_MONITORING_SCHEMA_VERSION,
        "ok": False,
        "error": None,
        "ml_horizon_suffix": hz,
        "ticker": tku,
        "production_default_runtime": "parallel",
        "signals": [],
        "live_drift_summary": {},
        "calibration_drift_summary": {},
        "confidence_drift_summary": {},
        "model_freshness_summary": {},
        "evaluation_freshness_summary": {},
        "regime_shift_summary": {},
        "promotion_validity_summary": {},
    }

    ev_path = evaluation_manifest_path(model_dir, hz, tku)
    pr_path = promotion_decision_path(model_dir, hz, tku)
    try:
        manifest, prom = validate_persisted_governed_artifacts_or_raise(model_dir, hz, tku)
    except PromotionGovernanceError as e:
        err = str(e)
        log.warning("live_drift_monitoring: governed baseline validation failed: %s", err)
        out["error"] = err
        out["live_drift_summary"] = {
            "state": "error",
            "reason_code": _governed_baseline_failure_reason(e),
        }
        return out

    if normalize_ml_horizon_slug(str(manifest.get("ml_horizon_slug", ""))) != hz:
        out["error"] = "evaluation manifest horizon mismatch"
        out["live_drift_summary"] = {"state": "error", "reason_code": REASON_HORIZON_MISMATCH}
        out["signals"].append(
            {
                "severity": DRIFT_SEVERITY_CRITICAL,
                "reason_code": REASON_HORIZON_MISMATCH,
                "evidence": f"manifest={manifest.get('ml_horizon_slug')!r} request={hz!r}",
                "source": str(ev_path.resolve()),
            }
        )
        return out

    lineage = manifest.get("lineage") or {}
    req_lineage = ("feature_cache_key", "data_fingerprint", "ml_horizon_suffix", "training_code_fingerprint")
    if any(lineage.get(k) in (None, "") for k in req_lineage):
        out["error"] = "incomplete lineage in evaluation manifest"
        out["live_drift_summary"] = {"state": "error", "reason_code": REASON_LINEAGE_INCOMPLETE}
        out["signals"].append(
            {
                "severity": DRIFT_SEVERITY_CRITICAL,
                "reason_code": REASON_LINEAGE_INCOMPLETE,
                "evidence": "missing required lineage keys for drift comparison",
                "source": str(ev_path.resolve()),
            }
        )
        return out

    resolved_db = _resolve_db_path(db_path)
    if resolved_db is None or not resolved_db.is_file():
        fp_current = None
    else:
        fp_current = db_training_fingerprint(str(resolved_db), tku, label_column=target_column)

    fp_lineage = lineage.get("data_fingerprint")
    data_drift: bool | None = False
    if fp_current is not None and fp_lineage is not None:
        try:
            data_drift = _normalize_data_fp(fp_current) != _normalize_data_fp(fp_lineage)
        except (TypeError, ValueError):
            data_drift = None
            out["signals"].append(
                {
                    "severity": DRIFT_SEVERITY_CRITICAL,
                    "reason_code": REASON_DATA_FINGERPRINT_COMPARE_UNAVAILABLE,
                    "evidence": "could not normalize lineage vs DB fingerprint for comparison",
                    "source": "training_cache._normalize_data_fp",
                }
            )
        if data_drift is True:
            out["signals"].append(
                {
                    "severity": DRIFT_SEVERITY_PROMOTION_BLOCKER,
                    "reason_code": REASON_DATA_FINGERPRINT_DRIFT,
                    "evidence": "current DB fingerprint != lineage data_fingerprint",
                    "source": "training_cache.db_training_fingerprint",
                }
            )

    code_now = compute_training_code_fingerprint()
    code_lineage = str(lineage.get("training_code_fingerprint") or "")
    # lineage completeness validated above; empty training_code_fingerprint cannot reach here.
    code_drift = code_now != code_lineage
    if code_drift:
        out["signals"].append(
            {
                "severity": DRIFT_SEVERITY_WARNING,
                "reason_code": REASON_CODE_FINGERPRINT_DRIFT,
                "evidence": "training code fingerprint changed since manifest lineage",
                "source": "training_cache.compute_training_code_fingerprint",
            }
        )

    ev_created = _parse_iso_utc(str(manifest.get("created_at_utc") or ""))
    ev_age = _age_days_utc(ev_created)
    ev_sev = DRIFT_SEVERITY_INFO
    if ev_age is not None:
        if ev_age >= evaluation_stale_days_critical:
            ev_sev = DRIFT_SEVERITY_CRITICAL
        elif ev_age >= evaluation_stale_days_warning:
            ev_sev = DRIFT_SEVERITY_WARNING
    if ev_age is not None and ev_age >= evaluation_stale_days_warning:
        out["signals"].append(
            {
                "severity": ev_sev,
                "reason_code": REASON_EVALUATION_STALE,
                "evidence": f"evaluation manifest age_days={ev_age:.2f}",
                "source": str(ev_path.resolve()),
            }
        )

    par_raw = manifest.get("parallel_model_dir")
    cas_raw = manifest.get("cascade_model_dir")
    par_dir = Path(par_raw) if isinstance(par_raw, (str, Path)) and str(par_raw).strip() else None
    cas_dir = Path(cas_raw) if isinstance(cas_raw, (str, Path)) and str(cas_raw).strip() else None
    model_dirs_ok = (
        par_dir is not None
        and par_dir.is_dir()
        and cas_dir is not None
        and cas_dir.is_dir()
    )
    if not model_dirs_ok:
        missing_dirs: list[str] = []
        if par_dir is None or not par_dir.is_dir():
            missing_dirs.append("parallel")
        if cas_dir is None or not cas_dir.is_dir():
            missing_dirs.append("cascade")
        out["signals"].append(
            {
                "severity": DRIFT_SEVERITY_WARNING,
                "reason_code": REASON_MODEL_DIR_UNAVAILABLE,
                "evidence": f"candidate model_dir unavailable: {', '.join(missing_dirs)}",
                "source": "evaluation_manifest.parallel_model_dir|cascade_model_dir",
            }
        )
    pm_par = (
        par_dir / "scheduler_run_manifest.json"
        if par_dir is not None and par_dir.is_dir()
        else None
    )
    pm_cas = (
        cas_dir / "scheduler_run_manifest.json"
        if cas_dir is not None and cas_dir.is_dir()
        else None
    )
    trained_ts: list[tuple[str, float | None]] = []
    for label, pm in ("parallel", pm_par), ("cascade", pm_cas):
        if pm is None or not pm.is_file():
            trained_ts.append((label, None))
            continue
        try:
            sm = json.loads(pm.read_text(encoding="utf-8"))
            tr = _parse_iso_utc(str(sm.get("trained_at") or ""))
            trained_ts.append((label, _age_days_utc(tr)))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
            log.warning("live_drift_monitoring: invalid scheduler manifest %s: %s", pm, e)
            trained_ts.append((label, None))
            out["signals"].append(
                {
                    "severity": DRIFT_SEVERITY_WARNING,
                    "reason_code": REASON_MODEL_MANIFEST_INVALID,
                    "evidence": str(e),
                    "source": str(pm),
                }
            )

    model_stale = False
    for label, age in trained_ts:
        if age is not None and age >= model_manifest_stale_days_warning:
            model_stale = True
            out["signals"].append(
                {
                    "severity": DRIFT_SEVERITY_WARNING,
                    "reason_code": REASON_MODEL_MANIFEST_STALE,
                    "evidence": f"{label} candidate scheduler_run_manifest trained_at age_days={age:.2f}",
                    "source": "scheduler_run_manifest.json",
                }
            )

    mp = (manifest.get("metrics") or {}).get("parallel") or {}
    mc = (manifest.get("metrics") or {}).get("cascade") or {}
    base_ece_p = mp.get("calibration_ece")
    base_ece_c = mc.get("calibration_ece")
    crp = (manifest.get("confidence_reliability_summary") or {}).get("by_architecture") or {}
    base_conf_p = (crp.get("parallel") or {}).get("confidence_hit_correlation")
    base_conf_c = (crp.get("cascade") or {}).get("confidence_hit_correlation")

    eval_fresh: dict[str, Any] = {
        "state": "ok",
        "baseline_source": str(ev_path.resolve()),
        "evaluation_manifest_created_at_utc": manifest.get("created_at_utc"),
        "age_days": ev_age,
    }
    if fp_current is None:
        eval_fresh["db_fingerprint_check"] = {
            "state": "unavailable",
            "reason_code": REASON_DB_PATH_UNAVAILABLE,
            "evidence": "DB file not found or path unresolved — lineage vs DB drift not computed",
        }
    else:
        eval_fresh["db_fingerprint_check"] = {
            "state": "ok",
            "data_fingerprint_matches_lineage": not data_drift,
        }
    out["evaluation_freshness_summary"] = eval_fresh
    model_freshness: dict[str, Any] = {
        "state": "ok" if model_dirs_ok else "unavailable",
        "parallel_model_dir": str(par_dir.resolve()) if par_dir is not None and par_dir.is_dir() else None,
        "cascade_model_dir": str(cas_dir.resolve()) if cas_dir is not None and cas_dir.is_dir() else None,
        "candidate_trained_age_days": dict(trained_ts),
        "stale_candidate_warning": model_stale,
    }
    if not model_dirs_ok:
        model_freshness["reason_code"] = REASON_MODEL_DIR_UNAVAILABLE
        model_freshness["evidence"] = (
            "evaluation manifest parallel_model_dir and/or cascade_model_dir missing or not a directory"
        )
    out["model_freshness_summary"] = model_freshness
    out["promotion_validity_summary"] = {
        "state": "ok",
        "promotion_decision_source": str(pr_path.resolve()),
        "promotion_decision": prom.get("promotion_decision"),
        "would_promote_challenger": prom.get("would_promote_challenger"),
        "blocked_promotion_flags": prom.get("blocked_promotion_flags"),
        "evaluation_age_days_at_check": ev_age,
        "decay_note": "older evaluations reduce promotion confidence; re-run governed eval for fresh gates",
    }

    regime_base = manifest.get("calibration_summary", {}).get("regime_conditional_ece") or {}
    out["regime_shift_summary"] = {
        "state": "ok",
        "baseline_regime_conditional_ece": regime_base,
        "recent_comparison": None,
        "note": "recent regime comparison requires recent-slice evaluation",
    }

    recent_payload: dict[str, Any] | None = None
    recent_err: str | None = None
    if not include_recent_slice_evaluation:
        out["calibration_drift_summary"] = {
            "state": "unavailable",
            "reason_code": REASON_RECENT_SLICE_DISABLED,
            "baseline_ece_parallel": base_ece_p,
            "baseline_ece_cascade": base_ece_c,
            "evidence": "include_recent_slice_evaluation=False",
        }
        out["confidence_drift_summary"] = {
            "state": "unavailable",
            "reason_code": REASON_RECENT_SLICE_DISABLED,
            "baseline_confidence_correlation_parallel": base_conf_p,
            "baseline_confidence_correlation_cascade": base_conf_c,
        }
    else:
        if resolved_db is None or not resolved_db.is_file():
            out["calibration_drift_summary"] = {
                "state": "unavailable",
                "reason_code": REASON_DB_PATH_UNAVAILABLE,
                "baseline_ece_parallel": base_ece_p,
                "baseline_ece_cascade": base_ece_c,
            }
            out["confidence_drift_summary"] = {"state": "unavailable", "reason_code": REASON_DB_PATH_UNAVAILABLE}
            recent_err = "db unavailable"
        else:
            try:
                dates = db_distinct_rth_et_dates_for_ticker(
                    str(resolved_db), tku, label_column=target_column,
                )
                if len(dates) < recent_rth_sessions:
                    recent_err = "insufficient RTH sessions in DB"
                    out["signals"].append(
                        {
                            "severity": DRIFT_SEVERITY_INFO,
                            "reason_code": REASON_RECENT_SLICE_INSUFFICIENT,
                            "evidence": recent_err,
                            "source": "db_distinct_rth_et_dates_for_ticker",
                        }
                    )
                else:
                    recent_dates = set(dates[-recent_rth_sessions:])
                    recent_payload = run_architecture_pair_evaluation(
                        db_path=str(resolved_db.resolve()),
                        ticker=tku,
                        parallel_model_dir=par_dir,
                        cascade_model_dir=cas_dir,
                        ml_horizon_slug=hz,
                        allowed_et_dates=recent_dates,
                        require_manifest_lineage=True,
                        expected_ml_horizon_suffix=hz,
                    )
            except (
                EvaluationLineageError,
                PromotionGovernanceError,
                OSError,
                ValueError,
                KeyError,
                json.JSONDecodeError,
                sqlite3.Error,
            ) as e:
                log.warning("live_drift_monitoring: recent slice evaluation failed: %s", e)
                recent_err = str(e)
                out["signals"].append(
                    {
                        "severity": DRIFT_SEVERITY_WARNING,
                        "reason_code": REASON_RECENT_SLICE_FAILED,
                        "evidence": recent_err,
                        "source": "run_architecture_pair_evaluation",
                    }
                )

        if recent_payload is not None:
            rp = (recent_payload.get("metrics") or {}).get("parallel") or {}
            rc = (recent_payload.get("metrics") or {}).get("cascade") or {}
            r_ece_p = rp.get("calibration_ece")
            r_ece_c = rc.get("calibration_ece")
            n_recent = rp.get("n_rows_scored")
            if n_recent is not None and int(n_recent) < MIN_SAMPLES_STATISTICAL:
                out["calibration_drift_summary"] = {
                    "state": "unavailable",
                    "reason_code": REASON_RECENT_SLICE_INSUFFICIENT,
                    "evidence": (
                        f"recent slice n_rows_scored={n_recent} "
                        f"(requires >= {MIN_SAMPLES_STATISTICAL})"
                    ),
                    "baseline_ece_parallel": base_ece_p,
                    "baseline_ece_cascade": base_ece_c,
                }
                out["confidence_drift_summary"] = {
                    "state": "unavailable",
                    "reason_code": REASON_RECENT_SLICE_INSUFFICIENT,
                }
            else:
                d_p = (
                    abs(float(r_ece_p) - float(base_ece_p))
                    if r_ece_p is not None and base_ece_p is not None
                    else None
                )
                d_c = (
                    abs(float(r_ece_c) - float(base_ece_c))
                    if r_ece_c is not None and base_ece_c is not None
                    else None
                )
                out["calibration_drift_summary"] = {
                    "state": "ok",
                    "baseline_source": str(ev_path.resolve()),
                    "recent_slice_source": "run_architecture_pair_evaluation",
                    "recent_rth_sessions_used": recent_rth_sessions,
                    "baseline_ece_parallel": base_ece_p,
                    "baseline_ece_cascade": base_ece_c,
                    "recent_ece_parallel": r_ece_p,
                    "recent_ece_cascade": r_ece_c,
                    "abs_delta_ece_parallel": d_p,
                    "abs_delta_ece_cascade": d_c,
                }
                crs_r = (recent_payload.get("confidence_reliability_summary") or {}).get("by_architecture") or {}
                r_cp = (crs_r.get("parallel") or {}).get("confidence_hit_correlation")
                r_cc = (crs_r.get("cascade") or {}).get("confidence_hit_correlation")
                out["confidence_drift_summary"] = {
                    "state": "ok",
                    "baseline_confidence_correlation_parallel": base_conf_p,
                    "baseline_confidence_correlation_cascade": base_conf_c,
                    "recent_confidence_correlation_parallel": r_cp,
                    "recent_confidence_correlation_cascade": r_cc,
                }
                reg_recent = (recent_payload.get("calibration_summary") or {}).get("regime_conditional_ece") or {}
                out["regime_shift_summary"] = {
                    "state": "ok",
                    "baseline_regime_conditional_ece": regime_base,
                    "recent_regime_conditional_ece": reg_recent,
                }

                candidates = [x for x in (d_p, d_c) if x is not None]
                max_d = max(candidates) if candidates else None
                if max_d is not None:
                    if max_d >= calibration_ece_drift_critical:
                        out["signals"].append(
                            {
                                "severity": DRIFT_SEVERITY_CRITICAL,
                                "reason_code": REASON_CALIBRATION_DRIFT_MATERIAL,
                                "evidence": f"max abs delta ECE={max_d:.4f}",
                                "source": "recent_slice_vs_baseline_manifest",
                            }
                        )
                    elif max_d >= calibration_ece_drift_warning:
                        out["signals"].append(
                            {
                                "severity": DRIFT_SEVERITY_WARNING,
                                "reason_code": REASON_CALIBRATION_DRIFT_MATERIAL,
                                "evidence": f"max abs delta ECE={max_d:.4f}",
                                "source": "recent_slice_vs_baseline_manifest",
                            }
                        )

                if base_conf_p is not None and r_cp is not None and abs(float(r_cp) - float(base_conf_p)) > 0.15:
                    out["signals"].append(
                        {
                            "severity": DRIFT_SEVERITY_WARNING,
                            "reason_code": REASON_CONFIDENCE_DRIFT_MATERIAL,
                            "evidence": f"parallel conf_corr baseline={base_conf_p} recent={r_cp}",
                            "source": "confidence_reliability_summary",
                        }
                    )
        elif include_recent_slice_evaluation and recent_err and resolved_db and resolved_db.is_file():
            out["calibration_drift_summary"] = {
                "state": "unavailable",
                "reason_code": REASON_RECENT_SLICE_INSUFFICIENT
                if "insufficient" in (recent_err or "").lower()
                else REASON_RECENT_SLICE_FAILED,
                "evidence": recent_err,
                "baseline_ece_parallel": base_ece_p,
                "baseline_ece_cascade": base_ece_c,
            }
            out["confidence_drift_summary"] = {
                "state": "unavailable",
                "reason_code": REASON_RECENT_SLICE_INSUFFICIENT
                if "insufficient" in (recent_err or "").lower()
                else REASON_RECENT_SLICE_FAILED,
            }

    rollback_watch = bool(
        data_drift
        or code_drift
        or (ev_age is not None and ev_age >= evaluation_stale_days_critical)
        or model_stale
    )
    if rollback_watch:
        out["signals"].append(
            {
                "severity": DRIFT_SEVERITY_ROLLBACK_WATCH,
                "reason_code": "ROLLBACK_WATCH_COMPOSITE",
                "evidence": "stale evaluation/code/data/model signals present — manual review",
                "source": "live_drift_monitoring",
            }
        )

    max_sev = DRIFT_SEVERITY_INFO
    order = (
        DRIFT_SEVERITY_INFO,
        DRIFT_SEVERITY_WARNING,
        DRIFT_SEVERITY_CRITICAL,
        DRIFT_SEVERITY_PROMOTION_BLOCKER,
        DRIFT_SEVERITY_ROLLBACK_WATCH,
    )
    order_index = {sev: i for i, sev in enumerate(order)}
    for s in out["signals"]:
        si = order_index.get(s["severity"], 0)
        mi = order_index.get(max_sev, 0)
        if si >= mi:
            max_sev = s["severity"]

    out["live_drift_summary"] = {
        "state": "ok",
        "highest_severity": max_sev,
        "signal_count": len(out["signals"]),
        "data_fingerprint_matches_lineage": (not data_drift)
        if (fp_current is not None and data_drift is not None)
        else None,
        "training_code_fingerprint_matches_lineage": not code_drift,
        "baseline_evaluation_manifest": str(ev_path.resolve()),
    }
    out["ok"] = True
    return out
