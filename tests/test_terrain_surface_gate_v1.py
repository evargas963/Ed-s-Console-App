"""RC-UI-1 #1 — behavioral proof at the REAL producer branch: _terrain_refresh_one projects the
gamma surface only for a demanded (viewed) ticker, exactly once with that cycle's contracts+spot, and
a projection failure never fails the terrain refresh. Heavy leaf deps are monkeypatched (existing
seam); no new production abstraction was created to make this testable."""
import json
import time
import types
from pathlib import Path

import server

#: A REAL complete Schwab capture (native rows verbatim) stands in for the cycle's flattened
#: chain — the producer hands project_gamma_surface whatever flatten_chain_contracts returns.
_REAL_CHAIN = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "real_cde_complete_chain_half_dollar.json")
    .read_text(encoding="utf-8"))["chain"]


def _stub_terrain(monkeypatch, proj):
    class R:
        status_code = 200
        def json(self):  # noqa: D401 - stub
            return {"x": 1}

    class Snap:
        profile = {}
        per_strike = {}
        oi_by_strike = {}
        confidence = None
        def to_dict(self):
            return {}

    monkeypatch.setattr(server, "_terrain_quarantine_blocks", lambda t: False)
    monkeypatch.setattr(server, "get_client", lambda: object())
    monkeypatch.setattr(server, "_universal_capture_wanted", lambda t: (False, None))
    monkeypatch.setattr(server, "_terrain_strike_count", lambda t: 60)
    monkeypatch.setattr(server, "_gated_safe_get_chain", lambda *a, **k: (R(), 0.0, 0.0))
    monkeypatch.setattr(server, "flatten_chain_contracts", lambda j: [dict(ct) for ct in _REAL_CHAIN])
    monkeypatch.setattr(server, "resolve_spot", lambda t, chain_json=None: (100.0, "stub", 0.0))
    monkeypatch.setattr(server, "_persist_universal_complete_chain", lambda *a, **k: None)
    monkeypatch.setattr(server, "_learn_strike_geometry", lambda *a, **k: None)
    monkeypatch.setattr(server, "compute_terrain", lambda *a, **k: Snap())
    monkeypatch.setattr(server, "_accrue_chain_observation", lambda *a, **k: None)
    monkeypatch.setattr(server, "_log_flip_drift", lambda *a, **k: None)
    monkeypatch.setattr(server, "_radar_atr", lambda t: types.SimpleNamespace(daily=None, m15=None))
    monkeypatch.setattr(server, "_note_terrain_success", lambda t: None)
    monkeypatch.setattr(server, "project_gamma_surface", proj)


def _cached_surface(tk):
    return (server.terrain_cache_get(tk) or {}).get("_gamma_surface")


def test_producer_gates_projection_on_demand(monkeypatch):
    tk = server.ticker_storage_key("SPY")
    server._gamma_surface_seq.pop(tk, None)   # surface_seq is a running per-ticker counter
    calls = {"n": 0, "args": None}

    def proj(contracts, spot):
        calls["n"] += 1
        calls["args"] = (len(contracts), spot)
        return {"expirations": [], "strikes": [], "cells": []}

    _stub_terrain(monkeypatch, proj)

    # UNWANTED ticker -> the producer path does NOT invoke project_gamma_surface
    server._gamma_surface_demand.pop(tk, None)
    server._terrain_refresh_one(tk)
    assert calls["n"] == 0
    assert _cached_surface(tk) is None

    # WANTED ticker -> invoked EXACTLY ONCE, with that cycle's contracts + live spot
    server._note_gamma_surface_demand(tk)
    server._terrain_refresh_one(tk)
    assert calls["n"] == 1
    assert calls["args"] == (len(_REAL_CHAIN), 100.0)
    # RC-UI-2: the producer now stamps how many contracts the streaming overlay touched this
    # cycle (0 here -- no option contract is streaming in this test) and a per-ticker
    # publication counter (surface_seq), alongside the faucet's own cells/strikes/expirations,
    # which are otherwise unchanged.
    assert _cached_surface(tk) == {
        "expirations": [], "strikes": [], "cells": [], "stream_overlay_contracts": 0,
        "surface_seq": 1,
    }

    server._gamma_surface_demand.pop(tk, None)


