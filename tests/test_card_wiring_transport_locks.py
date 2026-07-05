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


# ── Lane-3 lock — compute-stage instrumentation must stay stamped ────────────


def test_fetch_state_stamps_compute_breakdown() -> None:
    """Lane-3 (2026-07-05): the Tier C pipeline must attribute its compute time.
    _fetch_state marks named stages and stamps _compute_breakdown on the payload;
    without it the 13–27s _compute_ms is unattributable and cadence/staleness
    policy decisions lose their evidence base."""
    fn = _find_function(SERVER_TREE, "_fetch_state")
    assert fn is not None, "server._fetch_state not found"
    # Def-free marks (the mega1 section-inventory gate counts every def, so the
    # instrumentation appends (stage, perf_counter) pairs instead of calling a helper).
    mark_calls = sum(
        1
        for n in ast.walk(fn)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "append"
        and isinstance(n.func.value, ast.Name)
        and n.func.value.id == "_stage_marks"
    )
    assert mark_calls >= 8, (
        f"_fetch_state has only {mark_calls} _stage_marks.append(...) marks — "
        "compute-stage instrumentation regressed (need the named stage marks)."
    )
    seg = ast.get_source_segment(SERVER_SRC, fn) or ""
    assert '"_compute_breakdown"' in seg, (
        "_fetch_state no longer stamps _compute_breakdown on the payload"
    )


# ── Lane-4 lock — bars persistence must stay off the synchronous hot path ───


def test_fetch_state_bars_persist_offloaded_and_ordered() -> None:
    """Lane-4 (2026-07-05): upsert_1m_bars measured 8,090.8ms of the synchronous
    db_snapshot_write_accuracy stage while its result is never read by the live
    payload. It must run ONLY inside the ordered background task (upsert before
    fill_outcomes, single-worker executor) — never inline in _fetch_state."""
    fn = _find_function(SERVER_TREE, "_fetch_state")
    assert fn is not None, "server._fetch_state not found"
    bg = _find_function(fn, "_bg_persist_bars_then_fill_outcomes")
    assert bg is not None, (
        "_bg_persist_bars_then_fill_outcomes not found — bars persistence has "
        "been moved out of the ordered background task (lane-4 regression)."
    )
    # Every upsert_1m_bars call in _fetch_state must live inside the bg task.
    upsert_lines = [
        n.lineno
        for n in ast.walk(fn)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "upsert_1m_bars"
    ]
    assert upsert_lines, "_fetch_state no longer persists 1m bars at all"
    for ln in upsert_lines:
        assert bg.lineno <= ln <= (bg.end_lineno or bg.lineno), (
            f"upsert_1m_bars called at server.py:{ln} outside the background task — "
            "the 1m-bars write is back on the synchronous Tier C hot path."
        )
    # Ordering inside the task: bars durable before labels advance.
    fill_lines = [
        n.lineno
        for n in ast.walk(bg)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "fill_outcomes"
    ]
    assert fill_lines, "background task no longer runs fill_outcomes"
    assert min(upsert_lines) < min(fill_lines), (
        "fill_outcomes precedes upsert_1m_bars in the background task — labels "
        "could advance before their bars are durable."
    )
    assert "_get_db_fill_outcomes_executor" in _called_names(fn), (
        "_fetch_state no longer submits to the fill-outcomes executor"
    )


def test_fill_outcomes_executor_is_single_worker() -> None:
    """The upsert→fill ordering guarantee rests on max_workers=1; two workers
    would let a newer cycle's bars land before an older cycle's fill reads them."""
    fn = _find_function(SERVER_TREE, "_get_db_fill_outcomes_executor")
    assert fn is not None, "server._get_db_fill_outcomes_executor not found"
    seg = ast.get_source_segment(SERVER_SRC, fn) or ""
    assert "max_workers=1" in seg, (
        "fill-outcomes executor is no longer single-worker — cross-cycle "
        "persist/fill ordering is no longer guaranteed."
    )


# ── Burndown lock — same-tick similarity dedup must stay wired ──────────────

SIGNALS_SRC = (ROOT / "signals.py").read_text(encoding="utf-8")
SIGNALS_TREE = ast.parse(SIGNALS_SRC)


def test_signals_tick_shares_similarity_context() -> None:
    """Burndown (2026-07-05): the fusion overlay and compute_prediction_core ran an
    identical tiered get_similar_setups in the same tick — 57% of the signals-engine
    stage (py-spy: 692/1,214 build_market_state samples). Both hot-path call sites
    must pass the shared per-tick ctx or the duplicate DB retrieval returns."""
    fn = _find_function(SIGNALS_TREE, "_compute_signals_impl")
    assert fn is not None, "signals._compute_signals_impl not found"
    wired = {"build_fusion_model_overlay_for_stack": False, "compute_prediction_core": False}
    for n in ast.walk(fn):
        if not isinstance(n, ast.Call):
            continue
        callee = n.func.id if isinstance(n.func, ast.Name) else (
            n.func.attr if isinstance(n.func, ast.Attribute) else None
        )
        if callee in wired and any(k.arg == "similar_ctx" for k in n.keywords):
            wired[callee] = True
    assert all(wired.values()), (
        f"similar_ctx not passed at hot-path call site(s) {sorted(k for k, v in wired.items() if not v)} "
        "— the same-tick similarity dedup is unwired (duplicate get_similar_setups per tick)."
    )


def test_similar_setups_shared_dedups_exact_args_only() -> None:
    """Functional half: identical kwargs + shared ctx → one DB call, value-equal
    rows, mutation-isolated copies; different kwargs → fresh DB call."""
    from prediction_engine import _similar_setups_shared

    calls: list[dict] = []

    class _Db:
        def get_similar_setups(self, **kw):
            calls.append(kw)
            return [{"match_tier": 1, "outcome_5c": "up"}]

    ctx: dict = {}
    a = _similar_setups_shared(_Db(), ctx, ticker="SPY", timeframe="1m", zone="pin",
                               vwap_side="above", nearest_above_dist=1.0,
                               nearest_below_dist=2.0, as_of_ts_utc=100.0)
    b = _similar_setups_shared(_Db(), ctx, ticker="SPY", timeframe="1m", zone="pin",
                               vwap_side="above", nearest_above_dist=1.0,
                               nearest_below_dist=2.0, as_of_ts_utc=100.0)
    assert len(calls) == 1, "identical same-tick query was not deduplicated"
    assert a == b
    b[0]["outcome_5c"] = "down"
    assert a[0]["outcome_5c"] == "up", "reused rows are not mutation-isolated copies"
    c = _similar_setups_shared(_Db(), ctx, ticker="SPY", timeframe="1m", zone="pin",
                               vwap_side="above", nearest_above_dist=1.0,
                               nearest_below_dist=2.0, as_of_ts_utc=200.0)
    assert len(calls) == 2, "changed args must fall back to a fresh DB query"
    assert c == a
    # No ctx → passthrough, no caching side effects.
    d = _similar_setups_shared(_Db(), None, ticker="QQQ", timeframe="1m", zone="pin",
                               vwap_side="above", nearest_above_dist=1.0,
                               nearest_below_dist=2.0, as_of_ts_utc=100.0)
    assert len(calls) == 3 and d


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
