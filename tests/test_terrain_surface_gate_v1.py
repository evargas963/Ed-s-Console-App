"""The terrain loop's chain fetch publishes through _publish_levels: the gamma surface is shaped
only for a demanded (viewed) ticker, exactly once, from the books the levels were priced into,
and a shaping failure is reported, never half-published. Heavy leaf deps are monkeypatched."""
import json
import time
from pathlib import Path

import pytest

import live_market_plane as lmp
import server
from math_exposure_core import ExposureDiagnostics
from terrain_atr import AtrPair


def _daemon_holds(*symbols):
    """The daemon's heartbeat: Schwab socket open, these contracts held on LEVELONE_OPTIONS."""
    lmp.record_feed_heartbeat({"schwab_socket_open": True,
                               "held": {"LEVELONE_OPTIONS": list(symbols)}}, time.time())


#: A REAL complete Schwab capture (native rows verbatim) stands in for the cycle's flattened
#: chain — the producer hands project_gamma_surface whatever flatten_chain_contracts returns.
_REAL_CHAIN = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "real_cde_complete_chain_half_dollar.json")
    .read_text(encoding="utf-8"))["chain"]



@pytest.fixture(autouse=True)
def _at_capture(pin_clock):
    """Valued at the stored chain's capture (2026-09-02 10:05 ET), so its expiries passing never change
    what this test measures."""
    return pin_clock(2026, 9, 2, 10, 5)

@pytest.fixture(autouse=True)
def _session_open(monkeypatch):
    """These tests are about the open market: levels are computed only then (closed-market
    behaviour: tests/test_one_levels_producer_v1.py)."""
    monkeypatch.setattr(server, "_is_loggable_session", lambda now: True)


def _stub_terrain(monkeypatch, proj):
    class R:
        status_code = 200
        def json(self):  # noqa: D401 - stub
            return {"x": 1}

    monkeypatch.setattr(server, "_terrain_quarantine_blocks", lambda t, now: False)
    monkeypatch.setattr(server, "get_client", lambda: object())
    monkeypatch.setattr(server, "_gated_safe_get_chain", lambda *a, **k: (R(), 0.0, 0.0))
    monkeypatch.setattr(server, "flatten_chain_contracts", lambda j: [dict(ct) for ct in _REAL_CHAIN])
    monkeypatch.setattr(server, "resolve_spot", lambda t, **k: (100.0, "stub", 0.0))
    monkeypatch.setattr(server, "compute_terrain", lambda tk, contracts, spot, **k: Snap(contracts))
    monkeypatch.setattr(server, "_atr_pair", lambda t: AtrPair(None, None, "stand-in", "stand-in"))
    monkeypatch.setattr(server, "_note_terrain_success", lambda t: None)
    monkeypatch.setattr(server, "project_gamma_surface", proj)


class Snap:
    """compute_terrain's stand-in: remembers the contracts it was asked to price."""
    profile = {}
    per_strike = {}
    charm_by_strike = {}
    confidence = None
    spot = 100.0
    # the levels the refresh reads after publishing (level crosses): none computed here. The
    # stand-in lacked them, so every refresh it drove failed at that step, logged and unnoticed.
    call_wall = put_wall = gamma_flip = net_gex_peak = max_pain = call_delta_wall = put_delta_wall = None

    def __init__(self, contracts):
        self.contracts = contracts
        self.books = {("2026-09-04", 0.0): ({}, ExposureDiagnostics(0, 0, 0, ""))}

    def to_dict(self):
        return {}


def _cached_surface(tk):
    return (server.terrain_cache_get(tk, time.time()) or {}).get("_gamma_surface")


