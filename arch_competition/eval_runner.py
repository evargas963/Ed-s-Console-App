"""
Offline evaluation runner: parallel vs cascade on identical rows and shared lineage.

Does not promote, copy artifacts, or change ``run_base_models_once`` / production default.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Set

from ml_horizon import normalize_ml_horizon_slug, outcome_column

from calibration.statistical_integrity import MIN_SAMPLES_STATISTICAL

from arch_competition.atomic_io import write_json_file_atomically
from arch_competition.exceptions import EvaluationLineageError
from arch_competition.lineage import validate_parallel_cascade_manifest_lineage
from arch_competition.metrics import (
    architecture_win_consistency_by_window,
    brier_decomposition_multiclass,
    confidence_bucket_summaries,
    confidence_reliability_proxy,
    expected_calibration_error_multiclass,
    half_split_log_loss_std,
    max_calibration_error_bins,
    multiclass_brier_score,
    overconfidence_diagnostics,
    regime_bucket_metrics,
    regime_conditional_calibration,
    reliability_bins_table,
    rolling_calibration_and_loss_stability,
)

EVALUATION_MANIFEST_SCHEMA_VERSION = "1"

EVALUATION_MANIFEST_REQUIRED_KEYS: frozenset[str] = frozenset(
    {
        "schema_version",
        "created_at_utc",
        "ticker",
        "ml_horizon_slug",
        "target_column",
        "db_path",
        "parallel_model_dir",
        "cascade_model_dir",
        "lineage",
        "metrics",
        "rolling_oos_windows",
        "architecture_comparison_summary",
        "calibration_summary",
        "confidence_reliability_summary",
        "rolling_stability_summary",
        "empirical_validation",
    }
)

EMPIRICAL_VALIDATION_SCHEMA_VERSION = "1"
EMPIRICAL_SECTION_SCHEMA_VERSION = "1"


def _validate_probability_detail(
    architecture: str,
    n_rows_scored: int,
    detail: dict[str, Any],
) -> None:
    """Fail-closed when calibration requires aligned probability vectors."""
    if n_rows_scored < MIN_SAMPLES_STATISTICAL:
        return
    y_true = detail.get("y_true") or []
    prob_rows = detail.get("prob_rows") or []
    if not prob_rows:
        raise EvaluationLineageError(
            f"{architecture}: missing prob_rows for calibration (n_rows_scored={n_rows_scored})"
        )
    if len(prob_rows) != n_rows_scored or len(y_true) != n_rows_scored:
        raise EvaluationLineageError(
            f"{architecture}: prob_rows/y_true length mismatch vs n_rows_scored "
            f"(n={n_rows_scored}, len(p)={len(prob_rows)}, len(y)={len(y_true)})"
        )


def _pack_arch_metrics(
    name: str,
    acc: float,
    bal: float,
    n: int,
    ll: Optional[float],
    realized: dict[str, Any],
    detail: dict[str, Any],
) -> dict[str, Any]:
    y_true = detail.get("y_true") or []
    prob_rows = detail.get("prob_rows") or []
    rows_used = detail.get("rows_used") or []
    brier = multiclass_brier_score(y_true, prob_rows)
    stab = half_split_log_loss_std(y_true, prob_rows)
    regime = regime_bucket_metrics(y_true, prob_rows, rows_used)
    conf_rel = confidence_reliability_proxy(prob_rows, y_true)
    ece = expected_calibration_error_multiclass(y_true, prob_rows, n_bins=10)
    mce = max_calibration_error_bins(y_true, prob_rows, n_bins=10)
    brier_dec = brier_decomposition_multiclass(y_true, prob_rows)
    return {
        "architecture": name,
        "n_rows_scored": n,
        "accuracy": acc,
        "balanced_accuracy": bal,
        "log_loss": ll,
        "brier_score": brier,
        "stability_log_loss_std_halves": stab,
        "calibration_ece": ece,
        "calibration_mce": mce,
        "brier_decomposition": brier_dec,
        "regime_slices": regime,
        "confidence_reliability": conf_rel,
        "realized_contract_metrics": realized,
    }


def _build_empirical_sections(
    hz: str,
    parallel_metrics: dict[str, Any],
    cascade_metrics: dict[str, Any],
    pdet: dict[str, Any],
    cdet: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Calibration / confidence / rolling summaries + bundled empirical_validation envelope."""
    py = pdet.get("y_true") or []
    pp = pdet.get("prob_rows") or []
    pru = pdet.get("rows_used") or []
    cy = cdet.get("y_true") or []
    cp = cdet.get("prob_rows") or []
    cru = cdet.get("rows_used") or []

    rel_p = reliability_bins_table(py, pp, n_bins=10)
    rel_c = reliability_bins_table(cy, cp, n_bins=10)
    occ_p = overconfidence_diagnostics(py, pp)
    occ_c = overconfidence_diagnostics(cy, cp)
    cb_p = confidence_bucket_summaries(py, pp, n_buckets=5)
    cb_c = confidence_bucket_summaries(cy, cp, n_buckets=5)
    roll_p = rolling_calibration_and_loss_stability(py, pp, n_windows=3)
    roll_c = rolling_calibration_and_loss_stability(cy, cp, n_windows=3)
    reg_cal_p = regime_conditional_calibration(py, pp, pru)
    reg_cal_c = regime_conditional_calibration(cy, cp, cru)
    win_cons = architecture_win_consistency_by_window(py, pp, cp, n_windows=3)

    calibration_summary = {
        "schema_version": EMPIRICAL_SECTION_SCHEMA_VERSION,
        "n_bins_default": 10,
        "by_architecture": {
            "parallel": {
                "ece": parallel_metrics.get("calibration_ece"),
                "mce": parallel_metrics.get("calibration_mce"),
                "reliability_bins": rel_p,
                "brier_decomposition": parallel_metrics.get("brier_decomposition"),
            },
            "cascade": {
                "ece": cascade_metrics.get("calibration_ece"),
                "mce": cascade_metrics.get("calibration_mce"),
                "reliability_bins": rel_c,
                "brier_decomposition": cascade_metrics.get("brier_decomposition"),
            },
        },
        "by_horizon": {
            hz: {
                "parallel": {"ece": parallel_metrics.get("calibration_ece")},
                "cascade": {"ece": cascade_metrics.get("calibration_ece")},
            }
        },
        "regime_conditional_ece": {"parallel": reg_cal_p, "cascade": reg_cal_c},
    }

    conf_sum = {
        "schema_version": EMPIRICAL_SECTION_SCHEMA_VERSION,
        "by_architecture": {
            "parallel": {
                **(parallel_metrics.get("confidence_reliability") or {}),
                "confidence_buckets": cb_p,
                "overconfidence": occ_p,
            },
            "cascade": {
                **(cascade_metrics.get("confidence_reliability") or {}),
                "confidence_buckets": cb_c,
                "overconfidence": occ_c,
            },
        },
    }

    roll_sum = {
        "schema_version": EMPIRICAL_SECTION_SCHEMA_VERSION,
        "n_windows": 3,
        "by_architecture": {
            "parallel": roll_p,
            "cascade": roll_c,
        },
        "architecture_win_consistency_log_loss": win_cons,
    }

    empirical_validation = {
        "schema_version": EMPIRICAL_VALIDATION_SCHEMA_VERSION,
        "calibration_summary_ref": "calibration_summary",
        "confidence_reliability_summary_ref": "confidence_reliability_summary",
        "rolling_stability_summary_ref": "rolling_stability_summary",
        "lineage_required_for_comparison": True,
    }
    return calibration_summary, conf_sum, roll_sum, empirical_validation


