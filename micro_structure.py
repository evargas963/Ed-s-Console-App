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

import logging
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger(__name__)


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
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def upper_wick(self) -> float:
        return self.high - max(self.open, self.close)

    @property
    def lower_wick(self) -> float:
        return min(self.open, self.close) - self.low

    @property
    def is_green(self) -> bool:
        return self.close >= self.open

    @property
    def is_red(self) -> bool:
        return self.close < self.open

    @property
    def mid(self) -> float:
        return (self.high + self.low) / 2


@dataclass
class SwingPoint:
    """A detected swing high or swing low."""
    index:  int         # index into the candle list
    price:  float       # the high (for swing high) or low (for swing low)
    type:   str         # 'high' or 'low'
    ts:     float       # timestamp of the candle


@dataclass
class StructureBreak:
    """A Break of Structure (BOS) or Change of Character (CHoCH)."""
    type:       str         # 'bos' or 'choch'
    direction:  str         # 'up' or 'down'
    level:      float       # the swing level that was broken
    bar_index:  int         # which candle broke it
    description: str        # plain English


@dataclass
class CandlePattern:
    """A detected candle pattern."""
    name:       str         # 'doji', 'hammer', 'shooting_star', 'engulfing_bull', etc.
    bar_index:  int         # which candle(s)
    bias:       str         # 'bullish', 'bearish', 'neutral'
    description: str        # plain English


@dataclass
class MultiBarPattern:
    """A detected multi-bar pattern."""
    name:       str         # 'bull_flag', 'bear_flag', 'double_top', 'double_bottom', 'compression'
    start_idx:  int
    end_idx:    int
    bias:       str         # 'bullish', 'bearish', 'neutral'
    key_level:  Optional[float]   # the level the pattern revolves around
    description: str


@dataclass
class SweepEvent:
    """A liquidity sweep — price broke a swing level, triggering stops."""
    type:       str         # 'sweep_high' or 'sweep_low'
    level:      float       # the swing price that was broken
    bar_index:  int         # which candle broke it
    held:       bool        # True if price closed back inside (failed sweep), False if continuation
    description: str


@dataclass
class MicroRead:
    """
    Complete micro-structure analysis — consumed by the signals engine
    to generate the Right Now card.
    """
    # ── Regime classification (the headline) ──────────────────────────────────
    regime:             str     # TREND_UP, TREND_DOWN, BOS_UP, BOS_DOWN,
                                # CHOCH_BULL, CHOCH_BEAR, COMPRESSION,
                                # RANGE, REVERSAL_UP, REVERSAL_DOWN, CHOP
    regime_label:       str     # human-readable badge text
    regime_color:       str     # hex color for badge

    # ── 5-min structure ───────────────────────────────────────────────────────
    structure:          str     # 'uptrend', 'downtrend', 'range', 'no_structure'
    swing_highs:        list    # list of SwingPoint
    swing_lows:         list    # list of SwingPoint

    # ── 1-min regime (early warning system) ───────────────────────────────────
    regime_1m:          str = "UNKNOWN"   # same regime constants, from 1-min candles
    regime_1m_label:    str = ""          # human-readable

    last_swing_high:    Optional[SwingPoint] = None
    last_swing_low:     Optional[SwingPoint] = None

    # ── Structure breaks ──────────────────────────────────────────────────────
    bos:                Optional[StructureBreak] = None
    choch:              Optional[StructureBreak] = None

    # ── Candle patterns (1-min) ───────────────────────────────────────────────
    candle_patterns:    list = field(default_factory=list)   # list of CandlePattern

    # ── Multi-bar patterns (5-min) ────────────────────────────────────────────
    multi_patterns:     list = field(default_factory=list)   # list of MultiBarPattern

    # ── Compression state ─────────────────────────────────────────────────────
    is_compressing:     bool = False
    compression_bars:   int = 0
    compression_ratio:  float = 0.0    # current range / range N bars ago

    # ── Chop detection ────────────────────────────────────────────────────────
    is_chop:            bool = False
    chop_score:         float = 0.0    # 0-1, higher = choppier
    direction_changes:  int = 0        # how many times direction flipped in window

    # ── Descriptive text for the card ─────────────────────────────────────────
    headline_5m:        str = ""       # "5min: 3 higher lows — uptrend intact"
    headline_1m:        str = ""       # "1min: bull flag forming after BOS"
    detail:             str = ""       # fuller explanation
    alerts:             list = field(default_factory=list)   # urgent notes

    # ── Key structural levels from the swings ─────────────────────────────────
    structure_support:  Optional[float] = None   # most recent swing low
    structure_resist:   Optional[float] = None   # most recent swing high

    # ── Session high/low ──────────────────────────────────────────────────────
    session_high:       Optional[float] = None   # highest price today
    session_low:        Optional[float] = None   # lowest price today
    session_high_bar:   Optional[int] = None     # bar index of session high
    session_low_bar:    Optional[int] = None      # bar index of session low

    # ── Liquidity sweeps ──────────────────────────────────────────────────────
    sweeps:             list = field(default_factory=list)   # list of SweepEvent
    last_sweep:         Optional[SweepEvent] = None          # most recent sweep


# ════════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ════════════════════════════════════════════════════════════════════════════════

# Swing detection: how many bars on each side to confirm a pivot
SWING_LOOKBACK = 1

# Candle pattern thresholds (as fraction of range)
DOJI_BODY_RATIO     = 0.20
HAMMER_WICK_RATIO   = 2.0
ENGULF_MIN_BODY_PCT = 0.0003

# Compression
COMPRESSION_RATIO   = 0.60
COMPRESSION_MIN_BARS = 3

# Chop detection
CHOP_REVERSAL_THRESHOLD = 0.60
CHOP_WINDOW = 6

# Flag pattern
FLAG_IMPULSE_MIN_BARS = 2
FLAG_CONSOLIDATION_MIN = 3
FLAG_RETRACE_MAX = 0.50
FLAG_IMPULSE_MIN_PCT = 0.0015

# Double top/bottom tolerance
DOUBLE_LEVEL_TOL = 0.15

# Minimum candle body size
MIN_BODY_PCT = 0.00005

