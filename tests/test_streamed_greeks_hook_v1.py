"""set_streamed_greeks_hook / _replay_option_contract_rows (app/options/order_flow/streaming.py):
the hook that lets a consumer (server.py's gamma-surface cache) learn the instant a streamed
option L1 tick carries new GAMMA/DELTA/OPEN_INTEREST, instead of only via the slow poll of
OrderFlowState. Same shape/precedent as the existing `_on_tick_callback`. Proven against the
REAL replay path (_replay_option_contract_rows reading real stream_capture.db rows written by
CaptureWriter), not a reimplementation of its dispatch logic."""
from __future__ import annotations

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


def test_hook_fires_on_a_tick_carrying_greeks_or_open_interest(tmp_path, monkeypatch):
    db = _reset(tmp_path, monkeypatch)
    _write_option_l1_row(db, _SPY_CONTRACT, _REAL_LEVELONE_OPTIONS_CONTENT, ts_recv=1700000000.0)
    calls = []
    ofs.set_streamed_greeks_hook(lambda sym, ts: calls.append((sym, ts)))
    try:
        con = ofs._open_capture_db_readonly(db)
        ofs._replay_option_contract_rows(con, _SPY_CONTRACT)
        con.close()
    finally:
        ofs.set_streamed_greeks_hook(None)
    assert calls == [(_SPY_CONTRACT, 1700000000.0)]


def test_hook_does_not_fire_on_a_bid_ask_only_tick(tmp_path, monkeypatch):
    """A tick with no GAMMA/DELTA/OPEN_INTEREST at all is not worth an eager recompute --
    nothing changed that the exposure formula reads."""
    db = _reset(tmp_path, monkeypatch)
    _write_option_l1_row(db, _SPY_CONTRACT, _BID_ASK_ONLY_CONTENT, ts_recv=1700000000.0)
    calls = []
    ofs.set_streamed_greeks_hook(lambda sym, ts: calls.append((sym, ts)))
    try:
        con = ofs._open_capture_db_readonly(db)
        ofs._replay_option_contract_rows(con, _SPY_CONTRACT)
        con.close()
    finally:
        ofs.set_streamed_greeks_hook(None)
    assert calls == []


def test_hook_fires_on_a_volume_only_tick_with_no_greeks_present(tmp_path, monkeypatch):
    """Independent-review finding (2026-09-12): 'the current hook is triggered by
    GAMMA/DELTA/OPEN_INTEREST; that does not complete volume-only update delivery.' A tick
    that carries ONLY TOTAL_VOLUME (no Greeks/OI at all) must still fire the hook, since
    _per_strike's volume column and compute_exposures_by_strike's own volume aggregation both
    read a contract's totalVolume directly."""
    db = _reset(tmp_path, monkeypatch)
    volume_only = dict(_BID_ASK_ONLY_CONTENT, TOTAL_VOLUME=54321)
    _write_option_l1_row(db, _SPY_CONTRACT, volume_only, ts_recv=1700000000.0)
    calls = []
    ofs.set_streamed_greeks_hook(lambda sym, ts: calls.append((sym, ts)))
    try:
        con = ofs._open_capture_db_readonly(db)
        ofs._replay_option_contract_rows(con, _SPY_CONTRACT)
        con.close()
    finally:
        ofs.set_streamed_greeks_hook(None)
    assert calls == [(_SPY_CONTRACT, 1700000000.0)]


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


def test_a_hook_that_raises_does_not_break_the_replay(tmp_path, monkeypatch):
    db = _reset(tmp_path, monkeypatch)
    _write_option_l1_row(db, _SPY_CONTRACT, _REAL_LEVELONE_OPTIONS_CONTENT, ts_recv=1700000000.0)

    def _boom(sym, ts):
        raise RuntimeError("simulated hook failure")

    ofs.set_streamed_greeks_hook(_boom)
    try:
        con = ofs._open_capture_db_readonly(db)
        ofs._replay_option_contract_rows(con, _SPY_CONTRACT)  # must not raise
        con.close()
    finally:
        ofs.set_streamed_greeks_hook(None)
    items = ofls.get_content_for_symbol(_SPY_CONTRACT)
    assert any(i.get("LAST_PRICE") == 1.27 for i in items), (
        "a failing hook must not prevent the real observation from being applied"
    )


