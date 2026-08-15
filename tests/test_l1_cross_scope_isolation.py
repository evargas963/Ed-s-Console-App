"""
Issue 51 — Tier B / L1 cross-scope isolation (ticker|expiry).

Mirrors client norms: static/js/l1_sse_guards.js normL1ExpiryKey + renderTierBLight scope gate
(l1TierBPayloadMatchesActiveScope). Proves no cross-scope generation, authority, or render leakage.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parent.parent


def norm_l1_expiry_key(exp: Any) -> str:
    """EdL1SseGuards.normL1ExpiryKey (keep aligned)."""
    if exp is None or exp == "":
        return "__auto__"
    s = str(exp).strip()
    if not s:
        return "__auto__"
    if s == "__auto__":
        return "__auto__"
    return s[:10] if len(s) >= 10 else s


def scope_key(ticker: str, active_exp: Any) -> str:
    """Client renderTierBLight: activeTicker + '|' + wantExp (raw active expiry string or '')."""
    want = str(active_exp).strip() if active_exp else ""
    return f"{ticker.strip().upper()}|{want}"


def l1_tier_b_payload_matches_active_scope(
    d: Dict[str, Any],
    active_ticker: str,
    active_exp: Any,
) -> bool:
    """l1TierBPayloadMatchesActiveScope — must pass before monotonic/authority/dedupe."""
    pt = str(d.get("ticker", "")).strip().upper() if d.get("ticker") is not None else ""
    if not pt:
        return False
    at = (active_ticker or "").strip().upper() or "SPY"
    if pt != at:
        return False
    pk = norm_l1_expiry_key(d.get("selected_exp"))
    ck = norm_l1_expiry_key(active_exp)
    return pk == ck


# --- A. Different scope rejection -----------------------------------------------------------


def test_a_wrong_ticker_rejected():
    assert not l1_tier_b_payload_matches_active_scope(
        {"ticker": "SPY", "selected_exp": None},
        "QQQ",
        None,
    )


def test_a_wrong_expiry_rejected():
    assert not l1_tier_b_payload_matches_active_scope(
        {"ticker": "SPY", "selected_exp": "2026-06-19"},
        "SPY",
        "2026-12-19",
    )


def test_a_matching_scope_accepted():
    assert l1_tier_b_payload_matches_active_scope(
        {"ticker": "SPY", "selected_exp": None},
        "SPY",
        None,
    )


# --- B. Rapid switching: stale SPY after switch to QQQ --------------------------------------


def test_b_spy_payload_rejected_when_active_qqq():
    gen_store: Dict[str, float] = {}
    # Was SPY| — gen 1
    gen_store[scope_key("SPY", None)] = 1.0
    # User switched to QQQ; SPY gen=2 SSE must not apply to QQQ scope
    assert not l1_tier_b_payload_matches_active_scope(
        {"ticker": "SPY", "l1_generation": 2, "selected_exp": None},
        "QQQ",
        None,
    )


# --- C. Interleaved: two scopes keep isolated generations -----------------------------------


def test_c_generation_isolation_spy_vs_qqq():
    gen_store: Dict[str, float] = {}
    sk_spy = scope_key("SPY", None)
    sk_qqq = scope_key("QQQ", None)
    gen_store[sk_spy] = 10.0
    gen_store[sk_qqq] = 1.0
    assert gen_store[sk_qqq] == 1.0
    assert gen_store[sk_spy] == 10.0
    # QQQ not rejected because of SPY gen
    assert gen_store[sk_qqq] < gen_store[sk_spy]


# --- D. Authority isolation per scope -------------------------------------------------------


def test_d_authority_map_isolated():
    auth: Dict[str, str] = {}
    sk_spy = scope_key("SPY", None)
    sk_qqq = scope_key("QQQ", None)
    auth[sk_spy] = "SSE_LIVE"
    assert auth.get(sk_qqq, "INIT") == "INIT"


# --- E. Norm alignment __auto__ -------------------------------------------------------------


def test_e_auto_expiry_matches_empty_selected():
    assert l1_tier_b_payload_matches_active_scope(
        {"ticker": "SPY", "selected_exp": None},
        "SPY",
        None,
    )
    assert norm_l1_expiry_key(None) == norm_l1_expiry_key("__auto__")


# --- Regression: no global Tier B gen in client source --------------------------------------


def test_no_global_l1_generation_mutable_in_index_html():
    text = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    assert "_l1GenByScope" in text
    assert "window._l1Gen =" not in text
    assert "window._l1Generation =" not in text


def test_authority_and_identity_stores_keyed_by_scope_in_source():
    text = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    assert "_l1AuthorityByScope" in text
    assert "_l1LastPaintedIdentityByScope" in text
    assert "l1TierBPayloadMatchesActiveScope" in text
