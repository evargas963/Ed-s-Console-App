"""order_flow_engine chunk-2: the composite order_flow_score is RETIRED (TRUTH_V1 / RC-450).

This file formerly pinned FIND-OF1/OF2 — preserving 0.0 through the book/tape composite score
selection. That composite (order_flow_score / order_flow_direction / order_flow_regime /
order_flow_readiness) and its double-counting verdict are retired: no fitted weights, no OOS
validation, withheld from Decide. The canonical primitives (book_imbalance_1/3/5, tape_pressure_*,
cum_delta_proxy, options_flow_score, book_microstructure) remain individually. These tests lock
that the composite is not produced and is not reintroduced.
"""
from __future__ import annotations

from order_flow_engine import OrderFlowEngine


def _five_level_book() -> dict:
    bids = [{"BID_PRICE": 100.0 - i * 0.01, "TOTAL_VOLUME": v}
            for i, v in enumerate([125.0, 125.0, 125.0, 13.0, 13.0])]
    asks = [{"ASK_PRICE": 100.05 + i * 0.01, "TOTAL_VOLUME": v}
            for i, v in enumerate([42.0, 42.0, 42.0, 137.5, 137.5])]
    return {"content": [{"BIDS": bids, "ASKS": asks}]}


def test_composite_score_family_is_retired_and_none():
    out = OrderFlowEngine().compute(_five_level_book())
    for k in ("order_flow_score", "order_flow_direction", "order_flow_regime",
              "order_flow_readiness", "order_flow_verdict"):
        assert out.get(k) is None, f"{k} must be retired (None), got {out.get(k)!r}"


def test_canonical_primitives_survive_the_retirement():
    out = OrderFlowEngine().compute(_five_level_book())
    # the strict-L2 depth imbalance is a canonical primitive and must still be produced
    assert out.get("book_imbalance_5") is not None
    assert "book_microstructure" in out


def test_engine_no_longer_calls_the_retired_composite():
    import inspect

    src = inspect.getsource(OrderFlowEngine.compute)
    assert "_compute_order_flow_score(" not in src, "compute must not call the retired composite"
    assert "compute_order_flow_verdict(" not in src, "compute must not call the retired verdict"