def test_a_burst_of_rows_in_one_poll_batch_fires_the_hook_exactly_once(tmp_path, monkeypatch):
    """Independent-review finding (2026-09-12), REPRODUCED then fixed: calling the hook once
    PER ROW meant a burst of N rows landing in one poll batch triggered N sequential expensive
    recomputes on the consumer side (MEASURED: ~3.1s each on a full SPXW-scale book -- three
    sequential calls, 9.3s total, zero suppressed). Three rows are written here BEFORE the
    daemon ever replays them (simulating a burst that accumulated between poll ticks, a real
    shape: CaptureWriter and the replay poll are independent), so ONE _replay_option_contract_rows
    call sees all three in a single query -- proving the hook fires exactly once for the whole
    batch, not three times, while EVERY row still lands in OrderFlowState (nothing is dropped
    from the state itself, only the expensive recompute is coalesced)."""
    db = _reset(tmp_path, monkeypatch)
    _write_option_l1_row(db, _SPY_CONTRACT, dict(_REAL_LEVELONE_OPTIONS_CONTENT, GAMMA=0.01), ts_recv=1700000000.0)
    _write_option_l1_row(db, _SPY_CONTRACT, dict(_REAL_LEVELONE_OPTIONS_CONTENT, GAMMA=0.02), ts_recv=1700000001.0)
    _write_option_l1_row(db, _SPY_CONTRACT, dict(_REAL_LEVELONE_OPTIONS_CONTENT, GAMMA=0.03), ts_recv=1700000002.0)

    calls = []
    ofs.set_streamed_greeks_hook(lambda sym, ts: calls.append((sym, ts)))
    try:
        con = ofs._open_capture_db_readonly(db)
        ofs._replay_option_contract_rows(con, _SPY_CONTRACT)  # ONE call sees all three rows
        con.close()
    finally:
        ofs.set_streamed_greeks_hook(None)

    assert calls == [(_SPY_CONTRACT, 1700000002.0)], (
        "exactly one hook call for the whole batch, stamped with the FRESHEST row's ts_recv"
    )
    # every row still reached OrderFlowState -- push_level_one ran for all three, the LATEST
    # (gamma=0.03) is what a consumer reading state now sees, nothing from the batch was lost
    assert ofls.get_stream_greeks(_SPY_CONTRACT)["gamma"] == 0.03


def test_a_batch_with_no_qualifying_rows_never_fires_the_hook(tmp_path, monkeypatch):
    db = _reset(tmp_path, monkeypatch)
    _write_option_l1_row(db, _SPY_CONTRACT, _BID_ASK_ONLY_CONTENT, ts_recv=1700000000.0)
    _write_option_l1_row(db, _SPY_CONTRACT, dict(_BID_ASK_ONLY_CONTENT, LAST_PRICE=1.35), ts_recv=1700000001.0)

    calls = []
    ofs.set_streamed_greeks_hook(lambda sym, ts: calls.append((sym, ts)))
    try:
        con = ofs._open_capture_db_readonly(db)
        ofs._replay_option_contract_rows(con, _SPY_CONTRACT)
        con.close()
    finally:
        ofs.set_streamed_greeks_hook(None)
    assert calls == []


