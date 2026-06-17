"""order_flow_engine chunk-4: FIND-OF6/OF7 — withhold labels at exact-zero composite."""

from __future__ import annotations

from unittest.mock import patch

from math_exposure import (
    _of_sign,
    compute_order_flow_verdict,
    order_flow_score_label,
)
from order_flow_engine import OrderFlowEngine, _direction


def test_direction_exact_zero_is_none_weak_band_still_neutral():
    assert _direction(0.0) is None
    assert _direction(0.05) == "neutral"
    assert _direction(None) is None


def test_order_flow_score_label_exact_zero_is_none():
    assert order_flow_score_label(0.0) is None
    assert order_flow_score_label(0.05) == "neutral"


def test_of_sign_zero_is_none_not_neutral_vote():
    assert _of_sign(0.0) is None
    assert _of_sign(0.01) == 1.0
    assert _of_sign(-0.01) == -1.0


def test_verdict_with_zero_cum_delta_still_emits_when_score_directional():
    out = compute_order_flow_verdict(0.5, None, 0.0, None)
    assert out["verdict"] is not None
    assert out["agreement"] != "unavailable"


def test_compute_order_flow_verdict_score_only_zero_is_unavailable():
    out = compute_order_flow_verdict(0.0, None, None, None)
    assert out["verdict"] is None
    assert out["verdict_color"] is None
    assert out["arrow"] is None
    assert out["agreement"] == "unavailable"


def test_compute_order_flow_verdict_score_only_nonzero_in_band_has_verdict():
    out = compute_order_flow_verdict(0.05, None, None, None)
    assert out["verdict"] is not None
    assert out["verdict"] != ""


def test_compute_e2e_exact_zero_score_withholds_direction_and_verdict():
    with (
        patch("order_flow_engine._compute_book_imbalance", return_value=0.0),
        patch("order_flow_engine._compute_tape_pressure", return_value=0.0),
        patch("order_flow_engine._compute_cum_delta_proxy", return_value=None),
        patch("order_flow_engine._compute_absorption", return_value=(None, None, None)),
        patch("order_flow_engine._compute_options_flow", return_value=(None, None, None, None, None)),
        patch("order_flow_engine._compute_rvol", return_value=(None, "current_volume_unavailable")),
    ):
        out = OrderFlowEngine().compute({"quote": {}})
    assert out["order_flow_score"] is not None
    assert abs(out["order_flow_score"]) < 1e-9
    assert out["order_flow_direction"] is None
    assert out["order_flow_regime"] is None
    assert out["order_flow_score_label"] is None
    assert out["order_flow_verdict"] is None
