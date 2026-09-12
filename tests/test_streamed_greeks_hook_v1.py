"""set_streamed_greeks_hook / _replay_option_contract_rows (app/options/order_flow/streaming.py):
the hook that lets a consumer (server.py's gamma-surface cache) learn the instant a streamed
option L1 tick carries new GAMMA/DELTA/OPEN_INTEREST, instead of only via the slow poll of
OrderFlowState. Same shape/precedent as the existing `_on_tick_callback`. Proven against the
REAL replay path (_replay_option_contract_rows reading real stream_capture.db rows written by
CaptureWriter), not a reimplementation of its dispatch logic."""
from __future__ import annotations

import asyncio
import time

import app.options.order_flow.state as ofls
import app.options.order_flow.streaming as ofs
from stream_spine import CaptureWriter, options_quote_msg

_SPY_CONTRACT = "SPY   260820C00767000"

#: Real content shape (reports/of_capability_probe/options_20260820T1354Z/), same fixture the
#: existing options order-flow semantics tests use.
_REAL_LEVELONE_OPTIONS_CONTENT = {
    "key": _SPY_CONTRACT, "assetMainType": "OPTION", "BID_PRICE": 1.26, "ASK_PRICE": 1.28,
    "LAST_PRICE": 1.27, "LAST_SIZE": 2, "BID_SIZE": 458, "ASK_SIZE": 209,
    "TOTAL_VOLUME": 44994, "TRADE_TIME_MILLIS": 1787234092319, "OPEN_INTEREST": 2097,
    "DELTA": 0.45644607, "CONTRACT_TYPE": "C", "UNDERLYING": "SPY",
}
_BID_ASK_ONLY_CONTENT = {
    "key": _SPY_CONTRACT, "assetMainType": "OPTION", "BID_PRICE": 1.30, "ASK_PRICE": 1.32,
    "LAST_PRICE": 1.31, "LAST_SIZE": 1, "TRADE_TIME_MILLIS": 1787234093000,
}


def _reset(tmp_path, monkeypatch):
    ofs._feed_running = False
    ofs._active_option_contract = None
    ofs._option_l1_cursor = {}
    ofs._option_book_cursor = {}
    ofs._streamed_greeks_hook = None
    ofls.clear_all_live_state()
    db = tmp_path / "stream_capture.db"
    monkeypatch.setattr(ofs, "STREAM_DB_DEFAULT", db)
    monkeypatch.delenv("STREAM_CAPTURE_DB_PATH", raising=False)
    monkeypatch.setattr(
        "app.options.contracts.default.default_option_contract",
        lambda *a, **k: None,
    )
    return db


def _write_option_l1_row(db, symbol, content, ts_recv):
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    w.insert(f"optquote.{symbol}", options_quote_msg(
        symbol=symbol, content=content, src="schwab_options_l1", ts_recv=ts_recv))
    w.commit()
    w.close()


def test_set_streamed_greeks_hook_registers_and_clears():
    calls = []
    ofs.set_streamed_greeks_hook(lambda sym, ts: calls.append((sym, ts)))
    assert ofs._streamed_greeks_hook is not None
    ofs.set_streamed_greeks_hook(None)
    assert ofs._streamed_greeks_hook is None


def test_replay_returns_the_qualifying_ts_on_a_tick_carrying_greeks_or_open_interest(tmp_path, monkeypatch):
    """_replay_option_contract_rows no longer calls the hook itself (see _feed_loop, which
    now coalesces the hook call across every desired contract replayed in one poll tick,
    not just across one contract's own rows) -- it only REPORTS its own freshest qualifying
    ts_recv back to the caller. This is that contract, proven directly."""
    db = _reset(tmp_path, monkeypatch)
    _write_option_l1_row(db, _SPY_CONTRACT, _REAL_LEVELONE_OPTIONS_CONTENT, ts_recv=1700000000.0)
    con = ofs._open_capture_db_readonly(db)
    result = ofs._replay_option_contract_rows(con, _SPY_CONTRACT)
    con.close()
    assert result == 1700000000.0


def test_replay_returns_none_on_a_bid_ask_only_tick(tmp_path, monkeypatch):
    """A tick with no GAMMA/DELTA/OPEN_INTEREST at all is not worth an eager recompute --
    nothing changed that the exposure formula reads."""
    db = _reset(tmp_path, monkeypatch)
    _write_option_l1_row(db, _SPY_CONTRACT, _BID_ASK_ONLY_CONTENT, ts_recv=1700000000.0)
    con = ofs._open_capture_db_readonly(db)
    result = ofs._replay_option_contract_rows(con, _SPY_CONTRACT)
    con.close()
    assert result is None


