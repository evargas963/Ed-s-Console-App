"""
L1 adaptive materiality engine — regime-aware, dynamically scaled, deterministic.

When AdaptiveMaterialityContext is absent, resolution matches legacy static defaults.
Single entry: resolve_l1_materiality_engine (alias: resolve_l1_adaptive_thresholds).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional
from planes.l1_runtime import L1_SPREAD_FRAC_ABS_EPS, L1_SPOT_REL_EPS
from time_et import ET as _ET

# --- Absolute bounds (guardrails) ---
L1_SPOT_REL_EPS_MIN = 8e-5
L1_SPOT_REL_EPS_MAX = 1.2e-3
L1_SPREAD_FRAC_ABS_EPS_MIN = 3e-5
L1_SPREAD_FRAC_ABS_EPS_MAX = 4.0e-4

# Reference fractional spread for instability ratio (deterministic)
_SPREAD_REF_FRAC = 2.0e-4

_BROAD_ETFS = frozenset({"SPY", "QQQ", "IWM", "DIA", "VOO", "IVV"})
_INDEXISH = frozenset({"SPX", "NDX", "RUT", "VIX", "DJI", "$VIX", "^SPX", "^NDX", "^RUT", "^VIX"})


@dataclass(frozen=True)
class AdaptiveMaterialityContext:
    """
    Optional inputs for adaptive resolution. All fields optional except caller supplies
    what the L1 path can observe without extra I/O tiers.
    """

    session_label: Optional[str] = None
    vix_level: Optional[float] = None
    spot: Optional[float] = None
    spread_frac: Optional[float] = None
    now_ts: Optional[float] = None


@dataclass(frozen=True)
class AdaptiveThresholdResolution:
    spot_rel_eps: float
    spread_frac_abs_eps: float
    mode: str
    instrument_kind: str
    session_bucket: str
    vol_regime: str
    price_tier: str
    spot_effective_multiplier: float
    spread_effective_multiplier: float
    microstructure_spread_add: float
    rules_applied: tuple[str, ...] = field(default_factory=tuple)
    # --- Materiality engine (regime + dynamic scaling + explainability) ---
    materiality_regime: str = "unspecified"
    sensitivity_vs_baseline_spot: str = "unspecified"
    sensitivity_vs_baseline_spread: str = "unspecified"
    vix_spot_factor_smooth: float = 1.0
    vix_spread_factor_smooth: float = 1.0
    session_intraday_ramp: float = 1.0
    spread_instability_mult: float = 1.0
    spread_stress_score: float = 0.0
    baseline_spot_rel_eps: float = field(default_factory=lambda: L1_SPOT_REL_EPS)
    baseline_spread_frac_abs_eps: float = field(default_factory=lambda: L1_SPREAD_FRAC_ABS_EPS)

    def as_dict(self) -> dict[str, Any]:
        return {
            "spot_rel_eps": self.spot_rel_eps,
            "spread_frac_abs_eps": self.spread_frac_abs_eps,
            "mode": self.mode,
            "instrument_kind": self.instrument_kind,
            "session_bucket": self.session_bucket,
            "vol_regime": self.vol_regime,
            "price_tier": self.price_tier,
            "spot_effective_multiplier": round(self.spot_effective_multiplier, 6),
            "spread_effective_multiplier": round(self.spread_effective_multiplier, 6),
            "microstructure_spread_add": round(self.microstructure_spread_add, 10),
            "rules_applied": list(self.rules_applied),
            "materiality_regime": self.materiality_regime,
            "sensitivity_vs_baseline_spot": self.sensitivity_vs_baseline_spot,
            "sensitivity_vs_baseline_spread": self.sensitivity_vs_baseline_spread,
            "vix_spot_factor_smooth": round(self.vix_spot_factor_smooth, 6),
            "vix_spread_factor_smooth": round(self.vix_spread_factor_smooth, 6),
            "session_intraday_ramp": round(self.session_intraday_ramp, 6),
            "spread_instability_mult": round(self.spread_instability_mult, 6),
            "spread_stress_score": round(self.spread_stress_score, 6),
            "baseline_spot_rel_eps": self.baseline_spot_rel_eps,
            "baseline_spread_frac_abs_eps": self.baseline_spread_frac_abs_eps,
        }


def _et_minutes(now_ts: Optional[float]) -> int:
    if now_ts is None:
        dt = datetime.now(_ET)
    else:
        dt = datetime.fromtimestamp(float(now_ts), tz=_ET)
    return dt.hour * 60 + dt.minute


def _session_bucket(session_label: Optional[str], now_ts: Optional[float]) -> str:
    lab = (session_label or "").strip()
    if lab in ("Pre-Market", "After-Hours", "Closed"):
        return "extended_or_closed"
    if lab != "RTH":
        return "unknown_session"
    m = _et_minutes(now_ts)
    if 570 <= m <= 630:
        return "rth_open"
    if 631 <= m <= 870:
        return "rth_midday"
    if 871 <= m <= 959:
        return "rth_close"
    return "rth_other"


def _vol_regime(vix: Optional[float]) -> str:
    """VIX regime label for adaptive materiality — delegates 15/20/30 cuts to math_volatility.vix_tier_token (single authority)."""
    from math_volatility import vix_tier_token

    return vix_tier_token(vix) or "unknown"


def _piecewise_linear(x: float, anchors: list[tuple[float, float]]) -> float:
    """Linear interpolation through (xi, yi); clamp beyond ends."""
    if not anchors:
        return 1.0
    if x <= anchors[0][0]:
        return anchors[0][1]
    if x >= anchors[-1][0]:
        return anchors[-1][1]
    for i in range(len(anchors) - 1):
        x0, y0 = anchors[i]
        x1, y1 = anchors[i + 1]
        if x0 <= x <= x1:
            if x1 == x0:
                return y0
            t = (x - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)
    return anchors[-1][1]


def _vix_smooth_factors(vix: Optional[float]) -> tuple[float, float, str]:
    """
    Continuous VIX→multiplier mapping (reduces discrete jumps at regime boundaries).
    Returns (spot_factor, spread_factor, coarse_label).
    """
    if vix is None or vix <= 0 or math.isnan(vix):
        return 1.0, 1.0, "unknown"
    vx = float(vix)
    spot_anchors = [
        (10.0, 0.86),
        (14.0, 0.90),
        (18.0, 0.96),
        (22.0, 1.02),
        (28.0, 1.12),
        (36.0, 1.24),
        (48.0, 1.34),
    ]
    spr_anchors = [
        (10.0, 0.92),
        (14.0, 0.96),
        (18.0, 1.0),
        (22.0, 1.06),
        (28.0, 1.16),
        (36.0, 1.30),
        (48.0, 1.40),
    ]
    sf = _piecewise_linear(vx, spot_anchors)
    spf = _piecewise_linear(vx, spr_anchors)
    label = _vol_regime(vix)
    return sf, spf, label


def _session_base_spot_mult(bucket: str) -> float:
    return {
        "extended_or_closed": 1.38,
        "rth_open": 1.08,
        "rth_midday": 0.98,
        "rth_close": 1.08,
        "rth_other": 1.0,
        "unknown_session": 1.0,
    }.get(bucket, 1.0)


def _session_base_spread_mult(bucket: str) -> float:
    return {
        "extended_or_closed": 1.65,
        "rth_open": 1.12,
        "rth_midday": 0.96,
        "rth_close": 1.12,
        "rth_other": 1.0,
        "unknown_session": 1.0,
    }.get(bucket, 1.0)


def _session_intraday_ramp(session_bucket: str, et_minutes: int) -> tuple[float, str]:
    """
    Smooth ramp at RTH open (first ~20m) and close (last ~20m) to avoid step jumps
    at bucket boundaries. Returns (multiplier applied on top of base session spot mult, note).
    """
    if session_bucket == "rth_open":
        # 9:30–9:50 ET: ramp 1.0 → ~1.04 extra sensitivity to volatility
        if 570 <= et_minutes <= 590:
            u = (et_minutes - 570) / 20.0
            ramp = 1.0 + 0.04 * min(1.0, max(0.0, u))
            return ramp, "rth_open_ramp_first_20m"
        return 1.04, "rth_open_post_ramp"
    if session_bucket == "rth_close":
        # 3:00–3:20 PM: ramp
        if 900 <= et_minutes <= 920:
            u = (et_minutes - 900) / 20.0
            ramp = 1.0 + 0.05 * min(1.0, max(0.0, u))
            return ramp, "rth_close_ramp_last_window"
        if 921 <= et_minutes <= 959:
            return 1.05, "rth_close_steady"
        return 1.0, "rth_close_edge"
    return 1.0, "no_intraday_ramp"


def _spread_instability(spread_frac: Optional[float]) -> tuple[float, float, float]:
    """
    Returns (multiplicative factor for spread eps chain, stress score 0..~3, micro add).
    """
    if spread_frac is None or spread_frac <= 0:
        return 1.0, 0.0, 0.0
    sf = float(spread_frac)
    ratio = sf / max(_SPREAD_REF_FRAC, 1e-12)
    stress = max(0.0, min(3.0, ratio - 1.0))
    # Bounded multiplicative widening — degrading microstructure → less churn on tiny spread jitter
    mult = 1.0 + 0.12 * stress
    mult = min(1.45, mult)
    excess = max(0.0, sf - 4.0e-4)
    micro = min(2.5e-4, excess * 0.22)
    return mult, stress, micro


def _materiality_regime_label(vol_regime: str, session_bucket: str, stress: float) -> str:
    if session_bucket == "extended_or_closed":
        return "extended_hours"
    if stress >= 1.5:
        return "microstructure_stress"
    if vol_regime == "high":
        return "high_volatility_rth"
    if vol_regime == "elevated":
        return "elevated_volatility_rth"
    if vol_regime == "low":
        return "calm_rth"
    if session_bucket in ("rth_open", "rth_close"):
        return f"session_tail_{session_bucket}"
    if session_bucket == "rth_midday":
        return "midday_rth"
    return "normal_rth"


def _sensitivity_label(eps: float, baseline: float) -> str:
    if baseline <= 0:
        return "unknown"
    r = eps / baseline
    if r > 1.03:
        return "less_sensitive_than_baseline"
    if r < 0.97:
        return "more_sensitive_than_baseline"
    return "similar_to_baseline"


def _instrument_kind(ticker: str) -> str:
    t = (ticker or "").upper().strip()
    if t in _BROAD_ETFS:
        return "broad_etf"
    if t in _INDEXISH or t.startswith("^"):
        return "index_proxy"
    return "equity_general"


def _price_tier(spot: Optional[float]) -> str:
    if spot is None or spot <= 0:
        return "unknown"
    if spot < 10.0:
        return "penny_small"
    if spot < 100.0:
        return "mid_price"
    return "large_price"


def _spot_price_multiplier(tier: str) -> float:
    return {"penny_small": 1.75, "mid_price": 1.12, "large_price": 1.0, "unknown": 1.0}.get(tier, 1.0)


def _instrument_spot_multiplier(kind: str) -> float:
    return {"broad_etf": 0.92, "index_proxy": 1.05, "equity_general": 1.0}.get(kind, 1.0)


def resolve_l1_materiality_engine(
    ticker: str,
    *,
    context: Optional[AdaptiveMaterialityContext] = None,
) -> AdaptiveThresholdResolution:
    """
    Full adaptive materiality: regime labels, smooth VIX scaling, session ramps,
    spread instability, bounded eps. Single resolver for L1 materiality.
    """
    tkr = (ticker or "").upper().strip() or "SPY"
    if context is None:
        return AdaptiveThresholdResolution(
            spot_rel_eps=L1_SPOT_REL_EPS,
            spread_frac_abs_eps=L1_SPREAD_FRAC_ABS_EPS,
            mode="static_defaults",
            instrument_kind=_instrument_kind(tkr),
            session_bucket="not_evaluated",
            vol_regime="not_evaluated",
            price_tier="not_evaluated",
            spot_effective_multiplier=1.0,
            spread_effective_multiplier=1.0,
            microstructure_spread_add=0.0,
            rules_applied=("no_context_use_runtime_defaults",),
            materiality_regime="fallback_static",
            sensitivity_vs_baseline_spot="similar_to_baseline",
            sensitivity_vs_baseline_spread="similar_to_baseline",
            baseline_spot_rel_eps=L1_SPOT_REL_EPS,
            baseline_spread_frac_abs_eps=L1_SPREAD_FRAC_ABS_EPS,
        )

    kind = _instrument_kind(tkr)
    pt = _price_tier(context.spot)
    sb = _session_bucket(context.session_label, context.now_ts)
    et_m = _et_minutes(context.now_ts)
    vr = _vol_regime(context.vix_level)
    vx_sf, vx_spf, _vx_label = _vix_smooth_factors(context.vix_level)

    ramp, ramp_note = _session_intraday_ramp(sb, et_m)
    base_ss = _session_base_spot_mult(sb) * ramp
    base_spr = _session_base_spread_mult(sb)

    spr_inst_mult, stress_score, micro_add = _spread_instability(context.spread_frac)

    pm = _spot_price_multiplier(pt)
    im = _instrument_spot_multiplier(kind)

    spot_mult = pm * im * base_ss * vx_sf
    raw_spot = L1_SPOT_REL_EPS * spot_mult
    spot_eps = max(L1_SPOT_REL_EPS_MIN, min(L1_SPOT_REL_EPS_MAX, raw_spot))

    spread_mult_chain = base_spr * vx_spf * spr_inst_mult
    raw_spr = L1_SPREAD_FRAC_ABS_EPS * spread_mult_chain + micro_add
    spr_eps = max(L1_SPREAD_FRAC_ABS_EPS_MIN, min(L1_SPREAD_FRAC_ABS_EPS_MAX, raw_spr))

    mreg = _materiality_regime_label(vr, sb, stress_score)

    rules = (
        "engine=v1",
        f"instrument={kind}",
        f"price_tier={pt}",
        f"session_bucket={sb}",
        f"vol_regime={vr}",
        f"vix_smooth_spot={vx_sf:.5f}",
        f"vix_smooth_spread={vx_spf:.5f}",
        f"session_base_spot={_session_base_spot_mult(sb):.4f}",
        f"session_ramp={ramp:.4f}:{ramp_note}",
        f"spot_chain={pm:.4f}*{im:.4f}*session*{vx_sf:.4f}",
        f"spread_chain={base_spr:.4f}*{vx_spf:.4f}*inst={spr_inst_mult:.4f}",
        f"spread_stress={stress_score:.4f}",
    )

    return AdaptiveThresholdResolution(
        spot_rel_eps=spot_eps,
        spread_frac_abs_eps=spr_eps,
        mode="adaptive_engine",
        instrument_kind=kind,
        session_bucket=sb,
        vol_regime=vr,
        price_tier=pt,
        spot_effective_multiplier=spot_mult,
        spread_effective_multiplier=spread_mult_chain,
        microstructure_spread_add=micro_add,
        rules_applied=rules,
        materiality_regime=mreg,
        sensitivity_vs_baseline_spot=_sensitivity_label(spot_eps, L1_SPOT_REL_EPS),
        sensitivity_vs_baseline_spread=_sensitivity_label(spr_eps, L1_SPREAD_FRAC_ABS_EPS),
        vix_spot_factor_smooth=vx_sf,
        vix_spread_factor_smooth=vx_spf,
        session_intraday_ramp=ramp,
        spread_instability_mult=spr_inst_mult,
        spread_stress_score=stress_score,
        baseline_spot_rel_eps=L1_SPOT_REL_EPS,
        baseline_spread_frac_abs_eps=L1_SPREAD_FRAC_ABS_EPS,
    )


# Backward-compatible alias
resolve_l1_adaptive_thresholds = resolve_l1_materiality_engine


def resolve_spot_rel_eps(ticker: str, *, session_label: Optional[str] = None) -> float:
    _ = (ticker, session_label)
    return L1_SPOT_REL_EPS


def resolve_spread_frac_abs_eps(ticker: str, *, session_label: Optional[str] = None) -> float:
    _ = (ticker, session_label)
    return L1_SPREAD_FRAC_ABS_EPS