def test_producer_gates_projection_on_demand(monkeypatch, view):
    tk = server.ticker_storage_key("SPY")
    server._gamma_surface_seq.pop(tk, None)   # surface_seq is a running per-ticker counter
    calls = {"n": 0, "args": None}

    def proj(contracts, books):
        calls["n"] += 1
        calls["args"] = (len(contracts), books)
        return {"expirations": [], "strikes": [], "cells": []}

    _stub_terrain(monkeypatch, proj)

    # UNWANTED ticker (no page open) -> the producer path does NOT invoke project_gamma_surface
    server._terrain_refresh_one(tk, time.time())
    assert calls["n"] == 0
    assert _cached_surface(tk) is None

    # WANTED ticker -> shaped EXACTLY ONCE, from that cycle's contracts and the snapshot's books
    view(tk)
    server._terrain_refresh_one(tk, time.time())
    assert calls["n"] == 1
    assert calls["args"] == (len(_REAL_CHAIN), {("2026-09-04", 0.0): ({}, ExposureDiagnostics(0, 0, 0, ""))})
    surf = dict(_cached_surface(tk))
    # the spot that priced this generation travels with it; no contract was streaming
    assert surf == {
        "expirations": [], "strikes": [], "cells": [], "stream_overlay_contracts": 0,
        "stream_overlay_symbols": [], "surface_seq": 1,
        "spot": 100.0, "spot_source": "stub", "spot_as_of_ts_utc": 0.0,
        "stream_by_expiry": {},          # each column's served streaming state (none: no columns)
    }


def test_a_projection_failure_is_reported_and_publishes_nothing(monkeypatch, view):
    tk = server.ticker_storage_key("SPY")

    def boom(contracts, books):
        raise RuntimeError("projection boom")

    _stub_terrain(monkeypatch, boom)
    with server._terrain_cache_lock:
        server._terrain_cache.pop(tk, None)
    view(tk)
    res = server._terrain_refresh_one(tk, time.time())
    assert res == "error:RuntimeError"
    assert server.terrain_cache_get(tk, time.time()) is None      # nothing half-published
    assert "projection boom" in server._terrain_refresh_last_error[tk]


def test_producer_overlays_the_active_streaming_contract_before_projecting(monkeypatch, view):
    """An option contract of THIS ticker streaming fresher greeks than the fetched chain is
    overlaid before pricing -- the levels, per-strike rows and surface are all priced from the
    overlaid contracts -- while the raw chain is kept for the next tick-driven reprice."""
    contract_symbol = _REAL_CHAIN[0]["symbol"]                # "CDE   260904C00005000"
    tk = server.ticker_storage_key("CDE")                     # must match the streaming root
    server._gamma_surface_seq.pop(tk, None)
    streamed = {"gamma": 0.777, "gamma_ts_recv": None}  # ts_recv patched to "now" below

    def proj(contracts, books):
        return {"expirations": [], "strikes": [], "cells": [],
                "_overlaid_gamma": contracts[0].get("gamma")}

    _stub_terrain(monkeypatch, proj)
    priced = {}
    monkeypatch.setattr(server, "compute_terrain",
                        lambda tk_, contracts, spot, **k: priced.setdefault("snap", Snap(contracts)))
    import time as _time
    # Newer-than-REST-baseline precedence (RC-UI-2): the producer stamps computed_ts_utc
    # DURING _terrain_refresh_one below, after this line runs -- a plain "now" here would
    # make the streamed value OLDER than the REST baseline it is meant to override, and the
    # precedence rule would correctly reject it. A far-future stamp keeps this test about the
    # overlay WIRING, not about winning a race against the producer's own clock read.
    streamed["gamma_ts_recv"] = _time.time() + 3600.0
    monkeypatch.setattr(
        "app.options.order_flow.streaming.get_active_option_contract",
        lambda: contract_symbol)
    monkeypatch.setattr(
        "app.options.order_flow.state.get_stream_greeks",
        lambda sym: streamed if sym == contract_symbol else None)
    _daemon_holds(contract_symbol)

    view(tk)
    server._terrain_refresh_one(tk, time.time())

    surf = _cached_surface(tk)
    assert surf["_overlaid_gamma"] == 0.777, "project_gamma_surface must see the overlaid gamma"
    assert surf["stream_overlay_contracts"] == 1
    assert surf["surface_seq"] == 1

    assert priced["snap"].contracts[0]["gamma"] == 0.777, "the levels are priced from the overlay too"
    cached = server.terrain_cache_get(tk, time.time())
    assert cached["_chain"] == _REAL_CHAIN, "the raw chain is kept, unoverlaid"
    assert cached["_chain_fetched_ts"] <= cached["computed_ts_utc"]


