"""
liquidity_models.py — Data models for Liquidity & Value Playbook Engine
========================================================================
Enums and dataclasses for structural snapshots, zones, and price levels.
Ticker-agnostic; works for any instrument.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from numeric_contract import float_nonnegative_or_none  # RC-274: absence is not zero volume

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


def volume_profile_poc_vah_val(
    bars: list,
    value_area_pct: float = 0.70,
    tick_size: float = 0.01,
    ndigits: int = 4,
) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """POC / VAH / VAL from a volume profile built by DISTRIBUTING each bar across [low, high].

    Returns (poc, vah, val), or (None, None, None) when no usable volume exists — absence reads
    as absence, never a fabricated level.

    Bins are addressed by INTEGER index (round(price / tick_size)) so that binning is exact:
    accumulating float bin prices as dict keys lets 724.9999999 and 725.0 become two bins for
    one price, which silently fragments the profile and can move the POC.
    """
    if not bars or tick_size <= 0:
        return None, None, None

    vol_by_idx: dict[int, float] = defaultdict(float)
    for b in bars:
        if not isinstance(b, dict):
            continue
        try:
            hi = float(b["high"])
            lo = float(b["low"])
            vol = float_nonnegative_or_none(b.get("volume"))  # RC-274
        except (KeyError, TypeError, ValueError):
            continue
        if vol is None:
            continue
        # NaN/inf must never enter the profile: a NaN bin key poisons every comparison after it
        if not (hi == hi and lo == lo and vol == vol):        # NaN check without importing math
            continue
        if hi in (float("inf"), float("-inf")) or lo in (float("inf"), float("-inf")):
            continue
        if vol <= 0:
            continue
        if hi < lo:
            hi, lo = lo, hi
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
        return None, None, None
    total_vol = sum(vol_by_idx.values())
    if total_vol <= 0:
        return None, None, None

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
    return (round(poc_idx * tick_size, ndigits),
            round(idx_sorted[hi_pos] * tick_size, ndigits),
            round(idx_sorted[lo_pos] * tick_size, ndigits))


class SnapshotType(str, Enum):
    """Structural checkpoint when levels are computed (no continuous redraw)."""
    PREMARKET = "premarket"
    OPENING = "opening"
    MIDDAY = "midday"
    AFTERNOON = "afternoon"
    LIVE = "live"


class ZoneType(str, Enum):
    """
    Canonical zone types for structure/value mapping.

    LP-01 Step 3 (RC-154) — `sell_side_liquidity` / `buy_side_liquidity` are RETIRED. Those
    names make an SMC claim: that resting stop orders pool beyond a prior extreme and that
    price is drawn to them. We have measured no such thing. There is no equal-extreme
    stop-cluster detector in this repo, no touch study, and no forward test — the zones were
    built from ordinary session extremes (overnight low, prior-day low, below the opening
    range) and then given a name that asserts a mechanism.

    What we can honestly say is geometric: this is the LOW extreme of the prior session /
    overnight window, or the HIGH one. `low_extreme` / `high_extreme` say exactly that and
    nothing more. If stop-cluster levels are ever built and proven, they earn their own type.

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


def zone_class_for_type(zone_type: ZoneType) -> str:
    """Return zone_class from zone_type: structure | trigger | value.

    RC-154: the `liquidity` CLASS is retired with the two types that carried it. No zone in
    this taxonomy is a measured liquidity pool, so no zone may be classed as one — a class is
    read as a category of evidence, and there is no evidence in that category yet.
    """
    _class_map = {
        ZoneType.LOW_EXTREME: "structure",
        ZoneType.HIGH_EXTREME: "structure",
        ZoneType.SUPPORT_LIQUIDITY: "structure",
        ZoneType.RESISTANCE_LIQUIDITY: "structure",
        ZoneType.BREAKDOWN_TRIGGER: "trigger",
        ZoneType.BREAKOUT_TRIGGER: "trigger",
        ZoneType.PIVOT_VALUE: "value",
    }
    return _class_map.get(zone_type, "value")


@dataclass
class PriceLevel:
    """Single price level with source tag."""
    label: str
    value: float
    source_tag: str = ""   # e.g. "PDH", "VWAP", "ORB_HIGH"


@dataclass
class Zone:
    """Clustered zone built from one or more price levels."""
    zone_type: ZoneType
    zone_low: float
    zone_high: float
    zone_mid: float
    source_levels: list[dict] = field(default_factory=list)   # [{"label": str, "value": float}]
    source_tags: list[str] = field(default_factory=list)
    confluence_score: int = 0
    snapshot_type: SnapshotType = SnapshotType.PREMARKET
    interpretation_notes: str = ""

    @property
    def zone_class(self) -> str:
        """Derived: liquidity | structure | trigger | value."""
        return zone_class_for_type(self.zone_type)


@dataclass
class SnapshotSummary:
    """Readable auction context interpretation."""
    value_state: str = ""           # "shifted_higher" | "shifted_lower" | "unchanged"
    vwap_relation: str = ""         # "above_value" | "below_value" | "at_value"
    auction_interpretation: str = ""  # "bullish_acceptance" | "bearish_acceptance" | etc.
    notes: list[str] = field(default_factory=list)


@dataclass
class SnapshotOutput:
    """Full structural snapshot output."""
    ticker: str
    session_date: str
    snapshot_type: SnapshotType
    zones: list[Zone] = field(default_factory=list)
    summary: Optional[SnapshotSummary] = None
    raw_levels: dict = field(default_factory=dict)  # for debugging/audit


@dataclass
class PlaybookConfig:
    """Configurable engine settings."""
    opening_range_minutes: int = 15
    value_area_percent: float = 0.70
    clustering_threshold: float = 0.0   # fixed $ when mode=fixed
    clustering_threshold_pct: float = 0.002   # 0.2% of price when mode=percent
    clustering_mode: str = "percent"   # "fixed" | "percent" | "atr"
    clustering_threshold_atr_mult: float = 1.0   # ATR multiplier when mode=atr
    atr_period: int = 14   # bars for ATR calculation
    max_zone_width: float = 0.0   # 0 = no cap; when > 0, zones cannot exceed this width
    max_distance_from_anchor: float = 0.0   # 0 = no cap; max distance from zone anchor
    timezone: str = "America/New_York"
    use_rth_only_profiles: bool = True
    tick_size: float = 0.01


@dataclass
class PlaybookState:
    """
    Full session state across all structural snapshots.
    Used for historical or live session tracking and dashboard integration.
    Snapshots may be None when not yet available (e.g. live mode before checkpoint).
    """
    ticker: str
    session_date: str
    premarket_snapshot: Optional[SnapshotOutput] = None
    opening_snapshot: Optional[SnapshotOutput] = None
    midday_snapshot: Optional[SnapshotOutput] = None
    afternoon_snapshot: Optional[SnapshotOutput] = None
    latest_snapshot_type: Optional[SnapshotType] = None
    latest_summary: Optional[SnapshotSummary] = None
    session_bias: str = ""   # "bullish" | "bearish" | "neutral" | ""
    auction_state: str = ""  # derived from latest summary
    generated_at: Optional[str] = None  # ISO timestamp when state was built
