"""No forecast is None, and readiness without its inputs is withheld -- never a placeholder.

Fallback register C-01, C-03..C-07, S-01..S-04 (2026-09-24, operator rule: no fallbacks).
With the model stack off, fusion is never authoritative, so EVERY tick used to persist a
"flat / 1/3 each / low" forecast and score readiness on it -- and the calibration edge
studies read each stored placeholder as a LONG call.
"""
from __future__ import annotations



_FULL = {
    "regime": "bull", "trend": "up", "structure_confirmation": "reclaim",
    "structure_higher_tf": "uptrend intact", "prediction_direction": "up",
    "prediction_dominant_prob": 0.61, "confluence_read": "strong",
    "validation_passed": True, "level_proximity": "near",
}












# ── L-01 / F-11: the stamped model version is what RAN, or None ────────────────



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
