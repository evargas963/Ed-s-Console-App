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







    @property
    def mid(self) -> float:
        return (self.high + self.low) / 2














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

