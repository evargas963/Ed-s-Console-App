"""
liquidity_models.py — Data models for Liquidity & Value Playbook Engine
========================================================================
Enums and dataclasses for structural snapshots, zones, and price levels.
Ticker-agnostic; works for any instrument.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class SnapshotType(str, Enum):
    """Structural checkpoint when levels are computed (no continuous redraw)."""
    PREMARKET = "premarket"
    OPENING = "opening"
    MIDDAY = "midday"
    AFTERNOON = "afternoon"
    LIVE = "live"


class ZoneType(str, Enum):
    """
    Canonical zone types for liquidity/value mapping.
    Taxonomy: sell_side_liquidity | support_liquidity | pivot_value | breakdown_trigger |
    breakout_trigger | resistance_liquidity | buy_side_liquidity
    """
    SELL_SIDE_LIQUIDITY = "sell_side_liquidity"
    SUPPORT_LIQUIDITY = "support_liquidity"
    PIVOT_VALUE = "pivot_value"
    BREAKDOWN_TRIGGER = "breakdown_trigger"
    BREAKOUT_TRIGGER = "breakout_trigger"
    RESISTANCE_LIQUIDITY = "resistance_liquidity"
    BUY_SIDE_LIQUIDITY = "buy_side_liquidity"


def zone_class_for_type(zone_type: ZoneType) -> str:
    """Return zone_class from zone_type: liquidity | structure | trigger | value."""
    _class_map = {
        ZoneType.SELL_SIDE_LIQUIDITY: "liquidity",
        ZoneType.BUY_SIDE_LIQUIDITY: "liquidity",
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