# Sweep alert collapse — max summary lines before truncation
SWEEP_SUMMARY_MAX_GROUPS = 3


# ════════════════════════════════════════════════════════════════════════════════
# SWING DETECTION
# ════════════════════════════════════════════════════════════════════════════════

def find_swing_points(candles: list[Candle], lookback: int = SWING_LOOKBACK) -> tuple[list[SwingPoint], list[SwingPoint]]:
    """
    Identify swing highs and swing lows from a candle series.
    Returns (swing_highs, swing_lows) as sorted lists.
    """
    n = len(candles)
    if n < (2 * lookback + 1):
        return [], []

    highs = []
    lows  = []

    for i in range(lookback, n - lookback):
        c = candles[i]

        is_high = True
        for j in range(i - lookback, i):
            if candles[j].high > c.high:
                is_high = False
                break
        if is_high:
            for j in range(i + 1, i + lookback + 1):
                if candles[j].high > c.high:
                    is_high = False
                    break
        if is_high:
            highs.append(SwingPoint(index=i, price=c.high, type="high", ts=c.ts))

        is_low = True
        for j in range(i - lookback, i):
            if candles[j].low < c.low:
                is_low = False
                break
        if is_low:
            for j in range(i + 1, i + lookback + 1):
                if candles[j].low < c.low:
                    is_low = False
                    break
        if is_low:
            lows.append(SwingPoint(index=i, price=c.low, type="low", ts=c.ts))

    return highs, lows


# ════════════════════════════════════════════════════════════════════════════════
# MARKET STRUCTURE CLASSIFICATION
# ════════════════════════════════════════════════════════════════════════════════

def classify_structure(swing_highs: list[SwingPoint],
                       swing_lows: list[SwingPoint]) -> str:
    """
    Classify the swing sequence into a market structure.
    Returns: 'uptrend', 'downtrend', 'range', 'no_structure'
    """
    if len(swing_highs) < 2 and len(swing_lows) < 2:
        return "no_structure"

    hh_count = lh_count = 0
    for i in range(1, len(swing_highs)):
        if swing_highs[i].price > swing_highs[i - 1].price:
            hh_count += 1
        elif swing_highs[i].price < swing_highs[i - 1].price:
            lh_count += 1

    hl_count = ll_count = 0
    for i in range(1, len(swing_lows)):
        if swing_lows[i].price > swing_lows[i - 1].price:
            hl_count += 1
        elif swing_lows[i].price < swing_lows[i - 1].price:
            ll_count += 1

    if hh_count >= 1 and hl_count >= 1:
        return "uptrend"
    if lh_count >= 1 and ll_count >= 1:
        return "downtrend"
    if hh_count >= 2:
        return "uptrend"
    if ll_count >= 2:
        return "downtrend"
    if lh_count >= 2:
        return "downtrend"
    if hl_count >= 2:
        return "uptrend"

    if len(swing_highs) >= 2 or len(swing_lows) >= 2:
        return "range"

    return "no_structure"


# ════════════════════════════════════════════════════════════════════════════════
# BREAK OF STRUCTURE / CHANGE OF CHARACTER
# ════════════════════════════════════════════════════════════════════════════════

def detect_bos(candles: list[Candle], structure: str,
               swing_highs: list[SwingPoint],
               swing_lows: list[SwingPoint]) -> Optional[StructureBreak]:
    """Break of Structure — a CONTINUATION signal."""
    if not candles:
        return None

    if structure == "uptrend" and swing_highs:
        last_sh = swing_highs[-1]
        for i in range(max(0, len(candles) - 3), len(candles)):
            if i > last_sh.index and candles[i].high > last_sh.price:
                return StructureBreak(
                    type="bos", direction="up",
                    level=last_sh.price, bar_index=i,
                    description=f"BOS up — broke above {last_sh.price:.2f} swing high"
                )

    if structure == "downtrend" and swing_lows:
        last_sl = swing_lows[-1]
        for i in range(max(0, len(candles) - 3), len(candles)):
            if i > last_sl.index and candles[i].low < last_sl.price:
                return StructureBreak(
                    type="bos", direction="down",
                    level=last_sl.price, bar_index=i,
                    description=f"BOS down — broke below {last_sl.price:.2f} swing low"
                )

    return None


def detect_choch(candles: list[Candle], structure: str,
                 swing_highs: list[SwingPoint],
                 swing_lows: list[SwingPoint]) -> Optional[StructureBreak]:
    """Change of Character — an early REVERSAL warning."""
    if not candles:
        return None

    if structure == "uptrend" and swing_lows:
        last_sl = swing_lows[-1]
        for i in range(max(0, len(candles) - 3), len(candles)):
            if i > last_sl.index and candles[i].low < last_sl.price:
                return StructureBreak(
                    type="choch", direction="down",
                    level=last_sl.price, bar_index=i,
                    description=f"CHoCH — broke below {last_sl.price:.2f} swing low, uptrend may be ending"
                )

    if structure == "downtrend" and swing_highs:
        last_sh = swing_highs[-1]
        for i in range(max(0, len(candles) - 3), len(candles)):
            if i > last_sh.index and candles[i].high > last_sh.price:
                return StructureBreak(
                    type="choch", direction="up",
                    level=last_sh.price, bar_index=i,
                    description=f"CHoCH — broke above {last_sh.price:.2f} swing high, downtrend may be ending"
                )

    return None


# ════════════════════════════════════════════════════════════════════════════════
# SINGLE CANDLE PATTERN DETECTION
# ════════════════════════════════════════════════════════════════════════════════

