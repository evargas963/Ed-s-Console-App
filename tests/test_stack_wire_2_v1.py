"""STACK-WIRE-2 — coherence-lens re-Read (FIND-WIRE2-1..5)."""

from __future__ import annotations

import inspect











def test_market_state_mhap_rank_derived_from_primary_decision_horizons():
    import market_state

    src = inspect.getsource(market_state.build_market_state)
    assert '{"1c": 0, "5c": 1, "15c": 2, "60c": 3}' not in src
    assert "enumerate(PRIMARY_DECISION_HORIZONS)" in src