def test_replay_returns_the_qualifying_ts_on_a_volume_only_tick_with_no_greeks_present(tmp_path, monkeypatch):
    """Independent-review finding (2026-09-12): 'the current hook is triggered by
    GAMMA/DELTA/OPEN_INTEREST; that does not complete volume-only update delivery.' A tick
    that carries ONLY TOTAL_VOLUME (no Greeks/OI at all) must still qualify, since
    _per_strike's volume column and compute_exposures_by_strike's own volume aggregation both
    read a contract's totalVolume directly."""
    db = _reset(tmp_path, monkeypatch)
    volume_only = dict(_BID_ASK_ONLY_CONTENT, TOTAL_VOLUME=54321)
    _write_option_l1_row(db, _SPY_CONTRACT, volume_only, ts_recv=1700000000.0)
    con = ofs._open_capture_db_readonly(db)
    result = ofs._replay_option_contract_rows(con, _SPY_CONTRACT)
    con.close()
    assert result == 1700000000.0


def test_no_hook_registered_does_not_break_the_replay(tmp_path, monkeypatch):
    """The default (unregistered) state -- must not raise or skip the ordinary push_level_one."""
    db = _reset(tmp_path, monkeypatch)
    _write_option_l1_row(db, _SPY_CONTRACT, _REAL_LEVELONE_OPTIONS_CONTENT, ts_recv=1700000000.0)
    assert ofs._streamed_greeks_hook is None
    con = ofs._open_capture_db_readonly(db)
    ofs._replay_option_contract_rows(con, _SPY_CONTRACT)
    con.close()
    items = ofls.get_content_for_symbol(_SPY_CONTRACT)
    assert any(i.get("LAST_PRICE") == 1.27 for i in items)


def test_a_burst_of_rows_in_one_poll_batch_reports_exactly_one_qualifying_ts(tmp_path, monkeypatch):
    """Independent-review finding (2026-09-12), REPRODUCED then fixed: calling the hook once
    PER ROW meant a burst of N rows landing in one poll batch triggered N sequential expensive
    recomputes on the consumer side. Three rows are written here BEFORE the daemon ever
    replays them (simulating a burst that accumulated between poll ticks, a real shape:
    CaptureWriter and the replay poll are independent), so ONE _replay_option_contract_rows
    call sees all three in a single query -- proving it reports exactly ONE qualifying
    ts_recv for the whole batch (the caller fires the hook at most once from it), stamped
    with the FRESHEST row, while EVERY row still lands in OrderFlowState (nothing is
    dropped from the state itself, only the expensive recompute is coalesced)."""
    db = _reset(tmp_path, monkeypatch)
    _write_option_l1_row(db, _SPY_CONTRACT, dict(_REAL_LEVELONE_OPTIONS_CONTENT, GAMMA=0.01), ts_recv=1700000000.0)
    _write_option_l1_row(db, _SPY_CONTRACT, dict(_REAL_LEVELONE_OPTIONS_CONTENT, GAMMA=0.02), ts_recv=1700000001.0)
    _write_option_l1_row(db, _SPY_CONTRACT, dict(_REAL_LEVELONE_OPTIONS_CONTENT, GAMMA=0.03), ts_recv=1700000002.0)

    con = ofs._open_capture_db_readonly(db)
    result = ofs._replay_option_contract_rows(con, _SPY_CONTRACT)  # ONE call sees all three rows
    con.close()

    assert result == 1700000002.0, (
        "exactly one qualifying ts_recv for the whole batch, the FRESHEST row's ts_recv"
    )
    # every row still reached OrderFlowState -- push_level_one ran for all three, the LATEST
    # (gamma=0.03) is what a consumer reading state now sees, nothing from the batch was lost
    assert ofls.get_stream_greeks(_SPY_CONTRACT)["gamma"] == 0.03


def test_a_batch_with_no_qualifying_rows_reports_none(tmp_path, monkeypatch):
    db = _reset(tmp_path, monkeypatch)
    _write_option_l1_row(db, _SPY_CONTRACT, _BID_ASK_ONLY_CONTENT, ts_recv=1700000000.0)
    _write_option_l1_row(db, _SPY_CONTRACT, dict(_BID_ASK_ONLY_CONTENT, LAST_PRICE=1.35), ts_recv=1700000001.0)

    con = ofs._open_capture_db_readonly(db)
    result = ofs._replay_option_contract_rows(con, _SPY_CONTRACT)
    con.close()
    assert result is None


