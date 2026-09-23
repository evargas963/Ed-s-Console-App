"""refresh_gamma_surface_from_spot_tick / _dispatch_spot_gamma_refresh (server.py).

CONFIRMED ROOT DEFECT (2026-09-17): the header's spot updates on every streamed
LEVELONE_EQUITIES tick (live_market_plane -> resolve_spot's own top-priority source), but
refresh_gamma_surface_from_stream only ever fires on a streamed OPTION contract's own
greeks tick -- a spot-only tick (no option contract ticking at the same instant) never
recomputed the gamma surface at all, leaving every spot-dependent dollar cell (GEX/DEX/
OI$, all scaled by spot or spot squared) stale for up to the ~60s terrain REST cycle while
the header visibly moved. This file proves the fix: a symmetric eager-refresh path
triggered by spot alone, sharing the SAME canonical faucet and the SAME REST-baseline
compare-and-swap discipline as the existing option-tick path, with its own coalesced,
per-ticker, off-the-ingestion-path dispatcher.

Proven against a REAL captured chain fixture (tests/fixtures/real_crwd_complete_chain_
quarter.json) for the single-expiry cases and the real CRWD+CDE two-expiry union (shared
with tests/test_gamma_surface_projection_v1.py) for the multi-expiry case -- never a
hand-derived expected GEX value."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import server
# RC-REHAB-1 (2026-09-23, module extraction, twenty-seventh slice):
# refresh_gamma_surface_from_spot_tick moved out of server.py entirely, into
# gamma_surface_eager_refresh.py, which imports project_gamma_surface directly
# (module-level, not lazily via `import server`) -- a mock targeting it must patch
# that module's own binding, not server's re-export, to be picked up.
import gamma_surface_eager_refresh as gse
from gamma_surface_eager_refresh import refresh_gamma_surface_from_spot_tick, refresh_gamma_surface_from_stream
from gamma_surface_projection import project_gamma_surface
from instrument_identity import ticker_storage_key
from gamma_surface_eager_refresh import _dispatch_spot_gamma_refresh
import gamma_surface_eager_refresh
import gamma_surface_state
import per_strike_view
import gamma_surface_projection
import terrain_state
import terrain_engine

_FX = Path(__file__).resolve().parent / "fixtures"
_REAL = json.loads((_FX / "real_crwd_complete_chain_quarter.json").read_text(encoding="utf-8"))
_SPOT = float(_REAL["spot"])
_CONTRACTS = [dict(ct) for ct in _REAL["chain"]]
_CONTRACT_SYMBOL = _CONTRACTS[0]["symbol"]
TK = ticker_storage_key("CRWD")
TK2 = ticker_storage_key("ZZZSPOTTICK_ISOLATION")

_CDE = json.loads((_FX / "real_cde_complete_chain_half_dollar.json").read_text(encoding="utf-8"))


def _clear_caches():
    with terrain_state._terrain_cache_lock:
        terrain_state._terrain_cache.pop(TK, None)
        terrain_state._terrain_cache.pop(TK2, None)
    with server._LAST_VALID_GEX_CELLS_LOCK:
        server._LAST_VALID_GEX_CELLS.pop(TK, None)
        server._LAST_VALID_GEX_CELLS_HYDRATED.discard(TK)
        server._LAST_VALID_GEX_CELLS_DB_WRITE_TS[TK] = time.time()
        server._LAST_VALID_GEX_CELLS.pop(TK2, None)
        server._LAST_VALID_GEX_CELLS_HYDRATED.discard(TK2)
        server._LAST_VALID_GEX_CELLS_DB_WRITE_TS[TK2] = time.time()
    with gamma_surface_eager_refresh._spot_gamma_refresh_lock:
        gamma_surface_eager_refresh._spot_gamma_refresh_inflight.discard(TK)
        gamma_surface_eager_refresh._spot_gamma_refresh_pending.discard(TK)
        gamma_surface_eager_refresh._spot_gamma_refresh_inflight.discard(TK2)
        gamma_surface_eager_refresh._spot_gamma_refresh_pending.discard(TK2)


def _put_rest_baseline_with_spot(tk, contracts, spot, *, computed_ts_utc=None):
    """Unlike test_gamma_surface_stream_refresh_v1.py's own _put_rest_baseline, this
    stamps `spot` onto the seeded surface -- matching what PRODUCTION always does
    (_terrain_refresh_one/refresh_gamma_surface_from_stream both stamp it), which
    refresh_gamma_surface_from_spot_tick's own prior-spot comparison depends on."""
    ts = time.time() if computed_ts_utc is None else computed_ts_utc
    surf = project_gamma_surface(contracts, spot)
    surf["spot"] = float(spot)
    surf["spot_source"] = "stub"
    surf["spot_as_of_ts_utc"] = ts
    with terrain_state._terrain_cache_lock:
        terrain_state._terrain_cache[tk] = {
            "_contracts_rest": contracts,
            "_contracts_rest_spot": spot,
            "_contracts_rest_computed_ts": ts,
            "_gamma_surface": surf,
            "computed_ts_utc": ts,
        }
    gamma_surface_state._gamma_surface_seq.pop(tk, None)
    return surf


