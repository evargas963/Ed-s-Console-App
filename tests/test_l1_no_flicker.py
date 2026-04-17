"""
Issue 25 — Tier B / L1: no flicker under mixed HTTP + SSE (dedupe + existing guards).

Mirrors client logic in static/index.html:
- l1TierBComputeVisiblePaintInputs + l1TierBSemanticSignatureFromPaintInputs (semantic identity)
- _l1LastPaintedIdentityByScope dedupe after monotonic (Issue 27 authority unchanged)
- Same authority + monotonic rules as test_l1_cold_start_transition.py (must stay aligned).
"""
from __future__ import annotations

import math
from typing import Any, Dict, Literal, Optional, Tuple

import pytest

AuthorityState = Literal["INIT", "HTTP_INIT", "SSE_LIVE"]
Outcome = Literal["rejected", "deduped", "painted"]


def _apply_tier_b_monotonic(
    scope_key: str,
    g: float,
    gen_store: Dict[str, float],
    server_ts: float,
    ts_store: Dict[str, float],
) -> bool:
    """EdL1SseGuards.l1ApplyTierBLightMonotonic — keep in sync with test_l1_cold_start_transition."""
    if g is None or not isinstance(g, (int, float)) or not math.isfinite(g):
        return True
    prev = gen_store.get(scope_key)
    last_ts = ts_store.get(scope_key) if ts_store and scope_key in ts_store else float("nan")
    if not math.isfinite(last_ts):
        last_ts = float("nan")
    if prev is not None and g < prev:
        return False
    if prev is not None and g == prev:
        if math.isfinite(server_ts) and math.isfinite(last_ts) and server_ts < last_ts:
            return False
    gen_store[scope_key] = max(prev or 0, g)
    if ts_store is not None and math.isfinite(server_ts):
        base = last_ts if math.isfinite(last_ts) else 0.0
        ts_store[scope_key] = max(base, server_ts)
    return True


def try_accept_tier_b_render(
    scope_key: str,
    authority_by_scope: Dict[str, AuthorityState],
    full_render_source: str,
    g: Optional[float],
    server_ts: float,
    gen_store: Dict[str, float],
    ts_store: Dict[str, float],
) -> Tuple[bool, Dict[str, AuthorityState]]:
    """Single acceptance step matching renderTierBLight — keep in sync with test_l1_cold_start_transition."""
    is_sse = full_render_source == "l1_sse"
    if is_sse and (
        g is None
        or not isinstance(g, (int, float))
        or not math.isfinite(g)
    ):
        return False, dict(authority_by_scope)

    auth = authority_by_scope.get(scope_key, "INIT")
    if auth == "SSE_LIVE" and not is_sse:
        return False, dict(authority_by_scope)

    if g is not None and isinstance(g, (int, float)) and math.isfinite(g):
        prev_accepted = gen_store.get(scope_key)
        if not _apply_tier_b_monotonic(scope_key, g, gen_store, server_ts, ts_store):
            return False, dict(authority_by_scope)
        if is_sse:
            last_acc = prev_accepted if prev_accepted is not None else 0.0
            assert g >= last_acc, "SSE l1_generation must be >= lastAcceptedGeneration"

    new_auth = dict(authority_by_scope)
    if is_sse:
        new_auth[scope_key] = "SSE_LIVE"
    elif new_auth.get(scope_key, "INIT") == "INIT":
        new_auth[scope_key] = "HTTP_INIT"

    return True, new_auth


