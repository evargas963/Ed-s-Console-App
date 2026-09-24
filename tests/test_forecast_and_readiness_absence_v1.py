"""No forecast is None, and readiness without its inputs is withheld -- never a placeholder.

Fallback register C-01, C-03..C-07, S-01..S-04 (2026-09-24, operator rule: no fallbacks).
With the model stack off, fusion is never authoritative, so EVERY tick used to persist a
"flat / 1/3 each / low" forecast and score readiness on it -- and the calibration edge
studies read each stored placeholder as a LONG call.
"""
from __future__ import annotations

import json

from call_engine import _canonical_stack_vote, _level_proximity_label, _readiness_canonical_fields
from calibration.analyze_phase3 import _canonical_prob_triplet
from calibration.edge_validation import _effective_directional_signal
from setup_readiness import compute_call_readiness, compute_put_readiness
from signal_types import CanonicalForecast
from signals import canonical_forecast_from_fusion

_FULL = {
    "regime": "bull", "trend": "up", "structure_confirmation": "reclaim",
    "structure_higher_tf": "uptrend intact", "prediction_direction": "up",
    "prediction_dominant_prob": 0.61, "confluence_read": "strong",
    "validation_passed": True, "level_proximity": "near",
}


def test_non_tradable_canonical_is_absent():
    c = canonical_forecast_from_fusion(None)
    assert (c.direction, c.confidence) == (None, None)
    assert (c.probability_up, c.probability_down, c.probability_flat) == (None, None, None)
    assert c.dominant_probability() is None
    assert _readiness_canonical_fields(c) == (None, None)
    assert _canonical_stack_vote(c) == 0


def test_tradable_canonical_with_unreadable_confidence_does_not_vote_on_it():
    c = CanonicalForecast(direction="up", probability_up=0.40, probability_down=0.30,
                          probability_flat=0.30, confidence=None, provenance="bayesian_fusion")
    # 0.40 is below the stack-vote probability floor; an absent confidence is not "not low"
    assert _canonical_stack_vote(c) == 0


def test_readiness_withheld_for_each_missing_input():
    for key in ("regime", "trend", "structure_confirmation", "structure_higher_tf",
                "prediction_direction", "prediction_dominant_prob", "confluence_read",
                "level_proximity"):
        inp = dict(_FULL)
        inp[key] = None
        for fn in (compute_call_readiness, compute_put_readiness):
            out = fn(inp)
            assert out["readiness_score"] is None and out["call_state"] is None, (fn, key)
            assert key in out["missing_conditions"][0], (fn, key)
    assert compute_call_readiness(dict(_FULL))["readiness_score"] is not None


def test_trigger_zone_needs_no_level_distance():
    inp = dict(_FULL, level_proximity=None, breakout_ready=True)
    assert compute_call_readiness(inp)["readiness_score"] is not None


def test_level_proximity_absent_is_none_not_far():
    assert _level_proximity_label(None) is None
    assert _level_proximity_label(0.0) == "near"
    assert _level_proximity_label(1e9) == "far"


def test_calibration_reader_ignores_placeholder_triplets():
    u = 1.0 / 3.0
    placeholder = json.dumps({"probability_up": u, "probability_down": u, "probability_flat": u,
                              "provenance": "fusion_unavailable"})
    no_prov = json.dumps({"probability_up": u, "probability_down": u, "probability_flat": u})
    real = json.dumps({"probability_up": 0.2, "probability_down": 0.6, "probability_flat": 0.2,
                       "provenance": "bayesian_fusion"})
    assert _canonical_prob_triplet(placeholder) is None
    assert _canonical_prob_triplet(no_prov) is None
    # the placeholder used to win the p_up >= p_dn >= p_fl tie-break -> "long"
    assert _effective_directional_signal({"final_signal": "wait", "canonical_json": placeholder}) == "wait"
    assert _effective_directional_signal({"final_signal": "wait", "canonical_json": real}) == "short"


# ── L-01 / F-11: the stamped model version is what RAN, or None ────────────────

def test_executed_model_version_reads_what_ran():
    from ml_predict import executed_model_version
    assert executed_model_version(None) is None          # stack off: model_outputs None
    off = {"available": False}
    assert executed_model_version({"xgb": off, "lstm": off, "transformer": off}) is None
    v = executed_model_version({"xgb": {"available": True}, "lstm": off,
                                "transformer": {"available": True}})
    assert v is not None and v.startswith("stack(xgb_tr)_")


def test_no_serving_model_when_stack_off(monkeypatch):
    import signals
    import server
    monkeypatch.setattr(signals, "LIVE_MODEL_STACK_ENABLED", False)
    assert server._current_pred_model_version("SPY") is None
