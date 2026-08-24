"""monte_carlo.simulate behavioral locks (v2).

Extends tests/test_monte_carlo_chunk1_fail_closed.py with:
  - seeded determinism (identical full output) and seed sensitivity,
  - distribution sanity on known parameters (median / dispersion / expected
    move against the analytic GBM values, large n),
  - internal output consistency (band ordering, containment+expansion=1,
    excursions positive, echo of n_paths/horizon),
  - degenerate inputs: zero/negative horizon fail closed; floor-level vol,
  - regime sigma scaling and regime-confidence blending monotonicity,
  - wall-touch probability monotonicity and sidedness guards,
  - GARCH sigma path activation contract (length gate),
  - fail-closed on invalid params, including two strict xfails where NaN
    inputs currently slip past the ``<= 0`` guards and produce an
    available=True payload (suspected defect — see reasons on the marks).

simulate() consumes scalar spot/IV/vol parameters, not a market payload; no
captured-chain fixture applies at this seam (parameter values mirror the
module's own self-test: SPY-scale spot, 0.18 IV).
"""
from __future__ import annotations

import math

import pytest

from monte_carlo import ANNUALIZED_HOURS, BAR_MINUTES, _blend_sigma, simulate

SPOT = 100.0
IV = 0.20


def _run(**kw):
    base = dict(spot=SPOT, iv=IV, horizon_bars=20, n_paths=4000, seed=7)
    base.update(kw)
    return simulate(**base)


# ── Fail-closed on invalid params ────────────────────────────────────────────

@pytest.mark.parametrize("spot", [None, 0.0, -5.0])
def test_invalid_spot_fails_closed(spot):
    out = simulate(spot=spot, iv=IV, horizon_bars=10)
    assert out.available is False
    assert out.fallback_used is True
    assert out.median_path is None
    assert out.expected_favorable_excursion is None


@pytest.mark.parametrize("iv", [None, 0.0, -0.2])
def test_invalid_iv_fails_closed(iv):
    out = simulate(spot=SPOT, iv=iv, horizon_bars=10)
    assert out.available is False
    assert out.fallback_used is True


@pytest.mark.parametrize("horizon", [0, -3])
def test_zero_or_negative_horizon_fails_closed(horizon):
    out = simulate(spot=SPOT, iv=IV, horizon_bars=horizon)
    assert out.available is False
    assert out.fallback_used is True
    assert out.containment_prob is None


# FIXED (REHAB 2026-08-24): the guard is now NaN-safe (`not (spot > 0)`).
def test_nan_spot_should_fail_closed():
    out = simulate(spot=float("nan"), iv=IV, horizon_bars=10, n_paths=200, seed=1)
    assert out.available is False


# FIXED (REHAB 2026-08-24): the guard is now NaN-safe (`not (iv > 0)`).
def test_nan_iv_should_fail_closed():
    out = simulate(spot=SPOT, iv=float("nan"), horizon_bars=10, n_paths=200, seed=1)
    assert out.available is False


# ── Seeded determinism ───────────────────────────────────────────────────────

def test_same_seed_reproduces_identical_full_output():
    kw = dict(
        regime="breakout", regime_confidence="high", realized_vol=0.15, atr=0.4,
        call_gamma_wall=101.5, put_gamma_wall=98.5, em_upper=101.0, em_lower=99.0,
        model_prob_up=0.6, model_prob_down=0.2, model_confidence="high",
    )
    a = _run(seed=42, **kw)
    b = _run(seed=42, **kw)
    assert a.available and b.available
    assert a == b  # full dataclass equality, assumptions dict included


def test_different_seeds_produce_different_paths():
    a = _run(seed=1)
    b = _run(seed=2)
    assert a.available and b.available
    assert a.path_dispersion != b.path_dispersion


# ── Distribution sanity on known parameters ──────────────────────────────────

def _per_bar_sigma(annual_sigma: float) -> float:
    dt = BAR_MINUTES / (ANNUALIZED_HOURS * 60.0)
    return annual_sigma * math.sqrt(dt)


def test_driftless_gbm_median_and_dispersion_match_analytics():
    # IV-only blend, no regime, no models: sigma_bar = 0.20*sqrt(dt),
    # terminal std ~= spot*sigma_bar*sqrt(h); median ~= spot (drift 0).
    h = 20
    out = simulate(spot=SPOT, iv=IV, horizon_bars=h, n_paths=20000, seed=11)
    assert out.available is True
    sigma_bar = _per_bar_sigma(IV)
    expected_std = SPOT * sigma_bar * math.sqrt(h)
    assert out.median_path == pytest.approx(SPOT, abs=6.0 * expected_std / math.sqrt(20000) + 0.02)
    assert out.path_dispersion == pytest.approx(expected_std, rel=0.15)
    # E|terminal - spot| for a centered normal = std*sqrt(2/pi)
    assert out.expected_move == pytest.approx(expected_std * math.sqrt(2.0 / math.pi), rel=0.15)
    # Near-symmetric: negligible skew and directional bias at this scale.
    assert abs(out.skew) < 0.25
    assert abs(out.directional_bias) < 0.001