def _tier_b_semantic_signature(payload: dict[str, Any]) -> str:
    """Match l1TierBSemanticSignatureFromPaintInputs when fingerprint set; else fallback path."""
    fp = payload.get("l1_payload_fingerprint")
    if fp is not None and str(fp) != "":
        return "fp:" + str(fp)
    # Fallback mirrors freshSig + strip fields (simplified stable subset for tests).
    q_age = payload.get("quote_overlay_age_sec")
    of_age = payload.get("order_flow_age_sec")
    q_tier = "muted"
    if payload.get("quote_live_overlay_applied") is True and isinstance(q_age, (int, float)) and math.isfinite(q_age):
        if q_age <= 2.0:
            q_tier = "fresh"
        elif q_age <= 15.0:
            q_tier = "aging"
        else:
            q_tier = "stale"
    of_tier = "stale" if payload.get("order_flow_stale") is True else (
        "muted" if not isinstance(of_age, (int, float)) or not math.isfinite(of_age)
        else ("fresh" if of_age <= 3.0 else ("aging" if of_age < 30.0 else "stale"))
    )
    q_line = f"Q:{q_age}" if payload.get("quote_live_overlay_applied") is True else "Q:no"
    of_line = f"OF:{of_age}"
    tail = str(payload.get("l1_generation") or "")
    fresh_sig = "|".join(
        [
            q_line,
            of_line,
            q_tier,
            of_tier,
            "1" if payload.get("order_flow_stale") else "0",
            str((payload.get("l1_projection") or {}).get("mode", "")),
            str(round((q_age if isinstance(q_age, (int, float)) and math.isfinite(q_age) else -1) * 4) / 4),
            str(round((of_age if isinstance(of_age, (int, float)) and math.isfinite(of_age) else -1) * 4) / 4),
            tail,
        ]
    )
    of = payload.get("order_flow") or {}
    zone = str(payload.get("zone_label") or payload.get("zone") or "")
    parts = [
        fresh_sig,
        zone,
        str(payload.get("bias_signal") or ""),
        str(payload.get("pin_strength") or ""),
        str(payload.get("nd_disp") or ""),
        str(payload.get("net_gamma") or ""),
        str(of.get("order_flow_verdict") or ""),
        str(of.get("order_flow_verdict_color") or ""),
    ]
    return "\x1e".join(parts)


def tier_b_render_step(
    scope_key: str,
    active_ticker: str,
    payload_ticker: str,
    authority_by_scope: Dict[str, AuthorityState],
    gen_store: Dict[str, float],
    ts_store: Dict[str, float],
    last_painted: Dict[str, Tuple[float, str]],
    full_render_source: str,
    g: Optional[float],
    server_ts: float,
    payload: dict[str, Any],
) -> Outcome:
    """One Tier B render attempt: ticker → authority+monotonic → semantic dedupe. Mutates authority_by_scope."""
    if payload_ticker.upper() != active_ticker.upper():
        return "rejected"

    ok, new_auth = try_accept_tier_b_render(
        scope_key, authority_by_scope, full_render_source, g, server_ts, gen_store, ts_store
    )
    authority_by_scope.clear()
    authority_by_scope.update(new_auth)
    if not ok:
        return "rejected"

    if g is None or not isinstance(g, (int, float)) or not math.isfinite(g):
        return "painted"

    sig = _tier_b_semantic_signature(payload)
    prev = last_painted.get(scope_key)
    if prev is not None and prev[0] == g and prev[1] == sig:
        return "deduped"

    last_painted[scope_key] = (float(g), sig)
    return "painted"


# --- A. Duplicate SSE (same scope, gen, semantic) → dedupe ---------------------------------


def test_a_duplicate_sse_no_repaint():
    scope = "SPY|"
    auth: Dict[str, AuthorityState] = {}
    gen_store: Dict[str, float] = {}
    ts_store: Dict[str, float] = {}
    last_painted: Dict[str, Tuple[float, str]] = {}
    p = {
        "l1_payload_fingerprint": "abc123" * 5 + "abcdef",  # 32 hex-like
        "l1_generation": 2,
        "_server_build_ts": 100.0,
        "quote_overlay_age_sec": 0.5,
        "order_flow_age_sec": 1.0,
    }
    o1 = tier_b_render_step(
        scope, "SPY", "SPY", auth, gen_store, ts_store, last_painted, "l1_sse", 2.0, 100.0, p
    )
    o2 = tier_b_render_step(
        scope, "SPY", "SPY", auth, gen_store, ts_store, last_painted, "l1_sse", 2.0, 100.0, dict(p)
    )
    assert o1 == "painted"
    assert o2 == "deduped"


# --- B. Late HTTP after SSE does not repaint ------------------------------------------------


