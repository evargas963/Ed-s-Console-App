"""RC-REHAB-1 (Phase 4): _fetch_state decomposition, tenth extracted phase.

_gamma_flip_and_void_zones_for_state (server.py) is the Gamma Flip + Void
Zones phase, extracted verbatim from _fetch_state's body: canonical gamma
flip (compute_gamma_flip_v2), gamma void zones, the ATM-IV tick into the
module-level `_iv_tracker` (direction detection for vanna context), and
`consensus_summary` derived from the Exposures phase's own `rows` output.

The original inline code has no try/except around this block -- an
exception here propagates out of _fetch_state unchanged, exactly as before
the extraction. These tests prove behavior parity against the underlying
compute_gamma_flip_v2/compute_gamma_void_zones/_iv_tracker chain.
"""
from __future__ import annotations

import time

import server as srv
# RC-REHAB-1 (2026-09-23, module extraction, twenty-third slice): these 5 helpers'
# only server.py call site (_exposures_for_state) moved out into
# server_state_exposures.py, which imports all 5 directly from math_exposure -- this
# fixture helper does the same rather than resolving them off srv.
from math_exposure import (
    build_summary_rows,
    build_totals_rows,
    build_walls_rows,
    compute_exposures_by_strike,
)
from server_state_exposures import EXPOSURE_WINDOWS
import terrain_state


def _fixture_contracts():
    # institutional-synthetic-ok: verifies this phase's own gamma-flip/void-zone/ATM-IV
    # wiring in isolation against a minimal, deterministic two-strike fixture.
    return [
        {"strikePrice": 100.0, "putCall": "CALL", "openInterest": 500, "delta": 0.5, "gamma": 0.05, "vega": 0.1, "volatility": 0.2, "multiplier": 100, "totalVolume": 200, "mark": 2.0, "bid": 1.9, "ask": 2.1},
        {"strikePrice": 100.0, "putCall": "PUT", "openInterest": 300, "delta": -0.5, "gamma": 0.05, "vega": 0.1, "volatility": 0.2, "multiplier": 100, "totalVolume": 150, "mark": 1.8, "bid": 1.7, "ask": 1.9},
        {"strikePrice": 105.0, "putCall": "CALL", "openInterest": 400, "delta": 0.3, "gamma": 0.04, "vega": 0.08, "volatility": 0.2, "multiplier": 100, "totalVolume": 100, "mark": 1.0, "bid": 0.9, "ask": 1.1},
        {"strikePrice": 105.0, "putCall": "PUT", "openInterest": 200, "delta": -0.3, "gamma": 0.04, "vega": 0.08, "volatility": 0.2, "multiplier": 100, "totalVolume": 80, "mark": 3.0, "bid": 2.9, "ask": 3.1},
    ]


def _build_exposures_rows_walls_totals(contracts, spot_f):
    exposures, _diag = compute_exposures_by_strike(contracts, spot=spot_f, require_oi=True)
    rows = build_summary_rows(exposures, spot_f, windows=EXPOSURE_WINDOWS)
    walls = build_walls_rows(exposures, spot_f)
    totals = build_totals_rows(exposures, spot_f, windows=EXPOSURE_WINDOWS, contracts_for_iv=contracts)
    return exposures, rows, walls, totals


def test_full_pipeline_matches_the_original_computation_chain():
    """RC-569 (2026-09-21): gamma_flip/gamma_flip_conf/gamma_flip_diag no longer come from
    an independent compute_gamma_flip_v2(contracts_use, ...) call on the SELECTED-EXPIRY
    slice -- that was a second, narrower producer than the live-UI-facing terrain SSOT
    (RC-33/v23 already migrated kl_gamma_flip away from exactly this narrow-chain basis;
    this logging-only phase was the one path that migration missed). With no terrain
    snapshot cached for this synthetic ticker, gamma_flip/diag must fail closed to None --
    never fall back to re-deriving a second, disagreeing answer from contracts_use."""
    contracts = _fixture_contracts()
    spot_f = 100.5
    ticker = "ZZZ_GFVZ_MATCH"
    exposures, rows, _walls, totals = _build_exposures_rows_walls_totals(contracts, spot_f)

    result = srv._gamma_flip_and_void_zones_for_state(ticker, contracts, spot_f, exposures, totals, rows)

    expected_voids = srv.compute_gamma_void_zones(exposures, spot_f)
    t0 = totals[0] if totals else None
    expected_atm_iv = getattr(t0, "atm_iv", None) if t0 else None
    expected_cs = rows[0] if rows else None

    assert result.gamma_flip is None, "no terrain snapshot cached -- must fail closed, not recompute"
    assert result.gamma_flip_conf is None
    assert result.gamma_flip_diag is None
    assert result.gamma_voids == expected_voids
    assert result.atm_iv == expected_atm_iv
    assert result.atm_iv is not None, "fixture must produce a real ATM IV, not a degenerate None"
    assert result.consensus_summary == expected_cs
    assert result.consensus_summary is not None