def detect_candle_patterns(candles: list[Candle], spot: Optional[float] = None) -> list[CandlePattern]:
    """Detect single-candle patterns on the most recent 2-3 candles."""
    if spot is None or spot <= 0 or len(candles) < 2:
        return []

    patterns = []
    curr = candles[-1]
    prev = candles[-2]

    min_body = spot * MIN_BODY_PCT
    engulf_min = spot * ENGULF_MIN_BODY_PCT

    rng = curr.range
    if rng < min_body:
        return []

    body_ratio = curr.body / rng if rng > 0 else 0

    if body_ratio < DOJI_BODY_RATIO:
        patterns.append(CandlePattern(
            name="doji", bar_index=len(candles) - 1,
            bias="neutral",
            description="Doji — indecision, body is tiny relative to the range"
        ))

    if (curr.lower_wick > HAMMER_WICK_RATIO * curr.body and
        curr.upper_wick < curr.body and
        curr.body > min_body):
        patterns.append(CandlePattern(
            name="hammer", bar_index=len(candles) - 1,
            bias="bullish",
            description="Hammer — long lower wick rejected lower prices, buyers stepped in"
        ))

    if (curr.upper_wick > HAMMER_WICK_RATIO * curr.body and
        curr.lower_wick < curr.body and
        curr.body > min_body):
        patterns.append(CandlePattern(
            name="shooting_star", bar_index=len(candles) - 1,
            bias="bearish",
            description="Shooting star — long upper wick rejected higher prices, sellers stepped in"
        ))

    if (prev.is_red and curr.is_green and
        curr.body >= engulf_min and
        curr.close > prev.open and curr.open < prev.close):
        patterns.append(CandlePattern(
            name="engulfing_bull", bar_index=len(candles) - 1,
            bias="bullish",
            description="Bullish engulfing — this bar's body completely swallowed the prior red bar"
        ))

    if (prev.is_green and curr.is_red and
        curr.body >= engulf_min and
        curr.open > prev.close and curr.close < prev.open):
        patterns.append(CandlePattern(
            name="engulfing_bear", bar_index=len(candles) - 1,
            bias="bearish",
            description="Bearish engulfing — this bar's body completely swallowed the prior green bar"
        ))

    if curr.high <= prev.high and curr.low >= prev.low:
        patterns.append(CandlePattern(
            name="inside_bar", bar_index=len(candles) - 1,
            bias="neutral",
            description="Inside bar — entire range fits within the prior bar, coiling before a move"
        ))

    total_wick = curr.upper_wick + curr.lower_wick
    if curr.body > min_body and total_wick > 3 * curr.body:
        if curr.lower_wick > curr.upper_wick * 2:
            patterns.append(CandlePattern(
                name="pin_bar_bull", bar_index=len(candles) - 1,
                bias="bullish",
                description="Bullish pin bar — strong rejection of lower prices"
            ))
        elif curr.upper_wick > curr.lower_wick * 2:
            patterns.append(CandlePattern(
                name="pin_bar_bear", bar_index=len(candles) - 1,
                bias="bearish",
                description="Bearish pin bar — strong rejection of higher prices"
            ))

    return patterns


# ════════════════════════════════════════════════════════════════════════════════
# MULTI-BAR PATTERN DETECTION
# ════════════════════════════════════════════════════════════════════════════════

def detect_compression(candles: list[Candle]) -> tuple[bool, int, float]:
    """Detect range compression — bars getting progressively narrower."""
    if len(candles) < COMPRESSION_MIN_BARS + 1:
        return False, 0, 0.0

    window = candles[-min(8, len(candles)):]
    ranges = [c.range for c in window]

    narrowing = 0
    for i in range(len(ranges) - 1, 0, -1):
        if ranges[i] < ranges[i - 1]:
            narrowing += 1
        else:
            break

    if narrowing < COMPRESSION_MIN_BARS:
        return False, 0, 0.0

    start_range = ranges[-(narrowing + 1)] if narrowing + 1 <= len(ranges) else ranges[0]
    if start_range < 0.01:
        return False, 0, 0.0

    ratio = ranges[-1] / start_range
    is_compressing = ratio <= COMPRESSION_RATIO and narrowing >= COMPRESSION_MIN_BARS
    return is_compressing, narrowing, round(ratio, 3)


def detect_chop(candles: list[Candle]) -> tuple[bool, float, int]:
    """Detect choppy, low-quality price action."""
    if len(candles) < CHOP_WINDOW:
        return False, 0.0, 0

    window = candles[-CHOP_WINDOW:]

    reversals = 0
    for i in range(1, len(window)):
        prev_dir = 1 if window[i - 1].close >= window[i - 1].open else -1
        curr_dir = 1 if window[i].close >= window[i].open else -1
        if prev_dir != curr_dir:
            reversals += 1

    wick_bars = 0
    for c in window:
        if c.body > 0.01:
            total_wick = c.upper_wick + c.lower_wick
            if total_wick > c.body * 1.5:
                wick_bars += 1

    net_move = abs(window[-1].close - window[0].open)
    total_range = sum(c.range for c in window)
    efficiency = net_move / total_range if total_range > 0 else 0

    reversal_ratio = reversals / (len(window) - 1)
    wick_ratio     = wick_bars / len(window)
    inefficiency   = 1.0 - efficiency

    chop_score = (reversal_ratio * 0.4 + wick_ratio * 0.3 + inefficiency * 0.3)
    chop_score = min(1.0, max(0.0, chop_score))

    is_chop = chop_score >= CHOP_REVERSAL_THRESHOLD
    return is_chop, round(chop_score, 3), reversals


def detect_flag(candles: list[Candle], spot: Optional[float] = None) -> Optional[MultiBarPattern]:
    """Detect bull and bear flags."""
    if spot is None or spot <= 0:
        return None
    n = len(candles)
    if n < FLAG_IMPULSE_MIN_BARS + FLAG_CONSOLIDATION_MIN:
        return None

    min_impulse = spot * FLAG_IMPULSE_MIN_PCT

    for split in range(n - FLAG_CONSOLIDATION_MIN, FLAG_IMPULSE_MIN_BARS - 1, -1):
        impulse = candles[:split]
        consol  = candles[split:]

        if len(consol) < FLAG_CONSOLIDATION_MIN:
            continue

        impulse_move = impulse[-1].close - impulse[0].open
        impulse_range = max(c.high for c in impulse) - min(c.low for c in impulse)

        if abs(impulse_move) < min_impulse:
            continue

        consol_high = max(c.high for c in consol)
        consol_low  = min(c.low for c in consol)
        consol_range = consol_high - consol_low

        if consol_range > impulse_range * 0.60:
            continue

        if impulse_move > 0:
            retrace = impulse[-1].close - consol_low
            retrace_pct = retrace / impulse_move if impulse_move > 0 else 1.0
            if retrace_pct <= FLAG_RETRACE_MAX:
                return MultiBarPattern(
                    name="bull_flag", start_idx=0, end_idx=n - 1,
                    bias="bullish",
                    key_level=consol_high,
                    description=f"Bull flag — {len(impulse)}-bar impulse up, {len(consol)} bars consolidating"
                )
        else:
            retrace = consol_high - impulse[-1].close
            retrace_pct = retrace / abs(impulse_move) if impulse_move != 0 else 1.0
            if retrace_pct <= FLAG_RETRACE_MAX:
                return MultiBarPattern(
                    name="bear_flag", start_idx=0, end_idx=n - 1,
                    bias="bearish",
                    key_level=consol_low,
                    description=f"Bear flag — {len(impulse)}-bar impulse down, {len(consol)} bars consolidating"
                )

    return None


