"""
regime_engine.py
Market-environment classification layer.

Phase 4 of the Canonical Implementation Roadmap.

Answers: What kind of market environment are we in right now?

8 regime families:
  1. pinning           — price constrained near dealer-control levels
  2. acceleration      — low gamma void, dealers amplifying movement
  3. breakout          — transitioning from compression to directional expansion
  4. mean_reversion    — rotating back toward central levels
  5. vol_compression   — movement constrained, coiling
  6. vol_expansion     — movement broadening, follow-through likely
  7. trend_continuation — dominant trend intact
  8. reversal_prone    — current move vulnerable to failure

Consumes:
  - SignalInput (levels, Greeks, zone, VIX, candles)
  - RulesCard (micro regime from rules_engine)

Consumed by:
  - prediction_engine.py (trust weighting, horizon emphasis)
  - call_engine.py (trade style, size cues)
  - bayesian_fusion.py (future — prior selection)
  - market_state.py (UI display)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from features.regime_mvp_context import (
    mvp_net_gamma,
    mvp_nearest_distances_for_regime,
    mvp_spot,
    mvp_vwap_side,
    mvp_zone,
    require_mvp_features,
)
from signal_types import SignalInput, RulesCard
from math_levels import is_pin_zone, APPROACH_PTS

log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# OUTPUT
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class RegimePayload:
    """Structured regime classification returned every refresh."""
    primary:                str             # regime label (see REGIMES below)
    secondary_tags:         list            # additional active conditions
    confidence:             str             # 'high', 'medium', 'low'
    confidence_score:       float           # 0.0–1.0
    support_factors:        list            # why this regime
    contradiction_factors:  list            # what weakens it
    summary:                str             # short text for UI / downstream
    scores:                 dict            # raw scores for all 8 families


# ══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ══════════════════════════════════════════════════════════════════════════════

# Regime labels
R_PINNING           = "pinning"
R_ACCELERATION      = "acceleration"
R_BREAKOUT          = "breakout"
R_MEAN_REVERSION    = "mean_reversion"
R_VOL_COMPRESSION   = "vol_compression"
R_VOL_EXPANSION     = "vol_expansion"
R_TREND_CONTINUATION = "trend_continuation"
R_REVERSAL_PRONE    = "reversal_prone"

ALL_REGIMES = [
    R_PINNING, R_ACCELERATION, R_BREAKOUT, R_MEAN_REVERSION,
    R_VOL_COMPRESSION, R_VOL_EXPANSION, R_TREND_CONTINUATION, R_REVERSAL_PRONE,
]

# Secondary tag thresholds
SECONDARY_SCORE_MIN = 3.0     # regime becomes a secondary tag above this
PIN_WIDTH_TIGHT     = 3.0     # pts — pin width considered tight
BALANCED_DIST_RATIO = 0.6     # nearest_above / nearest_below within this ratio → balanced
SMALL_BODY_PCT      = 0.0005  # candle body < 0.05% of spot → small body


# ══════════════════════════════════════════════════════════════════════════════
# MICRO REGIME CONSTANTS (imported lazily to avoid circular deps)
# ══════════════════════════════════════════════════════════════════════════════

def _micro_regimes():
    """Lazy import to avoid circular dependency with micro_structure."""
    from micro_structure import (
        R_TREND_UP, R_TREND_DOWN, R_BOS_UP, R_BOS_DOWN,
        R_CHOCH_BULL, R_CHOCH_BEAR, R_COMPRESSION, R_RANGE,
        R_REVERSAL_UP, R_REVERSAL_DN, R_CHOP,
    )
    return {
        "trend_up": R_TREND_UP, "trend_down": R_TREND_DOWN,
        "bos_up": R_BOS_UP, "bos_down": R_BOS_DOWN,
        "choch_bull": R_CHOCH_BULL, "choch_bear": R_CHOCH_BEAR,
        "compression": R_COMPRESSION, "range": R_RANGE,
        "reversal_up": R_REVERSAL_UP, "reversal_dn": R_REVERSAL_DN,
        "chop": R_CHOP,
    }


# ══════════════════════════════════════════════════════════════════════════════
# SCORING ENGINE
# ══════════════════════════════════════════════════════════════════════════════

def _score_pinning(inp: SignalInput, micro_regime: str, mr: dict, mvp: dict) -> tuple[float, list, list]:
    """Score pinning regime. Returns (score, support_factors, contradiction_factors)."""
    score = 0.0
    support = []
    contra = []

    zone = mvp_zone(mvp)
    if is_pin_zone(zone):
        score += 3.0
        support.append(f"price inside pin zone ({zone})")
    else:
        contra.append("not in pin zone")

    pw = inp.pin_width_pts
    if pw is not None and pw < PIN_WIDTH_TIGHT:
        score += 2.0
        support.append(f"tight pin width ({pw:.1f}pts)")
    elif pw is not None and pw >= PIN_WIDTH_TIGHT:
        contra.append(f"wide pin ({pw:.1f}pts)")

    if micro_regime in (mr["range"], mr["compression"], mr["chop"]):
        score += 2.0
        support.append(f"micro regime = {micro_regime} (non-directional)")

    # Charm attracting toward pin
    _spot = mvp_spot(mvp)
    if inp.charm_direction == "buying" and inp.charm_drift_toward is not None and _spot is not None:
        if inp.charm_drift_toward > _spot:
            score += 1.0
            support.append("charm drifting upward toward pin")
    elif inp.charm_direction == "selling" and inp.charm_drift_toward is not None and _spot is not None:
        if inp.charm_drift_toward < _spot:
            score += 1.0
            support.append("charm drifting downward toward pin")

    # Positive gamma = dealers dampening movement
    ng = mvp_net_gamma(mvp)
    if ng is not None and ng > 0:
        score += 1.0
        support.append("positive gamma — dealers dampening")

    return score, support, contra


def _score_acceleration(inp: SignalInput, micro_regime: str, mr: dict, mvp: dict) -> tuple[float, list, list]:
    """Score acceleration regime — low gamma void, dealers amplifying."""
    score = 0.0
    support = []
    contra = []

    zone = mvp_zone(mvp)

    # Not in pin zone + distance from walls
    if not is_pin_zone(zone):
        dcgw = inp.dist_call_gamma_wall
        dpgw = inp.dist_put_gamma_wall
        far_from_walls = (
            (dcgw is not None and dcgw > APPROACH_PTS * 2) and
            (dpgw is not None and abs(dpgw) > APPROACH_PTS * 2)
        )
        if far_from_walls:
            score += 2.0
            support.append("price far from both gamma walls — low gamma void")
        else:
            contra.append("still near gamma walls")
    else:
        contra.append("in pin zone — not acceleration territory")

    # BOS = structure breaking
    if micro_regime in (mr["bos_up"], mr["bos_down"]):
        score += 3.0
        support.append(f"break of structure ({micro_regime})")

    # Negative gamma = dealers amplifying
    ng = mvp_net_gamma(mvp)
    if ng is not None and ng < 0:
        score += 2.0
        support.append("negative gamma — dealers amplifying movement")
    elif ng is not None and ng > 0:
        contra.append("positive gamma opposes acceleration")

    # VIX elevated supports acceleration
    vb = (inp.vix_bucket or "").lower()
    if "elevated" in vb or "high" in vb:
        score += 1.0
        support.append(f"VIX elevated ({inp.vix_level:.1f})" if inp.vix_level else "VIX elevated")

    return score, support, contra


def _score_breakout(inp: SignalInput, micro_regime: str, mr: dict, mvp: dict) -> tuple[float, list, list]:
    """Score breakout regime — transitioning from compression to expansion."""
    score = 0.0
    support = []
    contra = []

    zone = mvp_zone(mvp)
    prev = (inp.prev_zone or "").lower()

    if zone in ("breakout", "breakdown"):
        score += 3.0
        support.append(f"zone = {zone}")

    if micro_regime in (mr["bos_up"], mr["bos_down"]):
        score += 2.0
        support.append(f"micro confirms structure break ({micro_regime})")

    # Fresh transition from pin → breakout
    if is_pin_zone(prev) and zone in ("breakout", "breakdown"):
        score += 2.0
        support.append(f"breakout from pin zone ({prev} → {zone})")

    # Very recent zone change — execution-layer (1m) recency
    zone_fresh_bars_1m = inp.zone_since_bars_1m
    if zone_fresh_bars_1m is None:
        zone_fresh_bars_1m = inp.zone_since_bars
    if zone_fresh_bars_1m is not None and zone_fresh_bars_1m <= 3 and zone in ("breakout", "breakdown"):
        score += 1.0
        support.append(f"fresh breakout ({zone_fresh_bars_1m} 1m bars ago)")

    if is_pin_zone(zone):
        contra.append("still in pin zone — not breakout")
    if micro_regime in (mr["chop"], mr["range"]):
        contra.append(f"micro = {micro_regime} — no breakout structure")

    return score, support, contra


def _score_mean_reversion(inp: SignalInput, micro_regime: str, mr: dict, mvp: dict) -> tuple[float, list, list]:
    """Score mean reversion — rotating back toward central levels."""
    score = 0.0
    support = []
    contra = []

    zone = mvp_zone(mvp)

    if is_pin_zone(zone) and micro_regime == mr["range"]:
        score += 3.0
        support.append("pin zone + range micro — classic mean reversion")

    # Price near center of levels (balanced above/below distances)
    a_dist, b_dist = mvp_nearest_distances_for_regime(mvp)
    if a_dist is not None and b_dist is not None and a_dist > 0 and b_dist > 0:
        ratio = min(a_dist, b_dist) / max(a_dist, b_dist)
        if ratio >= BALANCED_DIST_RATIO:
            score += 2.0
            support.append(f"balanced level distances (ratio {ratio:.2f})")

    # Low VIX favors mean reversion
    vb = (inp.vix_bucket or "").lower()
    if "low" in vb or "normal" in vb:
        score += 1.0
        support.append("low/normal VIX — supports mean reversion")
    elif "high" in vb or "elevated" in vb:
        contra.append("elevated VIX — expansion more likely than reversion")

    if micro_regime in (mr["bos_up"], mr["bos_down"], mr["trend_up"], mr["trend_down"]):
        contra.append(f"directional micro ({micro_regime}) — not reverting")

    return score, support, contra


def _score_vol_compression(inp: SignalInput, micro_regime: str, mr: dict, mvp: dict) -> tuple[float, list, list]:
    """Score volatility compression — movement constrained, coiling."""
    score = 0.0
    support = []
    contra = []

    if micro_regime == mr["compression"]:
        score += 3.0
        support.append("micro detects compression pattern")

    # Small candle body
    _sp = mvp_spot(mvp)
    if inp.candle_body_pts is not None and _sp is not None and _sp > 0:
        body_pct = inp.candle_body_pts / _sp
        if body_pct < SMALL_BODY_PCT:
            score += 1.5
            support.append(f"small candle body ({body_pct*100:.3f}% of spot)")

    # Low VIX
    vb = (inp.vix_bucket or "").lower()
    if "low" in vb:
        score += 1.0
        support.append("low VIX — compression environment")

    # IV contracting
    if inp.iv_direction == "contracting":
        score += 1.5
        support.append("IV contracting — compression confirmed")
    elif inp.iv_direction == "expanding":
        contra.append("IV expanding — not compression")

    if micro_regime in (mr["bos_up"], mr["bos_down"], mr["trend_up"], mr["trend_down"]):
        contra.append(f"directional micro ({micro_regime}) — not compressed")

    return score, support, contra


def _score_vol_expansion(inp: SignalInput, micro_regime: str, mr: dict, mvp: dict) -> tuple[float, list, list]:
    """Score volatility expansion — movement broadening."""
    score = 0.0
    support = []
    contra = []

    # VIX elevated
    vb = (inp.vix_bucket or "").lower()
    if "high" in vb:
        score += 2.5
        support.append(f"VIX high ({inp.vix_level:.1f})" if inp.vix_level else "VIX high")
    elif "elevated" in vb:
        score += 1.5
        support.append(f"VIX elevated ({inp.vix_level:.1f})" if inp.vix_level else "VIX elevated")

    # IV expanding
    if inp.iv_direction == "expanding":
        score += 2.0
        support.append("IV expanding")
    elif inp.iv_direction == "contracting":
        contra.append("IV contracting — not expanding")

    # Directional micro supports expansion
    if micro_regime in (mr["bos_up"], mr["bos_down"], mr["trend_up"], mr["trend_down"]):
        score += 1.0
        support.append(f"directional micro supports expansion ({micro_regime})")

    if micro_regime in (mr["compression"], mr["chop"]):
        contra.append(f"micro = {micro_regime} — not expanding yet")

    return score, support, contra


def _score_trend_continuation(inp: SignalInput, micro_regime: str, mr: dict,
                               rules: RulesCard, mvp: dict) -> tuple[float, list, list]:
    """Score trend continuation — dominant trend intact."""
    score = 0.0
    support = []
    contra = []

    if micro_regime in (mr["trend_up"], mr["trend_down"]):
        score += 3.0
        support.append(f"micro confirms trend ({micro_regime})")

    # Rules conviction alignment
    if rules.conviction in ("high", "medium") and rules.signal in ("long", "short"):
        score += 2.0
        support.append(f"rules bias = {rules.signal} ({rules.conviction} conviction)")
    elif rules.signal == "wait":
        contra.append("rules see no directional setup")

    # VWAP alignment with signal direction
    vs = mvp_vwap_side(mvp)
    sig = rules.signal
    if (sig == "long" and vs == "above") or (sig == "short" and vs == "below"):
        score += 1.0
        support.append(f"VWAP side ({vs}) aligned with {sig} lean")
    elif (sig == "long" and vs and vs != "above") or (sig == "short" and vs and vs != "below"):
        contra.append(f"VWAP side ({vs}) conflicts with {sig} lean")

    if micro_regime in (mr["reversal_up"], mr["reversal_dn"], mr["choch_bull"], mr["choch_bear"]):
        contra.append(f"micro shows reversal signal ({micro_regime})")

    return score, support, contra


def _score_reversal_prone(inp: SignalInput, micro_regime: str, mr: dict,
                           rules: RulesCard, mvp: dict) -> tuple[float, list, list]:
    """Score reversal-prone — current move vulnerable to failure."""
    score = 0.0
    support = []
    contra = []

    if micro_regime in (mr["reversal_up"], mr["reversal_dn"]):
        score += 3.0
        support.append(f"micro confirms reversal ({micro_regime})")
    elif micro_regime in (mr["choch_bull"], mr["choch_bear"]):
        score += 2.0
        support.append(f"change of character detected ({micro_regime})")

    # Approaching opposing wall
    dcgw = inp.dist_call_gamma_wall
    dpgw = inp.dist_put_gamma_wall
    if dcgw is not None and 0 < dcgw <= APPROACH_PTS:
        score += 2.0
        support.append(f"approaching call gamma wall ({dcgw:.1f}pts away)")
    if dpgw is not None and 0 < abs(dpgw) <= APPROACH_PTS:
        score += 2.0
        support.append(f"approaching put gamma wall ({abs(dpgw):.1f}pts away)")

    # Low rules conviction
    if rules.conviction == "low":
        score += 1.0
        support.append("rules engine has low conviction")

    if micro_regime in (mr["trend_up"], mr["trend_down"], mr["bos_up"], mr["bos_down"]):
        contra.append(f"strong directional micro ({micro_regime}) opposes reversal")

    return score, support, contra


# ══════════════════════════════════════════════════════════════════════════════
# SUMMARIES
# ══════════════════════════════════════════════════════════════════════════════

_REGIME_SUMMARIES = {
    R_PINNING:          "Pinning conditions dominant — price constrained near dealer-control levels. Fade edges, expect chop.",
    R_ACCELERATION:     "Low gamma void — dealers amplifying movement. Expect fast directional follow-through.",
    R_BREAKOUT:         "Breakout in progress — structure transitioning from compression to directional expansion.",
    R_MEAN_REVERSION:   "Mean reversion favored — price rotating back toward central levels.",
    R_VOL_COMPRESSION:  "Volatility compressed — coiling for a move. Wait for the breakout candle.",
    R_VOL_EXPANSION:    "Volatility expanding — broader moves likely. Adjust stops and size accordingly.",
    R_TREND_CONTINUATION: "Trend intact — continuation more likely than reversal. Trade with the trend.",
    R_REVERSAL_PRONE:   "Reversal risk elevated — current move vulnerable to failure or fade.",
}


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ══════════════════════════════════════════════════════════════════════════════

def classify_regime(
    inp: SignalInput,
    rules: RulesCard,
    *,
    mvp_features: dict,
) -> RegimePayload:
    """
    Classify the current market environment.

    Called after rules_engine.py runs (needs micro regime from RulesCard).
    Called before prediction_engine.py and call_engine.py so they can
    adjust behavior based on regime.

    Args:
        inp:   SignalInput with all current market data
        rules: RulesCard from rules_engine (provides micro regime)
        mvp_features: Canonical MVP row (``inference_snapshot_v1["features"]``) — required.
            Structure / anchor / price fields for scoring use this row only.

    Returns:
        RegimePayload with primary regime, secondary tags, confidence,
        and supporting/contradicting evidence.
    """
    mvp = require_mvp_features(mvp_features, context="classify_regime")

    try:
        mr = _micro_regimes()
    except ImportError:
        log.warning("regime_engine: micro_structure not available — returning unknown")
        return _unknown_regime()

    # Get micro regime from the RulesCard's micro object
    micro = getattr(rules, "micro", None)
    micro_regime = getattr(micro, "regime", "UNKNOWN") if micro else "UNKNOWN"

    # ── Score all 8 regime families ───────────────────────────────────────────
    scores = {}
    all_support = {}
    all_contra = {}

    s, sup, con = _score_pinning(inp, micro_regime, mr, mvp)
    scores[R_PINNING] = s; all_support[R_PINNING] = sup; all_contra[R_PINNING] = con

    s, sup, con = _score_acceleration(inp, micro_regime, mr, mvp)
    scores[R_ACCELERATION] = s; all_support[R_ACCELERATION] = sup; all_contra[R_ACCELERATION] = con

    s, sup, con = _score_breakout(inp, micro_regime, mr, mvp)
    scores[R_BREAKOUT] = s; all_support[R_BREAKOUT] = sup; all_contra[R_BREAKOUT] = con

    s, sup, con = _score_mean_reversion(inp, micro_regime, mr, mvp)
    scores[R_MEAN_REVERSION] = s; all_support[R_MEAN_REVERSION] = sup; all_contra[R_MEAN_REVERSION] = con

    s, sup, con = _score_vol_compression(inp, micro_regime, mr, mvp)
    scores[R_VOL_COMPRESSION] = s; all_support[R_VOL_COMPRESSION] = sup; all_contra[R_VOL_COMPRESSION] = con

    s, sup, con = _score_vol_expansion(inp, micro_regime, mr, mvp)
    scores[R_VOL_EXPANSION] = s; all_support[R_VOL_EXPANSION] = sup; all_contra[R_VOL_EXPANSION] = con

    s, sup, con = _score_trend_continuation(inp, micro_regime, mr, rules, mvp)
    scores[R_TREND_CONTINUATION] = s; all_support[R_TREND_CONTINUATION] = sup; all_contra[R_TREND_CONTINUATION] = con

    s, sup, con = _score_reversal_prone(inp, micro_regime, mr, rules, mvp)
    scores[R_REVERSAL_PRONE] = s; all_support[R_REVERSAL_PRONE] = sup; all_contra[R_REVERSAL_PRONE] = con

    # ── Determine primary regime (highest score) ──────────────────────────────
    primary_score = max(scores.values()) if scores else 0.0
    if primary_score <= 0:
        return _unknown_regime()

    primary = max(scores, key=scores.get)

    # ── Secondary tags: any regime above threshold (excluding primary) ─────────
    secondary_tags = [r for r in ALL_REGIMES
                      if r != primary and scores[r] >= SECONDARY_SCORE_MIN]

    # ── Confidence from primary score and gap to runner-up ────────────────────
    sorted_scores = sorted(scores.values(), reverse=True)
    gap = sorted_scores[0] - sorted_scores[1] if len(sorted_scores) > 1 else sorted_scores[0]

    if primary_score >= 6.0 and gap >= 2.0:
        confidence = "high"
        confidence_score = min(1.0, primary_score / 10.0)
    elif primary_score >= 4.0 and gap >= 1.0:
        confidence = "medium"
        confidence_score = min(0.8, primary_score / 10.0)
    else:
        confidence = "low"
        confidence_score = min(0.5, primary_score / 10.0)

    summary = _REGIME_SUMMARIES.get(primary, f"Regime: {primary}")

    return RegimePayload(
        primary=primary,
        secondary_tags=secondary_tags,
        confidence=confidence,
        confidence_score=round(confidence_score, 2),
        support_factors=all_support.get(primary, []),
        contradiction_factors=all_contra.get(primary, []),
        summary=summary,
        scores={k: round(v, 1) for k, v in scores.items()},
    )


def _unknown_regime() -> RegimePayload:
    """Fallback when classification can't run."""
    return RegimePayload(
        primary="unknown",
        secondary_tags=[],
        confidence="low",
        confidence_score=0.0,
        support_factors=[],
        contradiction_factors=["regime engine could not classify"],
        summary="Regime unknown — insufficient data for classification.",
        scores={r: 0.0 for r in ALL_REGIMES},
    )


# ══════════════════════════════════════════════════════════════════════════════
# SELF-TEST
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("regime_engine.py — self-test")
    print(f"  Regime families: {ALL_REGIMES}")
    print(f"  Secondary threshold: {SECONDARY_SCORE_MIN}")
    payload = _unknown_regime()
    print(f"  Unknown fallback: primary={payload.primary}, confidence={payload.confidence}")
    print("  OK")
