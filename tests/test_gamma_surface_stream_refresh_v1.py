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
# RC-REHAB-1 (2026-09-23, module extraction, twenty-seventh slice):
# refresh_gamma_surface_from_stream moved out of server.py entirely, into
# gamma_surface_eager_refresh.py, which imports project_gamma_surface/
# project_gamma_surface_update_expiry/compute_terrain directly (module-level, not
# lazily via `import server`) -- mocks targeting those three must patch that
# module's own binding, not server's re-export, to be picked up.
import gamma_surface_eager_refresh as gse
from gamma_surface_eager_refresh import refresh_gamma_surface_from_stream
from gamma_surface_projection import project_gamma_surface
from instrument_identity import ticker_storage_key
from math_exposure_core import overlay_streamed_contract_fields

_FX = Path(__file__).resolve().parent / "fixtures"
_REAL = json.loads((_FX / "real_crwd_complete_chain_quarter.json").read_text(encoding="utf-8"))
_SPOT = float(_REAL["spot"])
_CONTRACTS = [dict(ct) for ct in _REAL["chain"]]
_CONTRACT_SYMBOL = _CONTRACTS[0]["symbol"]
_CONTRACT_SYMBOL_B = _CONTRACTS[1]["symbol"]
TK = ticker_storage_key("CRWD")


def _cells_match_ignoring_vanna_drift(actual, expected, tol=0.1):
    """Every field exact except `vanna`, tolerated within `tol`. bs_vanna's own t_years input
    is genuinely intraday-time-sensitive (math_levels.py), so calling project_gamma_surface a
    second time -- as every test in this file does, to build its own "expected" reference --
    can legitimately drift a few hundredths from the value the code path under test computed a
    moment earlier. This was invisible before 2026-09-13's vanna-rounding fix (whole-integer
    rounding of a value in the hundreds/thousands absorbed drift this size); rounding to 2
    decimals (matching /api/options/vanna-by-strike's own precision) made it visible here for
    the first time. tests/test_vanna_charm_by_strike_v1.py and
    tests/test_gamma_surface_projection_v1.py already tolerate the identical drift for the
    identical reason.

    Also ignores `stream` (always-live heatmap mandate, 2026-09-15): every "expected" reference
    in this file calls the bare project_gamma_surface faucet directly, never through
    _stamp_gamma_surface_cell_stream_state, so it never carries that key at all -- this
    comparison is about the exposure-math faucet's own output, which that stamp never touches
    (RC-80: still one producer, one computation), not about the orthogonal per-cell stream-state
    disclosure layered on top of it."""
    if len(actual) != len(expected):
        return False
    for a, e in zip(actual, expected):
        a_keys = set(a.keys()) - {"stream"}
        if a_keys != set(e.keys()):
            return False
        for k in a_keys:
            if k != "vanna":
                if a[k] != e[k]:
                    return False
                continue
            if len(a[k]) != len(e[k]):
                return False
            for av, ev in zip(a[k], e[k]):
                if av is None or ev is None:
                    if av != ev:
                        return False
                elif abs(av - ev) >= tol:
                    return False
    return True


def _surfaces_match_ignoring_vanna_drift(actual, expected, tol=0.1):
    """Same tolerance as _cells_match_ignoring_vanna_drift, for a whole surface dict (every
    key exact except `cells`, which gets the tolerant per-cell comparison)."""
    if set(actual.keys()) != set(expected.keys()):
        return False
    for k in actual:
        if k == "cells":
            if not _cells_match_ignoring_vanna_drift(actual[k], expected[k], tol):
                return False
        elif actual[k] != expected[k]:
            return False
    return True


def _clear_cache():
    with server._terrain_cache_lock:
        server._terrain_cache.pop(TK, None)
    # Canonical input-validity rules (2026-09-15): _LAST_VALID_GEX_CELLS is a module-level,
    # cross-call snapshot store (by design -- it must survive the very cache pops this helper
    # performs, in production). Cleared here too so ONE test's real backfilled values never
    # leak into a LATER test's "expected" comparison, which calls project_gamma_surface
    # directly and therefore never goes through backfill itself. _HYDRATED is cleared too so
    # a later test's first backfill call re-hydrates (a real, but harmless and fail-closed-
    # empty-for-this-ticker, DB read) rather than silently reusing this run's in-memory state.
    with server._LAST_VALID_GEX_CELLS_LOCK:
        server._LAST_VALID_GEX_CELLS.pop(TK, None)
        server._LAST_VALID_GEX_CELLS_HYDRATED.discard(TK)
        # Pre-throttled (not popped) -- this file's tests are about overlay/refresh semantics,
        # not DB persistence (see test_canonical_gex_input_validity_v1.py for that proof), so
        # the durability flush is deliberately kept quiet here: real backfill READS still run
        # (harmless, read-only, fail-closed to {} for this synthetic ticker), but no test in
        # this file writes rows into the real dev database.
        server._LAST_VALID_GEX_CELLS_DB_WRITE_TS[TK] = time.time()


def _put_rest_baseline(*, computed_ts_utc=None, contracts=None):
    ts = time.time() if computed_ts_utc is None else computed_ts_utc
    cts = _CONTRACTS if contracts is None else contracts
    with server._terrain_cache_lock:
        server._terrain_cache[TK] = {
            "_contracts_rest": cts,
            "_contracts_rest_spot": _SPOT,
            "_contracts_rest_computed_ts": ts,
            "_gamma_surface": project_gamma_surface(cts, _SPOT),
            "computed_ts_utc": ts,
        }
    server._gamma_surface_seq.pop(TK, None)


