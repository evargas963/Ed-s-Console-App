"""Candle body_ratio and signed flow_imbalance primitives (RC-460).

The 2026-08-22 stall/push products

    stall = (1 - body_ratio) * abs(flow_imbalance)
    push  = body_ratio * abs(flow_imbalance)

added no information beyond the two primitives, used the absolute value
(so "signed imbalance" was a lie), and named a causal stall/push the
multiplication does not prove. They are retired.

This is NOT microstructure absorption (no tape, no L2 replenish, no
limit-vs-market classification). Historical ``absorption_score`` /
``continuation_score`` and the one-day ``range_imbalance_*`` composites
are quarantined semantic eras and must not train as these fields.

SEMANTIC_ERA ``ohlcv_body_imbalance_primitives_v1`` starts 2026-08-22.
"""
from __future__ import annotations

import math
from typing import Any

BODY_IMBALANCE_SEMANTIC_ERA = "ohlcv_body_imbalance_primitives_v1"
RANGE_IMBALANCE_SEMANTIC_ERA = BODY_IMBALANCE_SEMANTIC_ERA  # retired alias
LEGACY_ABSORPTION_SEMANTIC_ERA = "ohlcv_imbalance_absorption_v0_quarantined"
RANGE_IMBALANCE_COMPOSITE_ERA = "range_imbalance_v1_quarantined"

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
    net_gamma: Any = None,  # unused; not a primitive input
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
    """Return candle body_ratio plus the signed flow_imbalance primitive.

    Stall/push composites are always None. Unused kwargs are accepted so
    existing call sites do not fabricate values; they are ignored.
    """
    _ = order_flow_score, net_gamma, spot, atr, candle_range_pts, candle_body_pts
    hi = _f(high if high is not None else candle_high)
    lo = _f(low if low is not None else candle_low)
    op = _f(open_ if open_ is not None else candle_open)
    cl = _f(close if close is not None else candle_close)
    vol = _f(volume if volume is not None else candle_volume)
    imb = _f(flow_imbalance)

    vol_log = None if vol is None else float(math.log1p(max(0.0, vol)))
    retired = {
        "range_imbalance_stall_score": None,
        "range_imbalance_push_score": None,
        "range_imbalance_label": None,
        "absorption_score": None,
        "continuation_score": None,
        "absorption_label": None,
        "behavior_label": None,
        "legacy_absorption_quarantined": True,
        "legacy_absorption_semantic_era": LEGACY_ABSORPTION_SEMANTIC_ERA,
        "range_imbalance_composite_quarantined": True,
        "range_imbalance_composite_semantic_era": RANGE_IMBALANCE_COMPOSITE_ERA,
        "semantic_era": BODY_IMBALANCE_SEMANTIC_ERA,
        "volume_log1p": vol_log,
        "flow_imbalance": imb,
        "classification": {
            "body_ratio": "DERIVED",
            "flow_imbalance": "PASSTHROUGH",
            "volume_log1p": "DERIVED",
            "range_imbalance_stall_score": "RETIRED",
            "range_imbalance_push_score": "RETIRED",
        },
    }

    if hi is None or lo is None or op is None or cl is None:
        retired["body_ratio"] = None
        return retired

    rng = hi - lo
    body = abs(cl - op)
    body_ratio = 0.0 if rng <= _EPS else _clip01(body / rng)
    retired["body_ratio"] = body_ratio
    return retired
