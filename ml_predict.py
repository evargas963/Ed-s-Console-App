"""
Ed Console - ML Prediction Module (Phase 4 - Stacked Ensemble)
===============================================================
Loads and runs all three base models + meta-learner for each ticker.

Architecture:
    Layer 1 (base models, run in parallel):
        XGBoost     - tabular snapshot features (per-ticker model)
        LSTM        - dual-stream candle sequences (shared model)
        Transformer - attention-based candle sequences (shared model)

    Layer 2 (meta-learner):
        Logistic regression trained on stacked Layer 1 probability outputs.
        Input:  [xgb_up, xgb_dn, xgb_fl, lstm_up, lstm_dn, lstm_fl,
                 tr_up,  tr_dn,  tr_fl]  (9 features)
        Output: final {up, down, flat} probabilities

Fallback chain:
    meta-learner -> weighted average -> XGBoost alone -> rules engine

Integration:
    signals.py calls run_base_models_once with inference_snapshot_v1= (InferenceSnapshotV1).
    Returns {up, down, flat} or None (rules engine takes over).
"""

import json
import pickle
import logging
import numpy as np
import os
from contextlib import contextmanager
from contextvars import ContextVar, Token
from pathlib import Path
from typing import Optional, Any

from ml_horizon import (
    DEFAULT_ML_HORIZON_SLUG,
    PRIMARY_DECISION_HORIZONS,
    live_inference_horizon_slug,
    normalize_ml_horizon_slug,
)

from features.lstm_sequence_input import (
    LstmSequenceInputError,
    TransformerSequenceInputError,
    build_transformer_merged_window,
)
from features.xgb_model_input import XgbInferenceInputError
from features.parallel_stack_schema import (
    PARALLEL_STACK_SCHEMA_VERSION,
    build_parallel_base_output,
)
from features.cascade_stack_contract import (
    CASCADE_UPSTREAM_BUNDLE_VERSION,
    CascadeChallengerError,
    CascadeStageError,
    assert_no_legacy_mvp_in_fusion_overlay,
    validate_cascade_inference_lineage,
)
from features.cascade_stack_schema import (
    CASCADE_STACK_SCHEMA_VERSION,
    build_cascade_challenger_run_metadata,
)

logger = logging.getLogger("ed_console.ml")


class ParallelRuntimeArtifactError(ValueError):
    """Loaded artifact expects cascade (upstream model) tensors; parallel runtime forbids that coupling."""

# "parallel" = production default; "cascade" = challenger challenger inference scope (models/cascade/{ticker}/).
_INFER_ARCHITECTURE: ContextVar[str] = ContextVar("ml_predict_infer_architecture", default="parallel")


def _reg_key(ticker: str) -> str:
    return f"{_INFER_ARCHITECTURE.get()}:{ticker.upper()}"


def _model_registry_key(ticker: str, hz: str | None = None) -> str:
    """
    In-memory cache key for base stack models (XGB / LSTM / Transformer / meta).

    Must include horizon slug so each governed horizon loads its own artifact
    (xgb_{TICKER}_{hz}.pkl, etc.) — not reused across horizons.
    """
    su = normalize_ml_horizon_slug(hz) if hz is not None else get_ml_infer_horizon_slug()
    return f"{_reg_key(ticker)}:{su}"


@contextmanager
def _cascade_challenger_inference_scope():
    tok = _INFER_ARCHITECTURE.set("cascade")
    try:
        yield
    finally:
        _INFER_ARCHITECTURE.reset(tok)


# Scheduler / eval sets this when loading non-1c artifacts from a candidate directory.
_ml_infer_horizon_cv: ContextVar[str] = ContextVar(
    "ml_infer_horizon_slug", default=DEFAULT_ML_HORIZON_SLUG
)


def get_ml_infer_horizon_slug() -> str:
    return normalize_ml_horizon_slug(_ml_infer_horizon_cv.get())


def set_ml_infer_horizon_slug(slug: str) -> Token:
    return _ml_infer_horizon_cv.set(normalize_ml_horizon_slug(slug))


def reset_ml_infer_horizon_slug(token: Token) -> None:
    _ml_infer_horizon_cv.reset(token)


def stack_probs_bundle_key() -> str:
    """Dict key for stacked ML probabilities in run_base_models_once / signals.ml_bundle (Issue 15)."""
    return f"stack_probs_{get_ml_infer_horizon_slug()}"


# Cascade training appends these extras (must match lstm_model / transformer_train).
_CASCADE_LSTM_CONF_EXTRA = 3
_CASCADE_TRANSFORMER_SEQ_EXTRA = 6


def _snap_dict(row: Any) -> Optional[dict]:
    if row is None:
        return None
    if isinstance(row, dict):
        return row
    try:
        return dict(row)
    except Exception:
        return None


def _require_as_of_ts_utc_for_sequence_db(inference_snapshot_v1: dict | None) -> float:
    """Causal upper bound for LSTM/Transformer rolling DB history (rows must have ts_utc < as_of)."""
    if not inference_snapshot_v1:
        raise LstmSequenceInputError(
            "LSTM/Transformer sequence inference requires inference_snapshot_v1 with as_of_ts "
            "for causal DB history (EdDB.get_recent_snapshots(..., as_of_ts_utc=...))."
        )
    ts = inference_snapshot_v1.get("as_of_ts")
    if ts is None:
        raise LstmSequenceInputError(
            "InferenceSnapshotV1.as_of_ts is required for LSTM/Transformer DB history "
            "(strict causal cutoff: only snapshots with ts_utc < as_of_ts are used from the DB; "
            "the current bar MVP is merged from inference_snapshot_v1)."
        )
    return float(ts)


def _probs_dict_to_arr(p: Optional[dict]) -> np.ndarray:
    u = 1.0 / 3.0
    if not p:
        return np.array([u, u, u], dtype=np.float32)
    return np.array(
        [float(p.get("up", u)), float(p.get("down", u)), float(p.get("flat", u))],
        dtype=np.float32,
    )


def _transformer_normalize_and_select(X_raw: np.ndarray, checkpoint: dict) -> np.ndarray:
    """
    Match transformer_train.train_transformer: per-column normalize using raw means/stds,
    then keep columns where feature_mask is True (same order as training).
    """
    fm = np.asarray(checkpoint.get("feature_mask", np.ones(X_raw.shape[2], dtype=bool)), dtype=bool)
    if X_raw.shape[2] != fm.shape[0]:
        raise ValueError(f"raw width {X_raw.shape[2]} != feature_mask len {fm.shape[0]}")
    mean_m = np.asarray(checkpoint["norm_mean"], dtype=np.float32)
    std_m = np.asarray(checkpoint["norm_std"], dtype=np.float32)
    std_m = np.where(std_m < 1e-8, 1.0, std_m)
    kept = np.flatnonzero(fm)
    # Train-time bug once saved full-width mean/std with per-position mask; repair at inference.
    if mean_m.size == fm.shape[0] and std_m.size == fm.shape[0]:
        mean_m = mean_m[kept]
        std_m = std_m[kept]
    if mean_m.size != kept.size or std_m.size != kept.size:
        raise ValueError(
            f"norm_mean/std ({mean_m.size}) != kept columns ({kept.size})"
        )
    parts = []
    for k, j in enumerate(kept):
        col = X_raw[:, :, j].astype(np.float32)
        parts.append((col - mean_m[k]) / std_m[k])
    return np.nan_to_num(np.stack(parts, axis=2), nan=0.0, posinf=0.0, neginf=0.0)

MODEL_DIR = Path("models")
ARCH_STATE_PATH = MODEL_DIR / "arch_state.json"

# Per-(ticker, horizon) model registry — loaded on first call per slug
_xgb_registry   = {}   # _model_registry_key -> {model, meta, feature_names, category_maps, vol_medians}
_xgb_movehead_registry: dict[str, dict | None] = {}  # movement-target v1 binary XGB heads
_meta_registry  = {}   # _model_registry_key -> sklearn LogisticRegression
_lstm_registry  = {}   # _model_registry_key -> (model, checkpoint)
_trans_registry = {}   # _model_registry_key -> (model, checkpoint)

CLASS_NAMES = ["up", "down", "flat"]


