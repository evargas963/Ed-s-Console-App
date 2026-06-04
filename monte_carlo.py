"""
monte_carlo.py
Regime-aware stochastic-volatility Monte Carlo path engine.

Phase 5 of the Canonical Implementation Roadmap.
Phase 1 Consultant Upgrade: regime-conditioned sigma, state-aware drift, shock behavior.

VERSION: mc_v2 (regime-aware stochastic volatility)

Changes from mc_v1:
  - sigma blended from IV + realized vol + ATR (not just IV)
  - sigma regime-scaled (pinning=0.70x, breakout=1.30x)
  - sigma random-walks per-step (stochastic vol, vol-of-vol=8%)
  - drift model-derived, confidence-scaled, regime-damped
  - regime-gated shock term for breakout/acceleration/vol-expansion/reversal
  - output contract preserved — downstream consumers unchanged
"""
from __future__ import annotations

import math
import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

log = logging.getLogger(__name__)

DEFAULT_N_PATHS     = 10000
DEFAULT_HORIZON     = 13
ANNUALIZED_HOURS    = 252 * 6.5
BAR_MINUTES         = 5
SEED                = None

# Regime sigma multipliers
REGIME_SIGMA_MULT = {
    "pinning": 0.60, "mean_reversion": 0.75, "vol_compression": 0.70,
    "trend_continuation": 1.00, "breakout": 1.30, "acceleration": 1.35,
    "vol_expansion": 1.40, "reversal_prone": 1.20, "unknown": 1.00,
}

# Regime drift damping
REGIME_DRIFT_MULT = {
    "pinning": 0.20, "mean_reversion": 0.30, "vol_compression": 0.40,
    "trend_continuation": 1.00, "breakout": 0.80, "acceleration": 0.90,
    "vol_expansion": 0.70, "reversal_prone": 0.40, "unknown": 0.50,
}

# Shock: (probability_per_step, magnitude_in_atr_units)
SHOCK_CONFIG = {
    "breakout": (0.05, 1.5), "acceleration": (0.06, 1.8),
    "vol_expansion": (0.07, 2.0), "reversal_prone": (0.04, 1.5),
}

VOL_OF_VOL = 0.08


@dataclass
class MonteCarloOutput:
    """Structured output from Monte Carlo simulation."""
    available:          bool
    simulation_ok:      bool  = False
    n_paths:            int   = 0
    horizon_bars:       int   = 0
    upper_25:           Optional[float] = None
    upper_50:           Optional[float] = None
    upper_75:           Optional[float] = None
    median_path:        Optional[float] = None
    lower_25:           Optional[float] = None
    lower_50:           Optional[float] = None
    lower_75:           Optional[float] = None
    expected_favorable_excursion:  Optional[float] = None
    expected_adverse_excursion:    Optional[float] = None
    prob_touch_upper_wall:  Optional[float] = None
    prob_touch_lower_wall:  Optional[float] = None
    prob_exceed_em_upper:   Optional[float] = None
    prob_exceed_em_lower:   Optional[float] = None
    containment_prob:   Optional[float] = None
    expansion_prob:     Optional[float] = None
    path_dispersion:    Optional[float] = None
    # Path-level features for post-fusion context only (not class probabilities)
    expected_move:       Optional[float] = None
    volatility:          Optional[float] = None
    skew:                Optional[float] = None
    tail_risk:           Optional[float] = None
    directional_bias:    Optional[float] = None
    fallback_used:      bool  = True
    model_version:      str   = "mc_v3_garch"
    assumptions:        dict  = field(default_factory=dict)

    def mc_feature_dict(self) -> dict[str, float | str]:
        """Contract for fusion adjustment: path features present on this run only (no fabricated zeros)."""
        out: dict[str, float | str] = {"source": "derived_mc_normalized"}
        for key, val in (
            ("expected_move", self.expected_move),
            ("volatility", self.volatility),
            ("skew", self.skew),
            ("tail_risk", self.tail_risk),
            ("directional_bias", self.directional_bias),
        ):
            if val is not None:
                try:
                    out[key] = float(val)
                except (TypeError, ValueError):
                    pass
        return out