def detect_double_top_bottom(swing_highs: list[SwingPoint],
                              swing_lows: list[SwingPoint],
                              spot: float) -> Optional[MultiBarPattern]:
    """Detect double top or double bottom from swing points."""
    if len(swing_highs) >= 2:
        sh1 = swing_highs[-2]
        sh2 = swing_highs[-1]
        tol = max(sh1.price, sh2.price) * DOUBLE_LEVEL_TOL / 100
        if abs(sh1.price - sh2.price) <= tol:
            avg_level = (sh1.price + sh2.price) / 2
            if spot <= avg_level + tol:
                return MultiBarPattern(
                    name="double_top", start_idx=sh1.index, end_idx=sh2.index,
                    bias="bearish", key_level=round(avg_level, 2),
                    description=f"Double top at {avg_level:.2f} — two rejections of the same level"
                )

    if len(swing_lows) >= 2:
        sl1 = swing_lows[-2]
        sl2 = swing_lows[-1]
        tol = max(sl1.price, sl2.price) * DOUBLE_LEVEL_TOL / 100
        if abs(sl1.price - sl2.price) <= tol:
            avg_level = (sl1.price + sl2.price) / 2
            if spot >= avg_level - tol:
                return MultiBarPattern(
                    name="double_bottom", start_idx=sl1.index, end_idx=sl2.index,
                    bias="bullish", key_level=round(avg_level, 2),
                    description=f"Double bottom at {avg_level:.2f} — two bounces off the same level"
                )

    return None


def detect_multi_bar_patterns(candles: list[Candle],
                               swing_highs: list[SwingPoint],
                               swing_lows: list[SwingPoint],
                               spot: float) -> list[MultiBarPattern]:
    """Run all multi-bar pattern detectors."""
    patterns = []
    flag = detect_flag(candles[-12:] if len(candles) > 12 else candles, spot=spot)
    if flag:
        patterns.append(flag)
    dbl = detect_double_top_bottom(swing_highs, swing_lows, spot)
    if dbl:
        patterns.append(dbl)
    return patterns


# ════════════════════════════════════════════════════════════════════════════════
# TREND STRENGTH / MOMENTUM
# ════════════════════════════════════════════════════════════════════════════════

def _count_consecutive_direction(candles: list[Candle]) -> tuple[int, str]:
    """Count consecutive candles in the same direction from the end."""
    if not candles:
        return 0, "flat"
    last_dir = "up" if candles[-1].is_green else "down"
    count = 1
    for i in range(len(candles) - 2, -1, -1):
        c_dir = "up" if candles[i].is_green else "down"
        if c_dir == last_dir:
            count += 1
        else:
            break
    return count, last_dir


# ── Session High / Low ────────────────────────────────────────────────────────

def compute_session_hl(candles: list) -> tuple:
    """
    Find session high and low from candle data.

    Returns (session_high, session_low, high_bar_idx, low_bar_idx).
    """
    if not candles:
        return None, None, None, None

    s_high = None
    s_low = None
    high_idx = 0
    low_idx = 0

    for i, c in enumerate(candles):
        if s_high is None or c.high > s_high:
            s_high = c.high
            high_idx = i
        if s_low is None or c.low < s_low:
            s_low = c.low
            low_idx = i

    return s_high, s_low, high_idx, low_idx


# ── Liquidity Sweep Detection ────────────────────────────────────────────────