def _model_dir_for_ticker(ticker: str) -> Path:
    """RULE 4: Read arch_state.json, load from models/active/{ticker}/. Default parallel if missing.

    Cascade challenger inference (`_cascade_challenger_inference_scope`) uses `models/cascade/{ticker}/` only.
    """
    hz = get_ml_infer_horizon_slug()
    strict_active_only = os.environ.get("ED_XGB_STRICT_ACTIVE_ONLY", "1").strip().lower() not in (
        "0",
        "false",
        "no",
    )
    if strict_active_only:
        # Fail-closed to active roots only (default). Deterministic selection:
        # choose the directory that actually contains the per-horizon artifacts for this hz,
        # not merely "first existing dir with any xgb_* for hz" (which can strand LSTM/TR).
        cands = [MODEL_DIR / f"active_{hz}" / ticker, MODEL_DIR / "active" / ticker]

        def _score_dir(d: Path) -> tuple[int, int]:
            if not d.exists():
                return (-1, -1)
            xgb = 0
            if (d / f"xgb_{ticker}_{hz}.pkl").exists():
                xgb = 3
            elif (d / f"xgb_{ticker}_{hz}_dir.pkl").exists() or (d / f"xgb_{ticker}_{hz}_move.pkl").exists():
                xgb = 2
            lstm = 2 if (
                (d / f"lstm_{ticker}_{hz}.pt").exists()
                and (d / f"lstm_{ticker}_{hz}_meta.json").exists()
            ) else 0
            tr = 2 if (
                (d / f"transformer_{ticker}_{hz}.pt").exists()
                and (d / f"transformer_{ticker}_{hz}_meta.json").exists()
            ) else 0
            total = xgb + lstm + tr
            # Prefer horizon-specific root on ties (cands[0]) by giving it +1 tiebreaker.
            tie = 1 if d == cands[0] else 0
            return (total, tie)

        best: Path | None = None
        best_score = (-1, -1)
        for d in cands:
            sc = _score_dir(d)
            if sc[0] < 0:
                continue
            if sc > best_score:
                best_score = sc
                best = d
        if best is None or best_score[0] <= 0:
            raise FileNotFoundError(
                f"ED_XGB_STRICT_ACTIVE_ONLY=1: no active model bundle found for {ticker} hz={hz} "
                f"(checked: {[str(x) for x in cands]})"
            )
        return best
    if _INFER_ARCHITECTURE.get() == "cascade":
        cd = MODEL_DIR / "cascade" / ticker
        if not cd.is_dir():
            raise CascadeChallengerError(f"cascade challenger directory missing: {cd}")
        if not (cd / f"xgb_{ticker}_{hz}.pkl").exists():
            raise CascadeChallengerError(
                f"cascade challenger XGB artifact missing under {cd} (same horizon {hz} as parallel)"
            )
        return cd
    # Movement-only bundles: prefer models/active/{ticker}/ when dir/move heads exist for this horizon.
    active_early = MODEL_DIR / "active" / ticker
    if active_early.exists():
        if (active_early / f"xgb_{ticker}_{hz}_dir.pkl").exists() or (
            active_early / f"xgb_{ticker}_{hz}_move.pkl"
        ).exists():
            return active_early
    if ARCH_STATE_PATH.exists():
        try:
            data = json.loads(ARCH_STATE_PATH.read_text())
            if ticker in data:
                active = MODEL_DIR / "active" / ticker
                # Use active if any of xgb/lstm/transformer binary exists
                if active.exists():
                    has_any = (
                        (active / f"xgb_{ticker}_{hz}.pkl").exists()
                        or (active / f"xgb_{ticker}_{hz}_dir.pkl").exists()
                        or (active / f"xgb_{ticker}_{hz}_move.pkl").exists()
                        or (active / f"lstm_{ticker}_{hz}.pt").exists()
                        or (active / f"transformer_{ticker}_{hz}.pt").exists()
                    )
                    if has_any:
                        return active
        except Exception:
            pass
    # Default to parallel: models/parallel/{ticker}/
    parallel = MODEL_DIR / "parallel" / ticker
    if parallel.exists():
        has_any = (
            (parallel / f"xgb_{ticker}_{hz}.pkl").exists()
            or (parallel / f"xgb_{ticker}_{hz}_dir.pkl").exists()
            or (parallel / f"xgb_{ticker}_{hz}_move.pkl").exists()
            or (parallel / f"lstm_{ticker}_{hz}.pt").exists()
            or (parallel / f"transformer_{ticker}_{hz}.pt").exists()
        )
        if has_any:
            return parallel
    # Fallback: flat models/ (train_all output) or per-ticker subdir for flat layout
    flat_pt = MODEL_DIR / f"lstm_{ticker}_{hz}.pt"
    flat_pkl = MODEL_DIR / f"xgb_{ticker}_{hz}.pkl"
    if flat_pt.exists() or flat_pkl.exists():
        return MODEL_DIR
    return MODEL_DIR


# ══════════════════════════════════════════════════════════════════════════════
# XGBoost - per-ticker
# ══════════════════════════════════════════════════════════════════════════════


def build_xgb_pre_engineering_snapshot_for_tick(
    inference_snapshot_v1: dict,
    fusion_feature_overlay: dict | None,
) -> dict:
    """
    Engineering snapshot after MVP map + fusion overlay + m5 additive columns.

    Identical for every governed horizon on a single tick; call once and pass into
    ``run_base_models_once(..., xgb_pre_engineering_snapshot=...)`` so XGB tri-class
    and movement heads skip repeated ingest/merge/m5 work (per-horizon work remains:
    ``engineer_single_snapshot`` + ``predict_proba`` per artifact).
    """
    from features.xgb_model_input import (
        assert_not_raw_l1_payload,
        inference_snapshot_v1_to_engineering_snapshot,
        merge_xgb_fusion_overlay,
    )
    from ml_data_common import snapshot_with_m5_additive
    from ml_train import DB_PATH as _ML_DB

    assert_not_raw_l1_payload(inference_snapshot_v1)
    if fusion_feature_overlay is not None:
        assert_not_raw_l1_payload(fusion_feature_overlay)
    base = inference_snapshot_v1_to_engineering_snapshot(inference_snapshot_v1)
    snap = merge_xgb_fusion_overlay(base, fusion_feature_overlay)
    return snapshot_with_m5_additive(snap, _ML_DB)


def _load_xgb(ticker: str) -> bool:
    hz = get_ml_infer_horizon_slug()
    rk = _model_registry_key(ticker, hz)
    if rk in _xgb_registry:
        return _xgb_registry[rk] is not None

    base = _model_dir_for_ticker(ticker)
    mp  = base / f"xgb_{ticker}_{hz}.pkl"
    mtp = base / f"xgb_{ticker}_{hz}_meta.json"

    if not mp.exists():
        logger.debug("XGBoost model not found for %s", ticker)
        _xgb_registry[rk] = None
        return False

    try:
        with open(mp, "rb") as f:
            model = pickle.load(f)
        with open(mtp, "r") as f:
            meta = json.load(f)

        from model_contract import validate_artifact_contract

        ok, reason = validate_artifact_contract(meta, "xgb")
        if not ok:
            logger.error(
                "XGBoost %s: incompatible model contract (%s). Retrain; refusing load.",
                ticker,
                reason,
            )
            _xgb_registry[rk] = None
            return False

        _xgb_registry[rk] = dict(
            model=model, meta=meta,
            feature_names=meta["features"],
            category_maps=meta.get("category_maps", {}),
            vol_medians=meta.get("vol_medians", {}),
        )
        logger.info("XGBoost loaded for %s hz=%s: %d features", ticker, hz, len(meta["features"]))
        return True

    except Exception as e:
        logger.error("Failed to load XGBoost for %s: %s", ticker, e)
        _xgb_registry[rk] = None
        return False


