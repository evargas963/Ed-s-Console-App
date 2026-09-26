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

CANDLE_1M_MAX_BARS: int = 390  # 1-day 1m from Schwab; LSTM needs 20



# composite <= -0.25 → "SELLING PRESSURE"












# RETIRED (mission TRUTH_V1, RC-473/RC-474): compute_order_flow_verdict was DELETED. It
# STRUCTURALLY DOUBLE-COUNTED — `score` already contained book/cum-delta/options, then the verdict
# re-added book, sign(cum-delta) and options over arbitrary unvalidated weights to emit the false
# operator claim BUYING/SELLING PRESSURE. It had no measurable semantic and no OOS validation, so it
# is removed, not repaired. No executable path reconstructs it (locked by the order-flow tests).












# ── Formatting helpers (owned by this file per Extraction Blueprint) ──────────




# ── Re-export everything from split modules ───────────────────────────────────

from math_exposure_core import *                                               # noqa: F401,F403
from math_levels import *                                                      # noqa: F401,F403
from math_volatility import *                                                  # noqa: F401,F403
from math_probabilities import *                                               # noqa: F401,F403

# Underscore names are excluded from import * — re-export explicitly
from math_exposure_core import (                                               # noqa: F401
    MISSING_GREEK_SENTINEL,
    greek_reported,
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
