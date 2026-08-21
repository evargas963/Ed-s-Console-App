"""order_flow_engine chunk-3: FIND-OF3/OF4/OF5 — renormalize composite + rvol-aware readiness."""

from __future__ import annotations

from order_flow_engine import (
    OrderFlowEngine,
    _compute_order_flow_score,
    _direction,
    _normalize,
    _readiness,
    _weighted_mean_present,
)


def test_all_four_legs_use_full_weight_formula():
    # TRUTH_V1: absorption AND rvol legs were removed (both non-directional magnitudes). The
    # composite is now four SIGNED directional legs; present weights renormalize to 1.0.
    book, tape, delta, opt = 0.4, -0.2, 0.1, -0.15
    score = _compute_order_flow_score(book, tape, delta, opt)
    raw = (
        0.25 * _normalize(book)
        + 0.20 * _normalize(tape)
        + 0.20 * _normalize(delta)
        + 0.15 * _normalize(opt)
    )
    expected = raw / (0.25 + 0.20 + 0.20 + 0.15)  # renormalize present weights to 1.0
    assert score is not None
    assert abs(score - expected) < 1e-9


def test_two_legs_renormalize_book_and_tape():
    book, tape = 0.5, 0.3
    score = _compute_order_flow_score(book, tape, None, None)
    expected = (
        _normalize(book) * (0.25 / 0.45) + _normalize(tape) * (0.20 / 0.45)
    )
    assert score is not None
    assert abs(score - expected) < 1e-9


def test_non_directional_magnitudes_are_not_composite_legs():
    # TRUTH_V1 lock: no non-directional magnitude may influence the composite. The signature is
    # exactly the four SIGNED directional legs — no absorption, no rvol argument. This fails if a
    # future edit re-introduces a magnitude-as-direction leg.
    import inspect

    params = list(inspect.signature(_compute_order_flow_score).parameters)
    assert params == ["book_imbalance", "tape_pressure", "cum_delta", "options_flow"]
    assert "absorption" not in params
    assert "rvol" not in params


def test_one_leg_present_returns_none():
    assert _compute_order_flow_score(0.5, None, None, None) is None


def test_zero_legs_present_returns_none():
    assert _compute_order_flow_score(None, None, None, None) is None


def test_single_options_leg_below_min_present_gate():
    assert _compute_order_flow_score(None, None, None, 0.5) is None


def test_readiness_strong_rvol_unknown_is_yellow_not_green():
    assert _readiness(0.30, None) == "yellow"


def test_readiness_strong_rvol_ok_is_green():
    assert _readiness(0.30, 1.5) == "green"


def test_readiness_weak_rvol_unknown_is_red():
    assert _readiness(0.05, None) == "red"


def test_direction_none_when_score_unavailable():
    assert _direction(None) is None


def test_compute_options_only_no_streaming_score_is_none():
    data = {
        "callExpDateMap": {
            "2026-06-20:0": {
                "150.0": {"totalVolume": 500, "delta": 0.5},
            },
        },
        "putExpDateMap": {
            "2026-06-20:0": {
                "150.0": {"totalVolume": 200, "delta": -0.5},
            },
        },
        "fundamental": {},
        "quote": {},
    }
    out = OrderFlowEngine().compute(data)
    assert out["options_flow_score"] is not None
    assert out["rvol"] is None
    assert out["order_flow_score"] is None
    assert out["order_flow_direction"] is None
    assert out["order_flow_regime"] is None
    assert out["order_flow_readiness"] == "red"


def test_weighted_mean_present_helper_respects_min_present():
    terms = [(0.05, 0.5, -0.5, 0.5)]
    assert _weighted_mean_present(terms, min_present=2) is None
    assert _weighted_mean_present(terms, min_present=1) is not None