def setup_function(_fn):
    _clear_caches()


def teardown_function(_fn):
    _clear_caches()


# ---------------------------------------------------------------------------
# 1. Spot-only streamed update
# ---------------------------------------------------------------------------

def test_spot_only_tick_recomputes_surface_bumps_generation_and_changes_gex(monkeypatch):
    new_spot = _SPOT + 5.0   # a real, material move -- no option tick involved at all
    _put_rest_baseline_with_spot(TK, _CONTRACTS, _SPOT)
    with terrain_state._terrain_cache_lock:
        seq_before = terrain_state._terrain_cache[TK]["_gamma_surface"].get("surface_seq")
        gex_before = [row["gex"] for row in terrain_state._terrain_cache[TK]["_gamma_surface"]["cells"]]
    # No option contract is desired at all -- proves this path needs none.
    monkeypatch.setattr("app.options.order_flow.streaming.get_active_option_contracts", lambda: [])
    monkeypatch.setattr("app.options.order_flow.streaming.get_active_option_contract", lambda: None)
    monkeypatch.setattr(server, "resolve_spot", lambda tk, **kw: (new_spot, "stub", time.time()))

    status = refresh_gamma_surface_from_spot_tick(TK)
    assert status == "ok"

    expected = project_gamma_surface(_CONTRACTS, new_spot)
    with terrain_state._terrain_cache_lock:
        cached = terrain_state._terrain_cache[TK]["_gamma_surface"]
    assert cached["spot"] == new_spot
    assert cached.get("spot_tick_triggered") is True
    # surface_seq strictly advanced -- a post-tick render is only proven by a NEWER generation.
    assert seq_before is None or cached["surface_seq"] > seq_before
    # every spot-dependent expiry actually used the new spot -- exact match to an
    # independent full recompute at that spot, not merely "some value changed".
    gex_after = [row["gex"] for row in cached["cells"]]
    assert gex_after == [row["gex"] for row in expected["cells"]]
    # and at least one displayed GEX-dollar value actually changed from the baseline.
    assert gex_after != gex_before


