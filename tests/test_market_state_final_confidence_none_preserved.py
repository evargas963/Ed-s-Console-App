"""I-01: ms.final_confidence stays None when MHA bundle/decision absent (market_state ~1420).

Calls the real build_market_state (via the same patched-signals.compute_signals pattern
used in test_market_state_numeric_contract_v1.py) instead of a hand-copied mirror of its
MHA-confidence block, so a regression in the real code is what fails this test.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from market_state import build_market_state
from multi_horizon_decision import build_multi_horizon_bundle
from tests.test_build_market_state_spot_fail_closed import _base_kwargs
from tests.test_issue18_multi_horizon_decision import _call, _canonical, _inp, _pred
from tests.test_market_state_numeric_contract_v1 import _sig_out_with_pred


@patch("signals.compute_signals")
def test_final_confidence_none_without_multi_horizon_bundle(mock_cs) -> None:
    out = _sig_out_with_pred()
    out.multi_horizon_bundle = None
    mock_cs.return_value = out
    ms = build_market_state(**_base_kwargs())
    assert ms.final_confidence is None


@patch("signals.compute_signals")
def test_final_confidence_none_without_final_decision(mock_cs) -> None:
    out = _sig_out_with_pred()
    out.multi_horizon_bundle = SimpleNamespace(final_decision=None)
    mock_cs.return_value = out
    ms = build_market_state(**_base_kwargs())
    assert ms.final_confidence is None


@patch("signals.compute_signals")
def test_final_confidence_populated_from_producer(mock_cs) -> None:
    bundle = build_multi_horizon_bundle(_inp(mins_to_close=180), _pred(), _canonical(), _call())
    out = _sig_out_with_pred()
    out.multi_horizon_bundle = bundle
    mock_cs.return_value = out
    ms = build_market_state(**_base_kwargs())
    assert ms.final_confidence is not None
    assert 0.0 <= ms.final_confidence <= 1.0
    assert ms.final_confidence == bundle.final_decision.final_confidence


@patch("signals.compute_signals")
def test_final_confidence_none_when_producer_value_none(mock_cs) -> None:
    bundle = build_multi_horizon_bundle(_inp(mins_to_close=180), _pred(), _canonical(), _call())
    bundle.final_decision.final_confidence = None  # type: ignore[misc]
    out = _sig_out_with_pred()
    out.multi_horizon_bundle = bundle
    mock_cs.return_value = out
    ms = build_market_state(**_base_kwargs())
    assert ms.final_confidence is None
