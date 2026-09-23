"""RC-REHAB-1 (Phase 4): _fetch_state decomposition, eighth extracted phase.

_predictive_positioning_for_state (server.py) is the Section 8 Predictive Positioning
Signals phase (DPI, hedging flow, gamma gradient, breakout score, pin score, vol
expansion, void factor, and the terrain-SSOT pin/regime reads build_market_state also
needs), moved out of _fetch_state's body into a standalone function returning a
_PredictivePositioningForState NamedTuple.

This slice also promoted _bucket_total_oi from a closure nested inside _fetch_state's
Section 8 block to a module-level function (server.py, see its own docstring): a SECOND
call site much later in _fetch_state's body (the Level Density sub-phase) also calls it,
and a nested def is only visible within the function it is defined in -- extracting
Section 8 into its own top-level function would have made that second call site's
reference unresolvable had this promotion not happened first.

Sweep Score is deliberately NOT part of this phase's return contract -- the original
inline code only pre-initializes `_sweep_score = {}` in the same banner scope (a
placeholder); its real value is computed in a LATER block needing
ms.nearest_above_dist/ms.nearest_below_dist, only available after build_market_state
runs. _fetch_state keeps that pre-initializer itself, unmoved.
"""
from __future__ import annotations

from unittest import mock

import server as srv
import server_state_predictive_positioning as spp
from math_exposure_core import bucket_total_oi
from math_exposure import (
    aggregate_net_gex,
    bucket_metric,
    compute_dealer_pressure_index,
    compute_gamma_gradient,
    compute_hedging_flow_score,
    compute_pin_score,
)
import terrain_loop


def _fixture_exposures():
    # Per-side dollar GEX is carried as a real bucket carries it (net = call - put, the
    # compute_exposures_by_strike convention). Without the per-side keys
    # exposures_have_dollar_gex() is False, aggregate_net_gex() returns None, and the
    # hedging-flow comparison below used to agree with production on a fabricated 0.0 GEX.
    return {
        445.0: {"net_dex_dollars": 1000.0, "call_oi": 500, "put_oi": 300, "call_vanna": 10.0, "put_vanna": -5.0,
                "call_gex_1pct": 2500.0, "put_gex_1pct": 500.0, "net_gex_1pct": 2000.0},
        450.0: {"net_dex_dollars": -500.0, "call_oi": 800, "put_oi": 600, "call_vanna": 20.0, "put_vanna": -8.0,
                "call_gex_1pct": 500.0, "put_gex_1pct": 1500.0, "net_gex_1pct": -1000.0},
        455.0: {"net_dex_dollars": 700.0, "call_oi": 400, "put_oi": 200, "call_vanna": 5.0, "put_vanna": -3.0,
                "call_gex_1pct": 2000.0, "put_gex_1pct": 500.0, "net_gex_1pct": 1500.0},
    }


def test_bucket_total_oi_promoted_to_module_level_matches_original_arithmetic():
    assert bucket_total_oi({"call_oi": 100, "put_oi": 50}) == 150.0
    assert bucket_total_oi({"call_oi": None, "put_oi": None}) is None
    assert bucket_total_oi({"call_oi": 100, "put_oi": None}) == 100.0
    assert bucket_total_oi({"call_oi": None, "put_oi": 50}) == 50.0


def test_full_pipeline_matches_the_original_computation_chain():
    exposures = _fixture_exposures()
    cons_strikes = sorted(exposures.keys())
    fake_terrain_snap = {
        "absolute_gamma_strike": 450.0,
        "levels_stale": False,
        "absolute_gamma_gex_dollars": 5000.0,
        "absolute_gamma_oi": 900.0,
        "book_oi_total": 3000.0,
        "net_gex_at_spot": -1200.0,
    }
    with mock.patch.object(terrain_loop, "terrain_cache_get", return_value=fake_terrain_snap):
        result = srv._predictive_positioning_for_state(
            "SPY", exposures, cons_strikes, 450.0, 12.5, [{"contains_spot": False, "lower": 448.0, "upper": 452.0}], "expanding",
        )

    # RC-REHAB-1 CAPS fix (twenty-first slice): DPI now sees the honest None from
    # aggregate_net_gex directly -- only the hedging-flow normalization further down
    # still coerces None to 0.0 (that math has no null-safe path of its own).
    _gex_raw = aggregate_net_gex(exposures, cons_strikes)
    sum_dex = sum(bucket_metric(b, "net_dex_dollars") for b in exposures.values())
    sum_oi = sum(bucket_total_oi(b) for b in exposures.values())
    sum_vanna = (
        sum(bucket_metric(b, "call_vanna") for b in exposures.values())
        + sum(bucket_metric(b, "put_vanna") for b in exposures.values())
    )
    expected_dpi = compute_dealer_pressure_index(sum_dex, _gex_raw, sum_oi)
    assert result.dpi == expected_dpi

    # The fixture carries real gamma, so the net GEX is a measured number; an `or 0.0` here
    # would let expected and actual agree on a fabricated zero.
    assert _gex_raw is not None, "fixture must produce a real net GEX"
    sum_gex = float(_gex_raw)
    max_gex, max_dex = max(abs(sum_gex), 1.0), max(abs(sum_dex), 1.0)
    max_charm, max_vanna = max(abs(12.5), 1.0), max(abs(sum_vanna), 1.0)
    expected_hedging = compute_hedging_flow_score(
        net_gex_normalized=sum_gex / max_gex,
        net_dex_normalized=sum_dex / max_dex,
        charm_normalized=12.5 / max_charm,
        vanna_normalized=sum_vanna / max_vanna,
    )
    assert result.hedging_flow == expected_hedging

    assert result.gamma_gradient == compute_gamma_gradient(exposures, 450.0)
    assert result.pin_strike == 450.0
    assert result.regime_gamma_at_spot == -1200.0

    expected_oi_concentration = 900.0 / 3000.0
    assert result.pin_score_val == compute_pin_score(5000.0, expected_oi_concentration)