def test_spot_only_tick_bumps_the_sse_generation_counter(monkeypatch):
    """_next_gamma_surface_seq is the SAME function refresh_gamma_surface_from_stream
    uses to both bump the generation AND push the ed:gamma-push SSE notify (see that
    function's own docstring/tests) -- calling it is what makes this an "immediate gamma
    SSE notification", not a second mechanism to re-prove here."""
    _put_rest_baseline_with_spot(TK, _CONTRACTS, _SPOT)
    monkeypatch.setattr("app.options.order_flow.streaming.get_active_option_contracts", lambda: [])
    monkeypatch.setattr("app.options.order_flow.streaming.get_active_option_contract", lambda: None)
    monkeypatch.setattr(server, "resolve_spot", lambda tk, **kw: (_SPOT + 1.0, "stub", time.time()))
    seq_calls = []
    real_next_seq = gamma_surface_state._next_gamma_surface_seq

    def _spy(tk):
        n = real_next_seq(tk)
        seq_calls.append(n)
        return n
    monkeypatch.setattr(gamma_surface_state, "_next_gamma_surface_seq", _spy)
    assert refresh_gamma_surface_from_spot_tick(TK) == "ok"
    assert len(seq_calls) == 1


# ---------------------------------------------------------------------------
# 4. Spot unchanged -> true no-op
# ---------------------------------------------------------------------------

def test_spot_unchanged_never_recomputes(monkeypatch):
    surf = _put_rest_baseline_with_spot(TK, _CONTRACTS, _SPOT)
    monkeypatch.setattr(server, "resolve_spot", lambda tk, **kw: (_SPOT, "stub", time.time()))
    status = refresh_gamma_surface_from_spot_tick(TK)
    assert status == "spot_unchanged"
    with terrain_state._terrain_cache_lock:
        cached = terrain_state._terrain_cache[TK]["_gamma_surface"]
    assert cached is surf, "an unchanged spot must not rebuild the surface at all -- same object"


def test_no_prior_surface_is_a_safe_noop(monkeypatch):
    with terrain_state._terrain_cache_lock:
        terrain_state._terrain_cache[TK] = {
            "_contracts_rest": _CONTRACTS, "_contracts_rest_spot": _SPOT,
            "_contracts_rest_computed_ts": time.time(), "computed_ts_utc": time.time(),
        }   # no "_gamma_surface" key at all yet
    monkeypatch.setattr(server, "resolve_spot", lambda tk, **kw: (_SPOT, "stub", time.time()))
    assert refresh_gamma_surface_from_spot_tick(TK) == "no_prior_surface"


def test_no_rest_baseline_is_a_safe_noop():
    with terrain_state._terrain_cache_lock:
        terrain_state._terrain_cache[TK] = {"_gamma_surface": {"spot": _SPOT}}
    assert refresh_gamma_surface_from_spot_tick(TK) == "no_rest_baseline"


def test_no_cached_ticker_is_a_safe_noop():
    assert refresh_gamma_surface_from_spot_tick(TK) == "no_cached_ticker"


def test_no_current_spot_is_a_safe_noop(monkeypatch):
    _put_rest_baseline_with_spot(TK, _CONTRACTS, _SPOT)
    monkeypatch.setattr(server, "resolve_spot", lambda tk, **kw: (None, "none", None))
    assert refresh_gamma_surface_from_spot_tick(TK) == "no_current_spot"


# ---------------------------------------------------------------------------
# 5. Ticker isolation
# ---------------------------------------------------------------------------

def test_a_spot_tick_for_one_ticker_never_touches_a_different_ticker(monkeypatch):
    _put_rest_baseline_with_spot(TK, _CONTRACTS, _SPOT)
    other_surf = _put_rest_baseline_with_spot(TK2, _CONTRACTS, _SPOT)
    monkeypatch.setattr("app.options.order_flow.streaming.get_active_option_contracts", lambda: [])
    monkeypatch.setattr("app.options.order_flow.streaming.get_active_option_contract", lambda: None)
    monkeypatch.setattr(server, "resolve_spot", lambda tk, **kw: (_SPOT + 5.0, "stub", time.time()))
    assert refresh_gamma_surface_from_spot_tick(TK) == "ok"
    with terrain_state._terrain_cache_lock:
        untouched = terrain_state._terrain_cache[TK2]["_gamma_surface"]
    assert untouched is other_surf, "SPY's own spot tick must never repaint a different ticker's surface"


