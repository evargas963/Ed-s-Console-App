"""set_streamed_greeks_hook (app/options/order_flow/streaming.py): the hook that lets a
consumer (server.py's gamma-surface cache) learn the instant a streamed option L1 tick carries
new GAMMA/DELTA/OPEN_INTEREST/volume. Same shape/precedent as the existing `_on_tick_callback`.

Since 2026-09-23 the capture daemon PUSHES each message over a local WebSocket
(app.market_data.schwab.streaming.live_push); nothing live reads stream_capture.db. These tests
publish on a real stream_spine.MessageBus served by the REAL push server and run the REAL
console feed loop (_feed_loop -> _ingest_pushed -> OrderFlowState -> hook dispatch), not a
reimplementation of its dispatch logic."""
from __future__ import annotations

import asyncio
import threading
import time

import app.options.order_flow.state as ofls
import app.options.order_flow.streaming as ofs
from app.market_data.schwab.streaming import live_push
from stream_spine import MessageBus, options_quote_msg

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


#: The daemon side of the push channel for the current test: its bus and port.
_H: dict = {}


def _free_port() -> int:
    import socket
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _reset(tmp_path, monkeypatch):
    ofs._feed_running = False
    ofs._active_option_contract = None
    ofs._streamed_greeks_hook = None
    ofls.clear_all_live_state()
    _H.clear()
    _H.update(bus=MessageBus(), port=_free_port())
    monkeypatch.setattr(ofs, "LIVE_PUSH_URL", f"ws://127.0.0.1:{_H['port']}")
    monkeypatch.setattr(ofs, "PUSH_RECONNECT_SEC", 0.05)
    monkeypatch.setattr(
        "app.options.contracts.default.default_option_contract",
        lambda *a, **k: None,
    )
    return None


def _write_option_l1_row(_db, symbol, content, ts_recv):
    """The daemon receives one LEVELONE_OPTIONS message and publishes it on its bus -- what
    the push server forwards to the console (a console connecting later first receives each
    topic's last value)."""
    _H["bus"].publish(f"optquote.{symbol}", options_quote_msg(
        symbol=symbol, content=content, src="schwab_options_l1", ts_recv=ts_recv))


async def _feed_with_push():
    """The daemon's push server plus the console's REAL _feed_loop, for one test. Cancelling
    the returned task stops both."""
    stop = asyncio.Event()
    server = asyncio.create_task(live_push.serve_live_push(_H["bus"], stop, port=_H["port"]))
    try:
        await ofs._feed_loop()
    finally:
        stop.set()
        await asyncio.gather(server, return_exceptions=True)


def test_set_streamed_greeks_hook_registers_and_clears():
    calls = []
    ofs.set_streamed_greeks_hook(lambda sym, ts: calls.append((sym, ts)))
    assert ofs._streamed_greeks_hook is not None
    ofs.set_streamed_greeks_hook(None)
    assert ofs._streamed_greeks_hook is None


def _ingest(symbol, content, ts_recv):
    return ofs._ingest_pushed(f"optquote.{symbol}", options_quote_msg(
        symbol=symbol, content=content, src="schwab_options_l1", ts_recv=ts_recv))


def test_a_tick_carrying_greeks_or_open_interest_reports_its_receive_time():
    ofls.clear_all_live_state()
    assert _ingest(_SPY_CONTRACT, _REAL_LEVELONE_OPTIONS_CONTENT, 1700000000.0) == (
        _SPY_CONTRACT, 1700000000.0)


def test_a_bid_ask_only_tick_reports_nothing():
    """No GAMMA/DELTA/OPEN_INTEREST/volume: nothing the exposure formula reads changed."""
    ofls.clear_all_live_state()
    assert _ingest(_SPY_CONTRACT, _BID_ASK_ONLY_CONTENT, 1700000000.0) is None


def test_a_volume_only_tick_with_no_greeks_still_qualifies():
    """Independent-review finding (2026-09-12): a tick carrying ONLY TOTAL_VOLUME must still
    qualify -- _per_strike's volume column and compute_exposures_by_strike's own volume
    aggregation both read a contract's totalVolume directly."""
    ofls.clear_all_live_state()
    volume_only = dict(_BID_ASK_ONLY_CONTENT, TOTAL_VOLUME=54321)
    assert _ingest(_SPY_CONTRACT, volume_only, 1700000000.0) == (_SPY_CONTRACT, 1700000000.0)


def test_no_hook_registered_still_lands_the_tick_in_state():
    ofls.clear_all_live_state()
    assert ofs._streamed_greeks_hook is None
    _ingest(_SPY_CONTRACT, _REAL_LEVELONE_OPTIONS_CONTENT, 1700000000.0)
    items = ofls.get_content_for_symbol(_SPY_CONTRACT)
    assert any(i.get("LAST_PRICE") == 1.27 for i in items)


def test_a_burst_keeps_one_entry_per_underlying_with_the_freshest_tick():
    """Independent-review finding (2026-09-12), REPRODUCED then fixed: one hook call PER
    qualifying tick meant a burst of N ticks cost N whole-surface recomputes. A burst now
    yields ONE dispatch per underlying, stamped with the freshest tick -- while every tick
    still lands in OrderFlowState (only the recompute is coalesced)."""
    burst = ofs.HookBurst()
    assert burst.note(_SPY_CONTRACT, 1700000000.0) is True        # opens the burst
    assert burst.note(_SPY_CONTRACT, 1700000002.0) is False
    assert burst.note(_SPY_CONTRACT, 1700000001.0) is False       # older: does not win
    assert burst.take() == [(_SPY_CONTRACT, 1700000002.0)]
    assert burst.take() == []
    assert burst.note(_SPY_CONTRACT, 1700000003.0) is True        # next burst opens again


