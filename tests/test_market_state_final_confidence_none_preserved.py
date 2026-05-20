"""I-01: ms.final_confidence stays None when MHA bundle/decision absent (market_state ~1420)."""
from __future__ import annotations

from types import SimpleNamespace

from market_state import MarketState
from numeric_contract import float_finite_or_none
from multi_horizon_decision import build_multi_horizon_bundle
from tests.test_issue18_multi_horizon_decision import _call, _canonical, _inp, _pred


def _apply_mha_confidence_from_sig_out(ms: MarketState, sig_out) -> None:
    """Mirror build_market_state MHA block (keep in sync with market_state.py ~1413-1420)."""
    _mhb = getattr(sig_out, "multi_horizon_bundle", None)
    if _mhb is not None and getattr(_mhb, "final_decision", None) is not None:
        _mhd = _mhb.final_decision
        _fc = getattr(_mhd, "final_confidence", None)
        ms.final_confidence = float_finite_or_none(_fc)


def test_final_confidence_none_without_multi_horizon_bundle() -> None:
    ms = MarketState(ticker="SPY")
    _apply_mha_confidence_from_sig_out(ms, SimpleNamespace(multi_horizon_bundle=None))
    assert ms.final_confidence is None


def test_final_confidence_none_without_final_decision() -> None:
    ms = MarketState(ticker="SPY")
    _apply_mha_confidence_from_sig_out(
        ms,
        SimpleNamespace(multi_horizon_bundle=SimpleNamespace(final_decision=None)),
    )
    assert ms.final_confidence is None


def test_final_confidence_populated_from_producer() -> None:
    bundle = build_multi_horizon_bundle(_inp(mins_to_close=180), _pred(), _canonical(), _call())
    ms = MarketState(ticker="SPY")
    _apply_mha_confidence_from_sig_out(ms, SimpleNamespace(multi_horizon_bundle=bundle))
    assert ms.final_confidence is not None
    assert 0.0 <= ms.final_confidence <= 1.0
    assert ms.final_confidence == bundle.final_decision.final_confidence


def test_final_confidence_none_when_producer_value_none() -> None:
    bundle = build_multi_horizon_bundle(_inp(mins_to_close=180), _pred(), _canonical(), _call())
    bundle.final_decision.final_confidence = None  # type: ignore[misc]
    ms = MarketState(ticker="SPY")
    _apply_mha_confidence_from_sig_out(ms, SimpleNamespace(multi_horizon_bundle=bundle))
    assert ms.final_confidence is None