def test_surface_seq_publication_is_atomic_with_the_cache_write(monkeypatch, view):
    """The seq bump and the cache write happen under one lock acquisition, so no reader sees
    a new surface_seq with the previous payload."""
    tk = server.ticker_storage_key("SPY")
    server._gamma_surface_seq.pop(tk, None)

    class _CountingLockWrapper:
        def __init__(self, real):
            self._real = real
            self.enter_count = 0

        def __enter__(self):
            self.enter_count += 1
            return self._real.__enter__()

        def __exit__(self, *a):
            return self._real.__exit__(*a)

    wrapper = _CountingLockWrapper(server._terrain_cache_lock)
    monkeypatch.setattr(server, "_terrain_cache_lock", wrapper)

    seen = {"seq_call_enter_n": None, "cache_write_enter_n": None}
    real_next_seq = server._next_gamma_surface_seq

    def spy_next_seq(tk_):
        seen["seq_call_enter_n"] = wrapper.enter_count
        return real_next_seq(tk_)
    monkeypatch.setattr(server, "_next_gamma_surface_seq", spy_next_seq)

    class _WatchedCache(dict):
        def __setitem__(self, key, value):
            if key == tk:
                seen["cache_write_enter_n"] = wrapper.enter_count
            return super().__setitem__(key, value)
    monkeypatch.setattr(server, "_terrain_cache", _WatchedCache())

    def proj(contracts, books):
        return {"expirations": [], "strikes": [], "cells": []}

    _stub_terrain(monkeypatch, proj)
    view(tk)
    server._terrain_refresh_one(tk, time.time())

    assert seen["seq_call_enter_n"] is not None, "the surface-seq path was not exercised"
    assert seen["cache_write_enter_n"] is not None, "the cache write for this ticker never happened"
    assert seen["seq_call_enter_n"] == seen["cache_write_enter_n"], (
        f"the seq bump (lock __enter__ #{seen['seq_call_enter_n']}) and the cache write "
        f"(lock __enter__ #{seen['cache_write_enter_n']}) happened under DIFFERENT lock "
        f"acquisitions -- a concurrent reader could acquire the lock in the gap between "
        f"them and observe the new surface_seq with the old cached payload"
    )


def test_terrain_loop_refreshes_a_previewed_ticker_not_on_the_enrolled_board(monkeypatch, view):
    """Independent-review finding (2026-09-12, state-authority review), REPRODUCED: a ticker
    merely PREVIEWED (never enrolled onto _logger_tickers -- TICKER-PREVIEW-NO-ENROLL) got
    exactly ONE on-demand terrain compute (the /api/terrain cache-miss priority path) and
    then NOTHING -- _terrain_loop only ever iterated the enrolled board, so its cache entry
    sat frozen forever while /api/options/gamma-surface kept serving it "live: True" (sourced
    from the live pathway, not "currently fresh") alongside a growing stale age. "Universally
    across supported tickers" requires that viewing ANY ticker keeps it refreshing, not only
    the pre-enrolled board.

    Proven with a REAL cycle of the actual loop function, in a real background thread --
    only the heavy vendor-facing leaves are stubbed (the existing _stub_terrain seam this
    file already uses); the loop's own ticker-selection logic runs unmodified.
    """
    import threading

    calls: list[str] = []

    def proj(contracts, books):
        return {"expirations": [], "strikes": [], "cells": []}
    _stub_terrain(monkeypatch, proj)
    monkeypatch.setattr(server, "_is_loggable_session", lambda now: True)
    monkeypatch.setattr(server, "TERRAIN_REFRESH_SEC", 0.2)
    # midday ET: between 09:30 and 10:00 the loop defers tickers, and this test failed whenever
    # it ran then (2026-09-27 audit); the minute is fixed, not read from the clock
    monkeypatch.setattr(server, "et_minute_total_from_ts_utc", lambda ts_utc: 720)
    real_refresh = server._terrain_refresh_one

    def spy_refresh(tk, now, priority=False):
        calls.append(tk)
        return real_refresh(tk, now, priority=priority)
    monkeypatch.setattr(server, "_terrain_refresh_one", spy_refresh)

    enrolled_tk = server.ticker_storage_key("SPY")
    previewed_tk = server.ticker_storage_key("ZZPREVIEWONLY")
    with server._logger_lock:
        prev_logger_tickers = list(server._logger_tickers)
        server._logger_tickers[:] = [enrolled_tk]
    view(previewed_tk)                                 # a page open on it, never enrolled

    server._terrain_loop_running = True
    t = threading.Thread(target=server._terrain_loop, daemon=True)
    t.start()
    try:
        deadline = time.time() + 5.0
        while time.time() < deadline and previewed_tk not in calls:
            time.sleep(0.05)
    finally:
        server._terrain_loop_running = False
        t.join(timeout=5.0)
        with server._logger_lock:
            server._logger_tickers[:] = prev_logger_tickers

    assert enrolled_tk in calls, "the enrolled ticker must still refresh as before"
    assert previewed_tk in calls, (
        "a ticker with live view demand but never enrolled must still be refreshed by the "
        "terrain loop -- viewing ANY supported ticker must keep it live, not only the "
        "pre-enrolled board")


