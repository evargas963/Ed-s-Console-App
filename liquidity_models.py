"""liquidity_models.py — Data models for Liquidity & Value Playbook Engine.

Enums and dataclasses for structural snapshots, zones, and price levels.
Ticker-agnostic; works for any instrument.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum

from numeric_contract import schwab_count, schwab_number

#: The ONE volume-profile construction.
#: A bar's volume did not trade at one price. It traded ACROSS [low, high], and the profile is
#: the record of where; a bar's whole volume put in one bin at the typical price (H+L+C)/3 would
#: be a typical-price histogram, not a volume profile. Auction Market Theory / Volume Profile
#: practice distributes the bar's volume across every price the bar traded through; POC is then
#: the price that actually saw the most volume, and the value area is the smallest contiguous band
#: holding `value_area_pct` of it.
#:
#: Uniform distribution across the spanned bins is the standard first-order model (it is what
#: TPO-style and most charting-package volume profiles do without tick-level trade data). The
#: profile is built from 1-minute bars, which carry no within-bar distribution, so a within-bar
#: shape would be invented, not measured.
#: Uniform is the honest choice: it asserts only what the bar actually tells us — this volume
#: traded somewhere in [low, high].

#: Bound the work a single pathological bar can cause (a wide index bar against a 0.01 tick).
#: When a bar spans more bins than this, its volume is spread across this many evenly-spaced
#: bins covering the SAME range — still distributed, never dumped, and never unbounded.
MAX_BINS_PER_BAR: int = 5000


@dataclass(frozen=True)
class VolumeProfile:
    """Volume by price from bars, each bar's volume spread evenly over its [low, high].

    Spread in tick bins -- a derived distribution from 1-minute bars, not traded volume at a
    price from trade prints -- and the value area read from it. `bins`: ((price, volume), ...)
    in price order. `bars`: the bars given; `bars_without_volume`: those Schwab sent with no
    volume, which the profile cannot place and does not contain.
    """

    tick_size: float
    bins: tuple
    poc: float
    vah: float
    val: float
    bars: int
    bars_without_volume: int


def _spread(vol_by_idx: dict[int, float], lo_i: int, hi_i: int, vol: float) -> None:
    """Spread one bar's volume evenly over the tick bins `lo_i`..`hi_i` (a flat bar: one bin).

    A bar spanning more than MAX_BINS_PER_BAR bins is spread over that many bins evenly spaced
    across the same range.
    """
    n = hi_i - lo_i + 1
    if n <= MAX_BINS_PER_BAR:
        share = vol / n
        for i in range(lo_i, hi_i + 1):
            vol_by_idx[i] += share
    else:
        share = vol / MAX_BINS_PER_BAR
        step = (hi_i - lo_i) / (MAX_BINS_PER_BAR - 1)
        for k in range(MAX_BINS_PER_BAR):
            vol_by_idx[int(round(lo_i + k * step))] += share


def _value_area(vols: list[float], poc: int, target: float) -> tuple[int, int]:
    """Return the value area's first and last positions in `vols` (each bin's volume, by price).

    From the POC's position it grows one bin at a time toward the side whose next bin holds more
    volume (the lower one on a tie), until it holds `target` or spans every bin.
    """
    lo = hi = poc
    acc = vols[poc]
    last = len(vols) - 1
    while acc < target and (lo > 0 or hi < last):
        v_lo = vols[lo - 1] if lo > 0 else -1.0  # every bin's volume is above 0
        v_hi = vols[hi + 1] if hi < last else -1.0
        if v_hi > v_lo:
            hi += 1
            acc += v_hi
        else:
            lo -= 1
            acc += v_lo
    return lo, hi


def volume_profile(
    bars: list,
    value_area_pct: float = 0.70,
    tick_size: float = 0.01,
    ndigits: int = 4,
) -> VolumeProfile | None:
    """Return the volume profile built by DISTRIBUTING each bar across [low, high].

    It comes with its POC and value area; None when no usable volume exists -- absence reads as
    absence, never a fabricated level.

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
        hi, lo, vol = (
            schwab_number(b.get("high")),
            schwab_number(b.get("low")),
            schwab_count(b.get("volume")),
        )
        no_volume += vol is None
        # high < low has no range to spread over (measured: 0 of 2,166,115 bars)
        if hi is None or lo is None or vol is None or vol == 0 or hi < lo:
            continue
        _spread(vol_by_idx, int(round(lo / tick_size)), int(round(hi / tick_size)), vol)

    if not vol_by_idx:  # every bin holds volume above 0
        return None
    idx_sorted = sorted(vol_by_idx)
    poc_idx = max(idx_sorted, key=lambda i: (vol_by_idx[i], -i))
    lo_pos, hi_pos = _value_area(
        [vol_by_idx[i] for i in idx_sorted],
        idx_sorted.index(poc_idx),
        sum(vol_by_idx.values()) * value_area_pct,
    )
    return VolumeProfile(
        tick_size=tick_size,
        bins=tuple((round(i * tick_size, ndigits), vol_by_idx[i]) for i in idx_sorted),
        poc=round(poc_idx * tick_size, ndigits),
        vah=round(idx_sorted[hi_pos] * tick_size, ndigits),
        val=round(idx_sorted[lo_pos] * tick_size, ndigits),
        bars=len(bars),
        bars_without_volume=no_volume,
    )


