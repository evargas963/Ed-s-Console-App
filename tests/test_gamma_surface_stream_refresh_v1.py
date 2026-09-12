"""refresh_gamma_surface_from_stream / _gamma_surface_contracts_with_stream_overlay (server.py):
lets the ONE canonical gamma-surface faucet (project_gamma_surface -> compute_exposures_by_strike,
RC-UI-1) use a fresher-than-REST GAMMA/DELTA/OPEN_INTEREST for the one contract actively
streaming, instead of only refreshing on the ~60s wide-chain REST cycle (RC-UI-2). Proven against
a REAL captured chain fixture (tests/fixtures/real_crwd_complete_chain_quarter.json), not
invented contracts, and against the actual `project_gamma_surface` faucet -- never a
hand-derived expected GEX value."""
from __future__ import annotations

import json
import time
from pathlib import Path

import server
from server import (
    refresh_gamma_surface_from_stream,
    project_gamma_surface,
    ticker_storage_key,
)
from math_exposure_core import overlay_streamed_contract_fields

_FX = Path(__file__).resolve().parent / "fixtures"
_REAL = json.loads((_FX / "real_crwd_complete_chain_quarter.json").read_text(encoding="utf-8"))
_SPOT = float(_REAL["spot"])
_CONTRACTS = [dict(ct) for ct in _REAL["chain"]]
_CONTRACT_SYMBOL = _CONTRACTS[0]["symbol"]
_CONTRACT_SYMBOL_B = _CONTRACTS[1]["symbol"]
TK = ticker_storage_key("CRWD")


def _clear_cache():
    with server._terrain_cache_lock:
        server._terrain_cache.pop(TK, None)


def _put_rest_baseline(*, computed_ts_utc=None):
    ts = time.time() if computed_ts_utc is None else computed_ts_utc
    with server._terrain_cache_lock:
        server._terrain_cache[TK] = {
            "_contracts_rest": _CONTRACTS,
            "_contracts_rest_spot": _SPOT,
            "_contracts_rest_computed_ts": ts,
            "_gamma_surface": project_gamma_surface(_CONTRACTS, _SPOT),
            "computed_ts_utc": ts,
        }
    server._gamma_surface_seq.pop(TK, None)


def _drain_l1_sse_thread_queue():
    """refresh_gamma_surface_from_stream -> _next_gamma_surface_seq pushes a
    gamma_surface_seq SSE notify through server._l1_sse_thread_queue -- a module-level
    GLOBAL queue shared by every test in the process (see server.py's own
    _l1_notify_sse_after_authoritative_build users, e.g. tests/test_l1_light_sse.py).
    Independent-review-adjacent finding: an undrained entry left here by one of this
    file's own calls was FIFO-popped by test_l1_light_sse.py's
    test_notify_enqueues_when_subscribed as if it were that test's own fresh SPY
    notification -- CRWD (this file's ticker) instead of SPY, failing an assertion that
    has nothing to do with this file. Drained before AND after every test here so this
    file never leaks state into, or inherits it from, tests run earlier in the process."""
    import server as srv
    while not srv._l1_sse_thread_queue.empty():
        try:
            srv._l1_sse_thread_queue.get_nowait()
        except Exception:
            break


def setup_function(_fn):
    _clear_cache()
    _drain_l1_sse_thread_queue()
    # RC-UI-3 (2026-09-12): refresh_gamma_surface_from_stream now gathers streamed
    # greeks for EVERY currently-desired contract (_desired_stream_greeks_for_ticker),
    # not just the one it was called for -- in production this hook only ever fires for
    # a contract that IS currently desired (it is driven by _feed_loop's replay, which
    # only replays desired contracts). Establish that same realistic precondition here:
    # _CONTRACT_SYMBOL is the primary desired contract by default. Individual tests that
    # need different desired-state wiring (e.g. testing a foreign ticker or "nothing
    # active") monkeypatch get_active_option_contract themselves, which overrides this.
    import app.options.order_flow.streaming as _ofs
    _ofs._active_option_contract = _CONTRACT_SYMBOL
    _ofs._active_option_contracts = []