def _predict_xgb(
    inference_snapshot_v1: dict,
    ticker: str,
    fusion_feature_overlay: dict | None = None,
    *,
    xgb_pre_engineering_snapshot: dict | None = None,
) -> Optional[dict]:
    """
    XGBoost tabular inference: MVP fields come exclusively from InferenceSnapshotV1
    (mapped via `features.xgb_model_input`). Optional `fusion_feature_overlay` supplies
    non-MVP keys only (pred_*, et_hour from fusion, …); it must not override MVP columns.

    When ``xgb_pre_engineering_snapshot`` is set (from ``build_xgb_pre_engineering_snapshot_for_tick``),
    ``fusion_feature_overlay`` is ignored — the snapshot must already include that merge.
    """
    if not _load_xgb(ticker):
        return None

    reg = _xgb_registry[_model_registry_key(ticker)]
    try:
        from features.xgb_model_input import (
            assert_not_raw_l1_payload,
            inference_snapshot_v1_to_engineering_snapshot,
            merge_xgb_fusion_overlay,
        )
        from ml_data_common import snapshot_with_m5_additive
        from ml_train import (
            apply_xgb_imputation_matrix,
            engineer_single_snapshot,
            DB_PATH as _ML_DB,
        )

        if xgb_pre_engineering_snapshot is not None:
            snap = xgb_pre_engineering_snapshot
        else:
            assert_not_raw_l1_payload(inference_snapshot_v1)
            if fusion_feature_overlay is not None:
                assert_not_raw_l1_payload(fusion_feature_overlay)

            base = inference_snapshot_v1_to_engineering_snapshot(inference_snapshot_v1)
            snap = merge_xgb_fusion_overlay(base, fusion_feature_overlay)

            snap = snapshot_with_m5_additive(snap, _ML_DB)
        X = engineer_single_snapshot(
            snapshot=snap,
            category_maps=reg["category_maps"],
            feature_names=reg["feature_names"],
            vol_medians=reg["vol_medians"],
            ticker=ticker,
        )
        if X is None:
            return None
        impute = reg["meta"].get("impute_medians") or {}
        x_mat = apply_xgb_imputation_matrix(
            X.values.astype(np.float64),
            reg["feature_names"],
            impute,
        )
        nfi = getattr(reg["model"], "n_features_in_", None)
        if nfi is not None and x_mat.shape[1] != int(nfi):
            logger.warning(
                "XGBoost %s: feature mismatch (have %d, model expects %d)",
                ticker,
                x_mat.shape[1],
                int(nfi),
            )
            return None
        probs = reg["model"].predict_proba(x_mat)[0]
        return {CLASS_NAMES[i]: round(float(probs[i]), 4) for i in range(3)}
    except XgbInferenceInputError:
        raise
    except Exception as e:
        logger.warning("XGBoost prediction failed for %s: %s", ticker, e)
        return None


def _normalize_binary_head_probs(raw: np.ndarray, class_names: list[str]) -> dict[str, float]:
    p = np.asarray(raw, dtype=np.float64).reshape(-1)
    p = np.nan_to_num(np.clip(p, 0.0, 1.0), nan=0.5, posinf=1.0, neginf=0.0)
    names = list(class_names)
    if len(names) >= 2 and p.size >= 2:
        s = float(p[0] + p[1])
        if s <= 0:
            u = 0.5
            return {names[0]: u, names[1]: u}
        return {names[0]: float(p[0]) / s, names[1]: float(p[1]) / s}
    if len(names) >= 2 and p.size == 1:
        p1 = float(p[0])
        return {names[1]: p1, names[0]: max(0.0, 1.0 - p1)}
    u = 1.0 / max(len(names), 1)
    return {n: u for n in names}


def _predict_xgb_movement_heads(
    inference_snapshot_v1: dict,
    ticker: str,
    fusion_feature_overlay: dict | None = None,
    *,
    xgb_pre_engineering_snapshot: dict | None = None,
) -> dict[str, float]:
    """
    Optional XGB binary classifiers: conditional direction (up/down) and move vs no_move.
    Canonical keys: pred_dir_up_prob_{hz}, pred_dir_down_prob_{hz}, pred_move_prob_{hz}, pred_no_move_prob_{hz}.
    Also mirrors legacy pred_{hz}_dir_* / pred_{hz}_move_* for backward compatibility.

    Inference contract — Option 1: when both heads load successfully, direction probabilities are
    emitted for every scored row (same engineered features as training). Downstream evaluation may
    restrict to valid_dir rows for outcome_dir calibration; move head uses the full labeled row set.
    """
    hz = get_ml_infer_horizon_slug()
    tkr = ticker.strip().upper()
    out: dict[str, float] = {}
    _m5_snap_cached: dict | None = xgb_pre_engineering_snapshot
    for suffix, names_default in (("dir", ["up", "down"]), ("move", ["move", "no_move"])):
        reg_key = f"{_model_registry_key(ticker, hz)}:{suffix}"
        if reg_key not in _xgb_movehead_registry:
            base = _model_dir_for_ticker(ticker)
            mp = base / f"xgb_{tkr}_{hz}_{suffix}.pkl"
            mtp = base / f"xgb_{tkr}_{hz}_{suffix}_meta.json"
            if not mp.is_file() or not mtp.is_file():
                _xgb_movehead_registry[reg_key] = None
            else:
                try:
                    with open(mtp, encoding="utf-8") as fm:
                        meta = json.load(fm)
                    from model_contract import validate_artifact_contract

                    ok, reason = validate_artifact_contract(meta, "xgb")
                    if not ok:
                        logger.debug("movement head %s contract fail %s: %s", suffix, ticker, reason)
                        _xgb_movehead_registry[reg_key] = None
                    else:
                        with open(mp, "rb") as f:
                            model = pickle.load(f)
                        cnames = list(meta.get("class_names") or names_default)
                        _xgb_movehead_registry[reg_key] = dict(
                            model=model,
                            meta=meta,
                            feature_names=meta["features"],
                            category_maps=meta.get("category_maps", {}),
                            vol_medians=meta.get("vol_medians", {}),
                            class_names=cnames,
                        )
                except Exception as e:
                    logger.debug("movement head %s load failed for %s: %s", suffix, ticker, e)
                    _xgb_movehead_registry[reg_key] = None
        reg = _xgb_movehead_registry[reg_key]
        if reg is None:
            continue
        try:
            from features.xgb_model_input import (
                assert_not_raw_l1_payload,
                inference_snapshot_v1_to_engineering_snapshot,
                merge_xgb_fusion_overlay,
            )
            from ml_data_common import snapshot_with_m5_additive
            from ml_train import (
                DB_PATH as _ML_DB,
                apply_xgb_imputation_matrix,
                engineer_single_snapshot,
            )

            if _m5_snap_cached is None:
                assert_not_raw_l1_payload(inference_snapshot_v1)
                if fusion_feature_overlay is not None:
                    assert_not_raw_l1_payload(fusion_feature_overlay)
                base_snap = inference_snapshot_v1_to_engineering_snapshot(inference_snapshot_v1)
                snap = merge_xgb_fusion_overlay(base_snap, fusion_feature_overlay)
                _m5_snap_cached = snapshot_with_m5_additive(snap, _ML_DB)
            snap = _m5_snap_cached
            X = engineer_single_snapshot(
                snapshot=snap,
                category_maps=reg["category_maps"],
                feature_names=reg["feature_names"],
                vol_medians=reg["vol_medians"],
                ticker=ticker,
            )
            if X is None:
                continue
            impute = reg["meta"].get("impute_medians") or {}
            x_mat = apply_xgb_imputation_matrix(
                X.values.astype(np.float64),
                reg["feature_names"],
                impute,
            )
            nfi = getattr(reg["model"], "n_features_in_", None)
            if nfi is not None and x_mat.shape[1] != int(nfi):
                continue
            probs = reg["model"].predict_proba(x_mat)[0]
            norm = _normalize_binary_head_probs(probs, reg["class_names"])
            sm = sum(norm.values())
            if sm > 0:
                norm = {k: round(v / sm, 6) for k, v in norm.items()}
            else:
                norm = {k: round(1.0 / len(reg["class_names"]), 6) for k in reg["class_names"]}
            if suffix == "dir":
                pu = float(norm.get("up", 0.5))
                pd_ = float(norm.get("down", 0.5))
                out[f"pred_dir_up_prob_{hz}"] = pu
                out[f"pred_dir_down_prob_{hz}"] = pd_
                out[f"pred_{hz}_dir_up_prob"] = pu
                out[f"pred_{hz}_dir_down_prob"] = pd_
            else:
                pm = float(norm.get("move", 0.5))
                pn = float(norm.get("no_move", 0.5))
                out[f"pred_move_prob_{hz}"] = pm
                out[f"pred_no_move_prob_{hz}"] = pn
                out[f"pred_{hz}_move_prob"] = pm
                out[f"pred_{hz}_no_move_prob"] = pn
        except Exception as e:
            logger.debug("movement head %s predict failed for %s: %s", suffix, ticker, e)
    for k, v in list(out.items()):
        if v is None or not np.isfinite(v):
            out.pop(k, None)
        else:
            out[k] = float(min(1.0, max(0.0, v)))
    return out


# ══════════════════════════════════════════════════════════════════════════════
# LSTM - per-ticker model
# ══════════════════════════════════════════════════════════════════════════════

