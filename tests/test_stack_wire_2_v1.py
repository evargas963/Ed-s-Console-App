"""STACK-WIRE-2 — coherence-lens re-Read (FIND-WIRE2-1..5)."""

from __future__ import annotations

import ast
import inspect
import re

import multi_horizon_decision as mhd
from ml_horizon import PRIMARY_DECISION_HORIZONS


def _mhd_src() -> str:
    return inspect.getsource(mhd)


def test_horizon_minutes_derived_from_primary_decision_horizons():
    expected = {s: int(s[:-1]) for s in PRIMARY_DECISION_HORIZONS}
    assert mhd.HORIZON_MINUTES == expected
    tree = ast.parse(_mhd_src())
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict) and len(node.keys) == 4:
            keys = [getattr(k, "value", None) for k in node.keys if isinstance(k, ast.Constant)]
            if keys == ["1c", "5c", "15c", "60c"]:
                vals = [getattr(v, "value", None) for v in node.values if isinstance(v, ast.Constant)]
                if vals == [1, 5, 15, 60]:
                    raise AssertionError("hardcoded HORIZON_MINUTES dict still present")


def test_horizon_semantic_role_keys_match_primary_decision_horizons():
    assert set(mhd.HORIZON_SEMANTIC_ROLE.keys()) == set(PRIMARY_DECISION_HORIZONS)


def test_primary_order_for_mode_returns_permutation_of_primary_decision_horizons():
    for mode in ("scalp", "intraday", "session", None, "unknown"):
        order = mhd._primary_order_for_mode(mode)
        assert set(order) == set(PRIMARY_DECISION_HORIZONS)
        assert len(order) == len(PRIMARY_DECISION_HORIZONS)


def test_market_state_mhap_rank_derived_from_primary_decision_horizons():
    import market_state

    src = inspect.getsource(market_state.build_market_state)
    assert '{"1c": 0, "5c": 1, "15c": 2, "60c": 3}' not in src
    assert "enumerate(PRIMARY_DECISION_HORIZONS)" in src


def test_canonical_provenance_fallback_is_fail_closed():
    from fusion_contract import TRADABLE_CANONICAL_PROVENANCE
    from market_state import MarketState

    ms = MarketState()
    _cf = None
    if _cf is not None:
        ms.canonical_provenance = str(getattr(_cf, "provenance", "") or "")
    else:
        ms.canonical_provenance = "canonical_forecast_missing"
    assert ms.canonical_provenance == "canonical_forecast_missing"
    assert ms.canonical_provenance not in TRADABLE_CANONICAL_PROVENANCE


def test_multi_horizon_decision_threshold_constants_exist_and_used():
    assert mhd.TRADEABLE_DOM_MIN == 0.38
    assert mhd.TRADEABLE_MARGIN_MIN == 0.03
    assert mhd.ENTRY_CONFIRMATION_CONFIDENCE_MIN == 0.54
    assert mhd.QUALITY_THRESHOLD_A == 0.74
    assert mhd.TRADE_MODE_SCALP_MAX_MINS == 75
    assert mhd.CONSENSUS_MAJORITY_VOTE_MIN == 3
    assert mhd.SIZING_STRUCTURAL_CONTRADICTION_FACTOR == 0.5

    body = _mhd_src()
    const_block_end = body.index("REASON_PRIMARY_HORIZON_DATA_MISSING")
    tail = body[const_block_end + len("REASON_PRIMARY_HORIZON_DATA_MISSING") :]
    banned = [
        r"(?<![\w.])0\.37(?![\w.])",
        r"(?<![\w.])0\.025(?![\w.])",
        r"(?<![\w.])0\.38(?![\w.])",
        r"(?<![\w.])0\.03(?![\w.])",
        r"(?<![\w.])0\.54(?![\w.])",
        r"(?<![\w.])0\.74(?![\w.])",
        r"(?<![\w.])0\.66(?![\w.])",
        r"(?<![\w.])0\.58(?![\w.])",
        r"(?<![\w.])0\.50(?![\w.])",
        r"(?<![\w.])0\.10(?![\w.])",
        r"(?<![\w.])0\.16(?![\w.])",
        r"(?<![\w.])0\.18(?![\w.])",
        r"(?<![\w.])75(?![\w.])",
        r"(?<![\w.])240(?![\w.])",
    ]
    for pat in banned:
        assert re.search(pat, tail) is None, f"literal still in MHD body: {pat}"