def test_a_batch_with_one_qualifying_row_among_several_reports_that_rows_ts(tmp_path, monkeypatch):
    """A qualifying row in the MIDDLE of a batch (not the last row overall) must still be the
    one whose ts_recv is reported -- 'freshest QUALIFYING row', not 'last row in the batch'."""
    db = _reset(tmp_path, monkeypatch)
    _write_option_l1_row(db, _SPY_CONTRACT, _BID_ASK_ONLY_CONTENT, ts_recv=1700000000.0)
    _write_option_l1_row(db, _SPY_CONTRACT, dict(_REAL_LEVELONE_OPTIONS_CONTENT, GAMMA=0.05), ts_recv=1700000001.0)
    _write_option_l1_row(db, _SPY_CONTRACT, dict(_BID_ASK_ONLY_CONTENT, LAST_PRICE=1.40), ts_recv=1700000002.0)

    con = ofs._open_capture_db_readonly(db)
    result = ofs._replay_option_contract_rows(con, _SPY_CONTRACT)
    con.close()
    assert result == 1700000001.0


# ─────────────────────────────────────────────────────────────────────────────
# Independent-review finding (2026-09-12), performance-assurance critique: the coalescing
# fix above was justified in comments by a fixed "~3.1s per call, 9.3s for three calls"
# figure, with no reproducible benchmark in the repo to back it, and the tests above only
# ever prove CALL COUNT ("fires once, not three times") -- which establishes a repeated-
# computation OPPORTUNITY existed, not actual production latency saved. This test measures
# the REAL thing: server.py's own production hook (refresh_gamma_surface_from_stream,
# wired exactly as server.py's startup registers it -- see set_streamed_greeks_hook call
# site), run against a SYNTHETIC SCALE BASELINE sized to a genuine full SPXW-class book,
# with the app's own wall clock, end to end through the real replay path.
# ─────────────────────────────────────────────────────────────────────────────

async def _wait_until(predicate, *, timeout_sec, step=0.05, what=""):
    """Poll `predicate` until it is True, or raise AssertionError on timeout -- never
    silently declares completion. Independent-review finding (2026-09-12), REPRODUCED:
    the original version of this wait used an IDLE-DETECTED heuristic ('no new hook call
    for ~1s') instead of a deterministic completion signal -- since hook_calls.append()
    fires at the START of a slow hook call (before it blocks on the real, ~1-2.5s
    projection), a single still-in-flight call already looks 'idle' by that heuristic,
    so the wait could conclude 'done, 1 call' while a buggy implementation's 2nd/3rd
    calls were still queued behind the first and had not even started yet -- reproduced
    directly: an isolated probe with a deliberately slow hook against the PRE-fix
    per-contract-hook-calling loop stopped after only ONE of three contracts had been
    processed, yet the old heuristic's call-count and timing assertions still passed.
    Every wait below is anchored to an EXPLICIT, unambiguous signal (a symbol having
    actually been replayed; a hook call having actually started and finished) instead."""
    waited = 0.0
    while waited < timeout_sec:
        if predicate():
            return
        await asyncio.sleep(step)
        waited += step
    raise AssertionError(f"timed out after {timeout_sec:.1f}s waiting for: {what}")


def _drain_l1_sse_thread_queue():
    """refresh_gamma_surface_from_stream -> _next_gamma_surface_seq pushes a
    gamma_surface_seq SSE notify through server._l1_sse_thread_queue -- a module-level
    GLOBAL queue shared by every test in the process (see
    tests/test_gamma_surface_stream_refresh_v1.py's identical helper and its own
    cross-test-leak finding: an undrained entry here was FIFO-popped by
    tests/test_l1_light_sse.py::test_notify_enqueues_when_subscribed as if it were that
    test's own fresh notification). Drained before AND after the real-hook benchmark
    below, which is the one test in this file that calls the REAL production hook and so
    is the one test in this file that can push into this queue at all."""
    import server as srv
    while not srv._l1_sse_thread_queue.empty():
        try:
            srv._l1_sse_thread_queue.get_nowait()
        except Exception:
            break


