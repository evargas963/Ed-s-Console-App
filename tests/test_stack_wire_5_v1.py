"""STACK-WIRE-5 — order_flow_engine → stack vote (FIND-WIRE5-1..3)."""

from __future__ import annotations

import inspect
import re

import order_flow_engine as ofe
import order_flow_live_state as ofls
from time_et import RTH_END_MINS, RTH_OPEN_MINS


def test_order_flow_live_state_rth_uses_rth_open_mins_authority():
    src = inspect.getsource(ofls.is_rth_open)
    assert "9 * 60 + 30" not in src
    assert "16 * 60" not in src
    assert "RTH_OPEN_MINS" in src
    assert "RTH_END_MINS" in src
    assert RTH_OPEN_MINS == 570
    assert RTH_END_MINS == 960


def test_order_flow_engine_composite_constants_exist_and_used():
    assert ofe.OF_COMPOSITE_WEIGHT_BOOK == 0.25
    assert ofe.OF_DIRECTION_BULLISH_THRESHOLD == 0.15
    assert ofe.OF_COMPOSITE_MIN_LEGS == 2

    body = inspect.getsource(ofe)
    # STACK-WIRE-5-CAND-TEST-SLICE-TIGHTEN fix: cover the full _compute_order_flow_score
    # body (not just the ~4 closing lines between min_present= and def _direction).
    tail = body[
        body.index("def _compute_order_flow_score") : body.index("def _direction")
    ]
    banned = [
        r"(?<![\w.])0\.25(?![\w.])",
        r"(?<![\w.])0\.20(?![\w.])",
        r"(?<![\w.])0\.15(?![\w.])",
        r"(?<![\w.])0\.05(?![\w.])",
    ]
    for pat in banned:
        assert re.search(pat, tail) is None, f"literal still in _compute_order_flow_score: {pat}"


def test_call_engine_consumes_order_flow_direction_not_second_score():
    import call_engine

    src = inspect.getsource(call_engine.compute_call)
    assert "order_flow_direction" in src
    assert "_compute_order_flow_score" not in src
    assert "OrderFlowEngine" not in src


def test_server_of_freshness_independent_from_decision_generation():
    import server

    src = inspect.getsource(server._l1_attach_freshness_semantics)
    assert "order_flow_as_of_ts" in src
    assert "order_flow_stale" in src
    assert "decision_generation_id" not in src


def test_order_flow_engine_has_no_tradability_gate():
    src = inspect.getsource(ofe.OrderFlowEngine.compute)
    assert "canonical_provenance_is_tradable" not in src
    assert "fusion_is_authoritative" not in src
    assert "is_canonical_tradable" not in src