def _backfilled(surface):
    """Canonical input-validity rules (2026-09-15): every production caller of
    project_gamma_surface in this file's real code path (_terrain_refresh_one,
    refresh_gamma_surface_from_stream) immediately runs the result through
    _backfill_gex_cells_from_last_valid -- an "expected" surface built by calling
    project_gamma_surface directly, as every test below does, must go through the SAME step
    to be a true mirror of what the real path actually publishes (this real CRWD fixture can
    itself carry the same vendor-invalid-greeks contracts the canonical gate now excludes;
    a strike that has no valid value in THIS computation but does in the shared
    _LAST_VALID_GEX_CELLS store -- already populated by the real call under test -- is
    correctly backfilled in production and must be here too, or the comparison is against a
    path production no longer takes)."""
    server._backfill_gex_cells_from_last_valid(TK, surface)
    return surface


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
    # Canonical input-validity rules (2026-09-15): _backfill_gex_cells_from_last_valid's DB
    # hydration calls server.get_db() -- on this PROCESS's first-ever call, that pays a
    # real, one-time schema-migration cost (can be tens to hundreds of ms). Paid HERE, before
    # any timing-sensitive assertion, so it never lands inside the tiny real wall-clock gap
    # these tests compare two independent bs_vanna(t_years) computations across (see
    # _cells_match_ignoring_vanna_drift's own docstring on that pre-existing sensitivity) --
    # otherwise the SAME real drift this file already tolerates can occasionally exceed the
    # fixed 0.1 absolute tolerance purely because migration, not vanna math, ate the gap.
    server.get_db()
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


# ---------------------------------------------------------------------------
# ONE spot faucet (operator directive, 2026-09-15): "streamed GEX must use the canonical
# fresh spot, not the REST-cycle spot." This is the eager path that most needs it -- a
# streamed tick is exactly the case where spot itself may have moved since the last ~60s
# REST cycle. resolve_spot (RC-14) is the single existing authority every other consumer in
# this file (_terrain_refresh_one) already calls; these tests prove the eager refresh now
# calls the SAME function fresh instead of reusing the REST-cycle-cached _contracts_rest_spot.
# ---------------------------------------------------------------------------

_REST_BASELINE_SPOT = _SPOT   # the REST cycle's own cached spot, from _put_rest_baseline


def test_eager_refresh_uses_resolve_spot_not_the_stale_rest_cycle_spot(monkeypatch):
    _put_rest_baseline(computed_ts_utc=time.time() - 10.0)
    now = time.time()
    live = {_CONTRACT_SYMBOL: {"gamma": 0.05, "gamma_ts_recv": now}}
    monkeypatch.setattr("app.options.order_flow.state.get_stream_greeks", lambda sym: live.get(sym))
    fresher_spot = _REST_BASELINE_SPOT * 1.10   # a spot that has clearly moved since the REST cycle
    monkeypatch.setattr(server, "resolve_spot", lambda tk, **kw: (fresher_spot, "streaming_plane", now))

    assert refresh_gamma_surface_from_stream(_CONTRACT_SYMBOL, now) == "ok"
    with server._terrain_cache_lock:
        surf = server._terrain_cache[TK]["_gamma_surface"]
    overlaid, n = overlay_streamed_contract_fields(_CONTRACTS, {_CONTRACT_SYMBOL: {"gamma": 0.05, "gamma_ts_recv": now}})
    assert n == 1
    expected = _backfilled(project_gamma_surface(overlaid, fresher_spot))
    assert _cells_match_ignoring_vanna_drift(surf["cells"], expected["cells"]), (
        "the eager refresh must recompute against resolve_spot's fresh value, not the REST-cycle spot"
    )
    # Never computed from the stale REST-cycle spot -- a real, material difference (10%).
    expected_from_stale = _backfilled(project_gamma_surface(overlaid, _REST_BASELINE_SPOT))
    assert not _cells_match_ignoring_vanna_drift(surf["cells"], expected_from_stale["cells"]), (
        "sanity: fresher_spot must be material enough that using the stale spot would visibly differ"
    )


def test_eager_refresh_stamps_the_resolved_spot_source_and_timestamp():
    _put_rest_baseline(computed_ts_utc=time.time() - 10.0)
    now = time.time()
    live = {_CONTRACT_SYMBOL: {"gamma": 0.05, "gamma_ts_recv": now}}
    import unittest.mock as _mock
    with _mock.patch("app.options.order_flow.state.get_stream_greeks", lambda sym: live.get(sym)), \
         _mock.patch.object(server, "resolve_spot", lambda tk, **kw: (321.5, "streaming_plane", now)):
        assert refresh_gamma_surface_from_stream(_CONTRACT_SYMBOL, now) == "ok"
    with server._terrain_cache_lock:
        surf = server._terrain_cache[TK]["_gamma_surface"]
    assert surf["spot"] == 321.5
    assert surf["spot_source"] == "streaming_plane"
    assert surf["spot_as_of_ts_utc"] == now


