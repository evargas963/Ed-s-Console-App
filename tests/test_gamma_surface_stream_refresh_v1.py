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


def _put_rest_baseline():
    with server._terrain_cache_lock:
        server._terrain_cache[TK] = {
            "_contracts_rest": _CONTRACTS,
            "_contracts_rest_spot": _SPOT,
            "_gamma_surface": project_gamma_surface(_CONTRACTS, _SPOT),
            "computed_ts_utc": time.time(),
        }


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
    _put_rest_baseline()
    now = time.time()
    streamed = {"gamma": 0.5, "gamma_ts_recv": now, "delta": 0.9, "delta_ts_recv": now,
                "open_interest": 99999.0, "open_interest_ts_recv": now}
    monkeypatch.setattr(
        "app.options.order_flow.state.get_stream_greeks",
        lambda sym: streamed if sym == _CONTRACT_SYMBOL else None)

    status = refresh_gamma_surface_from_stream(_CONTRACT_SYMBOL, now)
    assert status == "ok"

    overlaid, n = overlay_streamed_contract_fields(_CONTRACTS, {_CONTRACT_SYMBOL: streamed})
    assert n == 1
    expected = project_gamma_surface(overlaid, _SPOT)

    with server._terrain_cache_lock:
        cached = server._terrain_cache[TK]["_gamma_surface"]
    # the faucet's own cells/strikes/expirations must match the independently-computed
    # expectation exactly -- proves the wiring calls the SAME projection, not a reimplementation
    assert cached["cells"] == expected["cells"]
    assert cached["strikes"] == expected["strikes"]
    assert cached["expirations"] == expected["expirations"]
    assert cached["stream_overlay_contracts"] == 1
    assert cached["stream_overlay_latency_ms"] >= 0
    # the untouched REST baseline in the cache is unchanged by the eager overlay
    with server._terrain_cache_lock:
        assert server._terrain_cache[TK]["_contracts_rest"] == _CONTRACTS


def test_repeated_eager_refreshes_never_compound_away_from_the_rest_baseline(monkeypatch):
    """Each call overlays onto the STORED _contracts_rest, never onto a previously-overlaid
    result -- so two refreshes with two DIFFERENT streamed values produce the surface for the
    SECOND value alone, not an accumulation of both."""
    _put_rest_baseline()
    now = time.time()
    monkeypatch.setattr(
        "app.options.order_flow.state.get_stream_greeks",
        lambda sym: {"gamma": 0.11, "gamma_ts_recv": now})
    assert refresh_gamma_surface_from_stream(_CONTRACT_SYMBOL, now) == "ok"

    monkeypatch.setattr(
        "app.options.order_flow.state.get_stream_greeks",
        lambda sym: {"gamma": 0.22, "gamma_ts_recv": now})
    assert refresh_gamma_surface_from_stream(_CONTRACT_SYMBOL, now) == "ok"

    overlaid, _ = overlay_streamed_contract_fields(
        _CONTRACTS, {_CONTRACT_SYMBOL: {"gamma": 0.22, "gamma_ts_recv": now}})
    expected = project_gamma_surface(overlaid, _SPOT)
    with server._terrain_cache_lock:
        cached = server._terrain_cache[TK]["_gamma_surface"]
    assert cached["cells"] == expected["cells"], (
        "the second refresh must reflect ONLY gamma=0.22, not gamma=0.11 carried forward"
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