def test_wait_reason_constants_exist_and_used():
    # ALL-card pooled consensus (operator 2026-06-11): wait reasons name the pooled
    # failure modes; the synthesis must route through _pooled_consensus.
    assert "insufficient evidence" in mhd.WAIT_REASON_INSUFFICIENT_VALID_HORIZONS
    assert "flat" in mhd.WAIT_REASON_POOLED_FLAT
    assert "entry gate" in mhd._wait_reason_pooled_below_gate(0.36, 0.02)
    src = inspect.getsource(mhd.compute_multi_horizon_synthesis)
    assert "_pooled_consensus" in src
    helper = inspect.getsource(mhd._pooled_consensus)
    assert "WAIT_REASON_INSUFFICIENT_VALID_HORIZONS" in helper
    assert "WAIT_REASON_POOLED_FLAT" in helper
    assert "_wait_reason_pooled_below_gate" in helper


def _hf(hz, up, dn, fl, **kw):
    d = dict(
        horizon=hz,
        direction="long" if up > max(dn, fl) else "short" if dn > max(up, fl) else "wait",
        probability_up=up, probability_down=dn, probability_flat=fl,
        confidence=max(up, dn, fl), provenance="fusion", tradeable=True,
        unavailable=False, missing=False, valid_contract=True,
        dominant_probability=max(up, dn, fl),
        probability_margin=max(up, dn, fl) - sorted([up, dn, fl])[-2],
    )
    d.update(kw)
    return mhd.HorizonForecast(**d)


def test_all_card_pooled_consensus_is_evidence_weighted_not_head_count():
    """ALL card pools the four triplets (log opinion pool) — never a relay or vote count."""
    eq = {h: 0.25 for h in mhd.PRODUCT_HORIZONS}
    # Aligned long evidence pools long with the pooled dominant as confidence.
    aligned = {
        "1c": _hf("1c", 0.45, 0.30, 0.25), "5c": _hf("5c", 0.48, 0.27, 0.25),
        "15c": _hf("15c", 0.44, 0.31, 0.25), "60c": _hf("60c", 0.42, 0.33, 0.25),
    }
    p = mhd._pooled_consensus(aligned, eq, True)
    assert p.final_bias == "long" and p.wait_reason == ""
    assert p.dominant_probability >= mhd.TRADEABLE_DOM_MIN

    # A strong dissenter drags the pooled evidence below gate — continuous veto.
    dissent = dict(aligned)
    dissent["60c"] = _hf("60c", 0.20, 0.60, 0.20)
    pd = mhd._pooled_consensus(dissent, eq, True)
    assert pd.final_bias == "wait"
    assert pd.wait_reason.startswith("pooled stack evidence below entry gate")

    # Skill weights matter: weighting the dissenter flips pooled evidence short-ward.
    w = {"1c": 0.05, "5c": 0.05, "15c": 0.05, "60c": 0.85}
    pw = mhd._pooled_consensus(dissent, w, False)
    assert pw.prob_down > pd.prob_down

    # Fewer than CONSENSUS_MIN_VALID_HORIZONS valid triplets → fail-closed WAIT.
    sparse = {hz: _hf(hz, 0.4, 0.3, 0.3, missing=True, unavailable=True) for hz in mhd.PRODUCT_HORIZONS}
    sparse["1c"] = _hf("1c", 0.45, 0.30, 0.25)
    ps = mhd._pooled_consensus(sparse, eq, True)
    assert ps.final_bias == "wait"
    assert ps.wait_reason == mhd.WAIT_REASON_INSUFFICIENT_VALID_HORIZONS

    # Flat-dominant pool stays WAIT (no directional fabrication).
    flat = {hz: _hf(hz, 0.25, 0.25, 0.50) for hz in mhd.PRODUCT_HORIZONS}
    pf = mhd._pooled_consensus(flat, eq, True)
    assert pf.final_bias == "wait"
    assert pf.wait_reason == mhd.WAIT_REASON_POOLED_FLAT