def test_b_late_http_after_sse_no_repaint():
    scope = "SPY|"
    auth: Dict[str, AuthorityState] = {}
    gen_store: Dict[str, float] = {}
    ts_store: Dict[str, float] = {}
    last_painted: Dict[str, Tuple[float, str]] = {}
    http1 = {"l1_generation": 1, "_server_build_ts": 10.0, "l1_payload_fingerprint": "a" * 32}
    sse2 = {"l1_generation": 2, "_server_build_ts": 20.0, "l1_payload_fingerprint": "b" * 32}

    tier_b_render_step(scope, "SPY", "SPY", auth, gen_store, ts_store, last_painted, "rest_manual", 1.0, 10.0, http1)
    tier_b_render_step(scope, "SPY", "SPY", auth, gen_store, ts_store, last_painted, "l1_sse", 2.0, 20.0, sse2)

    o_late = tier_b_render_step(
        scope,
        "SPY",
        "SPY",
        auth,
        gen_store,
        ts_store,
        last_painted,
        "rest_manual",
        1.0,
        99.0,
        dict(http1),
    )
    assert o_late == "rejected"
    assert auth.get(scope) == "SSE_LIVE"


# --- C. Same gen + newer ts, identical fingerprint → dedupe --------------------------------


def test_c_same_gen_newer_ts_identical_fp_no_repaint():
    scope = "SPY|"
    auth: Dict[str, AuthorityState] = {}
    gen_store: Dict[str, float] = {}
    ts_store: Dict[str, float] = {}
    last_painted: Dict[str, Tuple[float, str]] = {}
    fp = "c" * 32
    p1 = {"l1_generation": 5, "_server_build_ts": 50.0, "l1_payload_fingerprint": fp}
    p2 = {"l1_generation": 5, "_server_build_ts": 51.0, "l1_payload_fingerprint": fp, "_pipeline_ms": 9.9}

    o1 = tier_b_render_step(
        scope, "SPY", "SPY", auth, gen_store, ts_store, last_painted, "l1_sse", 5.0, 50.0, p1
    )
    o2 = tier_b_render_step(
        scope, "SPY", "SPY", auth, gen_store, ts_store, last_painted, "l1_sse", 5.0, 51.0, p2
    )
    assert o1 == "painted"
    assert o2 == "deduped"


# --- D. Higher generation repaints --------------------------------------------------------


def test_d_higher_generation_repaints():
    scope = "SPY|"
    auth: Dict[str, AuthorityState] = {}
    gen_store: Dict[str, float] = {}
    ts_store: Dict[str, float] = {}
    last_painted: Dict[str, Tuple[float, str]] = {}
    p2 = {"l1_generation": 2, "_server_build_ts": 1.0, "l1_payload_fingerprint": "d" * 32}
    p3 = {"l1_generation": 3, "_server_build_ts": 2.0, "l1_payload_fingerprint": "e" * 32}

    o1 = tier_b_render_step(
        scope, "SPY", "SPY", auth, gen_store, ts_store, last_painted, "l1_sse", 2.0, 1.0, p2
    )
    o2 = tier_b_render_step(
        scope, "SPY", "SPY", auth, gen_store, ts_store, last_painted, "l1_sse", 3.0, 2.0, p3
    )
    assert o1 == "painted"
    assert o2 == "painted"


# --- E. Wrong ticker (old scope) rejected ---------------------------------------------------


def test_e_wrong_ticker_payload_rejected():
    scope = "QQQ|"
    auth: Dict[str, AuthorityState] = {}
    gen_store: Dict[str, float] = {}
    ts_store: Dict[str, float] = {}
    last_painted: Dict[str, Tuple[float, str]] = {}
    p = {"l1_generation": 1, "_server_build_ts": 1.0, "l1_payload_fingerprint": "f" * 32}

    o = tier_b_render_step(
        scope, "QQQ", "SPY", auth, gen_store, ts_store, last_painted, "l1_sse", 1.0, 1.0, p
    )
    assert o == "rejected"


# --- Monotonic still enforced (no stale repaint after higher gen) ---------------------------


def test_monotonic_rejects_stale_after_paint():
    scope = "SPY|"
    auth: Dict[str, AuthorityState] = {}
    gen_store: Dict[str, float] = {}
    ts_store: Dict[str, float] = {}
    last_painted: Dict[str, Tuple[float, str]] = {}
    tier_b_render_step(
        scope, "SPY", "SPY", auth, gen_store, ts_store, last_painted, "l1_sse", 3.0, 10.0, {"l1_generation": 3, "l1_payload_fingerprint": "g" * 32}
    )
    o = tier_b_render_step(
        scope,
        "SPY",
        "SPY",
        auth,
        gen_store,
        ts_store,
        last_painted,
        "l1_sse",
        2.0,
        20.0,
        {"l1_generation": 2, "l1_payload_fingerprint": "h" * 32},
    )
    assert o == "rejected"
