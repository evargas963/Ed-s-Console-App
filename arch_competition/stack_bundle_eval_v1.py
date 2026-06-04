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
from functools import lru_cache
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
    Explicit blend among provided branches only.
    Missing branches are omitted (weights renormalized over XGB=0.40, LSTM=0.35, TR=0.25).
    Full triple delegates to ml_predict._weighted_average (collapse-aware).
    """
    if xgb_d is not None and lstm_d is not None and tr_d is not None:
        collapsed = mp._active_base_collapse_flags(ticker)
        wa = mp._weighted_average(ticker, xgb_d, lstm_d, tr_d, collapsed=collapsed)
        return _dict_to_probs(wa)

    collapsed: set = set()
    try:
        collapsed = mp._active_base_collapse_flags(ticker)
    except Exception:
        pass

    base_weights = (
        ("xgb", xgb_d, 0.40),
        ("lstm", lstm_d, 0.35),
        ("transformer", tr_d, 0.25),
    )
    healthy = [
        (name, p, w)
        for name, p, w in base_weights
        if p is not None and name not in collapsed and _dict_to_probs(p) is not None
    ]
    if not healthy:
        return None

    total_w = sum(w for _, _, w in healthy)
    if total_w <= 0:
        return None

    acc = {"up": 0.0, "down": 0.0, "flat": 0.0}
    for _name, probs, w in healthy:
        tri = _dict_to_probs(probs)
        assert tri is not None
        nw = w / total_w
        acc["up"] += tri[0] * nw
        acc["down"] += tri[1] * nw
        acc["flat"] += tri[2] * nw
    return _norm_triplet(acc["up"], acc["down"], acc["flat"])


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
        mp.MODEL_DIR = _models_root_from_bundle_dir(Path(model_dir))
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
                    _bpu = getattr(fusion_payload_base, "prob_up", None)
                    _bpd = getattr(fusion_payload_base, "prob_down", None)
                    _bpf = getattr(fusion_payload_base, "prob_flat", None)
                    if _bpu is not None and _bpd is not None and _bpf is not None:
                        row_probs["fusion_without_mc"] = _norm_triplet(
                            float(_bpu), float(_bpd), float(_bpf)
                        )
                    else:
                        _bump("fusion_without_mc:null_probs")
                if fusion_payload_full is not None and "full_fusion" in modes:
                    _pu = getattr(fusion_payload_full, "prob_up", None)
                    _pd = getattr(fusion_payload_full, "prob_down", None)
                    _pf = getattr(fusion_payload_full, "prob_flat", None)
                    if _pu is not None and _pd is not None and _pf is not None:
                        row_probs["full_fusion"] = _norm_triplet(
                            float(_pu), float(_pd), float(_pf)
                        )
                    else:
                        _bump("full_fusion:null_probs")

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


WHOLE_STACK_FEATURE_ABLATION_SCHEMA = "1"
WHOLE_STACK_DECISION_MODE = "full_fusion"


def _models_root_from_bundle_dir(model_dir: Path) -> Path:
    """mp.MODEL_DIR must be repo ``models/`` — not the per-ticker leaf passed by callers."""
    md = Path(model_dir).resolve()
    if any(md.glob("xgb_*.pkl")) or any(md.glob("lstm_*.pt")) or any(md.glob("transformer_*.pt")):
        return md.parent.parent
    return md


def _synthetic_ablation_snapshot_rows() -> tuple[dict, dict]:
    """Two distinct synthetic rows for engineer_features → raw snapshot dependency map."""
    from ml_train import CATEGORICALS, SCALE_INVARIANT_COLS, WALL_DISTANCE_COLS

    row1: dict[str, Any] = {
        "ticker": "SPY",
        "ts_utc": 1_700_000_000.0,
        "spot": 100.0,
        "outcome_1c": "up",
        "et_hour": 10,
        "et_minute": 15,
        "candle_body_pts": 0.5,
        "candle_range_pts": 1.0,
        "nearest_above_dist": 1.0,
        "nearest_below_dist": 1.0,
        "vwap_dist_pts": 0.25,
        "flow_imbalance": 0.55,
        "bid_ask_imbalance": 0.55,
        "candle_volume": 1000.0,
        "net_gamma": 1.0,
    }
    for c in list(WALL_DISTANCE_COLS) + list(SCALE_INVARIANT_COLS):
        row1.setdefault(c, 1.0)
    for c in CATEGORICALS:
        row1.setdefault(c, "neutral")
    row1["zone"] = "pin_neutral"
    row1["vwap_side"] = "above"
    row2 = {
        **row1,
        "ts_utc": row1["ts_utc"] + 60.0,
        "candle_volume": 1100.0,
        "net_gamma": 2.0,
    }
    return row1, row2


@lru_cache(maxsize=1)
def _xgb_engineered_to_raw_deps() -> dict[str, frozenset[str]]:
    """Engineered XGB column → raw DB snapshot keys (cached; drives grouped permutation)."""
    import functools

    @functools.lru_cache(maxsize=1)
    def _build() -> dict[str, frozenset[str]]:
        import pandas as pd
        from ml_train import engineer_features

        row1, row2 = _synthetic_ablation_snapshot_rows()
        df0 = pd.DataFrame([row1, row2])
        X0, feat_names, _, _ = engineer_features(df0)
        raw_keys = set(row1.keys()) - {"ticker", "outcome_1c", "ts_utc"}
        deps: dict[str, set[str]] = {str(n): set() for n in feat_names}
        for raw in sorted(raw_keys):
            base = row1[raw]
            perturbed: list[Any]
            if isinstance(base, str):
                perturbed = [f"perturb_{base}", "alt_" + base[:3]]
            else:
                try:
                    fv = float(base)
                except (TypeError, ValueError):
                    continue
                perturbed = [fv * 1.37 + 0.17, fv * -0.83 + 0.42]
            for new_val in perturbed:
                r_pert = dict(row1)
                r_pert[raw] = new_val
                df_pert = pd.DataFrame([r_pert, row2])
                Xp, _, _, _ = engineer_features(df_pert)
                for n in feat_names:
                    if n not in X0.columns or n not in Xp.columns:
                        continue
                    v0 = X0[n].to_numpy(dtype=np.float64)
                    vp = Xp[n].to_numpy(dtype=np.float64)
                    if not np.allclose(v0, vp, rtol=0, atol=1e-9, equal_nan=True):
                        deps[str(n)].add(raw)
        return {k: frozenset(v) for k, v in deps.items()}

    return _build()


def xgb_engineered_members_to_raw_snapshot(engineered: list[str]) -> list[str]:
    """Map manifest XGB engineered members to raw snapshot columns for permutation."""
    dep = _xgb_engineered_to_raw_deps()
    out: set[str] = set()
    for n in engineered:
        out.update(dep.get(n, ()))
    return sorted(out)


def group_snapshot_columns(group: dict) -> list[str]:
    """Union of raw DB snapshot columns for one manifest ABLATE group (all model streams)."""
    members = group.get("members") or {}
    out: set[str] = set()
    for key in ("lstm_5m", "lstm_1m"):
        out.update(members.get(key) or [])
    xgb_eng = members.get("xgb") or []
    if xgb_eng:
        out.update(xgb_engineered_members_to_raw_snapshot(xgb_eng))
    return sorted(out)


def permute_snapshot_columns_across_rows(
    rows: list[dict],
    columns: list[str],
    rng: np.random.Generator,
) -> list[dict]:
    """Grouped permutation on raw DB snapshot columns — one row shuffle for all group members."""
    if len(rows) < 2:
        return [dict(r) for r in rows]
    present = [c for c in columns if any(c in r for r in rows)]
    if not present:
        return [dict(r) for r in rows]
    perm = rng.permutation(len(rows))
    out = [dict(r) for r in rows]
    for col in present:
        shuffled = [rows[int(i)].get(col) for i in perm]
        for i, val in enumerate(shuffled):
            out[i][col] = val
    return out


# Full per-model × horizon primary matrix size (O-56): 3 models × 4 horizons × ablation groups =
# 828 scored cells. resolve_ablation_drop_group_ids requires a COMPLETE primary matrix before it
# will consider any report-derived drop; the legacy 276-cell partial threshold is retired.
# (The old DEFAULT_ABLATION_DROP_GROUP_IDS 12-tuple was a fabricated fallback — it silently dropped
# volume/vwap/iv/price_candle, which are not verified non-survivors — and has been removed. The
# money path now fails closed to the full feature set unless drops are confirm-verified.)
ABLATION_FULL_MATRIX_CELL_TARGET: int = 828

# Never null these raw snapshot keys — required for labels, joins, pct math, sequence encode.
ABLATION_SURVIVOR_PROTECTED_SNAPSHOT_COLUMNS: frozenset[str] = frozenset(
    {
        "spot",
        "ticker",
        "timeframe",
        "ts_utc",
        "ts_et",
        "et_hour",
        "et_minute",
        "outcome_1c",
        "outcome_5c",
        "outcome_15c",
        "outcome_60c",
        "outcome_filled",
    }
)

ABLATION_SURVIVORS_ENV = "ED_APPLY_ABLATION_SURVIVORS"
ABLATION_DROP_GROUPS_ENV = "ED_ABLATION_DROP_GROUPS"
ABLATION_MANIFEST_PATH = Path("governance/artifacts/feature_ablation_manifest.json")
ABLATION_REPORT_PATH = Path("governance/artifacts/feature_ablation_report.json")
# Bump when confirm holdout transform order changes; preflight blocks until --ablation-confirm re-run.
ABLATION_CONFIRM_PATH_VERSION = "2"


def ablation_survivors_training_enabled() -> bool:
    import os

    # Ablation primary/confirm passes score on the FULL feature set — never apply survivor
    # drops while measuring MCC delta or drop-and-refit (chicken-and-egg with confirm pass).
    if os.environ.get("ED_ABLATION_SCORED_EVAL", "").strip().lower() in ("1", "true", "yes"):
        return False
    return os.environ.get(ABLATION_SURVIVORS_ENV, "").strip().lower() in ("1", "true", "yes")


def ablation_confirm_pass_complete(
    survivor_summary: dict | None = None,
    *,
    require_current_path: bool = True,
) -> bool:
    """True when survivor_summary.confirm_pass is populated and matches the current confirm path."""
    if survivor_summary is None:
        if not ABLATION_REPORT_PATH.is_file():
            return False
        try:
            report = json.loads(ABLATION_REPORT_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            return False
        survivor_summary = report.get("survivor_summary") or {}
    confirm = survivor_summary.get("confirm_pass")
    if not isinstance(confirm, dict) or not confirm.get("cells"):
        return False
    if require_current_path:
        return confirm.get("confirm_path_version") == ABLATION_CONFIRM_PATH_VERSION
    return True


def confirmed_drop_group_ids_by_model_horizon(
    survivor_summary: dict,
) -> dict[tuple[str, str], set[str]]:
    """O-56-faithful per-cell drop sets: {(model_family, horizon_slug): {group_id, ...}}.

    A group is included for a cell ONLY when the confirm pass (drop-and-refit) verified it
    ``safe_to_drop`` for that cell on EVERY anchor. The primary pass's DROP_CANDIDATE
    recommendation is a screen, not a verified drop — never sufficient on its own.

    Confirm cells carry ``dropped_groups`` (batched DROP set per anchor); legacy ``group_id`` /
    ``group_ids`` are also accepted.
    """
    from collections import defaultdict

    out: dict[tuple[str, str], set[str]] = {}
    confirm = survivor_summary.get("confirm_pass")
    if not isinstance(confirm, dict):  # live report carries a status string until the pass runs
        return out
    cells = [c for c in (confirm.get("cells") or []) if c.get("status") == "ok"]
    by_mh: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for cell in cells:
        key = (str(cell.get("model_family")), str(cell.get("horizon_slug")))
        by_mh[key].append(cell)

    anchors_required = int(confirm.get("anchors_required") or 0)
    for key, group in by_mh.items():
        safe = [c for c in group if c.get("safe_to_drop")]
        need = anchors_required if anchors_required > 0 else len(group)
        if len(safe) < need:
            continue
        batch_sets: list[set[str]] = []
        for c in safe:
            dg: list[str] = list(c.get("dropped_groups") or [])
            if c.get("group_id"):
                dg.append(str(c["group_id"]))
            if c.get("group_ids"):
                dg.extend(str(g) for g in c["group_ids"])
            batch_sets.append({str(g) for g in dg if g})
        if not batch_sets:
            continue
        intersection = set.intersection(*batch_sets)
        if intersection:
            out[key] = intersection
    return out


def globally_safe_drop_group_ids(survivor_summary: dict) -> list[str]:
    """Groups safe to null in the SHARED snapshot: the INTERSECTION of confirm-verified per-cell
    drops across every cell. A group survives the mask if ANY (model, horizon) still needs it."""
    by_cell = confirmed_drop_group_ids_by_model_horizon(survivor_summary)
    if not by_cell:
        return []
    return sorted(set.intersection(*by_cell.values()))


def resolve_ablation_drop_group_ids() -> list[str]:
    """Feature groups to null in the SHARED snapshot/dataframe when ED_APPLY_ABLATION_SURVIVORS=1.

    The snapshot is the ONE shared input to every model (XGB tabular + LSTM/Transformer channels),
    so this mask is necessarily GLOBAL: a group is only safe to drop here when it is a confirm-
    verified non-survivor for EVERY (model, horizon) cell (the intersection). True per-model ×
    horizon survivor sets (O-56) are applied at each model's feature assembly via
    confirmed_drop_group_ids_by_model_horizon(), NOT by destroying shared snapshot columns.

    Fail-closed: returns [] (train/serve on the FULL feature set) unless there is an explicit
    ED_ABLATION_DROP_GROUPS override, OR a COMPLETE primary matrix (>= ABLATION_FULL_MATRIX_CELL_TARGET
    scored cells) WITH a populated confirm pass yielding a globally-safe intersection. The primary-
    pass MCC-delta screen alone never deletes features from the money path; there is no fabricated
    default drop set.
    """
    import os

    if not ablation_survivors_training_enabled():
        return []
    override = (os.environ.get(ABLATION_DROP_GROUPS_ENV) or "").strip()
    if override:
        return sorted({g.strip() for g in override.split(",") if g.strip()})
    report_path = ABLATION_REPORT_PATH
    if not report_path.is_file():
        log.warning(
            "ablation survivor mask ON but no report at %s; fail-closed (full feature set).",
            report_path,
        )
        return []
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError) as e:
        log.warning("ablation survivor mask: report unreadable (%s); fail-closed.", e)
        return []
    ss = report.get("survivor_summary") or {}
    scored = int(ss.get("scored_cell_count") or 0)
    if scored < ABLATION_FULL_MATRIX_CELL_TARGET:
        log.warning(
            "ablation survivor mask: primary matrix incomplete (%d/%d scored); fail-closed.",
            scored, ABLATION_FULL_MATRIX_CELL_TARGET,
        )
        return []
    drop_ids = globally_safe_drop_group_ids(ss)
    if not drop_ids:
        log.warning(
            "ablation survivor mask: no confirm-verified globally-safe drops (run --ablation-confirm; "
            "per-model survivors apply at feature assembly, not the shared snapshot); "
            "fail-closed (full feature set)."
        )
    return drop_ids


@lru_cache(maxsize=1)
def _ablation_drop_snapshot_columns_cached() -> tuple[str, ...]:
    """Cached column list — extract/train loops call apply_ablation per row."""
    drop_groups = resolve_ablation_drop_group_ids()
    if not drop_groups:
        return ()
    if not ABLATION_MANIFEST_PATH.is_file():
        log.warning("ablation survivor mask: manifest missing at %s", ABLATION_MANIFEST_PATH)
        return ()
    try:
        manifest = json.loads(ABLATION_MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        log.warning("ablation survivor mask: manifest read failed: %s", e)
        return ()
    groups_by_id = {g["group_id"]: g for g in manifest.get("groups") or []}
    cols: set[str] = set()
    for gid in drop_groups:
        grp = groups_by_id.get(gid)
        if not grp:
            log.warning("ablation survivor mask: unknown group_id %r", gid)
            continue
        cols.update(group_snapshot_columns(grp))
    return tuple(sorted(c for c in cols if c not in ABLATION_SURVIVOR_PROTECTED_SNAPSHOT_COLUMNS))


def ablation_drop_snapshot_columns() -> list[str]:
    """Raw DB columns to null when survivor mask is active."""
    return list(_ablation_drop_snapshot_columns_cached())


# Categoricals with locked MVP vocabulary — must null to None/NA, not generic "neutral".
ABLATION_MVP_LOCKED_CATEGORICAL_COLUMNS: frozenset[str] = frozenset(
    {"zone", "prev_zone", "vwap_side"}
)


def ablation_null_value_for_snapshot_column(col: str, *, for_pandas: bool = False):
    """Null-out value for one dropped snapshot column (train + ablation confirm pass)."""
    from ml_train import CATEGORICALS

    if col in ABLATION_MVP_LOCKED_CATEGORICAL_COLUMNS:
        if for_pandas:
            import pandas as pd

            return pd.NA
        return None
    if col in CATEGORICALS:
        return "neutral"
    if for_pandas:
        import pandas as pd

        return pd.NA
    return None


def drop_snapshot_columns_across_rows(
    rows: list[dict],
    columns: list[str],
) -> list[dict]:
    """Null-out raw DB snapshot columns for confirm pass (pre-retrain inference drop)."""
    present = [c for c in columns if any(c in r for r in rows)]
    if not present:
        return [dict(r) for r in rows]
    out = [dict(r) for r in rows]
    for col in present:
        for row in out:
            if col not in row:
                continue
            row[col] = ablation_null_value_for_snapshot_column(col)
    return out


def ablation_survivors_fingerprint_part() -> str:
    """Cache-key fragment when survivor mask is on (global + per-model×horizon confirm drops)."""
    if not ablation_survivors_training_enabled():
        return "ablation_survivors=off"
    global_part = ",".join(resolve_ablation_drop_group_ids())
    per_model_part = "unavailable"
    try:
        if ABLATION_REPORT_PATH.is_file():
            report = json.loads(ABLATION_REPORT_PATH.read_text(encoding="utf-8"))
            by_cell = confirmed_drop_group_ids_by_model_horizon(report.get("survivor_summary") or {})
            per_model_part = "|".join(
                f"{m}/{h}:{','.join(sorted(g))}" for (m, h), g in sorted(by_cell.items())
            )
    except (OSError, json.JSONDecodeError, ValueError):
        pass
    return f"ablation_survivors=on|global={global_part}|per_model={per_model_part}"


def apply_ablation_survivor_nulls_to_snapshot(row: dict) -> dict:
    """In-place null-out of DROP-group raw columns (train + live when env is on)."""
    cols = _ablation_drop_snapshot_columns_cached()
    if not cols:
        return row
    out = dict(row)
    for col in cols:
        if col not in out:
            continue
        out[col] = ablation_null_value_for_snapshot_column(col)
    return out


def apply_ablation_survivor_nulls_to_dataframe(df):
    """Apply survivor mask to a training DataFrame (column-wise)."""
    cols = ablation_drop_snapshot_columns()
    if not cols or df is None or len(df) == 0:
        return df
    out = df.copy()
    for col in cols:
        if col not in out.columns:
            continue
        out[col] = ablation_null_value_for_snapshot_column(col, for_pandas=True)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# O-56 PER-MODEL × HORIZON survivor application (the ablated-training path).
# Each base model trains on ITS OWN survivor set for the horizon being trained — this is what
# "train on the ablated data" means. Full-feature training is NOT a valid retrain target when an
# ablation matrix exists (AGENTS §Ablation contract). These resolvers FAIL LOUD (raise) when
# survivors are enabled but the matrix is missing/incomplete — they never silently fall through to
# full features on a real retrain.
# ─────────────────────────────────────────────────────────────────────────────
class AblatedTrainingUnavailable(RuntimeError):
    """Survivors enabled for a retrain but the ablation matrix can't be applied — fail loud."""