def teardown_function(_fn):
    _clear_cache()
    _drain_l1_sse_thread_queue()
    import app.options.order_flow.streaming as _ofs
    _ofs._active_option_contract = None
    _ofs._active_option_contracts = []


def test_not_an_option_symbol_short_circuits():
    assert refresh_gamma_surface_from_stream("SPY", 1.0) == "not_an_option_symbol"


def test_no_cached_ticker_when_the_root_matches_nothing_on_the_board():
    _clear_cache()
    assert refresh_gamma_surface_from_stream(_CONTRACT_SYMBOL, 1.0) == "no_cached_ticker"


def test_no_rest_baseline_when_the_cache_has_no_stored_contracts(monkeypatch):
    with server._terrain_cache_lock:
        server._terrain_cache[TK] = {"computed_ts_utc": time.time()}  # no _contracts_rest
    assert refresh_gamma_surface_from_stream(_CONTRACT_SYMBOL, 1.0) == "no_rest_baseline"


def test_no_streamed_greeks_when_none_were_ever_observed(monkeypatch):
    _put_rest_baseline()
    monkeypatch.setattr(
        "app.options.order_flow.state.get_stream_greeks", lambda sym: None)
    assert refresh_gamma_surface_from_stream(_CONTRACT_SYMBOL, time.time()) == "no_streamed_greeks"


def test_no_change_when_the_streamed_value_is_too_stale(monkeypatch):
    _put_rest_baseline()
    monkeypatch.setattr(
        "app.options.order_flow.state.get_stream_greeks",
        lambda sym: {"gamma": 0.99, "gamma_ts_recv": 0.0})
    assert refresh_gamma_surface_from_stream(_CONTRACT_SYMBOL, 100000.0) == "no_change"
    # the cache must be untouched -- still the original, un-overlaid projection
    with server._terrain_cache_lock:
        assert server._terrain_cache[TK]["_gamma_surface"] == project_gamma_surface(_CONTRACTS, _SPOT)


def test_a_fresh_streamed_update_recomputes_and_caches_the_overlaid_surface(monkeypatch):
    baseline_ts = time.time() - 10.0
    _put_rest_baseline(computed_ts_utc=baseline_ts)
    now = time.time()   # strictly after the REST baseline -- genuinely newer
    streamed = {"gamma": 0.5, "gamma_ts_recv": now, "delta": 0.9, "delta_ts_recv": now,
                "open_interest": 99999.0, "open_interest_ts_recv": now}
    monkeypatch.setattr(
        "app.options.order_flow.state.get_stream_greeks",
        lambda sym: streamed if sym == _CONTRACT_SYMBOL else None)

    status = refresh_gamma_surface_from_stream(_CONTRACT_SYMBOL, now)
    assert status == "ok"

    overlaid, n = overlay_streamed_contract_fields(_CONTRACTS, {_CONTRACT_SYMBOL: streamed})
    assert n == 1
    expected_surface = project_gamma_surface(overlaid, _SPOT)
    expected_per_strike = server._per_strike_view_from_contracts(overlaid, _SPOT)

    with server._terrain_cache_lock:
        cached = server._terrain_cache[TK]["_gamma_surface"]
        cached_per_strike = server._terrain_cache[TK]["_per_strike"]
    # the faucet's own cells/strikes/expirations must match the independently-computed
    # expectation exactly -- proves the wiring calls the SAME projection, not a reimplementation
    assert cached["cells"] == expected_surface["cells"]
    assert cached["strikes"] == expected_surface["strikes"]
    assert cached["expirations"] == expected_surface["expirations"]
    assert cached["stream_overlay_contracts"] == 1
    assert cached["stream_overlay_receipt_to_computed_ms"] >= 0
    assert cached["surface_seq"] == 1
    # finding #2 (independent review, 2026-09-12): the eager refresh must publish _per_strike
    # from the SAME overlaid contracts as _gamma_surface, or the heatmap and the Strike Detail
    # / GEX-by-strike panel disagree on the same strike.
    assert cached_per_strike == expected_per_strike
    # the untouched REST baseline in the cache is unchanged by the eager overlay
    with server._terrain_cache_lock:
        assert server._terrain_cache[TK]["_contracts_rest"] == _CONTRACTS