def detect_sweeps(
    candles: list,
    swing_highs: list,
    swing_lows: list,
    session_high: float | None = None,
    session_low: float | None = None,
) -> list:
    """
    Detect liquidity sweeps — price breaking a swing level or session extreme.

    Per Institutional Acceleration Zone Framework:
    A sweep occurs when price breaks a prior swing high/low (or session high/low),
    triggering stop orders and forced execution.

    Detection logic:
    - A candle's high exceeds a prior swing high → sweep_high
    - A candle's low exceeds a prior swing low → sweep_low
    - If the candle closes BACK inside the level → failed sweep (reversal signal)
    - If the candle closes beyond the level → continuation sweep

    Also checks session high/low as sweep targets.

    Args:
        candles:       list of Candle objects
        swing_highs:   list of SwingPoint (type='high')
        swing_lows:    list of SwingPoint (type='low')
        session_high:  today's session high (optional)
        session_low:   today's session low (optional)

    Returns list of SweepEvent.
    """
    if not candles or len(candles) < 3:
        return []

    sweeps = []
    last_bar = candles[-1]
    prev_bar = candles[-2]

    # Build sweep target levels from recent swing points
    # Only check swings that occurred BEFORE the last 2 bars
    high_targets = []
    for sp in swing_highs:
        if sp.index < len(candles) - 2:
            high_targets.append(sp.price)

    low_targets = []
    for sp in swing_lows:
        if sp.index < len(candles) - 2:
            low_targets.append(sp.price)

    # Add session high/low as targets (most recent swing might be the session extreme)
    if session_high is not None and session_high not in high_targets:
        # Only add if session high was set before the current bar
        # (i.e., current bar hasn't yet made a new session high by more than a wick)
        pass  # session high sweeps handled below

    # Check if last bar swept any swing high
    for target in high_targets:
        if last_bar.high > target and prev_bar.high <= target:
            # Price broke above this swing high on the current bar
            held = last_bar.close < target  # closed back below = failed sweep
            desc = (f"Swept swing high at {target:.2f}"
                    + (" — FAILED, closed back below (reversal)" if held
                       else " — held above (continuation)"))
            sweeps.append(SweepEvent(
                type="sweep_high",
                level=target,
                bar_index=len(candles) - 1,
                held=held,
                description=desc,
            ))

    # Check if last bar swept any swing low
    for target in low_targets:
        if last_bar.low < target and prev_bar.low >= target:
            # Price broke below this swing low on the current bar
            held = last_bar.close > target  # closed back above = failed sweep
            desc = (f"Swept swing low at {target:.2f}"
                    + (" — FAILED, closed back above (reversal)" if held
                       else " — held below (continuation)"))
            sweeps.append(SweepEvent(
                type="sweep_low",
                level=target,
                bar_index=len(candles) - 1,
                held=held,
                description=desc,
            ))

    # Session high/low sweeps (only if we have prior bars establishing them)
    if session_high is not None and len(candles) >= 10:
        # Check if current bar made a new session high after at least 10 bars
        prior_high = max(c.high for c in candles[:-1])
        if last_bar.high > prior_high and prev_bar.high <= prior_high:
            held = last_bar.close < prior_high
            desc = (f"Swept session high at {prior_high:.2f}"
                    + (" — FAILED, closed back below" if held
                       else " — new session high (breakout)"))
            sweeps.append(SweepEvent(
                type="sweep_high",
                level=prior_high,
                bar_index=len(candles) - 1,
                held=held,
                description=desc,
            ))

    if session_low is not None and len(candles) >= 10:
        prior_low = min(c.low for c in candles[:-1])
        if last_bar.low < prior_low and prev_bar.low >= prior_low:
            held = last_bar.close > prior_low
            desc = (f"Swept session low at {prior_low:.2f}"
                    + (" — FAILED, closed back above" if held
                       else " — new session low (breakdown)"))
            sweeps.append(SweepEvent(
                type="sweep_low",
                level=prior_low,
                bar_index=len(candles) - 1,
                held=held,
                description=desc,
            ))

    return sweeps


def collapse_sweep_alerts(sweeps: list) -> list[str]:
    """
    Group sweep events by (direction, outcome) and produce summary lines.

    - direction: "swing high" or "swing low" (from type sweep_high/sweep_low)
    - outcome: "continuation" (held=False) or "reversal" (held=True)

    For each group: one summary line with count, price range, outcome.
    Single-event groups show normally (no ×N badge).
    Cap at SWEEP_SUMMARY_MAX_GROUPS lines; if more, show "(+N more sweep groups)".
    """
    if not sweeps:
        return []

    # Group by (direction, outcome)
    groups: dict[tuple[str, str], list] = {}
    for sw in sweeps:
        direction = "swing high" if getattr(sw, "type", "") == "sweep_high" else "swing low"
        outcome = "reversal" if getattr(sw, "held", False) else "continuation"
        key = (direction, outcome)
        if key not in groups:
            groups[key] = []
        groups[key].append(sw)

    # Build summary lines
    lines: list[str] = []
    for (direction, outcome), events in groups.items():
        count = len(events)
        levels: list[float] = []
        for e in events:
            lv = getattr(e, "level", None)
            if lv is None:
                continue
            try:
                levels.append(float(lv))
            except (TypeError, ValueError):
                continue
        if not levels:
            continue
        price_lo = min(levels)
        price_hi = max(levels)

        if outcome == "reversal":
            outcome_label = "rejected"
        elif direction == "swing low":
            outcome_label = "held below (continuation)"
        else:
            outcome_label = "held above (continuation)"

        if count == 1:
            # Single event — show normally, no count badge
            lines.append(f"SWEEP: Swept {direction} at {price_lo:.2f} — {outcome_label}")
        else:
            # Grouped summary
            lines.append(f"SWEEP: ×{count} {direction} {price_lo:.2f}–{price_hi:.2f} — {outcome_label}")

    # Cap at SWEEP_SUMMARY_MAX_GROUPS
    if len(lines) > SWEEP_SUMMARY_MAX_GROUPS:
        kept = lines[:SWEEP_SUMMARY_MAX_GROUPS]
        extra = len(lines) - SWEEP_SUMMARY_MAX_GROUPS
        kept.append(f"(+{extra} more sweep groups)")
        return kept
    return lines


def _higher_lows_count(candles: list[Candle]) -> int:
    """Count consecutive higher lows from the end."""
    if len(candles) < 2:
        return 0
    count = 0
    for i in range(len(candles) - 1, 0, -1):
        if candles[i].low > candles[i - 1].low:
            count += 1
        else:
            break
    return count


def _lower_highs_count(candles: list[Candle]) -> int:
    """Count consecutive lower highs from the end."""
    if len(candles) < 2:
        return 0
    count = 0
    for i in range(len(candles) - 1, 0, -1):
        if candles[i].high < candles[i - 1].high:
            count += 1
        else:
            break
    return count


# ════════════════════════════════════════════════════════════════════════════════
# REGIME CLASSIFICATION — the main synthesis
# ════════════════════════════════════════════════════════════════════════════════

R_TREND_UP    = "TREND_UP"
R_TREND_DOWN  = "TREND_DOWN"
R_BOS_UP      = "BOS_UP"
R_BOS_DOWN    = "BOS_DOWN"
R_CHOCH_BULL  = "CHOCH_BULL"
R_CHOCH_BEAR  = "CHOCH_BEAR"
R_COMPRESSION = "COMPRESSION"
R_RANGE       = "RANGE"
R_REVERSAL_UP = "REVERSAL_UP"
R_REVERSAL_DN = "REVERSAL_DOWN"
R_CHOP        = "CHOP"
R_UNKNOWN     = "UNKNOWN"