def test_eager_refresh_fails_closed_never_falls_back_to_the_rest_cycle_spot(monkeypatch):
    """Operator directive (2026-09-15, SECOND pass): "Remove the heatmap-local
    _contracts_rest_spot fallback; a historical spot stamped on a completed surface may
    remain provenance, but it must not become an alternate current-spot selector." When
    resolve_spot (the ONE authority) has nothing -- no live plane, no REST quote, no stored
    snapshot -- this refresh must fail closed, never silently substitute its own cached copy
    of a past resolve_spot answer as a second spot source."""
    _put_rest_baseline(computed_ts_utc=time.time() - 10.0)
    now = time.time()
    live = {_CONTRACT_SYMBOL: {"gamma": 0.05, "gamma_ts_recv": now}}
    monkeypatch.setattr("app.options.order_flow.state.get_stream_greeks", lambda sym: live.get(sym))
    monkeypatch.setattr(server, "resolve_spot", lambda tk, **kw: (None, "none", None))

    assert refresh_gamma_surface_from_stream(_CONTRACT_SYMBOL, now) == "no_current_spot"
    with server._terrain_cache_lock:
        # The cache must still hold only the untouched REST baseline surface -- no eager
        # write happened at all, so nothing here can have "fallen back" to anything.
        surf = server._terrain_cache[TK]["_gamma_surface"]
    assert surf.get("spot") is None, "the REST-cycle baseline in this fixture never stamped its own spot"


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
        assert _surfaces_match_ignoring_vanna_drift(
            server._terrain_cache[TK]["_gamma_surface"], project_gamma_surface(_CONTRACTS, _SPOT))


def test_a_fresh_streamed_update_recomputes_and_caches_the_overlaid_surface(monkeypatch):
    baseline_ts = time.time() - 10.0
    _put_rest_baseline(computed_ts_utc=baseline_ts)
    now = time.time()   # strictly after the REST baseline -- genuinely newer
    streamed = {"gamma": 0.5, "gamma_ts_recv": now, "delta": 0.9, "delta_ts_recv": now,
                "open_interest": 99999.0, "open_interest_ts_recv": now}
    monkeypatch.setattr(
        "app.options.order_flow.state.get_stream_greeks",
        lambda sym: streamed if sym == _CONTRACT_SYMBOL else None)
    monkeypatch.setattr(server, "resolve_spot", lambda tk, **kw: (_SPOT, "stub", time.time()))

    status = refresh_gamma_surface_from_stream(_CONTRACT_SYMBOL, now)
    assert status == "ok"

    overlaid, n = overlay_streamed_contract_fields(_CONTRACTS, {_CONTRACT_SYMBOL: streamed})
    assert n == 1
    expected_surface = _backfilled(project_gamma_surface(overlaid, _SPOT))
    expected_per_strike = server._per_strike_view_from_contracts(overlaid, _SPOT)

    with server._terrain_cache_lock:
        cached = server._terrain_cache[TK]["_gamma_surface"]
        cached_per_strike = server._terrain_cache[TK]["_per_strike"]
    # the faucet's own cells/strikes/expirations must match the independently-computed
    # expectation exactly -- proves the wiring calls the SAME projection, not a reimplementation
    assert _cells_match_ignoring_vanna_drift(cached["cells"], expected_surface["cells"])
    assert cached["strikes"] == expected_surface["strikes"]
    assert cached["expirations"] == expected_surface["expirations"]
    assert cached["stream_overlay_contracts"] == 1
    # A SIXTH independent review (2026-09-13): the COUNT alone cannot tell a consumer WHICH
    # contract was actually freshened -- see _overlaid_symbols's own docstring finding. The
    # heatmap's per-column 'observed' promotion needs this identity, not just a nonzero count.
    assert cached["stream_overlay_symbols"] == [_CONTRACT_SYMBOL]
    assert cached["stream_overlay_receipt_to_computed_ms"] >= 0
    assert cached["surface_seq"] == 1
    # finding #2 (independent review, 2026-09-12): the eager refresh must publish _per_strike
    # from the SAME overlaid contracts as _gamma_surface, or the heatmap and the Strike Detail
    # / GEX-by-strike panel disagree on the same strike.
    assert cached_per_strike == expected_per_strike
    # the untouched REST baseline in the cache is unchanged by the eager overlay
    with server._terrain_cache_lock:
        assert server._terrain_cache[TK]["_contracts_rest"] == _CONTRACTS


