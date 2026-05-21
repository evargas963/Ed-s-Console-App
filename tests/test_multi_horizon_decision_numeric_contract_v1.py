"""FIND-MHD-1..8 paired-fix — numeric_contract + MHMLB-2 audit propagation."""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from multi_horizon_decision import (
    _confidence_from_probs,
    _forecast_horizon_live,
    _norm_triplet,
    _safe_prob_optional,
    build_multi_horizon_bundle,
    compute_multi_horizon_synthesis,
)
from tests.test_issue18_multi_horizon_decision import _call, _canonical, _inp, _pred
from multi_horizon_ml_bundle import build_multi_horizon_ml_fusion_bundle


def _fus(up: float, down: float, flat: float):
    return SimpleNamespace(
        available=True,
        prob_up=up,
        prob_down=down,
        prob_flat=flat,
        dominant_direction="up",
        fusion_confidence="medium",
        fusion_confidence_score=0.5,
        mc_available=False,
        contributing_models=[],
        missing_models=[],
    )


def _pred(**kw):
    base = dict(
        up_prob_1c=0.6,
        down_prob_1c=0.2,
        flat_prob_1c=0.2,
        up_prob_5c=0.6,
        down_prob_5c=0.2,
        flat_prob_5c=0.2,
        up_prob_15c=0.6,
        down_prob_15c=0.2,
        flat_prob_15c=0.2,
        up_prob_60c=0.6,
        down_prob_60c=0.2,
        flat_prob_60c=0.2,
        mh_prob_source_by_horizon={},
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _canonical(up=0.6, down=0.2, flat=0.2):
    return SimpleNamespace(
        probability_up=up,
        probability_down=down,
        probability_flat=flat,
    )


def test_safe_prob_optional_rejects_non_finite_and_out_of_range():
    assert _safe_prob_optional(float("nan")) is None
    assert _safe_prob_optional(float("inf")) is None
    assert _safe_prob_optional(-0.1) is None
    assert _safe_prob_optional(1.1) is None
    assert _safe_prob_optional(0.5) == pytest.approx(0.5)


def test_norm_triplet_rejects_nan_and_inf():
    assert _norm_triplet(float("nan"), 0.2, 0.2) is None
    assert _norm_triplet(0.6, float("inf"), 0.2) is None


def test_forecast_missing_when_native_prob_nan():
    p = _pred(up_prob_1c=float("nan"))
    f = _forecast_horizon_live(p, SimpleNamespace(), "1c", canonical=None, mh_ml_bundle=None)
    assert f.missing is True
    assert f.provenance == "predictive_probs_unavailable"


def test_confidence_from_probs_margin_wait_on_equal_top_two():
    dom, margin, call = _confidence_from_probs(0.5, 0.5, 0.0)
    assert margin == pytest.approx(0.0)
    assert call == "wait"


def test_confidence_from_probs_uses_triplet_authority_when_margin_ok():
    dom, margin, call = _confidence_from_probs(0.1, 0.7, 0.2)
    assert call == "short"
    assert dom == pytest.approx(0.7)


def test_confidence_from_probs_triplet_up_maps_to_long():
    _, _, call = _confidence_from_probs(0.5, 0.3, 0.2)
    assert call == "long"


def test_confidence_from_probs_equal_down_flat_margin_wait():
    _, margin, call = _confidence_from_probs(0.0, 0.5, 0.5)
    assert margin == pytest.approx(0.0)
    assert call == "wait"


def test_canonical_blend_skipped_on_non_finite_canonical(monkeypatch):
    monkeypatch.setenv("ED_MH_FALLBACK_CANONICAL_BLEND", "0.5")
    p = _pred()
    canon = _canonical(up=float("nan"), down=0.2, flat=0.2)
    f = _forecast_horizon_live(p, SimpleNamespace(), "5c", canonical=canon, mh_ml_bundle=None)
    assert f.provenance == "predictive_empirical_fallback_5c_canonical_nonfinite"
    assert f.probability_up == pytest.approx(0.6)


def test_malformed_fallback_blend_env_logs_and_uses_zero(monkeypatch, caplog):
    monkeypatch.setenv("ED_MH_FALLBACK_CANONICAL_BLEND", "not-a-float")
    p = _pred()
    with caplog.at_level("DEBUG", logger="multi_horizon_decision"):
        f = _forecast_horizon_live(
            p,
            SimpleNamespace(),
            "15c",
            canonical=_canonical(),
            mh_ml_bundle=None,
        )
    assert f.provenance == "predictive_empirical_fallback_15c"
    assert "ED_MH_FALLBACK_CANONICAL_BLEND ignored" in caplog.text


def test_per_hz_audit_fusion_dominant_direction_matches_bundle_triplet():
    fusion_by_hz = {
        "1c": _fus(0.6, 0.2, 0.2),
        "5c": _fus(0.1, 0.7, 0.2),
        "15c": _fus(0.6, 0.2, 0.2),
        "60c": _fus(0.6, 0.2, 0.2),
    }
    bundle = build_multi_horizon_ml_fusion_bundle(fusion_by_hz, live_canonical_horizon_slug="1c")
    synth = compute_multi_horizon_synthesis(
        SimpleNamespace(mins_to_close=180.0),
        _pred(),
        _canonical(),
        mh_ml_bundle=bundle,
    )
    audit = synth.ml_live_audit["per_horizon"]["5c"]
    snap = bundle.snapshot("5c")
    assert snap is not None
    assert snap.dominant_direction == "down"
    assert audit["fusion_dominant_direction"] == "down"
    assert audit["fusion_ml_available"] is True


def test_per_hz_audit_unavailable_horizon_flat_matches_snap():
    fusion_by_hz = {
        "1c": None,
        "5c": _fus(0.6, 0.2, 0.2),
        "15c": _fus(0.6, 0.2, 0.2),
        "60c": _fus(0.6, 0.2, 0.2),
    }
    bundle = build_multi_horizon_ml_fusion_bundle(fusion_by_hz, live_canonical_horizon_slug="1c")
    synth = compute_multi_horizon_synthesis(
        SimpleNamespace(mins_to_close=180.0),
        _pred(),
        _canonical(),
        mh_ml_bundle=bundle,
    )
    snap = bundle.snapshot("1c")
    audit = synth.ml_live_audit["per_horizon"]["1c"]
    assert snap is not None
    assert snap.horizon_fusion_available is False
    assert snap.dominant_direction == "flat"
    assert audit["fusion_dominant_direction"] == "flat"
    assert audit["fusion_ml_available"] is False


def test_finalize_display_withholds_nan_target_and_stop():
    call = _call()
    call.target = float("nan")
    call.stop = float("inf")
    b = build_multi_horizon_bundle(_inp(), _pred(), _canonical(), call)
    plan = b.final_decision.final_trade_plan
    assert plan.target_ladder[0] == "T1: —"
    assert plan.stop_display_text == "—"
    assert plan.stop is None


def test_entry_state_machine_nan_spot_fail_closed_no_setup():
    from multi_horizon_decision import _entry_state_machine

    one_c = _forecast_horizon_live(_pred(), SimpleNamespace(), "1c")
    state, px, txt = _entry_state_machine(
        "long",
        True,
        SimpleNamespace(spot=float("nan"), nearest_below_val=440.0, nearest_above_val=442.0),
        one_c,
        None,
        "WATCH",
    )
    assert state == "no_setup"
    assert px is None
    assert "missing or invalid zone/spot" in txt
