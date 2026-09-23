"""RC-REHAB-1 (Phase 4): _fetch_state decomposition, ninth extracted phase.

_exposures_for_state (server.py) is the Exposures phase (candle tick feed,
seed-from-price-history-on-stale-grid, GEX/DEX/vanna by strike, and the
summary/wall/totals rows built from it), moved out of _fetch_state's body into
a standalone function returning an _ExposuresForState NamedTuple.

Callers must have already handled the `spot is None` guard -- that guard
clause stays inline in _fetch_state (it is a full early-return out of the
function, which a helper cannot do), and this function assumes a real,
non-None spot was passed in.

A genuine subtlety this phase's tests protect: the original inline code's
candle-seed try block does `client = get_client()`, rebinding _fetch_state's
own `client` local -- a value the Price Levels phase reads afterward.
get_client() is a cached singleton in practice, so this is normally a no-op,
but the extracted function returns the (possibly rebound) client explicitly
so _fetch_state can rebind its own `client` from the return value and match
the original behavior exactly, not just "close enough".

RC-REHAB-1 (2026-09-23, module extraction, twenty-third slice): the function
itself moved out of server.py into server_state_exposures.py (ses below);
server.py keeps a re-export so srv._exposures_for_state still resolves, but
compute_exposures_by_strike/build_summary_rows/build_walls_rows/
build_totals_rows/pick_net_gex_peak_strike/EXPOSURE_WINDOWS are no longer bound
on srv -- they're imported/defined directly in ses, matching what ses itself
does. get_client stays bound on srv (it has 27 other call sites and stays in
server.py, reached lazily) so mocking srv.get_client is unaffected; but
safe_get_price_history is imported directly in ses (module-level, not lazily
via `import server`), so it must be mocked on ses, not srv.
"""
from __future__ import annotations

from unittest import mock

import server as srv
import server_state_exposures as ses


def _fixture_contracts():
    # institutional-synthetic-ok: this test verifies _exposures_for_state's own
    # aggregation/rows/walls/totals pipeline in isolation against a minimal,
    # deterministic two-strike fixture -- a real captured chain would obscure which
    # specific contract drives each aggregate and make the expected values opaque.
    # multiplier/volatility are required for compute_exposures_by_strike to treat a
    # contract as usable (missing multiplier -> silently filtered, empty exposures).
    return [
        {"strikePrice": 100.0, "putCall": "CALL", "openInterest": 500, "delta": 0.5, "gamma": 0.05, "vega": 0.1, "volatility": 0.2, "multiplier": 100, "totalVolume": 200, "mark": 2.0, "bid": 1.9, "ask": 2.1},
        {"strikePrice": 100.0, "putCall": "PUT", "openInterest": 300, "delta": -0.5, "gamma": 0.05, "vega": 0.1, "volatility": 0.2, "multiplier": 100, "totalVolume": 150, "mark": 1.8, "bid": 1.7, "ask": 1.9},
        {"strikePrice": 105.0, "putCall": "CALL", "openInterest": 400, "delta": 0.3, "gamma": 0.04, "vega": 0.08, "volatility": 0.2, "multiplier": 100, "totalVolume": 100, "mark": 1.0, "bid": 0.9, "ask": 1.1},
        {"strikePrice": 105.0, "putCall": "PUT", "openInterest": 200, "delta": -0.3, "gamma": 0.04, "vega": 0.08, "volatility": 0.2, "multiplier": 100, "totalVolume": 80, "mark": 3.0, "bid": 2.9, "ask": 3.1},
    ]


def test_full_pipeline_matches_the_original_computation_chain():
    contracts = _fixture_contracts()
    client = object()
    ticker = "ZZZ_EXPOSURES_TEST"

    orig_grid_stale = srv._candles_1m.grid_stale
    srv._candles_1m.grid_stale = lambda *a, **k: False
    try:
        result = srv._exposures_for_state(
            ticker, client, 100.5, contracts, 1000.0, None, 12345.0, True, False,
        )

        exposures2, diag2 = ses.compute_exposures_by_strike(contracts, spot=100.5, require_oi=True)
        cons2 = sorted(float(k) for k in exposures2.keys())
        from math_exposure_core import key_level_strikes_with_gamma
        gamma2 = key_level_strikes_with_gamma(exposures2) or cons2
        pin2 = ses.pick_net_gex_peak_strike(exposures2, gamma2, institutional=True) if gamma2 else None
        rows2 = ses.build_summary_rows(exposures2, 100.5, windows=ses.EXPOSURE_WINDOWS)
        walls2 = ses.build_walls_rows(exposures2, 100.5)
        from math_levels import consensus_walls_bind_terrain_ssot
        walls2 = consensus_walls_bind_terrain_ssot(walls2, srv.terrain_cache_get(ticker) or {})
        totals2 = ses.build_totals_rows(exposures2, 100.5, windows=ses.EXPOSURE_WINDOWS, contracts_for_iv=contracts)

        assert result.spot_f == 100.5
        assert result.tick_ts == 1000.0
        assert result.exposures, "fixture must produce real, non-degenerate exposures"
        assert result.exposures == exposures2
        assert result.cons_strikes == cons2
        assert result.gamma_strikes == gamma2
        assert result.institutional_pin == pin2
        assert result.rows == rows2
        assert result.walls == walls2
        assert result.totals == totals2
        assert result.client is client
    finally:
        srv._candles_1m.grid_stale = orig_grid_stale