def test_a_batch_with_one_qualifying_row_among_several_fires_once_with_that_rows_ts(tmp_path, monkeypatch):
    """A qualifying row in the MIDDLE of a batch (not the last row overall) must still be the
    one whose ts_recv is used -- 'freshest QUALIFYING row', not 'last row in the batch'."""
    db = _reset(tmp_path, monkeypatch)
    _write_option_l1_row(db, _SPY_CONTRACT, _BID_ASK_ONLY_CONTENT, ts_recv=1700000000.0)
    _write_option_l1_row(db, _SPY_CONTRACT, dict(_REAL_LEVELONE_OPTIONS_CONTENT, GAMMA=0.05), ts_recv=1700000001.0)
    _write_option_l1_row(db, _SPY_CONTRACT, dict(_BID_ASK_ONLY_CONTENT, LAST_PRICE=1.40), ts_recv=1700000002.0)

    calls = []
    ofs.set_streamed_greeks_hook(lambda sym, ts: calls.append((sym, ts)))
    try:
        con = ofs._open_capture_db_readonly(db)
        ofs._replay_option_contract_rows(con, _SPY_CONTRACT)
        con.close()
    finally:
        ofs.set_streamed_greeks_hook(None)
    assert calls == [(_SPY_CONTRACT, 1700000001.0)]


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
    to have fallen into with too-thin synthetic inputs."""
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
    call's worth of latency, not three -- the actual production claim, not a call count."""
    import time as _t

    import server as srv

    _drain_l1_sse_thread_queue()
    db = _reset(tmp_path, monkeypatch)
    tk = srv.ticker_storage_key("SPY")
    contracts = _synthetic_full_book_contracts()
    # _SPY_CONTRACT must be a genuine MEMBER of the REST baseline, or
    # overlay_streamed_contract_fields finds nothing to overlay and
    # refresh_gamma_surface_from_stream short-circuits to "no_change" BEFORE ever running
    # the real projection cost this benchmark exists to measure.
    contracts = contracts + [{
        "symbol": _SPY_CONTRACT, "putCall": "CALL", "strikePrice": 767.0,
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
    ofs._active_option_contract = ofs.ticker_storage_key(_SPY_CONTRACT)
    try:
        # Baseline: measure ONE real call's cost directly against the real consumer.
        def _stream_greeks(sym):
            return {"gamma": 0.02, "gamma_ts_recv": _t.time()} if sym == _SPY_CONTRACT else None
        monkeypatch.setattr("app.options.order_flow.state.get_stream_greeks", _stream_greeks)

        t0 = _t.perf_counter()
        status = srv.refresh_gamma_surface_from_stream(_SPY_CONTRACT, _t.time())
        one_call_sec = _t.perf_counter() - t0
        assert status == "ok", (
            f"benchmark call must actually run the real projection, not short-circuit: {status}")
        print(f"[perf] refresh_gamma_surface_from_stream, {len(contracts)}-contract "
              f"synthetic SPXW-scale book: {one_call_sec * 1000:.1f} ms/call")

        # Reset the REST generation so the second measurement below is a fresh, comparable
        # compute-and-publish, not a "stale_baseline_superseded" no-op.
        with srv._terrain_cache_lock:
            srv._terrain_cache[tk]["_contracts_rest_computed_ts"] = _t.time() - 30.0

        # The real proof: three L1 rows land in ONE poll batch (a real burst shape --
        # CaptureWriter and the replay poll run independently) with the hook wired to the
        # REAL production function -- only ONE real call's worth of wall-clock time must be
        # paid for the whole batch, not three.
        ofs.set_streamed_greeks_hook(srv.refresh_gamma_surface_from_stream)
        _write_option_l1_row(db, _SPY_CONTRACT, dict(_REAL_LEVELONE_OPTIONS_CONTENT, GAMMA=0.01), ts_recv=1700000000.0)
        _write_option_l1_row(db, _SPY_CONTRACT, dict(_REAL_LEVELONE_OPTIONS_CONTENT, GAMMA=0.02), ts_recv=1700000001.0)
        _write_option_l1_row(db, _SPY_CONTRACT, dict(_REAL_LEVELONE_OPTIONS_CONTENT, GAMMA=0.03), ts_recv=1700000002.0)
        con = ofs._open_capture_db_readonly(db)
        t0 = _t.perf_counter()
        ofs._replay_option_contract_rows(con, _SPY_CONTRACT)   # 3 rows, ONE poll batch
        batch_sec = _t.perf_counter() - t0
        con.close()
        ofs.set_streamed_greeks_hook(None)
        print(f"[perf] one poll batch carrying 3 qualifying rows, real hook wired: "
              f"{batch_sec * 1000:.1f} ms total (one-call baseline was "
              f"{one_call_sec * 1000:.1f} ms)")

        with srv._terrain_cache_lock:
            published = srv._terrain_cache[tk]["_gamma_surface"]
        assert published is not None and published.get("stream_overlay_contracts", 0) >= 1, (
            "the batch's real projection must have actually published -- otherwise this "
            "measured zero real cost, not the coalescing benefit it claims to prove")
        # Generous 2x ceiling (not a tight SLA) -- this only fails if coalescing regresses
        # toward per-row firing (which would cost close to 3x one_call_sec).
        assert batch_sec < one_call_sec * 2.0, (
            f"a 3-row batch cost {batch_sec * 1000:.1f} ms -- close to 3x one real call's "
            f"{one_call_sec * 1000:.1f} ms, suggesting the hook fired more than once for "
            f"this batch")
    finally:
        ofs.set_streamed_greeks_hook(None)
        with srv._terrain_cache_lock:
            srv._terrain_cache.pop(tk, None)
        srv._gamma_surface_seq.pop(tk, None)
        _drain_l1_sse_thread_queue()