def test_a_stale_baseline_generation_is_discarded_not_published(monkeypatch):
    """A REST cycle landing (bumping _contracts_rest_computed_ts) WHILE this eager spot
    refresh is computing must win -- the same CAS discipline refresh_gamma_surface_from_
    stream already proves (test_a_rest_refresh_landing_mid_computation_is_not_overwritten_
    by_the_stale_result), reproduced here for the spot-triggered path."""
    _put_rest_baseline_with_spot(TK, _CONTRACTS, _SPOT)
    monkeypatch.setattr("app.options.order_flow.streaming.get_active_option_contracts", lambda: [])
    monkeypatch.setattr("app.options.order_flow.streaming.get_active_option_contract", lambda: None)
    monkeypatch.setattr(server, "resolve_spot", lambda tk, **kw: (_SPOT + 5.0, "stub", time.time()))

    fresh_marker = {"expirations": [], "strikes": [], "cells": [], "marker": "NEWER_REST_GENERATION"}
    orig_project = gamma_surface_projection.project_gamma_surface

    def racing_project(contracts_arg, spot_arg):
        with terrain_state._terrain_cache_lock:
            terrain_state._terrain_cache[TK] = {
                "_contracts_rest": _CONTRACTS, "_contracts_rest_spot": _SPOT,
                "_contracts_rest_computed_ts": time.time(),   # NEW generation lands mid-flight
                "_gamma_surface": fresh_marker, "computed_ts_utc": time.time(),
            }
        return orig_project(contracts_arg, spot_arg)
    monkeypatch.setattr(gse, "project_gamma_surface", racing_project)
    try:
        status = refresh_gamma_surface_from_spot_tick(TK)
    finally:
        gamma_surface_projection.project_gamma_surface = orig_project
    assert status == "stale_baseline_superseded"
    with terrain_state._terrain_cache_lock:
        assert terrain_state._terrain_cache[TK]["_gamma_surface"] is fresh_marker, (
            "the newer REST generation's own surface must survive untouched")


# ---------------------------------------------------------------------------
# 6. Changed spot across multiple expiries -- full recompute, never incremental
# ---------------------------------------------------------------------------

def test_changed_spot_across_two_expiries_matches_an_independent_full_recompute(monkeypatch):
    import time_et
    frozen = time_et.now_et()
    monkeypatch.setattr(time_et, "now_et", lambda: frozen)
    chain = [dict(ct) for ct in _REAL["chain"]] + [dict(ct) for ct in _CDE["chain"]]
    old_spot = _SPOT
    new_spot = _SPOT + 5.0
    _put_rest_baseline_with_spot(TK, chain, old_spot)
    monkeypatch.setattr("app.options.order_flow.streaming.get_active_option_contracts", lambda: [])
    monkeypatch.setattr("app.options.order_flow.streaming.get_active_option_contract", lambda: None)
    monkeypatch.setattr(server, "resolve_spot", lambda tk, **kw: (new_spot, "stub", time.time()))

    assert refresh_gamma_surface_from_spot_tick(TK) == "ok"
    expected = project_gamma_surface(chain, new_spot)
    with terrain_state._terrain_cache_lock:
        cached = terrain_state._terrain_cache[TK]["_gamma_surface"]
    # every field exact (this function never calls the incremental per-expiry splice at
    # all, so there is no vanna-drift tolerance to make here -- both are fresh full
    # recomputes from the SAME frozen clock).
    for field in ("expirations", "strikes"):
        assert cached[field] == expected[field]
    assert [c["gex"] for c in cached["cells"]] == [c["gex"] for c in expected["cells"]]
    assert [c["dex"] for c in cached["cells"]] == [c["dex"] for c in expected["cells"]]


# ---------------------------------------------------------------------------
# 3. Mixed burst -> coalescing, bounded work, no unbounded queue
# ---------------------------------------------------------------------------

