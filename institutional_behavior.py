"""Descriptive range × signed-imbalance stall/push proxy (RC-455).

This is NOT microstructure absorption (no tape, no L2 replenish, no
limit-vs-market classification). The historical name ``absorption_score``
is retired. Surviving scores are unitless [0, 1] products of:

- candle body/range ratio (0 = doji, 1 = full-range body)
- clipped |flow_imbalance|

No gamma nudge, no retired order_flow_score mix-in, no magic imbalance
divisors, no log-volume term inside the score. Volume is emitted as a
separate ``volume_log1p`` field when present.

SEMANTIC_ERA ``range_imbalance_v1`` starts 2026-08-22. Historical
``absorption_score`` / ``continuation_score`` rows are a different
formula and must not train as this field.
"""
from __future__ import annotations

import math
from typing import Any

RANGE_IMBALANCE_SEMANTIC_ERA = "range_imbalance_v1"
LEGACY_ABSORPTION_SEMANTIC_ERA = "ohlcv_imbalance_absorption_v0_quarantined"

_EPS = 1e-12


def _f(v: Any) -> float | None:
    try:
        if v is None:
            return None
        out = float(v)
    except (TypeError, ValueError):
        return None
    if out != out:  # NaN
        return None
    return out


def _clip01(v: float) -> float:
    return 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)


def compute_liquidity_behavior_row(
    *,
    high: Any = None,
    low: Any = None,
    open_: Any = None,
    close: Any = None,
    volume: Any = None,
    flow_imbalance: Any = None,
    order_flow_score: Any = None,  # unused; retired composite (RC-454)
    net_gamma: Any = None,  # unused; not a stall/push input
    # Live call-site aliases (server.py). Ignored extras never mix into the score.
    candle_high: Any = None,
    candle_low: Any = None,
    candle_open: Any = None,
    candle_close: Any = None,
    candle_volume: Any = None,
    spot: Any = None,
    atr: Any = None,
    candle_range_pts: Any = None,
    candle_body_pts: Any = None,
) -> dict[str, Any]:
    """Return one range×imbalance stall/push observation.

    Unused kwargs are accepted so existing call sites do not fabricate
    values; they are ignored (fail-closed: no silent mix-in).
    """
    _ = order_flow_score, net_gamma, spot, atr, candle_range_pts, candle_body_pts
    hi = _f(high if high is not None else candle_high)
    lo = _f(low if low is not None else candle_low)
    op = _f(open_ if open_ is not None else candle_open)
    cl = _f(close if close is not None else candle_close)
    vol = _f(volume if volume is not None else candle_volume)
    imb = _f(flow_imbalance)

    if hi is None or lo is None or op is None or cl is None:
        return {
            "range_imbalance_stall_score": None,
            "range_imbalance_push_score": None,
            "range_imbalance_label": None,
            "volume_log1p": None if vol is None else float(math.log1p(max(0.0, vol))),
            "flow_imbalance": imb,
            "semantic_era": RANGE_IMBALANCE_SEMANTIC_ERA,
            "absorption_score": None,
            "continuation_score": None,
            "absorption_label": None,
            "behavior_label": None,
            "legacy_absorption_quarantined": True,
            "legacy_absorption_semantic_era": LEGACY_ABSORPTION_SEMANTIC_ERA,
        }

    rng = hi - lo
    body = abs(cl - op)
    body_ratio = 0.0 if rng <= _EPS else _clip01(body / rng)
    imb_mag = 0.0 if imb is None else _clip01(abs(imb))
    stall = _clip01((1.0 - body_ratio) * imb_mag)
    push = _clip01(body_ratio * imb_mag)

    if stall <= 0.0 and push <= 0.0:
        label = "balanced"
    elif stall > push:
        label = "stall_heavy"
    elif push > stall:
        label = "push_heavy"
    else:
        label = "balanced"

    vol_log = None if vol is None else float(math.log1p(max(0.0, vol)))
    return {
        "range_imbalance_stall_score": stall,
        "range_imbalance_push_score": push,
        "range_imbalance_label": label,
        "volume_log1p": vol_log,
        "flow_imbalance": imb,
        "body_ratio": body_ratio,
        "semantic_era": RANGE_IMBALANCE_SEMANTIC_ERA,
        "absorption_score": None,
        "continuation_score": None,
        "absorption_label": None,
        "behavior_label": label,
        "legacy_absorption_quarantined": True,
        "legacy_absorption_semantic_era": LEGACY_ABSORPTION_SEMANTIC_ERA,
    }
