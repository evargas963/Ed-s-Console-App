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


def test_order_flow_live_state_rth_actually_behaves_at_the_boundaries(monkeypatch):
    """RC-298: the test above reads the SOURCE. This one runs the FUNCTION.

    Source assertions prove `is_rth_open` NAMES the authority constants; only calling it
    proves it USES them correctly. A file that only matches text cannot detect a false
    claim — that is how RC-294 locked "calls sell, puts buy", which one call refuted.

    Driven by pinning the clock, because the real one makes the answer depend on when the
    suite happens to run.
    """
    import datetime as _dt

    from time_et import ET

    def _at(y, m, d, hh, mm):
        monkeypatch.setattr(ofls, "now_et",
                            lambda: _dt.datetime(y, m, d, hh, mm, tzinfo=ET), raising=True)
        return ofls.is_rth_open()

    # 2026-08-07 is a Friday; 2026-08-08 a Saturday.
    assert _at(2026, 8, 7, 9, 29) is False, "one minute before the open must not be RTH"
    assert _at(2026, 8, 7, 9, 30) is True, "the open itself is RTH (inclusive lower bound)"
    assert _at(2026, 8, 7, 12, 0) is True
    assert _at(2026, 8, 7, 15, 59) is True
    assert _at(2026, 8, 7, 16, 0) is False, "16:00 is the exclusive upper bound"
    assert _at(2026, 8, 8, 12, 0) is False, "Saturday is never RTH regardless of clock"


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


def test_order_flow_engine_residual_magics_named():
    """STACK-WIRE-5-CAND-OF-RESIDUAL-MAGICS: bare integer depths and RVOL center named."""
    # Constants exist with expected values.
    assert ofe.OF_BOOK_DEPTH_TOP == 1
    assert ofe.OF_BOOK_DEPTH_SHALLOW == 3
    assert ofe.OF_BOOK_DEPTH_DEEP == 5
    assert ofe.OF_RVOL_NEUTRAL_CENTER == 1.0
    assert ofe.OF_WEIGHTED_MEAN_DEFAULT_MIN_PRESENT == 2

    # _compute_institutional_flow_proxy and OrderFlowEngine.compute use the named depths,
    # not bare integers.
    src_inst = inspect.getsource(ofe._compute_institutional_flow_proxy)
    assert "OF_BOOK_DEPTH_DEEP" in src_inst
    assert "_compute_book_imbalance(data, 5)" not in src_inst

    src_compute = inspect.getsource(ofe.OrderFlowEngine.compute)
    assert "OF_BOOK_DEPTH_TOP" in src_compute
    assert "OF_BOOK_DEPTH_SHALLOW" in src_compute
    assert "OF_BOOK_DEPTH_DEEP" in src_compute
    assert "_compute_book_imbalance(data, 1)" not in src_compute
    assert "_compute_book_imbalance(data, 3)" not in src_compute
    assert "_compute_book_imbalance(data, 5)" not in src_compute

    # _compute_order_flow_score uses OF_RVOL_NEUTRAL_CENTER (not bare 1.0) for the rvol term.
    body = inspect.getsource(ofe)
    score_body = body[
        body.index("def _compute_order_flow_score") : body.index("def _direction")
    ]
    assert "OF_RVOL_NEUTRAL_CENTER" in score_body
    assert "(rvol - 1.0)" not in score_body

    # _weighted_mean_present default uses the named constant, not bare 2.
    wm_src = inspect.getsource(ofe._weighted_mean_present)
    assert "min_present: int = OF_WEIGHTED_MEAN_DEFAULT_MIN_PRESENT" in wm_src
    assert "min_present: int = 2" not in wm_src