def _synthetic_full_book_contracts(n_expiries=42, n_strikes=500):
    """SYNTHETIC SCALE BASELINE -- not real captured data, and not claimed to be. Sized to
    match the "42,000 contracts, 42x500" full SPXW-class book this repo's own comments have
    historically cited (42 expiries x 500 strikes x 2 sides), so a benchmark against it
    reflects the actual worst-case shape the per-batch hook-coalescing fix exists to bound.
    Every field compute_exposures_by_strike/project_gamma_surface reads is populated with a
    plausible, finite, in-range value (nonzero OI, small OTM-to-ATM gamma, a delta spread
    that stays clear of the deep-ITM/OTM gamma-plausibility guard) -- not zeros or None,
    which would let this app's own quality gates (require_oi, gamma_is_plausible) skip most
    of the aggregate and understate the real per-call cost, exactly the vacuous-test trap
    the A-then-B overwrite tests (tests/test_gamma_surface_stream_refresh_v1.py) were found
    to have fallen into with too-thin synthetic inputs.

    # institutional-synthetic-ok: no real captured chain at genuine full SPXW scale
    # (~42,000 contracts) is committed under tests/fixtures/, and this benchmark's own
    # point is to measure cost at that exact scale with every quality-gate-relevant
    # field (OI, delta, gamma) deliberately in a plausible, non-degenerate range -- a
    # real fixture at this size would also need to be hand-verified for the same
    # properties, with no more provenance than a labeled synthetic one.
    """
    import datetime
    base = datetime.date(2026, 9, 18)
    contracts = []
    for e in range(n_expiries):
        expiry_dt = base + datetime.timedelta(days=e * 7)
        expiry = expiry_dt.strftime("%Y-%m-%dT20:00:00.000+00:00")
        dte = max(1, (expiry_dt - datetime.date(2026, 9, 11)).days)
        for s in range(n_strikes):
            strike = round(50.0 + s * 1.0, 2)
            frac = s / float(n_strikes)
            for side, delta in (("CALL", round(0.05 + 0.85 * frac, 3)),
                                 ("PUT", round(-0.90 + 0.85 * frac, 3))):
                contracts.append({
                    "symbol": "SYN%02d%04d%s" % (e, s, side[0]),
                    "putCall": side,
                    "strikePrice": strike,
                    "openInterest": 100 + (s * 7 + e * 13) % 4000,
                    "multiplier": 100.0,
                    "gamma": round(0.005 + 0.03 * ((s % 50) / 50.0), 5),
                    "delta": delta,
                    "totalVolume": (s * 3 + e) % 1500,
                    "volatility": round(20.0 + (s % 40), 2),
                    "expirationDate": expiry,
                    "daysToExpiration": dte,
                })
    return contracts