REGIME_LABELS = {
    R_TREND_UP:    "TREND UP",
    R_TREND_DOWN:  "TREND DOWN",
    R_BOS_UP:      "BOS ↑",
    R_BOS_DOWN:    "BOS ↓",
    R_CHOCH_BULL:  "CHoCH ↑",
    R_CHOCH_BEAR:  "CHoCH ↓",
    R_COMPRESSION: "COMPRESSING",
    R_RANGE:       "RANGE",
    R_REVERSAL_UP: "REVERSAL ↑",
    R_REVERSAL_DN: "REVERSAL ↓",
    R_CHOP:        "CHOP",
    R_UNKNOWN:     "—",
}

REGIME_COLORS = {
    R_TREND_UP:    "#16a34a",
    R_TREND_DOWN:  "#dc2626",
    R_BOS_UP:      "#2563eb",
    R_BOS_DOWN:    "#dc2626",
    R_CHOCH_BULL:  "#d97706",
    R_CHOCH_BEAR:  "#d97706",
    R_COMPRESSION: "#7c3aed",
    R_RANGE:       "#92400e",
    R_REVERSAL_UP: "#0891b2",
    R_REVERSAL_DN: "#0891b2",
    R_CHOP:        "#6b7280",
    R_UNKNOWN:     "#374151",
}


# ── 1-min regime direction helper ─────────────────────────────────────────────
# Maps regime constants to directional lean for cross-timeframe comparison
_REGIME_BULLISH = {R_TREND_UP, R_BOS_UP, R_CHOCH_BULL, R_REVERSAL_UP}
_REGIME_BEARISH = {R_TREND_DOWN, R_BOS_DOWN, R_CHOCH_BEAR, R_REVERSAL_DN}

def regime_direction(regime: str) -> str:
    """Return 'bullish', 'bearish', or 'neutral' for any regime constant."""
    if regime in _REGIME_BULLISH:
        return "bullish"
    if regime in _REGIME_BEARISH:
        return "bearish"
    return "neutral"


def analyze_micro(candles_5m: list[Candle],
                  candles_1m: list[Candle],
                  spot: float) -> MicroRead:
    """
    Main entry point — run full micro-structure analysis.

    Requires at least 5 bars of 5-min data. 1-min data is optional
    (if missing, candle patterns are skipped).

    Returns a complete MicroRead for the Right Now card.
    """
    # ── Guard: insufficient data ──────────────────────────────────────────────
    if not candles_5m or len(candles_5m) < 5:
        return MicroRead(
            regime=R_UNKNOWN, regime_label="WAITING",
            regime_color=REGIME_COLORS[R_UNKNOWN],
            structure="no_structure", swing_highs=[], swing_lows=[],
            headline_5m="Not enough candle data yet — need at least 5 bars.",
            detail="Candle data is still loading. Structure analysis will begin shortly."
        )

    # ── Step 1: Swing detection on 5-min ──────────────────────────────────────
    sh_5m, sl_5m = find_swing_points(candles_5m)
    last_sh = sh_5m[-1] if sh_5m else None
    last_sl = sl_5m[-1] if sl_5m else None

    # ── Step 2: Structure classification ──────────────────────────────────────
    structure = classify_structure(sh_5m, sl_5m)

    # ── Step 3: BOS / CHoCH detection ─────────────────────────────────────────
    bos   = detect_bos(candles_5m, structure, sh_5m, sl_5m)
    choch = detect_choch(candles_5m, structure, sh_5m, sl_5m)

    # ── Step 4: Candle patterns on 1-min ──────────────────────────────────────
    candle_pats = detect_candle_patterns(candles_1m, spot=spot) if candles_1m and len(candles_1m) >= 2 else []

    # ── Step 5: Multi-bar patterns on 5-min ───────────────────────────────────
    multi_pats = detect_multi_bar_patterns(candles_5m, sh_5m, sl_5m, spot)

    # ── Step 6: Compression detection ─────────────────────────────────────────
    is_comp, comp_bars, comp_ratio = detect_compression(candles_5m)

    # ── Step 7: Chop detection ────────────────────────────────────────────────
    is_chop, chop_score, dir_changes = detect_chop(candles_5m)

    # ── Step 8: Trend momentum stats ──────────────────────────────────────────
    hl_count = _higher_lows_count(candles_5m)
    lh_count = _lower_highs_count(candles_5m)
    consec_count, consec_dir = _count_consecutive_direction(candles_5m)

    # ── Step 9: Classify regime (priority order) ──────────────────────────────
    regime = _classify_regime(
        structure=structure,
        bos=bos, choch=choch,
        candle_pats=candle_pats,
        multi_pats=multi_pats,
        is_compressing=is_comp,
        is_chop=is_chop, chop_score=chop_score,
        hl_count=hl_count, lh_count=lh_count,
    )

    # ── Step 9b: 1-min regime classification (early warning) ──────────────────
    regime_1m = R_UNKNOWN
    regime_1m_label = ""
    if candles_1m and len(candles_1m) >= 5:
        sh_1m, sl_1m = find_swing_points(candles_1m)
        struct_1m = classify_structure(sh_1m, sl_1m)
        bos_1m   = detect_bos(candles_1m, struct_1m, sh_1m, sl_1m)
        choch_1m = detect_choch(candles_1m, struct_1m, sh_1m, sl_1m)
        is_chop_1m, chop_1m_score, _ = detect_chop(candles_1m)
        is_comp_1m, _, _ = detect_compression(candles_1m)
        hl_1m = _higher_lows_count(candles_1m)
        lh_1m = _lower_highs_count(candles_1m)
        # Reuse candle_pats already detected on 1-min above
        regime_1m = _classify_regime(
            structure=struct_1m,
            bos=bos_1m, choch=choch_1m,
            candle_pats=candle_pats,
            multi_pats=[],  # no multi-bar patterns on 1-min
            is_compressing=is_comp_1m,
            is_chop=is_chop_1m, chop_score=chop_1m_score,
            hl_count=hl_1m, lh_count=lh_1m,
        )
        regime_1m_label = REGIME_LABELS.get(regime_1m, regime_1m)

    # ── Step 9c: Session high/low ─────────────────────────────────────────────
    s_high, s_low, s_high_idx, s_low_idx = compute_session_hl(candles_5m)

    # ── Step 9d: Liquidity sweep detection ────────────────────────────────────
    sweeps = detect_sweeps(candles_5m, sh_5m, sl_5m, s_high, s_low)
    last_sweep = sweeps[-1] if sweeps else None

    # ── Step 10: Generate text ────────────────────────────────────────────────
    headline_5m, headline_1m, detail, alerts = _generate_text(
        regime=regime, structure=structure,
        bos=bos, choch=choch,
        candle_pats=candle_pats, multi_pats=multi_pats,
        is_comp=is_comp, comp_bars=comp_bars, comp_ratio=comp_ratio,
        is_chop=is_chop, chop_score=chop_score, dir_changes=dir_changes,
        hl_count=hl_count, lh_count=lh_count,
        consec_count=consec_count, consec_dir=consec_dir,
        sh_5m=sh_5m, sl_5m=sl_5m, spot=spot,
        candles_5m=candles_5m,
    )

    # Add sweep alerts — collapsed by (direction, outcome) to avoid flooding
    for line in collapse_sweep_alerts(sweeps):
        alerts.append(line)

    # ── Add 1-min contradiction alert ─────────────────────────────────────────
    dir_5m = regime_direction(regime)
    dir_1m = regime_direction(regime_1m)
    if (dir_5m != "neutral" and dir_1m != "neutral" and dir_5m != dir_1m):
        alerts.append(
            f"⚠ 1-min structure ({regime_1m_label}) contradicts "
            f"5-min ({REGIME_LABELS.get(regime, regime)}) — early reversal signal"
        )

    return MicroRead(
        regime=regime,
        regime_label=REGIME_LABELS.get(regime, regime),
        regime_color=REGIME_COLORS.get(regime, "#374151"),
        regime_1m=regime_1m,
        regime_1m_label=regime_1m_label,
        structure=structure,
        swing_highs=sh_5m,
        swing_lows=sl_5m,
        last_swing_high=last_sh,
        last_swing_low=last_sl,
        bos=bos,
        choch=choch,
        candle_patterns=candle_pats,
        multi_patterns=multi_pats,
        is_compressing=is_comp,
        compression_bars=comp_bars,
        compression_ratio=comp_ratio,
        is_chop=is_chop,
        chop_score=chop_score,
        direction_changes=dir_changes,
        headline_5m=headline_5m,
        headline_1m=headline_1m,
        detail=detail,
        alerts=alerts,
        structure_support=last_sl.price if last_sl else None,
        structure_resist=last_sh.price if last_sh else None,
        session_high=s_high,
        session_low=s_low,
        session_high_bar=s_high_idx,
        session_low_bar=s_low_idx,
        sweeps=sweeps,
        last_sweep=last_sweep,
    )