def test_a_streamed_tick_also_refreshes_key_levels_fast_no_rth_required(monkeypatch):
    """RC-570 (2026-09-21, live-RTH finding/operator demand): a streamed tick used to refresh
    ONLY _gamma_surface/_per_strike (the heatmap grid), leaving gamma_flip/call_wall/put_wall/
    absolute_gamma_strike/net_gex_peak -- everything the Key Levels panel shows -- frozen at
    whatever the last ~60s REST cycle computed. This is the direct, synthetic proof the
    operator demanded: inject one fake tick through the EXACT SAME code path a real Schwab
    tick would take, and prove BOTH that Key Levels' own fields update from it AND that this
    happens fast -- correctness and speed proven here, in a test, with no dependency on RTH.
    What RTH separately proves is a CAPACITY question (does Schwab keep sending ticks fast
    enough under real load), never a correctness question -- that distinction is the whole
    point of this test existing."""
    baseline_ts = time.time() - 10.0
    _put_rest_baseline(computed_ts_utc=baseline_ts)
    with server._terrain_cache_lock:
        # The REST baseline seeded above never set gamma_flip/walls (only a bare gamma
        # surface) -- start from an explicit "old/absent" sentinel so a pass proves this
        # call actually WROTE a fresh value, not that one was already sitting there.
        server._terrain_cache[TK]["gamma_flip"] = "SENTINEL_STALE_VALUE"
        server._terrain_cache[TK]["call_wall"] = "SENTINEL_STALE_VALUE"

    now = time.time()
    streamed = {"gamma": 0.5, "gamma_ts_recv": now, "delta": 0.9, "delta_ts_recv": now,
                "open_interest": 99999.0, "open_interest_ts_recv": now}
    monkeypatch.setattr(
        "app.options.order_flow.state.get_stream_greeks",
        lambda sym: streamed if sym == _CONTRACT_SYMBOL else None)
    monkeypatch.setattr(server, "resolve_spot", lambda tk, **kw: (_SPOT, "stub", time.time()))

    t0 = time.monotonic()
    status = refresh_gamma_surface_from_stream(_CONTRACT_SYMBOL, now)
    elapsed_sec = time.monotonic() - t0
    assert status == "ok"
    # PROOF OF SPEED: this is the exact same computation path _terrain_refresh_one's own
    # 60s REST cycle takes, but triggered by one tick instead of a timer. A generous but
    # real budget -- production runs this on a real chain in well under a second; 5s leaves
    # wide margin for a slow CI runner while still proving "fast", not "eventually".
    assert elapsed_sec < 5.0, (
        f"tick-to-Key-Levels-update took {elapsed_sec:.2f}s -- too slow to call this live"
    )

    overlaid, n = overlay_streamed_contract_fields(_CONTRACTS, {_CONTRACT_SYMBOL: streamed})
    assert n == 1
    expected_terrain = server.compute_terrain(TK, overlaid, _SPOT).to_dict()

    with server._terrain_cache_lock:
        cached = dict(server._terrain_cache[TK])

    # PROOF OF CORRECTNESS: Key Levels' own fields moved off the sentinel and match the
    # SAME canonical terrain_engine.compute_terrain the REST cycle uses -- never a second,
    # divergent formula (the exact class of bug RC-569, immediately above this one in the
    # ledger, already fixed for the background logger's own independent call).
    assert cached["gamma_flip"] != "SENTINEL_STALE_VALUE"
    assert cached["call_wall"] != "SENTINEL_STALE_VALUE"
    assert cached["gamma_flip"] == expected_terrain["gamma_flip"]
    assert cached["call_wall"] == expected_terrain["call_wall"]
    assert cached["put_wall"] == expected_terrain["put_wall"]
    assert cached["absolute_gamma_strike"] == expected_terrain["absolute_gamma_strike"]
    assert cached["net_gex_peak"] == expected_terrain["net_gex_peak"]
    # computed_ts_utc must advance to THIS tick's instant, not stay pinned to the stale
    # REST baseline_ts -- a reader checking freshness must see this really is new.
    assert cached["computed_ts_utc"] > baseline_ts

    # The heatmap's own existing per-tick contract (unchanged by this fix) still holds too --
    # proving this addition is additive, not a regression of the behavior already proven above.
    assert cached["_gamma_surface"]["stream_overlay_symbols"] == [_CONTRACT_SYMBOL]


def test_key_levels_refresh_is_best_effort_a_terrain_failure_never_blocks_the_heatmap(monkeypatch):
    """The heatmap/per-strike publication must succeed even if the new Key Levels refresh
    step raises -- this is an ADDITIONAL consumer of already-computed data, never a new
    precondition for the surface update that already worked before this fix existed."""
    _put_rest_baseline(computed_ts_utc=time.time() - 10.0)
    now = time.time()
    streamed = {"gamma": 0.5, "gamma_ts_recv": now, "delta": 0.9, "delta_ts_recv": now,
                "open_interest": 99999.0, "open_interest_ts_recv": now}
    monkeypatch.setattr(
        "app.options.order_flow.state.get_stream_greeks",
        lambda sym: streamed if sym == _CONTRACT_SYMBOL else None)
    monkeypatch.setattr(server, "resolve_spot", lambda tk, **kw: (_SPOT, "stub", time.time()))
    monkeypatch.setattr(gse, "compute_terrain", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))

    status = refresh_gamma_surface_from_stream(_CONTRACT_SYMBOL, now)
    assert status == "ok"
    with server._terrain_cache_lock:
        cached = server._terrain_cache[TK]
    assert cached["_gamma_surface"]["stream_overlay_symbols"] == [_CONTRACT_SYMBOL]
    # No Key Levels fields were written from the failed call -- degrades to "wait for the
    # next REST cycle", never to a partial/corrupt terrain write.
    assert "gamma_flip" not in cached or cached.get("gamma_flip") is None


