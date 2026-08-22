"""
math_exposure.py
Re-export facade for the four split math modules.

Phase 2 split the original monolith into:
  math_exposure_core.py    — Greeks, beta, charm, greek_bias
  math_levels.py           — walls, pins, inflections, key levels
  math_volatility.py       — IV, expected move, session/VIX context
  math_probabilities.py    — probability, confidence, scoring helpers

This file re-exports everything so all existing imports continue to work:
    from math_exposure import compute_exposures_by_strike, build_walls_rows, ...
"""
from __future__ import annotations

# ── Candle lookback (centralized for server + all consumers) ───────────────────
# Required by downstream: LSTM (60/20), GARCH (>20), ATR (15), micro (12).
# Must be >= Schwab 1-day seed sizes so seeded data is not truncated.
CANDLE_5M_MAX_BARS: int = 78   # 1-day 5m from Schwab; LSTM needs 60, GARCH ~30
CANDLE_1M_MAX_BARS: int = 390  # 1-day 1m from Schwab; LSTM needs 20


# ── Order Flow Verdict (composite headline) ───────────────────────────────────
# Used by order_flow_engine + frontend for Flow Verdict headline.
OF_VERDICT_W_SCORE: float = 0.40
OF_VERDICT_W_BOOK:  float = 0.25
OF_VERDICT_W_CUM:   float = 0.20
OF_VERDICT_W_OPT:   float = 0.15

OF_VERDICT_BUYING:      float = 0.25   # composite >= this → "BUYING PRESSURE"
OF_VERDICT_MILD_BUY:    float = 0.10   # composite >= this → "MILD BUY FLOW"
OF_VERDICT_NEUTRAL_HI:  float = -0.10  # composite > this → "FLOW NEUTRAL"
OF_VERDICT_MILD_SELL:   float = -0.25  # composite > this → "MILD SELL FLOW"
# composite <= -0.25 → "SELLING PRESSURE"

# Field label thresholds (plain-english labels for Score, Book Imb, Opt Flow)
OF_SCORE_BULLISH:   float = 0.10   # score > this → bullish
OF_SCORE_BEARISH:   float = -0.10  # score < this → bearish

OF_BOOK_BID_HEAVY:  float = 0.05   # book_imb > this → bid-heavy
OF_BOOK_ASK_HEAVY:  float = -0.05  # book_imb < this → ask-heavy

OF_OPT_CALL_HEAVY:  float = 0.05   # opt_flow > this → call-heavy
OF_OPT_PUT_HEAVY:   float = -0.05  # opt_flow < this → put-heavy

# Fusion posterior gate thresholds (call_engine._validate_trade 2c)
# Only meaningful posteriors block; low values (0.01) should not trigger.
CONTINUATION_BLOCK_THRESHOLD: float = 0.45
BREAKOUT_BLOCK_THRESHOLD: float = 0.45


def _of_sign(v: float | None) -> float | None:
    """Return -1 or +1 based on sign of v (for cum_delta in verdict). None when missing or exactly zero."""
    if v is None:
        return None
    try:
        f = float(v)
        if f == 0.0:
            return None
        return 1.0 if f > 0 else -1.0
    except (TypeError, ValueError):
        return None


def _of_direction(v: float | None) -> str | None:
    """Return 'bullish', 'bearish', or 'neutral' for arrow/label; None when input missing or exactly zero."""
    if v is None:
        return None
    try:
        f = float(v)
        if f == 0.0:
            return None
        if f > OF_SCORE_BULLISH:
            return "bullish"
        if f < OF_SCORE_BEARISH:
            return "bearish"
    except (TypeError, ValueError):
        return None
    return "neutral"


def _verdict_unavailable() -> dict:
    return {
        "verdict": None,
        "verdict_color": None,
        "arrow": None,
        "agreement": "unavailable",
    }


