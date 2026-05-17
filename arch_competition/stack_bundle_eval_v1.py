"""
Offline stack bundle evaluation (Issue: authority / XGB vs full stack / MC / Fusion).

Reuses:
- ml_scheduler._load_rth_rows_for_ticker — chronological RTH rows, causal inference_snapshot.
- ml_predict.run_base_models_once — production-parallel XGB+LSTM+Transformer + meta/weighted stack.
- signals._run_model_stack — adds Monte Carlo on top of base models.
- bayesian_fusion.fuse — posterior directional triplet.

Primary promotion metric (aligned with arch_competition.promotion_engine): multiclass log_loss (lower better).
Secondary: balanced_accuracy, macro_f1, calibration ECE (top-class bins), Brier (multiclass from metrics.py).

No naive random split: rows are ts_utc ascending from DB (same contract as ml_scheduler eval).
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    confusion_matrix,
    f1_score,
    log_loss,
    precision_recall_fscore_support,
)

from calibration.statistical_integrity import MIN_SAMPLES_STATISTICAL
from ml_horizon import normalize_ml_horizon_slug, outcome_column
from ml_predict import stack_probs_bundle_key

log = logging.getLogger(__name__)

SCHEMA_VERSION = "1"
UNIFORM_3CLASS_LOG_LOSS = float(math.log(3.0))
# Heuristic stack-bundle gate (distinct from promotion_engine.PromotionPolicy.max_ece_regression_vs_incumbent).
POLICY_CALIBRATION_MAX_ECE = 0.35

# Full component matrix (default CLI). All scored on the same row intersection.
DEFAULT_ALL_MODES: tuple[str, ...] = (
    "xgb_only",
    "lstm_only",
    "transformer_only",
    "xgb_plus_lstm",
    "xgb_plus_transformer",
    "xgb_plus_lstm_plus_transformer",
    "fusion_without_mc",
    "full_fusion",
)

# Backward-compatible alias.
DEFAULT_CORE_MODES: tuple[str, ...] = DEFAULT_ALL_MODES

# Optional: trained meta-learner on 9-dim stack vs explicit 40/35/25 weighted blend (see evaluation_contract).
META_STACK_MODE = "meta_stack"

VALID_MODES: frozenset[str] = frozenset(
    {
        "xgb_only",
        "lstm_only",
        "transformer_only",
        "xgb_plus_lstm",
        "xgb_plus_transformer",
        "xgb_plus_lstm_plus_transformer",
        META_STACK_MODE,
        "fusion_without_mc",
        "full_fusion",
    }
)

# Embedded in JSON manifests for auditors.
MODE_DEFINITIONS: dict[str, str] = {
    "xgb_only": "fusion.xgb from run_base_models_once only (tabular XGB, parallel_runtime stack).",
    "lstm_only": "fusion.lstm only — no XGB or Transformer probabilities in the triplet.",
    "transformer_only": "fusion.transformer only — no XGB or LSTM probabilities in the triplet.",
    "xgb_plus_lstm": "ml_predict._weighted_average with XGB + LSTM only (base weights 0.40+0.35 renormalized).",
    "xgb_plus_transformer": "ml_predict._weighted_average with XGB + Transformer only (0.40+0.25 renormalized).",
    "xgb_plus_lstm_plus_transformer": (
        "ml_predict._weighted_average(xgb, lstm, transformer) — explicit 0.40/0.35/0.25 blend; "
        "does NOT use the trained meta-learner (meta_*.pkl)."
    ),
    META_STACK_MODE: (
        "Production stack_probs: _predict_meta(meta_*.pkl) when present, else _weighted_average "
        "of three bases — differs from xgb_plus_lstm_plus_transformer when meta learner exists."
    ),
    "fusion_without_mc": (
        "bayesian_fusion.fuse (XGB+LSTM+Transformer+rules+regime); Monte Carlo is excluded from fusion math."
    ),
    "full_fusion": (
        "Same base fusion as fusion_without_mc, then mc_fusion_adjustment.fuse_payload_apply_mc_adjustment "
        "when MC is available (contextual volatility/tail/bias only)."
    ),
}


def _outcome_class_index(outcome_raw: Any) -> Optional[int]:
    """Map outcome column value to {up:0, down:1, flat:2}; None if missing or invalid."""
    if outcome_raw is None:
        return None
    key = str(outcome_raw).strip().lower()
    if not key:
        return None
    return {"up": 0, "down": 1, "flat": 2}.get(key)


def _norm_triplet(pu: float, pd: float, pf: float) -> Optional[list[float]]:
    fpu, fpd, fpf = float(pu), float(pd), float(pf)
    if not all(math.isfinite(v) for v in (fpu, fpd, fpf)):
        return None
    s = fpu + fpd + fpf
    if s <= 0:
        return None
    return [fpu / s, fpd / s, fpf / s]


def _dict_to_probs(d: Optional[dict]) -> Optional[list[float]]:
    if not d:
        return None
    if not all(k in d for k in ("up", "down", "flat")):
        return None
    try:
        return _norm_triplet(float(d["up"]), float(d["down"]), float(d["flat"]))
    except (TypeError, ValueError):
        return None


def _probs_from_fusion_branch(b: Optional[dict]) -> Optional[list[float]]:
    """run_base_models_once fusion.* uses prob_up / prob_down / prob_flat."""
    if not b or not b.get("available"):
        return None
    if not all(k in b for k in ("prob_up", "prob_down", "prob_flat")):
        return None
    try:
        return _norm_triplet(float(b["prob_up"]), float(b["prob_down"]), float(b["prob_flat"]))
    except (TypeError, ValueError):
        return None


def _fusion_branch_to_prob_dict(b: Optional[dict]) -> Optional[dict]:
    """Convert fusion branch to {up,down,flat} for _weighted_average."""
    if not b or not b.get("available"):
        return None
    if not all(k in b for k in ("prob_up", "prob_down", "prob_flat")):
        return None
    try:
        return {
            "up": float(b["prob_up"]),
            "down": float(b["prob_down"]),
            "flat": float(b["prob_flat"]),
        }
    except (TypeError, ValueError):
        return None


def _weighted_blend_probs(
    mp: Any,
    ticker: str,
    *,
    xgb_d: Optional[dict],
    lstm_d: Optional[dict],
    tr_d: Optional[dict],
) -> Optional[list[float]]:
    """
    Explicit blend using ml_predict._weighted_average only among provided branches.
    Missing branches are omitted (weights renormalized over XGB=0.40, LSTM=0.35, TR=0.25).
    """
    wa = mp._weighted_average(ticker, xgb_d, lstm_d, tr_d)
    return _dict_to_probs(wa)


def _pack_full_metrics(
    name: str,
    y_true: list[int],
    prob_rows: list[list[float]],
    rows_used: list[dict],
) -> dict[str, Any]:
    from arch_competition.metrics import (
        confidence_bucket_summaries,
        confidence_reliability_proxy,
        expected_calibration_error_multiclass,
        half_split_log_loss_std,
        multiclass_brier_score,
        overconfidence_diagnostics,
        regime_bucket_metrics,
        regime_conditional_calibration,
        reliability_bins_table,
    )

    n = len(y_true)
    if n < MIN_SAMPLES_STATISTICAL or len(prob_rows) != n:
        return {
            "config": name,
            "n_rows_scored": n,
            "error": "insufficient_rows_or_misaligned_probs",
        }
    P = np.asarray(prob_rows, dtype=np.float64)
    preds = list(np.argmax(P, axis=1).astype(int))
    acc = float(accuracy_score(y_true, preds))
    bal = float(balanced_accuracy_score(y_true, preds))
    macro_f1 = float(f1_score(y_true, preds, average="macro", labels=[0, 1, 2], zero_division=0))
    prec, rec, f1, _ = precision_recall_fscore_support(
        y_true, preds, labels=[0, 1, 2], zero_division=0, average=None
    )
    per_class = {
        "up": {"precision": float(prec[0]), "recall": float(rec[0]), "f1": float(f1[0])},
        "down": {"precision": float(prec[1]), "recall": float(rec[1]), "f1": float(f1[1])},
        "flat": {"precision": float(prec[2]), "recall": float(rec[2]), "f1": float(f1[2])},
    }
    cm = confusion_matrix(y_true, preds, labels=[0, 1, 2]).tolist()
    ll = float(log_loss(y_true, P, labels=[0, 1, 2]))
    brier = multiclass_brier_score(y_true, prob_rows)
    stab = half_split_log_loss_std(y_true, prob_rows)
    ece = expected_calibration_error_multiclass(y_true, prob_rows, n_bins=10)
    rel = reliability_bins_table(y_true, prob_rows, n_bins=10)
    cb = confidence_bucket_summaries(y_true, prob_rows, n_buckets=5)
    conf_rel = confidence_reliability_proxy(prob_rows, y_true)
    occ = overconfidence_diagnostics(y_true, prob_rows)

    # Directional: max prob on correct class vs incorrect (multiclass separation)
    p_correct = []
    p_wrong_max = []
    for pr, yt in zip(prob_rows, y_true):
        arr = np.asarray(pr, dtype=np.float64)
        p_correct.append(float(arr[yt]))
        mask = np.ones(3, dtype=bool)
        mask[yt] = False
        p_wrong_max.append(float(np.max(arr[mask])) if mask.any() else 0.0)
    dir_sep = float(np.mean(np.asarray(p_correct) - np.asarray(p_wrong_max)))

    return {
        "config": name,
        "n_rows_scored": n,
        "accuracy": acc,
        "balanced_accuracy": bal,
        "macro_f1": macro_f1,
        "per_class_precision_recall_f1": per_class,
        "confusion_matrix": {"labels_order": ["up", "down", "flat"], "matrix": cm},
        "multiclass_log_loss": ll,
        "brier_score_multiclass_mean_squared_error": brier,
        "calibration_top_predicted_class_ece": ece,
        "reliability_bins_top_class": rel,
        "confidence_buckets_quantile": cb,
        "confidence_reliability_proxy": conf_rel,
        "overconfidence_diagnostics": occ,
        "stability_log_loss_std_halves": stab,
        "directional_separation_mean_p_correct_minus_max_p_wrong": dir_sep,
        "regime_slices": regime_bucket_metrics(y_true, prob_rows, rows_used),
        "regime_conditional_ece": regime_conditional_calibration(y_true, prob_rows, rows_used),
    }


def _authority_block(
    by_config: dict[str, dict[str, Any]],
    *,
    min_rows: int,
    min_delta_log_loss: float,
) -> dict[str, Any]:
    """Rank by multiclass_log_loss on paired intersection subset."""
    ranked: list[tuple[str, float]] = []
    for name, m in by_config.items():
        ll = m.get("multiclass_log_loss")
        n = m.get("n_rows_scored", 0)
        if ll is None or n < min_rows:
            continue
        ranked.append((name, float(ll)))
    ranked.sort(key=lambda x: x[1])
    winner = ranked[0][0] if ranked else None
    runner = ranked[1][0] if len(ranked) > 1 else None
    best_ll = ranked[0][1] if ranked else None
    second_ll = ranked[1][1] if len(ranked) > 1 else None
    margin = (second_ll - best_ll) if (best_ll is not None and second_ll is not None) else None

    meta = by_config.get("meta_stack") or {}
    triplet_explicit = by_config.get("xgb_plus_lstm_plus_transformer") or {}
    full = by_config.get("full_fusion") or {}
    no_mc = by_config.get("fusion_without_mc") or {}
    xgb = by_config.get("xgb_only") or {}

    ll_meta = meta.get("multiclass_log_loss")
    ll_triplet_explicit = triplet_explicit.get("multiclass_log_loss")
    ll_full = full.get("multiclass_log_loss")
    ll_nomc = no_mc.get("multiclass_log_loss")
    ll_xgb = xgb.get("multiclass_log_loss")

    mc_helps: Optional[bool] = None
    if ll_nomc is not None and ll_full is not None:
        mc_helps = bool(ll_nomc - ll_full > 1e-6)

    fusion_helps_vs_meta_stack: Optional[bool] = None
    if ll_meta is not None and ll_full is not None:
        fusion_helps_vs_meta_stack = bool(ll_meta - ll_full > 1e-6)

    fusion_helps_vs_explicit_weighted_triplet: Optional[bool] = None
    if ll_triplet_explicit is not None and ll_full is not None:
        fusion_helps_vs_explicit_weighted_triplet = bool(ll_triplet_explicit - ll_full > 1e-6)

    edge_vs_uniform: Optional[bool] = None
    if best_ll is not None:
        edge_vs_uniform = bool(UNIFORM_3CLASS_LOG_LOSS - best_ll > 1e-4)

    deployable = bool(
        winner
        and best_ll is not None
        and edge_vs_uniform
        and ranked[0][1] < UNIFORM_3CLASS_LOG_LOSS - 1e-4
        and len(ranked) >= 2
        and margin is not None
        and margin >= min_delta_log_loss
    )

    policy_calibration_ok = False
    policy_calibration_status = "no_winner"
    if winner:
        ece = by_config[winner].get("calibration_top_predicted_class_ece")
        if ece is None:
            policy_calibration_status = "missing_ece"
            policy_calibration_ok = False
        elif float(ece) < POLICY_CALIBRATION_MAX_ECE:
            policy_calibration_status = "ok"
            policy_calibration_ok = True
        else:
            policy_calibration_status = "above_threshold"
            policy_calibration_ok = False

    return {
        "schema_version": SCHEMA_VERSION,
        "primary_metric": "multiclass_log_loss",
        "secondary_metrics": ["balanced_accuracy", "macro_f1", "calibration_top_predicted_class_ece", "brier_score_multiclass_mean_squared_error"],
        "authoritative_winner_config": winner,
        "runner_up_config": runner,
        "winner_multiclass_log_loss": best_ll,
        "margin_log_loss_vs_runner_up": margin,
        "full_stack_beats_xgb_meta_stack_log_loss": (
            bool(ll_full is not None and ll_meta is not None and ll_full < ll_meta - 1e-6)
            if (ll_full is not None and ll_meta is not None)
            else None
        ),
        "full_fusion_beats_xgb_only_log_loss": (
            bool(ll_full is not None and ll_xgb is not None and ll_full < ll_xgb - 1e-6)
            if (ll_full is not None and ll_xgb is not None)
            else None
        ),
        "monte_carlo_improves_vs_fusion_without_mc_log_loss": mc_helps,
        "bayesian_fusion_improves_vs_meta_stack_log_loss": fusion_helps_vs_meta_stack,
        "bayesian_fusion_improves_vs_explicit_weighted_triplet_log_loss": fusion_helps_vs_explicit_weighted_triplet,
        "edge_vs_uniform_3class_baseline": edge_vs_uniform,
        "uniform_baseline_log_loss": UNIFORM_3CLASS_LOG_LOSS,
        "deployable_now_governance_heuristic": deployable,
        "policy_calibration_may_proceed_heuristic": policy_calibration_ok,
        "policy_calibration_status": policy_calibration_status,
        "trade_plan_work_may_proceed_heuristic": bool(deployable and policy_calibration_ok),
        "notes": (
            "Heuristic gates only — arch_competition.promotion_engine.decide_promotion applies to "
            "parallel-vs-cascade manifests, not this bundle. MC/Fusion deltas are paired-row deltas "
            "on the same timestamps."
        ),
    }


@dataclass
class StackBundleEvalOptions:
    allowed_et_dates: Optional[set[str]] = None
    min_paired_rows: int = 50
    min_delta_log_loss: float = 0.02
    max_rows: Optional[int] = None


def run_stack_bundle_evaluation(
    *,
    db_path: str,
    ticker: str,
    model_dir: Path,
    ml_horizon_slug: str,
    options: Optional[StackBundleEvalOptions] = None,
    modes: tuple[str, ...] = DEFAULT_ALL_MODES,
) -> dict[str, Any]:
    """
    Evaluate named stack configurations on identical RTH rows (intersection pairing).

    Returns a JSON-serializable manifest including per-config metrics and authority block.

    Isolation: single-model modes use only that model's fusion branch from run_base_models_once.
    xgb_plus_* modes use ml_predict._weighted_average with only the listed branches (renormalized).
    xgb_plus_lstm_plus_transformer is never the trained meta-learner; use meta_stack for that.
    """
    import bayesian_fusion
    from features.inference_snapshot import build_inference_snapshot_v1_from_db_row
    from features.replay_signal_input_v1 import signal_input_from_snapshot_row_dict
    from ml_scheduler import _load_rth_rows_for_ticker
    from regime_engine import classify_regime
    from rules_engine import compute_rules
    from train_all import preload_historical_db_for_eval

    import ml_predict as mp
    from prediction_engine import build_fusion_model_overlay_for_stack
    from signals import _run_model_stack, _spot_for_mc_fusion_adjustment

    opts = options or StackBundleEvalOptions()
    hz = normalize_ml_horizon_slug(ml_horizon_slug)
    target_column = outcome_column(hz)

    unknown = [m for m in modes if m not in VALID_MODES]
    if unknown:
        raise ValueError(f"Unknown mode(s) {unknown!r}. Valid: {sorted(VALID_MODES)}")

    rows = _load_rth_rows_for_ticker(db_path, ticker, label_column=target_column)
    if opts.allowed_et_dates is not None:
        rows = [r for r in rows if r.get("ts_et") and str(r["ts_et"])[:10] in opts.allowed_et_dates]
    if opts.max_rows is not None and opts.max_rows > 0:
        # Most recent slice (chronological tail), not a random subsample.
        rows = rows[-int(opts.max_rows) :]

    orig_model_dir = mp.MODEL_DIR
    htok = mp.set_ml_infer_horizon_slug(hz)
    buffers: dict[str, list[list[float]]] = {m: [] for m in modes}
    y_paired: list[int] = []
    rows_paired: list[dict] = []

    skip_reasons: dict[str, int] = {}

    def _bump(key: str) -> None:
        skip_reasons[key] = skip_reasons.get(key, 0) + 1

    try:
        mp.MODEL_DIR = Path(model_dir)
        mp.reset_caches()
        # One snapshot preload for the whole eval window — no per-row sqlite for history.
        _tss = [float(r["ts_utc"]) for r in rows if r.get("ts_utc") is not None]
        hist_db = (
            preload_historical_db_for_eval(db_path, ticker, max(_tss))
            if _tss
            else None
        )

        for row in rows:
            ts_utc = row.get("ts_utc")
            if not ts_utc:
                _bump("missing_ts_utc")
                continue
            try:
                inp = signal_input_from_snapshot_row_dict(row)
            except Exception as e:
                _bump(f"signal_input:{type(e).__name__}")
                log.debug("skip row signal_input: %s", e)
                continue
            try:
                inf_v1 = build_inference_snapshot_v1_from_db_row(
                    ticker=ticker,
                    expiry=None,
                    as_of_ts=float(ts_utc),
                    db_row=row,
                )
            except Exception as e:
                _bump(f"inference_snapshot:{type(e).__name__}")
                log.debug("skip row inf_v1: %s", e)
                continue
            mvp = inf_v1.get("features") or {}
            try:
                rules = compute_rules(inp, mvp_features=mvp)
                regime = classify_regime(inp, rules, mvp_features=mvp)
            except Exception as e:
                _bump(f"rules_regime:{type(e).__name__}")
                log.debug("skip row rules/regime: %s", e)
                continue

            try:
                snap = build_fusion_model_overlay_for_stack(
                    inp, hist_db, rules, inference_snapshot_v1=inf_v1
                )
            except Exception as e:
                _bump(f"fusion_overlay:{type(e).__name__}")
                log.debug("skip row fusion overlay: %s", e)
                continue

            try:
                once = mp.run_base_models_once(
                    snap,
                    ticker,
                    hist_db,
                    getattr(rules, "signal", "wait") or "wait",
                    inference_snapshot_v1=inf_v1,
                )
            except Exception as e:
                _bump(f"run_base_models_once:{type(e).__name__}")
                log.debug("skip row base models: %s", e)
                continue

            fused_pack = once.get("fusion") or {}
            xgb_d = _fusion_branch_to_prob_dict(fused_pack.get("xgb"))
            lstm_d = _fusion_branch_to_prob_dict(fused_pack.get("lstm"))
            tr_d = _fusion_branch_to_prob_dict(fused_pack.get("transformer"))

            spk = stack_probs_bundle_key()
            meta_probs: Optional[list[float]] = None
            if META_STACK_MODE in modes:
                stack_d = once.get(spk)
                meta_probs = _dict_to_probs(stack_d) if stack_d else None
                if meta_probs is None:
                    meta_probs = _weighted_blend_probs(mp, ticker, xgb_d=xgb_d, lstm_d=lstm_d, tr_d=tr_d)

            row_probs: dict[str, Optional[list[float]]] = {m: None for m in modes}

            if "xgb_only" in modes:
                row_probs["xgb_only"] = _probs_from_fusion_branch(fused_pack.get("xgb"))
            if "lstm_only" in modes:
                row_probs["lstm_only"] = _probs_from_fusion_branch(fused_pack.get("lstm"))
            if "transformer_only" in modes:
                row_probs["transformer_only"] = _probs_from_fusion_branch(fused_pack.get("transformer"))
            if "xgb_plus_lstm" in modes:
                row_probs["xgb_plus_lstm"] = _weighted_blend_probs(
                    mp, ticker, xgb_d=xgb_d, lstm_d=lstm_d, tr_d=None
                )
            if "xgb_plus_transformer" in modes:
                row_probs["xgb_plus_transformer"] = _weighted_blend_probs(
                    mp, ticker, xgb_d=xgb_d, lstm_d=None, tr_d=tr_d
                )
            if "xgb_plus_lstm_plus_transformer" in modes:
                row_probs["xgb_plus_lstm_plus_transformer"] = _weighted_blend_probs(
                    mp, ticker, xgb_d=xgb_d, lstm_d=lstm_d, tr_d=tr_d
                )
            if META_STACK_MODE in modes:
                row_probs[META_STACK_MODE] = meta_probs

            # Full stack + MC + fusion requires _run_model_stack
            fusion_payload_base: Any = None
            fusion_payload_full: Any = None
            if "full_fusion" in modes or "fusion_without_mc" in modes:
                try:
                    from features.monte_carlo_stack_input import (
                        MonteCarloStackInputError,
                        resolve_monte_carlo_stack_inputs,
                    )

                    _smc = None
                    _mc_e = None
                    try:
                        _smc = resolve_monte_carlo_stack_inputs(inp, inf_v1)
                    except MonteCarloStackInputError as e:
                        _mc_e = e
                    try:
                        from ml_predict import build_xgb_pre_engineering_snapshot_for_tick

                        _xgb_pre = build_xgb_pre_engineering_snapshot_for_tick(inf_v1, snap)
                    except Exception:
                        _xgb_pre = None
                    xgb_out, lstm_out, transformer_out, mc_out, _mlb = _run_model_stack(
                        inp,
                        rules,
                        regime,
                        hist_db,
                        inference_snapshot_v1=inf_v1,
                        fusion_overlay=snap,
                        mc_spot_ctx=_smc,
                        mc_context_error=_mc_e,
                        xgb_pre_engineering_snapshot=_xgb_pre,
                    )
                    _fusion_tc = bayesian_fusion.build_fusion_tick_cache(regime, rules)
                    fusion_payload_base = bayesian_fusion.fuse(
                        regime,
                        xgb_out,
                        lstm_out,
                        transformer_out,
                        mc_out,
                        rules,
                        signal_layer_v1=inf_v1.get("signal_layer_v1"),
                        fusion_tick_cache=_fusion_tc,
                    )
                    fusion_payload_full = fusion_payload_base
                    try:
                        from mc_fusion_adjustment import fuse_payload_apply_mc_adjustment

                        _adj_spot = _spot_for_mc_fusion_adjustment(_smc, inf_v1)
                        fusion_payload_full = fuse_payload_apply_mc_adjustment(
                            fusion_payload_base,
                            mc_out,
                            _adj_spot,
                        )
                    except Exception:
                        fusion_payload_full = fusion_payload_base
                except Exception as e:
                    _bump(f"fusion_stack:{type(e).__name__}")
                    log.debug("skip row fusion stack: %s", e)

                if fusion_payload_base is not None and "fusion_without_mc" in modes:
                    row_probs["fusion_without_mc"] = _norm_triplet(
                        float(fusion_payload_base.prob_up),
                        float(fusion_payload_base.prob_down),
                        float(fusion_payload_base.prob_flat),
                    )
                if fusion_payload_full is not None and "full_fusion" in modes:
                    row_probs["full_fusion"] = _norm_triplet(
                        float(fusion_payload_full.prob_up),
                        float(fusion_payload_full.prob_down),
                        float(fusion_payload_full.prob_flat),
                    )

            outcome_raw = row.get(target_column)
            yt = _outcome_class_index(outcome_raw)
            if yt is None:
                _bump(f"missing_or_invalid_outcome:{outcome_raw!r}")
                continue

            if all(row_probs.get(m) is not None for m in modes):
                for m in modes:
                    buffers[m].append(row_probs[m])  # type: ignore[arg-type]
                y_paired.append(yt)
                rows_paired.append(row)
            else:
                _bump("incomplete_mode_set")

    finally:
        mp.MODEL_DIR = orig_model_dir
        mp.reset_caches()
        mp.reset_ml_infer_horizon_slug(htok)

    by_config: dict[str, Any] = {}
    for m in modes:
        probs = buffers.get(m) or []
        y = y_paired
        if len(probs) == len(y) and len(y) >= MIN_SAMPLES_STATISTICAL:
            by_config[m] = _pack_full_metrics(m, y, probs, rows_paired)
        else:
            by_config[m] = {
                "config": m,
                "n_rows_scored": len(probs),
                "error": "insufficient_paired_rows_or_alignment",
            }

    authority = _authority_block(
        by_config,
        min_rows=opts.min_paired_rows,
        min_delta_log_loss=opts.min_delta_log_loss,
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "evaluation_contract": {
            "time_ordering": "rows from _load_rth_rows_for_ticker ORDER BY ts_utc ASC (no random shuffle)",
            "label_column": target_column,
            "ml_horizon_slug": hz,
            "pairing": "A row is scored only if every requested mode produced a probability triplet.",
            "leakage_audit": (
                "InferenceSnapshotV1 built with as_of_ts = row ts_utc. preload_historical_db_for_eval loads "
                "rows with ts_utc < max(row ts_utc) once; PreloadedHistoricalDB.get_recent_snapshots filters "
                "each call to ts_utc < as_of_ts_utc (per-row causal slice). Outcomes excluded when "
                "target_column is null or not in {up, down, flat} (never fabricated as flat)."
            ),
            "outcome_validity": "Rows without valid outcome labels are skipped before pairing (see skip_reason_counts).",
            "primary_metric": "multiclass_log_loss",
            "promotion_engine_note": (
                "arch_competition.promotion_engine.decide_promotion remains the governed contract for "
                "parallel-vs-cascade artifact promotion; this bundle answers stack/MC/fusion authority separately."
            ),
            "meta_stack_vs_explicit_triplet": (
                "meta_stack uses trained logistic meta-learner on 9 stacked probs when meta_*.pkl exists; "
                "xgb_plus_lstm_plus_transformer always uses fixed _weighted_average (0.40/0.35/0.25) with no meta."
            ),
        },
        "mode_definitions": {k: MODE_DEFINITIONS[k] for k in modes if k in MODE_DEFINITIONS},
        "db_path": str(Path(db_path).resolve()),
        "ticker": ticker.upper(),
        "model_dir": str(Path(model_dir).resolve()),
        "allowed_et_dates": sorted(opts.allowed_et_dates) if opts.allowed_et_dates else None,
        "ml_horizon_slug": hz,
        "modes_requested": list(modes),
        "rows_loaded": len(rows),
        "max_rows_cap": opts.max_rows,
        "paired_rows_all_modes": len(y_paired),
        "skip_reason_counts": skip_reasons,
        "metrics_by_config": by_config,
        "authority_decision": authority,
    }


# --- tests / tooling: expose metric packer ---
def pack_metrics_for_probs(
    name: str,
    y_true: list[int],
    prob_rows: list[list[float]],
    rows_used: Optional[list[dict]] = None,
) -> dict[str, Any]:
    return _pack_full_metrics(name, y_true, prob_rows, rows_used or [])