def _load_lstm(ticker: str) -> bool:
    hz = get_ml_infer_horizon_slug()
    rk = _model_registry_key(ticker, hz)
    if rk in _lstm_registry:
        return _lstm_registry[rk] is not None

    base = _model_dir_for_ticker(ticker)
    mp = base / f"lstm_{ticker}_{hz}.pt"
    if not mp.exists():
        logger.debug("LSTM model not found for %s at %s", ticker, mp)
        _lstm_registry[rk] = None
        return False

    try:
        from lstm_model import load_lstm

        model, checkpoint = load_lstm(
            model_path=mp, ticker=ticker, model_dir=base, ml_horizon_slug=hz,
        )
        if model is None:
            logger.error("LSTM load failed for %s: %s", ticker, checkpoint)
            _lstm_registry[rk] = None
            return False

        model.eval()
        _lstm_registry[rk] = (model, checkpoint)
        logger.info("LSTM model loaded for %s hz=%s", ticker, hz)
        return True

    except ImportError as e:
        logger.debug("LSTM load skipped (missing dep: %s)", e)
        _lstm_registry[rk] = None
        return False
    except Exception as e:
        logger.error("LSTM load failed for %s: %s", ticker, e)
        _lstm_registry[rk] = None
        return False


def _predict_lstm(
    ticker: str,
    db,
    snapshot: Optional[dict] = None,
    xgb_probs_arr: Optional[np.ndarray] = None,
    timeframe: Optional[str] = None,
    *,
    inference_snapshot_v1: dict | None = None,
    parallel_runtime: bool = False,
    shared_sequence_context: Any = None,
) -> Optional[dict]:
    if not _load_lstm(ticker) or db is None:
        return None

    model, checkpoint = _lstm_registry[_model_registry_key(ticker)]
    try:
        import torch
        from features.lstm_sequence_input import build_lstm_merged_windows
        from lstm_data import (
            encode_snapshot_5m,
            encode_snapshot_1m,
            CANONICAL_TIMEFRAME,
            compute_confluence_features,
            CONFLUENCE_FEATURES,
            STREAM_5M_LOOKBACK,
            STREAM_1M_LOOKBACK,
            _safe_float,
            canonical_reference_spot_from_merged_window,
        )

        tf = timeframe or CANONICAL_TIMEFRAME
        if shared_sequence_context is not None:
            merged_window = list(shared_sequence_context.lstm_merged_window)
            merged_days = list(shared_sequence_context.lstm_merged_days)
        else:
            _asof = _require_as_of_ts_utc_for_sequence_db(inference_snapshot_v1)
            recent = db.get_recent_snapshots(
                ticker,
                tf,
                n=STREAM_5M_LOOKBACK + 5,
                filled_only=False,
                as_of_ts_utc=_asof,
            )
            if not recent or len(recent) < STREAM_5M_LOOKBACK:
                raise LstmSequenceInputError(
                    f"LSTM needs at least {STREAM_5M_LOOKBACK} snapshots, got {len(recent or [])}"
                )
            recent = list(reversed(recent))
            window = recent[-STREAM_5M_LOOKBACK:]

            day_snaps = db.get_recent_snapshots(
                ticker, tf, n=100, filled_only=False, as_of_ts_utc=_asof
            )
            day_snaps = list(reversed(day_snaps)) if day_snaps else list(window)

            merged_window, merged_days = build_lstm_merged_windows(
                window, day_snaps, inference_snapshot_v1=inference_snapshot_v1
            )

        try:
            ref_spot = canonical_reference_spot_from_merged_window(merged_window)
        except ValueError as e:
            raise LstmSequenceInputError(str(e)) from e

        seq_5m = [encode_snapshot_5m(s, ref_spot) for s in merged_window]
        micro = merged_window[-STREAM_1M_LOOKBACK:]
        mr = _safe_float(micro[0].get("spot")) or ref_spot
        seq_1m = [encode_snapshot_1m(s, mr) for s in micro]

        conf = compute_confluence_features(merged_days, len(merged_days) - 1)
        conf_vec = [conf[k] for k in CONFLUENCE_FEATURES]

        snap = snapshot if snapshot is not None else _snap_dict(merged_window[-1])
        mask_conf = np.array(
            checkpoint.get("mask_conf", [True] * (len(conf_vec))),
            dtype=bool,
        )
        n_conf_base = len(CONFLUENCE_FEATURES)
        if mask_conf.shape[0] > n_conf_base:
            need = mask_conf.shape[0] - n_conf_base
            if need == _CASCADE_LSTM_CONF_EXTRA:
                if parallel_runtime:
                    raise ParallelRuntimeArtifactError(
                        f"LSTM {ticker}: checkpoint confluence mask expects cascade extras "
                        f"({mask_conf.shape[0]} vs base {n_conf_base}); use parallel-trained artifacts "
                        f"for production parallel runtime."
                    )
                xa = xgb_probs_arr
                if xa is None and snap is not None:
                    if inference_snapshot_v1 is None:
                        xa = np.full(_CASCADE_LSTM_CONF_EXTRA, 1.0 / 3.0, dtype=np.float32)
                    else:
                        xa = _probs_dict_to_arr(
                            _predict_xgb(inference_snapshot_v1, ticker, fusion_feature_overlay=snap)
                        )
                elif xa is None:
                    xa = np.full(_CASCADE_LSTM_CONF_EXTRA, 1.0 / 3.0, dtype=np.float32)
                xa = np.asarray(xa, dtype=np.float32).reshape(-1)
                if xa.shape[0] != _CASCADE_LSTM_CONF_EXTRA:
                    xa = np.full(_CASCADE_LSTM_CONF_EXTRA, 1.0 / 3.0, dtype=np.float32)
                conf_vec = conf_vec + xa.tolist()
            else:
                logger.warning(
                    "LSTM %s: unexpected cascade confluence width (mask %d, base %d)",
                    ticker, mask_conf.shape[0], n_conf_base,
                )
                return None

        X_5m   = np.array([seq_5m],   dtype=np.float32)
        X_1m   = np.array([seq_1m],   dtype=np.float32)
        X_conf = np.array([conf_vec], dtype=np.float32)

        mask_5m = np.array(checkpoint.get("mask_5m", [True] * X_5m.shape[2]))
        mask_1m = np.array(checkpoint.get("mask_1m", [True] * X_1m.shape[2]))
        if mask_conf.shape[0] != X_conf.shape[1]:
            logger.warning(
                "LSTM %s: mask_conf len %d vs conf width %d",
                ticker, mask_conf.shape[0], X_conf.shape[1],
            )
            return None
        X_5m   = X_5m[:, :, mask_5m]
        X_1m   = X_1m[:, :, mask_1m]
        X_conf = X_conf[:, mask_conf]

        norm = checkpoint.get("norm_stats", {})
        if norm:
            from lstm_model import align_lstm_norm_stats, apply_normalization

            aligned = align_lstm_norm_stats(norm, mask_5m, mask_1m, mask_conf)
            if aligned is None:
                logger.warning(
                    "LSTM %s: norm_stats could not be aligned to feature masks", ticker
                )
                return None
            X_5m, X_1m, X_conf = apply_normalization(X_5m, X_1m, X_conf, aligned)

        X_5m   = np.nan_to_num(X_5m,   nan=0.0, posinf=0.0, neginf=0.0)
        X_1m   = np.nan_to_num(X_1m,   nan=0.0, posinf=0.0, neginf=0.0)
        X_conf = np.nan_to_num(X_conf, nan=0.0, posinf=0.0, neginf=0.0)

        with torch.no_grad():
            logits = model(torch.from_numpy(X_1m).float(),
                           torch.from_numpy(X_5m).float(),
                           torch.from_numpy(X_conf).float())
            probs = torch.softmax(logits, dim=-1).squeeze().numpy()

        return {CLASS_NAMES[i]: round(float(probs[i]), 4) for i in range(3)}

    except LstmSequenceInputError:
        raise
    except ParallelRuntimeArtifactError:
        raise
    except Exception as e:
        logger.warning("LSTM prediction failed for %s: %s", ticker, e)
        return None


# ══════════════════════════════════════════════════════════════════════════════
# TRANSFORMER - per-ticker model
# ══════════════════════════════════════════════════════════════════════════════