def _blend_sigma(iv, realized_vol, atr, spot):
    """Blend realized vol + IV + ATR into a single base sigma.
    Weights per consultant recommendation: 50% RV + 30% IV + 20% ATR-scaled.
    Falls back gracefully when components are missing."""
    bars_per_year = 252 * 78
    atr_vol = None
    if atr is not None and atr > 0 and spot > 0:
        atr_vol = (atr / spot) * math.sqrt(bars_per_year)

    rv = realized_vol if (realized_vol is not None and realized_vol > 0) else None

    # Full blend: 50% RV + 30% IV + 20% ATR
    if rv is not None and atr_vol is not None:
        base = 0.50 * rv + 0.30 * iv + 0.20 * atr_vol
    elif rv is not None:
        base = 0.55 * rv + 0.45 * iv
    elif atr_vol is not None:
        base = 0.60 * iv + 0.40 * atr_vol
    else:
        base = iv  # IV-only fallback

    return max(0.01, base)


def _compute_drift(regime, model_prob_up, model_prob_down, model_confidence, fusion_dominant, sigma_bar):
    """State-aware per-bar drift: model-derived, confidence-scaled, regime-damped."""
    raw_drift = 0.0
    if model_prob_up is not None and model_prob_down is not None:
        net = model_prob_up - model_prob_down
        raw_drift = net * sigma_bar * 0.3

    conf_scale = {"high": 1.0, "medium": 0.60, "low": 0.20}.get(model_confidence or "", 0.10)

    if fusion_dominant and raw_drift != 0:
        if (raw_drift > 0 and fusion_dominant in ("reversal", "mean_reversion")) or \
           (raw_drift < 0 and fusion_dominant in ("continuation", "breakout")):
            conf_scale *= 0.50

    regime_mult = REGIME_DRIFT_MULT.get(regime, 0.50)
    return raw_drift * conf_scale * regime_mult