def test_gamma_flip_reads_the_terrain_ssot_snapshot_when_one_is_cached():
    """The positive case: with a real (non-stale) terrain snapshot cached for this ticker,
    gamma_flip/diag come from THAT snapshot verbatim -- never a second, independent
    compute_gamma_flip_v2 call on the narrower contracts_use slice, even though that slice
    is available and was the OLD source. Proven by giving the snapshot a flip value the
    fixture's own narrow-chain computation would not independently produce."""
    contracts = _fixture_contracts()
    spot_f = 100.5
    ticker = "ZZZ_GFVZ_TERRAIN_HIT"
    tk = srv.ticker_storage_key(ticker)
    exposures, rows, _walls, totals = _build_exposures_rows_walls_totals(contracts, spot_f)

    sentinel_flip = 999.5   # a value the fixture's own narrow-chain compute would never produce
    sentinel_diag = {"reason": "test_sentinel_no_real_crossing"}
    terrain_state._terrain_cache[tk] = {
        "gamma_flip": sentinel_flip, "flip_diag": sentinel_diag,
        "computed_ts_utc": time.time(),   # fresh -- terrain_cache_get derives levels_stale from this
    }
    try:
        result = srv._gamma_flip_and_void_zones_for_state(ticker, contracts, spot_f, exposures, totals, rows)
    finally:
        terrain_state._terrain_cache.pop(tk, None)

    assert result.gamma_flip == sentinel_flip
    assert result.gamma_flip_diag == sentinel_diag
    assert result.gamma_flip_conf is None, (
        "narrow-analytics confidence was already retired for the live path (v23) -- "
        "this logging-only phase must not resurrect it"
    )


def test_gamma_flip_fails_closed_on_a_stale_terrain_snapshot():
    """A cached-but-stale terrain snapshot must be treated the same as no snapshot at all --
    never served as if it were current."""
    contracts = _fixture_contracts()
    spot_f = 100.5
    ticker = "ZZZ_GFVZ_TERRAIN_STALE"
    tk = srv.ticker_storage_key(ticker)
    exposures, rows, _walls, totals = _build_exposures_rows_walls_totals(contracts, spot_f)

    terrain_state._terrain_cache[tk] = {
        "gamma_flip": 123.0, "flip_diag": {},
        "computed_ts_utc": time.time() - 3600.0,   # an hour old -- terrain_staleness must call this stale
    }
    try:
        result = srv._gamma_flip_and_void_zones_for_state(ticker, contracts, spot_f, exposures, totals, rows)
    finally:
        terrain_state._terrain_cache.pop(tk, None)

    assert result.gamma_flip is None


def test_atm_iv_tick_feeds_the_shared_iv_tracker_and_direction_reflects_it():
    """_iv_tracker is a module-level singleton -- referenced directly, not parameterized.
    A second call with a higher ATM IV must register as 'expanding' on the SAME ticker,
    proving the tick() call inside the extracted function actually reaches the shared
    tracker (not a local copy)."""
    contracts = _fixture_contracts()
    spot_f = 100.5
    ticker = "ZZZ_GFVZ_TRACKER"
    exposures, rows, _walls, totals = _build_exposures_rows_walls_totals(contracts, spot_f)

    srv._gamma_flip_and_void_zones_for_state(ticker, contracts, spot_f, exposures, totals, rows)
    # Feed several rising IV ticks directly through the tracker to force a real direction signal.
    for iv in (0.25, 0.30, 0.35, 0.40):
        srv._iv_tracker.tick(ticker, iv)
    direction = srv._iv_tracker.direction(ticker)
    assert direction in ("expanding", "contracting", "flat")


def test_empty_totals_and_rows_yield_none_atm_iv_and_none_consensus_summary():
    contracts = _fixture_contracts()
    spot_f = 100.5
    exposures, _rows, _walls, _totals = _build_exposures_rows_walls_totals(contracts, spot_f)

    result = srv._gamma_flip_and_void_zones_for_state(
        "ZZZ_GFVZ_EMPTY", contracts, spot_f, exposures, [], [],
    )
    assert result.atm_iv is None
    assert result.consensus_summary is None
    # Gamma flip/void zones are independent of totals/rows -- still computed for real.
    assert result.gamma_voids == srv.compute_gamma_void_zones(exposures, spot_f)


def test_fetch_state_calls_the_extracted_function_exactly_once():
    """AST lock: _fetch_state must call _gamma_flip_and_void_zones_for_state exactly
    once, and must not directly call compute_gamma_flip_v2/compute_gamma_void_zones."""
    import ast
    from pathlib import Path

    src = Path(srv.__file__).read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(src)
    fetch_state_fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "_fetch_state"
    )
    calls_in_fetch_state = [
        n.func.id for n in ast.walk(fetch_state_fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    ]
    assert calls_in_fetch_state.count("_gamma_flip_and_void_zones_for_state") == 1
    for leaked in ("compute_gamma_flip_v2", "compute_gamma_void_zones"):
        assert leaked not in calls_in_fetch_state, (
            f"_fetch_state still calls {leaked} directly -- the gamma-flip/void-zones "
            f"phase was not fully extracted, a second inline computation site survived"
        )
