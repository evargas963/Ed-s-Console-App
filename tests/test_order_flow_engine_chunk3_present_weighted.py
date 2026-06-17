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


def test_all_six_legs_use_full_weight_formula():
    book, tape, delta, abs_, opt, rvol = 0.4, -0.2, 0.1, 0.3, -0.15, 1.5
    score = _compute_order_flow_score(book, tape, delta, abs_, opt, rvol)
    expected = (
        0.25 * _normalize(book)
        + 0.20 * _normalize(tape)
        + 0.20 * _normalize(delta)
        + 0.15 * _normalize(abs_)
        + 0.15 * _normalize(opt)
        + 0.05 * _normalize(rvol - 1.0, -0.5, 0.5)
    )
    assert score is not None
    assert score == expected


def test_two_legs_renormalize_book_and_tape():
    book, tape = 0.5, 0.3
    score = _compute_order_flow_score(book, tape, None, None, None, None)
    expected = (
        _normalize(book) * (0.25 / 0.45) + _normalize(tape) * (0.20 / 0.45)
    )
    assert score is not None
    assert abs(score - expected) < 1e-9


def test_one_leg_present_returns_none():
    assert _compute_order_flow_score(0.5, None, None, None, None, None) is None


def test_zero_legs_present_returns_none():
    assert _compute_order_flow_score(None, None, None, None, None, None) is None


def test_single_rvol_leg_below_min_present_gate():
    assert _compute_order_flow_score(None, None, None, None, None, 1.5) is None


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
