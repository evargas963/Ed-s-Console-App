"""order_flow_engine chunk-4: the order_flow verdict + composite family is RETIRED (RC-473/RC-474).

compute_order_flow_verdict (a structural double-count that emitted the false BUYING/SELLING PRESSURE
claim) and the composite score/direction/readiness producers were deleted. This file locks the
retirement end-to-end: the producers are gone and the engine emits None for the whole family.
"""
from __future__ import annotations

import math_exposure as me
import order_flow_engine as ofe
from order_flow_engine import OrderFlowEngine


def test_compute_order_flow_verdict_producer_is_deleted():
    assert not hasattr(me, "compute_order_flow_verdict"), "the double-counting verdict must stay deleted"


def test_order_flow_score_verdict_family_is_retired():
    # The producer must emit None for the whole retired family; canonical primitives remain.
    out = OrderFlowEngine().compute({"quote": {}})
    for k in ("order_flow_score", "order_flow_direction", "order_flow_regime",
              "order_flow_readiness", "order_flow_verdict", "order_flow_verdict_color"):
        assert out.get(k) is None, f"{k} must be retired (None), got {out.get(k)!r}"
    assert "book_imbalance_5" in out
    assert "options_flow_score" in out


def test_engine_does_not_reference_the_retired_producers():
    import inspect

    src = inspect.getsource(ofe.OrderFlowEngine.compute)
    assert "_compute_order_flow_score(" not in src
    assert "compute_order_flow_verdict(" not in src
    assert "_readiness(" not in src