def test_a_second_tick_with_a_moved_spot_forces_a_full_recompute_not_a_stale_splice(monkeypatch):
    """Independent-review finding (2026-09-16, follow-up mandate): net_gex_1pct/dex/vanna
    are functions of spot -- a streamed tick that also carries a genuinely NEW resolved spot
    must not be spliced into the prior surface's OTHER expiries/cells, which were priced at
    the OLD spot. Proven end-to-end through refresh_gamma_surface_from_stream's own wiring
    (not just the pure incremental functions in test_gamma_surface_projection_v1.py): a spy
    on project_gamma_surface_update_expiry proves it is never even attempted with a stale
    prior_spot once the second tick's resolve_spot disagrees with the first tick's own
    already-cached spot, and the full recompute this forces reflects the NEW spot exactly."""
    _put_rest_baseline(computed_ts_utc=time.time() - 10.0)
    spot1 = _SPOT
    spot2 = _SPOT + 5.0   # a genuinely different resolved spot for the second tick
    now1 = time.time()
    streamed1 = {"gamma": 0.5, "gamma_ts_recv": now1}
    monkeypatch.setattr("app.options.order_flow.state.get_stream_greeks",
                        lambda sym: streamed1 if sym == _CONTRACT_SYMBOL else None)
    monkeypatch.setattr(server, "resolve_spot", lambda tk, **kw: (spot1, "stub", time.time()))
    assert refresh_gamma_surface_from_stream(_CONTRACT_SYMBOL, now1) == "ok"
    with server._terrain_cache_lock:
        cached_after_1 = server._terrain_cache[TK]["_gamma_surface"]
    assert cached_after_1["spot"] == spot1

    real_update_expiry = server.project_gamma_surface_update_expiry
    calls = []

    def _spy_update_expiry(prior_surface, chain, spot, target_expiry, *, prior_spot):
        calls.append({"spot": spot, "prior_spot": prior_spot})
        return real_update_expiry(prior_surface, chain, spot, target_expiry, prior_spot=prior_spot)
    monkeypatch.setattr(gse, "project_gamma_surface_update_expiry", _spy_update_expiry)

    now2 = time.time()
    streamed2 = {"gamma": 0.6, "gamma_ts_recv": now2}
    monkeypatch.setattr("app.options.order_flow.state.get_stream_greeks",
                        lambda sym: streamed2 if sym == _CONTRACT_SYMBOL else None)
    monkeypatch.setattr(server, "resolve_spot", lambda tk, **kw: (spot2, "stub", time.time()))
    assert refresh_gamma_surface_from_stream(_CONTRACT_SYMBOL, now2) == "ok"

    assert calls, "the incremental splice must still be ATTEMPTED (and correctly refused), not skipped"
    assert calls[0]["spot"] == spot2 and calls[0]["prior_spot"] == spot1, (
        "the splice attempt must be told the truth about both spots, not a value already "
        "reconciled to look safe"
    )
    with server._terrain_cache_lock:
        cached_after_2 = server._terrain_cache[TK]["_gamma_surface"]
    assert cached_after_2["spot"] == spot2
    # The full recompute this forces must reflect the NEW spot exactly -- an independent
    # full computation at spot2 on the same overlaid contracts, never a value left over
    # from spot1.
    overlaid2, _n2 = overlay_streamed_contract_fields(_CONTRACTS, {_CONTRACT_SYMBOL: streamed2})
    expected_at_spot2 = _backfilled(project_gamma_surface(overlaid2, spot2))
    assert _cells_match_ignoring_vanna_drift(cached_after_2["cells"], expected_at_spot2["cells"])


def test_stream_overlay_symbols_names_only_the_contract_actually_freshened_not_every_desired_one(monkeypatch):
    """A SIXTH independent review (2026-09-13), REPRODUCED: the heatmap's 'observed' demand
    state used to promote to 'observed' off `stream_overlay_contracts > 0` alone -- a single
    surface-wide COUNT that says nothing about WHICH contract received it. With TWO desired
    contracts on this ticker (A and B) but only B's stream data fresh enough to overlay,
    `stream_overlay_symbols` must name B alone, never both, so a client can correctly leave
    A's own column at 'accepted' (requested, not yet evidenced) while promoting B's."""
    baseline_ts = time.time() - 10.0
    _put_rest_baseline(computed_ts_utc=baseline_ts)
    now = time.time()
    fresh = {"gamma": 0.5, "gamma_ts_recv": now}
    stale = {"gamma": 0.6, "gamma_ts_recv": 0.0}   # far older than max_staleness_sec

    import app.options.order_flow.streaming as _ofs
    _ofs._active_option_contract = _CONTRACT_SYMBOL
    _ofs._active_option_contracts = [_CONTRACT_SYMBOL_B]
    try:
        monkeypatch.setattr(
            "app.options.order_flow.state.get_stream_greeks",
            lambda sym: fresh if sym == _CONTRACT_SYMBOL_B else (stale if sym == _CONTRACT_SYMBOL else None))
        monkeypatch.setattr(server, "resolve_spot", lambda tk, **kw: (_SPOT, "stub", time.time()))

        status = refresh_gamma_surface_from_stream(_CONTRACT_SYMBOL_B, now)
        assert status == "ok"
        with server._terrain_cache_lock:
            cached = server._terrain_cache[TK]["_gamma_surface"]
        assert cached["stream_overlay_symbols"] == [_CONTRACT_SYMBOL_B], (
            f"only the genuinely-fresh contract must be named, not the stale desired one too: "
            f"{cached['stream_overlay_symbols']}")
    finally:
        _ofs._active_option_contract = None
        _ofs._active_option_contracts = []


def test_a_streamed_value_older_than_the_rest_baseline_is_rejected(monkeypatch):
    """Independent-review finding (2026-09-12): 'being received within ten seconds does not
    establish that a stream value is newer than the REST input it replaces.' A value only 2s
    old is still OLDER than a REST baseline fetched 1s ago.

    Independent-review finding (2026-09-13): a real chain contract carries its OWN native
    `quoteTimeInLong`, which now governs overlay precedence in preference to the shared
    REST-fetch instant (see overlay_streamed_contract_fields's fifth-review fix) -- the
    fixture's own captured quote time is whatever it happened to be when it was recorded,
    unrelated to this test's synthetic `now`, so the contract under test must be stamped
    with the scenario's own REST-baseline instant or the ordering guard this test exists to
    prove is not the one actually exercised."""
    now = time.time()
    contracts = [dict(ct) for ct in _CONTRACTS]
    contracts[0]["quoteTimeInLong"] = (now - 1.0) * 1000.0
    _put_rest_baseline(computed_ts_utc=now - 1.0, contracts=contracts)
    monkeypatch.setattr(
        "app.options.order_flow.state.get_stream_greeks",
        lambda sym: {"gamma": 0.99, "gamma_ts_recv": now - 2.0})
    assert refresh_gamma_surface_from_stream(_CONTRACT_SYMBOL, now) == "no_change"
    with server._terrain_cache_lock:
        assert _surfaces_match_ignoring_vanna_drift(
            server._terrain_cache[TK]["_gamma_surface"], project_gamma_surface(contracts, _SPOT))


