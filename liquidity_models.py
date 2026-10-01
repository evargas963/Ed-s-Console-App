"""
liquidity_models.py — Data models for Liquidity & Value Playbook Engine
========================================================================
The volume profile, and the records of the zones and the value context.
Ticker-agnostic; works for any instrument.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from numeric_contract import schwab_count, schwab_number

#: LP-01 Step 1 (RC-152) — the ONE volume-profile construction.
#: A bar's volume did not trade at one price. It traded ACROSS [low, high], and the profile is
#: the record of where. Both prior implementations dumped a bar's entire volume into a single
#: bin at the typical price (H+L+C)/3, which is not a volume profile at all — it is a
#: typical-price histogram wearing the name. Auction Market Theory / Volume Profile practice
#: distributes the bar's volume across every price the bar traded through; POC is then the price
#: that actually saw the most volume, and the value area is the smallest contiguous band holding
#: `value_area_pct` of it.
#:
#: Uniform distribution across the spanned bins is the standard first-order model (it is what
#: TPO-style and most charting-package volume profiles do without tick-level trade data). We do
#: not have per-trade prints (the Schwab streamer carries no trade prints — see
#: project_console_rebuild_program), so a within-bar shape would be invented, not measured.
#: Uniform is the honest choice: it asserts only what the bar actually tells us — this volume
#: traded somewhere in [low, high].

#: Bound the work a single pathological bar can cause (a wide index bar against a 0.01 tick).
#: When a bar spans more bins than this, its volume is spread across this many evenly-spaced
#: bins covering the SAME range — still distributed, never dumped, and never unbounded.
MAX_BINS_PER_BAR: int = 5000


@dataclass(frozen=True)
class VolumeProfile:
    """Volume by price from bars, each bar's volume spread evenly over its [low, high] in tick
    bins -- a derived distribution, not traded volume at a price (Schwab sends no trade prints)
    -- and the value area read from it. `bins`: ((price, volume), ...) in price order. `bars`:
    the bars given; `bars_without_volume`: those Schwab sent with no volume, which the profile
    cannot place and does not contain."""
    tick_size: float
    bins: tuple
    poc: float
    vah: float
    val: float
    bars: int
    bars_without_volume: int


def volume_profile(
    bars: list,
    value_area_pct: float = 0.70,
    tick_size: float = 0.01,
    ndigits: int = 4,
) -> Optional[VolumeProfile]:
    """The volume profile built by DISTRIBUTING each bar across [low, high], with its POC and
    value area; None when no usable volume exists -- absence reads as absence, never a
    fabricated level.

    Bins are addressed by INTEGER index (round(price / tick_size)) so that binning is exact:
    accumulating float bin prices as dict keys lets 724.9999999 and 725.0 become two bins for
    one price, which silently fragments the profile and can move the POC.
    """
    if not bars or tick_size <= 0:
        return None

    vol_by_idx: dict[int, float] = defaultdict(float)
    no_volume = 0
    for b in bars:
        if not isinstance(b, dict):
            continue
        hi, lo, vol = schwab_number(b.get("high")), schwab_number(b.get("low")), schwab_count(b.get("volume"))
        no_volume += vol is None
        # high < low has no range to spread over (measured 2026-09-27: 0 of 2,166,115 bars)
        if hi is None or lo is None or vol is None or vol == 0 or hi < lo:
            continue
        lo_i = int(round(lo / tick_size))
        hi_i = int(round(hi / tick_size))
        n = hi_i - lo_i + 1
        if n <= 1:
            vol_by_idx[lo_i] += vol            # flat bar: one price, all of it
            continue
        if n <= MAX_BINS_PER_BAR:
            share = vol / n
            for i in range(lo_i, hi_i + 1):
                vol_by_idx[i] += share
        else:
            share = vol / MAX_BINS_PER_BAR
            step = (hi_i - lo_i) / (MAX_BINS_PER_BAR - 1)
            for k in range(MAX_BINS_PER_BAR):
                vol_by_idx[int(round(lo_i + k * step))] += share

    if not vol_by_idx:
        return None
    total_vol = sum(vol_by_idx.values())
    if total_vol <= 0:
        return None

    idx_sorted = sorted(vol_by_idx)
    poc_idx = max(idx_sorted, key=lambda i: (vol_by_idx[i], -i))
    target = total_vol * value_area_pct
    lo_pos = hi_pos = idx_sorted.index(poc_idx)
    acc = vol_by_idx[poc_idx]
    while acc < target and (lo_pos > 0 or hi_pos < len(idx_sorted) - 1):
        v_lo = vol_by_idx[idx_sorted[lo_pos - 1]] if lo_pos > 0 else -1.0
        v_hi = vol_by_idx[idx_sorted[hi_pos + 1]] if hi_pos < len(idx_sorted) - 1 else -1.0
        if v_hi > v_lo and hi_pos < len(idx_sorted) - 1:
            hi_pos += 1
            acc += v_hi
        elif lo_pos > 0:
            lo_pos -= 1
            acc += v_lo
        elif hi_pos < len(idx_sorted) - 1:
            hi_pos += 1
            acc += v_hi
        else:
            break
    return VolumeProfile(
        tick_size=tick_size,
        bins=tuple((round(i * tick_size, ndigits), vol_by_idx[i]) for i in idx_sorted),
        poc=round(poc_idx * tick_size, ndigits),
        vah=round(idx_sorted[hi_pos] * tick_size, ndigits),
        val=round(idx_sorted[lo_pos] * tick_size, ndigits),
        bars=len(bars), bars_without_volume=no_volume)


class ZoneType(str, Enum):
    """What a zone is against the live price: support (below it), resistance (above it), a
    pivot (only value levels, whichever side it is on), or structure (the price is inside it,
    or there is no live price to place it against). No zone is a measured pool of resting
    orders, so none is named as one."""
    SUPPORT_LIQUIDITY = "support_liquidity"
    PIVOT_VALUE = "pivot_value"
    RESISTANCE_LIQUIDITY = "resistance_liquidity"
    STRUCTURE = "structure"


#: each zone type's name on screen and the side of price it is drawn as: support, resistance, or
#: neither (value; none for a zone with no side)
ZONE_DISPLAY: dict[ZoneType, tuple[str, Optional[str]]] = {
    ZoneType.SUPPORT_LIQUIDITY: ("Support", "support"),
    ZoneType.PIVOT_VALUE: ("Pivot / value", "value"),
    ZoneType.RESISTANCE_LIQUIDITY: ("Resistance", "resistance"),
    ZoneType.STRUCTURE: ("Structure", None),
}


@dataclass
class Zone:
    """Clustered zone built from one or more price levels. `confluence_score`: how many
    different levels it holds."""
    zone_type: ZoneType
    zone_low: float
    zone_high: float
    zone_mid: float
    source_levels: list[dict] = field(default_factory=list)   # [{"label": str, "value": float}]
    confluence_score: int = 0


VALUE_SHIFTED_HIGHER, VALUE_SHIFTED_LOWER, VALUE_UNCHANGED = "shifted_higher", "shifted_lower", "unchanged"
VWAP_ABOVE_VALUE, VWAP_BELOW_VALUE, VWAP_AT_VALUE = "above_value", "below_value", "at_value"
#: today's point of control reads as shifted when it is more than this fraction of the prior
#: day's away from it. The figure's origin is not recorded (ACTIVE_PROGRAM.md VALUE-SHIFT).
VALUE_SHIFT_MIN_FRACTION: float = 0.002


@dataclass(frozen=True)
class ValueContext:
    """Today's value against the prior day's (`value_state`: VALUE_*) and the session VWAP against
    today's value area (`vwap_relation`: VWAP_*). Each is None with its reason when an input
    is absent."""
    value_state: Optional[str]
    value_state_reason: Optional[str]
    vwap_relation: Optional[str]
    vwap_relation_reason: Optional[str]


@dataclass
class PlaybookConfig:
    """Configurable engine settings."""
    opening_range_minutes: int = 15
    value_area_percent: float = 0.70
    clustering_threshold_pct: float = 0.002   # adjacent levels within 0.2% merge
    max_zone_width: float = 0.0   # 0 = no cap; when > 0, zones cannot exceed this width
    tick_size: float = 0.01