def _load_ablation_report_or_raise() -> dict:
    if not ABLATION_REPORT_PATH.is_file():
        raise AblatedTrainingUnavailable(
            f"ED_APPLY_ABLATION_SURVIVORS=1 but no ablation report at {ABLATION_REPORT_PATH}; "
            "run the ablation before an ablated retrain (full-feature training is not a valid target)."
        )
    try:
        return json.loads(ABLATION_REPORT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError) as e:
        raise AblatedTrainingUnavailable(f"ablation report unreadable: {e}") from e


def _load_ablation_manifest_or_raise() -> dict:
    if not ABLATION_MANIFEST_PATH.is_file():
        raise AblatedTrainingUnavailable(f"ablation manifest missing at {ABLATION_MANIFEST_PATH}")
    try:
        return json.loads(ABLATION_MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError) as e:
        raise AblatedTrainingUnavailable(f"ablation manifest unreadable: {e}") from e


@lru_cache(maxsize=None)
def ablated_drop_group_ids_for_model_horizon(model_family: str, horizon_slug: str) -> list[str]:
    """The ablation's DROP set for one (model, horizon) cell (O-56). Requires confirm-verified

    Cached: the report/manifest are static within a training process, and this is called per-row by
    the sequence-model mask — without the cache it re-reads + re-parses the ~900KB report on every
    snapshot (catastrophic O(rows × file-parse)). Cache makes it one parse per (model, horizon).
    drops only; primary-pass DROP_CANDIDATE is never applied on the money path.
    Raises AblatedTrainingUnavailable if the matrix is missing/incomplete or confirm not run."""
    ss = _load_ablation_report_or_raise().get("survivor_summary") or {}
    scored = int(ss.get("scored_cell_count") or 0)
    if scored < ABLATION_FULL_MATRIX_CELL_TARGET:
        raise AblatedTrainingUnavailable(
            f"ablation matrix incomplete ({scored}/{ABLATION_FULL_MATRIX_CELL_TARGET} scored); "
            "cannot apply per-model survivors."
        )
    key = (str(model_family), str(horizon_slug))
    if not ablation_confirm_pass_complete(ss):
        raise AblatedTrainingUnavailable(
            "ED_APPLY_ABLATION_SURVIVORS=1 requires a completed --ablation-confirm pass "
            "(survivor_summary.confirm_pass must be {cells:[...]}). Primary-pass DROP_CANDIDATE "
            "recommendations are never applied on the money path."
        )
    confirmed = confirmed_drop_group_ids_by_model_horizon(ss)
    return sorted(confirmed.get(key, set()))


