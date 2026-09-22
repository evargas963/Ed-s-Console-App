"""RC-REHAB-1 (Phase 4): _fetch_state decomposition, third extracted phase.

_order_flow_signals_for_state (server.py) is the Order Flow Signals phase (option volume +
bid/ask size), moved out of _fetch_state's body into a standalone function returning an
_OrderFlowSignalsForState NamedTuple. Four independent computations, each already delegated
to its own module, each with its own try/except in the ORIGINAL inline code -- these tests
prove that per-call fail-closed isolation survived the extraction exactly: one signal's
failure must never affect a sibling's result, and total failure must never raise into the
caller.
"""
from __future__ import annotations

from unittest import mock

import server as srv
import server_state_signals as ss


def _patch_all(vol_oi_ratio, flow_imb, smart_money, iv_model_spread):
    return (
        mock.patch.object(ss, "compute_volume_oi_ratio", vol_oi_ratio),
        mock.patch.object(ss, "flow_imbalance_normalized_with_fallback", flow_imb),
        mock.patch.object(ss, "compute_smart_money_signal", smart_money),
        mock.patch.object(ss, "compute_iv_model_spread", iv_model_spread),
    )


def test_happy_path_all_four_signals_populate():
    with mock.patch.object(ss, "compute_volume_oi_ratio", lambda e, s: {"ratio": 1.5, "label": "elevated"}), \
         mock.patch.object(ss, "flow_imbalance_normalized_with_fallback", lambda e, s: (0.42, "volume")), \
         mock.patch.object(ss, "compute_smart_money_signal", lambda e, s: {"score": 7, "direction": "bullish", "label": "strong"}), \
         mock.patch.object(ss, "compute_iv_model_spread", lambda c, s: {"spread": 0.03, "label": "tight"}):
        result = srv._order_flow_signals_for_state({"x": 1}, 450.0, [{"strike": 450}])

    assert result.vol_oi_ratio == {"ratio": 1.5, "label": "elevated"}
    assert result.flow_imb_norm == 0.42
    assert result.flow_imb_source == "volume"
    assert result.smart_money == {"score": 7, "direction": "bullish", "label": "strong"}
    assert result.iv_model_spread == {"spread": 0.03, "label": "tight"}


def test_one_signal_failing_does_not_affect_its_siblings():
    """The original inline code wrapped each of the four calls in its OWN try/except --
    a vol_oi_ratio or smart_money failure must not touch flow_imb_norm/iv_model_spread,
    and vice versa."""
    def boom(*_a, **_kw):
        raise RuntimeError("synthetic failure")

    with mock.patch.object(ss, "compute_volume_oi_ratio", boom), \
         mock.patch.object(ss, "flow_imbalance_normalized_with_fallback", lambda e, s: (0.42, "volume")), \
         mock.patch.object(ss, "compute_smart_money_signal", boom), \
         mock.patch.object(ss, "compute_iv_model_spread", lambda c, s: {"spread": 0.03, "label": "tight"}):
        result = srv._order_flow_signals_for_state({"x": 1}, 450.0, [{"strike": 450}])

    assert result.vol_oi_ratio == {}, "a failed sub-computation must fail closed to an empty dict"
    assert result.smart_money == {}, "a failed sub-computation must fail closed to an empty dict"
    assert result.flow_imb_norm == 0.42, "a sibling's failure must not affect this independent computation"
    assert result.flow_imb_source == "volume"
    assert result.iv_model_spread == {"spread": 0.03, "label": "tight"}, (
        "a sibling's failure must not affect this independent computation"
    )


def test_all_four_signals_failing_never_raises():
    def boom(*_a, **_kw):
        raise RuntimeError("synthetic failure")

    with mock.patch.object(ss, "compute_volume_oi_ratio", boom), \
         mock.patch.object(ss, "flow_imbalance_normalized_with_fallback", boom), \
         mock.patch.object(ss, "compute_smart_money_signal", boom), \
         mock.patch.object(ss, "compute_iv_model_spread", boom):
        # Must not raise -- the original inline block never let a signal failure escape
        # into the rest of _fetch_state's pipeline.
        result = srv._order_flow_signals_for_state({"x": 1}, 450.0, [{"strike": 450}])

    assert result.vol_oi_ratio == {}
    assert result.smart_money == {}
    assert result.iv_model_spread == {}
    assert result.flow_imb_norm is None
    assert result.flow_imb_source == "none"


def test_fetch_state_calls_the_extracted_function_exactly_once():
    """AST lock: _fetch_state must call _order_flow_signals_for_state exactly once, and
    must not directly call any of the four underlying signal functions itself -- proving
    no second inline copy of this phase survived the extraction."""
    import ast
    from pathlib import Path

    src = Path(srv.__file__).read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(src)
    fetch_state_fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "_fetch_state"
    )
    calls_in_fetch_state = [
        n.func.id for n in ast.walk(fetch_state_fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    ]
    assert calls_in_fetch_state.count("_order_flow_signals_for_state") == 1
    for leaked in (
        "compute_volume_oi_ratio",
        "flow_imbalance_normalized_with_fallback",
        "compute_smart_money_signal",
        "compute_iv_model_spread",
    ):
        assert leaked not in calls_in_fetch_state, (
            f"_fetch_state still calls {leaked} directly -- the order-flow-signals phase "
            f"was not fully extracted, a second inline computation site survived"
        )