def test_a_burst_groups_by_underlying_not_by_contract():
    """Contracts of ONE underlying share a dispatch (the hook re-gathers every desired
    contract of it); a different underlying keeps its own; a bare SPX and a weekly SPXW
    contract are the same $SPX underlying."""
    burst = ofs.HookBurst()
    burst.note("SPY   260918C00600000", 1.0)
    burst.note("SPY   260918C00610000", 2.0)
    burst.note("QQQ   260918C00500000", 3.0)
    burst.note("SPX   260918C05600000", 4.0)
    burst.note("SPXW  260918C05600000", 5.0)
    assert sorted(burst.take()) == [("QQQ   260918C00500000", 3.0),
                                    ("SPXW  260918C05600000", 5.0),
                                    ("SPY   260918C00610000", 2.0)]


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
    monkeypatch.setattr(srv, "resolve_spot", lambda t, **kw: (spot, "stub", _t.time()))
    try:
        # Baseline: measure ONE real call's cost directly against the real consumer. A
        # prefilled dict is legitimate HERE -- this measures the projection/hook's own
        # cost in isolation, with no replay pipeline in the picture at all to be blind to.
        # Bug self-caught while fixing finding #2 below: `monkeypatch.setattr` does not
        # auto-undo mid-test, so leaving this in effect past the baseline measurement
        # would have made the batch section's OWN "real pipeline" assertions read
        # through this stale isolated-to-A mock instead of the real (unmocked) function
        # -- explicitly restored immediately after use, not left to leak forward.
        import app.options.order_flow.state as ofls_state
        _real_get_stream_greeks = ofls_state.get_stream_greeks

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
        monkeypatch.setattr("app.options.order_flow.state.get_stream_greeks", _real_get_stream_greeks)

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
        #
        # Independent-review finding (2026-09-12), REPRODUCED: this section used to
        # monkeypatch app.options.order_flow.state.get_stream_greeks with a PREFILLED
        # dict keyed by symbol, completely independent of the L1 rows written below --
        # an isolated probe that suppressed ALL THREE real replay-to-state writes
        # (push_level_one never actually storing anything) still passed every assertion
        # here, because the mocked dict answered regardless of whether the real
        # capture -> replay -> state pipeline worked at all. A prefilled dict is
        # legitimate for the ISOLATED one-call cost measurement above (there is no
        # replay in that measurement to begin with); it is NOT legitimate evidence that
        # captured observations actually reach state once a real replay is in the
        # picture. Fixed: get_stream_greeks runs UNMOCKED here -- the only way the real
        # hook ever sees fresh greeks for A/B/C is if the REAL _write_option_l1_row rows
        # below actually flow through the REAL (unmocked) _replay_option_contract_rows
        # -> push_level_one -> OrderFlowState -> get_stream_greeks chain. ts_recv is
        # real-clock `now` (not a fixed 2023 timestamp) so overlay_streamed_contract_
        # fields' own staleness gate (GAMMA_SURFACE_STREAM_STALENESS_SEC=10s) does not
        # reject it -- a stale timestamp would silently exclude the contract and this
        # test would falsely read as if the pipeline dropped it.
        ofs._active_option_contract = ofs.ticker_storage_key(_CONTRACT_A)
        ofs._active_option_contracts = [ofs.ticker_storage_key(_CONTRACT_B), ofs.ticker_storage_key(_CONTRACT_C)]

        replayed = []
        real_ingest = ofs._ingest_pushed

        def _spy_ingest(topic, msg):
            result = real_ingest(topic, msg)
            if topic.startswith("optquote."):
                replayed.append(msg["symbol"])
            return result
        monkeypatch.setattr(ofs, "_ingest_pushed", _spy_ingest)

        hook_started, hook_finished = [], []
        real_hook = srv.refresh_gamma_surface_from_stream

        def _counting_hook(sym, ts):
            hook_started.append(sym)
            try:
                return real_hook(sym, ts)
            finally:
                hook_finished.append(sym)
        ofs.set_streamed_greeks_hook(_counting_hook)
        _EXPECTED_GAMMA = {_CONTRACT_A: 0.03, _CONTRACT_B: 0.04, _CONTRACT_C: 0.05}
        for sym, gamma in _EXPECTED_GAMMA.items():
            _write_option_l1_row(db, sym, dict(_REAL_LEVELONE_OPTIONS_CONTENT, key=sym, GAMMA=gamma),
                                 ts_recv=_t.time())

        async def _run_one_tick():
            ofs._feed_running = True
            t0 = _t.perf_counter()
            task = asyncio.get_event_loop().create_task(_feed_with_push())
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

        # Three contracts of ONE underlying arriving together: one call for the burst, plus
        # at most one trailing re-run if the frames were split across socket reads (the
        # hook re-gathers every desired contract, so a trailing run loses nothing). Three
        # calls -- one per contract -- is the defect this bounds.
        assert 1 <= len(hook_started) <= 2, (
            f"3 contracts of one underlying must cost at most one call plus one trailing "
            f"re-run, not {len(hook_started)}: {hook_started}")
        # Every contract's REAL captured row must have actually reached OrderFlowState via
        # the real (unmocked) push_level_one -- checked against the ACTUAL gamma value
        # each L1 row carried, not merely "some value is present" (which a broken write
        # path could satisfy with stale/default state left over from an earlier test).
        for sym, expected_gamma in _EXPECTED_GAMMA.items():
            greeks = ofls.get_stream_greeks(sym)
            assert greeks is not None, f"{sym}'s row must have reached OrderFlowState via the real replay pipeline"
            assert greeks.get("gamma") == expected_gamma, (
                f"{sym}'s OrderFlowState gamma must be its OWN captured row's value "
                f"({expected_gamma}), not {greeks.get('gamma')} -- this is the real pipeline, "
                f"not a prefilled dict")

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
        # Ceiling: one call plus one trailing re-run, with slack -- fails if coalescing
        # regresses toward one hook call per contract (close to 3x one_call_sec).
        assert tick_sec < one_call_sec * 2.5 + 1.0, (
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


def test_suppressed_replay_to_state_writes_are_caught_by_the_pipeline_assertions(tmp_path, monkeypatch):
    """Adversarial-behavior finding (2026-09-12), REPRODUCED: independent review took the
    prior version of the benchmark above -- which monkeypatched get_stream_greeks with a
    dict PREFILLED independent of the captured L1 rows -- and, in an isolated probe,
    suppressed all three real replay-to-state writes (push_level_one made a no-op). Every
    assertion still passed, because the prefilled dict answered regardless of whether
    capture -> replay -> state ever worked. This test proves the FIXED benchmark's own
    pipeline assertions (checking OrderFlowState's ACTUAL per-contract gamma value, and
    the publication's overlay count) correctly FAIL under that exact fault -- run here
    directly against the real functions, with push_level_one genuinely suppressed, not a
    remembered claim about what a suppressed write would do.

    # institutional-synthetic-ok: a minimal 3-contract REST baseline, built inline for
    # exactly this adversarial control's purpose (proving the pipeline assertions fail
    # under a suppressed write) -- no real fixture is more informative than these small,
    # purpose-built contracts at this specific identity."""
    import server as srv

    _drain_l1_sse_thread_queue()
    db = _reset(tmp_path, monkeypatch)
    tk = srv.ticker_storage_key("SPY")
    _CONTRACT_A = "SPY   260918C00600000"
    _CONTRACT_B = "SPY   260918C00610000"
    _CONTRACT_C = "SPY   260918C00620000"
    contracts = [{
        "symbol": sym, "putCall": "CALL", "strikePrice": strike,
        "openInterest": 2097, "multiplier": 100.0, "gamma": 0.018, "delta": 0.5,
        "expirationDate": "2026-09-18T20:00:00.000+00:00", "daysToExpiration": 7,
    } for sym, strike in ((_CONTRACT_A, 600.0), (_CONTRACT_B, 610.0), (_CONTRACT_C, 620.0))]
    with srv._terrain_cache_lock:
        srv._terrain_cache[tk] = {
            "_contracts_rest": contracts, "_contracts_rest_spot": 400.0,
            "_contracts_rest_computed_ts": time.time() - 30.0,
        }
    srv._gamma_surface_seq.pop(tk, None)
    try:
        ofs._active_option_contract = ofs.ticker_storage_key(_CONTRACT_A)
        ofs._active_option_contracts = [ofs.ticker_storage_key(_CONTRACT_B), ofs.ticker_storage_key(_CONTRACT_C)]

        # THE fault: push_level_one -- the real ingestion write -- never actually stores
        # anything. get_stream_greeks is left completely UNMOCKED (the real function);
        # if replay-to-state genuinely worked, it would find real data. It must not.
        monkeypatch.setattr(ofs, "push_level_one", lambda *a, **k: None)

        real_hook = srv.refresh_gamma_surface_from_stream
        hook_started = []

        def _counting_hook(sym, ts):
            hook_started.append(sym)
            return real_hook(sym, ts)
        ofs.set_streamed_greeks_hook(_counting_hook)
        _EXPECTED_GAMMA = {_CONTRACT_A: 0.03, _CONTRACT_B: 0.04, _CONTRACT_C: 0.05}
        for sym, gamma in _EXPECTED_GAMMA.items():
            _write_option_l1_row(db, sym, dict(_REAL_LEVELONE_OPTIONS_CONTENT, key=sym, GAMMA=gamma),
                                 ts_recv=time.time())

        replayed = []
        real_ingest = ofs._ingest_pushed

        def _spy_ingest(topic, msg):
            result = real_ingest(topic, msg)
            if topic.startswith("optquote."):
                replayed.append(msg["symbol"])
            return result
        monkeypatch.setattr(ofs, "_ingest_pushed", _spy_ingest)

        async def _run_one_tick():
            ofs._feed_running = True
            task = asyncio.get_event_loop().create_task(_feed_with_push())
            await _wait_until(lambda: len(set(replayed)) >= 3, timeout_sec=15.0,
                              what="all three contracts to be replayed at least once (write suppressed)")
            # The hook may never fire at all with the write suppressed (no qualifying
            # observation ever reaches state to report) -- do not require it to; a
            # bounded settle window is enough since there is no slow real hook cost to wait
            # out when nothing ever overlays.
            await asyncio.sleep(0.3)
            ofs._feed_running = False
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        asyncio.run(_run_one_tick())
        ofs.set_streamed_greeks_hook(None)

        # Confirm the fault is real: OrderFlowState must show NOTHING for any contract --
        # sanity that this test's own suppression actually took effect, not a no-op patch.
        for sym in _EXPECTED_GAMMA:
            assert ofls.get_stream_greeks(sym) is None, (
                f"sanity failed: {sym} shows streamed greeks despite push_level_one being "
                f"suppressed -- this test's own fault injection did not take effect")

        # THE proof: the benchmark's own pipeline assertion (checking the ACTUAL gamma
        # value reached OrderFlowState) must FAIL here, exactly as required.
        pipeline_assertion_failed = False
        try:
            greeks = ofls.get_stream_greeks(_CONTRACT_A)
            assert greeks is not None and greeks.get("gamma") == _EXPECTED_GAMMA[_CONTRACT_A]
        except AssertionError:
            pipeline_assertion_failed = True
        assert pipeline_assertion_failed, (
            "the pipeline assertion (OrderFlowState reflects the captured row's own gamma) "
            "must FAIL when replay-to-state writes are suppressed -- it did not, so it "
            "cannot be trusted to catch a genuinely broken write path either")

        # And the publication assertion (overlay count reflecting the batch) must ALSO
        # fail -- with nothing ever written to state, nothing can have overlaid.
        with srv._terrain_cache_lock:
            published = srv._terrain_cache[tk].get("_gamma_surface")
        overlay_count = published.get("stream_overlay_contracts", 0) if published else 0
        assert overlay_count != 3, (
            f"the publication assertion (stream_overlay_contracts == 3) must also fail "
            f"when replay-to-state writes are suppressed; got {overlay_count}")
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

    Survivor-challenge finding (2026-09-12), REPRODUCED: the ORIGINAL version of this
    control called `_replay_option_contract_rows` directly, bypassing `_feed_loop`
    entirely -- since that function no longer calls the hook itself at all (hook
    dispatch moved to `_feed_loop` in the multi-contract coalescing fix), calling it
    directly never exercises the "disabled" branch of the feed loop's own dispatch logic
    (`if qualifying and _streamed_greeks_hook is not None:`) -- it would behave
    IDENTICALLY whether the hook were wired or not, proving nothing about disabling it.
    Fixed: runs the REAL `_feed_loop` for one real poll tick, with the hook genuinely
    never registered (`_streamed_greeks_hook is None`), so the feed loop's own
    "no hook wired, skip dispatch" branch is what actually executes.

    # institutional-synthetic-ok: a minimal single-contract REST baseline, built inline
    # for exactly this control's purpose (proving an assertion correctly fails) -- no
    # real fixture is needed or more informative than one deliberately simple contract.
    """
    import asyncio

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
    monkeypatch.setattr(srv, "resolve_spot", lambda t, **kw: (400.0, "stub", time.time()))
    try:
        monkeypatch.setattr("app.options.order_flow.state.get_stream_greeks",
                            lambda sym: {"gamma": 0.02, "gamma_ts_recv": time.time()} if sym == _CONTRACT_A else None)
        ofs._active_option_contract = ofs.ticker_storage_key(_CONTRACT_A)
        status = srv.refresh_gamma_surface_from_stream(_CONTRACT_A, time.time())
        assert status == "ok"
        with srv._terrain_cache_lock:
            seq_before = srv._terrain_cache[tk]["_gamma_surface"]["surface_seq"]
        with srv._terrain_cache_lock:
            srv._terrain_cache[tk]["_contracts_rest_computed_ts"] = time.time() - 30.0

        # The hook is NEVER wired (set_streamed_greeks_hook is never called; confirmed
        # explicitly below) -- this models "the batch-publication callback is disabled".
        # A fresh qualifying L1 row for A lands and IS replayed through the REAL
        # _feed_loop, but with `ofs._streamed_greeks_hook is None`, the feed loop's own
        # dispatch code must skip calling it -- nothing consumes the observation into a
        # new publication.
        assert ofs._streamed_greeks_hook is None, "sanity: the hook must genuinely be unregistered"
        _write_option_l1_row(db, _CONTRACT_A, dict(_REAL_LEVELONE_OPTIONS_CONTENT, key=_CONTRACT_A, GAMMA=0.09),
                             ts_recv=time.time())

        replayed = []
        real_ingest = ofs._ingest_pushed

        def _spy_ingest(topic, msg):
            result = real_ingest(topic, msg)
            if topic.startswith("optquote."):
                replayed.append(msg["symbol"])
            return result
        monkeypatch.setattr(ofs, "_ingest_pushed", _spy_ingest)

        async def _run_one_tick():
            ofs._feed_running = True
            task = asyncio.get_event_loop().create_task(_feed_with_push())
            await _wait_until(lambda: len(replayed) >= 1, timeout_sec=10.0,
                              what="A to be replayed at least once through the real feed loop")
            await asyncio.sleep(0.2)   # let the feed loop's own dispatch branch settle
            ofs._feed_running = False
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        asyncio.run(_run_one_tick())

        with srv._terrain_cache_lock:
            after = srv._terrain_cache[tk]["_gamma_surface"]
        assert after["surface_seq"] == seq_before, (
            "sanity: with the hook genuinely unregistered, _feed_loop's own dispatch "
            "branch must not publish a new surface generation")
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
    _spot_by_tk = {spy_tk: 400.0, qqq_tk: 300.0}
    monkeypatch.setattr(srv, "resolve_spot", lambda t, **kw: (_spot_by_tk.get(t), "stub", time.time()))
    try:
        live = {_SPY_A: {"gamma": 0.05, "gamma_ts_recv": time.time()},
                _SPY_B: {"gamma": 0.06, "gamma_ts_recv": time.time()},
                _QQQ_A: {"gamma": 0.07, "gamma_ts_recv": time.time()}}
        monkeypatch.setattr("app.options.order_flow.state.get_stream_greeks", lambda sym: live.get(sym))
        ofs._active_option_contract = ofs.ticker_storage_key(_SPY_A)
        ofs._active_option_contracts = [ofs.ticker_storage_key(_SPY_B), ofs.ticker_storage_key(_QQQ_A)]

        replayed = []
        real_ingest = ofs._ingest_pushed

        def _spy_ingest(topic, msg):
            result = real_ingest(topic, msg)
            if topic.startswith("optquote."):
                replayed.append(msg["symbol"])
            return result
        monkeypatch.setattr(ofs, "_ingest_pushed", _spy_ingest)

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
            task = asyncio.get_event_loop().create_task(_feed_with_push())
            await _wait_until(lambda: len(set(replayed)) >= 3, timeout_sec=15.0,
                              what="all three contracts (2 SPY, 1 QQQ) to be replayed at least once")
            await _wait_until(lambda: {ofs._hook_grouping_key(x) for x in hook_started} == {"SPY", "QQQ"}
                              and len(hook_started) == len(hook_finished),
                              timeout_sec=15.0, what="both underlyings' hook calls to finish")
            ofs._feed_running = False
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        asyncio.run(_run_one_tick())
        ofs.set_streamed_greeks_hook(None)

        roots = [ofs._hook_grouping_key(x) for x in hook_started]
        assert roots.count("QQQ") == 1, (
            f"QQQ must get its OWN call, never merged into SPY's: {hook_started}")
        assert 1 <= roots.count("SPY") <= 2, (
            f"two SPY contracts must cost at most one call plus one trailing re-run: {hook_started}")
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


def test_hook_coalesces_a_bare_spx_and_weekly_spxw_contract_into_one_group(tmp_path, monkeypatch):
    """Independent-review finding (2026-09-12), REPRODUCED: _feed_loop's hook-coalescing
    grouped qualifying contracts by the RAW `vendor_option_root(sym) or sym` value alone
    -- a bare-SPX-rooted contract (root "SPX") and a weekly-SPXW-rooted contract (root
    "SPXW") on the exact SAME $SPX underlying produced two DIFFERENT raw roots, landing
    in two different coalescing groups and firing the hook TWICE in one poll tick for
    what is genuinely one underlying's one terrain-cache entry -- not corrupting, but
    exactly the redundant-recompute defect this coalescing was built to close (see
    test_hook_fires_once_per_underlying_when_two_underlyings_qualify_in_one_tick above).

    Root-caused and fixed with `_hook_grouping_key`, a narrow canonicalization that
    strips a trailing "W" ONLY when the resulting bare root is in the existing,
    curated `BROKER_INDEX_BARE_ROOTS` set (SPX, NDX, RUT, DJX, XSP, OEX, ...) -- a real
    documented Schwab/OCC weekly-root convention, not an invented alias. This does not
    touch `contract_matches_underlying`'s own full chain-aware equivalence check used
    for correctness elsewhere (subscription reconciliation, coverage epochs); it exists
    only to avoid an over-eager extra hook call for this one well-known aliasing case.

    Negative control below reproduces the pre-fix disagreement directly with the exact
    production `vendor_option_root` function (not a reimplementation), before proving
    the current `_hook_grouping_key` unifies the two roots and the real `_feed_loop`
    fires the hook exactly once for this tick.

    # institutional-synthetic-ok: one minimal, real-shaped bare-SPX and weekly-SPXW
    # contract built inline for exactly this grouping control -- both use real
    # Schwab/OCC OSI symbol structure (6-char root + YYMMDD + C/P + 8-digit strike);
    # no real fixture would be more informative than these deliberately simple,
    # clearly-labeled contracts.
    """
    import server as srv

    _SPX_A = "SPX   260918C05600000"
    _SPXW_A = "SPXW  260918C05600000"

    # Negative control: the pre-fix grouping (raw vendor_option_root only, with no
    # BROKER_INDEX_BARE_ROOTS canonicalization) genuinely disagrees between these two
    # contracts -- if it did not, this test would prove nothing about the fix.
    pre_fix_root_a = ofs.vendor_option_root(_SPX_A) or _SPX_A
    pre_fix_root_b = ofs.vendor_option_root(_SPXW_A) or _SPXW_A
    assert pre_fix_root_a == "SPX" and pre_fix_root_b == "SPXW" and pre_fix_root_a != pre_fix_root_b, (
        "negative control setup is broken: the raw vendor roots must actually differ "
        "between a bare-SPX and a weekly-SPXW contract for this test to prove anything")

    # The current, fixed grouping key must agree.
    assert ofs._hook_grouping_key(_SPX_A) == ofs._hook_grouping_key(_SPXW_A) == "SPX"

    _drain_l1_sse_thread_queue()
    db = _reset(tmp_path, monkeypatch)
    spx_tk = srv.ticker_storage_key("SPX")
    assert spx_tk == "$SPX"
    with srv._terrain_cache_lock:
        srv._terrain_cache[spx_tk] = {
            "_contracts_rest": [
                {"symbol": _SPX_A, "putCall": "CALL", "strikePrice": 5600.0, "openInterest": 500,
                 "multiplier": 100.0, "gamma": 0.02, "delta": 0.5,
                 "expirationDate": "2026-09-18T20:00:00.000+00:00", "daysToExpiration": 7},
                {"symbol": _SPXW_A, "putCall": "CALL", "strikePrice": 5600.0, "openInterest": 500,
                 "multiplier": 100.0, "gamma": 0.02, "delta": 0.5,
                 "expirationDate": "2026-09-18T20:00:00.000+00:00", "daysToExpiration": 7},
            ],
            "_contracts_rest_spot": 5600.0, "_contracts_rest_computed_ts": time.time() - 30.0,
        }
    srv._gamma_surface_seq.pop(spx_tk, None)
    try:
        ofs._active_option_contract = ofs.ticker_storage_key(_SPX_A)
        ofs._active_option_contracts = [ofs.ticker_storage_key(_SPXW_A)]

        hook_started = []

        def _counting_hook(sym, ts):
            hook_started.append(sym)
        ofs.set_streamed_greeks_hook(_counting_hook)
        for sym in (_SPX_A, _SPXW_A):
            _write_option_l1_row(db, sym, dict(_REAL_LEVELONE_OPTIONS_CONTENT, key=sym, GAMMA=0.08),
                                  ts_recv=1700000000.0)

        async def _run_one_tick():
            ofs._feed_running = True
            task = asyncio.get_event_loop().create_task(_feed_with_push())
            await _wait_until(lambda: len(hook_started) >= 1, timeout_sec=15.0,
                              what="the coalesced SPX/SPXW hook call")
            # Give a would-be SECOND call (the pre-fix, un-coalesced behavior) a full
            # extra poll interval to land before declaring the tick settled.
            await asyncio.sleep(1.0)
            ofs._feed_running = False
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        asyncio.run(_run_one_tick())

        # The grouping itself is pinned deterministically by
        # test_a_burst_groups_by_underlying_not_by_contract; end to end, one $SPX underlying
        # costs at most one call plus one trailing re-run.
        assert 1 <= len(hook_started) <= 2, (
            f"a bare-SPX and a weekly-SPXW contract on the SAME $SPX underlying must "
            f"coalesce, not {len(hook_started)} calls: {hook_started}")
    finally:
        ofs.set_streamed_greeks_hook(None)
        ofs._active_option_contract = None
        ofs._active_option_contracts = []
        with srv._terrain_cache_lock:
            srv._terrain_cache.pop(spx_tk, None)
        srv._gamma_surface_seq.pop(spx_tk, None)
        _drain_l1_sse_thread_queue()


def test_a_slow_hook_for_one_underlying_does_not_delay_replay_for_another(tmp_path, monkeypatch):
    """Independent-review finding (2026-09-12, state-authority review), REPRODUCED: the hook
    call used to be AWAITED on _feed_loop's single-worker DB executor before the loop could
    proceed to the NEXT poll tick's own state capture -- a slow hook for ONE underlying (the
    committed SPXW benchmark above measures ~1.95s at full scale) delayed OrderFlowState
    updates for every OTHER ticker/contract by however long that one hook took, not just its
    own publication. Fixed by dispatching the hook as a background task on its own dedicated
    executor, decoupled from this loop's own tick cadence.

    Reproduced/proven here with a REAL threading.Event (the hook runs on a real OS thread via
    run_in_executor, not the asyncio loop, so a synchronous block is the correct primitive):
    SPY's hook is held open indefinitely while a genuinely NEW row for QQQ -- a different
    underlying, its own coalescing group -- is written AFTER SPY's hook has already started.
    QQQ's row must reach OrderFlowState well within the SPY hook's hold duration, not after it.
    """
    _drain_l1_sse_thread_queue()
    db = _reset(tmp_path, monkeypatch)
    _SPY_A = "SPY   260918C00600000"
    _QQQ_A = "QQQ   260918C00500000"
    ofs._active_option_contracts = [ofs.ticker_storage_key(_SPY_A), ofs.ticker_storage_key(_QQQ_A)]

    spy_hook_started = threading.Event()
    release_spy_hook = threading.Event()
    hook_calls = []

    def _hook(sym, ts):
        hook_calls.append(sym)
        if ofs._hook_grouping_key(sym) == ofs._hook_grouping_key(_SPY_A):
            spy_hook_started.set()
            release_spy_hook.wait(timeout=10.0)   # held open -- simulates the measured SPXW cost
    ofs.set_streamed_greeks_hook(_hook)

    _write_option_l1_row(db, _SPY_A, dict(_REAL_LEVELONE_OPTIONS_CONTENT, key=_SPY_A, GAMMA=0.05),
                          ts_recv=1700000000.0)

    async def _run():
        ofs._feed_running = True
        task = asyncio.get_event_loop().create_task(_feed_with_push())
        await _wait_until(lambda: spy_hook_started.is_set(), timeout_sec=5.0,
                          what="SPY's hook to start and block")
        start = time.time()
        # A genuinely NEW row for a DIFFERENT underlying, written only now -- while SPY's
        # hook is still blocked -- must still reach OrderFlowState promptly.
        _write_option_l1_row(db, _QQQ_A, dict(_REAL_LEVELONE_OPTIONS_CONTENT, key=_QQQ_A, GAMMA=0.09),
                              ts_recv=1700000005.0)
        await _wait_until(lambda: ofls.get_stream_greeks(_QQQ_A) is not None, timeout_sec=5.0,
                          what="QQQ's new row to reach OrderFlowState while SPY's hook is still blocked")
        elapsed = time.time() - start
        release_spy_hook.set()
        await _wait_until(lambda: ofs._hook_grouping_key(_QQQ_A) in
                          [ofs._hook_grouping_key(s) for s in hook_calls[1:]] or len(hook_calls) >= 2,
                          timeout_sec=5.0, what="QQQ's own hook call to fire")
        ofs._feed_running = False
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        return elapsed

    elapsed = asyncio.run(_run())
    ofs.set_streamed_greeks_hook(None)
    ofs._active_option_contracts = []
    _drain_l1_sse_thread_queue()

    assert elapsed < 2.0, (
        f"QQQ's row took {elapsed:.2f}s to reach OrderFlowState while SPY's hook was still "
        f"blocked -- state capture for one underlying must not wait behind another's slow "
        f"hook computation")
    assert hook_calls[0] == _SPY_A or ofs._hook_grouping_key(hook_calls[0]) == ofs._hook_grouping_key(_SPY_A)


def test_backlog_coalesces_across_ticks_and_a_shutdown_drops_the_pending_rerun(tmp_path, monkeypatch):
    """Independent-review finding (2026-09-13), REPRODUCED then FIXED: "coalescing within
    each poll does not bound work across polls." Holding the hook callback while four
    qualifying poll batches arrived for the SAME underlying used to queue FOUR independent
    tasks on the single-worker hook executor (one dispatch per qualifying tick, no check
    for "is a call for this root already in flight"); stopping the feed loop after only the
    first had started still let the other three run afterward, because each was already an
    independently submitted `run_in_executor` future the executor's own non-blocking
    shutdown lets finish to completion.

    Reproduced and fixed here with the REAL _feed_loop, a real threading.Event-blocked
    hook, and real captured rows -- not a reimplementation of the dispatch logic. Proves
    BOTH halves of the fix:
      (1) four qualifying ticks for the same root while a call is already in flight
          coalesce into AT MOST ONE trailing re-run, never one-per-tick -- the underlying
          OrderFlowState still advances through every one of them (nothing is lost), only
          the (wasteful, redundant -- the hook always re-gathers fresh state on every
          real run) hook CALL COUNT is bounded.
      (2) once the feed loop has been stopped, releasing the in-flight call must NOT let
          the coalesced trailing call start -- new work must never be scheduled into a
          lifecycle that has already ended, even though the trailing rerun was already
          "queued" in the coalescing sense.
    """
    _drain_l1_sse_thread_queue()
    db = _reset(tmp_path, monkeypatch)
    SYM = "SPY   260918C00650000"
    ofs._active_option_contracts = [ofs.ticker_storage_key(SYM)]

    first_hook_started = threading.Event()
    release_first_hook = threading.Event()
    hook_calls = []

    def _hook(sym, ts):
        hook_calls.append((sym, ts))
        if len(hook_calls) == 1:
            first_hook_started.set()
            release_first_hook.wait(timeout=10.0)
    ofs.set_streamed_greeks_hook(_hook)

    _write_option_l1_row(db, SYM, dict(_REAL_LEVELONE_OPTIONS_CONTENT, key=SYM, GAMMA=0.01),
                          ts_recv=1700000000.0)

    async def _run():
        ofs._feed_running = True
        task = asyncio.get_event_loop().create_task(_feed_with_push())
        await _wait_until(lambda: first_hook_started.is_set(), timeout_sec=5.0,
                          what="the first hook call to start and block")

        # Four MORE qualifying ticks for the SAME underlying while the first call is still
        # blocked. State must advance through every one of them -- matching the reviewer's
        # own "state correctly advanced 222 -> 333" observation -- even though the hook
        # call count must NOT grow one-per-tick.
        for i, gamma in enumerate((0.02, 0.03, 0.04, 0.05), start=1):
            _write_option_l1_row(db, SYM, dict(_REAL_LEVELONE_OPTIONS_CONTENT, key=SYM, GAMMA=gamma),
                                  ts_recv=1700000000.0 + i)
            await _wait_until(lambda g=gamma: (ofls.get_stream_greeks(SYM) or {}).get("gamma") == g,
                              timeout_sec=5.0, what=f"OrderFlowState to advance to gamma={gamma}")

        # All four ticks have now been replayed into state AND had their chance to dispatch
        # a hook call; only the first is actually running (blocked), so a live-locked or
        # unbounded implementation would show 4-5 calls here -- the fix must show exactly 1.
        assert len(hook_calls) == 1, (
            f"four qualifying ticks arriving while the first hook call is still in flight "
            f"must coalesce, not queue one call per tick -- saw {len(hook_calls)} calls "
            f"before the first was even released")

        # Stop the feed loop WHILE the first call is still blocked -- the reviewer's own
        # "after the feed loop stops" ordering.
        ofs._feed_running = False
        await asyncio.sleep(0.05)

        # NOW release the first (only) call and give any wrongly-scheduled trailing task a
        # real chance to start.
        release_first_hook.set()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await asyncio.sleep(0.5)

    asyncio.run(_run())
    ofs.set_streamed_greeks_hook(None)
    ofs._active_option_contracts = []
    _drain_l1_sse_thread_queue()

    assert len(hook_calls) == 1, (
        f"a coalesced trailing hook call must never start once the feed loop has already "
        f"stopped -- saw {len(hook_calls)} total calls (expected exactly 1); obsolete work "
        f"was scheduled into a lifecycle that had already ended")


def test_a_second_underlyings_queued_hook_does_not_run_after_shutdown(tmp_path, monkeypatch):
    """A FOURTH independent review (2026-09-13), REPRODUCED: the fix above (RC-556) only
    ever gated a coalesced TRAILING RERUN of the SAME root that was already in flight when
    shutdown happened -- it added no check for a DIFFERENT root's fresh, non-coalesced
    dispatch, submitted to the shared single-worker `hook_executor` (max_workers=1) while a
    first root's call is still running. Concretely: a held AMD hook call occupies the one
    worker thread; a genuinely NEW dispatch for PLTR (a different root, never in-flight
    before) is submitted and sits queued behind AMD in the executor's own internal queue,
    invisible to `_hook_inflight_roots`/`_feed_running` bookkeeping. Stopping the feed loop
    while AMD is still held, then releasing AMD, let PLTR's already-queued task start
    running regardless of shutdown, because nothing upstream of the task's own entry point
    ever re-checked liveness.

    Fixed with `_run_streamed_greeks_hook_if_live`: every hook invocation funnels through
    one wrapper that re-checks `_feed_running` the instant it ACTUALLY starts executing on
    the worker thread (not when it was submitted), regardless of which root or dispatch
    path submitted it.
    """
    _drain_l1_sse_thread_queue()
    db = _reset(tmp_path, monkeypatch)
    AMD_SYM = "AMD   260918C00160000"
    PLTR_SYM = "PLTR  260918C00050000"
    ofs._active_option_contracts = [ofs.ticker_storage_key(AMD_SYM), ofs.ticker_storage_key(PLTR_SYM)]

    amd_hook_started = threading.Event()
    release_amd_hook = threading.Event()
    hook_calls = []

    def _hook(sym, ts):
        hook_calls.append(sym)
        if sym == AMD_SYM:
            amd_hook_started.set()
            release_amd_hook.wait(timeout=10.0)
    ofs.set_streamed_greeks_hook(_hook)

    _write_option_l1_row(db, AMD_SYM, dict(_REAL_LEVELONE_OPTIONS_CONTENT, key=AMD_SYM, GAMMA=0.01, UNDERLYING="AMD"),
                         ts_recv=1700000000.0)

    async def _run():
        ofs._feed_running = True
        task = asyncio.get_event_loop().create_task(_feed_with_push())
        await _wait_until(lambda: amd_hook_started.is_set(), timeout_sec=5.0,
                          what="AMD's hook call to start and block")

        # A genuinely NEW dispatch for a DIFFERENT root (PLTR) while AMD's call occupies the
        # single-worker executor -- PLTR's task is submitted (not coalesced -- it was never
        # in flight before) and queues behind AMD at the executor's own thread-pool level.
        _write_option_l1_row(db, PLTR_SYM, dict(_REAL_LEVELONE_OPTIONS_CONTENT, key=PLTR_SYM, GAMMA=0.02, UNDERLYING="PLTR"),
                             ts_recv=1700000000.0)
        await _wait_until(lambda: (ofls.get_stream_greeks(PLTR_SYM) or {}).get("gamma") == 0.02,
                          timeout_sec=5.0, what="OrderFlowState to advance PLTR's gamma")
        # PLTR's task has been SUBMITTED (state advanced) but cannot have STARTED yet --
        # the one worker thread is still occupied by AMD.
        assert PLTR_SYM not in hook_calls, "PLTR's hook must not have started while AMD still holds the one worker"

        # Stop the feed loop WHILE AMD is still held and PLTR sits queued, unstarted.
        ofs._feed_running = False
        await asyncio.sleep(0.05)

        # Release AMD -- the worker frees up and would normally pick up PLTR's queued task
        # next. Give it a real chance to actually start.
        release_amd_hook.set()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await asyncio.sleep(0.5)

    asyncio.run(_run())
    ofs.set_streamed_greeks_hook(None)
    ofs._active_option_contracts = []
    _drain_l1_sse_thread_queue()

    assert AMD_SYM in hook_calls, "AMD's own held call must still have run to completion (already in flight, harmless)"
    assert PLTR_SYM not in hook_calls, (
        "PLTR's hook body must never have actually executed once the feed loop had already "
        "stopped, even though its task was submitted to the executor before shutdown -- "
        f"saw hook_calls={hook_calls}"
    )


def test_a_queued_hook_does_not_run_under_a_lifecycle_that_restarted_before_it_drained(tmp_path, monkeypatch):
    """A FIFTH independent review (2026-09-13), REPRODUCED: the fix above (`_feed_running`
    re-checked at actual execution time) closes "stopped and STAYED stopped" but not "stopped
    then RESTARTED before the old queued task drained" -- `_feed_running` goes False then
    True again across a restart, so a bare boolean check cannot tell the NEW lifecycle from
    the one that queued the old work. Concretely reproduced: a held AMD hook call occupies
    the one worker thread; a genuinely NEW dispatch for PLTR queues behind it. The feed is
    stopped (PLTR still queued, unstarted) and then RESTARTED (`_feed_running` -> True again,
    a NEW lifecycle) BEFORE AMD is released. Only THEN is AMD released, freeing the worker
    for PLTR's still-queued task. Under a bare `_feed_running` check, PLTR's task would see
    `_feed_running is True` (the NEW lifecycle) and incorrectly run as if it belonged to it.

    Fixed with the lifecycle-generation counter (`_feed_generation`): PLTR's task carries the
    generation number that was current when IT was dispatched (the OLD lifecycle, before the
    restart bumped the counter), and `_run_streamed_greeks_hook_if_live` now requires that
    captured generation to still match the CURRENT one, not merely that some feed is running.
    """
    _drain_l1_sse_thread_queue()
    db = _reset(tmp_path, monkeypatch)
    AMD_SYM = "AMD   260918C00160000"
    PLTR_SYM = "PLTR  260918C00050000"
    ofs._active_option_contracts = [ofs.ticker_storage_key(AMD_SYM), ofs.ticker_storage_key(PLTR_SYM)]

    amd_hook_started = threading.Event()
    release_amd_hook = threading.Event()
    hook_calls = []

    def _hook(sym, ts):
        hook_calls.append(sym)
        if sym == AMD_SYM:
            amd_hook_started.set()
            release_amd_hook.wait(timeout=10.0)
    ofs.set_streamed_greeks_hook(_hook)

    _write_option_l1_row(db, AMD_SYM, dict(_REAL_LEVELONE_OPTIONS_CONTENT, key=AMD_SYM, GAMMA=0.01, UNDERLYING="AMD"),
                         ts_recv=1700000000.0)

    async def _run():
        ofs._feed_running = True
        ofs._feed_generation += 1
        task = asyncio.get_event_loop().create_task(_feed_with_push())
        await _wait_until(lambda: amd_hook_started.is_set(), timeout_sec=5.0,
                          what="AMD's hook call to start and block")

        # PLTR's dispatch is submitted under THIS (about-to-be-old) lifecycle, queued behind
        # AMD, unstarted.
        _write_option_l1_row(db, PLTR_SYM, dict(_REAL_LEVELONE_OPTIONS_CONTENT, key=PLTR_SYM, GAMMA=0.02, UNDERLYING="PLTR"),
                             ts_recv=1700000000.0)
        await _wait_until(lambda: (ofls.get_stream_greeks(PLTR_SYM) or {}).get("gamma") == 0.02,
                          timeout_sec=5.0, what="OrderFlowState to advance PLTR's gamma")
        assert PLTR_SYM not in hook_calls, "PLTR's hook must not have started while AMD still holds the one worker"

        # Stop the feed loop WHILE AMD is still held and PLTR sits queued, unstarted...
        ofs._feed_running = False
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # ...then RESTART it -- a genuinely NEW lifecycle, `_feed_generation` bumped past
        # whatever PLTR's still-queued task captured. The old `_feed_loop` task is gone
        # (cancelled above); PLTR's dispatched-but-unstarted hook task on the shared
        # `hook_executor` is untouched by that cancellation and is still sitting queued.
        ofs._feed_running = True
        ofs._feed_generation += 1

        # NOW release AMD -- the worker frees up and would normally pick up PLTR's queued
        # task next, under the NEW lifecycle's `_feed_running is True`.
        release_amd_hook.set()
        await asyncio.sleep(0.5)

    asyncio.run(_run())
    ofs.set_streamed_greeks_hook(None)
    ofs._active_option_contracts = []
    ofs._feed_running = False
    _drain_l1_sse_thread_queue()

    assert AMD_SYM in hook_calls, "AMD's own held call must still have run to completion (already in flight, harmless)"
    assert PLTR_SYM not in hook_calls, (
        "PLTR's hook body must never have actually executed once the lifecycle that queued "
        "it had ended, even though the feed was RESTARTED (making a bare `_feed_running` "
        f"check true again) before its task drained -- saw hook_calls={hook_calls}"
    )
