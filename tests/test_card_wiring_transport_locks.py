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


# ── Burndown lock — IV history must stay a narrow projection ────────────────


def test_fetch_state_iv_history_uses_narrow_projection() -> None:
    """Burndown (2026-07-05): the IV rank/percentile history load pulled 5,000
    FULL-WIDTH snapshot rows (200+ cols incl. option_chain_json blobs) per tick
    per ticker to read one float each — 1,258/3,062 py-spy samples; the narrow
    twin measured 152x faster with identical values against the live DB. The
    hot loop must never regress to the full-width read for IV history."""
    fn = _find_function(SERVER_TREE, "_fetch_state")
    assert fn is not None, "server._fetch_state not found"
    calls = _called_names(fn)
    assert "get_recent_iv_levels" in calls, (
        "_fetch_state no longer uses the narrow iv_level projection — the IV "
        "rank/percentile path regressed to a full-width snapshot read."
    )
    seg = ast.get_source_segment(SERVER_SRC, fn) or ""
    idx = seg.find("IV Rank/Percentile")
    assert idx != -1, "IV rank/percentile block not found in _fetch_state"
    block = seg[idx : idx + 1500]
    assert "get_recent_iv_levels(" in block, "narrow projection call missing from IV block"
    assert "get_recent_snapshots(" not in block, (
        "full-width get_recent_snapshots( call is back inside the IV-history block"
    )


def test_similarity_hot_path_projection_drops_only_blob_columns(tmp_path) -> None:
    """Burndown (2026-07-05): the hot-path similarity read opts into a projection
    that drops ONLY option_chain_json / replay_context_json (no live consumer
    reads them — enumerated across overlay/core/enrichment/labeled-counts).
    Every other column, row order, tier semantics, and match_tier must be
    identical to the default full-width read; default callers stay full-width."""
    from db import EdDB
    from timeframe_config import CANONICAL_TIMEFRAME

    db = EdDB(tmp_path / "sim_projection.db")
    with db._connect() as conn:
        for i in range(3):
            conn.execute(
                "INSERT INTO snapshots (ticker, timeframe, ts_utc, ts_et, spot, zone,"
                " vwap_side, nearest_above_dist, nearest_below_dist, outcome_1c,"
                " outcome_5c, outcome_15c, option_chain_json, replay_context_json)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("SPY", CANONICAL_TIMEFRAME, 1000.0 + i, "test", 450.0, "pin",
                 "above", 1.0, 1.0, "up", "up", "up", '{"big":"blob"}', '{"ctx":1}'),
            )
    kw = dict(ticker="SPY", timeframe=CANONICAL_TIMEFRAME, zone="pin",
              vwap_side="above", nearest_above_dist=1.0, nearest_below_dist=1.0)
    full = db.get_similar_setups(**kw)
    slim = db.get_similar_setups(**kw, exclude_heavy_json_columns=True)
    assert len(full) == len(slim) == 3
    assert set(full[0]) - set(slim[0]) == {"option_chain_json", "replay_context_json"}
    for f, s in zip(full, slim):
        assert {k: f[k] for k in s} == dict(s), "projected rows diverge from full rows"
    assert all(s["match_tier"] == f["match_tier"] for f, s in zip(full, slim))
    assert full[0]["option_chain_json"] == '{"big":"blob"}', "default read lost blobs"


def test_prediction_hot_path_opts_into_similarity_projection() -> None:
    """Both hot-path similarity call sites must pass exclude_heavy_json_columns=True
    (and identically, so the same-tick dedup ctx key still matches)."""
    src = (ROOT / "prediction_engine.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    hits = 0
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_similar_setups_shared"
        ):
            kws = {k.arg for k in node.keywords}
            assert "exclude_heavy_json_columns" in kws, (
                f"_similar_setups_shared call at prediction_engine.py:{node.lineno} "
                "lost the hot-path projection opt-in"
            )
            hits += 1
    assert hits >= 2, "expected both hot-path similarity call sites"