class SnapshotType(str, Enum):
    """The shape of the served zones: before the session's open (premarket) or during it (live)."""

    PREMARKET = "premarket"
    LIVE = "live"


class ZoneType(str, Enum):
    """
    Canonical zone types for structure/value mapping.

    The extremes are named for what they are, geometrically: the LOW extreme of the prior
    session / overnight window, or the HIGH one. No name claims a mechanism (resting stop
    orders pooling beyond an extreme): no stop-cluster detector, touch study or forward test
    has measured one. If stop-cluster levels are ever built and proven, they earn their own type.

    Taxonomy: low_extreme | support_liquidity | pivot_value | breakdown_trigger |
    breakout_trigger | resistance_liquidity | high_extreme
    """

    LOW_EXTREME = "low_extreme"
    SUPPORT_LIQUIDITY = "support_liquidity"
    PIVOT_VALUE = "pivot_value"
    BREAKDOWN_TRIGGER = "breakdown_trigger"
    BREAKOUT_TRIGGER = "breakout_trigger"
    RESISTANCE_LIQUIDITY = "resistance_liquidity"
    HIGH_EXTREME = "high_extreme"


#: each zone type's name on screen and the side of price it is drawn as: support, resistance or
#: value (neither)
ZONE_DISPLAY: dict[ZoneType, tuple[str, str]] = {
    ZoneType.LOW_EXTREME: ("Low extreme", "support"),
    ZoneType.SUPPORT_LIQUIDITY: ("Support", "support"),
    ZoneType.BREAKDOWN_TRIGGER: ("Breakdown trigger", "support"),
    ZoneType.PIVOT_VALUE: ("Pivot / value", "value"),
    ZoneType.BREAKOUT_TRIGGER: ("Breakout trigger", "resistance"),
    ZoneType.RESISTANCE_LIQUIDITY: ("Resistance", "resistance"),
    ZoneType.HIGH_EXTREME: ("High extreme", "resistance"),
}


@dataclass
class Zone:
    """Clustered zone built from one or more price levels."""

    zone_type: ZoneType
    zone_low: float
    zone_high: float
    zone_mid: float
    source_levels: list[dict] = field(default_factory=list)  # [{"label": str, "value": float}]
    source_tags: list[str] = field(default_factory=list)
    confluence_score: int = 0
    snapshot_type: SnapshotType = SnapshotType.PREMARKET
    interpretation_notes: str = ""


@dataclass
class SnapshotSummary:
    """Readable auction context interpretation."""

    value_state: str = ""  # "shifted_higher" | "shifted_lower" | "unchanged"
    vwap_relation: str = ""  # "above_value" | "below_value" | "at_value"


@dataclass
class SnapshotOutput:
    """Full structural snapshot output."""

    ticker: str
    snapshot_type: SnapshotType
    zones: list[Zone] = field(default_factory=list)
    summary: SnapshotSummary | None = None


@dataclass
class PlaybookConfig:
    """Configurable engine settings."""

    opening_range_minutes: int = 15
    value_area_percent: float = 0.70
    clustering_threshold_pct: float = 0.002  # adjacent levels within 0.2% merge
    max_zone_width: float = 0.0  # 0 = no cap; when > 0, zones cannot exceed this width
    tick_size: float = 0.01