def test_no_gex_data_reports_honest_none_dpi_not_a_fabricated_zero():
    """RC-REHAB-1 CAPS fix (twenty-first slice): a real "no GEX data" case
    (aggregate_net_gex returns None when cons_strikes is empty -- its own contract,
    math_exposure_core.py) must produce DPI's honest null-shaped result, not a
    fabricated "raw=0.0, direction=neutral, magnitude=negligible" reading that looks
    like a real (if weak) measurement. compute_dealer_pressure_index was already
    built to handle net_gex=None this way; the old code coerced it to 0.0 before it
    ever got there."""
    exposures = _fixture_exposures()
    with mock.patch.object(terrain_loop, "terrain_cache_get", return_value=None):
        result = srv._predictive_positioning_for_state(
            "SPY", exposures, [], 450.0, 5.0, [], "flat",
        )
    assert aggregate_net_gex(exposures, []) is None  # the precondition this test relies on
    assert result.dpi == {"raw": None, "normalized": None, "direction": None, "magnitude": None}
    assert result.dpi != {"raw": 0.0, "normalized": 0.0, "direction": "buying", "magnitude": "negligible"}


def test_stale_terrain_snapshot_withholds_pin_and_regime():
    exposures = _fixture_exposures()
    with mock.patch.object(terrain_loop, "terrain_cache_get", return_value={"absolute_gamma_strike": 450.0, "levels_stale": True}):
        result = srv._predictive_positioning_for_state("SPY", exposures, [450.0], 450.0, 5.0, [], "flat")
    assert result.pin_strike is None
    assert result.regime_gamma_at_spot is None


def test_missing_terrain_snapshot_withholds_pin_and_regime():
    exposures = _fixture_exposures()
    with mock.patch.object(terrain_loop, "terrain_cache_get", return_value=None):
        result = srv._predictive_positioning_for_state("SPY", exposures, [450.0], 450.0, 5.0, [], "flat")
    assert result.pin_strike is None
    assert result.regime_gamma_at_spot is None


def test_total_failure_fails_closed_to_defaults_never_raises():
    """The gamma-audit 2026-08-26 fix this phase preserves: pin_strike and
    regime_gamma_at_spot are pre-initialized to None BEFORE the try block, so a raise
    anywhere earlier in the phase still leaves them safely None for build_market_state
    to consume -- never an UNDEFINED name that would crash the ENTIRE market state
    build for one failed sub-computation."""
    exposures = _fixture_exposures()
    # Patched on server_state_predictive_positioning, not srv: aggregate_net_gex is
    # imported directly there (module-level, not lazily via `import server as _srv`),
    # so that is the name the real call site actually resolves against.
    with mock.patch.object(spp, "aggregate_net_gex", side_effect=RuntimeError("boom")):
        result = srv._predictive_positioning_for_state("SPY", exposures, [450.0], 450.0, 5.0, [], "flat")

    assert result.dpi == {}
    assert result.hedging_flow == {}
    assert result.gamma_gradient is None
    assert result.breakout_score == {}
    assert result.pin_score_val == {}
    assert result.vol_expansion == {}
    assert result.void_factor == 0.0
    assert result.pin_strike is None
    assert result.regime_gamma_at_spot is None


def test_fetch_state_calls_the_extracted_function_exactly_once():
    """AST lock: _fetch_state must call _predictive_positioning_for_state exactly once,
    and must not directly call compute_dealer_pressure_index/compute_hedging_flow_score/
    compute_gamma_gradient/compute_breakout_score/compute_pin_score/
    compute_vol_expansion_signal itself."""
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
    assert calls_in_fetch_state.count("_predictive_positioning_for_state") == 1
    for leaked in (
        "compute_dealer_pressure_index",
        "compute_hedging_flow_score",
        "compute_gamma_gradient",
        "compute_breakout_score",
        "compute_pin_score",
        "compute_vol_expansion_signal",
    ):
        assert leaked not in calls_in_fetch_state, (
            f"_fetch_state still calls {leaked} directly -- the predictive-positioning "
            f"phase was not fully extracted, a second inline computation site survived"
        )
    # The per-bucket OI helper's SECOND caller (the no-gamma-void diagnostic) moved with the
    # payload projection into server_state_payload.py (thirty-third slice); both callers now
    # import the one definition, math_exposure_core.bucket_total_oi.
    import inspect

    import server_state_payload

    assert "bucket_total_oi(" in inspect.getsource(server_state_payload._log_why_no_gamma_voids)
    assert "bucket_total_oi(" in inspect.getsource(spp._predictive_positioning_for_state)
    assert not hasattr(srv, "_bucket_total_oi"), "a second copy of the OI helper is back in server.py"