def _classify_regime(structure, bos, choch, candle_pats, multi_pats,
                     is_compressing, is_chop, chop_score,
                     hl_count, lh_count) -> str:
    """
    Classify the micro regime. Priority order matters — earlier checks win.

    KEY DESIGN: BOS and CHoCH have HIGHEST priority. A structure break
    during chop is the most valuable signal possible.
    """
    if bos:
        if bos.direction == "up":
            return R_BOS_UP
        else:
            return R_BOS_DOWN

    if choch:
        confirm_pats = [p for p in candle_pats
                        if (choch.direction == "up" and p.bias == "bullish") or
                           (choch.direction == "down" and p.bias == "bearish")]
        if confirm_pats:
            return R_REVERSAL_UP if choch.direction == "up" else R_REVERSAL_DN
        else:
            return R_CHOCH_BULL if choch.direction == "up" else R_CHOCH_BEAR

    # High-conviction chop: only if NO clear trend structure
    # In high-VIX, large candles swing both ways but can still be trending.
    # CHOP should override RANGE, not established trends with hl/lh counts.
    if is_chop and chop_score >= 0.75:
        has_trend = (structure in ("uptrend", "downtrend") and (hl_count >= 2 or lh_count >= 2))
        if not has_trend:
            return R_CHOP

    if is_compressing:
        return R_COMPRESSION

    for mp in multi_pats:
        if mp.name == "bull_flag" and structure == "uptrend":
            return R_TREND_UP
        if mp.name == "bear_flag" and structure == "downtrend":
            return R_TREND_DOWN

    if structure == "uptrend" and hl_count >= 2:
        return R_TREND_UP
    if structure == "downtrend" and lh_count >= 2:
        return R_TREND_DOWN

    if structure == "range":
        return R_RANGE

    if is_chop:
        return R_CHOP

    if structure == "uptrend":
        return R_TREND_UP
    if structure == "downtrend":
        return R_TREND_DOWN

    return R_RANGE


# ════════════════════════════════════════════════════════════════════════════════
# TEXT GENERATION
# ════════════════════════════════════════════════════════════════════════════════