def test_a_streamed_value_older_than_the_rest_baseline_is_rejected(monkeypatch):
    """Independent-review finding (2026-09-12): 'being received within ten seconds does not
    establish that a stream value is newer than the REST input it replaces.' A value only 2s
    old is still OLDER than a REST baseline fetched 1s ago."""
    now = time.time()
    _put_rest_baseline(computed_ts_utc=now - 1.0)
    monkeypatch.setattr(
        "app.options.order_flow.state.get_stream_greeks",
        lambda sym: {"gamma": 0.99, "gamma_ts_recv": now - 2.0})
    assert refresh_gamma_surface_from_stream(_CONTRACT_SYMBOL, now) == "no_change"
    with server._terrain_cache_lock:
        assert server._terrain_cache[TK]["_gamma_surface"] == project_gamma_surface(_CONTRACTS, _SPOT)


def test_repeated_eager_refreshes_never_compound_away_from_the_rest_baseline(monkeypatch):
    """Each call overlays onto the STORED _contracts_rest, never onto a previously-overlaid
    result -- so two refreshes with two DIFFERENT streamed values produce the surface for the
    SECOND value alone, not an accumulation of both."""
    baseline_ts = time.time() - 10.0
    _put_rest_baseline(computed_ts_utc=baseline_ts)
    now = time.time()
    monkeypatch.setattr(
        "app.options.order_flow.state.get_stream_greeks",
        lambda sym: {"gamma": 0.11, "gamma_ts_recv": now})
    assert refresh_gamma_surface_from_stream(_CONTRACT_SYMBOL, now) == "ok"

    later = time.time()
    monkeypatch.setattr(
        "app.options.order_flow.state.get_stream_greeks",
        lambda sym: {"gamma": 0.22, "gamma_ts_recv": later})
    assert refresh_gamma_surface_from_stream(_CONTRACT_SYMBOL, later) == "ok"

    overlaid, _ = overlay_streamed_contract_fields(
        _CONTRACTS, {_CONTRACT_SYMBOL: {"gamma": 0.22, "gamma_ts_recv": later}})
    expected = project_gamma_surface(overlaid, _SPOT)
    with server._terrain_cache_lock:
        cached = server._terrain_cache[TK]["_gamma_surface"]
        seq = cached["surface_seq"]
    assert cached["cells"] == expected["cells"], (
        "the second refresh must reflect ONLY gamma=0.22, not gamma=0.11 carried forward"
    )
    assert seq == 2, "surface_seq must advance on each successive publication"


def test_a_rest_refresh_landing_mid_computation_is_not_overwritten_by_the_stale_result(monkeypatch):
    """Finding #3 (independent review, 2026-09-12), REPRODUCED then fixed: a REST refresh that
    completes WHILE this function is computing must not be silently clobbered by this
    function's now-stale-baseline result once it finally writes back."""
    baseline_ts = time.time() - 10.0
    _put_rest_baseline(computed_ts_utc=baseline_ts)
    now = time.time()
    monkeypatch.setattr(
        "app.options.order_flow.state.get_stream_greeks",
        lambda sym: {"gamma": 0.5, "gamma_ts_recv": now})

    orig_project = server.project_gamma_surface
    fresh_marker = {"expirations": [], "strikes": [], "cells": [], "marker": "FRESH_REST_GENERATION"}

    def racing_project(contracts_arg, spot_arg):
        # Simulate a REAL REST refresh landing WHILE this function computes, publishing a
        # newer generation before this function gets a chance to write its own (older) one.
        with server._terrain_cache_lock:
            server._terrain_cache[TK] = {
                "_contracts_rest": _CONTRACTS, "_contracts_rest_spot": _SPOT,
                "_contracts_rest_computed_ts": time.time(),   # NEW generation
                "_gamma_surface": fresh_marker,
                "computed_ts_utc": time.time(),
            }
        return orig_project(contracts_arg, spot_arg)

    monkeypatch.setattr(server, "project_gamma_surface", racing_project)
    try:
        status = refresh_gamma_surface_from_stream(_CONTRACT_SYMBOL, now)
    finally:
        server.project_gamma_surface = orig_project
    assert status == "stale_baseline_superseded"
    with server._terrain_cache_lock:
        cached = server._terrain_cache[TK]
    assert cached["_gamma_surface"] == fresh_marker, (
        "the newer REST generation published mid-computation must survive, never be "
        "overwritten by a result computed from the OLD baseline"
    )


