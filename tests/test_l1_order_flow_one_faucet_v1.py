"""RC-404 (Cursor F10): ONE FAUCET = ONE COMPUTATION for order flow.

The L1 light plane (/api/analytics/light) must CARRY the single canonical L2 OrderFlowEngine
computation (read from the acknowledged L2 cache), not run a second, chain-less engine
invocation on thin L1 inputs. These lock:
  1. the published order_flow block equals the L2 cache values (carrier, not recompute);
  2. build_l1_context never invokes a second OrderFlowEngine computation — even if the thin
     compute path is rigged to explode, the L1 build succeeds;
  3. absent L2 row -> absent order_flow (fail-closed), never a thin recompute.
"""
from __future__ import annotations

import time

import planes.context_light as cl
from planes.context_light import _ORDER_FLOW_KEYS, L1BuildContext, build_l1_context


def _vwap_side(spot, vwap):
    if spot is None or vwap is None:
        return None
    return "above" if spot >= vwap else "below"


_L2_OF = {
    "order_flow_score": 0.42,
    "order_flow_direction": "bullish",
    "order_flow_regime": "bullish",
    "order_flow_readiness": "green",
    "order_flow_verdict": "BUYING PRESSURE",
    "order_flow_verdict_color": "green",
    "order_flow_arrow": "▲",
    "order_flow_agreement": "strong | confirming",
    "book_imbalance_5": 0.11,
    "cum_delta_proxy": 250.0,
    "tape_pressure_30s": 0.33,
}


def _ctx(l2_cache_entry):
    return L1BuildContext(
        ticker="SPY",
        request_expiry=None,
        l0_row={"spot": 500.0, "bid": 499.9, "ask": 500.1},
        l2_cache_entry=l2_cache_entry,
        now_ts=time.time(),
        l2_analytics_refresh_in_progress=False,
        l1_generation=1,
    )


def test_l1_order_flow_is_carried_from_the_l2_cache_not_recomputed():
    ent = {"ms_dict": dict(_L2_OF), "analytics_version": 3, "generated_at": time.time()}
    out = build_l1_context(_ctx(ent), derive_vwap_side_fn=_vwap_side)
    of = out["order_flow"]
    # Every published OF key present in the L2 cache is carried verbatim.
    for k in _ORDER_FLOW_KEYS:
        if k in _L2_OF:
            assert of.get(k) == _L2_OF[k], f"{k}: L1 published {of.get(k)!r} != L2 {_L2_OF[k]!r}"
    # The freshly-added canonical field travels end to end.
    assert of["tape_pressure_30s"] == 0.33


def test_build_l1_context_does_not_run_a_second_orderflow_computation(monkeypatch):
    # Rig the thin-input compute to explode. If build_l1_context still touched it, this raises.
    def _boom(*a, **k):
        raise AssertionError("compute_order_flow_compact must NOT be called by build_l1_context (RC-404)")

    monkeypatch.setattr(cl, "compute_order_flow_compact", _boom)
    ent = {"ms_dict": dict(_L2_OF), "analytics_version": 3, "generated_at": time.time()}
    out = build_l1_context(_ctx(ent), derive_vwap_side_fn=_vwap_side)
    assert out["order_flow"]["order_flow_score"] == 0.42


def test_absent_l2_row_yields_absent_order_flow_not_a_thin_recompute(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("no thin recompute on L2 miss (RC-404)")

    monkeypatch.setattr(cl, "compute_order_flow_compact", _boom)
    out = build_l1_context(_ctx(None), derive_vwap_side_fn=_vwap_side)
    assert out["order_flow"] == {}