def test_get_recent_iv_levels_matches_full_read(tmp_path) -> None:
    """Parity half: the narrow projection must return exactly the iv_level
    sequence the full-width read returns (same window, order, as-of cutoff)."""
    from db import EdDB
    from timeframe_config import CANONICAL_TIMEFRAME

    db = EdDB(tmp_path / "iv_parity.db")
    with db._connect() as conn:
        for i, iv in enumerate([21.5, None, 0.0, 33.25, 18.0]):
            conn.execute(
                "INSERT INTO snapshots (ticker, timeframe, ts_utc, ts_et, spot, iv_level)"
                " VALUES (?,?,?,?,?,?)",
                ("SPY", CANONICAL_TIMEFRAME, 1000.0 + i, "test", 450.0, iv),
            )
    full = [
        r.get("iv_level")
        for r in db.get_recent_snapshots(
            "SPY", CANONICAL_TIMEFRAME, n=10, filled_only=False, as_of_ts_utc=1004.0
        )
    ]
    narrow = db.get_recent_iv_levels("SPY", CANONICAL_TIMEFRAME, n=10, as_of_ts_utc=1004.0)
    assert narrow == full == [33.25, 0.0, None, 21.5]
    assert db.get_recent_iv_levels("SPY", CANONICAL_TIMEFRAME, n=2) == [18.0, 33.25]


# ── Audit lock — snapshot minute gate must reserve atomically + durably ─────


def test_snapshot_minute_gate_atomic_reserve_and_durable_probe(tmp_path, monkeypatch) -> None:
    """Repo-wide audit (2026-07-05): the check-only gate leaked duplicate
    (ticker, minute) snapshot rows two ways — concurrent callers both passed
    before either committed, and process restarts began with an empty bucket
    (4,783 duplicate groups on disk; SPY dups written same-day). The gate must
    reserve AT CHECK TIME, release on failed insert, and consult the durable
    same-minute existence probe so restarts cannot re-insert a written minute."""
    import server as srv
    from db import EdDB
    from timeframe_config import CANONICAL_TIMEFRAME

    monkeypatch.setenv("ED_DB_SNAPSHOT_THROTTLE", "1")
    saved = dict(srv._db_snapshot_minute_bucket)
    srv._db_snapshot_minute_bucket.clear()
    try:
        ts = 6_000_000.0  # minute bucket 100000
        # 1. Atomic reserve: second concurrent caller in the same minute is blocked
        #    BEFORE any insert commits.
        assert srv._snapshot_row_insert_allowed("SPY", ts) is True
        assert srv._snapshot_row_insert_allowed("SPY", ts + 5.0) is False
        # 2. Failed insert releases the minute for a same-minute retry.
        srv._snapshot_row_insert_release("SPY", ts)
        assert srv._snapshot_row_insert_allowed("SPY", ts + 10.0) is True
        # 3. Committed keeps the minute closed; release after commit-era bucket
        #    of a DIFFERENT minute is a no-op.
        srv._snapshot_row_insert_committed("SPY", ts)
        assert srv._snapshot_row_insert_allowed("SPY", ts + 20.0) is False
        # 4. Next minute opens normally.
        assert srv._snapshot_row_insert_allowed("SPY", ts + 60.0) is True
        # 5. Restart simulation: fresh (empty) bucket, but the DB already holds a
        #    row for the minute — the durable probe must block the re-insert.
        db = EdDB(tmp_path / "gate.db")
        with db._connect() as conn:
            conn.execute(
                "INSERT INTO snapshots (ticker, timeframe, ts_utc, ts_et, spot)"
                " VALUES (?,?,?,?,?)",
                ("SPY", CANONICAL_TIMEFRAME, ts + 3.0, "test", 450.0),
            )
        srv._db_snapshot_minute_bucket.clear()  # simulate process restart
        assert db.snapshot_exists_in_minute("SPY", CANONICAL_TIMEFRAME, int(ts // 60)) is True
        assert srv._snapshot_row_insert_allowed("SPY", ts + 30.0, db=db) is False
        # 6. A minute with no durable row still opens after restart.
        assert srv._snapshot_row_insert_allowed("SPY", ts + 120.0, db=db) is True
    finally:
        srv._db_snapshot_minute_bucket.clear()
        srv._db_snapshot_minute_bucket.update(saved)


def test_snapshot_insert_sites_release_reservation_on_failure() -> None:
    """Both production insert sites must pass the db handle to the gate and
    release the reservation when the insert path fails."""
    fn = _find_function(SERVER_TREE, "_fetch_state")
    assert fn is not None
    seg = ast.get_source_segment(SERVER_SRC, fn) or ""
    assert "_snapshot_row_insert_allowed(ticker, _snap_ts, db=_ed_db)" in seg, (
        "_fetch_state gate call lost the durable-probe db handle"
    )
    assert "_snapshot_row_insert_release(ticker, _snap_ts)" in seg, (
        "_fetch_state no longer releases a failed reservation"
    )
    assert "db=get_db()" in SERVER_SRC and "_snapshot_row_insert_release(t, snap_ts)" in SERVER_SRC, (
        "base money-path capture site lost the durable probe or failure release"
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