def test_band_ordering_and_positive_excursions():
    out = _run(n_paths=8000)
    assert out.available is True
    assert (
        out.lower_75 <= out.lower_50 <= out.lower_25
        <= out.median_path
        <= out.upper_25 <= out.upper_50 <= out.upper_75
    )
    assert out.expected_favorable_excursion > 0.0
    assert out.expected_adverse_excursion > 0.0
    assert out.path_dispersion > 0.0


def test_containment_and_expansion_are_complementary_probabilities():
    out = _run()
    assert out.containment_prob is not None
    assert 0.0 <= out.containment_prob <= 1.0
    assert 0.0 <= out.expansion_prob <= 1.0
    assert out.containment_prob + out.expansion_prob == pytest.approx(1.0, abs=0.002)


def test_output_echoes_requested_paths_and_horizon():
    out = _run(n_paths=1234, horizon_bars=7)
    assert out.n_paths == 1234
    assert out.horizon_bars == 7
    assert out.assumptions["n_paths"] == 1234
    assert out.assumptions["horizon_bars"] == 7


def test_floor_level_vol_produces_tight_bands_around_spot():
    # iv=1e-6 hits the 0.01 sigma floor: bands stay within a tenth of a percent.
    out = simulate(spot=SPOT, iv=1e-6, horizon_bars=10, n_paths=2000, seed=3)
    assert out.available is True
    for band in (out.lower_75, out.upper_75, out.median_path):
        assert abs(band - SPOT) < SPOT * 0.001
    assert out.path_dispersion < SPOT * 0.001


# ── Regime conditioning ──────────────────────────────────────────────────────

def test_pinning_regime_tighter_than_breakout_at_high_confidence():
    kw = dict(realized_vol=0.15, atr=0.4, seed=42, n_paths=6000)
    pin = _run(regime="pinning", regime_confidence="high", **kw)
    brk = _run(regime="breakout", regime_confidence="high", **kw)
    assert pin.path_dispersion < brk.path_dispersion
    assert pin.containment_prob >= brk.containment_prob
    assert pin.assumptions["regime_sigma_mult"] < brk.assumptions["regime_sigma_mult"]


def test_low_regime_confidence_blends_multiplier_toward_baseline():
    # pinning: high conf -> 0.60x; low conf -> 0.25*0.60+0.75 = 0.90x.
    hi = _run(regime="pinning", regime_confidence="high", seed=42)
    lo = _run(regime="pinning", regime_confidence="low", seed=42)
    base = _run(regime=None, seed=42)
    assert hi.assumptions["regime_sigma_mult"] == pytest.approx(0.60)
    assert lo.assumptions["regime_sigma_mult"] == pytest.approx(0.90)
    assert base.assumptions["regime_sigma_mult"] == pytest.approx(1.0)
    assert hi.path_dispersion < lo.path_dispersion < base.path_dispersion


def test_shock_term_only_arms_for_configured_regimes_with_atr():
    shock = _run(regime="vol_expansion", regime_confidence="high", atr=0.5, seed=5)
    calm = _run(regime="pinning", regime_confidence="high", atr=0.5, seed=5)
    no_atr = _run(regime="vol_expansion", regime_confidence="high", atr=None, seed=5)
    assert shock.assumptions["shock_enabled"] is True
    assert calm.assumptions["shock_enabled"] is False
    # Shock regime without ATR still reports shock_prob but cannot size a shock;
    # dispersion must not exceed the ATR-armed run's.
    assert no_atr.assumptions["shock_enabled"] is True
    assert no_atr.path_dispersion <= shock.path_dispersion


# ── Wall / EM probabilities ──────────────────────────────────────────────────

def test_nearer_call_wall_touches_more_often():
    near = _run(call_gamma_wall=SPOT + 0.10, seed=9)
    far = _run(call_gamma_wall=SPOT + 5.0, seed=9)
    assert near.prob_touch_upper_wall is not None
    assert far.prob_touch_upper_wall is not None
    assert near.prob_touch_upper_wall > far.prob_touch_upper_wall
    assert far.prob_touch_upper_wall == pytest.approx(0.0, abs=0.01)


def test_walls_on_wrong_side_of_spot_yield_no_probability():
    out = _run(call_gamma_wall=SPOT - 1.0, put_gamma_wall=SPOT + 1.0, seed=9)
    # A "call wall" below spot / "put wall" above spot is not a touch target:
    # withheld (None), never a fabricated 0 or 1.
    assert out.prob_touch_upper_wall is None
    assert out.prob_touch_lower_wall is None


def test_em_exceedance_probabilities_bounded_and_zero_for_absurd_band():
    tight = _run(em_upper=SPOT + 0.05, em_lower=SPOT - 0.05, seed=13)
    wide = _run(em_upper=SPOT * 1.5, em_lower=SPOT * 0.5, seed=13)
    assert 0.0 <= tight.prob_exceed_em_upper <= 1.0
    assert 0.0 <= tight.prob_exceed_em_lower <= 1.0
    assert wide.prob_exceed_em_upper == pytest.approx(0.0, abs=1e-9)
    assert wide.prob_exceed_em_lower == pytest.approx(0.0, abs=1e-9)
    # No EM band supplied -> withheld, not defaulted.
    none_given = _run(seed=13)
    assert none_given.prob_exceed_em_upper is None
    assert none_given.prob_exceed_em_lower is None


