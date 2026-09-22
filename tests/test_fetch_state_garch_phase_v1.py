"""RC-REHAB-1 (Phase 4): _fetch_state decomposition, first extracted phase.

_garch_sigma_bars_for_state (server.py) is the GARCH Volatility Forecast phase, moved out of
_fetch_state's ~3,400-line body into a standalone function with an explicit
input/output contract, per docs/ANALYTICS_STATE_TIER_BOUNDARIES_V1.md's recommendation
that this territory only ever be decomposed phase-by-phase, never mechanically moved.

These tests prove the extraction is behavior-preserving: same computation, same
exception handling (including the pre-existing quirk where the RC-334 bar-mismatch
RuntimeError is swallowed by the same try/except that catches everything else in this
phase, deliberately NOT "fixed" as part of a decomposition), same result -- not merely
that the function exists.
"""
from __future__ import annotations

import random

import server as srv
import server_state_volatility as sv
from math_exposure import compute_garch_forecast, blend_garch_sigma


def _synthetic_closes(n: int = 61, seed: int = 42, start: float = 450.0) -> list[float]:
    """A random-walk close series long enough to clear the >20-bar GARCH floor."""
    rng = random.Random(seed)
    closes = [start]
    for _ in range(n - 1):
        closes.append(closes[-1] * (1 + rng.gauss(0, 0.0008)))
    return closes


def test_matches_the_original_inline_computation_chain_exactly():
    """The extracted function must produce BYTE-IDENTICAL output to calling
    compute_garch_forecast -> vol_percent_to_decimal -> blend_garch_sigma directly, the
    exact chain _fetch_state used to run inline before this extraction."""
    from volatility_regime import vol_percent_to_decimal
    from monte_carlo import BAR_MINUTES as _MC_BAR_MINUTES

    closes = _synthetic_closes()
    atm_iv, realized_vol, spot_f = 18.5, 15.0, closes[-1]

    result = srv._garch_sigma_bars_for_state(closes, atm_iv, realized_vol, spot_f)

    garch_raw = compute_garch_forecast(closes, horizon=srv.GARCH_HORIZON_BARS)
    expected = blend_garch_sigma(
        garch_raw,
        vol_percent_to_decimal(atm_iv),
        vol_percent_to_decimal(realized_vol),
        spot_f,
        bar_minutes=1.0,
    )

    assert result is not None, "GARCH extraction returned None on a real, adequate close series"
    assert len(result) == srv.GARCH_HORIZON_BARS, (
        f"expected {srv.GARCH_HORIZON_BARS} per-bar sigmas, got {len(result)}"
    )
    assert all(s > 0 for s in result), "every per-bar sigma must be a real, positive value"
    assert result == expected, "extraction diverged from the original inline call chain"
    # Sanity on the units contract the phase's own comment asserts (RC-334): this repo's
    # GARCH sigmas are built on one-minute closes and consumed as per-bar sigma at
    # monte_carlo.BAR_MINUTES -- if that constant ever moves, this is the fixture that
    # should catch it (not silently keep matching against a stale expectation).
    assert float(_MC_BAR_MINUTES) == 1.0, (
        "monte_carlo.BAR_MINUTES moved off 1.0 -- the RC-334 agreement this phase enforces "
        "is now live; test fixtures must be updated deliberately, not silently pass"
    )


def test_insufficient_history_returns_none_not_a_short_series():
    """The >20-bar floor must fail closed to None, never a shorter-than-requested result
    that could be mistaken for a real (if truncated) forecast."""
    closes = _synthetic_closes(n=15)
    assert srv._garch_sigma_bars_for_state(closes, 18.5, 15.0, closes[-1]) is None


def test_no_closes_returns_none():
    assert srv._garch_sigma_bars_for_state(None, 18.5, 15.0, 450.0) is None
    assert srv._garch_sigma_bars_for_state([], 18.5, 15.0, 450.0) is None


def test_exactly_twenty_bars_is_still_insufficient():
    """The original inline check was `len(_closes) > 20` (strictly greater) -- exactly 20
    must still return None, proving the boundary condition survived the extraction
    verbatim rather than drifting to `>=`."""
    closes = _synthetic_closes(n=20)
    assert len(closes) == 20
    assert srv._garch_sigma_bars_for_state(closes, 18.5, 15.0, closes[-1]) is None


def test_a_garch_or_blend_failure_is_swallowed_to_none_not_raised(monkeypatch):
    """The original inline try/except caught ANY exception from the GARCH/blend chain and
    debug-logged it, never propagating into _fetch_state. The extracted function must
    preserve that fail-closed contract exactly."""
    def _boom(*_a, **_kw):
        raise RuntimeError("synthetic GARCH failure")

    # RC-REHAB-1 (2026-09-22): _garch_sigma_bars_for_state moved to server_state_volatility
    # (module extraction) -- it now resolves compute_garch_forecast/blend_garch_sigma via
    # that module's own bound-name import, not server's, so the patch target moves with it.
    monkeypatch.setattr(sv, "compute_garch_forecast", _boom)
    closes = _synthetic_closes()
    # Must not raise -- the original inline block never let a GARCH failure escape into
    # the rest of _fetch_state's pipeline.
    assert srv._garch_sigma_bars_for_state(closes, 18.5, 15.0, closes[-1]) is None


def test_a_none_garch_raw_result_returns_none_without_calling_blend(monkeypatch):
    """Mirrors the original `if _garch_raw:` guard -- a falsy compute_garch_forecast
    result must short-circuit before blend_garch_sigma is ever called."""
    monkeypatch.setattr(sv, "compute_garch_forecast", lambda *_a, **_kw: None)
    blend_called = []
    monkeypatch.setattr(sv, "blend_garch_sigma", lambda *_a, **_kw: blend_called.append(1))
    closes = _synthetic_closes()
    result = srv._garch_sigma_bars_for_state(closes, 18.5, 15.0, closes[-1])
    assert result is None
    assert not blend_called, "blend_garch_sigma must not run when the raw GARCH forecast is falsy"


def test_fetch_state_still_calls_the_extracted_function_not_the_old_inline_block():
    """AST lock: _fetch_state's own body must call _garch_sigma_bars_for_state exactly
    once, and must NOT contain a second, independent inline reimplementation of the same
    compute_garch_forecast -> blend_garch_sigma chain -- that would be the exact
    two-producers-for-one-value defect class this repo's whole rehab has been closing."""
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
    assert calls_in_fetch_state.count("_garch_sigma_bars_for_state") == 1, (
        f"expected exactly one call to _garch_sigma_bars_for_state inside _fetch_state, "
        f"found {calls_in_fetch_state.count('_garch_sigma_bars_for_state')}"
    )
    assert "blend_garch_sigma" not in calls_in_fetch_state, (
        "_fetch_state still calls blend_garch_sigma directly -- the GARCH phase was not "
        "fully extracted, a second inline computation site survived"
    )
    assert "compute_garch_forecast" not in calls_in_fetch_state, (
        "_fetch_state still calls compute_garch_forecast directly -- the GARCH phase was "
        "not fully extracted, a second inline computation site survived"
    )