def simulate(
    spot: float,
    iv: float,
    *,
    horizon_bars: int = DEFAULT_HORIZON,
    n_paths: int = DEFAULT_N_PATHS,
    drift: float = 0.0,
    call_gamma_wall: Optional[float] = None,
    put_gamma_wall: Optional[float] = None,
    em_upper: Optional[float] = None,
    em_lower: Optional[float] = None,
    direction_threshold_pct: float = 0.0005,
    seed: Optional[int] = SEED,
    # v2 inputs
    regime: Optional[str] = None,
    regime_confidence: Optional[str] = None,
    realized_vol: Optional[float] = None,
    atr: Optional[float] = None,
    model_prob_up: Optional[float] = None,
    model_prob_down: Optional[float] = None,
    model_confidence: Optional[str] = None,
    fusion_dominant: Optional[str] = None,
    # v3 GARCH input
    garch_sigma_bars: Optional[list] = None,  # per-bar sigma forecast from GARCH+blend
) -> MonteCarloOutput:
    """
    Run regime-aware stochastic-volatility Monte Carlo simulation.

    v2: sigma blended + regime-scaled + stochastic per-step,
    drift model-derived + confidence-scaled + regime-damped,
    shock term for breakout/expansion regimes.
    v3: accepts GARCH per-bar sigma forecast. When provided, each MC step
    uses the GARCH-forecasted sigma for THAT bar (capturing vol clustering)
    instead of a flat constant. Regime multiplier + stochastic vol still applied.
    Output contract unchanged from v1.
    """
    if spot is None or spot <= 0:
        return _fallback("invalid spot price")
    if iv is None or iv <= 0:
        return _fallback("invalid IV")

    try:
        rng = np.random.default_rng(seed)

        # Regime multiplier (applied to ALL sigma sources); missing regime → baseline 1.0 (not "unknown")
        if regime:
            r_mult = REGIME_SIGMA_MULT.get(regime, 1.0)
        else:
            r_mult = 1.0
        if regime_confidence == "high":
            eff_mult = r_mult
        elif regime_confidence == "medium":
            eff_mult = 0.5 * r_mult + 0.5
        elif regime_confidence == "low":
            eff_mult = 0.25 * r_mult + 0.75
        else:
            eff_mult = r_mult

        # Determine sigma source: GARCH per-bar or flat blend
        use_garch = (garch_sigma_bars is not None and
                     len(garch_sigma_bars) >= horizon_bars)

        if use_garch:
            # GARCH provides pre-blended per-bar sigma (already includes IV+RV blend + floor)
            # Apply regime multiplier on top
            base_sigma_bars = [s * eff_mult for s in garch_sigma_bars[:horizon_bars]]
            # For reporting, use the average
            base_sigma = sum(garch_sigma_bars[:horizon_bars]) / horizon_bars
            scaled_sigma = base_sigma * eff_mult
            sigma_bar = sum(base_sigma_bars) / len(base_sigma_bars)  # avg for drift calc
        else:
            # Fallback: flat blend (v2 behavior)
            base_sigma = _blend_sigma(iv, realized_vol, atr, spot)
            scaled_sigma = base_sigma * eff_mult

            minutes_per_year = ANNUALIZED_HOURS * 60
            dt = BAR_MINUTES / minutes_per_year
            sigma_bar = scaled_sigma * math.sqrt(dt)
            base_sigma_bars = [sigma_bar] * horizon_bars  # flat

        # dt needed for drift and stochastic vol calculations
        minutes_per_year = ANNUALIZED_HOURS * 60
        dt = BAR_MINUTES / minutes_per_year

        # 4. State-aware drift (uses average sigma for scaling)
        avg_sigma_bar = sum(base_sigma_bars) / len(base_sigma_bars)
        per_bar_drift = _compute_drift(
            regime, model_prob_up, model_prob_down,
            model_confidence, fusion_dominant, avg_sigma_bar,
        )

        # 5. Shock config
        shock_cfg = SHOCK_CONFIG.get(regime)
        shock_prob = shock_cfg[0] if shock_cfg else 0.0
        shock_atr_mult = shock_cfg[1] if shock_cfg else 0.0
        shock_size = 0.0
        if shock_prob > 0 and atr is not None and atr > 0 and spot > 0:
            shock_size = (atr * shock_atr_mult) / spot

        # 6. Generate paths step-by-step (vectorized across paths, loop over time)
        prices = np.full((n_paths, horizon_bars + 1), float(spot))
        # Initialize per-path sigma from the FIRST bar's forecast
        sigmas = np.full(n_paths, float(base_sigma_bars[0]))

        for t in range(horizon_bars):
            # 6a. Reset sigma center to GARCH forecast for this bar
            # Then apply stochastic vol perturbation around it
            target_sigma = base_sigma_bars[t]
            vol_shocks = rng.standard_normal(n_paths)
            sigmas = float(target_sigma) * np.exp(VOL_OF_VOL * vol_shocks * math.sqrt(dt))
            sigmas = np.clip(sigmas, target_sigma * 0.10, target_sigma * 3.0)

            # 6b. GBM step
            Z = rng.standard_normal(n_paths)
            log_ret = (per_bar_drift - 0.5 * sigmas**2) * dt + sigmas * Z

            # 6c. Shock injection
            if shock_prob > 0 and shock_size > 0:
                shock_mask = rng.random(n_paths) < shock_prob
                if model_prob_up is not None and model_prob_down is not None:
                    net_dir = model_prob_up - model_prob_down
                    dir_prob = 0.5 + 0.3 * np.clip(net_dir, -1, 1)
                    shock_signs = np.where(rng.random(n_paths) < dir_prob, 1.0, -1.0)
                else:
                    shock_signs = np.where(rng.random(n_paths) < 0.5, 1.0, -1.0)
                shock_mag = shock_size * (0.5 + rng.random(n_paths))
                log_ret += shock_mask * shock_signs * shock_mag

            # 6d. Apply
            prices[:, t + 1] = prices[:, t] * np.exp(log_ret)

        paths = prices[:, 1:]
        terminals = paths[:, -1]

        # Range bands
        pcts = np.percentile(terminals, [6.25, 12.5, 25, 50, 75, 87.5, 93.75])
        lower_75, lower_50, lower_25, median, upper_25, upper_50, upper_75 = pcts

        # Excursions
        max_highs = np.max(paths, axis=1)
        max_lows  = np.min(paths, axis=1)
        efe = float(np.mean(max_highs - spot))
        eae = float(np.mean(spot - max_lows))

        # Touch probs
        prob_touch_upper = None
        prob_touch_lower = None
        if call_gamma_wall is not None and call_gamma_wall > spot:
            prob_touch_upper = float(np.mean(np.any(paths >= call_gamma_wall, axis=1)))
        if put_gamma_wall is not None and put_gamma_wall < spot:
            prob_touch_lower = float(np.mean(np.any(paths <= put_gamma_wall, axis=1)))

        # EM exceedance (prob_exceed uses full-session EM)
        prob_exceed_up = prob_exceed_down = None
        if em_upper is not None and em_lower is not None:
            exceed_up   = np.any(paths >= em_upper, axis=1)
            exceed_down = np.any(paths <= em_lower, axis=1)
            prob_exceed_up   = float(np.mean(exceed_up))
            prob_exceed_down = float(np.mean(exceed_down))

        # FIX: MC containment uses sigma-consistent band (self-consistent with MC paths)
        containment = expansion = None
        if spot > 0:
            try:
                mc_implied_half = avg_sigma_bar * math.sqrt(horizon_bars) * spot  # FIX: MC containment uses sigma-consistent band
                em_upper_mc = spot + mc_implied_half
                em_lower_mc = spot - mc_implied_half
                exceed_up_mc   = np.any(paths >= em_upper_mc, axis=1)
                exceed_down_mc = np.any(paths <= em_lower_mc, axis=1)
                containment = float(np.mean(~(exceed_up_mc | exceed_down_mc)))
                expansion = 1.0 - containment
                log.debug(
                    "MC_DEBUG em_upper=%.4f em_lower=%.4f spot=%.4f "
                    "mc_implied_half=%.4f em_upper_mc=%.4f em_lower_mc=%.4f "
                    "containment=%.4f expansion=%.4f",
                    em_upper or 0.0, em_lower or 0.0, spot,
                    mc_implied_half, em_upper_mc, em_lower_mc,
                    containment, expansion
                )
            except (TypeError, ValueError, ZeroDivisionError) as ex:
                log.warning("MC_CONTAINMENT_ERROR: %s", ex)

        dispersion = float(np.std(terminals))
        mean_t = float(np.mean(terminals))
        std_t = float(dispersion) if dispersion > 1e-12 else 1e-12
        skew = float(np.mean(((terminals - mean_t) / std_t) ** 3))
        expected_move = float(np.mean(np.abs(terminals - float(spot))))
        volatility = dispersion
        if prob_exceed_up is not None and prob_exceed_down is not None:
            tail_risk = float(max(prob_exceed_up, prob_exceed_down))
        elif prob_touch_upper is not None or prob_touch_lower is not None:
            _tail_parts = [p for p in (prob_touch_upper, prob_touch_lower) if p is not None]
            tail_risk = float(max(_tail_parts)) if _tail_parts else None
        else:
            p95 = float(np.percentile(terminals, 95))
            p5 = float(np.percentile(terminals, 5))
            span = (p95 - p5) / float(spot) if spot > 0 else 0.0
            tail_risk = float(min(1.0, max(0.0, span / 0.12)))
        dir_bias = float(np.clip((float(median) - float(spot)) / float(spot), -0.05, 0.05)) if spot > 0 else 0.0

        return MonteCarloOutput(
            available=True, simulation_ok=True,
            n_paths=n_paths, horizon_bars=horizon_bars,
            upper_25=round(upper_25, 2), upper_50=round(upper_50, 2), upper_75=round(upper_75, 2),
            median_path=round(median, 2),
            lower_25=round(lower_25, 2), lower_50=round(lower_50, 2), lower_75=round(lower_75, 2),
            expected_favorable_excursion=round(efe, 4),
            expected_adverse_excursion=round(eae, 4),
            prob_touch_upper_wall=round(prob_touch_upper, 3) if prob_touch_upper is not None else None,
            prob_touch_lower_wall=round(prob_touch_lower, 3) if prob_touch_lower is not None else None,
            prob_exceed_em_upper=round(prob_exceed_up, 3) if prob_exceed_up is not None else None,
            prob_exceed_em_lower=round(prob_exceed_down, 3) if prob_exceed_down is not None else None,
            containment_prob=round(containment, 3) if containment is not None else None,
            expansion_prob=round(expansion, 3) if expansion is not None else None,
            path_dispersion=round(dispersion, 4),
            expected_move=round(expected_move, 6),
            volatility=round(volatility, 6),
            skew=round(skew, 6),
            tail_risk=round(tail_risk, 6) if tail_risk is not None else None,
            directional_bias=round(dir_bias, 8),
            fallback_used=False, model_version="mc_v3_garch",
            assumptions={
                "base_iv": round(iv, 4), "blended_sigma": round(base_sigma, 4),
                "regime": regime,
                "regime_confidence": regime_confidence,
                "regime_sigma_mult": round(eff_mult, 2),
                "scaled_sigma": round(scaled_sigma, 4),
                "sigma_bar_avg": round(avg_sigma_bar, 6),
                "per_bar_drift": round(per_bar_drift, 8),
                "garch_active": use_garch,
                "shock_enabled": shock_prob > 0, "shock_prob": shock_prob,
                "vol_of_vol": VOL_OF_VOL, "horizon_bars": horizon_bars, "n_paths": n_paths,
            },
        )

    except Exception as e:
        log.warning("monte_carlo: simulation failed: %s", e)
        return _fallback(f"simulation error: {e}")


