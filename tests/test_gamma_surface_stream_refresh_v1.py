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
TK = ticker_storage_key("CRWD")


def _clear_cache():
    with server._terrain_cache_lock:
        server._terrain_cache.pop(TK, None)
    server._gamma_surface_stream_refresh_last_ts.pop(TK, None)


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


def setup_function(_fn):
    _clear_cache()


def teardown_function(_fn):
    _clear_cache()


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

    # bypass the debounce (a separate property, covered by its own tests below) so this test's
    # own concern -- compounding across repeated REAL executions -- is actually exercised.
    server._gamma_surface_stream_refresh_last_ts.pop(TK, None)
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


def test_a_burst_of_ticks_is_debounced_to_bound_backlog(monkeypatch):
    """MEASURED (2026-09-12, SYNTHETIC SCALE BASELINE): a single refresh_gamma_surface_from_stream
    call takes ~3.1s on a full SPXW-scale book (~42k contracts) and runs synchronously inside
    the daemon's one replay-poll worker -- an unbounded burst of ticks for a large-book contract
    would otherwise queue linearly and starve every other ticker sharing that worker. A second
    call within the debounce window must be skipped entirely (no overlay/projection work), not
    merely produce the same result more expensively."""
    baseline_ts = time.time() - 10.0
    _put_rest_baseline(computed_ts_utc=baseline_ts)
    now = time.time()
    calls = {"n": 0}

    def _spy_greeks(sym):
        calls["n"] += 1
        return {"gamma": 0.11, "gamma_ts_recv": now}

    monkeypatch.setattr("app.options.order_flow.state.get_stream_greeks", _spy_greeks)
    assert refresh_gamma_surface_from_stream(_CONTRACT_SYMBOL, now) == "ok"
    assert calls["n"] == 1
    # immediately after -- well inside the debounce window -- must be skipped BEFORE even
    # reading streamed greeks (proves the expensive path is never entered, not just short-circuited late)
    assert refresh_gamma_surface_from_stream(_CONTRACT_SYMBOL, time.time()) == "debounced"
    assert calls["n"] == 1, "a debounced call must not even read streamed greeks, let alone recompute"


def test_debounce_clears_after_the_minimum_interval_elapses(monkeypatch):
    baseline_ts = time.time() - 10.0
    _put_rest_baseline(computed_ts_utc=baseline_ts)
    now = time.time()
    monkeypatch.setattr(
        "app.options.order_flow.state.get_stream_greeks",
        lambda sym: {"gamma": 0.11, "gamma_ts_recv": now})
    assert refresh_gamma_surface_from_stream(_CONTRACT_SYMBOL, now) == "ok"
    # simulate real elapsed time having passed, rather than sleeping the test
    server._gamma_surface_stream_refresh_last_ts[TK] -= (
        server.GAMMA_SURFACE_STREAM_REFRESH_MIN_INTERVAL_SEC + 0.01)
    later = time.time()
    monkeypatch.setattr(
        "app.options.order_flow.state.get_stream_greeks",
        lambda sym: {"gamma": 0.22, "gamma_ts_recv": later})
    assert refresh_gamma_surface_from_stream(_CONTRACT_SYMBOL, later) == "ok"


def test_debounce_is_per_ticker_not_global(monkeypatch):
    """A burst on one ticker's contract must not delay a genuinely different ticker."""
    other_tk = ticker_storage_key("CDE")
    other_symbol = "CDE   260904C00005000"
    other_contracts = [dict(_CONTRACTS[0], symbol=other_symbol, strikePrice=5.0)]
    with server._terrain_cache_lock:
        server._terrain_cache[other_tk] = {
            "_contracts_rest": other_contracts, "_contracts_rest_spot": _SPOT,
            "_contracts_rest_computed_ts": time.time() - 10.0,
            "_gamma_surface": project_gamma_surface(other_contracts, _SPOT),
            "computed_ts_utc": time.time() - 10.0,
        }
    server._gamma_surface_stream_refresh_last_ts.pop(other_tk, None)
    try:
        now = time.time()
        _put_rest_baseline(computed_ts_utc=now - 10.0)
        monkeypatch.setattr(
            "app.options.order_flow.state.get_stream_greeks",
            lambda sym: {"gamma": 0.11, "gamma_ts_recv": now}
            if sym == _CONTRACT_SYMBOL else {"gamma": 0.22, "gamma_ts_recv": now})
        assert refresh_gamma_surface_from_stream(_CONTRACT_SYMBOL, now) == "ok"
        assert refresh_gamma_surface_from_stream(other_symbol, now) == "ok", (
            "a different ticker's contract must not be debounced by the first ticker's activity"
        )
    finally:
        with server._terrain_cache_lock:
            server._terrain_cache.pop(other_tk, None)
        server._gamma_surface_stream_refresh_last_ts.pop(other_tk, None)
