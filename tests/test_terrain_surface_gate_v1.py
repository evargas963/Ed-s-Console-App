"""A chain the daemon delivers is priced through _publish_levels (_price_chain): the gamma surface
is shaped exactly once, from the books the levels were priced into, and a shaping failure is
reported, never half-published. Heavy leaf deps are monkeypatched."""
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


#: A REAL complete Schwab capture (native rows verbatim): the chain the daemon delivers.
_REAL_CHAIN = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "real_cde_complete_chain_half_dollar.json")
    .read_text(encoding="utf-8"))["chain"]



@pytest.fixture(autouse=True)
def _at_capture(pin_clock):
    """Valued at the stored chain's capture (2026-09-02 10:05 ET), so its expiries passing never change
    what this test measures."""
    return pin_clock(2026, 9, 2, 10, 5)


def _stub_terrain(monkeypatch, proj):
    monkeypatch.setattr(server, "resolve_spot", lambda t, **k: (100.0, "stub", 0.0))
    monkeypatch.setattr(server, "compute_terrain", lambda tk, contracts, spot, **k: Snap(contracts))
    monkeypatch.setattr(server, "_log_flip_drift", lambda *a, **k: None)
    monkeypatch.setattr(server, "_atr_pair", lambda t: AtrPair(None, None, "stand-in", "stand-in"))
    monkeypatch.setattr(server, "project_gamma_surface", proj)


def _deliver(tk, fetched_ts=None):
    """The daemon's chain of `tk`, priced as the console prices every chain it is delivered."""
    server._price_chain(tk, [dict(ct) for ct in _REAL_CHAIN],
                        time.time() if fetched_ts is None else fetched_ts)


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
    return (server.terrain_cache_get(tk) or {}).get("_gamma_surface")


def test_producer_projects_every_tickers_heatmap(monkeypatch, view):
    """Every ticker's heatmap is projected at its publication, viewed or not (operator,
    2026-10-01: "when i switch tickers the heatmap doesnt render right away")."""
    tk = server.ticker_storage_key("SPY")
    server._gamma_surface_seq.pop(tk, None)   # surface_seq is a running per-ticker counter
    calls = {"n": 0, "args": None}

    def proj(contracts, books):
        calls["n"] += 1
        calls["args"] = (len(contracts), books)
        return {"expirations": [], "strikes": [], "cells": []}

    _stub_terrain(monkeypatch, proj)

    # no page open: shaped EXACTLY ONCE, from that chain's contracts and the snapshot's books
    _deliver(tk)
    assert calls["n"] == 1
    assert calls["args"] == (len(_REAL_CHAIN), {("2026-09-04", 0.0): ({}, ExposureDiagnostics(0, 0, 0, ""))})
    surf = dict(_cached_surface(tk))
    assert isinstance(surf.pop("stream_overlay_computed_ts_utc"), float)
    # the spot that priced this generation travels with it; no contract was streaming
    assert surf == {
        "expirations": [], "strikes": [], "cells": [], "stream_overlay_contracts": 0,
        "stream_overlay_symbols": [], "surface_seq": server._GAMMA_SURFACE_SEQ_START + 1,
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
    _deliver(tk)
    assert server.terrain_cache_get(tk) is None      # nothing half-published
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
    # Newer-than-REST-baseline precedence (RC-UI-2): the streamed value must be newer than the
    # chain's fetch time to override it. A far-future stamp keeps this test about the overlay
    # WIRING, not about the precedence rule (the last test here holds that).
    streamed["gamma_ts_recv"] = _time.time() + 3600.0
    monkeypatch.setattr(
        "app.options.order_flow.streaming.get_active_option_contract",
        lambda: contract_symbol)
    monkeypatch.setattr(
        "app.options.order_flow.state.get_stream_greeks",
        lambda sym: streamed if sym == contract_symbol else None)
    _daemon_holds(contract_symbol)

    view(tk)
    _deliver(tk)

    surf = _cached_surface(tk)
    assert surf["_overlaid_gamma"] == 0.777, "project_gamma_surface must see the overlaid gamma"
    assert surf["stream_overlay_contracts"] == 1
    assert surf["surface_seq"] == server._GAMMA_SURFACE_SEQ_START + 1

    assert priced["snap"].contracts[0]["gamma"] == 0.777, "the levels are priced from the overlay too"
    cached = server.terrain_cache_get(tk)
    assert cached["_chain"] == _REAL_CHAIN, "the raw chain is kept, unoverlaid"
    assert cached["_chain_fetched_ts"] <= cached["computed_ts_utc"]


def test_each_publication_carries_its_own_surface_seq(monkeypatch, view):
    """The surface is published with its seq already on it, so no reader sees a new surface_seq
    with the previous payload: each delivered chain's surface carries the next number."""
    tk = server.ticker_storage_key("SPY")
    server._gamma_surface_seq.pop(tk, None)

    def proj(contracts, books):
        return {"expirations": [], "strikes": [], "cells": []}

    _stub_terrain(monkeypatch, proj)
    view(tk)
    seqs = []
    for i in range(2):
        _deliver(tk, fetched_ts=1000.0 + i)
        seqs.append(server.terrain_cache_get(tk)["_gamma_surface"]["surface_seq"])
    with server._terrain_cache_lock:
        server._terrain_cache.pop(tk, None)
    assert seqs[0] > server._GAMMA_SURFACE_SEQ_START          # counted on from this console's start
    assert seqs[1] == seqs[0] + 1


def test_a_stream_observation_after_the_chain_fetch_is_admitted_and_one_before_is_not(monkeypatch, view):
    """The overlay's freshness baseline is the instant the daemon received the chain (its fetch
    time, carried with it), not any later point of its delivery or pricing: a streamed value
    observed after the fetch overrides the chain's own value; one observed before it does not."""
    tk = server.ticker_storage_key("CDE")
    contract_symbol = _REAL_CHAIN[0]["symbol"]
    fetched_ts = time.time() - 5.0
    observed = {}
    monkeypatch.setattr(server, "_terrain_cache", {})       # no newer chain held from another test

    def proj(contracts, books):
        return {"expirations": [], "strikes": [], "cells": [],
                "_overlaid_gamma": contracts[0].get("gamma")}

    _stub_terrain(monkeypatch, proj)
    monkeypatch.setattr(
        "app.options.order_flow.streaming.get_active_option_contract",
        lambda: contract_symbol)
    monkeypatch.setattr(
        "app.options.order_flow.state.get_stream_greeks",
        lambda sym: {"gamma": 0.777, "gamma_ts_recv": observed["ts"]})
    _daemon_holds(contract_symbol)
    view(tk)

    server._gamma_surface_seq.pop(tk, None)
    observed["ts"] = fetched_ts + 0.001                      # after the fetch
    _deliver(tk, fetched_ts)
    surf = _cached_surface(tk)
    assert surf["stream_overlay_contracts"] == 1 and surf["_overlaid_gamma"] == 0.777

    observed["ts"] = fetched_ts - 0.001                      # before it
    _deliver(tk, fetched_ts)
    surf = _cached_surface(tk)
    assert surf["stream_overlay_contracts"] == 0
    assert surf["_overlaid_gamma"] == _REAL_CHAIN[0]["gamma"]