def _fallback(reason: str) -> MonteCarloOutput:
    """Return safe fallback when simulation can't run."""
    log.debug("monte_carlo fallback: %s", reason)
    return MonteCarloOutput(available=False, fallback_used=True, model_version=f"fallback ({reason})")


if __name__ == "__main__":
    print("monte_carlo.py v2 — self-test\n")
    tests = [
        ("PINNING", {"regime": "pinning", "regime_confidence": "high"}),
        ("BREAKOUT", {"regime": "breakout", "regime_confidence": "high"}),
        ("BASELINE", {"regime": "unknown"}),
        ("BREAKOUT+MODEL UP", {"regime": "breakout", "regime_confidence": "high",
            "model_prob_up": 0.65, "model_prob_down": 0.15, "model_confidence": "high"}),
    ]
    for label, kw in tests:
        r = simulate(spot=570.0, iv=0.18, horizon_bars=13, n_paths=5000,
                     call_gamma_wall=575.0, put_gamma_wall=565.0,
                     em_upper=573.0, em_lower=567.0,
                     realized_vol=0.15, atr=0.8, seed=42, **kw)
        print(f"  {label}: disp={r.path_dispersion:.2f} EFE={r.expected_favorable_excursion:.2f} "
              f"EAE={r.expected_adverse_excursion:.2f} cont={r.containment_prob:.1%} "
              f"shock={r.assumptions.get('shock_enabled')} drift={r.assumptions.get('per_bar_drift',0):.6f}")

    r_pin = simulate(spot=570.0, iv=0.18, regime="pinning", regime_confidence="high",
                     realized_vol=0.15, atr=0.8, seed=42, n_paths=5000,
                     call_gamma_wall=575.0, put_gamma_wall=565.0,
                     em_upper=573.0, em_lower=567.0)
    r_brk = simulate(spot=570.0, iv=0.18, regime="breakout", regime_confidence="high",
                     realized_vol=0.15, atr=0.8, seed=42, n_paths=5000,
                     call_gamma_wall=575.0, put_gamma_wall=565.0,
                     em_upper=573.0, em_lower=567.0)
    assert r_pin.path_dispersion < r_brk.path_dispersion, "pinning < breakout dispersion"
    assert r_pin.containment_prob > r_brk.containment_prob, "pinning > breakout containment"
    print("\n  ✅ Regime differences verified. PASS")