def _load_transformer(ticker: str) -> bool:
    hz = get_ml_infer_horizon_slug()
    rk = _model_registry_key(ticker, hz)
    if rk in _trans_registry:
        return _trans_registry[rk] is not None

    base = _model_dir_for_ticker(ticker)
    mp = base / f"transformer_{ticker}_{hz}.pt"
    mtp = base / f"transformer_{ticker}_{hz}_meta.json"
    if not mp.exists():
        logger.debug("Transformer model not found for %s at %s", ticker, mp)
        _trans_registry[rk] = None
        return False
    if not mtp.exists():
        logger.error("Transformer %s: missing meta %s; refusing load.", ticker, mtp.name)
        _trans_registry[rk] = None
        return False

    try:
        with open(mtp, "r", encoding="utf-8") as f:
            tr_meta = json.load(f)
        from model_contract import validate_artifact_contract

        ok, reason = validate_artifact_contract(tr_meta, "transformer")
        if not ok:
            logger.error(
                "Transformer %s: incompatible model contract (%s). Retrain; refusing load.",
                ticker,
                reason,
            )
            _trans_registry[rk] = None
            return False

        import torch
        checkpoint = torch.load(str(mp), map_location="cpu", weights_only=False)
        from transformer_train import build_transformer
        model = build_transformer(
            checkpoint["n_features"],
            seq_len=checkpoint.get("seq_len", 20),
        )
        model.load_state_dict(checkpoint["model_state"])
        model.eval()
        _trans_registry[rk] = (model, checkpoint)
        logger.info("Transformer model loaded for %s hz=%s", ticker, hz)
        return True

    except ImportError as e:
        logger.debug("Transformer load skipped (missing dep: %s)", e)
        _trans_registry[rk] = None
        return False
    except Exception as e:
        logger.error("Transformer load failed for %s: %s", ticker, e)
        _trans_registry[rk] = None
        return False


def _predict_transformer(
    ticker: str,
    db,
    snapshot: Optional[dict] = None,
    xgb_probs_arr: Optional[np.ndarray] = None,
    lstm_probs_arr: Optional[np.ndarray] = None,
    timeframe: Optional[str] = None,
    *,
    inference_snapshot_v1: dict | None = None,
    parallel_runtime: bool = False,
    shared_sequence_context: Any = None,
) -> Optional[dict]:
    if not _load_transformer(ticker) or db is None:
        return None

    model, checkpoint = _trans_registry[_model_registry_key(ticker)]

    try:
        _asof = _require_as_of_ts_utc_for_sequence_db(inference_snapshot_v1)
    except LstmSequenceInputError as e:
        raise TransformerSequenceInputError(str(e)) from e

    try:
        import torch
        from lstm_data import (
            encode_snapshot_5m,
            _safe_float,
            CANONICAL_TIMEFRAME,
            FEATURES_5M,
            canonical_reference_spot_from_merged_window,
        )

        tf = timeframe or CANONICAL_TIMEFRAME
        seq_len = checkpoint.get("seq_len", 20)
        n_enc_base = len(FEATURES_5M)

        if shared_sequence_context is not None:
            from features.shared_sequence_context import transformer_window_chronological

            window = transformer_window_chronological(shared_sequence_context, seq_len)
        else:
            recent = db.get_recent_snapshots(
                ticker, tf, n=seq_len + 5, filled_only=False, as_of_ts_utc=_asof
            )
            if not recent or len(recent) < seq_len:
                raise TransformerSequenceInputError(
                    f"Transformer needs at least {seq_len} snapshots, got {len(recent or [])}"
                )
            recent = list(reversed(recent))
            window = recent[-seq_len:]

        merged_window = build_transformer_merged_window(
            window, inference_snapshot_v1=inference_snapshot_v1
        )

        try:
            ref_spot = canonical_reference_spot_from_merged_window(merged_window)
        except ValueError as e:
            raise TransformerSequenceInputError(str(e)) from e

        snap = snapshot if snapshot is not None else _snap_dict(merged_window[-1])
        seq = [encode_snapshot_5m(s, ref_spot) for s in merged_window]
        base = np.array([seq], dtype=np.float32)

        fm = np.asarray(
            checkpoint.get("feature_mask", np.ones(base.shape[2], dtype=bool)),
            dtype=bool,
        )

        if fm.shape[0] != base.shape[2]:
            if (
                fm.shape[0] == n_enc_base + _CASCADE_TRANSFORMER_SEQ_EXTRA
                and base.shape[2] == n_enc_base
            ):
                if parallel_runtime:
                    raise ParallelRuntimeArtifactError(
                        f"Transformer {ticker}: checkpoint feature_mask expects cascade sequence extras "
                        f"({fm.shape[0]} vs encode {n_enc_base}); use parallel-trained artifacts "
                        f"for production parallel runtime."
                    )
                if xgb_probs_arr is None:
                    if snap is None or inference_snapshot_v1 is None:
                        xgb_probs_arr = _probs_dict_to_arr(None)
                    else:
                        xgb_probs_arr = _probs_dict_to_arr(
                            _predict_xgb(inference_snapshot_v1, ticker, fusion_feature_overlay=snap)
                        )
                if lstm_probs_arr is None:
                    lstm_probs_arr = _probs_dict_to_arr(
                        _predict_lstm(
                            ticker,
                            db,
                            snapshot=snap,
                            xgb_probs_arr=xgb_probs_arr,
                            timeframe=tf,
                            inference_snapshot_v1=inference_snapshot_v1,
                            shared_sequence_context=shared_sequence_context,
                        )
                    )
                xa = np.asarray(xgb_probs_arr, dtype=np.float32).reshape(-1)
                la = np.asarray(lstm_probs_arr, dtype=np.float32).reshape(-1)
                if xa.shape[0] != 3:
                    xa = np.full(3, 1.0 / 3.0, dtype=np.float32)
                if la.shape[0] != 3:
                    la = np.full(3, 1.0 / 3.0, dtype=np.float32)
                six = np.concatenate([xa, la], axis=0)
                extra = np.broadcast_to(six.reshape(1, 1, 6), (1, seq_len, 6))
                X_raw = np.concatenate([base, extra.astype(np.float32)], axis=2)
            else:
                logger.warning(
                    "Transformer %s: cannot align feature_mask (%d) with encode width (%d)",
                    ticker, fm.shape[0], base.shape[2],
                )
                return None
        else:
            X_raw = base

        if X_raw.shape[2] != fm.shape[0]:
            logger.warning(
                "Transformer %s: raw tensor width %d vs feature_mask %d",
                ticker, X_raw.shape[2], fm.shape[0],
            )
            return None

        X = _transformer_normalize_and_select(X_raw, checkpoint)

        with torch.no_grad():
            logits = model(torch.from_numpy(X).float())
            probs_t = torch.softmax(logits, dim=-1)
            probs = probs_t.squeeze().detach().cpu().numpy()
        if probs.ndim > 1:
            probs = probs.reshape(-1, probs.shape[-1])[0]
        if probs.shape[0] != 3:
            logger.warning(
                "Transformer %s: unexpected prob shape %s", ticker, getattr(probs, "shape", None)
            )
            return None

        return {CLASS_NAMES[i]: round(float(probs[i]), 4) for i in range(3)}

    except TransformerSequenceInputError:
        raise
    except ParallelRuntimeArtifactError:
        raise
    except Exception as e:
        logger.warning("Transformer prediction failed for %s: %s", ticker, e)
        return None


# ══════════════════════════════════════════════════════════════════════════════
# META-LEARNER - logistic regression on stacked Layer 1 outputs
# ══════════════════════════════════════════════════════════════════════════════

def _load_meta(ticker: str) -> bool:
    hz = get_ml_infer_horizon_slug()
    rk = _model_registry_key(ticker, hz)
    if rk in _meta_registry:
        return _meta_registry[rk] is not None

    base = _model_dir_for_ticker(ticker)
    mp = base / f"meta_{ticker}_{hz}.pkl"
    if not mp.exists():
        _meta_registry[rk] = None
        return False

    try:
        with open(mp, "rb") as f:
            _meta_registry[rk] = pickle.load(f)
        logger.info("Meta-learner loaded for %s hz=%s", ticker, hz)
        return True
    except Exception as e:
        logger.error("Meta-learner load failed for %s: %s", ticker, e)
        _meta_registry[rk] = None
        return False


def _stack_probs(xgb_p, lstm_p, trans_p) -> np.ndarray:
    """Stack Layer 1 outputs into 9-feature vector. Missing = uniform 0.333."""
    uniform = [0.333, 0.333, 0.334]
    def _to_vec(p):
        return [p.get(c, uniform[i]) for i,c in enumerate(CLASS_NAMES)] if p else uniform
    return np.array(_to_vec(xgb_p) + _to_vec(lstm_p) + _to_vec(trans_p),
                    dtype=np.float64).reshape(1, -1)