def test_projection_failure_does_not_fail_terrain_refresh(monkeypatch):
    tk = server.ticker_storage_key("SPY")

    def boom(contracts, spot):
        raise RuntimeError("projection boom")

    _stub_terrain(monkeypatch, boom)
    server._note_gamma_surface_demand(tk)
    res = server._terrain_refresh_one(tk)          # wanted, but the projection raises
    assert not str(res).startswith("error")        # terrain refresh still succeeded
    assert _cached_surface(tk) is None             # surface absent -> endpoint falls back to reference
    server._gamma_surface_demand.pop(tk, None)


def test_producer_overlays_the_active_streaming_contract_before_projecting(monkeypatch):
    """RC-UI-2: when an option contract for THIS ticker is actively streaming fresher
    GAMMA/DELTA/OPEN_INTEREST than the cycle's own REST chain, the producer must pass the
    OVERLAID contracts to project_gamma_surface, not the raw REST list -- and it must persist
    the raw REST list + spot so a LATER streamed tick can refresh the cache eagerly
    (refresh_gamma_surface_from_stream) without a second vendor fetch."""
    contract_symbol = _REAL_CHAIN[0]["symbol"]                # "CDE   260904C00005000"
    tk = server.ticker_storage_key("CDE")                     # must match the streaming root
    server._gamma_surface_seq.pop(tk, None)
    streamed = {"gamma": 0.777, "gamma_ts_recv": None}  # ts_recv patched to "now" below

    def proj(contracts, spot):
        return {"expirations": [], "strikes": [], "cells": [],
                "_overlaid_gamma": contracts[0].get("gamma")}

    _stub_terrain(monkeypatch, proj)
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

    server._note_gamma_surface_demand(tk)
    server._terrain_refresh_one(tk)

    surf = _cached_surface(tk)
    assert surf["_overlaid_gamma"] == 0.777, "project_gamma_surface must see the overlaid gamma"
    assert surf["stream_overlay_contracts"] == 1
    assert surf["surface_seq"] == 1

    cached = server.terrain_cache_get(tk)
    assert cached["_contracts_rest"] == _REAL_CHAIN, "the RAW REST chain is retained, unoverlaid"
    assert cached["_contracts_rest_spot"] == 100.0
    # finding #4 (independent review, 2026-09-12), REPRODUCED then fixed: the CAS/precedence
    # generation marker must be the REST FETCH instant, not this cycle's full-computation
    # completion time (compute_terrain can take real, non-trivial time) -- otherwise a stream
    # value that genuinely postdates the REST DATA but arrives before compute_terrain finishes
    # is wrongly judged "not newer than REST" and discarded. The two are therefore no longer
    # required to be equal -- only ordered, fetch always at or before the cycle's own finish.
    assert cached["_contracts_rest_computed_ts"] <= cached["computed_ts_utc"], (
        "the REST-fetch generation marker must be at or before this cycle's full computation finish"
    )

    # finding #2 (independent review, 2026-09-12), REPRODUCED then fixed: the heatmap
    # (_gamma_surface, asserted above via _overlaid_gamma) and the Strike Detail /
    # GEX-by-strike panel (_per_strike) must NOT disagree on the same strike -- _per_strike
    # must ALSO be built from the overlaid contracts, not `snap`'s own un-overlaid ones.
    overlaid_contracts = [dict(c) for c in _REAL_CHAIN]
    overlaid_contracts[0]["gamma"] = 0.777
    expected_per_strike = server._per_strike_view_from_contracts(overlaid_contracts, 100.0)
    assert cached["_per_strike"] == expected_per_strike, (
        "_per_strike must be rebuilt from the SAME overlaid contracts as _gamma_surface"
    )

    server._gamma_surface_demand.pop(tk, None)


