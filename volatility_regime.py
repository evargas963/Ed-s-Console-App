"""
volatility_regime.py
Volatility Regime — STACK ORDER 2. Policy layer, computed immediately after Market Data.

REQUIRED: Must run before Market Regime (3). Influences downstream interpretation
as a policy layer, not just sizing or Monte Carlo input.

Classifies vol state (compression | expansion | unstable | unknown) from existing inputs:
  - realized_vol, garch_sigma_bars, atr
  - iv_level, iv_direction
  - vix_level, vix_vs_prev

Produces policy outputs that govern downstream interpretation:
  - breakout_bias, continuation_bias, reversal_bias
  - conviction_multiplier, risk_multiplier
  - trade_permissive

These values influence The Call (trade permissibility, conviction, risk policy)
and position sizing. Monte Carlo and sizing continue to use raw vol inputs
as before; this layer adds POLICY interpretation.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional
import logging

from features.regime_mvp_context import RegimeMvpInputError, mvp_spot, require_mvp_features
from numeric_contract import float_finite_or_none
from signal_types import SignalInput

log = logging.getLogger(__name__)

# Regime states
VOL_COMPRESSION = "compression"
VOL_EXPANSION = "expansion"
VOL_UNSTABLE = "unstable"
VOL_UNKNOWN = "unknown"

# Canonical Schwab / inference contract: IV and RV as decimals (0.18 = 18%).
VOL_DECIMAL_PERCENT_HEURISTIC = 5.0


@dataclass(frozen=True)
class VolRegimeThresholds:
    """Operator-tunable classification ladder (defaults; cite O-XX when changing)."""

    extreme_vix: float = 28.0
    rapid_vix_change_abs: float = 3.0
    rapid_vix_change_min_level: float = 20.0
    conflicting_signal_rv_iv_ratio: float = 0.70
    compression_atr_pct_max: float = 0.15
    compression_rv_iv_ratio: float = 0.85
    compression_vix_max: float = 16.0
    compression_min_score: int = 3
    expansion_atr_pct_min: float = 0.25
    expansion_rv_iv_ratio: float = 0.95
    expansion_vix_min: float = 18.0
    expansion_vix_max: float = 26.0
    expansion_min_score: int = 3
    garch_trend_threshold_pct: float = 0.05


VOL_REGIME_THRESHOLDS = VolRegimeThresholds()


@dataclass(frozen=True)
class VolRegimePayload:
    """
    Policy outputs from volatility regime. Used by The Call and position sizing
    to modify trade interpretation, conviction, and risk.
    """

    vol_regime: str  # "compression" | "expansion" | "unstable" | "unknown"
    breakout_bias: float  # 0.0-1.0: favor breakouts in expansion
    continuation_bias: float  # 0.0-1.0: favor continuation in expansion
    reversal_bias: float  # 0.0-1.0: favor reversals/range in compression
    conviction_multiplier: float  # 0.0-1.5: multiply base conviction
    risk_multiplier: float  # 0.8-1.5: scale stop distance, sizing
    trade_permissive: bool  # allow new trades vs require stricter confirmation
    summary: str  # human-readable policy note


def _f(v: Any) -> Optional[float]:
    """Safe float extraction (finite-only; NaN/inf → None)."""
    return float_finite_or_none(v)


def _normalize_vol_decimal(
    value: Optional[float],
    *,
    field: str,
    context: str = "classify_volatility_regime",
) -> Optional[float]:
    """Schwab contract is decimal; values > 5.0 may be percentage — log and scale."""
    if value is None or value <= VOL_DECIMAL_PERCENT_HEURISTIC:
        return value
    log.warning(
        "%s: %s=%s exceeds decimal range (>%s); treating as percentage — verify upstream format",
        context,
        field,
        value,
        VOL_DECIMAL_PERCENT_HEURISTIC,
    )
    return value / 100.0


def _safe_floats(lst: list[Any], *, context: str) -> list[float]:
    out: list[float] = []
    skipped = 0
    for x in lst:
        try:
            if x is not None:
                out.append(float(x))
        except (TypeError, ValueError):
            skipped += 1
    if skipped:
        log.warning(
            "%s: skipped %s non-float garch_sigma_bars entries",
            context,
            skipped,
        )
    return out


def _garch_trend(
    garch: list[Any] | None,
    *,
    thresholds: VolRegimeThresholds,
    context: str,
) -> tuple[bool, bool]:
    if not garch or len(garch) < 3:
        return False, False
    mid = len(garch) // 2
    first_half = _safe_floats(garch[:mid], context=context)
    second_half = _safe_floats(garch[mid:], context=context)
    if not first_half or not second_half:
        return False, False
    avg_first = sum(first_half) / len(first_half)
    avg_second = sum(second_half) / len(second_half)
    rising = avg_second > avg_first * (1.0 + thresholds.garch_trend_threshold_pct)
    falling = avg_second < avg_first * (1.0 - thresholds.garch_trend_threshold_pct)
    return rising, falling


def classify_volatility_regime(
    inp: SignalInput,
    *,
    mvp_features: dict[str, Any],
    thresholds: VolRegimeThresholds = VOL_REGIME_THRESHOLDS,
) -> VolRegimePayload:
    """
    Classify volatility regime from market data. Runs immediately after
    SignalInput is built, before market regime and ML stack.

    Uses: realized_vol, atr, garch_sigma_bars, iv_level, iv_direction,
          vix_level, vix_vs_prev. No new data sources.

    ``mvp_features`` (InferenceSnapshotV1 canonical row) is **required**; ATR%-of-spot uses
    canonical ``price.spot`` only (no SignalInput spot).
    """
    ctx = "classify_volatility_regime"
    mvp = require_mvp_features(mvp_features, context=ctx)
    spot = mvp_spot(mvp)
    if spot is None or spot <= 0:
        raise RegimeMvpInputError(
            "classify_volatility_regime requires canonical price.spot > 0 in mvp_features"
        )

    rv = _normalize_vol_decimal(_f(inp.realized_vol), field="realized_vol", context=ctx)
    atr = _f(inp.atr)
    iv = _normalize_vol_decimal(_f(inp.iv_level), field="iv_level", context=ctx)
    vix = _f(inp.vix_level)
    vix_chg = _f(inp.vix_vs_prev)
    iv_dir = inp.iv_direction.strip().lower() if inp.iv_direction else None
    garch = inp.garch_sigma_bars

    garch_rising, garch_falling = _garch_trend(garch, thresholds=thresholds, context=ctx)

    atr_pct = None
    if atr is not None and spot:
        atr_pct = atr / spot * 100.0

    t = thresholds
    if vix is not None and vix > t.extreme_vix:
        return VolRegimePayload(
            vol_regime=VOL_UNSTABLE,
            breakout_bias=0.5,
            continuation_bias=0.3,
            reversal_bias=0.5,
            conviction_multiplier=0.65,
            risk_multiplier=1.35,
            trade_permissive=False,
            summary="High VIX — unstable vol; reduce conviction, require stronger model agreement.",
        )
    if (
        vix_chg is not None
        and abs(vix_chg) > t.rapid_vix_change_abs
        and vix is not None
        and vix > t.rapid_vix_change_min_level
    ):
        return VolRegimePayload(
            vol_regime=VOL_UNSTABLE,
            breakout_bias=0.5,
            continuation_bias=0.35,
            reversal_bias=0.45,
            conviction_multiplier=0.75,
            risk_multiplier=1.25,
            trade_permissive=True,
            summary="VIX rising fast — volatile shift; reduce size, require agreement.",
        )
    if (
        iv_dir == "expanding"
        and garch_falling
        and rv is not None
        and iv is not None
        and rv < iv * t.conflicting_signal_rv_iv_ratio
    ):
        return VolRegimePayload(
            vol_regime=VOL_UNSTABLE,
            breakout_bias=0.55,
            continuation_bias=0.4,
            reversal_bias=0.5,
            conviction_multiplier=0.8,
            risk_multiplier=1.15,
            trade_permissive=True,
            summary="Mixed vol signals — IV up, RV down; cautious interpretation.",
        )

    compression_score = 0
    if iv_dir == "contracting":
        compression_score += 2
    if garch_falling:
        compression_score += 1
    if atr_pct is not None and atr_pct < t.compression_atr_pct_max:
        compression_score += 1
    if rv is not None and iv is not None and rv < iv * t.compression_rv_iv_ratio:
        compression_score += 1
    if vix is not None and vix < t.compression_vix_max:
        compression_score += 1

    if compression_score >= t.compression_min_score:
        return VolRegimePayload(
            vol_regime=VOL_COMPRESSION,
            breakout_bias=0.35,
            continuation_bias=0.4,
            reversal_bias=0.75,
            conviction_multiplier=0.9,
            risk_multiplier=1.0,
            trade_permissive=True,
            summary="Vol compression — favor range trades; breakout needs stronger confirmation.",
        )

    expansion_score = 0
    if iv_dir == "expanding":
        expansion_score += 2
    if garch_rising:
        expansion_score += 1
    if atr_pct is not None and atr_pct > t.expansion_atr_pct_min:
        expansion_score += 1
    if rv is not None and iv is not None and rv >= iv * t.expansion_rv_iv_ratio:
        expansion_score += 1
    if vix is not None and t.expansion_vix_min <= vix <= t.expansion_vix_max:
        expansion_score += 1

    if expansion_score >= t.expansion_min_score:
        return VolRegimePayload(
            vol_regime=VOL_EXPANSION,
            breakout_bias=0.85,
            continuation_bias=0.8,
            reversal_bias=0.3,
            conviction_multiplier=1.0,
            risk_multiplier=1.12,
            trade_permissive=True,
            summary="Vol expansion — allow continuation trades; reduced breakout threshold.",
        )

    return VolRegimePayload(
        vol_regime=VOL_UNKNOWN,
        breakout_bias=0.6,
        continuation_bias=0.6,
        reversal_bias=0.5,
        conviction_multiplier=0.95,
        risk_multiplier=1.05,
        trade_permissive=False,
        summary="Vol regime unclear — inputs insufficient; require stronger confirmation.",
    )