def _predict_meta(ticker: str, xgb_p, lstm_p, trans_p) -> Optional[dict]:
    if not _load_meta(ticker):
        return None
    try:
        X     = _stack_probs(xgb_p, lstm_p, trans_p)
        probs = _meta_registry[_model_registry_key(ticker)].predict_proba(X)[0]
        return {CLASS_NAMES[i]: round(float(probs[i]), 4) for i in range(3)}
    except Exception as e:
        logger.warning("Meta-learner prediction failed for %s: %s", ticker, e)
        return None


def _weighted_average(ticker: str, xgb_p, lstm_p, trans_p) -> Optional[dict]:
    """Weighted average when meta-learner not trained. XGB=0.40, LSTM=0.35, TR=0.25. Renormalize if any missing."""
    contributions = []
    if xgb_p:
        contributions.append((xgb_p, 0.40))
    if lstm_p:
        contributions.append((lstm_p, 0.35))
    if trans_p:
        contributions.append((trans_p, 0.25))

    if not contributions:
        return None

    total_w = sum(w for _, w in contributions)
    result  = {c: 0.0 for c in CLASS_NAMES}
    for probs, w in contributions:
        for c in CLASS_NAMES:
            result[c] += probs.get(c, 0.333) * w / total_w
    return {c: round(result[c], 4) for c in CLASS_NAMES}


def _apply_5c_xgb_plus_transformer_isotonic_calibration(
    ticker: str,
    probs: Optional[dict],
) -> Optional[dict]:
    """
    Runtime calibration for 5c winning stack (xgb_plus_transformer) using
    one-vs-rest isotonic regression maps fit from validation outputs.

    Applies only to SPY/5c blended probabilities and preserves simplex normalization.
    """
    if not probs:
        return probs
    if str(ticker or "").upper() != "SPY":
        return probs
    if get_ml_infer_horizon_slug() != "5c":
        return probs

    # OVR isotonic maps from validation cohort (X_thresholds_, y_thresholds_).
    maps = {
        "up": {
            "x": [0.0639, 0.1053, 0.10531053105310531, 0.1442, 0.1443, 0.1593, 0.15978402159784022, 0.1937, 0.194, 0.20492049204920493, 0.205, 0.3056, 0.3071, 0.3242, 0.3243, 0.3498, 0.3512, 0.3971, 0.3986, 0.44144414441444146, 0.4436, 0.4645, 0.4667533246675332, 0.4765, 0.4774, 0.4908509149085092, 0.4914, 0.5041495850414959, 0.5050505050505051, 0.5116, 0.512, 0.5696, 0.579, 0.6160383961603839],
            "y": [0.0, 0.0, 0.028846153846153848, 0.028846153846153848, 0.09090909090909091, 0.09090909090909091, 0.14754098360655737, 0.14754098360655737, 0.15384615384615385, 0.15384615384615385, 0.2222222222222222, 0.2222222222222222, 0.2631578947368421, 0.2631578947368421, 0.4074074074074074, 0.4074074074074074, 0.4090909090909091, 0.4090909090909091, 0.5, 0.5, 0.5625, 0.5625, 0.6363636363636364, 0.6363636363636364, 0.6470588235294118, 0.6470588235294118, 0.6666666666666666, 0.6666666666666666, 0.75, 0.75, 0.8888888888888888, 0.8888888888888888, 1.0, 1.0],
        },
        "down": {
            "x": [0.0471, 0.08680868086808681, 0.0869, 0.1111, 0.1114111411141114, 0.1386, 0.1389, 0.15548445155484447, 0.1559, 0.2506, 0.251, 0.26030000000000003, 0.2604, 0.3232, 0.32356764323567644, 0.436, 0.43755624437556245, 0.4625, 0.4642, 0.471, 0.4714, 0.4753, 0.4755, 0.4819, 0.4822, 0.5019, 0.5023, 0.607039296070393],
            "y": [0.0, 0.0, 0.014598540145985401, 0.014598540145985401, 0.0375, 0.0375, 0.043478260869565216, 0.043478260869565216, 0.08695652173913043, 0.08695652173913043, 0.1111111111111111, 0.1111111111111111, 0.18867924528301888, 0.18867924528301888, 0.32, 0.32, 0.5, 0.5, 0.6363636363636364, 0.6363636363636364, 0.75, 0.75, 0.7692307692307693, 0.7692307692307693, 0.8, 0.8, 0.9333333333333333, 0.9333333333333333],
        },
        "flat": {
            "x": [0.2429, 0.2636736326367363, 0.29892989298929895, 0.3063306330633063, 0.36423642364236425, 0.3662, 0.3828382838283828, 0.38303830383038306, 0.3986, 0.399, 0.4172, 0.4177, 0.41885811418858115, 0.419, 0.4281571842815718, 0.4293, 0.4423, 0.4436, 0.45825417458254175, 0.4588458845884588, 0.4995, 0.4996, 0.5050494950504949, 0.5053, 0.5333, 0.5335, 0.5428, 0.5437456254374562, 0.5672, 0.568, 0.5937406259374063, 0.5939, 0.6129, 0.6129612961296129, 0.6453, 0.6454, 0.6845, 0.685, 0.6932, 0.6951, 0.734073407340734, 0.7348, 0.7418, 0.7443, 0.7861786178617862, 0.7867786778677868, 0.8318, 0.8325, 0.8816],
            "y": [0.0, 0.125, 0.125, 0.19230769230769232, 0.19230769230769232, 0.2222222222222222, 0.2222222222222222, 0.25, 0.25, 0.3125, 0.3125, 0.375, 0.375, 0.4444444444444444, 0.4444444444444444, 0.4642857142857143, 0.4642857142857143, 0.4666666666666667, 0.4666666666666667, 0.4923076923076923, 0.4923076923076923, 0.5, 0.5, 0.5106382978723404, 0.5106382978723404, 0.5555555555555556, 0.5555555555555556, 0.5609756097560976, 0.5609756097560976, 0.5636363636363636, 0.5636363636363636, 0.7441860465116279, 0.7441860465116279, 0.8163265306122449, 0.8163265306122449, 0.8428571428571429, 0.8428571428571429, 0.8666666666666667, 0.8666666666666667, 0.8771929824561403, 0.8771929824561403, 0.9333333333333333, 0.9333333333333333, 0.9565217391304348, 0.9565217391304348, 0.9702970297029703, 0.9702970297029703, 1.0, 1.0],
        },
    }

    calibrated = {}
    for c in CLASS_NAMES:
        p = float(probs.get(c, 1.0 / 3.0))
        p = max(0.0, min(1.0, p))
        x = np.asarray(maps[c]["x"], dtype=np.float64)
        y = np.asarray(maps[c]["y"], dtype=np.float64)
        calibrated[c] = float(np.interp(p, x, y, left=y[0], right=y[-1]))

    s = float(sum(calibrated.values()))
    if s <= 0.0:
        return {"up": 1.0 / 3.0, "down": 1.0 / 3.0, "flat": 1.0 / 3.0}
    norm = {c: float(calibrated[c] / s) for c in CLASS_NAMES}
    # Keep exact simplex sum after float math.
    norm["flat"] = max(0.0, 1.0 - norm["up"] - norm["down"])
    return norm


# ══════════════════════════════════════════════════════════════════════════════
# FUSION API — model outputs with probabilities for bayesian_fusion
# ══════════════════════════════════════════════════════════════════════════════

