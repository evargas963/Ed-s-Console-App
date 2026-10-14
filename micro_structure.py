"""
micro_structure.py — Micro Price-Action Analysis Engine
========================================================
Reads 1-min and 5-min OHLCV candle data and classifies the current
micro regime for the "Right Now" card.

Detection layers (in priority order):
  1. Market structure — swing highs/lows on 5-min (HH/HL/LH/LL)
  2. Break of Structure (BOS) — continuation signal
  3. Change of Character (CHoCH) — early reversal warning
  4. Candle patterns on 1-min — trigger-level reads
  5. Multi-bar patterns on 5-min — flags, double tops, compression
  6. Regime classification — synthesized from all above

Output: MicroRead dataclass consumed by the signals engine.

Design principles:
  - All analysis is pure functions on candle data — no side effects
  - Graceful degradation — if only 5-min available, skip 1-min patterns
  - Every detection function returns None/empty when data is insufficient
  - Plain English descriptions attached to every detection
"""

from dataclasses import (
    dataclass,
)
from typing import Optional

from numeric_contract import schwab_count, schwab_number



# ════════════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ════════════════════════════════════════════════════════════════════════════════

@dataclass
class Candle:
    """Single OHLCV bar."""
    ts:     float       # epoch seconds
    open:   float
    high:   float
    low:    float
    close:  float
    volume: Optional[float] = None


def schwab_bar(start_ms, o, h, lo, c, volume) -> "Candle | None":
    """One Schwab CHART_EQUITY bar (or /pricehistory candle) as a Candle, each field as Schwab sent
    it; None when its start or a price is not a number (AGENTS.md rule 2: absent, -999, text, NaN
    or infinity). A volume that is not a number, or negative, is absent."""
    start, o, h, lo, c = schwab_number(start_ms), schwab_number(o), schwab_number(h), schwab_number(lo), schwab_number(c)
    if None in (start, o, h, lo, c):
        return None
    return Candle(ts=start / 1000.0, open=o, high=h, low=lo, close=c, volume=schwab_count(volume))


def bar_dict(c: Candle) -> dict:
    """A bar as the chart draws it: start (epoch s), open, high, low, close, volume."""
    return {"t": float(c.ts), "o": c.open, "h": c.high, "l": c.low, "c": c.close, "v": c.volume}













# ════════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ════════════════════════════════════════════════════════════════════════════════










# ════════════════════════════════════════════════════════════════════════════════
# SWING DETECTION
# ════════════════════════════════════════════════════════════════════════════════



# ════════════════════════════════════════════════════════════════════════════════
# MARKET STRUCTURE CLASSIFICATION
# ════════════════════════════════════════════════════════════════════════════════



# ════════════════════════════════════════════════════════════════════════════════
# BREAK OF STRUCTURE / CHANGE OF CHARACTER
# ════════════════════════════════════════════════════════════════════════════════





# ════════════════════════════════════════════════════════════════════════════════
# SINGLE CANDLE PATTERN DETECTION
# ════════════════════════════════════════════════════════════════════════════════



# ════════════════════════════════════════════════════════════════════════════════
# MULTI-BAR PATTERN DETECTION
# ════════════════════════════════════════════════════════════════════════════════











# ════════════════════════════════════════════════════════════════════════════════
# TREND STRENGTH / MOMENTUM
# ════════════════════════════════════════════════════════════════════════════════



# ── Session High / Low ────────────────────────────────────────────────────────



# ── Liquidity Sweep Detection ────────────────────────────────────────────────









# ════════════════════════════════════════════════════════════════════════════════
# REGIME CLASSIFICATION — the main synthesis
# ════════════════════════════════════════════════════════════════════════════════












# ════════════════════════════════════════════════════════════════════════════════
# TEXT GENERATION
# ════════════════════════════════════════════════════════════════════════════════