def run_architecture_pair_evaluation(
    *,
    db_path: str,
    ticker: str,
    parallel_model_dir: Path,
    cascade_model_dir: Path,
    ml_horizon_slug: str,
    allowed_et_dates: Optional[Set[str]] = None,
    require_manifest_lineage: bool = True,
    expected_ml_horizon_suffix: str | None = None,
) -> dict[str, Any]:
    """
    Evaluate parallel and cascade on the same RTH rows and (when present) shared manifest lineage.

    Raises:
        EvaluationLineageError: lineage validation failed or row-count mismatch between arches.
    """
    hz = normalize_ml_horizon_slug(ml_horizon_slug)
    target_column = outcome_column(hz)
    ex_hz = expected_ml_horizon_suffix or hz

    lineage: dict[str, Any] = {}
    if require_manifest_lineage:
        lineage = validate_parallel_cascade_manifest_lineage(
            parallel_model_dir,
            cascade_model_dir,
            ticker=ticker,
            expected_ml_horizon_suffix=ex_hz,
        )
    else:
        from features.canonical_contract import CANONICAL_FEATURE_CONTRACT_VERSION, CANONICAL_FEATURE_TIMEFRAME

        lineage = {
            "feature_cache_key": None,
            "data_fingerprint": None,
            "ml_horizon_suffix": hz,
            "canonical_feature_contract_version": CANONICAL_FEATURE_CONTRACT_VERSION,
            "canonical_timeframe": CANONICAL_FEATURE_TIMEFRAME,
            "manifests_skipped": True,
        }

    from ml_scheduler import _evaluate_cascade_on_full_rth, _evaluate_parallel_on_full_rth

    pr = _evaluate_parallel_on_full_rth(
        db_path,
        ticker,
        parallel_model_dir,
        allowed_et_dates=allowed_et_dates,
        target_column=target_column,
        return_detail=True,
    )
    cr = _evaluate_cascade_on_full_rth(
        db_path,
        ticker,
        cascade_model_dir,
        allowed_et_dates=allowed_et_dates,
        target_column=target_column,
        return_detail=True,
    )
    pac, pbal, pn, pll, prm, pdet = pr
    cac, cbal, cn, cll, crm, cdet = cr

    if pn != cn:
        raise EvaluationLineageError(
            f"evaluation row-count mismatch: parallel n={pn} cascade n={cn} "
            f"(same allowed_et_dates and DB required)"
        )

    _validate_probability_detail("parallel", pn, pdet)
    _validate_probability_detail("cascade", cn, cdet)

    parallel_metrics = _pack_arch_metrics("parallel", pac, pbal, pn, pll, prm, pdet)
    cascade_metrics = _pack_arch_metrics("cascade", cac, cbal, cn, cll, crm, cdet)

    calibration_summary, confidence_reliability_summary, rolling_stability_summary, empirical_validation = (
        _build_empirical_sections(hz, parallel_metrics, cascade_metrics, pdet, cdet)
    )

    rolling_windows: list[dict[str, Any]] = []
    # Single-window trial: expose halves stability as rolling proxy (spec §5.2 multi-roll can extend)
    rolling_windows.append(
        {
            "window_id": "full_oos",
            "parallel_log_loss": pll,
            "cascade_log_loss": cll,
            "parallel_brier": parallel_metrics.get("brier_score"),
            "cascade_brier": cascade_metrics.get("brier_score"),
        }
    )

    oos_fp: str | None = None
    if allowed_et_dates:
        oos_fp = hashlib.sha256(
            json.dumps(sorted(allowed_et_dates), separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    arch_summary = {
        "primary_metric_name": "log_loss",
        "delta_log_loss_parallel_minus_cascade": (
            (float(pll) - float(cll)) if pll is not None and cll is not None else None
        ),
        "delta_balanced_accuracy_cascade_minus_parallel": float(cbal) - float(pbal),
        "delta_ece_cascade_minus_parallel": (
            (float(cascade_metrics.get("calibration_ece") or 0) - float(parallel_metrics.get("calibration_ece") or 0))
            if cascade_metrics.get("calibration_ece") is not None
            and parallel_metrics.get("calibration_ece") is not None
            else None
        ),
        "n_rows_scored": pn,
        "parallel_wins_log_loss": bool(pll is not None and cll is not None and float(pll) < float(cll)),
        "note": "Summary only; promotion uses promotion_engine.decide_promotion (multi-metric + empirical gates).",
    }

    manifest: dict[str, Any] = {
        "schema_version": EVALUATION_MANIFEST_SCHEMA_VERSION,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "ticker": ticker.upper(),
        "ml_horizon_slug": hz,
        "target_column": target_column,
        "db_path": str(Path(db_path).resolve()),
        "parallel_model_dir": str(parallel_model_dir.resolve()),
        "cascade_model_dir": str(cascade_model_dir.resolve()),
        "allowed_et_dates": sorted(allowed_et_dates) if allowed_et_dates else None,
        "oos_et_dates_fingerprint": oos_fp,
        "lineage": lineage,
        "lineage_fingerprints": {
            "feature_cache_key": lineage.get("feature_cache_key"),
            "data_fingerprint": lineage.get("data_fingerprint"),
            "ml_horizon_suffix": lineage.get("ml_horizon_suffix"),
            "canonical_feature_contract_version": lineage.get("canonical_feature_contract_version"),
            "canonical_timeframe": lineage.get("canonical_timeframe"),
        },
        "metrics": {
            "parallel": parallel_metrics,
            "cascade": cascade_metrics,
        },
        "metric_breakdown": {
            "by_horizon": {hz: {"parallel": parallel_metrics, "cascade": cascade_metrics}},
            "by_regime_vix_bucket": {
                "parallel": parallel_metrics.get("regime_slices") or {},
                "cascade": cascade_metrics.get("regime_slices") or {},
            },
            "by_rolling_window": rolling_windows,
        },
        "rolling_oos_windows": rolling_windows,
        "architecture_comparison_summary": arch_summary,
        "calibration_summary": calibration_summary,
        "confidence_reliability_summary": confidence_reliability_summary,
        "rolling_stability_summary": rolling_stability_summary,
        "empirical_validation": empirical_validation,
        "evaluation_n_below_min_samples_statistical": pn < MIN_SAMPLES_STATISTICAL,
    }
    missing = EVALUATION_MANIFEST_REQUIRED_KEYS - manifest.keys()
    if missing:
        raise EvaluationLineageError(f"internal: evaluation manifest missing keys {sorted(missing)}")
    return manifest


def write_evaluation_manifest(path: Path, manifest: dict[str, Any]) -> None:
    write_json_file_atomically(path, manifest, indent=2, default=str)