def test_nothing_is_refreshed_while_the_market_is_closed(monkeypatch, view):
    """Operator design 2026-09-26: while the market is closed no chain is downloaded -- not for
    the board, not for a ticker someone is viewing. Weekend chains blank open interest (every
    $SPX contract, 18% of SPY's OI, measured 2026-09-26); the last session's levels stand."""
    import threading

    calls: list[str] = []

    def proj(contracts, books):
        return {"expirations": [], "strikes": [], "cells": []}
    _stub_terrain(monkeypatch, proj)
    monkeypatch.setattr(server, "_is_loggable_session", lambda now: False)
    monkeypatch.setattr(server, "TERRAIN_REFRESH_SEC", 0.2)
    real_refresh = server._terrain_refresh_one
    fetched: list[str] = []
    monkeypatch.setattr(server, "fetch_full_chain", lambda client, tk, get: fetched.append(tk))

    def spy_refresh(tk, now, priority=False):
        calls.append(tk)
        return real_refresh(tk, now, priority=priority)
    monkeypatch.setattr(server, "_terrain_refresh_one", spy_refresh)

    viewed_tk = server.ticker_storage_key("$SPX")
    with server._logger_lock:
        prev_logger_tickers = list(server._logger_tickers)
        server._logger_tickers[:] = [server.ticker_storage_key("SPY")]
    view(viewed_tk)
    server._terrain_loop_running = True
    th = threading.Thread(target=server._terrain_loop, daemon=True)
    th.start()
    try:
        time.sleep(1.0)                       # several 0.2 s cycles
    finally:
        server._terrain_loop_running = False
        th.join(timeout=5.0)
        with server._logger_lock:
            server._logger_tickers[:] = prev_logger_tickers
    assert calls == [], "the loop refreshed a ticker while the market was closed"
    # a direct request (the /api/terrain cold miss) is refused before any vendor call
    assert real_refresh(viewed_tk, time.time(), priority=True) == "skip:market_closed"
    assert fetched == []


def test_a_stream_observation_after_the_chain_fetch_is_admitted(monkeypatch, view):
    """The overlay's freshness baseline is the instant the chain response arrived, not any later
    point of the publication: a streamed value observed after the fetch (here, while the chain
    is still being flattened) overrides the chain's own value."""
    tk = server.ticker_storage_key("CDE")
    contract_symbol = _REAL_CHAIN[0]["symbol"]
    captured = {}

    def proj(contracts, books):
        return {"expirations": [], "strikes": [], "cells": [],
                "_overlaid_gamma": contracts[0].get("gamma")}

    def slow_flatten(_json):
        captured["after_fetch_ts"] = time.time()
        time.sleep(0.05)
        return [dict(ct) for ct in _REAL_CHAIN]

    _stub_terrain(monkeypatch, proj)
    monkeypatch.setattr(server, "flatten_chain_contracts", slow_flatten)
    monkeypatch.setattr(
        "app.options.order_flow.streaming.get_active_option_contract",
        lambda: contract_symbol)
    monkeypatch.setattr(
        "app.options.order_flow.state.get_stream_greeks",
        lambda sym: {"gamma": 0.777, "gamma_ts_recv": captured["after_fetch_ts"] + 0.001})
    _daemon_holds(contract_symbol)

    server._gamma_surface_seq.pop(tk, None)
    view(tk)
    server._terrain_refresh_one(tk, time.time())

    surf = _cached_surface(tk)
    assert surf["stream_overlay_contracts"] == 1
    assert surf["_overlaid_gamma"] == 0.777
