"""RC-REHAB-1 (Phase 4): _fetch_state decomposition, sixteenth extracted phase.

_vol_envelope_and_sector_for_state (server.py) is the Volatility Envelope, Level
Density, and Sector Strength phase, extracted verbatim from _fetch_state's body.

The most important behavior this phase preserves: vol_ctx's own computation (the VIX
tracker tick, MarketVolContextV1 construction, record_market_vol_observation) sits
OUTSIDE the try/except that wraps envelope/density/sector-strength/iwm-deep. vol_ctx
must be bound on every path that reaches build_market_state / the persistence tail /
ms_dict -- a swallowed envelope exception must degrade envelope fields only, never
unbind the vol context (a NameError there would break the whole serve cycle).

RC-REHAB-1 (2026-09-23, module extraction, twenty-second slice): the function itself
moved out of server.py into server_state_vol_envelope_sector.py (ves below);
server.py keeps a re-export so srv._vol_envelope_and_sector_for_state still resolves,
but compute_volatility_envelope/compute_sector_strength/etc. are no longer bound on
srv -- they're imported directly here from math_exposure, matching what ves itself
does.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import server as srv
import server_state_vol_envelope_sector as ves
from math_exposure import compute_sector_strength, compute_volatility_envelope


def _fixture_mkt_ctx(vix=18.5):
    return SimpleNamespace(
        vix=vix, spy_chg_pct=0.5, qqq_chg_pct=0.3, iwm_chg_pct=-0.2,
        constituents=[
            SimpleNamespace(symbol="aapl", chg_pct=1.2),
            SimpleNamespace(symbol="msft", chg_pct=-0.4),
        ],
        iwm_sectors=[
            SimpleNamespace(symbol="kre", chg_pct=0.8),
            SimpleNamespace(symbol="xbi", chg_pct=-1.1),
        ],
    )


def _fixture_walls():
    return [SimpleNamespace(
        call_gamma_wall=105.0, put_gamma_wall=95.0,
        call_delta_wall=104.0, put_delta_wall=96.0,
    )]


def test_full_pipeline_matches_the_original_computation_chain():
    mkt_ctx = _fixture_mkt_ctx()
    walls = _fixture_walls()
    cache_key = "ZZZ_VES_MATCH|None"
    srv._state_cache.pop(cache_key, None)

    result = srv._vol_envelope_and_sector_for_state("ZZZ_VES_MATCH", 100.0, 2.5, walls, mkt_ctx, cache_key)

    assert result.vol_envelope == compute_volatility_envelope(100.0, 2.5)
    assert result.index_strength == compute_sector_strength({"SPY": 0.5, "QQQ": 0.3, "IWM": -0.2})
    assert result.spy_strength == compute_sector_strength({"AAPL": 1.2, "MSFT": -0.4})
    assert result.sector_strength == compute_sector_strength({"KRE": 0.8, "XBI": -1.1})
    assert result.vol_ctx.market_iv_level == 18.5
    assert result.vol_ctx.quality_status == "VALID"
    assert result.iwm_deep, "fixture must produce a real, non-degenerate iwm_deep result"


def test_vol_ctx_stays_bound_when_envelope_computation_raises():
    mkt_ctx = _fixture_mkt_ctx()
    walls = _fixture_walls()
    cache_key = "ZZZ_VES_FAIL|None"
    srv._state_cache.pop(cache_key, None)

    # Patched on server_state_vol_envelope_sector, not srv: compute_volatility_envelope
    # is imported directly there (module-level, not lazily via `import server`), so
    # that is the name the real call site actually resolves against.
    with mock.patch.object(ves, "compute_volatility_envelope", side_effect=RuntimeError("boom")):
        result = srv._vol_envelope_and_sector_for_state("ZZZ_VES_FAIL", 100.0, 2.5, walls, mkt_ctx, cache_key)

    assert result.vol_ctx.market_iv_level == 18.5, (
        "vol_ctx must remain bound to a real value even when the envelope/density/"
        "sector try block fails entirely"
    )
    assert result.vol_ctx.quality_status == "VALID"
    assert result.vol_envelope == {}
    assert result.level_density == {}
    assert result.sector_strength == {}
    assert result.index_strength == {}
    assert result.spy_strength == {}
    assert result.iwm_deep == {}


def test_missing_vix_yields_unavailable_quality_status():
    mkt_ctx = _fixture_mkt_ctx(vix=None)
    walls = _fixture_walls()
    cache_key = "ZZZ_VES_NOVIX|None"
    srv._state_cache.pop(cache_key, None)

    result = srv._vol_envelope_and_sector_for_state("ZZZ_VES_NOVIX", 100.0, 2.5, walls, mkt_ctx, cache_key)
    assert result.vol_ctx.market_iv_level is None
    assert result.vol_ctx.quality_status == "UNAVAILABLE"


def test_vix_change_computed_against_previous_published_value():
    mkt_ctx = _fixture_mkt_ctx(vix=20.0)
    walls = _fixture_walls()
    cache_key = "ZZZ_VES_DELTA|None"
    srv._state_cache[cache_key] = {"vix": 18.0}
    try:
        result = srv._vol_envelope_and_sector_for_state("ZZZ_VES_DELTA", 100.0, 2.5, walls, mkt_ctx, cache_key)
        assert result.vol_ctx.market_iv_change == 2.0
    finally:
        srv._state_cache.pop(cache_key, None)


def test_fetch_state_calls_the_extracted_function_exactly_once():
    """AST lock: _fetch_state must call _vol_envelope_and_sector_for_state exactly
    once, and must not directly call compute_volatility_envelope/compute_level_density/
    compute_sector_strength/compute_iwm_confluence itself."""
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
    assert calls_in_fetch_state.count("_vol_envelope_and_sector_for_state") == 1
    for leaked in (
        "compute_volatility_envelope",
        "compute_level_density",
        "compute_sector_strength",
        "compute_iwm_confluence",
    ):
        assert leaked not in calls_in_fetch_state, (
            f"_fetch_state still calls {leaked} directly -- the vol-envelope/sector "
            f"phase was not fully extracted, a second inline computation site survived"
        )