# RETIRED (mission TRUTH_V1, RC-450/RC-451): compute_order_flow_verdict was DELETED. It
# STRUCTURALLY DOUBLE-COUNTED — `score` already contained book/cum-delta/options, then the verdict
# re-added book, sign(cum-delta) and options over arbitrary unvalidated weights to emit the false
# operator claim BUYING/SELLING PRESSURE. It had no measurable semantic and no OOS validation, so it
# is removed, not repaired. No executable path reconstructs it (locked by the order-flow tests).


def _book_direction(v: float | None) -> str | None:
    """Return bid-heavy, ask-heavy, or neutral for book imbalance; None when input missing."""
    if v is None:
        return None
    try:
        f = float(v)
        if f > OF_BOOK_BID_HEAVY:
            return "bullish"
        if f < OF_BOOK_ASK_HEAVY:
            return "bearish"
    except (TypeError, ValueError):
        return None
    return "neutral"


def order_flow_score_label(score: float | None) -> str | None:
    """Plain-english label for score."""
    d = _of_direction(score)
    if d is None:
        return None
    return "bullish" if d == "bullish" else ("bearish" if d == "bearish" else "neutral")


def order_flow_book_label(book_imb: float | None) -> str | None:
    """Plain-english label for book imbalance."""
    if book_imb is None:
        return None
    try:
        f = float(book_imb)
        if f > OF_BOOK_BID_HEAVY:
            return "bid-heavy"
        if f < OF_BOOK_ASK_HEAVY:
            return "ask-heavy"
    except (TypeError, ValueError):
        return None
    return "balanced"


def order_flow_opt_label(opt_flow: float | None) -> str | None:
    """Plain-english label for options flow."""
    if opt_flow is None:
        return None
    try:
        f = float(opt_flow)
        if f > OF_OPT_CALL_HEAVY:
            return "call-heavy"
        if f < OF_OPT_PUT_HEAVY:
            return "put-heavy"
    except (TypeError, ValueError):
        return None
    return "neutral"


def order_flow_field_arrow(val: float | None, *, use_book: bool = False) -> str | None:
    """Return ▲, ▼, or → for a single field; None when input missing."""
    if use_book:
        d = _book_direction(val)
    else:
        d = _of_direction(val)
    if d is None:
        return None
    return "▲" if d == "bullish" else ("▼" if d == "bearish" else "→")


# ── Formatting helpers (owned by this file per Extraction Blueprint) ──────────

def fmt_money(x: "float | None", *, signed: bool = True) -> str:
    if x is None: return "N/A"
    try: x = float(x)
    except Exception: return "N/A"
    sgn = "-" if x < 0 else ("+" if signed and x > 0 else "")
    v = abs(x)
    if v >= 1e9: return f"{sgn}${v/1e9:.2f}B"
    if v >= 1e6: return f"{sgn}${v/1e6:.2f}M"
    if v >= 1e3: return f"{sgn}${v/1e3:.1f}K"
    return f"{sgn}${v:.0f}"

def fmt_money_gex(x: "float | None") -> str:
    return fmt_money(x)


# ── Re-export everything from split modules ───────────────────────────────────

from math_exposure_core import *                                               # noqa: F401,F403
from math_levels import *                                                      # noqa: F401,F403
from math_volatility import *                                                  # noqa: F401,F403
from math_probabilities import *                                               # noqa: F401,F403

# Underscore names are excluded from import * — re-export explicitly
from math_exposure_core import (                                               # noqa: F401
    MISSING_GREEK_SENTINEL,
    gamma_is_plausible,
    _f,
    _nearest_strike,
    _window_strikes,
    _strike_bucket,
)
from math_levels import (                                                      # noqa: F401
    _pick_oi_center, _pick_inflection_closest_zero,
    _pin_strength, _bias_from_net, _dominant,
)
from math_volatility import _spot_atm_strike, _extract_iv_for_strike          # noqa: F401
from math_probabilities import _binomial_p_value                              # noqa: F401
