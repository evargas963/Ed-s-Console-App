"""
Institutional liquidity-behavior layer (proxy-based).

Scores absorption vs continuation from OHLCV + flow imbalance + optional order-flow score.
Non-authoritative: feeds features, UI, and research — does not replace fusion or The Call.
"""
from __future__ import annotations

import math
from typing import Any, Optional


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def compute_liquidity_behavior_row(
    *,
    spot: Optional[float],
    candle_open: Optional[float],
    candle_high: Optional[float],
    candle_low: Optional[float],
    candle_close: Optional[float],
    candle_volume: Optional[float],
    flow_imbalance: Optional[float],
    net_gamma: Optional[float],
    atr: Optional[float],
    candle_range_pts: Optional[float],
    candle_body_pts: Optional[float],
    order_flow_score: Optional[float],
) -> dict[str, Any]:
    """
    Return JSON-safe dict for MarketState.liquidity_behavior and snapshot flattening.

    absorption_score / continuation_score: 0..1 proxies (tape-grade flow not required).
    """
    sp = float(spot) if spot is not None and float(spot) > 0 else None
    hi = float(candle_high) if candle_high is not None else None
    lo = float(candle_low) if candle_low is not None else None
    opn = float(candle_open) if candle_open is not None else None
    cls = float(candle_close) if candle_close is not None else None

    rng = float(candle_range_pts) if candle_range_pts is not None else None
    if rng is None and hi is not None and lo is not None:
        rng = abs(hi - lo)
    body = abs(float(candle_body_pts)) if candle_body_pts is not None else None
    if body is None and opn is not None and cls is not None:
        body = abs(cls - opn)

    imb = float(flow_imbalance) if flow_imbalance is not None else 0.0
    imb_a = abs(imb)

    vol_n = 0.0
    if candle_volume is not None:
        try:
            vol_n = math.log1p(max(0.0, float(candle_volume))) / 18.0
            vol_n = _clip01(vol_n)
        except (TypeError, ValueError):
            vol_n = 0.0

    ofs_n = 0.0
    if order_flow_score is not None:
        try:
            ofs_n = _clip01(float(order_flow_score) / 100.0)
        except (TypeError, ValueError):
            ofs_n = 0.0

    range_pct = (rng / sp) if (rng is not None and sp) else None
    body_ratio = (body / rng) if (body is not None and rng and rng > 1e-12) else None
    br = body_ratio if body_ratio is not None else 0.4

    # Tight range → more weight on absorption-style read when imbalance exists
    tight = 1.15 if (range_pct is not None and range_pct < 0.0012) else 0.85
    wide = min(1.25, (range_pct or 0.0) * 900.0) if range_pct is not None else 0.5

    stall = _clip01((1.0 - br) * tight)
    push = _clip01(br * wide)

    abs_core = _clip01((imb_a / 0.52) * stall * (0.55 + 0.45 * vol_n) * (0.7 + 0.3 * ofs_n))
    cont_core = _clip01((imb_a / 0.48) * push * (0.5 + 0.5 * vol_n) * (0.65 + 0.35 * ofs_n))

    if net_gamma is not None:
        try:
            ng = float(net_gamma)
        except (TypeError, ValueError):
            ng = 0.0
        if ng > 0:
            abs_core = _clip01(abs_core * 1.08)
            cont_core = _clip01(cont_core * 0.92)
        elif ng < 0:
            cont_core = _clip01(cont_core * 1.06)
            abs_core = _clip01(abs_core * 0.94)

    label = "balanced"
    if abs_core >= cont_core + 0.12:
        label = "absorption_heavy"
    elif cont_core >= abs_core + 0.12:
        label = "continuation_heavy"

    gam_hint = "unknown"
    if sp and atr:
        try:
            atr_f = float(atr)
            if atr_f > 0 and rng is not None:
                rel = rng / atr_f
                vol_ctx = "compressed" if rel < 0.55 else "normal" if rel < 1.25 else "expanded"
            else:
                vol_ctx = "unknown"
        except (TypeError, ValueError):
            vol_ctx = "unknown"
    else:
        vol_ctx = "unknown"

    if net_gamma is not None:
        try:
            ng = float(net_gamma)
            gam_hint = "mean_reversion_bias" if ng > 0 else "trend_bias" if ng < 0 else "unknown"
        except (TypeError, ValueError):
            pass

    return {
        "absorption_score": round(abs_core, 4),
        "continuation_score": round(cont_core, 4),
        "behavior_label": label,
        "gamma_regime_hint": gam_hint,
        "imbalance_proxy": round(imb, 4),
        "body_ratio": round(br, 4) if body_ratio is not None else None,
        "range_pct_of_spot": round(range_pct * 100.0, 5) if range_pct is not None else None,
        "volume_activity": round(vol_n, 4),
        "candle_vs_atr": vol_ctx,
    }
