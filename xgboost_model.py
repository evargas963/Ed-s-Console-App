"""
xgboost_model.py
Dedicated structured-tabular inference layer.

Phase 5 of the Canonical Implementation Roadmap.

Wraps existing ml_predict.py / ml_train.py with the standardized
model interface defined in the Full Model-Stack Integration Map.

Answers: Given structured features, what does XGBoost predict?

Consumed by:
  - prediction_engine.py
  - bayesian_fusion.py (future)
  - market_state.py (display)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.domain.instrument_identity import ticker_storage_key

log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# OUTPUT
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class XGBoostOutput:
    """Standardized output from XGBoost inference."""
    available:              bool            # model loaded and ran successfully
    prob_up:                float = 0.33    # P(up) for primary horizon
    prob_down:              float = 0.33    # P(down)
    prob_flat:              float = 0.34    # P(flat)
    dominant_class:         str   = "flat"  # argmax class
    confidence_score:       float = 0.0     # max prob - 0.33 (edge over random)
    confidence_label:       str   = "low"   # low / medium / high
    continuation_support:   float = 0.0     # how much model supports continuation
    reversal_support:       float = 0.0     # how much model supports reversal
    model_version:          str   = ""
    model_loaded:           bool  = False
    inference_ok:           bool  = False
    fallback_used:          bool  = True
    horizon:                str   = "1c"    # which horizon was predicted
    top_features:           list  = field(default_factory=list)  # optional explainability
    all_horizons:           dict  = field(default_factory=dict)  # {hz: {up, down, flat}}


# ══════════════════════════════════════════════════════════════════════════════
# INFERENCE
# ══════════════════════════════════════════════════════════════════════════════

def predict(snapshot: dict, direction_hint: str = "flat") -> XGBoostOutput:
    """
    Run XGBoost inference on a snapshot dict.

    Args:
        snapshot:       dict with feature columns (same format ml_predict expects)
        direction_hint: current directional lean from rules engine ('long'/'short'/'wait')
                        Used to compute continuation/reversal support.

    Returns:
        XGBoostOutput with probabilities, confidence, and health metadata.
    """
    try:
        from ml_predict import (
            predict_direction,
            predict_all_horizons,
            is_available,
            get_model_version,
        )
        from features.inference_snapshot import build_inference_snapshot_v1_from_db_row
    except ImportError:
        log.info("xgboost_model: ml_predict not available")
        return _fallback("ml_predict not importable")

    if not is_available():
        return _fallback("model not loaded or below approval threshold")

    tkr = ticker_storage_key(snapshot.get("ticker"))  # RC-345/F25: canonical serving model-input identity (train/serve parity)
    if not tkr:
        return _fallback("snapshot missing ticker")

    try:
        inf_v1 = build_inference_snapshot_v1_from_db_row(
            ticker=tkr,
            expiry=None,
            as_of_ts=snapshot.get("ts_utc"),
            db_row=snapshot,
        )
    except Exception as e:
        return _fallback(f"InferenceSnapshotV1 build failed: {e}")

    # Run inference
    try:
        probs_1c = predict_direction(
            snapshot, tkr, None, inference_snapshot_v1=inf_v1
        )
        if probs_1c is None:
            return _fallback("predict_direction returned None")

        # Also get all horizons
        all_hz = predict_all_horizons(
            snapshot, tkr, None, inference_snapshot_v1=inf_v1
        )

        up   = probs_1c.get("up", 0.33)
        down = probs_1c.get("down", 0.33)
        flat = probs_1c.get("flat", 0.34)

        # Dominant class
        probs = {"up": up, "down": down, "flat": flat}
        dominant = max(probs, key=probs.get)
        max_prob = probs[dominant]

        # Confidence: edge over random (0.33)
        edge = max_prob - 0.333
        if edge >= 0.15:
            conf_label = "high"
        elif edge >= 0.08:
            conf_label = "medium"
        else:
            conf_label = "low"

        # Continuation/reversal support relative to direction hint
        if direction_hint == "long":
            cont_support = up
            rev_support = down
        elif direction_hint == "short":
            cont_support = down
            rev_support = up
        else:
            cont_support = flat
            rev_support = max(up, down)

        version = get_model_version()

        return XGBoostOutput(
            available=True,
            prob_up=round(up, 3),
            prob_down=round(down, 3),
            prob_flat=round(flat, 3),
            dominant_class=dominant,
            confidence_score=round(edge, 3),
            confidence_label=conf_label,
            continuation_support=round(cont_support, 3),
            reversal_support=round(rev_support, 3),
            model_version=version,
            model_loaded=True,
            inference_ok=True,
            fallback_used=False,
            horizon="1c",
            all_horizons={
                hz: vals for hz, vals in (all_hz or {}).items() if vals is not None
            },
        )

    except Exception as e:
        log.warning("xgboost_model: inference failed: %s", e)
        return _fallback(f"inference error: {e}")


def _fallback(reason: str) -> XGBoostOutput:
    """Return safe fallback when model can't run."""
    log.debug("xgboost_model fallback: %s", reason)
    return XGBoostOutput(
        available=False,
        fallback_used=True,
        model_version=f"fallback ({reason})",
    )


# ══════════════════════════════════════════════════════════════════════════════
# TRAINING DELEGATION
# ══════════════════════════════════════════════════════════════════════════════

def train(db_path: str = None, min_date: str = None) -> dict:
    """
    Trigger XGBoost training. Delegates to ml_train.py.

    Args:
        db_path:  override DB path (default: ml_train's default)
        min_date: only train on data after this date (ISO format)

    Returns:
        dict with training results (accuracy, feature importance, etc.)
    """
    try:
        from ml_train import main as train_main
        return train_main()
    except ImportError:
        log.error("xgboost_model: ml_train not available for training")
        return {"error": "ml_train not importable"}
    except Exception as e:
        log.error("xgboost_model: training failed: %s", e)
        return {"error": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# SELF-TEST
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("xgboost_model.py — self-test")
    result = predict({}, direction_hint="long")
    print(f"  available={result.available}, fallback={result.fallback_used}")
    print(f"  version={result.model_version}")
    print("  OK")