def test_dispatcher_coalesces_a_burst_into_at_most_two_underlying_calls(monkeypatch):
    """Requirement: 'at most one computation in flight per ticker; exactly one trailing
    recomputation when updates arrive while one is running; no unbounded queue.' Ten rapid
    dispatches for the SAME ticker while the first is still running must cost at most TWO
    real calls to the underlying function (the one already running, plus one coalesced
    trailing rerun) -- never ten."""
    calls = []
    release = threading.Event()
    started = threading.Event()

    def _slow_refresh(tk):
        calls.append(tk)
        started.set()
        release.wait(timeout=5.0)
        return "ok"
    monkeypatch.setattr(gamma_surface_eager_refresh, "refresh_gamma_surface_from_spot_tick", _slow_refresh)
    try:
        _dispatch_spot_gamma_refresh(TK)
        assert started.wait(timeout=2.0), "the first dispatch must actually start running"
        for _ in range(9):   # a burst arriving while the first call is still in flight
            _dispatch_spot_gamma_refresh(TK)
        release.set()
        # let the (at most one) coalesced trailing rerun complete
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and len(calls) < 2:
            time.sleep(0.02)
        time.sleep(0.2)   # settle window to catch any (incorrect) extra calls
    finally:
        release.set()
    assert len(calls) <= 2, f"a burst of 10 dispatches must coalesce, not queue: {calls}"
    with gamma_surface_eager_refresh._spot_gamma_refresh_lock:
        assert TK not in gamma_surface_eager_refresh._spot_gamma_refresh_inflight
        assert TK not in gamma_surface_eager_refresh._spot_gamma_refresh_pending


def test_dispatcher_keeps_two_tickers_data_isolated(monkeypatch):
    """The dispatcher's single-worker executor (deliberately the same design choice as
    app.options.order_flow.streaming's own hook_executor, for the same reason: this
    daemon-plane-feed lane only ever tracks ONE actively-viewed ticker at a time in
    production) means two tickers' recomputes are SERIALIZED, not concurrent -- that is
    not what this test is about. What it proves is DATA isolation: both tickers'
    dispatches are honored (neither is dropped or corrupted by the other's in-flight
    call), and each call receives its OWN ticker identity, never a mixed-up one."""
    calls = []
    release = threading.Event()
    started = threading.Event()

    def _slow_refresh(tk):
        calls.append(tk)
        if tk == TK:
            started.set()
            release.wait(timeout=5.0)
        return "ok"
    monkeypatch.setattr(gamma_surface_eager_refresh, "refresh_gamma_surface_from_spot_tick", _slow_refresh)
    try:
        _dispatch_spot_gamma_refresh(TK)
        assert started.wait(timeout=2.0)
        _dispatch_spot_gamma_refresh(TK2)   # queued behind TK on the single worker -- fine
        release.set()
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline and TK2 not in calls:
            time.sleep(0.02)
        assert TK2 in calls, "a different ticker's dispatch must still be honored, never dropped"
        assert calls == [TK, TK2], "each call must carry its OWN ticker identity, in order"
    finally:
        release.set()
        time.sleep(0.2)


# ---------------------------------------------------------------------------
# 2. Option-only streamed update still works, and does not fight the spot path
# ---------------------------------------------------------------------------

