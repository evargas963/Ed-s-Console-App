"""order_flow_engine chunk-4: FIND-OF6/OF7 — withhold labels at exact-zero composite."""

from __future__ import annotations

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


def test_order_flow_score_verdict_family_is_retired():
    # TRUTH_V1 / RC-450: the order_flow composite score, direction, regime, readiness and the
    # double-counting verdict are RETIRED (no fitted weights, no OOS validation, and the verdict
    # double-counted book/cum-delta/options to emit a false BUYING/SELLING PRESSURE claim). The
    # producer must emit None for the whole family; the canonical primitives remain.
    out = OrderFlowEngine().compute({"quote": {}})
    for k in ("order_flow_score", "order_flow_direction", "order_flow_regime",
              "order_flow_readiness", "order_flow_verdict", "order_flow_verdict_color",
              "order_flow_score_label"):
        assert out.get(k) is None, f"{k} must be retired (None), got {out.get(k)!r}"
    # canonical primitives are preserved individually
    assert "book_imbalance_5" in out
    assert "options_flow_score" in out