def _generate_text(regime, structure, bos, choch, candle_pats, multi_pats,
                   is_comp, comp_bars, comp_ratio, is_chop, chop_score,
                   dir_changes, hl_count, lh_count, consec_count, consec_dir,
                   sh_5m, sl_5m, spot, candles_5m) -> tuple[str, str, str, list]:
    """Generate the card text from the analysis results."""
    headline_5m = ""
    headline_1m = ""
    detail      = ""
    alerts      = []

    last_sh_price = sh_5m[-1].price if sh_5m else None
    last_sl_price = sl_5m[-1].price if sl_5m else None

    if regime == R_TREND_UP:
        flag_note = ""
        for mp in multi_pats:
            if mp.name == "bull_flag":
                flag_note = ", bull flag forming"
                break
        headline_5m = (
            f"5min: {hl_count} higher low{'s' if hl_count != 1 else ''} — "
            f"uptrend intact{flag_note}."
        )
        detail = (
            f"Price is making higher lows on the 5-min chart. "
            f"{'Holding above ' + f'{last_sl_price:.2f} swing low. ' if last_sl_price else ''}"
            f"{'Next resistance at ' + f'{last_sh_price:.2f}. ' if last_sh_price else ''}"
            f"Trend is your friend — look for pullbacks to enter, don't fade this."
        )

    elif regime == R_TREND_DOWN:
        flag_note = ""
        for mp in multi_pats:
            if mp.name == "bear_flag":
                flag_note = ", bear flag forming"
                break
        headline_5m = (
            f"5min: {lh_count} lower high{'s' if lh_count != 1 else ''} — "
            f"downtrend intact{flag_note}."
        )
        detail = (
            f"Price is making lower highs on the 5-min chart. "
            f"{'Capped by ' + f'{last_sh_price:.2f} swing high. ' if last_sh_price else ''}"
            f"{'Next support at ' + f'{last_sl_price:.2f}. ' if last_sl_price else ''}"
            f"Don't catch this knife — wait for structure change before going long."
        )

    elif regime == R_BOS_UP:
        headline_5m = f"5min: Break of structure UP — broke above {bos.level:.2f}."
        detail = (
            f"Price just took out the prior swing high at {bos.level:.2f}. "
            f"This is a continuation signal — the uptrend is accelerating. "
            f"{'Support now at ' + f'{last_sl_price:.2f}. ' if last_sl_price else ''}"
            f"Look for a retest of the breakout level as new support."
        )

    elif regime == R_BOS_DOWN:
        headline_5m = f"5min: Break of structure DOWN — broke below {bos.level:.2f}."
        detail = (
            f"Price just took out the prior swing low at {bos.level:.2f}. "
            f"This is a continuation signal — the downtrend is accelerating. "
            f"{'Resistance now at ' + f'{last_sh_price:.2f}. ' if last_sh_price else ''}"
            f"Look for a retest of the broken level as new resistance."
        )

    elif regime == R_CHOCH_BULL:
        headline_5m = f"5min: Change of character — broke above {choch.level:.2f} swing high."
        detail = (
            f"First higher high after a downtrend. This is an early reversal warning, "
            f"not a confirmed trend change yet. Watch for a higher low to confirm. "
            f"{'Key level: ' + f'{last_sl_price:.2f} must hold as support. ' if last_sl_price else ''}"
            f"Reduce short bias but don't go aggressively long yet."
        )

    elif regime == R_CHOCH_BEAR:
        headline_5m = f"5min: Change of character — broke below {choch.level:.2f} swing low."
        detail = (
            f"First lower low after an uptrend. This is an early reversal warning, "
            f"not a confirmed trend change yet. Watch for a lower high to confirm. "
            f"{'Key level: ' + f'{last_sh_price:.2f} must hold as resistance. ' if last_sh_price else ''}"
            f"Reduce long bias but don't go aggressively short yet."
        )

    elif regime == R_REVERSAL_UP:
        confirm_names = [p.name for p in candle_pats if p.bias == "bullish"]
        pat_text = confirm_names[0].replace("_", " ") if confirm_names else "confirming pattern"
        headline_5m = f"5min: Reversal attempt UP — CHoCH + {pat_text}."
        detail = (
            f"Structure broke higher AND a bullish candle pattern confirms buyers stepping in. "
            f"This is a stronger reversal signal than CHoCH alone. "
            f"{'Hold above ' + f'{last_sl_price:.2f} to stay valid. ' if last_sl_price else ''}"
        )

    elif regime == R_REVERSAL_DN:
        confirm_names = [p.name for p in candle_pats if p.bias == "bearish"]
        pat_text = confirm_names[0].replace("_", " ") if confirm_names else "confirming pattern"
        headline_5m = f"5min: Reversal attempt DOWN — CHoCH + {pat_text}."
        detail = (
            f"Structure broke lower AND a bearish candle pattern confirms sellers stepping in. "
            f"This is a stronger reversal signal than CHoCH alone. "
            f"{'Stay below ' + f'{last_sh_price:.2f} to stay valid. ' if last_sh_price else ''}"
        )

    elif regime == R_COMPRESSION:
        headline_5m = f"5min: Compressing — {comp_bars} bars of narrowing range."
        detail = (
            f"Each bar's range is getting smaller — price is coiling. "
            f"Current range is {comp_ratio*100:.0f}% of what it was {comp_bars} bars ago. "
            f"Something is about to happen — get ready but don't guess direction. "
            f"Wait for the breakout candle, then follow it."
        )

    elif regime == R_RANGE:
        range_hi = max(c.high for c in candles_5m[-8:]) if len(candles_5m) >= 8 else candles_5m[-1].high
        range_lo = min(c.low for c in candles_5m[-8:]) if len(candles_5m) >= 8 else candles_5m[-1].low
        range_pts = round(range_hi - range_lo, 2)
        headline_5m = f"5min: Range-bound {range_lo:.2f}–{range_hi:.2f} ({range_pts}pts)."
        dbl_note = ""
        for mp in multi_pats:
            if "double" in mp.name:
                dbl_note = f" {mp.description}."
                break
        detail = (
            f"Price is bouncing between {range_lo:.2f} and {range_hi:.2f} "
            f"with no consistent direction.{dbl_note} "
            f"Trade the edges — sell near the top, buy near the bottom. "
            f"Don't chase moves in the middle of the range."
        )

    elif regime == R_CHOP:
        headline_5m = f"5min: Choppy — {dir_changes} direction changes, no follow-through."
        detail = (
            f"{dir_changes} of the last {CHOP_WINDOW} bars reversed the prior bar's direction. "
            f"No reliable structure, no edge. "
            f"Every entry here gets stopped out — sit on hands until structure develops."
        )

    else:
        headline_5m = "5min: Reading structure..."
        detail = "Not enough data to classify the micro regime yet."

    if candle_pats:
        best = candle_pats[0]
        headline_1m = f"1min: {best.description}."
    elif consec_count >= 3:
        dir_word = "green" if consec_dir == "up" else "red"
        headline_1m = f"1min: {consec_count} consecutive {dir_word} bars — strong momentum {consec_dir}."
    else:
        headline_1m = "1min: No significant pattern on the current bar."

    if bos:
        alerts.append(f"⚡ {bos.description}")
    if choch:
        alerts.append(f"⚠ {choch.description}")
    if is_comp:
        alerts.append(f"🔄 Compression — {comp_bars} narrowing bars, breakout imminent")
    for mp in multi_pats:
        if "double" in mp.name:
            alerts.append(f"⚠ {mp.description}")
        elif "flag" in mp.name:
            alerts.append(f"📐 {mp.description}")

    return headline_5m, headline_1m, detail, alerts