# ── GARCH sigma path contract ────────────────────────────────────────────────

def test_garch_sigma_used_only_when_it_covers_the_horizon():
    sigma_bar = _per_bar_sigma(IV)
    full = _run(horizon_bars=10, garch_sigma_bars=[sigma_bar] * 10)
    short = _run(horizon_bars=10, garch_sigma_bars=[sigma_bar] * 9)
    absent = _run(horizon_bars=10)
    assert full.assumptions["garch_active"] is True
    assert short.assumptions["garch_active"] is False
    assert absent.assumptions["garch_active"] is False
    assert full.available and short.available


# ── Sigma unit contract (path-independent reporting) ─────────────────────────

def test_sigma_reporting_fields_agree_across_garch_and_blend_paths():
    # Same volatility level fed through BOTH source paths: garch_sigma_bars is
    # constructed FROM the blend sigma (per-bar via sqrt(dt)). Every
    # sigma-reporting field must then agree across paths — no consumer may see
    # a number whose unit depends on which path ran.
    h = 12
    rv, atr = 0.15, 0.4
    blend_annual = _blend_sigma(IV, rv, atr, SPOT)
    bar = _per_bar_sigma(blend_annual)
    kw = dict(horizon_bars=h, realized_vol=rv, atr=atr, seed=33)
    garch = _run(garch_sigma_bars=[bar] * h, **kw)
    blend = _run(**kw)
    assert garch.assumptions["garch_active"] is True
    assert blend.assumptions["garch_active"] is False
    for key in ("blended_sigma", "scaled_sigma", "sigma_annualized", "sigma_bar_avg"):
        assert garch.assumptions[key] == pytest.approx(blend.assumptions[key], rel=5e-3), key


def test_sigma_bar_avg_matches_sigma_annualized_times_sqrt_dt_on_both_paths():
    # Unit relationship lock: sigma_bar_avg (per-1-minute-bar) must equal
    # sigma_annualized * sqrt(dt) on the blend path, the GARCH path, and a
    # regime-scaled run alike.
    dt = BAR_MINUTES / (ANNUALIZED_HOURS * 60.0)
    h = 12
    bar = _per_bar_sigma(IV)
    for out in (
        _run(horizon_bars=h, seed=5),                                              # blend path
        _run(horizon_bars=h, garch_sigma_bars=[bar] * h, seed=5),                  # GARCH path
        _run(horizon_bars=h, regime="pinning", regime_confidence="high", seed=5),  # regime-scaled blend
    ):
        assert out.available is True
        a = out.assumptions
        assert a["sigma_bar_avg"] == pytest.approx(a["sigma_annualized"] * math.sqrt(dt), rel=5e-3)


def test_garch_path_reports_annualized_not_per_bar_sigma():
    # Regression lock on the unit defect itself: with a flat GARCH vector at
    # the per-bar equivalent of 0.20 annualized, the reported sigmas must be at
    # ANNUALIZED magnitude (~0.20), not per-bar magnitude (~0.0006).
    h = 10
    bar = _per_bar_sigma(IV)
    out = _run(horizon_bars=h, garch_sigma_bars=[bar] * h)
    assert out.assumptions["garch_active"] is True
    assert out.assumptions["sigma_annualized"] == pytest.approx(IV, rel=1e-2)
    assert out.assumptions["scaled_sigma"] == pytest.approx(IV, rel=1e-2)
    assert out.assumptions["blended_sigma"] == pytest.approx(IV, rel=1e-2)
    assert out.assumptions["sigma_bar_avg"] == pytest.approx(bar, rel=1e-2)


def test_flat_garch_forecast_equal_to_blend_sigma_matches_blend_run():
    # A flat GARCH vector at exactly the blend's per-bar sigma must reproduce
    # the non-GARCH run (same rng seed, same per-step sigma).
    sigma_bar = _per_bar_sigma(IV)
    garch = _run(horizon_bars=10, garch_sigma_bars=[sigma_bar] * 10, seed=21)
    blend = _run(horizon_bars=10, seed=21)
    assert garch.median_path == pytest.approx(blend.median_path, abs=0.01)
    assert garch.path_dispersion == pytest.approx(blend.path_dispersion, rel=0.01)


# ── Suspected defect: model-derived drift is inert ───────────────────────────

# FIXED (REHAB 2026-08-24): the GBM step no longer re-multiplies the per-bar
# drift/variance term by dt — a directional model view now moves the median.
def test_strong_model_up_view_shifts_median_upward():
    kw = dict(
        regime="trend_continuation", regime_confidence="high",
        horizon_bars=20, n_paths=8000, seed=17,
    )
    with_view = _run(model_prob_up=1.0, model_prob_down=0.0, model_confidence="high", **kw)
    no_view = _run(**kw)
    # Expected (correct) shift: 20 bars * 0.3*sigma_bar drift ≈ +0.38 on spot 100.
    assert with_view.median_path - no_view.median_path > 0.1
