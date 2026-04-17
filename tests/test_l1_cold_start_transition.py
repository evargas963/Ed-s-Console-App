"""
Issue 27 — cold start → live: authority state machine + generation acceptance.

Mirrors client rules in static/index.html (renderTierBLight, l1GetAuthority, l1SetAuthority)
and static/js/l1_sse_guards.js (l1ApplyTierBLightMonotonic). Proves:

- No HTTP overwrite after SSE_LIVE (HTTP fully ignored).
- No generation regression vs lastAcceptedGeneration (monotonic store).
- No authority oscillation (SSE_LIVE never reverts; HTTP blocked after SSE).
"""
from __future__ import annotations

import math
from typing import Dict, Literal, Optional, Tuple

import pytest

AuthorityState = Literal["INIT", "HTTP_INIT", "SSE_LIVE"]


def _apply_tier_b_monotonic(
    scope_key: str,
    g: float,
    gen_store: Dict[str, float],
    server_ts: float,
    ts_store: Dict[str, float],
) -> bool:
    """EdL1SseGuards.l1ApplyTierBLightMonotonic (in-process, mutates stores)."""
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
    """
    Single acceptance step matching renderTierBLight (Tier B L1).

    Returns (accepted, new_authority_map).
    """
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


@pytest.fixture
def scope() -> str:
    return "SPY|"


def test_a_http_to_sse_transition_then_http_blocked(scope: str):
    """HTTP loads (gen=1), SSE (gen=2) becomes authority; later HTTP ignored."""
    auth: Dict[str, AuthorityState] = {}
    gen_store: Dict[str, float] = {}
    ts_store: Dict[str, float] = {}

    ok1, auth = try_accept_tier_b_render(scope, auth, "rest_manual", 1.0, 100.0, gen_store, ts_store)
    assert ok1 is True
    assert auth[scope] == "HTTP_INIT"
    assert gen_store[scope] == 1.0

    ok2, auth = try_accept_tier_b_render(scope, auth, "l1_sse", 2.0, 200.0, gen_store, ts_store)
    assert ok2 is True
    assert auth[scope] == "SSE_LIVE"
    assert gen_store[scope] == 2.0

    ok3, auth = try_accept_tier_b_render(scope, auth, "rest_manual", 99.0, 300.0, gen_store, ts_store)
    assert ok3 is False
    assert auth[scope] == "SSE_LIVE"
    assert gen_store[scope] == 2.0


def test_b_late_stale_http_rejected_after_sse(scope: str):
    """SSE gen=10 accepted; late HTTP gen=9 rejected (monotonic)."""
    auth: Dict[str, AuthorityState] = {}
    gen_store: Dict[str, float] = {}
    ts_store: Dict[str, float] = {}

    try_accept_tier_b_render(scope, auth, "rest_manual", 1.0, 10.0, gen_store, ts_store)
    _, auth = try_accept_tier_b_render(scope, auth, "l1_sse", 10.0, 50.0, gen_store, ts_store)
    assert auth[scope] == "SSE_LIVE"
    assert gen_store[scope] == 10.0

    ok_late, auth = try_accept_tier_b_render(scope, auth, "rest_manual", 9.0, 60.0, gen_store, ts_store)
    assert ok_late is False
    assert gen_store[scope] == 10.0


def test_c_no_oscillation_http_higher_gen_still_ignored(scope: str):
    """After SSE_LIVE, HTTP with higher gen=3 must still be ignored (hard HTTP block)."""
    auth: Dict[str, AuthorityState] = {}
    gen_store: Dict[str, float] = {}
    ts_store: Dict[str, float] = {}

    try_accept_tier_b_render(scope, auth, "rest_manual", 1.0, 1.0, gen_store, ts_store)
    _, auth = try_accept_tier_b_render(scope, auth, "l1_sse", 2.0, 2.0, gen_store, ts_store)
    assert auth[scope] == "SSE_LIVE"

    ok, auth = try_accept_tier_b_render(scope, auth, "rest_manual", 3.0, 3.0, gen_store, ts_store)
    assert ok is False
    assert auth[scope] == "SSE_LIVE"
    assert gen_store[scope] == 2.0


def test_d_strict_monotonic_rendered_generations(scope: str):
    """Accepted sequence must never decrease l1_generation."""
    auth: Dict[str, AuthorityState] = {}
    gen_store: Dict[str, float] = {}
    ts_store: Dict[str, float] = {}
    rendered: list[float] = []

    steps = [
        ("rest_manual", 1.0, 10.0),
        ("l1_sse", 2.0, 20.0),
        ("l1_sse", 3.0, 30.0),
        ("rest_manual", 50.0, 99.0),
    ]
    for src, g, ts in steps:
        ok, auth = try_accept_tier_b_render(scope, auth, src, g, ts, gen_store, ts_store)
        if ok:
            rendered.append(g)

    assert rendered == [1.0, 2.0, 3.0]
    for i in range(1, len(rendered)):
        assert rendered[i] >= rendered[i - 1]


def test_sse_never_reverts_authority(scope: str):
    """Once SSE_LIVE, authority string never goes back to HTTP_INIT."""
    auth: Dict[str, AuthorityState] = {}
    gen_store: Dict[str, float] = {}
    ts_store: Dict[str, float] = {}

    try_accept_tier_b_render(scope, auth, "rest_manual", 1.0, 1.0, gen_store, ts_store)
    _, auth = try_accept_tier_b_render(scope, auth, "l1_sse", 2.0, 2.0, gen_store, ts_store)
    assert auth[scope] == "SSE_LIVE"
    try_accept_tier_b_render(scope, auth, "rest_manual", 1.0, 9.0, gen_store, ts_store)
    assert auth[scope] == "SSE_LIVE"


def test_init_to_http_init_without_generation(scope: str):
    """HTTP payload with no l1_generation still promotes INIT → HTTP_INIT (matches client)."""
    auth: Dict[str, AuthorityState] = {}
    gen_store: Dict[str, float] = {}
    ts_store: Dict[str, float] = {}

    ok, auth = try_accept_tier_b_render(scope, auth, "rest_manual", None, float("nan"), gen_store, ts_store)
    assert ok is True
    assert auth[scope] == "HTTP_INIT"