def test_option_only_tick_unaffected_by_the_spot_tick_path_coexisting(monkeypatch):
    """Spot unchanged, an option contract's own greeks tick -- refresh_gamma_surface_from_
    stream (the pre-existing path) must still work exactly as before, and a subsequent
    spot-tick call (same spot) must be a no-op, proving the two paths do not double-
    recompute or interfere with each other's published generation."""
    import app.options.order_flow.streaming as _ofs
    _put_rest_baseline_with_spot(TK, _CONTRACTS, _SPOT)
    now = time.time()
    streamed = {"gamma": 0.5, "gamma_ts_recv": now}
    monkeypatch.setattr("app.options.order_flow.state.get_stream_greeks",
                        lambda sym: streamed if sym == _CONTRACT_SYMBOL else None)
    monkeypatch.setattr(server, "resolve_spot", lambda tk, **kw: (_SPOT, "stub", time.time()))
    prior_contract, prior_contracts = _ofs._active_option_contract, _ofs._active_option_contracts
    _ofs._active_option_contract = _CONTRACT_SYMBOL
    _ofs._active_option_contracts = []
    try:
        assert refresh_gamma_surface_from_stream(_CONTRACT_SYMBOL, now) == "ok"
        with terrain_state._terrain_cache_lock:
            seq_after_option_tick = terrain_state._terrain_cache[TK]["_gamma_surface"]["surface_seq"]

        status = refresh_gamma_surface_from_spot_tick(TK)
        assert status == "spot_unchanged"
        with terrain_state._terrain_cache_lock:
            assert terrain_state._terrain_cache[TK]["_gamma_surface"]["surface_seq"] == seq_after_option_tick
    finally:
        _ofs._active_option_contract = prior_contract
        _ofs._active_option_contracts = prior_contracts


