"""No forecast is None, and readiness without its inputs is withheld -- never a placeholder.

Fallback register C-01, C-03..C-07, S-01..S-04 (2026-09-24, operator rule: no fallbacks).
With the model stack off, fusion is never authoritative, so EVERY tick used to persist a
"flat / 1/3 each / low" forecast and score readiness on it -- and the calibration edge
studies read each stored placeholder as a LONG call.
"""
from __future__ import annotations


from call_engine import _canonical_stack_vote, _level_proximity_label, _readiness_canonical_fields
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


# ── C-08: every WAIT names its own blocker ────────────────────────────────────

def test_wait_headline_names_its_blocker():
    import call_engine as ce

    def headline(blocker):
        return ce._build_call_headlines(
            "wait", "low", "none", None, None, None, None, 0, 5, "", None, None, None, False,
            wait_blocker=blocker)[0]

    for reason in (ce.WAIT_BLOCKER_REASON_NO_STOP, ce.WAIT_BLOCKER_REASON_EMISSION,
                   ce.WAIT_BLOCKER_REASON_CANONICAL_PROVENANCE,
                   ce.WAIT_BLOCKER_REASON_MULTI_HORIZON_POLICY, ce.WAIT_BLOCKER_REASON_TIME):
        h = headline({"reason": reason, "detail": f"detail-for-{reason}"})
        assert f"detail-for-{reason}" in h and "insufficient confirmation" not in h, h
    assert "some_new_reason" in headline({"reason": "some_new_reason"})


# ── S-14: a directional setup with no measured T1 is WAIT, never a 2R plan ──────

def test_directional_setup_without_a_measured_move_is_wait():
    import dataclasses

    from call_engine import WAIT_BLOCKER_REASON_NO_TARGET, compute_call
    from tests.test_call_owner_emission_veto_v1 import _directional_kwargs
    from tests.test_call_prediction_vote import _inp

    kw = _directional_kwargs()
    assert compute_call(_inp(), kw.pop("rules"), kw.pop("pred"), **kw).signal == "long"
    for avg5 in (None, 0.01):   # missing, and measured but below the minimum R
        kw = _directional_kwargs()
        pred = dataclasses.replace(kw.pop("pred"), avg_5c_pts=avg5)
        call = compute_call(_inp(), kw.pop("rules"), pred, **kw)
        assert call.signal == "wait", avg5
        assert call.wait_blocker["reason"] == WAIT_BLOCKER_REASON_NO_TARGET
        assert (call.entry, call.stop, call.target, call.target2) == (None, None, None, None)


# ── F-09 / F-10: context reads state only what was measured ─────────────────────

def test_timeframe_reads_claim_only_measured_facts():
    from types import SimpleNamespace

    import prediction_engine as pe
    from tests.mvp_test_fixtures import minimal_mvp_features

    def reads(zone, vwap, charm):
        mvp = minimal_mvp_features(zone=zone)
        mvp = {**mvp, "vwap_side": vwap} if "vwap_side" in mvp else mvp
        return pe._timeframe_reads(SimpleNamespace(charm_direction=charm), mvp_features=mvp)

    r = reads("pin_bull", "below", None)
    assert r["60m"] is None                                   # no charm -> no "range" claim
    assert r["15m"] is None or "lower high" not in r["15m"].lower()   # never an unmeasured pattern
    r2 = reads("pin_bull", "below", "selling")
    assert "charm selling" in r2["60m"].lower()
    for text in (r["15m"], r2["15m"]):
        if text:
            for unmeasured in ("lower high", "higher low", "holding", "above gamma walls", "confirmed"):
                assert unmeasured not in text.lower(), text