def run_base_models_once(
    snapshot: dict,
    ticker: str,
    db,
    direction_hint: str = "wait",
    *,
    inference_snapshot_v1: dict | None = None,
    xgb_pre_engineering_snapshot: dict | None = None,
    shared_sequence_context: Any = None,
) -> dict:
    """
    Production **parallel** runtime: XGB, LSTM, and Transformer run **independently** (no cross-model
    tensors). Sequence models use `parallel_runtime=True` and refuse cascade-only checkpoints.

    Feeds fusion helpers, UI model_outputs, and optional meta / weighted stack probs — single pass.

    XGBoost requires InferenceSnapshotV1. Pass `snapshot` as fusion overlay only (pred_*, et_hour, …);
    MVP comes only from `inference_snapshot_v1`.

    Optional ``xgb_pre_engineering_snapshot`` (from ``build_xgb_pre_engineering_snapshot_for_tick``)
    avoids repeating MVP→overlay→m5 ingest for each governed horizon on the same tick.

    Optional ``shared_sequence_context`` (from ``features.shared_sequence_context.build_shared_sequence_context``)
    supplies one DB fetch + one LSTM merge for the tick; LSTM/Transformer skip redundant history reads.
    """
    tkr = ticker or snapshot.get("ticker", "") or ""
    if not tkr:
        return {
            "fusion": {"xgb": None, "lstm": None, "transformer": None},
            "model_outputs": {
                "xgb": {"available": False, "dominant": None, "confidence": None, "approved": False},
                "lstm": {"available": False, "dominant": None, "confidence": None, "approved": False},
                "transformer": {"available": False, "dominant": None, "confidence": None, "approved": False},
            },
            stack_probs_bundle_key(): None,
            "movement_head_probs": {},
            "parallel_runtime": True,
            "stack_schema_version": PARALLEL_STACK_SCHEMA_VERSION,
        }

    if inference_snapshot_v1 is None:
        raise ValueError(
            "run_base_models_once requires inference_snapshot_v1= (InferenceSnapshotV1 dict). "
            "Raw fusion snapshots are not accepted for XGB."
        )

    xgb_p = _predict_xgb(
        inference_snapshot_v1,
        tkr,
        fusion_feature_overlay=snapshot,
        xgb_pre_engineering_snapshot=xgb_pre_engineering_snapshot,
    )
    lstm_p = _predict_lstm(
        tkr,
        db,
        snapshot=snapshot,
        xgb_probs_arr=None,
        inference_snapshot_v1=inference_snapshot_v1,
        parallel_runtime=True,
        shared_sequence_context=shared_sequence_context,
    )
    tr_p = _predict_transformer(
        tkr,
        db,
        snapshot=snapshot,
        xgb_probs_arr=None,
        lstm_probs_arr=None,
        inference_snapshot_v1=inference_snapshot_v1,
        parallel_runtime=True,
        shared_sequence_context=shared_sequence_context,
    )

    def _to_fusion_out(p: Optional[dict], hint: str) -> Optional[dict]:
        if p is None:
            return None
        up = p.get("up", 0.33)
        down = p.get("down", 0.33)
        flat = p.get("flat", 0.34)
        dominant = max(CLASS_NAMES, key=lambda c: p.get(c, 0))
        edge = p.get(dominant, 0.333) - 0.333
        conf_label = "high" if edge >= 0.15 else "medium" if edge >= 0.08 else "low"
        if hint == "long":
            cont_support, rev_support = up, down
        elif hint == "short":
            cont_support, rev_support = down, up
        else:
            cont_support, rev_support = flat, max(up, down)
        return {
            "available": True,
            "prob_up": up, "prob_down": down, "prob_flat": flat,
            "dominant_class": dominant,
            "confidence_label": conf_label,
            "continuation_support": cont_support,
            "reversal_support": rev_support,
        }

    def _to_ui_output(p: Optional[dict], approved: bool) -> dict:
        if p is None:
            return {"available": False, "dominant": None, "confidence": None, "approved": False}
        probs = p
        dominant = max(CLASS_NAMES, key=lambda c: probs.get(c, 0))
        max_prob = probs.get(dominant, 0.333)
        confidence = round(max_prob - 0.333, 4)
        return {
            "available": True,
            "dominant": dominant,
            "confidence": confidence,
            "approved": approved,
            "up": round(float(probs.get("up", 0.333)), 4),
            "down": round(float(probs.get("down", 0.333)), 4),
            "flat": round(float(probs.get("flat", 0.334)), 4),
        }

    fusion_pack = {
        "xgb": _to_fusion_out(xgb_p, direction_hint),
        "lstm": _to_fusion_out(lstm_p, direction_hint),
        "transformer": _to_fusion_out(tr_p, direction_hint),
    }
    def _parallel_model_output_record(p: Optional[dict], approved: bool) -> dict:
        r = build_parallel_base_output(probs=p, approved=approved and p is not None)
        if r.get("available"):
            r["up"] = r["prob_up"]
            r["down"] = r["prob_down"]
            r["flat"] = r["prob_flat"]
            r["confidence"] = r["confidence_score"]
        else:
            r["up"] = None
            r["down"] = None
            r["flat"] = None
            r["confidence"] = None
            r["dominant"] = None
        return r

    model_outputs = {
        "xgb": _parallel_model_output_record(xgb_p, xgb_p is not None),
        "lstm": _parallel_model_output_record(lstm_p, lstm_p is not None),
        "transformer": _parallel_model_output_record(tr_p, tr_p is not None),
    }

    stack_probs = None
    if xgb_p is not None or lstm_p is not None or tr_p is not None:
        # 5c default runtime path: winning stack is xgb_plus_transformer with
        # calibrated probabilities before downstream decision consumption.
        if get_ml_infer_horizon_slug() == "5c":
            stack_probs = _weighted_average(tkr, xgb_p, None, tr_p)
            stack_probs = _apply_5c_xgb_plus_transformer_isotonic_calibration(
                tkr, stack_probs
            )
        else:
            if _load_meta(tkr):
                stack_probs = _predict_meta(tkr, xgb_p, lstm_p, tr_p)
            if stack_probs is None:
                stack_probs = _weighted_average(tkr, xgb_p, lstm_p, tr_p)

    logger.debug(
        "run_base_models_once %s: xgb=%s lstm=%s tr=%s",
        tkr,
        _fmt(xgb_p),
        _fmt(lstm_p),
        _fmt(tr_p),
    )
    _mh = _predict_xgb_movement_heads(
        inference_snapshot_v1,
        tkr,
        fusion_feature_overlay=snapshot,
        xgb_pre_engineering_snapshot=xgb_pre_engineering_snapshot,
    )
    return {
        "fusion": fusion_pack,
        "model_outputs": model_outputs,
        stack_probs_bundle_key(): stack_probs,
        "movement_head_probs": _mh,
        "parallel_runtime": True,
        "stack_schema_version": PARALLEL_STACK_SCHEMA_VERSION,
    }


def run_cascade_models_once(
    snapshot: dict,
    ticker: str,
    db,
    direction_hint: str = "wait",
    *,
    inference_snapshot_v1: dict | None = None,
    expected_data_fingerprint: str | None = None,
    actual_data_fingerprint: str | None = None,
    expected_feature_contract_version: str | None = None,
    expected_canonical_timeframe: str | None = None,
    lineage_extra: dict | None = None,
) -> dict:
    """
    Challenger-only **cascade** inference: XGB → LSTM (with XGB prob tensor) → Transformer
    (with XGB + LSTM prob tensors). Loads artifacts from ``models/cascade/{ticker}/`` only.

    Does **not** change production routing; use ``run_base_models_once`` for live parallel stack.

    Lineage kwargs enforce parity with shared training cache when set (evaluation harness).
    """
    tkr = ticker or snapshot.get("ticker", "") or ""
    if not tkr:
        raise CascadeChallengerError("cascade challenger: empty ticker")

    validate_cascade_inference_lineage(
        inference_snapshot_v1,
        expected_data_fingerprint=expected_data_fingerprint,
        actual_data_fingerprint=actual_data_fingerprint,
        expected_feature_contract_version=expected_feature_contract_version,
        expected_canonical_timeframe=expected_canonical_timeframe,
    )
    assert_no_legacy_mvp_in_fusion_overlay(snapshot)

    def _fusion_out(p: Optional[dict], hint: str) -> Optional[dict]:
        if p is None:
            return None
        up = p.get("up", 0.33)
        down = p.get("down", 0.33)
        flat = p.get("flat", 0.34)
        dominant = max(CLASS_NAMES, key=lambda c: p.get(c, 0))
        edge = p.get(dominant, 0.333) - 0.333
        conf_label = "high" if edge >= 0.15 else "medium" if edge >= 0.08 else "low"
        if hint == "long":
            cont_support, rev_support = up, down
        elif hint == "short":
            cont_support, rev_support = down, up
        else:
            cont_support, rev_support = flat, max(up, down)
        return {
            "available": True,
            "prob_up": up,
            "prob_down": down,
            "prob_flat": flat,
            "dominant_class": dominant,
            "confidence_label": conf_label,
            "continuation_support": cont_support,
            "reversal_support": rev_support,
        }

    def _parallel_model_output_record(p: Optional[dict], approved: bool) -> dict:
        r = build_parallel_base_output(probs=p, approved=approved and p is not None)
        if r.get("available"):
            r["up"] = r["prob_up"]
            r["down"] = r["prob_down"]
            r["flat"] = r["prob_flat"]
            r["confidence"] = r["confidence_score"]
        else:
            r["up"] = None
            r["down"] = None
            r["flat"] = None
            r["confidence"] = None
            r["dominant"] = None
        return r

    with _cascade_challenger_inference_scope():
        xgb_p = _predict_xgb(inference_snapshot_v1, tkr, fusion_feature_overlay=snapshot)
        if xgb_p is None:
            raise CascadeStageError(f"{tkr}: cascade stage 1 (XGB) produced no probabilities")
        xgb_arr = _probs_dict_to_arr(xgb_p)

        lstm_p = _predict_lstm(
            tkr,
            db,
            snapshot=snapshot,
            xgb_probs_arr=xgb_arr,
            inference_snapshot_v1=inference_snapshot_v1,
            parallel_runtime=False,
        )
        if lstm_p is None:
            raise CascadeStageError(f"{tkr}: cascade stage 2 (LSTM) produced no probabilities")
        lstm_arr = _probs_dict_to_arr(lstm_p)

        tr_p = _predict_transformer(
            tkr,
            db,
            snapshot=snapshot,
            xgb_probs_arr=xgb_arr,
            lstm_probs_arr=lstm_arr,
            inference_snapshot_v1=inference_snapshot_v1,
            parallel_runtime=False,
        )
        if tr_p is None:
            raise CascadeStageError(f"{tkr}: cascade stage 3 (Transformer) produced no probabilities")

        fusion_pack = {
            "xgb": _fusion_out(xgb_p, direction_hint),
            "lstm": _fusion_out(lstm_p, direction_hint),
            "transformer": _fusion_out(tr_p, direction_hint),
        }
        model_outputs = {
            "xgb": _parallel_model_output_record(xgb_p, True),
            "lstm": _parallel_model_output_record(lstm_p, True),
            "transformer": _parallel_model_output_record(tr_p, True),
        }

        stack_probs = None
        if _load_meta(tkr):
            stack_probs = _predict_meta(tkr, xgb_p, lstm_p, tr_p)
        if stack_probs is None:
            stack_probs = _weighted_average(tkr, xgb_p, lstm_p, tr_p)

    lineage = build_cascade_challenger_run_metadata(
        data_fingerprint=actual_data_fingerprint,
        ml_horizon_slug=get_ml_infer_horizon_slug(),
    )
    if lineage_extra:
        lineage = {**lineage, **lineage_extra}

    stages = {
        "1_xgb": {
            "probabilities": xgb_p,
            "upstream_bundle_version": CASCADE_UPSTREAM_BUNDLE_VERSION,
        },
        "2_lstm": {
            "probabilities": lstm_p,
            "cascade_inputs_from_xgb_probs": [float(x) for x in xgb_arr.reshape(-1)],
        },
        "3_transformer": {
            "probabilities": tr_p,
            "cascade_inputs_from_xgb_probs": [float(x) for x in xgb_arr.reshape(-1)],
            "cascade_inputs_from_lstm_probs": [float(x) for x in lstm_arr.reshape(-1)],
        },
    }

    return {
        "architecture": "cascade",
        "schema_version": CASCADE_STACK_SCHEMA_VERSION,
        "parallel_runtime": False,
        "upstream_bundle_version": CASCADE_UPSTREAM_BUNDLE_VERSION,
        "fusion": fusion_pack,
        "model_outputs": model_outputs,
        stack_probs_bundle_key(): stack_probs,
        "stages": stages,
        "lineage": lineage,
    }