@lru_cache(maxsize=None)
def ablated_drop_members_for_model_horizon(
    model_family: str, horizon_slug: str
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Resolve a cell's DROP groups to concrete members: (xgb_cols, lstm_5m, lstm_1m). Cached
    (static within a process); returns tuples so the cached value can't be mutated by callers."""
    drop_ids = ablated_drop_group_ids_for_model_horizon(model_family, horizon_slug)
    if not drop_ids:
        return (), (), ()
    from tools.feature_curation_gate import _drop_members_for_model

    xgb, m5, m1 = _drop_members_for_model(_load_ablation_manifest_or_raise(), list(drop_ids))
    return tuple(xgb), tuple(m5), tuple(m1)


@lru_cache(maxsize=None)
def ablation_drop_snapshot_columns_for_model_horizon(model_family: str, horizon_slug: str) -> tuple[str, ...]:
    """Raw snapshot columns to null for one (model, horizon) cell — the sequence-model survivor mask
    operates at the snapshot level (the encoder turns nulled columns into absence flags)."""
    drop_ids = ablated_drop_group_ids_for_model_horizon(model_family, horizon_slug)
    if not drop_ids:
        return ()
    manifest = _load_ablation_manifest_or_raise()
    by_id = {g["group_id"]: g for g in manifest.get("groups") or []}
    cols: set[str] = set()
    for gid in drop_ids:
        grp = by_id.get(gid)
        if grp:
            cols.update(group_snapshot_columns(grp))
    return tuple(sorted(c for c in cols if c not in ABLATION_SURVIVOR_PROTECTED_SNAPSHOT_COLUMNS))


def apply_ablation_survivor_nulls_to_snapshot_for_model(snap, *, model_family: str, horizon_slug: str):
    """Per-row sequence-model survivor mask: null this (model, horizon) cell's dropped snapshot
    columns. No-op when survivors off. Fail-loud (raises) if the matrix can't be applied."""
    if not ablation_survivors_training_enabled() or not isinstance(snap, dict):
        return snap
    cols = ablation_drop_snapshot_columns_for_model_horizon(model_family, horizon_slug)
    if not cols:
        return snap
    for col in cols:
        if col in snap:
            snap[col] = ablation_null_value_for_snapshot_column(col, for_pandas=False)
    return snap


def null_snapshot_dict_for_drop_groups(
    snap: dict,
    manifest: dict,
    drop_group_ids: list[str],
) -> dict:
    """Confirm-path snapshot nulling — does not require confirm_pass or survivors env."""
    if not drop_group_ids or not isinstance(snap, dict):
        return snap
    by_id = {g["group_id"]: g for g in (manifest.get("groups") or [])}
    cols: set[str] = set()
    for gid in drop_group_ids:
        grp = by_id.get(gid)
        if grp:
            cols.update(group_snapshot_columns(grp))
    out = dict(snap)
    for col in cols:
        if col in out and col not in ABLATION_SURVIVOR_PROTECTED_SNAPSHOT_COLUMNS:
            out[col] = ablation_null_value_for_snapshot_column(col, for_pandas=False)
    return out


def null_snapshot_dataframe_for_drop_groups(df, manifest: dict, drop_group_ids: list[str]):
    """Confirm-path tabular nulling — mirrors production raw-null step before engineer_features."""
    if df is None or len(df) == 0 or not drop_group_ids:
        return df
    by_id = {g["group_id"]: g for g in (manifest.get("groups") or [])}
    cols: set[str] = set()
    for gid in drop_group_ids:
        grp = by_id.get(gid)
        if grp:
            cols.update(group_snapshot_columns(grp))
    out = df.copy()
    for col in cols:
        if col in out.columns and col not in ABLATION_SURVIVOR_PROTECTED_SNAPSHOT_COLUMNS:
            out[col] = ablation_null_value_for_snapshot_column(col, for_pandas=True)
    return out


def drop_ablated_xgb_engineered_columns(
    X,
    feat_names: list[str],
    horizon_slug: str,
) -> tuple[Any, list[str], int]:
    """Remove confirm-verified XGB engineered columns after ``engineer_features`` (O-56).

    Production must match ``--ablation-confirm`` holdout refit, which drops engineered names
    post-engineer — not raw snapshot columns pre-engineer (many manifest xgb members are
    engineered-only and never appear on the raw training frame).
    """
    xcols, _, _ = ablated_drop_members_for_model_horizon("xgb", horizon_slug)
    drop_set = {c for c in xcols if c not in ABLATION_SURVIVOR_PROTECTED_SNAPSHOT_COLUMNS}
    if not drop_set:
        return X, feat_names, 0
    keep = [f for f in feat_names if f not in drop_set]
    n_dropped = len(feat_names) - len(keep)
    if n_dropped == 0:
        return X, feat_names, 0
    return X[keep], keep, n_dropped


def apply_ablation_survivor_nulls_to_dataframe_for_model(df, *, model_family: str, horizon_slug: str):
    """Null raw snapshot columns for one (model, horizon) cell before feature engineering.

    XGB also drops engineered survivors in ``train_ticker`` via ``drop_ablated_xgb_engineered_columns``
    after ``engineer_features`` — matching the confirm-pass refit path."""
    if not ablation_survivors_training_enabled() or df is None or len(df) == 0:
        return df
    drop_ids = ablated_drop_group_ids_for_model_horizon(model_family, horizon_slug)
    if not drop_ids:
        return df
    manifest = _load_ablation_manifest_or_raise()
    by_id = {g["group_id"]: g for g in manifest.get("groups") or []}
    raw_cols: set[str] = set()
    for gid in drop_ids:
        grp = by_id.get(gid)
        if grp:
            raw_cols.update(group_snapshot_columns(grp))
    if model_family == "xgb":
        xcols, _, _ = ablated_drop_members_for_model_horizon("xgb", horizon_slug)
        for col in xcols:
            if col in df.columns:
                raw_cols.add(col)
    drop = sorted(
        c for c in raw_cols
        if c not in ABLATION_SURVIVOR_PROTECTED_SNAPSHOT_COLUMNS and c in df.columns
    )
    if not drop:
        return df
    out = df.copy()
    for col in drop:
        out[col] = ablation_null_value_for_snapshot_column(col, for_pandas=True)
    return out


def zero_ablated_sequence_channels_for_model(
    X_5m: np.ndarray,
    X_1m: np.ndarray,
    mask_5m: np.ndarray,
    mask_1m: np.ndarray,
    *,
    model_family: str,
    horizon_slug: str,
    features_5m: list[str],
    features_1m: list[str],
    encoded_features_5m: list[str],
    encoded_features_1m: list[str],
) -> tuple[np.ndarray, np.ndarray]:
    """Zero post-normalize LSTM/Transformer channels for confirm-verified drops (O-56).

    Matches ``--ablation-confirm`` holdout refit when groups carry lstm stream members; also
    zeros channels mapped from raw members present on the encoded streams."""
    from tools.feature_curation_gate import (
        _post_mask_channel_indices,
        _pre_mask_encoded_indices,
    )

    _, m5_raw, m1_raw = ablated_drop_members_for_model_horizon(model_family, horizon_slug)
    out5 = np.array(X_5m, copy=True)
    out1 = np.array(X_1m, copy=True)
    if m5_raw:
        ch5 = _post_mask_channel_indices(
            _pre_mask_encoded_indices(list(m5_raw), features_5m, encoded_features_5m),
            mask_5m,
        )
        for c in ch5:
            out5[:, :, c] = 0.0
    if m1_raw:
        ch1 = _post_mask_channel_indices(
            _pre_mask_encoded_indices(list(m1_raw), features_1m, encoded_features_1m),
            mask_1m,
        )
        for c in ch1:
            out1[:, :, c] = 0.0
    return out5, out1


def _full_fusion_prob_for_row(
    row: dict,
    *,
    ticker: str,
    target_column: str,
    hist_db,
) -> tuple[Optional[list[float]], Optional[int], Optional[str]]:
    """Score one row through the production stack to full_fusion (all six layers)."""
    import bayesian_fusion
    from features.inference_snapshot import build_inference_snapshot_v1_from_db_row
    from features.replay_signal_input_v1 import signal_input_from_snapshot_row_dict
    from regime_engine import classify_regime
    from rules_engine import compute_rules

    from prediction_engine import build_fusion_model_overlay_for_stack
    from signals import _run_model_stack, _spot_for_mc_fusion_adjustment

    ts_utc = row.get("ts_utc")
    if not ts_utc:
        return None, None, "missing_ts_utc"
    yt = _outcome_class_index(row.get(target_column))
    if yt is None:
        return None, None, f"missing_or_invalid_outcome:{row.get(target_column)!r}"
    try:
        inp = signal_input_from_snapshot_row_dict(row)
    except Exception as e:
        return None, yt, f"signal_input:{type(e).__name__}"
    try:
        inf_v1 = build_inference_snapshot_v1_from_db_row(
            ticker=ticker,
            expiry=None,
            as_of_ts=float(ts_utc),
            db_row=row,
        )
    except Exception as e:
        return None, yt, f"inference_snapshot:{type(e).__name__}"
    mvp = inf_v1.get("features") or {}
    try:
        rules = compute_rules(inp, mvp_features=mvp)
        regime = classify_regime(inp, rules, mvp_features=mvp)
    except Exception as e:
        return None, yt, f"rules_regime:{type(e).__name__}"
    try:
        snap = build_fusion_model_overlay_for_stack(
            inp, hist_db, rules, inference_snapshot_v1=inf_v1
        )
    except Exception as e:
        return None, yt, f"fusion_overlay:{type(e).__name__}"
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
        return None, yt, f"fusion_stack:{type(e).__name__}"

    try:
        triplet = _norm_triplet(
            float(fusion_payload_full.prob_up),
            float(fusion_payload_full.prob_down),
            float(fusion_payload_full.prob_flat),
        )
    except (TypeError, ValueError):
        return None, yt, "full_fusion_triplet_invalid"
    if triplet is None:
        return None, yt, "full_fusion_triplet_invalid"
    return triplet, yt, None


def _load_chronological_rth_rows(
    db_path: str,
    ticker: str,
    *,
    target_column: str,
    options: StackBundleEvalOptions,
) -> list[dict]:
    from ml_scheduler import _load_rth_rows_for_ticker

    rows = _load_rth_rows_for_ticker(db_path, ticker, label_column=target_column)
    if options.allowed_et_dates is not None:
        rows = [
            r
            for r in rows
            if r.get("ts_et") and str(r["ts_et"])[:10] in options.allowed_et_dates
        ]
    if options.max_rows is not None and options.max_rows > 0:
        rows = rows[-int(options.max_rows) :]
    return rows


def prepare_whole_stack_baseline_cache(
    *,
    db_path: str,
    ticker: str,
    model_dir: Path,
    ml_horizon_slug: str,
    options: Optional[StackBundleEvalOptions] = None,
    progress_every: int = 100,
    on_progress=None,
) -> dict[str, Any]:
    """One production-path baseline per (anchor, horizon): full_fusion probs on chronological RTH rows."""
    from train_all import preload_historical_db_for_eval

    import ml_predict as mp

    opts = options or StackBundleEvalOptions()
    hz = normalize_ml_horizon_slug(ml_horizon_slug)
    target_column = outcome_column(hz)
    rows = _load_chronological_rth_rows(
        db_path, ticker, target_column=target_column, options=opts
    )
    if not rows:
        return {
            "status": "skipped",
            "hz": hz,
            "reason": "no_rth_rows",
            "rows": [],
            "baseline_probs": [],
            "y_outcome": [],
        }

    orig_model_dir = mp.MODEL_DIR
    htok = mp.set_ml_infer_horizon_slug(hz)
    skip_reasons: dict[str, int] = {}

    def _bump(key: str) -> None:
        skip_reasons[key] = skip_reasons.get(key, 0) + 1

    baseline_probs: list[Optional[list[float]]] = [None] * len(rows)
    y_outcome: list[Optional[int]] = [None] * len(rows)
    try:
        mp.MODEL_DIR = _models_root_from_bundle_dir(Path(model_dir))
        mp.reset_caches()
        _tss = [float(r["ts_utc"]) for r in rows if r.get("ts_utc") is not None]
        hist_db = (
            preload_historical_db_for_eval(db_path, ticker, max(_tss))
            if _tss
            else None
        )
        for i, row in enumerate(rows):
            prob, yt, skip = _full_fusion_prob_for_row(
                row,
                ticker=ticker,
                target_column=target_column,
                hist_db=hist_db,
            )
            if skip:
                _bump(skip)
            y_outcome[i] = yt
            baseline_probs[i] = prob
            if on_progress and (
                i == 0 or (i + 1) % max(1, progress_every) == 0 or i + 1 == len(rows)
            ):
                paired_so_far = sum(
                    1
                    for p, y in zip(baseline_probs[: i + 1], y_outcome[: i + 1])
                    if p is not None and y is not None
                )
                on_progress(
                    {
                        "phase": "baseline",
                        "anchor_ticker": ticker,
                        "horizon_slug": hz,
                        "rows_done": i + 1,
                        "rows_total": len(rows),
                        "paired_so_far": paired_so_far,
                    }
                )
    finally:
        mp.MODEL_DIR = orig_model_dir
        mp.reset_caches()
        mp.reset_ml_infer_horizon_slug(htok)

    paired = sum(
        1
        for p, y in zip(baseline_probs, y_outcome)
        if p is not None and y is not None
    )
    if paired < opts.min_paired_rows:
        return {
            "status": "skipped",
            "hz": hz,
            "reason": f"insufficient_baseline_paired_rows:{paired}",
            "rows": rows,
            "baseline_probs": baseline_probs,
            "y_outcome": y_outcome,
            "skip_reason_counts": skip_reasons,
        }

    y_p = [y for p, y in zip(baseline_probs, y_outcome) if p is not None and y is not None]
    p_p = [p for p, y in zip(baseline_probs, y_outcome) if p is not None and y is not None]
    ll_b = float(log_loss(y_p, np.asarray(p_p, dtype=np.float64), labels=[0, 1, 2]))

    return {
        "status": "ok",
        "hz": hz,
        "rows": rows,
        "rows_scored": len(rows),
        "baseline_probs": baseline_probs,
        "y_outcome": y_outcome,
        "baseline_multiclass_log_loss": ll_b,
        "paired_rows": paired,
        "skip_reason_counts": skip_reasons,
    }


def run_whole_stack_feature_group_ablation(
    *,
    db_path: str,
    ticker: str,
    model_dir: Path,
    ml_horizon_slug: str,
    group_id: str,
    group_columns: list[str],
    baseline_cache: dict,
    options: Optional[StackBundleEvalOptions] = None,
    random_state: int = 42,
) -> dict[str, Any]:
    """Permute one feature group on the production path; measure full_fusion log_loss delta."""
    from train_all import preload_historical_db_for_eval

    import ml_predict as mp

    opts = options or StackBundleEvalOptions()
    if baseline_cache.get("status") != "ok":
        return {
            "anchor_ticker": ticker,
            "horizon_slug": baseline_cache.get("hz", ml_horizon_slug),
            "group_id": group_id,
            "status": "skipped",
            "reason": baseline_cache.get("reason", "baseline_not_ready"),
            "ablation_kind": "whole_stack_feature_group",
            "decision_mode": WHOLE_STACK_DECISION_MODE,
        }

    rows = baseline_cache["rows"]
    baseline_probs = baseline_cache["baseline_probs"]
    y_outcome = baseline_cache["y_outcome"]
    hz = baseline_cache["hz"]
    target_column = outcome_column(hz)

    present = [c for c in group_columns if any(c in r for r in rows)]
    rng = np.random.default_rng(random_state)
    permuted_rows = permute_snapshot_columns_across_rows(rows, group_columns, rng)

    orig_model_dir = mp.MODEL_DIR
    htok = mp.set_ml_infer_horizon_slug(hz)
    skip_reasons: dict[str, int] = {}

    def _bump(key: str) -> None:
        skip_reasons[key] = skip_reasons.get(key, 0) + 1

    permuted_probs: list[Optional[list[float]]] = [None] * len(rows)
    try:
        mp.MODEL_DIR = _models_root_from_bundle_dir(Path(model_dir))
        mp.reset_caches()
        _tss = [float(r["ts_utc"]) for r in rows if r.get("ts_utc") is not None]
        hist_db = (
            preload_historical_db_for_eval(db_path, ticker, max(_tss))
            if _tss
            else None
        )
        for i, row in enumerate(permuted_rows):
            if baseline_probs[i] is None or y_outcome[i] is None:
                continue
            prob, _yt, skip = _full_fusion_prob_for_row(
                row,
                ticker=ticker,
                target_column=target_column,
                hist_db=hist_db,
            )
            if skip:
                _bump(skip)
            permuted_probs[i] = prob
    finally:
        mp.MODEL_DIR = orig_model_dir
        mp.reset_caches()
        mp.reset_ml_infer_horizon_slug(htok)

    y_paired: list[int] = []
    b_paired: list[list[float]] = []
    p_paired: list[list[float]] = []
    for i in range(len(rows)):
        b = baseline_probs[i]
        p = permuted_probs[i]
        y = y_outcome[i]
        if b is None or p is None or y is None:
            continue
        y_paired.append(int(y))
        b_paired.append(b)
        p_paired.append(p)

    if len(y_paired) < opts.min_paired_rows:
        return {
            "anchor_ticker": ticker,
            "horizon_slug": hz,
            "group_id": group_id,
            "status": "skipped",
            "reason": f"insufficient_paired_rows:{len(y_paired)}",
            "ablation_kind": "whole_stack_feature_group",
            "decision_mode": WHOLE_STACK_DECISION_MODE,
            "columns_requested": list(group_columns),
            "columns_permuted": present,
            "columns_permuted_count": len(present),
            "skip_reason_counts": skip_reasons,
        }

    ll_b = float(log_loss(y_paired, np.asarray(b_paired, dtype=np.float64), labels=[0, 1, 2]))
    ll_p = float(log_loss(y_paired, np.asarray(p_paired, dtype=np.float64), labels=[0, 1, 2]))
    delta = round(ll_p - ll_b, 6)

    return {
        "anchor_ticker": ticker,
        "horizon_slug": hz,
        "group_id": group_id,
        "status": "ok",
        "ablation_kind": "whole_stack_feature_group",
        "decision_mode": WHOLE_STACK_DECISION_MODE,
        "metric": "multiclass_log_loss",
        "columns_requested": list(group_columns),
        "columns_permuted": present,
        "columns_permuted_count": len(present),
        "paired_rows": len(y_paired),
        "baseline_multiclass_log_loss": ll_b,
        "permuted_multiclass_log_loss": ll_p,
        "log_loss_delta": delta,
        "group_matters": bool(delta > 1e-6),
        "skip_reason_counts": skip_reasons,
    }


WHOLE_STACK_CONFIRM_DECISION_MODE = "full_fusion_confirm_drop"


def run_whole_stack_feature_group_confirm_drop(
    *,
    db_path: str,
    ticker: str,
    model_dir: Path,
    ml_horizon_slug: str,
    group_id: str,
    group_columns: list[str],
    baseline_cache: dict,
    options: Optional[StackBundleEvalOptions] = None,
) -> dict[str, Any]:
    """Confirm pass: drop (null) one feature group's raw columns; measure full_fusion log_loss delta.

    Pre-retrain inference validation — not model refit. Refit-on-survivors is the post-ablation retrain.
    """
    from train_all import preload_historical_db_for_eval

    import ml_predict as mp

    opts = options or StackBundleEvalOptions()
    if baseline_cache.get("status") != "ok":
        return {
            "anchor_ticker": ticker,
            "horizon_slug": baseline_cache.get("hz", ml_horizon_slug),
            "group_id": group_id,
            "status": "skipped",
            "reason": baseline_cache.get("reason", "baseline_not_ready"),
            "ablation_kind": "confirm_drop_feature_group",
            "decision_mode": WHOLE_STACK_CONFIRM_DECISION_MODE,
        }

    rows = baseline_cache["rows"]
    baseline_probs = baseline_cache["baseline_probs"]
    y_outcome = baseline_cache["y_outcome"]
    hz = baseline_cache["hz"]
    target_column = outcome_column(hz)

    present = [c for c in group_columns if any(c in r for r in rows)]
    dropped_rows = drop_snapshot_columns_across_rows(rows, group_columns)

    orig_model_dir = mp.MODEL_DIR
    htok = mp.set_ml_infer_horizon_slug(hz)
    skip_reasons: dict[str, int] = {}

    def _bump(key: str) -> None:
        skip_reasons[key] = skip_reasons.get(key, 0) + 1

    dropped_probs: list[Optional[list[float]]] = [None] * len(rows)
    try:
        mp.MODEL_DIR = _models_root_from_bundle_dir(Path(model_dir))
        mp.reset_caches()
        _tss = [float(r["ts_utc"]) for r in rows if r.get("ts_utc") is not None]
        hist_db = (
            preload_historical_db_for_eval(db_path, ticker, max(_tss))
            if _tss
            else None
        )
        for i, row in enumerate(dropped_rows):
            if baseline_probs[i] is None or y_outcome[i] is None:
                continue
            prob, _yt, skip = _full_fusion_prob_for_row(
                row,
                ticker=ticker,
                target_column=target_column,
                hist_db=hist_db,
            )
            if skip:
                _bump(skip)
            dropped_probs[i] = prob
    finally:
        mp.MODEL_DIR = orig_model_dir
        mp.reset_caches()
        mp.reset_ml_infer_horizon_slug(htok)

    y_paired: list[int] = []
    b_paired: list[list[float]] = []
    d_paired: list[list[float]] = []
    for i in range(len(rows)):
        b = baseline_probs[i]
        d = dropped_probs[i]
        y = y_outcome[i]
        if b is None or d is None or y is None:
            continue
        y_paired.append(int(y))
        b_paired.append(b)
        d_paired.append(d)

    if len(y_paired) < opts.min_paired_rows:
        return {
            "anchor_ticker": ticker,
            "horizon_slug": hz,
            "group_id": group_id,
            "status": "skipped",
            "reason": f"insufficient_paired_rows:{len(y_paired)}",
            "ablation_kind": "confirm_drop_feature_group",
            "decision_mode": WHOLE_STACK_CONFIRM_DECISION_MODE,
            "columns_requested": list(group_columns),
            "columns_dropped": present,
            "columns_dropped_count": len(present),
            "skip_reason_counts": skip_reasons,
        }

    ll_b = float(log_loss(y_paired, np.asarray(b_paired, dtype=np.float64), labels=[0, 1, 2]))
    ll_d = float(log_loss(y_paired, np.asarray(d_paired, dtype=np.float64), labels=[0, 1, 2]))
    delta = round(ll_d - ll_b, 6)
    safe_to_drop = bool(delta <= 1e-4)

    return {
        "anchor_ticker": ticker,
        "horizon_slug": hz,
        "group_id": group_id,
        "status": "ok",
        "ablation_kind": "confirm_drop_feature_group",
        "decision_mode": WHOLE_STACK_CONFIRM_DECISION_MODE,
        "metric": "multiclass_log_loss",
        "columns_requested": list(group_columns),
        "columns_dropped": present,
        "columns_dropped_count": len(present),
        "paired_rows": len(y_paired),
        "baseline_multiclass_log_loss": ll_b,
        "dropped_multiclass_log_loss": ll_d,
        "log_loss_delta": delta,
        "safe_to_drop": safe_to_drop,
        "skip_reason_counts": skip_reasons,
    }


# --- tests / tooling: expose metric packer ---
def pack_metrics_for_probs(
    name: str,
    y_true: list[int],
    prob_rows: list[list[float]],
    rows_used: Optional[list[dict]] = None,
) -> dict[str, Any]:
    return _pack_full_metrics(name, y_true, prob_rows, rows_used or [])