def test_hook_coalescing_avoids_the_real_per_call_cost_at_spxw_scale(tmp_path, monkeypatch):
    """Wires the REAL production hook against a real-scale synthetic book and measures its
    REAL wall-clock cost, proving end to end that a 3-row poll batch pays roughly ONE real
    call's worth of latency, not three -- the actual production claim, not a call count.

    # institutional-synthetic-ok: the appended _SPY_CONTRACT entry below must be a
    # MEMBER of the same synthetic-scale book _synthetic_full_book_contracts builds
    # (see that function's own institutional-synthetic-ok note) or
    # overlay_streamed_contract_fields finds nothing to overlay and this benchmark
    # short-circuits to zero real cost -- there is no real fixture at this contract's
    # exact identity inside a genuine 42,001-contract synthetic scale book.
    """
    import asyncio
    import time as _t

    import server as srv

    _drain_l1_sse_thread_queue()
    db = _reset(tmp_path, monkeypatch)
    tk = srv.ticker_storage_key("SPY")
    contracts = _synthetic_full_book_contracts()
    # Independent-review finding (2026-09-12), connected work: with MULTIPLE desired
    # contracts sharing one underlying (a primary plus additional -- RC-UI-3), _feed_loop
    # itself is the real site of redundant hook firing (see its own comment), not just a
    # single contract's own row burst. Three real, distinct, OSI-shaped SPY contracts --
    # not the "SYN..." placeholder symbols _synthetic_full_book_contracts generates --
    # must be genuine MEMBERS of the REST baseline (vendor_option_root("SPY...") groups
    # them together) or overlay_streamed_contract_fields finds nothing to overlay and the
    # real hook short-circuits to "no_change" before running the real projection cost.
    _CONTRACT_A = "SPY   260918C00600000"
    _CONTRACT_B = "SPY   260918C00610000"
    _CONTRACT_C = "SPY   260918C00620000"
    for sym, strike in ((_CONTRACT_A, 600.0), (_CONTRACT_B, 610.0), (_CONTRACT_C, 620.0)):
        contracts = contracts + [{
            "symbol": sym, "putCall": "CALL", "strikePrice": strike,
            "openInterest": 2097, "multiplier": 100.0, "gamma": 0.018, "delta": 0.5,
            "totalVolume": 4000, "volatility": 22.0,
            "expirationDate": "2026-09-18T20:00:00.000+00:00", "daysToExpiration": 7,
        }]
    spot = 400.0
    with srv._terrain_cache_lock:
        srv._terrain_cache[tk] = {
            "_contracts_rest": contracts,
            "_contracts_rest_spot": spot,
            "_contracts_rest_computed_ts": _t.time() - 30.0,
        }
    srv._gamma_surface_seq.pop(tk, None)
    try:
        # Baseline: measure ONE real call's cost directly against the real consumer.
        def _stream_greeks_one(sym):
            return {"gamma": 0.02, "gamma_ts_recv": _t.time()} if sym == _CONTRACT_A else None
        monkeypatch.setattr("app.options.order_flow.state.get_stream_greeks", _stream_greeks_one)
        ofs._active_option_contract = ofs.ticker_storage_key(_CONTRACT_A)

        t0 = _t.perf_counter()
        status = srv.refresh_gamma_surface_from_stream(_CONTRACT_A, _t.time())
        one_call_sec = _t.perf_counter() - t0
        assert status == "ok", (
            f"benchmark call must actually run the real projection, not short-circuit: {status}")
        print(f"[perf] refresh_gamma_surface_from_stream, {len(contracts)}-contract "
              f"synthetic SPXW-scale book: {one_call_sec * 1000:.1f} ms/call")
        with srv._terrain_cache_lock:
            baseline_surface = srv._terrain_cache[tk]["_gamma_surface"]
        seq_before_batch = baseline_surface["surface_seq"]
        assert baseline_surface["stream_overlay_contracts"] == 1   # only A, at this point

        # Reset the REST generation so the real _feed_loop run below is a fresh, comparable
        # compute-and-publish, not a "stale_baseline_superseded" no-op.
        with srv._terrain_cache_lock:
            srv._terrain_cache[tk]["_contracts_rest_computed_ts"] = _t.time() - 30.0

        # The real proof: THREE DISTINCT CONTRACTS (primary A, additional B and C -- all
        # sharing the SPY root) each get one fresh qualifying L1 row BEFORE one real
        # _feed_loop poll tick runs. A counting wrapper around the REAL production hook
        # measures how many times it actually fires (and tracks START vs FINISH
        # separately -- see _wait_until's own comment on why a call-count alone, sampled
        # on a timer, is not a safe completion signal); a spy on the REAL
        # _replay_option_contract_rows marks when each contract has actually been
        # replayed, giving a deterministic "this tick's per-contract work is done"
        # signal independent of how long the (possibly still-running) hook call takes.
        ofs._active_option_contract = ofs.ticker_storage_key(_CONTRACT_A)
        ofs._active_option_contracts = [ofs.ticker_storage_key(_CONTRACT_B), ofs.ticker_storage_key(_CONTRACT_C)]
        live = {_CONTRACT_A: {"gamma": 0.03, "gamma_ts_recv": _t.time()},
                _CONTRACT_B: {"gamma": 0.04, "gamma_ts_recv": _t.time()},
                _CONTRACT_C: {"gamma": 0.05, "gamma_ts_recv": _t.time()}}
        monkeypatch.setattr("app.options.order_flow.state.get_stream_greeks", lambda sym: live.get(sym))

        replayed = []
        real_replay = ofs._replay_option_contract_rows

        def _spy_replay(con, sym):
            result = real_replay(con, sym)
            replayed.append(sym)
            return result
        monkeypatch.setattr(ofs, "_replay_option_contract_rows", _spy_replay)

        hook_started, hook_finished = [], []
        real_hook = srv.refresh_gamma_surface_from_stream

        def _counting_hook(sym, ts):
            hook_started.append(sym)
            try:
                return real_hook(sym, ts)
            finally:
                hook_finished.append(sym)
        ofs.set_streamed_greeks_hook(_counting_hook)
        for sym in (_CONTRACT_A, _CONTRACT_B, _CONTRACT_C):
            _write_option_l1_row(db, sym, dict(_REAL_LEVELONE_OPTIONS_CONTENT, key=sym, GAMMA=0.05), ts_recv=1700000000.0)

        async def _run_one_tick():
            ofs._feed_running = True
            t0 = _t.perf_counter()
            task = asyncio.get_event_loop().create_task(ofs._feed_loop())
            # DETERMINISTIC completion, not a timer-sampled heuristic (see _wait_until):
            # (1) all three contracts have actually been replayed at least once -- proves
            #     this tick's per-contract work genuinely finished, regardless of how the
            #     hook is invoked; (2) every hook call that started has also finished --
            #     proves no hook work is still silently in flight when we measure.
            await _wait_until(lambda: len(set(replayed)) >= 3,
                              timeout_sec=max(15.0, one_call_sec * 4.0 + 5.0),
                              what="all three contracts to be replayed at least once")
            await _wait_until(lambda: len(hook_started) >= 1 and len(hook_started) == len(hook_finished),
                              timeout_sec=one_call_sec * 3.0 + 5.0,
                              what="every started hook call to finish")
            elapsed = _t.perf_counter() - t0
            ofs._feed_running = False
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            return elapsed

        tick_sec = asyncio.run(_run_one_tick())
        ofs.set_streamed_greeks_hook(None)
        print(f"[perf] one _feed_loop poll tick, 3 desired contracts each qualifying, real "
              f"hook wired: {tick_sec * 1000:.1f} ms total, hook fired {len(hook_started)}x "
              f"(one-call baseline was {one_call_sec * 1000:.1f} ms)")

        assert len(hook_started) == 1, (
            f"3 contracts each ticking in the SAME poll iteration must fire the real "
            f"whole-surface hook ONCE, not {len(hook_started)} times -- refresh_gamma_surface_"
            f"from_stream's own _desired_stream_greeks_for_ticker already re-gathers every "
            f"desired contract fresh on every call, so any call before the last is pure "
            f"waste: {hook_started}")
        # every contract's row still reached OrderFlowState -- no captured event lost by
        # moving the hook invocation up to _feed_loop
        for sym in (_CONTRACT_A, _CONTRACT_B, _CONTRACT_C):
            assert ofls.get_stream_greeks(sym) is not None, f"{sym}'s row must still reach OrderFlowState"

        # Independent-review finding (2026-09-12), REPRODUCED: "the benchmark reads a
        # prefilled mock for contract state and accepts a surface created before the
        # measured batch" -- disabling the hook entirely left this test's OLD assertion
        # (`stream_overlay_contracts >= 1`) trivially satisfied by the EARLIER baseline
        # call's leftover publication, proving nothing about the batch itself. Fixed:
        # require a NEW publication generation (surface_seq strictly greater than the
        # baseline's) AND that its overlay count reflects ALL THREE batch contracts, not
        # the baseline's one -- both are impossible to satisfy from stale leftover state.
        with srv._terrain_cache_lock:
            published = srv._terrain_cache[tk]["_gamma_surface"]
        assert published is not None
        assert published["surface_seq"] > seq_before_batch, (
            f"the coalesced tick must publish a NEW surface generation "
            f"({published.get('surface_seq')}) strictly after the baseline's "
            f"({seq_before_batch}) -- otherwise this is reading stale leftover state, not "
            f"proof the batch itself published anything")
        assert published["stream_overlay_contracts"] == 3, (
            f"the coalesced publication must reflect ALL THREE batch contracts (A, B, C), "
            f"not the baseline's one alone; got stream_overlay_contracts="
            f"{published.get('stream_overlay_contracts')}")
        # Generous 2x ceiling (not a tight SLA) -- this only fails if coalescing regresses
        # toward one hook call per contract (which would cost close to 3x one_call_sec).
        assert tick_sec < one_call_sec * 2.0 + 1.0, (
            f"one poll tick with 3 qualifying contracts cost {tick_sec * 1000:.1f} ms -- "
            f"close to 3x one real call's {one_call_sec * 1000:.1f} ms, suggesting the hook "
            f"fired more than once for this tick")
    finally:
        ofs.set_streamed_greeks_hook(None)
        ofs._active_option_contract = None
        ofs._active_option_contracts = []
        with srv._terrain_cache_lock:
            srv._terrain_cache.pop(tk, None)
        srv._gamma_surface_seq.pop(tk, None)
        _drain_l1_sse_thread_queue()


