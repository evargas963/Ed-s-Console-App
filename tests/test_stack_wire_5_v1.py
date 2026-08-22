"""STACK-WIRE-5 — order_flow_engine → stack vote (FIND-WIRE5-1..3)."""

from __future__ import annotations

import inspect

import order_flow_engine as ofe
import order_flow_live_state as ofls
from time_et import RTH_END_MINS, RTH_OPEN_MINS


def test_order_flow_live_state_rth_uses_rth_open_mins_authority():
    src = inspect.getsource(ofls.is_rth_open)
    assert "9 * 60 + 30" not in src
    assert "16 * 60" not in src
    assert "is_tradable_session_ts_utc" in src
    assert "weekday() >= 5" not in src
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
    # Weekday-only clocks admit these. Calendar authority must not.
    assert _at(2026, 7, 3, 10, 0) is False, "Independence Day observed 2026-07-03 is not RTH"
    assert _at(2026, 11, 27, 12, 59) is True, "early-close day is RTH before 13:00"
    assert _at(2026, 11, 27, 13, 0) is False, "2026-11-27 early close is exclusive at 13:00"
    assert _at(2026, 11, 27, 14, 0) is False, "after early close must not stay open until 16:00"


def test_order_flow_composite_constants_and_producers_are_retired():
    for c in (
        "OF_COMPOSITE_WEIGHT_BOOK",
        "OF_COMPOSITE_WEIGHT_TAPE",
        "OF_COMPOSITE_WEIGHT_CUM_DELTA",
        "OF_COMPOSITE_WEIGHT_OPTIONS",
        "OF_COMPOSITE_MIN_LEGS",
        "OF_DIRECTION_BULLISH_THRESHOLD",
        "OF_DIRECTION_BEARISH_THRESHOLD",
        "OF_RVOL_NEUTRAL_CENTER",
    ):
        assert not hasattr(ofe, c), f"retired composite constant {c} must be deleted"
    body = inspect.getsource(ofe)
    assert "def _compute_order_flow_score" not in body
    assert "def _direction" not in body
    assert "def _readiness" not in body


def test_order_flow_direction_is_withheld_from_the_decision_vote():
    import call_engine

    src = inspect.getsource(call_engine.compute_call)
    assert "of_vote = 1 if" not in src
    assert "WITHHELD" in src
    assert "_compute_order_flow_score" not in src
    assert "OrderFlowEngine" not in src
    assert call_engine.order_flow_stack_vote() == 0
    assert "order_flow_stack_vote()" in src


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
    assert ofe.OF_WEIGHTED_MEAN_DEFAULT_MIN_PRESENT == 2

    # RC-461: institutional_flow_proxy is retired (unvalidated mix + arbitrary CVD divisor).
    src_inst = inspect.getsource(ofe._compute_institutional_flow_proxy)
    assert "OF_BOOK_DEPTH_DEEP" in src_inst
    assert ofe._compute_institutional_flow_proxy({}) is None
    assert not hasattr(ofe, "OF_CUM_DELTA_NORM_DIVISOR")

    # ONE CANONICAL BOOK PATH: the depth ladder is walked once, in the canonical producer,
    # over the named ladder constant (not bare integers). OrderFlowEngine.compute no longer
    # walks the book itself — it READS the depth imbalances from that single producer's result.
    assert ofe.OF_MICRO_DEPTH_LADDER == (
        ofe.OF_BOOK_DEPTH_TOP, ofe.OF_BOOK_DEPTH_SHALLOW, ofe.OF_BOOK_DEPTH_DEEP,
    )
    src_struct = inspect.getsource(ofe._microstructure_structural)
    assert "OF_MICRO_DEPTH_LADDER" in src_struct
    assert "OF_BOOK_DEPTH_DEEP" in src_struct

    src_compute = inspect.getsource(ofe.OrderFlowEngine.compute)
    # compute reads the canonical state, and does NOT re-invoke the depth-imbalance helper.
    assert "compute_book_microstructure(" in src_compute
    assert "_compute_book_imbalance(data, 1)" not in src_compute
    assert "_compute_book_imbalance(data, 3)" not in src_compute
    assert "_compute_book_imbalance(data, 5)" not in src_compute

    # _weighted_mean_present default uses the named constant, not bare 2.
    wm_src = inspect.getsource(ofe._weighted_mean_present)
    assert "min_present: int = OF_WEIGHTED_MEAN_DEFAULT_MIN_PRESENT" in wm_src
    assert "min_present: int = 2" not in wm_src
