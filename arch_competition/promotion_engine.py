"""
Promotion decision layer — consumes evaluation manifests; does **not** copy to active/ or auto-promote.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from calibration.statistical_integrity import MIN_SAMPLES_STATISTICAL

from arch_competition.atomic_io import write_json_file_atomically
from arch_competition.exceptions import PromotionGovernanceError

PROMOTION_RECORD_SCHEMA_VERSION = "1"

INCUMBENT_ARCHITECTURE = "parallel"
CHALLENGER_ARCHITECTURE = "cascade"

# Stable contract for tests and downstream consumers (additive fields allowed only with version bump).
PROMOTION_RECORD_REQUIRED_KEYS: frozenset[str] = frozenset(
    {
        "schema_version",
        "created_at_utc",
        "incumbent_architecture",
        "challenger_architecture",
        "promotion_decision",
        "would_promote_challenger",
        "auto_promote_executed",
        "policy",
        "reason_codes",
        "blocked_promotion_flags",
        "rollback_demotion_ready",
        "evaluation_manifest_reference",
    }
)


@dataclass
class PromotionPolicy:
    """Locked governance thresholds (architecture competition spec §6)."""

    primary_metric: str = "log_loss"  # lower is better for log_loss
    min_delta_log_loss: float = 0.02  # cascade must beat parallel by this much on OOS log_loss
    max_brier_regression_vs_incumbent: float = 0.02  # cascade brier - parallel brier must not exceed this
    max_stability_std_vs_incumbent: float = 0.05  # cascade stability std may not exceed parallel + this
    require_calibration_pass: bool = True
    require_stability_pass: bool = True
    require_calibration_ece_pass: bool = True
    require_confidence_reliability_summary: bool = True
    require_min_samples_statistical: bool = True
    veto_regime_degradation: bool = True
    max_regime_balanced_accuracy_regression: float = 0.05  # cascade mid-VIX balanced_accuracy may lag parallel by this much
    # Empirical validation (calibration / rolling stability) — applied when manifest includes summaries.
    max_ece_regression_vs_incumbent: float = 0.12  # cascade ECE may not exceed parallel ECE by more than this
    veto_cascade_rolling_calibration_degradation: bool = True  # cascade-only rolling ECE degradation flag
    min_confidence_hit_correlation_vs_incumbent: float = -0.15  # cascade correlation must not lag parallel by more


def _reason(code: str, detail: str = "") -> dict[str, str]:
    return {"code": code, "detail": detail}


def decide_promotion(
    evaluation_manifest: dict[str, Any],
    policy: PromotionPolicy | None = None,
    *,
    auto_promote: bool = False,
) -> dict[str, Any]:
    """
    Produce a promotion **decision record** only. ``auto_promote`` must stay False for governed runs.

    Raises:
        PromotionGovernanceError: missing required manifest fields or lineage.
    """
    if auto_promote:
        raise PromotionGovernanceError("auto_promote is forbidden for governed promotion decisions")

    pol = policy or PromotionPolicy()
    if evaluation_manifest.get("schema_version") != "1":
        raise PromotionGovernanceError("evaluation_manifest.schema_version must be 1")

    lineage = evaluation_manifest.get("lineage") or {}
    if lineage.get("manifests_skipped"):
        raise PromotionGovernanceError("cannot promote without lineage manifests (manifests_skipped)")

    required = (
        "feature_cache_key",
        "data_fingerprint",
        "ml_horizon_suffix",
        "training_code_fingerprint",
    )
    for k in required:
        if lineage.get(k) in (None, ""):
            raise PromotionGovernanceError(f"missing lineage.{k} in evaluation manifest")

    hz_eval = str(evaluation_manifest.get("ml_horizon_slug") or "").strip().lower()
    if not hz_eval:
        raise PromotionGovernanceError("missing evaluation_manifest.ml_horizon_slug")
    hz_lineage = str(lineage.get("ml_horizon_suffix") or "").strip().lower()
    if hz_eval != hz_lineage:
        raise PromotionGovernanceError(
            f"horizon mismatch: manifest ml_horizon_slug={hz_eval!r} vs lineage ml_horizon_suffix={hz_lineage!r}"
        )

    m = evaluation_manifest.get("metrics") or {}
    mp = m.get("parallel") or {}
    mc = m.get("cascade") or {}

    if not mp.get("n_rows_scored") or mp.get("n_rows_scored") != mc.get("n_rows_scored"):
        raise PromotionGovernanceError("missing or mismatched n_rows_scored between architectures")

    blocked: list[dict[str, str]] = []
    reasons: list[dict[str, str]] = []

    if pol.require_min_samples_statistical:
        below_min = evaluation_manifest.get("evaluation_n_below_min_samples_statistical")
        if below_min is None:
            try:
                n_scored = int(mp.get("n_rows_scored") or 0)
            except (TypeError, ValueError):
                n_scored = 0
            below_min = n_scored < MIN_SAMPLES_STATISTICAL
        if below_min:
            blocked.append(
                _reason(
                    "MISSING_MIN_SAMPLES_STATISTICAL",
                    f"evaluation n_rows_scored below MIN_SAMPLES_STATISTICAL ({MIN_SAMPLES_STATISTICAL})",
                )
            )

    pll = mp.get("log_loss")
    cll = mc.get("log_loss")
    p_brier = mp.get("brier_score")
    c_brier = mc.get("brier_score")
    p_stab = mp.get("stability_log_loss_std_halves")
    c_stab = mc.get("stability_log_loss_std_halves")

    if pll is None or cll is None:
        blocked.append(_reason("MISSING_LOG_LOSS", "log_loss required for primary metric"))
    else:
        # lower log_loss is better — cascade wins if cll < pll - delta
        improvement = float(pll) - float(cll)
        if improvement < pol.min_delta_log_loss:
            blocked.append(
                _reason(
                    "PRIMARY_METRIC_INSUFFICIENT",
                    f"log_loss improvement {improvement:.4f} < min_delta {pol.min_delta_log_loss}",
                )
            )
        else:
            reasons.append(_reason("PRIMARY_OK", f"log_loss improvement {improvement:.4f}"))

    # Multi-metric gates (no single-metric promotion)
    calibration_ok = True
    if pol.require_calibration_pass:
        if p_brier is None or c_brier is None:
            calibration_ok = False
            blocked.append(_reason("MISSING_CALIBRATION_METRIC", "brier_score required for both architectures"))
        elif c_brier > p_brier + pol.max_brier_regression_vs_incumbent:
            calibration_ok = False
            blocked.append(
                _reason(
                    "CALIBRATION_REGRESSION",
                    f"cascade brier {c_brier:.4f} vs parallel {p_brier:.4f}",
                )
            )
        else:
            reasons.append(_reason("CALIBRATION_OK", ""))

    stability_ok = True
    if pol.require_stability_pass:
        if p_stab is None or c_stab is None:
            stability_ok = False
            blocked.append(_reason("MISSING_STABILITY_METRIC", "stability_log_loss_std_halves required for both"))
        elif c_stab > p_stab + pol.max_stability_std_vs_incumbent:
            stability_ok = False
            blocked.append(
                _reason(
                    "STABILITY_FAIL",
                    f"cascade half-split log_loss std {c_stab:.4f} vs parallel {p_stab:.4f}",
                )
            )
        else:
            reasons.append(_reason("STABILITY_OK", ""))

    regime_ok = True
    if pol.veto_regime_degradation:
        rp = (mp.get("regime_slices") or {}).get("mid")
        rc = (mc.get("regime_slices") or {}).get("mid")
        if not isinstance(rp, dict) or not isinstance(rc, dict):
            regime_ok = False
            blocked.append(
                _reason(
                    "MISSING_REGIME_METRIC",
                    "policy veto requires regime_slices.mid for both architectures",
                )
            )
        elif rp.get("skipped_low_support") or rc.get("skipped_low_support"):
            reasons.append(_reason("REGIME_MID_SKIPPED_LOW_SUPPORT", ""))
        elif rp.get("balanced_accuracy") is None or rc.get("balanced_accuracy") is None:
            regime_ok = False
            blocked.append(
                _reason(
                    "MISSING_REGIME_METRIC",
                    "regime_slices.mid balanced_accuracy required for both architectures",
                )
            )
        elif float(rc["balanced_accuracy"]) < float(rp["balanced_accuracy"]) - pol.max_regime_balanced_accuracy_regression:
            regime_ok = False
            blocked.append(_reason("REGIME_MID_BUCKET_REGRESSION", "mid VIX bucket accuracy degraded"))
        else:
            reasons.append(_reason("REGIME_OK", ""))

    empirical_ok = True
    p_ece = mp.get("calibration_ece")
    c_ece = mc.get("calibration_ece")
    if pol.require_calibration_ece_pass:
        if p_ece is None or c_ece is None:
            empirical_ok = False
            blocked.append(
                _reason(
                    "MISSING_CALIBRATION_ECE_METRIC",
                    "calibration_ece required for both architectures",
                )
            )
        elif float(c_ece) > float(p_ece) + pol.max_ece_regression_vs_incumbent:
            empirical_ok = False
            blocked.append(
                _reason(
                    "CALIBRATION_ECE_REGRESSION",
                    f"cascade ECE {float(c_ece):.4f} vs parallel {float(p_ece):.4f}",
                )
            )
        else:
            reasons.append(_reason("CALIBRATION_ECE_OK", ""))

    crs = evaluation_manifest.get("confidence_reliability_summary") or {}
    if pol.require_confidence_reliability_summary:
        if not crs.get("schema_version"):
            empirical_ok = False
            blocked.append(
                _reason(
                    "MISSING_CONFIDENCE_RELIABILITY_SUMMARY",
                    "policy requires confidence_reliability_summary.schema_version",
                )
            )
        else:
            crp = (crs.get("by_architecture") or {}).get("parallel") or {}
            crc = (crs.get("by_architecture") or {}).get("cascade") or {}
            p_corr = crp.get("confidence_hit_correlation")
            c_corr = crc.get("confidence_hit_correlation")
            if p_corr is None or c_corr is None:
                empirical_ok = False
                blocked.append(
                    _reason(
                        "MISSING_CONFIDENCE_RELIABILITY_METRIC",
                        "confidence_hit_correlation required for both architectures",
                    )
                )
            elif float(c_corr) < float(p_corr) + pol.min_confidence_hit_correlation_vs_incumbent:
                empirical_ok = False
                blocked.append(
                    _reason(
                        "CONFIDENCE_RELIABILITY_REGRESSION",
                        f"cascade conf_corr {float(c_corr):.4f} vs parallel {float(p_corr):.4f}",
                    )
                )
            else:
                reasons.append(_reason("CONFIDENCE_RELIABILITY_OK", ""))

    rss = evaluation_manifest.get("rolling_stability_summary") or {}
    rbp = (rss.get("by_architecture") or {}).get("parallel") or {}
    rbc = (rss.get("by_architecture") or {}).get("cascade") or {}
    if pol.veto_cascade_rolling_calibration_degradation:
        if not rss.get("schema_version"):
            empirical_ok = False
            blocked.append(
                _reason(
                    "MISSING_ROLLING_STABILITY_SUMMARY",
                    "policy veto requires rolling_stability_summary.schema_version",
                )
            )
        else:
            d_p = bool(rbp.get("calibration_degradation_flag"))
            d_c = bool(rbc.get("calibration_degradation_flag"))
            if d_c and not d_p:
                empirical_ok = False
                blocked.append(
                    _reason(
                        "ROLLING_CALIBRATION_DEGRADATION",
                        "cascade shows time-ordered calibration degradation vs parallel",
                    )
                )
            elif not d_c:
                reasons.append(_reason("ROLLING_CALIBRATION_STABLE_OK", ""))
            elif d_c and d_p:
                reasons.append(
                    _reason(
                        "ROLLING_CALIBRATION_BOTH_DEGRADED",
                        "both architectures show time-ordered calibration degradation — cascade-specific veto not triggered",
                    )
                )

    promoted = (
        len(blocked) == 0
        and pll is not None
        and cll is not None
        and (float(pll) - float(cll)) >= pol.min_delta_log_loss
        and calibration_ok
        and stability_ok
        and regime_ok
        and empirical_ok
    )

    decision = "promote_cascade" if promoted else "keep_incumbent"
    if not promoted and not blocked:
        decision = "keep_incumbent"
        reasons.append(_reason("TIE_OR_INSUFFICIENT", "incumbent wins ties per spec"))

    record: dict[str, Any] = {
        "schema_version": PROMOTION_RECORD_SCHEMA_VERSION,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "incumbent_architecture": INCUMBENT_ARCHITECTURE,
        "challenger_architecture": CHALLENGER_ARCHITECTURE,
        "promotion_decision": decision,
        "would_promote_challenger": bool(promoted),
        "auto_promote_executed": False,
        "policy": {
            "primary_metric": pol.primary_metric,
            "min_delta_log_loss": pol.min_delta_log_loss,
            "max_brier_regression_vs_incumbent": pol.max_brier_regression_vs_incumbent,
            "max_stability_std_vs_incumbent": pol.max_stability_std_vs_incumbent,
            "require_calibration_pass": pol.require_calibration_pass,
            "require_stability_pass": pol.require_stability_pass,
            "require_calibration_ece_pass": pol.require_calibration_ece_pass,
            "require_confidence_reliability_summary": pol.require_confidence_reliability_summary,
            "require_min_samples_statistical": pol.require_min_samples_statistical,
            "max_ece_regression_vs_incumbent": pol.max_ece_regression_vs_incumbent,
            "veto_cascade_rolling_calibration_degradation": pol.veto_cascade_rolling_calibration_degradation,
            "veto_regime_degradation": pol.veto_regime_degradation,
            "max_regime_balanced_accuracy_regression": pol.max_regime_balanced_accuracy_regression,
            "min_confidence_hit_correlation_vs_incumbent": pol.min_confidence_hit_correlation_vs_incumbent,
        },
        "reason_codes": reasons,
        "blocked_promotion_flags": blocked,
        "rollback_demotion_ready": True,
        "evaluation_manifest_reference": {
            "evaluation_manifest_schema": evaluation_manifest.get("schema_version"),
            "ticker": evaluation_manifest.get("ticker"),
            "ml_horizon_slug": evaluation_manifest.get("ml_horizon_slug"),
            "lineage_feature_cache_key": lineage.get("feature_cache_key"),
        },
    }
    missing_keys = PROMOTION_RECORD_REQUIRED_KEYS - record.keys()
    if missing_keys:
        raise PromotionGovernanceError(f"internal: promotion record missing keys {sorted(missing_keys)}")
    return record


def write_promotion_record(path: Path, record: dict[str, Any]) -> None:
    write_json_file_atomically(path, record, indent=2, default=str)