def test_repeated_eager_refreshes_never_compound_away_from_the_rest_baseline(monkeypatch):
    """Each call overlays onto the STORED _contracts_rest, never onto a previously-overlaid
    result -- so two refreshes with two DIFFERENT streamed values produce the surface for the
    SECOND value alone, not an accumulation of both."""
    baseline_ts = time.time() - 10.0
    _put_rest_baseline(computed_ts_utc=baseline_ts)
    now = time.time()
    monkeypatch.setattr(server, "resolve_spot", lambda tk, **kw: (_SPOT, "stub", time.time()))
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
    expected = _backfilled(project_gamma_surface(overlaid, _SPOT))
    with server._terrain_cache_lock:
        cached = server._terrain_cache[TK]["_gamma_surface"]
        seq = cached["surface_seq"]
    assert _cells_match_ignoring_vanna_drift(cached["cells"], expected["cells"]), (
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
    monkeypatch.setattr(server, "resolve_spot", lambda tk, **kw: (_SPOT, "stub", time.time()))
    monkeypatch.setattr(
        "app.options.order_flow.state.get_stream_greeks",
        lambda sym: {"gamma": 0.5, "gamma_ts_recv": now})

    orig_project = server.project_gamma_surface
    orig_update_expiry = server.project_gamma_surface_update_expiry
    fresh_marker = {"expirations": [], "strikes": [], "cells": [], "marker": "FRESH_REST_GENERATION"}

    def _simulate_race():
        # Simulate a REAL REST refresh landing WHILE this function computes, publishing a
        # newer generation before this function gets a chance to write its own (older) one.
        with server._terrain_cache_lock:
            server._terrain_cache[TK] = {
                "_contracts_rest": _CONTRACTS, "_contracts_rest_spot": _SPOT,
                "_contracts_rest_computed_ts": time.time(),   # NEW generation
                "_gamma_surface": fresh_marker,
                "computed_ts_utc": time.time(),
            }

    def racing_project(contracts_arg, spot_arg):
        _simulate_race()
        return orig_project(contracts_arg, spot_arg)

    def racing_update_expiry(prior_surface_arg, contracts_arg, spot_arg, expiry_arg, *, prior_spot):
        # 2026-09-16 incremental-update path (audit finding #2): a prior _gamma_surface is
        # already cached from _put_rest_baseline, so refresh_gamma_surface_from_stream now
        # takes THIS path instead of the full project_gamma_surface -- the race must be
        # simulated here too, or the CAS-race invariant this test exists to prove would go
        # completely untested the instant the incremental path is available.
        _simulate_race()
        return orig_update_expiry(prior_surface_arg, contracts_arg, spot_arg, expiry_arg,
                                  prior_spot=prior_spot)

    monkeypatch.setattr(gse, "project_gamma_surface", racing_project)
    monkeypatch.setattr(gse, "project_gamma_surface_update_expiry", racing_update_expiry)
    try:
        status = refresh_gamma_surface_from_stream(_CONTRACT_SYMBOL, now)
    finally:
        server.project_gamma_surface = orig_project
        server.project_gamma_surface_update_expiry = orig_update_expiry
    assert status == "stale_baseline_superseded"
    with server._terrain_cache_lock:
        cached = server._terrain_cache[TK]
    assert cached["_gamma_surface"] == fresh_marker, (
        "the newer REST generation published mid-computation must survive, never be "
        "overwritten by a result computed from the OLD baseline"
    )


def test_never_raises_on_an_internal_error(monkeypatch):
    _put_rest_baseline()
    monkeypatch.setattr(server, "resolve_spot", lambda tk, **kw: (_SPOT, "stub", time.time()))
    monkeypatch.setattr(
        "app.options.order_flow.state.get_stream_greeks",
        lambda sym: {"gamma": 0.5, "gamma_ts_recv": time.time()})
    monkeypatch.setattr(gse, "project_gamma_surface",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    # 2026-09-16 incremental-update path (audit finding #2): a prior _gamma_surface is
    # already cached from _put_rest_baseline, so the code under test reaches
    # project_gamma_surface_update_expiry, not project_gamma_surface directly -- both
    # must independently prove the never-raises guarantee.
    monkeypatch.setattr(gse, "project_gamma_surface_update_expiry",
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
    out, n, syms = server._gamma_surface_contracts_with_stream_overlay(
        ticker_storage_key("SPY"), _CONTRACTS)  # asking for SPY, not CRWD
    assert n == 0
    assert out == _CONTRACTS
    assert syms == []


def test_gamma_surface_contracts_with_stream_overlay_applies_for_the_matching_ticker(monkeypatch):
    monkeypatch.setattr(
        "app.options.order_flow.streaming.get_active_option_contract",
        lambda: _CONTRACT_SYMBOL)
    monkeypatch.setattr(
        "app.options.order_flow.state.get_stream_greeks",
        lambda sym: {"gamma": 0.99, "gamma_ts_recv": time.time()})
    out, n, syms = server._gamma_surface_contracts_with_stream_overlay(TK, _CONTRACTS)
    assert n == 1
    assert out[0]["gamma"] == 0.99
    assert syms == [_CONTRACT_SYMBOL]


def test_gamma_surface_contracts_with_stream_overlay_noop_with_no_active_contract(monkeypatch):
    monkeypatch.setattr(
        "app.options.order_flow.streaming.get_active_option_contract", lambda: None)
    out, n, syms = server._gamma_surface_contracts_with_stream_overlay(TK, _CONTRACTS)
    assert n == 0
    assert out is _CONTRACTS
    assert syms == []


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
    monkeypatch.setattr(server, "resolve_spot", lambda tk, **kw: (_SPOT, "stub", time.time()))
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
    monkeypatch.setattr(server, "resolve_spot", lambda tk, **kw: (_SPOT, "stub", time.time()))
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
#
# Independent-review test-quality finding (2026-09-12), REPRODUCED against the original
# choice of contracts (_CONTRACT_SYMBOL / _CONTRACT_SYMBOL_B, the fixture's first two
# rows): both are deep-in-the-money (delta=0.999, strikes 38.75/40 vs spot 205.40) and
# the SECOND row carries real openInterest=0. Two independent, compounding problems:
#   1. compute_exposures_by_strike's own require_oi gate (`if oi <= 0: continue`, the
#      SAME quality gate the faucet always enforces) drops a zero-OI contract from the
#      aggregate entirely -- no gamma value injected onto it, plausible or not, can ever
#      reach a cell. Verified: with the pre-fix version of this test's own two rows,
#      overlaying vs NOT overlaying contract B's streamed gamma produces IDENTICAL
#      published cells, because B never contributes regardless.
#   2. gamma_is_plausible() (this app's own quality gate -- see math_exposure_core.py)
#      rejects a non-near-zero gamma paired with a deep-ITM/OTM delta
#      (`abs(delta) >= DELTA_DEEP_ABS_FOR_GAMMA=0.98` and `gamma > 1e-4`). The original
#      test injected gamma=0.5/0.7 onto contracts whose real delta=0.999 -- both
#      rejected by the app's own gate, so contract A's assertion passed VACUOUSLY too:
#      the ORIGINAL real gamma=0.0 (plausible, since near-zero) and the INJECTED 0.5
#      (implausible, so also contributes zero) compute the identical net_gamma=0.0
#      either way. A production regression that dropped the overlay entirely would have
#      passed this test unchanged.
# Fixed by using two REAL, liquid, near-the-money contracts from this same captured
# fixture (delta ~0.4-0.5, real nonzero OI in the hundreds/thousands, at two DISTINCT
# strikes) and injecting gamma magnitudes representative of real listed-option gamma
# (0.02-0.09, clearly distinct from each contract's own real 0.018 baseline) -- large
# enough to move each contract's $-GEX cell measurably, small enough to stay well clear
# of both quality gates, so the published cells can only match the independently
# recomputed expectation when the production overlay genuinely ran.
# ─────────────────────────────────────────────────────────────────────────────
_ATM_CONTRACT_A = "CRWD  260918C00205000"   # real: OI=1606, delta=0.500, gamma=0.018
_ATM_CONTRACT_B = "CRWD  260918C00210000"   # real: OI=3897, delta=0.413, gamma=0.018


def test_refreshing_b_does_not_undo_a_the_a_then_b_overwrite_reproduction(monkeypatch):
    """A is primary, B is additional. A ticks first and its overlay applies; B ticks
    second and its own overlay must apply TOGETHER WITH A's, not instead of it."""
    import app.options.order_flow.streaming as ofs
    ofs._active_option_contract = ofs.ticker_storage_key(_ATM_CONTRACT_A)
    ofs._active_option_contracts = [ofs.ticker_storage_key(_ATM_CONTRACT_B)]

    baseline_ts = time.time() - 10.0
    _put_rest_baseline(computed_ts_utc=baseline_ts)
    now_a = time.time()
    streamed_a = {"gamma": 0.05, "gamma_ts_recv": now_a}
    streamed_b = {"gamma": 0.08, "gamma_ts_recv": now_a}
    # B's own streamed value is not YET live when A ticks -- _desired_stream_greeks_for_ticker
    # gathers EVERY currently-desired contract's CURRENT state on every call (that is the
    # RC-UI-3 fix this test exists to protect), so if B's mocked data existed from the
    # start, "A's own tick" would already legitimately reflect B too, and the "A-only"
    # comparison below would not describe what production actually did.
    live = {_ATM_CONTRACT_A: streamed_a}
    monkeypatch.setattr(
        "app.options.order_flow.state.get_stream_greeks", lambda sym: live.get(sym))
    monkeypatch.setattr(server, "resolve_spot", lambda tk, **kw: (_SPOT, "stub", time.time()))

    assert refresh_gamma_surface_from_stream(_ATM_CONTRACT_A, now_a) == "ok"
    with server._terrain_cache_lock:
        after_a = server._terrain_cache[TK]["_gamma_surface"]
    overlaid_a_only, n_a = overlay_streamed_contract_fields(_CONTRACTS, {_ATM_CONTRACT_A: streamed_a})
    assert n_a == 1
    assert _cells_match_ignoring_vanna_drift(
        after_a["cells"], _backfilled(project_gamma_surface(overlaid_a_only, _SPOT))["cells"]), (
        "A's own overlay must apply first")
    # Sanity the overlay is not vacuous: A's injected gamma (0.05, real OI=1606) must
    # actually move the published surface away from the untouched REST baseline.
    assert after_a["cells"] != project_gamma_surface(_CONTRACTS, _SPOT)["cells"], (
        "the injected overlay must be quality-gate-plausible and economically material "
        "-- if this fires, the test's own inputs are vacuous again")

    # B ticks -- ITS OWN data becomes live now, A's streamed value is STILL live too
    # (the mock's A entry is unchanged) -- never surrendered.
    now_b = now_a + 0.01
    live[_ATM_CONTRACT_B] = streamed_b
    assert refresh_gamma_surface_from_stream(_ATM_CONTRACT_B, now_b) == "ok"

    overlaid_both, n_both = overlay_streamed_contract_fields(
        _CONTRACTS, {_ATM_CONTRACT_A: streamed_a, _ATM_CONTRACT_B: streamed_b})
    assert n_both == 2
    expected_after_b = _backfilled(project_gamma_surface(overlaid_both, _SPOT))
    with server._terrain_cache_lock:
        after_b = server._terrain_cache[TK]["_gamma_surface"]
    assert _cells_match_ignoring_vanna_drift(after_b["cells"], expected_after_b["cells"]), (
        "refreshing B must not undo A's already-applied fresh overlay -- THE defect "
        "as independently reproduced")
    assert after_b["stream_overlay_contracts"] == 2, (
        "the published surface must report BOTH contracts as overlaid, not just the "
        "one that triggered this particular refresh")
    # Sanity B's own overlay is not vacuous either: it must differ from A-only.
    assert after_b["cells"] != after_a["cells"], (
        "B's own strike must show B's own injected gamma, not merely repeat A's cells "
        "-- if this fires, B's injected value never reached the surface")


def test_a_dropped_from_the_desired_set_no_longer_lingers_in_a_later_b_refresh(monkeypatch):
    """The converse control: once A genuinely stops being desired (dropped from both the
    primary and additional slots — its coverage has actually ended), a LATER B refresh
    must reflect ONLY the currently-desired set. Proves this is reconstructed fresh on
    every call, not an unbounded accumulator that never forgets a symbol."""
    import app.options.order_flow.streaming as ofs
    ofs._active_option_contract = ofs.ticker_storage_key(_ATM_CONTRACT_A)
    ofs._active_option_contracts = [ofs.ticker_storage_key(_ATM_CONTRACT_B)]

    baseline_ts = time.time() - 10.0
    _put_rest_baseline(computed_ts_utc=baseline_ts)
    now = time.time()
    streamed_a = {"gamma": 0.05, "gamma_ts_recv": now}
    streamed_b = {"gamma": 0.08, "gamma_ts_recv": now}
    live = {_ATM_CONTRACT_A: streamed_a, _ATM_CONTRACT_B: streamed_b}
    monkeypatch.setattr(
        "app.options.order_flow.state.get_stream_greeks", lambda sym: live.get(sym))
    monkeypatch.setattr(server, "resolve_spot", lambda tk, **kw: (_SPOT, "stub", time.time()))
    assert refresh_gamma_surface_from_stream(_ATM_CONTRACT_A, now) == "ok"

    # A's coverage genuinely ends: no longer primary, never additional, and its live
    # streamed state is gone (clear_symbol removes it in production).
    ofs._active_option_contract = None
    del live[_ATM_CONTRACT_A]

    assert refresh_gamma_surface_from_stream(_ATM_CONTRACT_B, now + 0.01) == "ok"
    overlaid_b_only, n_b = overlay_streamed_contract_fields(_CONTRACTS, {_ATM_CONTRACT_B: streamed_b})
    assert n_b == 1
    expected = _backfilled(project_gamma_surface(overlaid_b_only, _SPOT))
    with server._terrain_cache_lock:
        cached = server._terrain_cache[TK]["_gamma_surface"]
    assert _cells_match_ignoring_vanna_drift(cached["cells"], expected["cells"]), "A must not linger once it truly stops being desired"
    assert cached["stream_overlay_contracts"] == 1
    # Sanity: this is a REAL regression control only if A's lingering would have been
    # visible -- confirm A's own strike differs from the untouched-A expectation.
    assert cached["cells"] != project_gamma_surface(
        _CONTRACTS, _SPOT)["cells"], "B's own overlay must still be visible in this surface"


def test_desired_stream_greeks_excludes_an_additional_contract_on_a_foreign_ticker(monkeypatch):
    """The primary-contract role already proves contract_matches_underlying excludes a
    foreign ticker's contract (test_gamma_surface_contracts_with_stream_overlay_ignores_a_
    foreign_ticker). _desired_stream_greeks_for_ticker applies that SAME filter uniformly
    to primary AND every additional contract in one loop -- adversarially checked here
    for the additional role specifically, not assumed to transfer from the primary case."""
    import app.options.order_flow.streaming as ofs

    foreign = "SPY   260911C00583000"   # a real-shaped OSI symbol, but SPY -- not CRWD
    ofs._active_option_contract = None   # no primary this tick
    ofs._active_option_contracts = [ofs.ticker_storage_key(foreign)]

    baseline_ts = time.time() - 10.0
    _put_rest_baseline(computed_ts_utc=baseline_ts)
    now = time.time()
    monkeypatch.setattr(
        "app.options.order_flow.state.get_stream_greeks",
        lambda sym: {"gamma": 0.99, "gamma_ts_recv": now} if sym == foreign else None)

    streamed = server._desired_stream_greeks_for_ticker(TK)
    assert streamed == {}, (
        f"a foreign ticker's additional contract must never overlay onto CRWD: {streamed}")

    out, n, syms = server._gamma_surface_contracts_with_stream_overlay(TK, _CONTRACTS)
    assert n == 0
    assert out == _CONTRACTS
    assert syms == []
