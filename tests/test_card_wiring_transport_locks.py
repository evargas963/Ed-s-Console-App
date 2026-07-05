"""Regression locks for the card-wiring transport fixes (commit 3a0d338).

Defect classes locked (runtime-proven in the 2026-07-04 pre-RTH audit):
  1. Analytics-pool self-deadlock — _fetch_state ran its chain/quote futures on the
     same 4-worker analytics executor that runs _fetch_state itself; >=3 concurrent
     Tier C jobs parked every worker at .result() forever (py-spy proof).
  2. Expiry carryover on ticker switch (client) — behavioral lock in
     tests/e2e/ticker-switch-expiry-reset.spec.js; source lock here.
  3. Ordering-cursor scope (client) — gen-less quote/shell payloads must not advance
     the money-path ordering cursor; behavioral lock in the same e2e spec.
  4. SSE completed-fetch mirror parity — payloads broadcast after a completed
     _fetch_state must carry card_freshness_v1 + operator_card_* mirrors, matching
     REST and SSE cache-fanout.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER_SRC = (ROOT / "server.py").read_text(encoding="utf-8")
SERVER_TREE = ast.parse(SERVER_SRC)
INDEX_SRC = (ROOT / "static" / "index.html").read_text(encoding="utf-8")


def _find_function(tree: ast.AST, name: str) -> ast.FunctionDef | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def _called_names(node: ast.AST) -> set[str]:
    out: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name):
                out.add(f.id)
            elif isinstance(f, ast.Attribute):
                out.add(f.attr)
    return out


# ── Lock 1 — analytics-pool self-deadlock ────────────────────────────────────


def test_fetch_state_never_submits_to_analytics_pool() -> None:
    """_fetch_state occupies an analytics worker; nested submit+.result() on the
    same pool self-deadlocks once the pool saturates. Chain/quote parallelization
    must use a pool whose tasks never wait on analytics futures."""
    fn = _find_function(SERVER_TREE, "_fetch_state")
    assert fn is not None, "server._fetch_state not found"
    calls = _called_names(fn)
    assert "_submit_analytics_task" not in calls, (
        "_fetch_state submits work back into the analytics executor — this is the "
        "nested submit+.result() self-deadlock class fixed at 3a0d338 (py-spy proof "
        "2026-07-04: all four ed_analytics_bg workers parked at .result())."
    )
    assert "_get_route_offload_executor" in calls, (
        "_fetch_state chain/quote parallel fetch must run on the route-offload pool "
        "(leaf HTTP tasks; no wait cycle back into the analytics pool)."
    )


# ── Lock 4 — SSE completed-fetch mirror parity ──────────────────────────────


def test_completed_fetch_broadcast_attaches_operator_mirrors() -> None:
    """The completed-fetch broadcast path must attach the same actionability block
    REST and SSE cache-fanout attach — otherwise an SSE-fed card can paint
    actionable in a fresh-bundle/stale-quote window where REST clients are withheld."""
    outer = _find_function(SERVER_TREE, "_schedule_analytics_recompute")
    assert outer is not None, "server._schedule_analytics_recompute not found"
    inner = _find_function(outer, "_work")
    assert inner is not None, "_schedule_analytics_recompute._work not found"
    assert "_attach_card_freshness_v1_block" in _called_names(inner), (
        "completed-fetch broadcast no longer attaches card_freshness_v1 / "
        "operator_card_* mirrors — SSE/REST actionability parity regressed."
    )


def test_attach_block_stamps_operator_mirrors_functionally() -> None:
    """Functional half of lock 4: the attach block must stamp the S2B-1 mirrors."""
    import server

    md: dict = {"ticker": "SPY", "mhap_rows": [], "analytics_stale": False}
    server._attach_card_freshness_v1_block(
        md,
        ticker="SPY",
        now=1_000_000.0,
        analytics_ttl_sec=5.0,
        tier_c_cache_stale_serve=False,
        plane_quote=None,
    )
    assert md.get("operator_card_actionable") is False  # mhap_missing → withheld
    assert isinstance(md.get("operator_stale_reason_codes"), list)
    assert md.get("operator_actionability_reason")
    cf = md.get("card_freshness_v1")
    assert isinstance(cf, dict) and cf.get("card_trust_state")


# ── Locks 2 + 3 — client source guards (behavioral locks live in
#    tests/e2e/ticker-switch-expiry-reset.spec.js) ───────────────────────────


def test_client_ordering_cursor_commits_gen_bearing_only() -> None:
    marker = "function _edMplMonotonicGateRecordAccept"
    assert marker in INDEX_SRC, "ordering-gate accept recorder not found in index.html"
    body = INDEX_SRC[INDEX_SRC.index(marker) : INDEX_SRC.index(marker) + 1600]
    assert "if (key.gen != null)" in body, (
        "ordering cursor is no longer restricted to gen-bearing Tier C bundles — "
        "a fresher gen-less quote/shell payload can again block a valid cached "
        "bundle as ts_regression (QQQ LOADING wedge, audit 2026-07-04)."
    )
    assert body.index("if (key.gen != null)") < body.index(
        "_edMplMonotonicLastAccepted = {"
    ), "cursor assignment escaped the gen-bearing guard"


def test_client_render_updates_module_level_render_source_diag() -> None:
    """Lane-2 diagnostic lock: _edTransportSync reads the module-level
    _lastFullRenderSource; render must assign it (not only the window property),
    or __edTransport.lastFullRenderSource reverts to 'init' on the next sync."""
    marker = "if (fullRenderSource) {"
    assert marker in INDEX_SRC, "render fullRenderSource block not found in index.html"
    body = INDEX_SRC[INDEX_SRC.index(marker) : INDEX_SRC.index(marker) + 1400]
    assert "_lastFullRenderSource = fullRenderSource;" in body, (
        "render no longer assigns the module-level _lastFullRenderSource — "
        "__edTransport.lastFullRenderSource sticks at 'init' (lane-2 regression)."
    )
    assert "window._lastFullRenderSource = fullRenderSource;" in body, (
        "window._lastFullRenderSource mirror removed — external consumers lose it"
    )


def test_client_ticker_switch_resets_expiry_scope() -> None:
    marker = "async function fetchState"
    assert marker in INDEX_SRC, "fetchState not found in index.html"
    body = INDEX_SRC[INDEX_SRC.index(marker) : INDEX_SRC.index(marker) + 3200]
    assert "if (domTicker !== prevT)" in body, "ticker-switch expiry reset guard missing"
    seg_start = body.index("if (domTicker !== prevT)")
    seg = body[seg_start : seg_start + 1100]
    assert "domExpiry = null" in seg, (
        "ticker switch no longer resets the expiry scope — the prior ticker's "
        "expiry is carried into the new ticker's requests (AAPL wedge, audit "
        "2026-07-04)."
    )
    assert "innerHTML = ''" in seg, "stale expiry select is no longer cleared on switch"
