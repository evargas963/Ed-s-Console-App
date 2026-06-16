"""Adversarial — stale Tier C cache revalidation (R-010)."""
from __future__ import annotations


def test_stale_cache_revalidation_quarantines_bad_spot():
    from trade_impacting_gate import revalidate_cached_decision

    md = {
        "ticker": "SPY",
        "spot": 0.01,
        "call_signal": "long",
        "call_conviction": "high",
        "validation_summary": "stale_ok",
        "analytics_stale": False,
    }
    out = revalidate_cached_decision(
        md,
        route="server._tier_c_analytics_json_response",
        stale=True,
    )
    assert out.get("tier_c_cache_revalidated") is True
    assert out.get("tier_c_cache_gate_ok") is False
    assert out.get("call_signal") == "wait"
    assert (out.get("market_data_quarantine") or {}).get("active") is True
    assert out.get("analytics_stale") is True


def test_fresh_valid_cache_passes_gate():
    from trade_impacting_gate import revalidate_cached_decision

    md = {
        "ticker": "SPY",
        "spot": 500.0,
        "call_signal": "wait",
        "validation_summary": "ok",
    }
    out = revalidate_cached_decision(md, route="server._tier_c_cache", stale=False)
    assert out.get("tier_c_cache_gate_ok") is True
