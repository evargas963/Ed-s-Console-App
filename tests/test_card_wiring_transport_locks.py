"""Regression locks for the card-wiring transport fixes (commit 3a0d338).

Defect classes locked (runtime-proven in the 2026-07-04 pre-RTH audit):
  1. Analytics-pool self-deadlock — _fetch_state ran its chain/quote futures on the
     same 4-worker analytics executor that runs _fetch_state itself; >=3 concurrent
     Tier C jobs parked every worker at .result() forever (py-spy proof).
  2. Expiry carryover on ticker switch (client) — source lock here; the e2e behavioral
     companion (tests/e2e/ticker-switch-expiry-reset.spec.js) was retired 2026-09-15
     (tested window.*/DOM ids absent from the current static/index.html — see the note
     at Locks 2+3 below).
  3. Ordering-cursor scope (client) — gen-less quote/shell payloads must not advance
     the money-path ordering cursor; its own behavioral lock was retired alongside the
     same e2e spec (see the note at Locks 2+3 below).
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
# RC-REHAB-1 (2026-09-23, module extraction, twentieth slice): _post_publish_persistence_tail
# moved out of server.py into its own file -- no longer findable in SERVER_TREE at all.
TAIL_SRC = (ROOT / "server_state_persistence_tail.py").read_text(encoding="utf-8")
TAIL_TREE = ast.parse(TAIL_SRC)


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
    # RC-REHAB-1 (thirty-fourth slice): the chain/quote leg moved to server_state_intake.py;
    # _fetch_state must delegate to it, and neither body may submit into the analytics pool.
    assert "_fetch_chain_and_quote_for_state" in _called_names(fn)
    intake_tree = ast.parse((ROOT / "server_state_intake.py").read_text(encoding="utf-8"))
    intake_fn = _find_function(intake_tree, "_fetch_chain_and_quote_for_state")
    assert intake_fn is not None
    assert "_submit_analytics_task" not in _called_names(fn)
    calls = _called_names(intake_fn)
    assert "_submit_analytics_task" not in calls, (
        "_fetch_state submits work back into the analytics executor — this is the "
        "nested submit+.result() self-deadlock class fixed at 3a0d338 (py-spy proof "
        "2026-07-04: all four ed_analytics_bg workers parked at .result())."
    )
    # OPERATOR_CARD_PRIORITY_ISOLATION_V1_STEP_2: the nested chain/quote/seed
    # futures moved from the shared route pool to the dedicated recompute-leaf
    # pool. The deadlock invariant is pool-agnostic: the pool used must never
    # wait back into the analytics pool (leaf-ness AST-locked in
    # tests/test_analytics_state_freshness_api.py).
    assert "_get_recompute_leaf_executor" in calls, (
        "_fetch_state chain/quote parallel fetch must run on the dedicated "
        "recompute-leaf pool (true leaf tasks; no wait cycle back into the "
        "analytics pool)."
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
    fill_outcomes, single-worker executor) — never inline in _fetch_state.

    RC-REHAB-1 (Phase 4, _fetch_state decomposition, nineteenth slice): the
    background task's owner, _post_publish_persistence_tail, was promoted from a
    nested closure inside _fetch_state to a module-level function -- found
    directly at module scope now, not as a descendant of _fetch_state's own
    AST node. The invariants themselves (no bars write on the render path,
    fill_outcomes ordered inside the background task, submitted to the
    fill-outcomes executor) are unchanged; only where each is checked moved.

    RC-REHAB-1 (2026-09-23, module extraction, twentieth slice): the tail moved out
    of server.py entirely, into server_state_persistence_tail.py -- found there now."""
    fn = _find_function(SERVER_TREE, "_fetch_state")
    assert fn is not None, "server._fetch_state not found"
    tail = _find_function(TAIL_TREE, "_post_publish_persistence_tail")
    assert tail is not None, "server_state_persistence_tail._post_publish_persistence_tail not found"
    bg = _find_function(tail, "_bg_persist_bars_then_fill_outcomes")
    assert bg is not None, (
        "_bg_persist_bars_then_fill_outcomes not found — bars persistence has "
        "been moved out of the ordered background task (lane-4 regression)."
    )
    # RC-69 SUPERSEDES THE BARS HALF OF THIS LOCK. Lane-4 correctly moved the 8,090.8ms
    # upsert_1m_bars off the synchronous path; RC-69 removed it from this RENDER path entirely,
    # because persisting bars here made COLLECTION a side-effect of DISPLAY (MEASURED 2026-07-27:
    # SPY on-screen bar lag 3.1 min vs QQQ/IWM 19.1 min off-screen, all three with ~1.0 min
    # snapshot lag; 39.8% of snapshots unlabelled for want of forward bars). `_bars_loop` is now
    # the ONE writer of price_bars_1m. This lock now guards that the render path does NOT write
    # bars, and that outcome labelling stays offloaded and ordered. Checked across both
    # _fetch_state and the (now-separate) persistence tail -- neither may write bars.
    upsert_lines = [
        n.lineno
        for n in list(ast.walk(fn)) + list(ast.walk(tail))
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "upsert_1m_bars"
    ]
    assert not upsert_lines, (
        f"RC-69 regression: bars persisted at server.py:{upsert_lines} - bar "
        f"collection is coupled to the viewport again."
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
    # The old upsert-before-fill ordering assertion is retired with the bars write itself:
    # bars are now durable ahead of any render because `_bars_loop` persists them continuously
    # and independently, rather than racing a per-render background task.
    assert "_get_db_fill_outcomes_executor" in _called_names(tail), (
        "the persistence tail no longer submits to the fill-outcomes executor"
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
    hot loop must never regress to the full-width read for IV history.

    RC-REHAB-1 (Phase 4, _fetch_state decomposition, fourth slice, predating this
    session's visible portion): the IV rank/percentile block moved out of
    _fetch_state's own body into _volatility_signals_for_state well before this
    lock was last verified; checked against that function's own source now,
    caught here by running the full suite rather than a curated batch.

    RC-REHAB-1 (2026-09-22, module extraction): _volatility_signals_for_state moved
    again, out of server.py entirely into server_state_volatility.py -- checked against
    that module's own source, not SERVER_TREE (which no longer contains this function's
    body, only a re-export import)."""
    vol_src = (ROOT / "server_state_volatility.py").read_text(encoding="utf-8")
    vol_tree = ast.parse(vol_src)
    fn = _find_function(vol_tree, "_volatility_signals_for_state")
    assert fn is not None, "server_state_volatility._volatility_signals_for_state not found"
    calls = _called_names(fn)
    assert "get_recent_iv_levels" in calls, (
        "_volatility_signals_for_state no longer uses the narrow iv_level "
        "projection — the IV rank/percentile path regressed to a full-width "
        "snapshot read."
    )
    seg = ast.get_source_segment(vol_src, fn) or ""
    idx = seg.find("IV Rank/Percentile")
    assert idx != -1, "IV rank/percentile block not found in _volatility_signals_for_state"
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
    release the reservation when the insert path fails.

    RC-REHAB-1 (Phase 4, _fetch_state decomposition, nineteenth slice):
    _post_publish_persistence_tail (which consumes the reservation and releases
    it on failure) was promoted to a module-level function -- checked against
    its own source segment now; the reservation TAKEN at the pre-publish
    identity anchor is still inside _fetch_state's own body, unaffected.

    RC-REHAB-1 (2026-09-23, module extraction, twentieth slice): the tail moved out
    of server.py into server_state_persistence_tail.py -- found and its source
    segment extracted from there now. _snapshot_row_insert_release itself stayed in
    server.py (it has other callers), reached lazily as `_srv.` from the tail."""
    fn = _find_function(SERVER_TREE, "_fetch_state")
    assert fn is not None
    seg = ast.get_source_segment(SERVER_SRC, fn) or ""
    tail = _find_function(TAIL_TREE, "_post_publish_persistence_tail")
    assert tail is not None, "server_state_persistence_tail._post_publish_persistence_tail not found"
    tail_seg = ast.get_source_segment(TAIL_SRC, tail) or ""
    # EXEC_IDENTITY_DECISION_SURFACE_ORDERING_V1: the reservation is taken at
    # the pre-publish identity anchor (same key: ticker + refresh ts, same db
    # handle) and the tail consumes it — the durable-probe db handle and the
    # single-reservation-per-cycle semantics are unchanged.
    # RC-REHAB-1 (thirty-fifth slice): the reservation is taken inside the identity anchor
    # (server_state_decision.py), which _fetch_state calls with its own db handle.
    assert "_anchor_execution_identity_for_state(" in seg and "db=_ed_db" in seg
    dec_src = (ROOT / "server_state_decision.py").read_text(encoding="utf-8")
    assert "_srv._snapshot_row_insert_allowed(ticker, refresh_ts_utc, db=db)" in dec_src, (
        "the anchor's gate call lost the durable-probe db handle"
    )
    assert "_do_insert = _xid_do_snapshot_insert" in tail_seg, (
        "the persistence tail must consume the hoisted reservation"
    )
    assert "_srv._snapshot_row_insert_release(ticker, _snap_ts)" in tail_seg, (
        "the persistence tail no longer releases a failed reservation"
    )
    assert "db=get_db()" in SERVER_SRC and "_snapshot_row_insert_release(t, snap_ts)" in SERVER_SRC, (
        "base money-path capture site lost the durable probe or failure release"
    )


def test_offhours_snapshot_writes_gated_rc48() -> None:
    """RC-48: no off-hours (overnight / weekend / full holiday) snapshot may be
    persisted — options don't trade, spot doesn't move, training excludes them,
    nothing reads them. Both capture paths route through the ONE calendar
    authority time_et.is_capturable_session: the SSE _fetch_state insert skips +
    releases the reservation when it is False, and the base logger's
    _is_loggable_session ANDs it in so its minute-window is no longer
    weekday/holiday-blind (the leak that mislabeled 27,681 weekend rows 'rth').

    RC-REHAB-1 (Phase 4, _fetch_state decomposition, nineteenth slice): the
    off-hours insert-skip gate lives inside _post_publish_persistence_tail now
    (promoted to a module-level function), not _fetch_state's own body.

    RC-REHAB-1 (2026-09-23, module extraction, twentieth slice): the tail (and its
    own direct `from time_et import is_capturable_session`) moved out of server.py
    into server_state_persistence_tail.py."""
    assert "is_capturable_session" in TAIL_SRC, "the persistence tail lost the capture authority import"
    tail = _find_function(TAIL_TREE, "_post_publish_persistence_tail")
    assert tail is not None, "server_state_persistence_tail._post_publish_persistence_tail not found"
    tail_seg = ast.get_source_segment(TAIL_SRC, tail) or ""
    assert "elif not is_capturable_session():" in tail_seg, (
        "off-hours capture gate (RC-48) missing from the persistence tail"
    )
    ils = _find_function(SERVER_TREE, "_is_loggable_session")
    assert ils is not None
    ils_seg = ast.get_source_segment(SERVER_SRC, ils) or ""
    assert "is_capturable_session()" in ils_seg, (
        "_is_loggable_session no longer calendar-aware (RC-48 weekend/holiday leak reopened)"
    )


# ── Audit lock — accuracy must be computed for the SERVING model version ────


def test_accuracy_callers_use_serving_model_version() -> None:
    """Repo-wide audit (2026-07-05): compute_accuracy / accuracy-history callers
    hardcoded the legacy 'statistical_v1' version, which matches ZERO persisted
    rows — the accuracy payload block and history were silently empty forever.
    Every accuracy caller must resolve the serving version via
    _current_pred_model_version (the same source that stamps rows)."""
    helper = _find_function(SERVER_TREE, "_current_pred_model_version")
    assert helper is not None, "server._current_pred_model_version not found"
    seg = ast.get_source_segment(SERVER_SRC, helper) or ""
    assert "get_model_version" in seg, (
        "_current_pred_model_version no longer resolves via ml_predict.get_model_version"
    )
    assert '"statistical_v1"' not in seg
    # No accuracy call site may pass the dead literal anywhere in server.py.
    for n in ast.walk(SERVER_TREE):
        if not isinstance(n, ast.Call):
            continue
        callee = n.func.attr if isinstance(n.func, ast.Attribute) else (
            n.func.id if isinstance(n.func, ast.Name) else None
        )
        if callee in ("compute_accuracy", "maybe_log_model_accuracy", "get_model_accuracy_history"):
            for k in n.keywords:
                if k.arg == "model_version":
                    assert not (
                        isinstance(k.value, ast.Constant) and k.value.value == "statistical_v1"
                    ), f"dead 'statistical_v1' literal at server.py:{n.lineno} ({callee})"
            if callee == "compute_accuracy":
                assert any(k.arg == "model_version" for k in n.keywords), (
                    f"compute_accuracy at server.py:{n.lineno} relies on the dead default"
                )


# ── Lock 4 — SSE completed-fetch mirror parity ──────────────────────────────
# REMOVED 2026-09-21: card_freshness_v1 / operator_card_* mirrors and the
# _attach_card_freshness_v1_block function they locked are confirmed dead --
# CARD_TRUST_CONTRACT.md's resolveCardTrustGate, the sole intended consumer,
# does not exist anywhere in the rebuilt frontend, and neither field has any
# other Python-side reader or database column.


# ── Locks 2 + 3 — client source guards ────────────────────────────────────
# The behavioral companion (tests/e2e/ticker-switch-expiry-reset.spec.js) was itself
# retired 2026-09-15: every window.*/DOM id it exercised (__edTestHooks, #cv2-hd-ticker,
# window.setActiveTicker, _edMplMonotonicGateReset, acceptMoneyPathPayload) was verified
# absent from the current static/index.html (direct read + git HEAD, not assumed from a
# prior triage's own notes) -- the whole file tested a page structure that no longer
# exists. The ticker-switch/expiry-reset invariant itself stays covered below, against
# the CURRENT ed-core.js.


# test_client_ordering_cursor_commits_gen_bearing_only and
# test_client_render_updates_module_level_render_source_diag were retired here (/console
# cutover, operator directive 2026-09-14): both locked legacy static/index.html's
# _edMplMonotonicGateRecordAccept ordering cursor / _lastFullRenderSource render-source
# diagnostic, neither of which exists in the new console's simpler poll model (grepped
# static/js/*.js, zero matches for either name).


def test_client_ticker_switch_resets_expiry_scope() -> None:
    """The real invariant this protected -- a ticker switch must not carry the prior ticker's
    expiry scope into the new ticker's requests (AAPL wedge, audit 2026-07-04) -- has a live
    equivalent: ed-core.js's setTicker() clears the shared selection and reloads expiries fresh
    for the new ticker on every switch, so there is no stale-select DOM to carry over at all."""
    core = (ROOT / "static" / "js" / "ed-core.js").read_text(encoding="utf-8")
    marker = "function setTicker(sym) {"
    assert marker in core, "setTicker not found in ed-core.js"
    body = core[core.index(marker) : core.index(marker) + 2200]
    assert "state.selStrike = null; state.selExpiry = null;" in body, (
        "ticker switch no longer resets the shared strike/expiry selection — the prior "
        "ticker's scope can carry into the new ticker's requests (AAPL wedge, audit "
        "2026-07-04)."
    )
    assert "loadExpiries(state.ticker);" in body, (
        "ticker switch no longer reloads expiries for the new ticker"
    )
    assert body.index("state.selStrike = null; state.selExpiry = null;") < body.index(
        "loadExpiries(state.ticker);"
    ), "selection reset happens after (not before) the new ticker's expiry reload"