def test_disabling_the_hook_leaves_no_fresh_multi_contract_publication(tmp_path, monkeypatch):
    """The direct control for the benchmark above's freshness assertions: independent
    review disabled the batch-publication callback (the hook) entirely and found the
    OLD assertion set (`stream_overlay_contracts >= 1`, satisfied by ANY prior
    publication) still passed -- proving those assertions established nothing about the
    batch itself. This test proves the NEW assertions (surface_seq strictly increases;
    stream_overlay_contracts reflects every batch contract) correctly FAIL under that
    exact disabled-hook condition, so the benchmark's freshness checks are not vacuous.

    # institutional-synthetic-ok: a minimal single-contract REST baseline, built inline
    # for exactly this control's purpose (proving an assertion correctly fails) -- no
    # real fixture is needed or more informative than one deliberately simple contract.
    """
    import server as srv

    _drain_l1_sse_thread_queue()
    db = _reset(tmp_path, monkeypatch)
    tk = srv.ticker_storage_key("SPY")
    _CONTRACT_A = "SPY   260918C00600000"
    with srv._terrain_cache_lock:
        srv._terrain_cache[tk] = {
            "_contracts_rest": [{
                "symbol": _CONTRACT_A, "putCall": "CALL", "strikePrice": 600.0,
                "openInterest": 2097, "multiplier": 100.0, "gamma": 0.018, "delta": 0.5,
                "expirationDate": "2026-09-18T20:00:00.000+00:00", "daysToExpiration": 7,
            }],
            "_contracts_rest_spot": 400.0,
            "_contracts_rest_computed_ts": time.time() - 30.0,
        }
    srv._gamma_surface_seq.pop(tk, None)
    try:
        monkeypatch.setattr("app.options.order_flow.state.get_stream_greeks",
                            lambda sym: {"gamma": 0.02, "gamma_ts_recv": time.time()} if sym == _CONTRACT_A else None)
        ofs._active_option_contract = ofs.ticker_storage_key(_CONTRACT_A)
        status = srv.refresh_gamma_surface_from_stream(_CONTRACT_A, time.time())
        assert status == "ok"
        with srv._terrain_cache_lock:
            seq_before = srv._terrain_cache[tk]["_gamma_surface"]["surface_seq"]

        # The hook is NEVER wired (set_streamed_greeks_hook is never called) -- this
        # models "the batch-publication callback is disabled". A fresh qualifying L1 row
        # for A lands, but with no hook, nothing consumes it into a new publication.
        _write_option_l1_row(db, _CONTRACT_A, dict(_REAL_LEVELONE_OPTIONS_CONTENT, key=_CONTRACT_A, GAMMA=0.09),
                             ts_recv=1700000000.0)
        con = ofs._open_capture_db_readonly(db)
        ofs._replay_option_contract_rows(con, _CONTRACT_A)
        con.close()

        with srv._terrain_cache_lock:
            after = srv._terrain_cache[tk]["_gamma_surface"]
        assert after["surface_seq"] == seq_before, (
            "sanity: with the hook disabled, no new surface generation is published")
        # THE proof: an assertion requiring a NEW generation correctly FAILS here.
        try:
            assert after["surface_seq"] > seq_before, "expected to fail: no new publication"
        except AssertionError:
            pass
        else:
            raise AssertionError(
                "the freshness assertion (surface_seq strictly increases) must FAIL when "
                "the hook is disabled -- it did not, so it cannot be trusted to catch a "
                "genuinely missing publication either")
    finally:
        ofs._active_option_contract = None
        with srv._terrain_cache_lock:
            srv._terrain_cache.pop(tk, None)
        srv._gamma_surface_seq.pop(tk, None)
        _drain_l1_sse_thread_queue()