def test_surface_seq_publication_is_atomic_with_the_cache_write(monkeypatch):
    """Independent-review finding (2026-09-12, state-authority review), REPRODUCED: the seq
    bump (_next_gamma_surface_seq, which ALSO pushes the SSE 'gamma_surface_seq' notify) used
    to run inside its OWN, EARLIER `with _terrain_cache_lock:` block -- a real gap of several
    statements (and a possible exception) before `_terrain_cache[tk] = payload` in a SECOND,
    later lock acquisition. Any reader in that window (an SSE subscriber reacting to the
    notify by immediately re-fetching, or an ordinary concurrent poll) could acquire the
    now-released lock and observe the NEW surface_seq while `_terrain_cache[tk]` still held
    the PREVIOUS cycle's payload -- publication announced before the published data was
    visible ("the REST producer can announce surface revision 2 while the serving cache
    still returns revision 1").

    This proves the STRUCTURAL fix directly rather than racing real threads against a gap of
    a few Python statements (unreliable to hit deterministically): the seq bump and the
    cache write must now occur under the SAME lock acquisition (the same `with
    _terrain_cache_lock:` __enter__ call), so no other thread can ever acquire that lock in
    between them -- exactly how refresh_gamma_surface_from_stream (the eager stream path)
    already does it correctly.
    """
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

    def proj(contracts, spot):
        return {"expirations": [], "strikes": [], "cells": []}

    _stub_terrain(monkeypatch, proj)
    server._note_gamma_surface_demand(tk)
    server._terrain_refresh_one(tk)

    assert seen["seq_call_enter_n"] is not None, "the surface-seq path was not exercised"
    assert seen["cache_write_enter_n"] is not None, "the cache write for this ticker never happened"
    assert seen["seq_call_enter_n"] == seen["cache_write_enter_n"], (
        f"the seq bump (lock __enter__ #{seen['seq_call_enter_n']}) and the cache write "
        f"(lock __enter__ #{seen['cache_write_enter_n']}) happened under DIFFERENT lock "
        f"acquisitions -- a concurrent reader could acquire the lock in the gap between "
        f"them and observe the new surface_seq with the old cached payload"
    )
    server._gamma_surface_demand.pop(tk, None)


def test_a_stream_observation_between_rest_fetch_and_computation_completion_is_admitted(monkeypatch):
    """Independent-review finding (2026-09-12), REPRODUCED against this exact production path
    before being fixed: 'I supplied REST data at time 400, a stream update at 401, and
    computation completion at 402. The update was rejected because 402 became the supposed REST
    freshness boundary.' The old code stamped the CAS/precedence marker AFTER compute_terrain
    (a real computation, not the REST observation) -- a stream value causally AFTER the REST
    fetch but arriving DURING that computation was incorrectly judged older than the REST data
    it should have overlaid. This drives a real elapsed gap between fetch and computation
    completion (a controlled sleep in the compute_terrain stub, not a hand-set timestamp), and
    proves a stream observation timestamped inside that real gap is admitted."""
    tk = server.ticker_storage_key("CDE")
    contract_symbol = _REAL_CHAIN[0]["symbol"]

    captured = {}

    class Snap:
        profile = {}
        per_strike = {}
        oi_by_strike = {}
        confidence = None
        def to_dict(self):
            return {}

    def slow_compute_terrain(*a, **k):
        # This runs AFTER the REST fetch (server.py captures _rest_fetch_ts immediately once
        # the 200 response is in hand, before this is ever called) and BEFORE
        # payload["computed_ts_utc"] is stamped -- a real elapsed window between the two.
        captured["mid_computation_ts"] = time.time()
        time.sleep(0.05)
        return Snap()

    def proj(contracts, spot):
        return {"expirations": [], "strikes": [], "cells": [],
                "_overlaid_gamma": contracts[0].get("gamma")}

    _stub_terrain(monkeypatch, proj)
    monkeypatch.setattr(server, "compute_terrain", slow_compute_terrain)
    monkeypatch.setattr(
        "app.options.order_flow.streaming.get_active_option_contract",
        lambda: contract_symbol)

    def _stream_arrived_mid_computation(sym):
        # The streamed observation's OWN receive time: causally after the REST fetch (which
        # already completed by the time compute_terrain started) but before compute_terrain
        # -- and therefore payload["computed_ts_utc"] -- finishes.
        return {"gamma": 0.777, "gamma_ts_recv": captured["mid_computation_ts"] + 0.001}

    monkeypatch.setattr(
        "app.options.order_flow.state.get_stream_greeks", _stream_arrived_mid_computation)

    server._gamma_surface_seq.pop(tk, None)
    server._note_gamma_surface_demand(tk)
    server._terrain_refresh_one(tk)

    surf = _cached_surface(tk)
    assert surf["stream_overlay_contracts"] == 1, (
        "a stream observation that postdates the REST fetch must be admitted even when it "
        "arrives before the REST cycle's own (later) computation finishes"
    )
    assert surf["_overlaid_gamma"] == 0.777

    server._gamma_surface_demand.pop(tk, None)
