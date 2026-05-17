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

from features.regime_mvp_context import mvp_spot, require_mvp_features, RegimeMvpInputError
from signal_types import SignalInput

log = logging.getLogger(__name__)

# Regime states
VOL_COMPRESSION = "compression"
VOL_EXPANSION   = "expansion"
VOL_UNSTABLE    = "unstable"
VOL_UNKNOWN     = "unknown"


@dataclass
class VolRegimePayload:
    """
    Policy outputs from volatility regime. Used by The Call and position sizing
    to modify trade interpretation, conviction, and risk.
    """
    vol_regime:            str   # "compression" | "expansion" | "unstable" | "unknown"
    breakout_bias:         float # 0.0-1.0: favor breakouts in expansion
    continuation_bias:     float # 0.0-1.0: favor continuation in expansion
    reversal_bias:         float # 0.0-1.0: favor reversals/range in compression
    conviction_multiplier: float # 0.0-1.5: multiply base conviction
    risk_multiplier:       float # 0.8-1.5: scale stop distance, sizing
    trade_permissive:      bool  # allow new trades vs require stricter confirmation
    summary:               str  # human-readable policy note


def classify_volatility_regime(
    inp: SignalInput,
    *,
    mvp_features: dict[str, Any],
) -> VolRegimePayload:
    """
    Classify volatility regime from market data. Runs immediately after
    SignalInput is built, before market regime and ML stack.

    Uses: realized_vol, atr, garch_sigma_bars, iv_level, iv_direction,
          vix_level, vix_vs_prev. No new data sources.

    ``mvp_features`` (InferenceSnapshotV1 canonical row) is **required**; ATR%-of-spot uses
    canonical ``price.spot`` only (no SignalInput spot).
    """
    mvp = require_mvp_features(mvp_features, context="classify_volatility_regime")
    spot = mvp_spot(mvp)
    if spot is None or spot <= 0:
        raise RegimeMvpInputError(
            "classify_volatility_regime requires canonical price.spot > 0 in mvp_features"
        )

    rv   = _f(inp.realized_vol)
    atr  = _f(inp.atr)
    iv   = _f(inp.iv_level)
    vix  = _f(inp.vix_level)
    vix_chg = _f(inp.vix_vs_prev)
    iv_dir  = (inp.iv_direction or "").strip().lower()
    garch  = inp.garch_sigma_bars

    # Normalize IV: often stored as 0.18 or 18
    if iv is not None and iv > 5.0:
        iv = iv / 100.0
    if rv is not None and rv > 5.0:
        rv = rv / 100.0

    # GARCH trend: rising vs falling sigma
    garch_rising = False
    garch_falling = False
    if garch and len(garch) >= 3:
        def _safe_floats(lst):
            out = []
            for x in lst:
                try:
                    if x is not None:
                        out.append(float(x))
                except (TypeError, ValueError):
                    pass
            return out
        first_half = _safe_floats(garch[: len(garch) // 2])
        second_half = _safe_floats(garch[len(garch) // 2 :])
        if first_half and second_half:
            avg_first = sum(first_half) / len(first_half)
            avg_second = sum(second_half) / len(second_half)
            if avg_second > avg_first * 1.05:
                garch_rising = True
            elif avg_second < avg_first * 0.95:
                garch_falling = True

    # ATR relative to spot (rough vol proxy)
    atr_pct = (atr / spot * 100) if (atr and spot) else None

    # ── Unstable: high VIX + rapid change or conflicting signals ────────────
    if vix is not None and vix > 28:
        # Extreme VIX → unstable
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
    if vix_chg is not None and abs(vix_chg) > 3.0 and vix is not None and vix > 20:
        # VIX jumping quickly
        return VolRegimePayload(
            vol_regime=VOL_UNSTABLE,
            breakout_bias=0.5,
            continuation_bias=0.35,
            reversal_bias=0.45,
            conviction_multiplier=0.75,
            risk_multiplier=1.25,
            trade_permissive=True,  # allow but reduced
            summary="VIX rising fast — volatile shift; reduce size, require agreement.",
        )
    if iv_dir == "expanding" and garch_falling and rv is not None and iv is not None and rv < iv * 0.7:
        # Conflicting: IV expanding but realized low, GARCH falling
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

    # ── Compression: low vol, IV contracting, range-bound ────────────────────
    compression_score = 0
    if iv_dir == "contracting":
        compression_score += 2
    if garch_falling:
        compression_score += 1
    if atr_pct is not None and atr_pct < 0.15:
        compression_score += 1
    if rv is not None and iv is not None and rv < iv * 0.85:
        compression_score += 1
    if vix is not None and vix < 16:
        compression_score += 1

    if compression_score >= 3:
        return VolRegimePayload(
            vol_regime=VOL_COMPRESSION,
            breakout_bias=0.35,   # require stronger breakout confirmation
            continuation_bias=0.4,
            reversal_bias=0.75,   # allow range/fade trades
            conviction_multiplier=0.9,
            risk_multiplier=1.0,
            trade_permissive=True,
            summary="Vol compression — favor range trades; breakout needs stronger confirmation.",
        )

    # ── Expansion: vol rising, IV expanding, trending environment ─────────────
    expansion_score = 0
    if iv_dir == "expanding":
        expansion_score += 2
    if garch_rising:
        expansion_score += 1
    if atr_pct is not None and atr_pct > 0.25:
        expansion_score += 1
    if rv is not None and iv is not None and rv >= iv * 0.95:
        expansion_score += 1
    if vix is not None and 18 <= vix <= 26:
        expansion_score += 1

    if expansion_score >= 3:
        return VolRegimePayload(
            vol_regime=VOL_EXPANSION,
            breakout_bias=0.85,   # allow breakouts, lower threshold
            continuation_bias=0.8,
            reversal_bias=0.3,
            conviction_multiplier=1.0,
            risk_multiplier=1.12,  # slightly wider stops
            trade_permissive=True,
            summary="Vol expansion — allow continuation trades; reduced breakout threshold.",
        )

    # ── Default: insufficient signal — fail-closed (not permissive neutral policy) ─
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


def _f(v) -> Optional[float]:
    """Safe float extraction."""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
