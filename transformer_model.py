"""
transformer_model.py
Dedicated sequence/context inference layer.

Phase 5 of the Canonical Implementation Roadmap.

Answers: Given the ordered multi-step market context, what does the
Transformer model predict about continuation, reversal, breakout,
and directional evolution?

Architecture:
  - Input: ordered sequence of bar-level features (1m snapshots; predict() uses DB)
  - Model: Transformer encoder with classification head
  - Output: directional probabilities + continuation/reversal support

Status: scaffold with fallback. Model artifacts produced by
transformer_train.py.

Consumed by:
  - prediction_engine.py
  - bayesian_fusion.py (future)
  - market_state.py (display)
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List

log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# PATHS
# ══════════════════════════════════════════════════════════════════════════════

from transformer_train import transformer_model_path, transformer_meta_path
from ml_horizon import DEFAULT_ML_HORIZON_SLUG, normalize_ml_horizon_slug
from features.lstm_sequence_input import TransformerSequenceInputError


def _horizon_label_from_meta(meta: dict | None) -> str:
    """Match trained artifact: meta.target_column outcome_15c -> 15c."""
    if not meta:
        return DEFAULT_ML_HORIZON_SLUG
    tc = (meta.get("target_column") or "").strip().lower()
    if tc.startswith("outcome_"):
        try:
            return normalize_ml_horizon_slug(tc[len("outcome_") :])
        except ValueError:
            pass
    return DEFAULT_ML_HORIZON_SLUG


# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════

SEQUENCE_LENGTH = 20    # number of bars in input sequence
MIN_SEQUENCE    = 10    # minimum usable sequence length (padded if shorter)


# ══════════════════════════════════════════════════════════════════════════════
# OUTPUT
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class TransformerOutput:
    """Standardized output from Transformer inference."""
    available:              bool            # model loaded and ran successfully
    prob_up:                float = 0.33
    prob_down:              float = 0.33
    prob_flat:              float = 0.34
    dominant_class:         str   = "flat"
    confidence_score:       float = 0.0     # edge over random
    confidence_label:       str   = "low"
    continuation_support:   float = 0.0
    reversal_support:       float = 0.0
    breakout_support:       float = 0.0     # Transformer-specific: breakout detection
    breakout_failure_support: float = 0.0   # failed breakout detection
    model_version:          str   = ""
    model_loaded:           bool  = False
    inference_ok:           bool  = False
    fallback_used:          bool  = True
    horizon:                str   = DEFAULT_ML_HORIZON_SLUG
    sequence_length_used:   int   = 0       # how many bars were fed in
    attention_summary:      list  = field(default_factory=list)  # optional: top attended bars


# ══════════════════════════════════════════════════════════════════════════════
# SEQUENCE PREPARATION
# ══════════════════════════════════════════════════════════════════════════════

def _prepare_sequence(
    candles_5m: list,
    inp,
    reference_spot: float,
) -> Optional[list]:
    """
    Convert candle history + context into a model-ready feature sequence.
    Param name candles_5m is legacy; can receive 1m or 5m bars. Predict path uses DB snapshots.

    **Production / stack inference:** ``reference_spot`` is required (canonical / governed
    normalization anchor). The input object's spot field is not read for normalization — legacy
    implicit use was removed.

    Each step in the sequence is a feature vector combining:
      - OHLCV from the candle
      - Level distances at that bar (approximated from current distances)
      - Greeks snapshot (approximated as constant over short window)

    Returns list of dicts, one per bar, or None if insufficient data.
    """
    if not candles_5m or len(candles_5m) < MIN_SEQUENCE:
        return None

    # Use the most recent SEQUENCE_LENGTH bars
    bars = candles_5m[-SEQUENCE_LENGTH:]
    try:
        spot = float(reference_spot)
    except (TypeError, ValueError):
        return None
    if spot <= 0:
        return None

    sequence = []
    for candle in bars:
        o = candle.open
        h = candle.high
        l = candle.low
        c = candle.close
        v = candle.volume

        if spot > 0:
            ret = (c - o) / spot  # return for this bar
            rng = (h - l) / spot  # range for this bar
            pos = (c - spot) / spot  # position relative to current spot
        else:
            ret = rng = pos = 0.0

        step = {
            "return": ret,
            "range": rng,
            "position": pos,
            "volume": float(v) if v else 0.0,
            # Static context (same for all bars — approximation)
            "net_gamma": inp.net_gamma or 0,
            "net_delta": inp.net_delta or 0,
            "dist_call_gamma_wall": inp.dist_call_gamma_wall or 0,
            "dist_put_gamma_wall": inp.dist_put_gamma_wall or 0,
            "vix_level": inp.vix_level or 0,
        }
        sequence.append(step)

    return sequence


# ══════════════════════════════════════════════════════════════════════════════
# INFERENCE
# ══════════════════════════════════════════════════════════════════════════════

def predict(inp, ticker: str, direction_hint: str = "flat", db=None, model_dir: Path = None) -> TransformerOutput:
    """
    Run Transformer inference using recent DB snapshots.

    Uses the same encoding pipeline as training (lstm_data.encode_snapshot_5m)
    to ensure feature consistency.

    Args:
        inp:            SignalInput with current market state
        ticker:         ticker symbol (used for model path)
        direction_hint:  directional lean from rules engine
        db:             EdDB instance for fetching recent snapshots
        model_dir:      optional override for model directory

    Returns:
        TransformerOutput with probabilities and health metadata.
    """
    model_path = transformer_model_path(ticker, model_dir)
    meta_path = transformer_meta_path(ticker, model_dir)

    if not model_path.exists():
        return _fallback("model artifact not found — not yet trained")

    if db is None:
        return _fallback("no DB for snapshot history")

    try:
        import json

        meta: dict = {}
        if meta_path.exists():
            with open(meta_path) as f:
                meta = json.load(f)
            version = meta.get("version", "transformer_v1")
        else:
            version = "transformer_v1"

        # Delegate to ml_predict (canonical MVP merge + encode_snapshot_5m).
        from features.inference_snapshot import build_inference_snapshot_v1_from_db_row
        from ml_predict import _predict_transformer, _snap_dict

        _asof = getattr(inp, "refresh_ts_utc", None)
        if _asof is None:
            _asof = time.time()
        _asof = float(_asof)
        recent = db.get_recent_snapshots(
            ticker,
            inp.timeframe,
            n=SEQUENCE_LENGTH + 5,
            filled_only=False,
            as_of_ts_utc=_asof,
        )
        recent = list(reversed(recent))
        if len(recent) < SEQUENCE_LENGTH:
            return _fallback(f"need {SEQUENCE_LENGTH} snapshots, have {len(recent)}")
        window = recent[-SEQUENCE_LENGTH:]
        snap = _snap_dict(window[-1])
        inf_v1 = build_inference_snapshot_v1_from_db_row(
            ticker=ticker,
            expiry=getattr(inp, "expiry", None),
            as_of_ts=_asof,
            db_row=dict(snap) if snap else {},
        )
        prob_dict = _predict_transformer(
            ticker,
            db,
            snapshot=snap,
            timeframe=inp.timeframe,
            inference_snapshot_v1=inf_v1,
        )
        if not prob_dict:
            return _fallback("inference returned no probabilities")
        up   = float(prob_dict["up"])
        down = float(prob_dict["down"])
        flat = float(prob_dict["flat"])
        dominant = max(prob_dict, key=prob_dict.get)
        edge = prob_dict[dominant] - 0.333

        if edge >= 0.15:
            conf_label = "high"
        elif edge >= 0.08:
            conf_label = "medium"
        else:
            conf_label = "low"

        if direction_hint == "long":
            cont = up; rev = down
        elif direction_hint == "short":
            cont = down; rev = up
        else:
            cont = flat; rev = max(up, down)

        breakout = max(up, down) * (1.0 - flat)
        breakout_fail = flat * max(up, down)

        return TransformerOutput(
            available=True,
            prob_up=round(up, 3),
            prob_down=round(down, 3),
            prob_flat=round(flat, 3),
            dominant_class=dominant,
            confidence_score=round(edge, 3),
            confidence_label=conf_label,
            continuation_support=round(cont, 3),
            reversal_support=round(rev, 3),
            breakout_support=round(breakout, 3),
            breakout_failure_support=round(breakout_fail, 3),
            model_version=version,
            model_loaded=True,
            inference_ok=True,
            fallback_used=False,
            horizon=_horizon_label_from_meta(meta),
            sequence_length_used=SEQUENCE_LENGTH,
        )

    except ImportError as e:
        return _fallback(f"missing dependency: {e}")
    except TransformerSequenceInputError:
        raise
    except Exception as e:
        log.warning("transformer_model: inference failed: %s", e)
        return _fallback(f"inference error: {e}")


def _fallback(reason: str) -> TransformerOutput:
    """Return safe fallback when model can't run."""
    log.debug("transformer_model fallback: %s", reason)
    return TransformerOutput(
        available=False,
        fallback_used=True,
        model_version=f"fallback ({reason})",
    )


# ══════════════════════════════════════════════════════════════════════════════
# SELF-TEST
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("transformer_model.py — self-test")
    result = _fallback("self-test")
    print(f"  available={result.available}, fallback={result.fallback_used}")
    p = transformer_model_path("SPY")
    print(f"  transformer_model_path(SPY)={p}, exists={p.exists()}")
    print("  OK")