def get_model_outputs_for_fusion(
    snapshot: dict,
    ticker: str,
    db,
    direction_hint: str = "wait",
    *,
    inference_snapshot_v1: dict | None = None,
) -> dict:
    """
    Return structured outputs for fusion. Delegates to run_base_models_once — single inference truth per tick.
    """
    tkr = ticker or snapshot.get("ticker", "") or ""
    if not tkr:
        return {"xgb": None, "lstm": None, "transformer": None}
    return run_base_models_once(
        snapshot, tkr, db, direction_hint, inference_snapshot_v1=inference_snapshot_v1
    )["fusion"]


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ══════════════════════════════════════════════════════════════════════════════

def get_model_outputs(
    snapshot: dict,
    ticker: str = None,
    db=None,
    *,
    inference_snapshot_v1: dict | None = None,
) -> dict:
    """
    Run XGBoost, LSTM, Transformer individually and return availability,
    dominant direction, and confidence for each. Used for stack visibility
    in snapshots — does not affect prediction logic.

    Returns:
        {
            "xgb": {"available": bool, "dominant": str|None, "confidence": float|None, "approved": bool},
            "lstm": {"available": bool, "dominant": str|None, "confidence": float|None, "approved": bool},
            "transformer": {"available": bool, "dominant": str|None, "confidence": float|None, "approved": bool},
        }
    """
    tkr = ticker or snapshot.get("ticker", "")
    if not tkr:
        return {
            "xgb": {"available": False, "dominant": None, "confidence": None, "approved": False},
            "lstm": {"available": False, "dominant": None, "confidence": None, "approved": False},
            "transformer": {"available": False, "dominant": None, "confidence": None, "approved": False},
        }
    return run_base_models_once(
        snapshot, tkr, db, "wait", inference_snapshot_v1=inference_snapshot_v1
    )["model_outputs"]


def predict_direction(
    snapshot: dict,
    ticker: str = None,
    db=None,
    *,
    inference_snapshot_v1: dict | None = None,
) -> Optional[dict]:
    """
    Full stacked prediction.

    Runs XGBoost + LSTM + Transformer, combines via meta-learner (or
    weighted average if meta-learner not yet trained).

    Returns {up, down, flat} or None (caller uses rules engine).

    Args:
        snapshot: fusion overlay (pred_*, et_hour, …) — not used for MVP tabular fields
        ticker:   ticker symbol; uses snapshot['ticker'] if None
        db:       EdDB instance (needed for LSTM/Transformer sequence access)
        inference_snapshot_v1: required InferenceSnapshotV1 dict for XGB MVP path
    """
    tkr = ticker or snapshot.get("ticker", "")
    if not tkr:
        return None
    return run_base_models_once(
        snapshot, tkr, db, "wait", inference_snapshot_v1=inference_snapshot_v1
    )[stack_probs_bundle_key()]


def predict_all_horizons(
    snapshot: dict,
    ticker: str = None,
    db=None,
    *,
    inference_snapshot_v1: dict | None = None,
) -> dict:
    """Predict for UI horizon keys; only the live ML product horizon runs the trained stack."""
    result = {}
    live_ml_hz = live_inference_horizon_slug()
    for hz in PRIMARY_DECISION_HORIZONS:
        result[hz] = (
            predict_direction(snapshot, ticker, db, inference_snapshot_v1=inference_snapshot_v1)
            if hz == live_ml_hz
            else None
        )
    return result


def is_available(ticker: str) -> bool:
    """True if ANY of xgb, LSTM, or Transformer model exists for this ticker."""
    hz = get_ml_infer_horizon_slug()
    base = _model_dir_for_ticker(ticker)
    return (
        (base / f"xgb_{ticker}_{hz}.pkl").exists()
        or (base / f"lstm_{ticker}_{hz}.pt").exists()
        or (base / f"transformer_{ticker}_{hz}.pt").exists()
    )


def get_model_version(ticker: str) -> str:
    """Version string for dashboard display."""
    hz = get_ml_infer_horizon_slug()
    base = _model_dir_for_ticker(ticker)
    parts = []
    if (base / f"xgb_{ticker}_{hz}.pkl").exists():        parts.append("xgb")
    if (base / f"lstm_{ticker}_{hz}.pt").exists():        parts.append("lstm")
    if (base / f"transformer_{ticker}_{hz}.pt").exists(): parts.append("tr")
    if (base / f"meta_{ticker}_{hz}.pkl").exists():       parts.append("meta")
    if parts:
        return f"stack({'_'.join(parts)})_{hz}"
    return "rules_v1"


def get_component_status(ticker: str) -> dict:
    """Which components are active. Used for dashboard health display."""
    return {
        "xgb":         "approved" if _load_xgb(ticker)       else "unavailable",
        "lstm":        "approved" if _load_lstm(ticker)      else "unavailable",
        "transformer": "approved" if _load_transformer(ticker) else "unavailable",
        "meta":        "loaded"   if _load_meta(ticker)     else "not trained yet",
        "stack_ready": _load_xgb(ticker) or _load_lstm(ticker) or _load_transformer(ticker),
    }


def reset_caches():
    """Clear all loaded models. Call this after retraining."""
    global _xgb_registry, _xgb_movehead_registry, _meta_registry, _lstm_registry, _trans_registry
    _xgb_registry   = {}
    _xgb_movehead_registry = {}
    _meta_registry  = {}
    _lstm_registry  = {}
    _trans_registry = {}
    logger.info("ml_predict: all model caches cleared")


def _fmt(p):
    if p is None: return "None"
    return f"up={p['up']:.2f} dn={p['down']:.2f} fl={p['flat']:.2f}"