def test_RC570_REPO_WIDE_PROOF_a_spot_tick_alone_refreshes_every_live_surface(monkeypatch):
    """RC-570 REPO-WIDE PROOF (operator demand, 2026-09-21: "you need to prove to me that
    you fixed the live UI repo wide"). One single event -- the underlying's price moving,
    with NO option contract ticking at all -- must refresh EVERY surface this session found
    frozen on a slow poll: the heatmap grid, Strike Detail/GEX-by-strike, Key Levels
    (gamma_flip/walls/pin/etc.), AND Vanna/Charm-by-strike (which read the chain
    _live_terrain_contracts_and_spot serves, not the surface directly). All four are
    asserted against the SAME independently-computed reference, from the SAME real captured
    chain, so this is proof by direct comparison, not by trusting internal consistency.
    Runs end to end with a synthetic tick, no RTH, no live Schwab connection required --
    the same distinction this session's other RC-570 tests already establish: correctness
    is provable in a test; only Schwab's own real-world tick RATE needs RTH to confirm."""
    import datetime as _dt

    from math_levels import compute_charm_by_strike as _ccs
    from math_exposure_core import compute_exposures_by_strike as _cebs
    from time_et import ET as _ET
    from tests.test_gamma_surface_stream_refresh_v1 import _cells_match_ignoring_vanna_drift

    # RC-REHAB-2's exact date-rot fix (tests/test_vanna_charm_by_strike_v1.py): this fixture's
    # chain was captured 2026-09-02 with a uniform expirationDate of 2026-09-18T20:00:00Z.
    # compute_charm_by_strike/compute_exposures_by_strike derive T from time_et.now_et() and
    # fail-closed (empty) once real wall-clock time passes that date -- freeze `now` to inside
    # the fixture's own capture window so this test keeps proving real per-contract math
    # instead of silently degrading to an always-empty/always-zero comparison.
    monkeypatch.setattr("time_et.now_et", lambda: _dt.datetime(2026, 9, 2, 14, 30, tzinfo=_ET))

    new_spot = _SPOT + 7.0   # a real, material move -- proves every surface below actually
    _put_rest_baseline_with_spot(TK, _CONTRACTS, _SPOT)             # used the NEW spot, not
    with terrain_state._terrain_cache_lock:                                # a leftover stale one.
        terrain_state._terrain_cache[TK]["gamma_flip"] = "SENTINEL_STALE"
        terrain_state._terrain_cache[TK]["call_wall"] = "SENTINEL_STALE"
    monkeypatch.setattr(server, "resolve_spot", lambda tk, **kw: (new_spot, "stub", time.time()))

    t0 = time.monotonic()
    status = refresh_gamma_surface_from_spot_tick(TK)
    elapsed_sec = time.monotonic() - t0
    assert status == "ok"
    assert elapsed_sec < 5.0, f"spot-tick-to-every-surface took {elapsed_sec:.2f}s -- too slow"

    # ---- 1. Heatmap grid ----
    expected_surface = project_gamma_surface(_CONTRACTS, new_spot)
    with terrain_state._terrain_cache_lock:
        cached_surface = terrain_state._terrain_cache[TK]["_gamma_surface"]
    assert cached_surface["spot"] == new_spot
    # _backfill_gex_cells_from_last_valid also stamps a `value_snapshot_ts_utc` provenance
    # list onto each cell (server.py:15068) -- an orthogonal disclosure layered on top of the
    # exposure-math faucet, exactly like `stream`, and absent from a bare project_gamma_surface
    # call. Stripped here for the same reason _cells_match_ignoring_vanna_drift already strips
    # `stream`; the helper itself is left alone since its own docstring's claim (that file's
    # tests never hit this stamping path) still holds for its own callers.
    actual_cells = [
        {k: v for k, v in cell.items() if k != "value_snapshot_ts_utc"}
        for cell in cached_surface["cells"]
    ]
    assert _cells_match_ignoring_vanna_drift(actual_cells, expected_surface["cells"]), (
        "heatmap cells did not match the independently-computed reference surface at the new spot"
    )

    # ---- 2. Strike Detail / GEX-by-strike (per_strike) ----
    expected_per_strike = per_strike_view._per_strike_view_from_contracts(_CONTRACTS, new_spot)
    with terrain_state._terrain_cache_lock:
        cached_per_strike = terrain_state._terrain_cache[TK]["_per_strike"]
    assert cached_per_strike == expected_per_strike

    # ---- 3. Key Levels (gamma_flip/call_wall/put_wall/absolute_gamma_strike/net_gex_peak) ----
    expected_terrain = terrain_engine.compute_terrain(TK, _CONTRACTS, new_spot).to_dict()
    with terrain_state._terrain_cache_lock:
        cached = dict(terrain_state._terrain_cache[TK])
    assert cached["gamma_flip"] != "SENTINEL_STALE"
    assert cached["call_wall"] != "SENTINEL_STALE"
    assert cached["gamma_flip"] == expected_terrain["gamma_flip"]
    assert cached["call_wall"] == expected_terrain["call_wall"]
    assert cached["put_wall"] == expected_terrain["put_wall"]
    assert cached["absolute_gamma_strike"] == expected_terrain["absolute_gamma_strike"]
    assert cached["net_gex_peak"] == expected_terrain["net_gex_peak"]

    # ---- 4. Vanna-by-strike / Charm-by-strike (via _live_terrain_contracts_and_spot) ----
    # These two endpoints do NOT read _gamma_surface at all -- they call
    # _live_terrain_contracts_and_spot for raw contracts+spot and compute fresh on every
    # request. Before this fix they read ONLY _contracts_rest/_contracts_rest_spot (the
    # REST-cycle-only baseline) and would still show the OLD spot here. Proving they now
    # see the NEW spot is the direct test of the _contracts_overlaid fix.
    live_contracts, live_spot = server._live_terrain_contracts_and_spot(TK)
    assert live_spot == new_spot, (
        "Vanna/Charm-by-strike still reading the stale REST-only spot -- "
        "_contracts_overlaid fix did not take effect"
    )
    expected_charm = _ccs(live_contracts, live_spot)
    actual_charm_rows = {k: v for k, v in expected_charm.items()}  # same faucet either way;
    assert actual_charm_rows, "a real chain must yield at least one charm row at the new spot"
    expected_vanna_exposures, _diag = _cebs(live_contracts, spot=live_spot, require_oi=True)
    assert expected_vanna_exposures, "a real chain must yield at least one vanna bucket at the new spot"