def test_tick_ts_falls_back_to_trade_time_when_quote_time_missing():
    contracts = _fixture_contracts()
    orig_grid_stale = srv._candles_1m.grid_stale
    srv._candles_1m.grid_stale = lambda *a, **k: False
    try:
        result = srv._exposures_for_state(
            "ZZZ_EXPOSURES_TICK", object(), 100.5, contracts, None, 555.0, None, True, False,
        )
        assert result.tick_ts == 555.0
    finally:
        srv._candles_1m.grid_stale = orig_grid_stale


def test_client_rebound_from_get_client_on_the_seed_path():
    """The original inline code's `client = get_client()` inside the candle-seed try
    block rebinds _fetch_state's own `client` local -- preserved here via the return
    value rather than a parameter mutation (which would not propagate to the caller)."""
    contracts = _fixture_contracts()
    orig_client = object()
    new_client = object()

    orig_grid_stale = srv._candles_1m.grid_stale
    srv._candles_1m.grid_stale = lambda *a, **k: True
    try:
        with mock.patch.object(srv, "get_client", return_value=new_client), \
             mock.patch.object(ses, "safe_get_price_history", return_value=None):
            result = srv._exposures_for_state(
                "ZZZ_EXPOSURES_SEED", orig_client, 100.5, contracts, None, None, None, True, False,
            )
        assert result.client is new_client
    finally:
        srv._candles_1m.grid_stale = orig_grid_stale


def test_client_passes_through_unchanged_when_grid_is_not_stale():
    contracts = _fixture_contracts()
    orig_client = object()

    orig_grid_stale = srv._candles_1m.grid_stale
    srv._candles_1m.grid_stale = lambda *a, **k: False
    try:
        result = srv._exposures_for_state(
            "ZZZ_EXPOSURES_NOSEED", orig_client, 100.5, contracts, None, None, None, True, False,
        )
        assert result.client is orig_client
    finally:
        srv._candles_1m.grid_stale = orig_grid_stale


def test_candle_seed_failure_is_swallowed_and_does_not_raise():
    """A price-history fetch exception during seeding must be caught and logged, exactly
    like the original inline `except Exception as e: log.debug(...)` block -- never
    propagate out of the phase."""
    contracts = _fixture_contracts()

    orig_grid_stale = srv._candles_1m.grid_stale
    srv._candles_1m.grid_stale = lambda *a, **k: True
    try:
        with mock.patch.object(srv, "get_client", side_effect=RuntimeError("boom")):
            result = srv._exposures_for_state(
                "ZZZ_EXPOSURES_FAIL", object(), 100.5, contracts, None, None, None, True, False,
            )
        # Seeding failed, but the rest of the phase (exposures/rows/walls/totals) still runs.
        assert result.exposures
    finally:
        srv._candles_1m.grid_stale = orig_grid_stale


def test_fetch_state_calls_the_extracted_function_exactly_once():
    """AST lock: _fetch_state must call _exposures_for_state exactly once, and must not
    directly call compute_exposures_by_strike/build_summary_rows/build_walls_rows/
    build_totals_rows/pick_net_gex_peak_strike itself."""
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
    assert calls_in_fetch_state.count("_exposures_for_state") == 1
    for leaked in (
        "compute_exposures_by_strike",
        "build_summary_rows",
        "build_walls_rows",
        "build_totals_rows",
        "pick_net_gex_peak_strike",
    ):
        assert leaked not in calls_in_fetch_state, (
            f"_fetch_state still calls {leaked} directly -- the exposures phase was not "
            f"fully extracted, a second inline computation site survived"
        )