def test_never_raises_on_an_internal_error(monkeypatch):
    _put_rest_baseline()
    monkeypatch.setattr(
        "app.options.order_flow.state.get_stream_greeks",
        lambda sym: {"gamma": 0.5, "gamma_ts_recv": time.time()})
    monkeypatch.setattr(server, "project_gamma_surface",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    status = refresh_gamma_surface_from_stream(_CONTRACT_SYMBOL, time.time())
    assert status.startswith("error:")


def test_gamma_surface_contracts_with_stream_overlay_ignores_a_foreign_ticker(monkeypatch):
    """The overlay used by _terrain_refresh_one itself must not apply another ticker's
    streaming contract onto THIS ticker's chain."""
    monkeypatch.setattr(
        "app.options.order_flow.streaming.get_active_option_contract",
        lambda: _CONTRACT_SYMBOL)  # a CRWD contract
    monkeypatch.setattr(
        "app.options.order_flow.state.get_stream_greeks",
        lambda sym: {"gamma": 0.99, "gamma_ts_recv": time.time()})
    out, n = server._gamma_surface_contracts_with_stream_overlay(
        ticker_storage_key("SPY"), _CONTRACTS)  # asking for SPY, not CRWD
    assert n == 0
    assert out == _CONTRACTS


def test_gamma_surface_contracts_with_stream_overlay_applies_for_the_matching_ticker(monkeypatch):
    monkeypatch.setattr(
        "app.options.order_flow.streaming.get_active_option_contract",
        lambda: _CONTRACT_SYMBOL)
    monkeypatch.setattr(
        "app.options.order_flow.state.get_stream_greeks",
        lambda sym: {"gamma": 0.99, "gamma_ts_recv": time.time()})
    out, n = server._gamma_surface_contracts_with_stream_overlay(TK, _CONTRACTS)
    assert n == 1
    assert out[0]["gamma"] == 0.99


def test_gamma_surface_contracts_with_stream_overlay_noop_with_no_active_contract(monkeypatch):
    monkeypatch.setattr(
        "app.options.order_flow.streaming.get_active_option_contract", lambda: None)
    out, n = server._gamma_surface_contracts_with_stream_overlay(TK, _CONTRACTS)
    assert n == 0
    assert out is _CONTRACTS


def test_a_volume_only_streamed_update_reaches_both_per_strike_and_gamma_surface(monkeypatch):
    """Independent-review finding (2026-09-12): 'the current hook is triggered by
    GAMMA/DELTA/OPEN_INTEREST; that does not complete volume-only update delivery.' A tick
    carrying ONLY total_volume (no Greeks/OI change at all) must still flow through the eager
    refresh into BOTH the per-strike volume column and compute_exposures_by_strike's own
    call/put volume aggregation (which the gamma-surface projection also feeds from)."""
    baseline_ts = time.time() - 10.0
    _put_rest_baseline(computed_ts_utc=baseline_ts)
    now = time.time()
    streamed = {"total_volume": 999999.0, "total_volume_ts_recv": now}
    monkeypatch.setattr(
        "app.options.order_flow.state.get_stream_greeks",
        lambda sym: streamed if sym == _CONTRACT_SYMBOL else None)

    status = refresh_gamma_surface_from_stream(_CONTRACT_SYMBOL, now)
    assert status == "ok"

    overlaid, n = overlay_streamed_contract_fields(_CONTRACTS, {_CONTRACT_SYMBOL: streamed})
    assert n == 1
    assert overlaid[0]["totalVolume"] == 999999.0
    expected_per_strike = server._per_strike_view_from_contracts(overlaid, _SPOT)

    with server._terrain_cache_lock:
        cached_per_strike = server._terrain_cache[TK]["_per_strike"]
    assert cached_per_strike == expected_per_strike
    # the overlaid contract's own strike shows the new volume in the per-strike "all" rows
    strike = round(overlaid[0]["strikePrice"], 2)
    row = next(r for r in cached_per_strike["all"] if r[0] == strike)
    assert row[2] == 999999, "the streamed volume must reach the per-strike volume column"


def test_rapid_successive_calls_are_never_silently_dropped(monkeypatch):
    """RETIRED (2026-09-12): a leading-edge per-ticker debounce used to live in this function.
    Independent review MEASURED it directly and found it gave zero protection against slow
    computations (a call's own duration already exceeds any reasonable window by the time the
    next one can arrive) while still being ABLE to silently drop the final update of a burst
    with nothing scheduling a trailing publication. Removed in favour of coalescing at the
    actual replay layer (see tests/test_streamed_greeks_hook_v1.py for that proof) -- this
    function itself must now execute EVERY call it is given, back to back, with no artificial
    rejection of its own."""
    baseline_ts = time.time() - 10.0
    _put_rest_baseline(computed_ts_utc=baseline_ts)
    now = time.time()
    monkeypatch.setattr(
        "app.options.order_flow.state.get_stream_greeks",
        lambda sym: {"gamma": 0.11, "gamma_ts_recv": now})
    assert refresh_gamma_surface_from_stream(_CONTRACT_SYMBOL, now) == "ok"

    later = time.time()
    monkeypatch.setattr(
        "app.options.order_flow.state.get_stream_greeks",
        lambda sym: {"gamma": 0.22, "gamma_ts_recv": later})
    assert refresh_gamma_surface_from_stream(_CONTRACT_SYMBOL, later) == "ok", (
        "an immediately-successive call must execute in full, never return a synthetic "
        "'debounced'/skipped status"
    )
    with server._terrain_cache_lock:
        cached = server._terrain_cache[TK]["_gamma_surface"]
    assert cached["surface_seq"] == 2, "both calls must have actually published"


# ─────────────────────────────────────────────────────────────────────────────
# RC-UI-3 (2026-09-12) — the A-then-B overwrite reproduction. Independent-review finding,
# REPRODUCED against these exact production functions: refreshing_gamma_surface_from_stream
# used to overlay a single-entry {contract_symbol: greeks} map for whichever ONE contract's
# tick triggered THAT call, onto the untouched RAW REST baseline -- so B's refresh silently
# discarded A's already-applied fresh overlay, even though A's fresh value remained
# genuinely available. Fixed by _desired_stream_greeks_for_ticker: every refresh gathers
# EVERY currently-desired contract's live streamed state fresh, every time.
# ─────────────────────────────────────────────────────────────────────────────

def test_refreshing_b_does_not_undo_a_the_a_then_b_overwrite_reproduction(monkeypatch):
    """A is primary (setup_function's default), B is additional. A ticks first and its
    overlay applies; B ticks second and its own overlay must apply TOGETHER WITH A's,
    not instead of it."""
    import app.options.order_flow.streaming as ofs
    ofs._active_option_contracts = [ofs.ticker_storage_key(_CONTRACT_SYMBOL_B)]

    baseline_ts = time.time() - 10.0
    _put_rest_baseline(computed_ts_utc=baseline_ts)
    now_a = time.time()
    streamed_a = {"gamma": 0.5, "gamma_ts_recv": now_a}
    streamed_b = {"gamma": 0.7, "gamma_ts_recv": now_a}
    live = {_CONTRACT_SYMBOL: streamed_a, _CONTRACT_SYMBOL_B: streamed_b}
    monkeypatch.setattr(
        "app.options.order_flow.state.get_stream_greeks", lambda sym: live.get(sym))

    assert refresh_gamma_surface_from_stream(_CONTRACT_SYMBOL, now_a) == "ok"
    with server._terrain_cache_lock:
        after_a = server._terrain_cache[TK]["_gamma_surface"]
    overlaid_a_only, n_a = overlay_streamed_contract_fields(_CONTRACTS, {_CONTRACT_SYMBOL: streamed_a})
    assert n_a == 1
    assert after_a["cells"] == project_gamma_surface(overlaid_a_only, _SPOT)["cells"], (
        "A's own overlay must apply first")

    # B ticks. A's streamed value is STILL live (the mock is unchanged) -- never surrendered.
    now_b = now_a + 0.01
    assert refresh_gamma_surface_from_stream(_CONTRACT_SYMBOL_B, now_b) == "ok"

    overlaid_both, n_both = overlay_streamed_contract_fields(
        _CONTRACTS, {_CONTRACT_SYMBOL: streamed_a, _CONTRACT_SYMBOL_B: streamed_b})
    assert n_both == 2
    expected_after_b = project_gamma_surface(overlaid_both, _SPOT)
    with server._terrain_cache_lock:
        after_b = server._terrain_cache[TK]["_gamma_surface"]
    assert after_b["cells"] == expected_after_b["cells"], (
        "refreshing B must not undo A's already-applied fresh overlay -- THE defect "
        "as independently reproduced")
    assert after_b["stream_overlay_contracts"] == 2, (
        "the published surface must report BOTH contracts as overlaid, not just the "
        "one that triggered this particular refresh")


def test_a_dropped_from_the_desired_set_no_longer_lingers_in_a_later_b_refresh(monkeypatch):
    """The converse control: once A genuinely stops being desired (dropped from both the
    primary and additional slots — its coverage has actually ended), a LATER B refresh
    must reflect ONLY the currently-desired set. Proves this is reconstructed fresh on
    every call, not an unbounded accumulator that never forgets a symbol."""
    import app.options.order_flow.streaming as ofs
    ofs._active_option_contracts = [ofs.ticker_storage_key(_CONTRACT_SYMBOL_B)]

    baseline_ts = time.time() - 10.0
    _put_rest_baseline(computed_ts_utc=baseline_ts)
    now = time.time()
    streamed_a = {"gamma": 0.5, "gamma_ts_recv": now}
    streamed_b = {"gamma": 0.7, "gamma_ts_recv": now}
    live = {_CONTRACT_SYMBOL: streamed_a, _CONTRACT_SYMBOL_B: streamed_b}
    monkeypatch.setattr(
        "app.options.order_flow.state.get_stream_greeks", lambda sym: live.get(sym))
    assert refresh_gamma_surface_from_stream(_CONTRACT_SYMBOL, now) == "ok"

    # A's coverage genuinely ends: no longer primary, never additional, and its live
    # streamed state is gone (clear_symbol removes it in production).
    ofs._active_option_contract = None
    del live[_CONTRACT_SYMBOL]

    assert refresh_gamma_surface_from_stream(_CONTRACT_SYMBOL_B, now + 0.01) == "ok"
    overlaid_b_only, n_b = overlay_streamed_contract_fields(_CONTRACTS, {_CONTRACT_SYMBOL_B: streamed_b})
    assert n_b == 1
    expected = project_gamma_surface(overlaid_b_only, _SPOT)
    with server._terrain_cache_lock:
        cached = server._terrain_cache[TK]["_gamma_surface"]
    assert cached["cells"] == expected["cells"], "A must not linger once it truly stops being desired"
    assert cached["stream_overlay_contracts"] == 1