def test_hook_fires_once_per_underlying_when_two_underlyings_qualify_in_one_tick(tmp_path, monkeypatch):
    """Architecture-judgment control: the vendor-root grouping in _feed_loop must not
    over-coalesce across GENUINELY DIFFERENT underlyings sharing one poll tick -- two
    SPY contracts and one QQQ contract qualifying together must fire the hook exactly
    TWICE (once per underlying), not once (wrongly merging distinct terrain-cache
    entries) and not three times (falling back to the pre-fix per-contract behavior).

    # institutional-synthetic-ok: two minimal, distinct-underlying REST baselines built
    # inline for exactly this control's purpose (two real SPY strikes, one real QQQ
    # strike, at a scale this specific grouping proof needs) -- no real fixture would be
    # more informative than these deliberately simple, clearly-labeled contracts.
    """
    import server as srv

    _drain_l1_sse_thread_queue()
    db = _reset(tmp_path, monkeypatch)
    spy_tk = srv.ticker_storage_key("SPY")
    qqq_tk = srv.ticker_storage_key("QQQ")
    _SPY_A = "SPY   260918C00600000"
    _SPY_B = "SPY   260918C00610000"
    _QQQ_A = "QQQ   260918C00500000"
    with srv._terrain_cache_lock:
        srv._terrain_cache[spy_tk] = {
            "_contracts_rest": [
                {"symbol": _SPY_A, "putCall": "CALL", "strikePrice": 600.0, "openInterest": 500,
                 "multiplier": 100.0, "gamma": 0.02, "delta": 0.5,
                 "expirationDate": "2026-09-18T20:00:00.000+00:00", "daysToExpiration": 7},
                {"symbol": _SPY_B, "putCall": "CALL", "strikePrice": 610.0, "openInterest": 500,
                 "multiplier": 100.0, "gamma": 0.02, "delta": 0.5,
                 "expirationDate": "2026-09-18T20:00:00.000+00:00", "daysToExpiration": 7},
            ],
            "_contracts_rest_spot": 400.0, "_contracts_rest_computed_ts": time.time() - 30.0,
        }
        srv._terrain_cache[qqq_tk] = {
            "_contracts_rest": [
                {"symbol": _QQQ_A, "putCall": "CALL", "strikePrice": 500.0, "openInterest": 500,
                 "multiplier": 100.0, "gamma": 0.02, "delta": 0.5,
                 "expirationDate": "2026-09-18T20:00:00.000+00:00", "daysToExpiration": 7},
            ],
            "_contracts_rest_spot": 300.0, "_contracts_rest_computed_ts": time.time() - 30.0,
        }
    srv._gamma_surface_seq.pop(spy_tk, None)
    srv._gamma_surface_seq.pop(qqq_tk, None)
    try:
        live = {_SPY_A: {"gamma": 0.05, "gamma_ts_recv": time.time()},
                _SPY_B: {"gamma": 0.06, "gamma_ts_recv": time.time()},
                _QQQ_A: {"gamma": 0.07, "gamma_ts_recv": time.time()}}
        monkeypatch.setattr("app.options.order_flow.state.get_stream_greeks", lambda sym: live.get(sym))
        ofs._active_option_contract = ofs.ticker_storage_key(_SPY_A)
        ofs._active_option_contracts = [ofs.ticker_storage_key(_SPY_B), ofs.ticker_storage_key(_QQQ_A)]

        replayed = []
        real_replay = ofs._replay_option_contract_rows

        def _spy_replay(con, sym):
            result = real_replay(con, sym)
            replayed.append(sym)
            return result
        monkeypatch.setattr(ofs, "_replay_option_contract_rows", _spy_replay)

        hook_started, hook_finished = [], []
        real_hook = srv.refresh_gamma_surface_from_stream

        def _counting_hook(sym, ts):
            hook_started.append(sym)
            try:
                return real_hook(sym, ts)
            finally:
                hook_finished.append(sym)
        ofs.set_streamed_greeks_hook(_counting_hook)
        for sym in (_SPY_A, _SPY_B, _QQQ_A):
            _write_option_l1_row(db, sym, dict(_REAL_LEVELONE_OPTIONS_CONTENT, key=sym, GAMMA=0.08), ts_recv=1700000000.0)

        async def _run_one_tick():
            ofs._feed_running = True
            task = asyncio.get_event_loop().create_task(ofs._feed_loop())
            await _wait_until(lambda: len(set(replayed)) >= 3, timeout_sec=15.0,
                              what="all three contracts (2 SPY, 1 QQQ) to be replayed at least once")
            await _wait_until(lambda: len(hook_started) >= 2 and len(hook_started) == len(hook_finished),
                              timeout_sec=15.0, what="both underlyings' hook calls to finish")
            ofs._feed_running = False
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        asyncio.run(_run_one_tick())
        ofs.set_streamed_greeks_hook(None)

        assert len(hook_started) == 2, (
            f"two SPY contracts + one QQQ contract qualifying in the same tick must fire "
            f"the hook exactly twice (once per underlying), not {len(hook_started)}: "
            f"{hook_started}")
        with srv._terrain_cache_lock:
            spy_pub = srv._terrain_cache[spy_tk]["_gamma_surface"]
            qqq_pub = srv._terrain_cache[qqq_tk]["_gamma_surface"]
        assert spy_pub is not None and spy_pub["stream_overlay_contracts"] == 2, (
            "SPY's publication must reflect BOTH its own contracts")
        assert qqq_pub is not None and qqq_pub["stream_overlay_contracts"] == 1, (
            "QQQ's publication must reflect its own contract, independent of SPY's")
    finally:
        ofs.set_streamed_greeks_hook(None)
        ofs._active_option_contract = None
        ofs._active_option_contracts = []
        with srv._terrain_cache_lock:
            srv._terrain_cache.pop(spy_tk, None)
            srv._terrain_cache.pop(qqq_tk, None)
        srv._gamma_surface_seq.pop(spy_tk, None)
        srv._gamma_surface_seq.pop(qqq_tk, None)
        _drain_l1_sse_thread_queue()
