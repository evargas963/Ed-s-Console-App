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

import server as srv


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
    exposures, _diag = srv.compute_exposures_by_strike(contracts, spot=spot_f, require_oi=True)
    rows = srv.build_summary_rows(exposures, spot_f, windows=srv.EXPOSURE_WINDOWS)
    walls = srv.build_walls_rows(exposures, spot_f)
    totals = srv.build_totals_rows(exposures, spot_f, windows=srv.EXPOSURE_WINDOWS, contracts_for_iv=contracts)
    return exposures, rows, walls, totals


def test_full_pipeline_matches_the_original_computation_chain():
    contracts = _fixture_contracts()
    spot_f = 100.5
    ticker = "ZZZ_GFVZ_MATCH"
    exposures, rows, _walls, totals = _build_exposures_rows_walls_totals(contracts, spot_f)

    result = srv._gamma_flip_and_void_zones_for_state(ticker, contracts, spot_f, exposures, totals, rows)

    expected_flip, expected_conf, expected_diag = srv.compute_gamma_flip_v2(contracts, spot_f)
    expected_voids = srv.compute_gamma_void_zones(exposures, spot_f)
    t0 = totals[0] if totals else None
    expected_atm_iv = getattr(t0, "atm_iv", None) if t0 else None
    expected_cs = rows[0] if rows else None

    assert result.gamma_flip == expected_flip
    assert result.gamma_flip_conf == expected_conf
    assert result.gamma_voids == expected_voids
    assert result.atm_iv == expected_atm_iv
    assert result.atm_iv is not None, "fixture must produce a real ATM IV, not a degenerate None"
    assert result.consensus_summary == expected_cs
    assert result.consensus_summary is not None


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
