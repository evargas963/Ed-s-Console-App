"""
call_engine.py
The Call — implements STACK ORDER 8, 9, 10 (enforced in compute_call):
  8. Decision Policy Layer: signal, conviction, trade interpretation (uses vol_regime)
  9. Risk Engine: _validate_trade (structure, probability, risk gates)
 10. Position Sizing: compute_position_size (r_units, execution_mode)
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from lifecycle_rule_core import derive_stop_distance_pct, derive_target_levels
from multi_horizon_decision import MultiHorizonSynthesis
from datetime import timezone, timedelta

from math_exposure import (
    greek_bias,
    is_pin_zone,
    CONTINUATION_BLOCK_THRESHOLD,
    BREAKOUT_BLOCK_THRESHOLD,
)
from signal_types import SignalInput, RulesCard, PredictiveCard, TheCall, CanonicalForecast

log = logging.getLogger(__name__)
ET = timezone(timedelta(hours=-5))


def _mh_size_tier_from_modifier(mh_mod: float) -> int:
    if mh_mod <= 0.30:
        return 3
    if mh_mod <= 0.45:
        return 2
    if mh_mod <= 0.80:
        return 1
    return 0


def _size_cue_tier(cue: str) -> int:
    c = (cue or "FULL").strip().upper()
    if c == "SKIP":
        return 3
    if c == "QUARTER":
        return 2
    if c == "HALF":
        return 1
    return 0


def _tier_to_size_cue(tier: int) -> str:
    if tier >= 3:
        return "SKIP"
    if tier == 2:
        return "QUARTER"
    if tier == 1:
        return "HALF"
    return "FULL"


def _merge_size_cue_with_mh(base_cue: str, mh_modifier: float) -> str:
    """More conservative of base position sizing and multi-horizon sizing_modifier."""
    t = max(_size_cue_tier(base_cue), _mh_size_tier_from_modifier(mh_modifier))
    return _tier_to_size_cue(t)

TRADE_TYPE_LABELS = {
    "trend_continuation": "trend continuation",
    "breakout":           "breakout",
    "reversal":           "reversal",
    "fade":               "fade",
    "mean_reversion":     "mean reversion",
    "none":               "no setup",
}

def _classify_trade_type(micro_regime: str, zone: str, signal: str) -> str:
    """Classify the trade type from micro regime + zone context."""
    from micro_structure import (
        R_TREND_UP, R_TREND_DOWN, R_BOS_UP, R_BOS_DOWN,
        R_CHOCH_BULL, R_CHOCH_BEAR, R_COMPRESSION, R_RANGE,
        R_REVERSAL_UP, R_REVERSAL_DN, R_CHOP,
    )

    if signal == "wait":
        return "none"

    # Trend continuation: micro says trending + signal follows the trend
    if micro_regime in (R_TREND_UP, R_TREND_DOWN):
        return "trend_continuation"

    # BOS: break of structure continuation
    if micro_regime in (R_BOS_UP, R_BOS_DOWN):
        return "breakout"

    # Reversal / CHoCH
    if micro_regime in (R_REVERSAL_UP, R_REVERSAL_DN, R_CHOCH_BULL, R_CHOCH_BEAR):
        return "reversal"

    # Range + pin zone = fade the wall
    if micro_regime == R_RANGE and is_pin_zone(zone):
        return "fade"

    # Range not at wall = mean reversion
    if micro_regime == R_RANGE:
        return "mean_reversion"

    # Compression: waiting for direction, but if forced to trade
    if micro_regime == R_COMPRESSION:
        return "breakout"

    return "none"

def _build_invalidation(micro, micro_regime, final_signal, trade_type, stop, inp) -> str:
    """Build plain English invalidation reason."""
    from micro_structure import (
        R_TREND_UP, R_TREND_DOWN, R_BOS_UP, R_BOS_DOWN,
        R_CHOCH_BULL, R_CHOCH_BEAR, R_COMPRESSION, R_RANGE,
        R_REVERSAL_UP, R_REVERSAL_DN,
    )

    if final_signal == "wait" or stop is None:
        return ""

    parts = []

    # Structural invalidation from micro
    if micro:
        if final_signal == "long" and micro.structure_support:
            parts.append(f"Invalid if 5min closes below {micro.structure_support:.2f} swing low")
        elif final_signal == "short" and micro.structure_resist:
            parts.append(f"Invalid if 5min closes above {micro.structure_resist:.2f} swing high")

    # Trade-type specific invalidation
    if trade_type == "fade":
        if final_signal == "short" and inp.call_gamma_wall:
            parts.append(f"Invalid if price holds above {inp.call_gamma_wall:.2f} for 3+ bars")
        elif final_signal == "long" and inp.put_gamma_wall:
            parts.append(f"Invalid if price holds below {inp.put_gamma_wall:.2f} for 3+ bars")
    elif trade_type == "breakout" and micro_regime in (R_BOS_UP, R_BOS_DOWN):
        if micro and micro.bos:
            parts.append(f"Invalid if price falls back below {micro.bos.level:.2f} breakout level")

    # Fallback: just the stop
    if not parts and stop:
        parts.append(f"Stop at {stop:.2f}")

    return ". ".join(parts) + "." if parts else ""

def _time_qualifier(micro_regime: str, trade_type: str) -> str:
    """How long is this setup valid?"""
    from micro_structure import R_COMPRESSION, R_RANGE, R_CHOP

    if trade_type == "none":
        return ""

    if micro_regime == R_COMPRESSION:
        return "Setup valid ~10-15min — expires if no breakout candle."
    if trade_type == "fade":
        return "Setup valid while price stays near the wall."
    if trade_type == "breakout":
        return "Setup valid ~15min — watch for follow-through or failure."
    if trade_type == "reversal":
        return "Setup valid ~20min — needs confirming bar to stay active."
    if trade_type == "trend_continuation":
        return "Setup valid while trend structure holds."
    if micro_regime == R_RANGE:
        return "Setup valid while range holds."

    return ""


def replay_max_hold_bars_for_setup(micro_regime: str, trade_type: str) -> int:
    """
    Max 1m bars for historical replay time_expiry — branches stay aligned with _time_qualifier().
    Canonical 1m snapshots: one bar ≈ one minute of RTH cadence in the training table.
    """
    from micro_structure import R_COMPRESSION, R_RANGE

    if trade_type == "none":
        return 0
    if micro_regime == R_COMPRESSION:
        return 15
    if trade_type == "fade":
        return 30
    if trade_type == "breakout":
        return 15
    if trade_type == "reversal":
        return 20
    if trade_type == "trend_continuation":
        return 60
    if trade_type == "mean_reversion":
        return 30
    if micro_regime == R_RANGE:
        return 30
    return 30

def _mc_reasoning_snippet(fusion, final_signal: str) -> str:
    """Build Monte Carlo snippet for call reasoning when MC is available and relevant."""
    if not fusion or not getattr(fusion, 'mc_available', False):
        return ""
    cont = getattr(fusion, 'mc_containment', None)
    exp = getattr(fusion, 'mc_expansion', None)
    sim_up = getattr(fusion, 'mc_sim_prob_up', None)  # may not be on fusion
    sim_dn = getattr(fusion, 'mc_sim_prob_down', None)
    # Fusion gets MC from bayesian_fusion which passes mc_out — fusion doesn't have sim_prob_*
    # We get mc_containment, mc_expansion from fusion. For directional: use fusion_dominant_direction
    # vs call. MC contributes containment/expansion to fusion evidence.
    mode = "expansion" if (exp or 0) >= (cont or 0) else "containment"
    pct = int(100 * (exp if (exp or 0) >= (cont or 0) else cont) or 0)
    # Directional: fusion has dominant_direction; MC's path outcomes inform fusion
    # Simple: state MC mode and whether it supports directional trade
    if final_signal == "wait":
        return f" Monte Carlo: {mode} bias ({pct}%)."
    # For long/short: containment favors range, expansion favors breakout
    if mode == "containment" and pct > 50:
        return f" Monte Carlo: {pct}% containment — range likely, favor fades."
    if mode == "expansion" and pct > 50:
        return f" Monte Carlo: {pct}% expansion — breakout environment supports direction."
    return f" Monte Carlo: {mode} {pct}%."


def _build_call_headlines(final_signal, conviction, trade_type,
                           entry, stop, target, target2,
                           confluence_count, confluence_total, confluence_detail,
                           micro_regime, rules, pred, pred_agrees,
                           fusion=None, wait_blocker: dict = None) -> tuple[str, str]:
    """Build headline and reasoning for The Call card. Driven by full stack result.
    wait_blocker: when final_signal=wait, dict with reason ('stack'|'vol_regime'|'gates'|'time'),
    and optional long_count, short_count, threshold, gate_reasons, vol_detail, detail, full_detail.
    """
    type_label = TRADE_TYPE_LABELS.get(trade_type, trade_type)

    if final_signal == "wait":
        blocker = wait_blocker or {}
        reason = blocker.get("reason", "unknown")
        if reason == "stack":
            lc = blocker.get("long_count", 0)
            sc = blocker.get("short_count", 0)
            th = blocker.get("threshold", 2)
            ln = blocker.get("long_names", [])
            sn = blocker.get("short_names", [])
            headline = f"WAIT — stack: {lc} long, {sc} short (need {th}+ in one direction)."
            reasoning = (
                f"Stack: {lc} long ({', '.join(ln) or '—'}), {sc} short ({', '.join(sn) or '—'}). "
                f"Need at least {th} sources agreeing. "
                "Note: stack uses 9 layers (micro, Greeks, spy_basket, qqq_basket, iwm_basket, regime, fusion, order_flow, multi_horizon); "
                "each index basket vote is independent — no cross-ETF veto. "
                "'5 of 5 agree' in fusion is model agreement inside fusion — separate from these votes."
            )
        elif reason == "vol_regime":
            detail = blocker.get("detail", "unstable — require stronger confirmation")
            headline = f"WAIT — vol regime: {detail}."
            reasoning = blocker.get("full_detail", detail)
        elif reason == "gates":
            gate_reasons = blocker.get("gate_reasons", [])
            headline = f"WAIT — gated: {', '.join(gate_reasons) if gate_reasons else 'validation failed'}."
            reasoning = f"Validation gates: {'; '.join(gate_reasons)}."
        elif reason == "time":
            detail = blocker.get("detail", "≤30 min to close")
            headline = f"WAIT — {detail}."
            reasoning = blocker.get("full_detail", f"Only {detail} — no new entries.")
        else:
            headline = "WAIT — insufficient confirmation."
            reasoning = confluence_detail or "Await stronger stack consensus or key level."
        return headline, reasoning

    dir_word = "LONG" if final_signal == "long" else "SHORT"

    # Entry/target strings
    e_s  = f"{entry:.2f}"  if entry  else "—"
    t1_s = f"{target:.2f}" if target else "—"

    headline = f"{dir_word} — {type_label}"
    if entry:
        headline += f". Entry {e_s}"
    if stop:
        headline += f", stop {stop:.2f}"

    # Reasoning based on confluence
    if confluence_count >= 3:
        reasoning = (
            f"{confluence_count} of {confluence_total} aligned: {confluence_detail}. "
            f"High conviction — {type_label} setup with multiple confirmations."
        )
    elif confluence_count >= 2:
        reasoning = (
            f"{confluence_count} of {confluence_total} aligned: {confluence_detail}. "
            f"Solid setup — trade with confidence but manage risk."
        )
    elif confluence_count == 1:
        reasoning = (
            f"Only {confluence_count} of {confluence_total} aligned: {confluence_detail}. "
            f"{'Forward stack disagrees — trade smaller. ' if not pred_agrees and pred.forward_confidence != 'low' else ''}"
            f"Wait for more confirmation or reduce size."
        )
    else:
        reasoning = "No signals aligned — skip this one."

    mc_snippet = _mc_reasoning_snippet(fusion, final_signal)
    if mc_snippet:
        reasoning = reasoning.rstrip(". ") + mc_snippet

    return headline, reasoning

def _greek_notes(inp: SignalInput) -> list:
    """Translate key Greeks into plain English bullet notes."""
    notes = []

    if inp.net_gamma is not None:
        if inp.net_gamma > 0:
            notes.append("Dealers are absorbing moves — chop/fade mode")
        else:
            notes.append("Dealers are amplifying moves — trend/momentum mode")

    if inp.charm_direction and inp.charm_drift_toward:
        notes.append(f"Time decay pushing dealers to {inp.charm_direction} toward {inp.charm_drift_toward:.2f}")

    if inp.iv_direction == "expanding":
        notes.append("Volatility rising — moves may be larger than expected")
    elif inp.iv_direction == "contracting":
        notes.append("Volatility falling — moves may be smaller than expected")

    if inp.vix_level and inp.vix_level > 25:
        notes.append(f"VIX at {inp.vix_level:.1f} — high vol, widen stops")

    return notes

def _add_greek_color(detail: str, greek_notes: list) -> str:
    """Append the most relevant Greek note to a detail string."""
    if greek_notes:
        return detail + " " + greek_notes[0] + "."
    return detail

def _canonical_stack_vote(canonical: CanonicalForecast) -> int:
    """Stack vote from CanonicalForecast only (fusion forward triplet — Issue 13)."""
    pred_dir = str(getattr(canonical, "direction", "") or "").strip().lower()
    pred_conf = str(getattr(canonical, "confidence", "") or "").strip().lower()
    try:
        dom_p = float(canonical.dominant_probability())
    except (TypeError, ValueError):
        dom_p = 0.0
    if pred_dir == "up":
        if pred_conf != "low" or dom_p >= 0.45:
            return 1
    elif pred_dir == "down":
        if pred_conf != "low" or dom_p >= 0.45:
            return -1
    return 0


def _fusion_authoritative_directional_vote(
    fusion_available: bool, fusion_dom_vote: int, canonical: CanonicalForecast
) -> int:
    """
    Single model-direction slot: live fusion dominant when non-flat; else canonical weak-lean
    (same lane as former duplicate 'prediction' + redundant fusion when both matched).
    """
    if fusion_available and fusion_dom_vote != 0:
        return fusion_dom_vote
    return _canonical_stack_vote(canonical)


def _index_basket_vote(
    weighted_push: float | None,
    etf_chg_pct: float | None,
    *,
    min_lean: float = 0.08,
) -> int:
    """
    One index, one vote: cap-weighted basket push if present, else that index's ETF session %.
    No other instrument can veto this vote (cross-ETF veto removed by policy).
    Returns: 1 (long lean), -1 (short lean), 0 (flat / insufficient lean).
    """
    if weighted_push is not None:
        try:
            p = float(weighted_push)
            if p > min_lean:
                return 1
            if p < -min_lean:
                return -1
        except (TypeError, ValueError):
            pass
    try:
        c = float(etf_chg_pct or 0.0)
    except (TypeError, ValueError):
        return 0
    if c > min_lean:
        return 1
    if c < -min_lean:
        return -1
    return 0


def _cross_instrument_signal(inp: SignalInput) -> str:
    """
    Continuous cross-instrument alignment score for **narrative / notes** only
    (e.g. `_cross_instrument_notes`, regime copy) — **not** used for stack_vote;
    see `_index_basket_vote` (three independent index votes) for The Call tape layer.

    Treats direction agreement × magnitude across SPY, QQQ, IWM. Full agreement is
    a strong contextual label; divergence is a warning in text — not a hard gate.
    """
    spy = inp.spy_chg_pct or 0.0
    qqq = inp.qqq_chg_pct or 0.0
    iwm = inp.iwm_chg_pct or 0.0

    # All three directions (chg_pct is in percentage points, e.g. -1.65 = -1.65%)
    dirs = []
    for v in (spy, qqq, iwm):
        if v > 0.1:    dirs.append(1)     # > +0.1%
        elif v < -0.1: dirs.append(-1)    # < -0.1%
        else:          dirs.append(0)

    # Agreement: do they all point the same way?
    nonzero = [d for d in dirs if d != 0]
    if len(nonzero) < 2:
        return "neutral"  # not enough movement to judge

    all_same = len(set(nonzero)) == 1
    has_conflict = 1 in nonzero and -1 in nonzero

    # Magnitude: average absolute move across instruments (in pct points)
    avg_mag = (abs(spy) + abs(qqq) + abs(iwm)) / 3.0
    STRONG_THRESHOLD = 0.40   # 0.4% average move = strong signal
    WEAK_THRESHOLD   = 0.10   # 0.1% average move = barely moving

    if has_conflict:
        return "strong_diverge" if avg_mag >= STRONG_THRESHOLD else "diverging"
    elif all_same:
        return "strong_confirm" if avg_mag >= STRONG_THRESHOLD else "confirming"
    return "neutral"

def _cross_instrument_notes(inp: SignalInput) -> list:
    """Plain English notes from cross-instrument reads with magnitude context."""
    notes = []

    spy = inp.spy_chg_pct or 0.0
    qqq = inp.qqq_chg_pct or 0.0
    iwm = inp.iwm_chg_pct or 0.0

    # QQQ vs SPY — magnitude matters (values in percentage points)
    delta = qqq - spy
    if abs(delta) > 0.20:  # meaningful divergence (0.2% spread)
        if delta > 0:
            notes.append(f"QQQ leading SPY by {abs(delta):.2f}% — tech pulling market up")
        else:
            notes.append(f"QQQ lagging SPY by {abs(delta):.2f}% — tech is a drag")

    # IWM — risk appetite with magnitude
    if iwm < -0.50:
        notes.append(f"Small caps down {abs(iwm):.2f}% — risk-off, be careful with longs")
    elif iwm > 0.50:
        notes.append(f"Small caps up {iwm:.2f}% — risk-on, longs favored")

    # All three aligned strongly
    cross_sig = _cross_instrument_signal(inp)
    if cross_sig == "strong_confirm":
        avg_dir = "bullish" if (spy + qqq + iwm) > 0 else "bearish"
        notes.append(f"SPY/QQQ/IWM all moving strongly {avg_dir} — broad market conviction")
    elif cross_sig in ("diverging", "strong_diverge"):
        notes.append("Index instruments diverging — mixed signals, reduce sizing")

    return notes

def _stop_distance(inp: SignalInput, risk_multiplier: float = 1.0) -> float:
    """
    Time-aware, VIX-aware stop distance for 0DTE trading.
    PERCENTAGE-BASED so it scales correctly across underlyings.

    risk_multiplier: from volatility regime — scales stop in expansion/unstable
    (e.g. 1.35 in unstable = wider stops). Default 1.0.
    """
    spot = inp.spot
    mins_elapsed = inp.et_hour * 60 + inp.et_minute - 570  # mins since 9:30 AM
    mins_elapsed = max(0, mins_elapsed)

    stop_distance = derive_stop_distance_pct(
        spot=spot,
        vix_level=inp.vix_level,
        mins_elapsed_since_open=mins_elapsed,
        risk_multiplier=risk_multiplier,
    )
    return round(stop_distance.final_pct * spot, 2)

def _compute_levels(
    inp: SignalInput,
    signal: str,
    rules: RulesCard,
    pred: PredictiveCard = None,
    risk_multiplier: float = 1.0,
    *,
    governed_zone: str,
):
    """
    Compute entry, stop, target based on signal, zone, and key levels.
    risk_multiplier: from volatility regime — scales stop distance.

    TARGET PHILOSOPHY:
    The primary target comes from the PREDICTION ENGINE (avg expected move
    from similar historical setups). Structural levels (gamma walls, OI walls,
    VWAP) act as CONFIRMATION — if a structural level is near the predicted
    move, snap to it. If no structural level is nearby, use the predicted move.

    This prevents the old bug where the call gamma wall at 595 becomes the
    target when spot is 580, giving a fantasy 14:1 R:R on a 25-minute trade.

    RULES:
    1. Entry is ALWAYS at or near spot (adjusted by zone anchor).
    2. Stop = entry ± stop_dist (percentage-based, VIX-aware).
    3. T1 = predicted avg move (5-bar horizon), snapped to nearby structural
       level if one exists within ±30% of the predicted distance.
    4. T2 = predicted move at **primary** horizons (15c / 60c empirical) only — not 3c/8c/13c secondary.
    5. Maximum R:R cap = 5:1 for T1, 8:1 for T2. Anything beyond is unrealistic
       for intraday scalps.
    """
    spot      = inp.spot
    cgw       = inp.call_gamma_wall
    pgw       = inp.put_gamma_wall
    coi       = inp.call_oi_wall
    poi       = inp.put_oi_wall
    vwap      = inp.vwap
    zone      = (governed_zone or "").lower()
    stop_dist = _stop_distance(inp, risk_multiplier=risk_multiplier)

    # ── Prediction-based move distances (primary horizons for tradable targets only) ──
    avg5  = pred.avg_5c_pts  if pred and pred.avg_5c_pts is not None else None
    avg15 = pred.avg_15c_pts if pred and pred.avg_15c_pts is not None else None
    avg60 = pred.avg_60c_pts if pred and pred.avg_60c_pts is not None else None

    def _structural_levels(direction):
        if direction == "long":
            return [level for level in (vwap, cgw, coi) if level and level > spot]
        return [level for level in (vwap, pgw, poi) if level and level < spot]

    def _targets(entry, direction, risk):
        return derive_target_levels(
            entry=entry,
            direction=direction,
            risk=risk,
            avg5=avg5,
            avg15=avg15,
            avg60=avg60,
            structural_levels=_structural_levels(direction),
        )

    def _long_levels(anchor):
        entry = round(max(anchor + 0.25, spot), 2)
        stop  = round(entry - stop_dist, 2)
        risk  = round(entry - stop, 2)
        if risk <= 0:
            risk = stop_dist

        targets = _targets(entry, "long", risk)
        return entry, stop, targets.target, targets.target2

    def _short_levels(anchor):
        entry = round(min(anchor - 0.25, spot), 2)
        stop  = round(entry + stop_dist, 2)
        risk  = round(stop - entry, 2)
        if risk <= 0:
            risk = stop_dist

        targets = _targets(entry, "short", risk)
        return entry, stop, targets.target, targets.target2

    # ── PIN ZONE: fade the walls ──────────────────────────────────────────────
    if signal == "short" and is_pin_zone(zone) and cgw:
        return _short_levels(anchor=cgw)

    if signal == "long" and is_pin_zone(zone) and pgw:
        return _long_levels(anchor=pgw)

    # ── BREAKOUT: momentum long above CGW ────────────────────────────────────
    if signal == "long" and zone == "breakout" and cgw:
        return _long_levels(anchor=cgw)

    # ── BREAKDOWN: momentum short below PGW ──────────────────────────────────
    if signal == "short" and zone == "breakdown" and pgw:
        return _short_levels(anchor=pgw)

    # ── Fallback: anchor to spot ──────────────────────────────────────────────
    if signal == "short":
        return _short_levels(anchor=spot + 0.25)

    if signal == "long":
        return _long_levels(anchor=spot - 0.25)

    return None, None, None, None

def _downgrade(conviction: str) -> str:
    if conviction == "high":   return "medium"
    if conviction == "medium": return "low"
    return "low"


# Issue 13 closeout: directional trades require a real posterior; uniform fallback is non-tradable.
_NON_TRADABLE_CANONICAL_PROVENANCE = frozenset({"fusion_unavailable", "missing_canonical_fallback"})

_CONV_ORDER = {"low": 0, "medium": 1, "high": 2}


def _conviction_from_canonical_forecast(
    canonical: CanonicalForecast,
    *,
    pred_agrees: bool,
    final_signal: str,
) -> str:
    """
    Base call.conviction tier from canonical confidence + marginal probability only.
    Environmental layers may _downgrade later; they must not invent higher conviction than this
    when pred_agrees (canonical direction matches final_signal).
    """
    if final_signal == "wait" or not pred_agrees:
        return "low"
    c = str(getattr(canonical, "confidence", "low") or "low").strip().lower()
    if c not in _CONV_ORDER:
        c = "low"
    try:
        dom_p = float(canonical.dominant_probability())
    except (TypeError, ValueError):
        dom_p = 1.0 / 3.0
    margin = dom_p - (1.0 / 3.0)
    ceil_ord = _CONV_ORDER[c]

    if c == "high":
        base_ord = 2 if margin >= 0.12 else (1 if margin >= 0.06 else 0)
    elif c == "medium":
        base_ord = 1 if margin >= 0.10 else 0
    else:
        base_ord = 0

    base_ord = min(base_ord, ceil_ord)
    for label, tier_o in _CONV_ORDER.items():
        if tier_o == base_ord:
            return label
    return "low"


def _size_note(conviction: str, mins_to_close: float, vix: Optional[float]) -> str:
    """Plain English sizing guidance."""
    if mins_to_close <= 30:
        return "No new positions — too close to close."
    elif mins_to_close <= 120:
        base = "Quick trades only — half size, take profits fast."
    elif conviction == "high":
        base = "Full size appropriate — high conviction setup."
    elif conviction == "medium":
        base = "Half to three-quarter size — medium conviction."
    else:
        base = "Small size or skip — low conviction. Wait for better setup."

    if vix and vix > 25:
        base += f" VIX at {vix:.1f} — widen stops, reduce size further."
    return base


# Execution mode labels based on R-unit ranges
EXEC_MODES = {
    "NO_TRADE": (0.00, 0.00),
    "PROBE":    (0.01, 0.30),
    "REDUCED":  (0.31, 0.55),
    "STANDARD": (0.56, 1.00),
    "MAX":      (1.01, 1.25),
}


def compute_position_size(
    *,
    signal: str,
    conviction: str,
    trade_type: str,
    confluence_count: int,
    confluence_total: int,
    # Regime
    regime_label: str = "unknown",
    regime_confidence: str = "low",
    # Volatility
    atr: float | None = None,
    iv_level: float | None = None,
    vix: float | None = None,
    stop_distance: float | None = None,
    # MC
    mc_eae: float | None = None,
    mc_efe: float | None = None,
    mc_containment: float | None = None,
    mc_expansion: float | None = None,
    # Fusion
    model_agreement: float | None = None,
    fusion_confidence: str = "low",
    n_models_active: int = 0,
    # Level quality
    dist_to_nearest_opposing_wall: float | None = None,
    has_void_ahead: bool = False,
    # Risk
    reward_risk: float | None = None,
    validation_passed: bool = True,
    # Time
    mins_to_close: float = 390.0,
    # Volatility regime: risk_multiplier > 1 = wider stops → reduce position for same $ risk
    vol_regime_risk_multiplier: float = 1.0,
) -> dict:
    """
    Formal position sizing per Trade Execution & Position Sizing Framework v1.

    Returns dict with:
        r_units:            float (0.00 to 1.25)
        execution_mode:     str ('NO_TRADE', 'PROBE', 'REDUCED', 'STANDARD', 'MAX')
        multipliers:        dict of each factor
        size_cue:           str ('SKIP', 'QUARTER', 'HALF', 'FULL')
        reduction_reasons:  list of strings explaining each cut
        summary:            str plain English
    """
    if signal == "wait" or not validation_passed:
        return {
            "r_units": 0.0,
            "execution_mode": "NO_TRADE",
            "size_cue": "SKIP",
            "multipliers": {},
            "reduction_reasons": ["no active trade" if signal == "wait" else "validation gate failed"],
            "summary": "No trade.",
        }

    reasons = []

    # == 1. CONFIDENCE MULTIPLIER =============================================
    # From fusion confidence + model agreement + confluence
    if conviction == "high" and confluence_count >= 3:
        conf_mult = 1.00
    elif conviction == "high":
        conf_mult = 0.85
    elif conviction == "medium":
        conf_mult = 0.70
    elif conviction == "low":
        conf_mult = 0.45
        reasons.append("low conviction")
    else:
        conf_mult = 0.25
        reasons.append("very low conviction")

    # Model agreement boost/cut
    if model_agreement is not None and n_models_active >= 2:
        if model_agreement >= 0.80:
            conf_mult = min(1.25, conf_mult * 1.10)
        elif model_agreement < 0.35:
            conf_mult *= 0.80
            reasons.append(f"model disagreement ({model_agreement:.0%})")

    # Fusion confidence boost
    if fusion_confidence == "high" and conf_mult < 1.0:
        conf_mult = min(1.0, conf_mult * 1.10)

    # == 2. REGIME MULTIPLIER =================================================
    REGIME_MULT = {
        "pinning":            0.60,
        "mean_reversion":     0.60,
        "reversal_prone":     0.50,
        "vol_compression":    0.70,
        "vol_expansion":      0.85,
        "breakout":           0.90,
        "acceleration":       0.90,
        "trend_continuation": 1.00,
        "unknown":            0.70,
    }
    regime_mult = REGIME_MULT.get(regime_label, 0.70)

    # Regime confidence adjustment
    if regime_confidence == "high" and regime_mult < 1.0:
        regime_mult = min(1.0, regime_mult + 0.10)
    elif regime_confidence == "low":
        regime_mult = max(0.40, regime_mult - 0.10)
        reasons.append("low regime confidence")

    if regime_label in ("pinning", "reversal_prone"):
        reasons.append(f"{regime_label} regime")

    # == 3. VOLATILITY MULTIPLIER =============================================
    vol_mult = 1.00

    # VIX-based
    if vix is not None:
        if vix > 35:
            vol_mult *= 0.50
            reasons.append(f"VIX extreme ({vix:.0f})")
        elif vix > 25:
            vol_mult *= 0.70
            reasons.append(f"VIX elevated ({vix:.0f})")
        elif vix > 20:
            vol_mult *= 0.85

    # ATR-based: if stop distance < 0.5 ATR, trade is too tight
    if atr and stop_distance and atr > 0:
        stop_atr_ratio = stop_distance / atr
        if stop_atr_ratio < 0.5:
            vol_mult *= 0.60
            reasons.append(f"stop too tight ({stop_atr_ratio:.1f}x ATR)")
        elif stop_atr_ratio > 3.0:
            vol_mult *= 0.70
            reasons.append(f"stop very wide ({stop_atr_ratio:.1f}x ATR)")

    # == 4. MONTE CARLO RISK MULTIPLIER (regime-aware v2) =======================
    mc_mult = 1.00

    if mc_eae is not None and stop_distance and stop_distance > 0:
        eae_ratio = mc_eae / stop_distance
        # Regime-aware EAE thresholds: expansion regimes tolerate more
        if regime_label in ("breakout", "acceleration", "vol_expansion"):
            # Wider tolerance — expansion paths are expected to have larger EAE
            if eae_ratio > 2.5:
                mc_mult *= 0.50
                reasons.append(f"MC EAE extreme ({eae_ratio:.1f}x stop) even for {regime_label}")
            elif eae_ratio > 1.8:
                mc_mult *= 0.75
        elif regime_label in ("pinning", "mean_reversion"):
            # Tighter tolerance — contained regimes shouldn't have large EAE
            if eae_ratio > 1.5:
                mc_mult *= 0.40
                reasons.append(f"MC EAE {eae_ratio:.1f}x stop in {regime_label} — risk elevated")
            elif eae_ratio > 1.0:
                mc_mult *= 0.70
        else:
            # Default thresholds
            if eae_ratio > 2.0:
                mc_mult *= 0.40
                reasons.append(f"MC EAE 2x+ stop ({mc_eae:.1f} vs {stop_distance:.1f})")
            elif eae_ratio > 1.5:
                mc_mult *= 0.65
            elif eae_ratio > 1.0:
                mc_mult *= 0.85

    # Containment vs expansion — regime-aware interpretation
    if mc_containment is not None:
        if trade_type == "breakout":
            # For breakouts: high containment = bad (expansion needed)
            if mc_containment > 0.70:
                mc_mult *= 0.60
                reasons.append(f"MC containment {mc_containment:.0%} — expansion unlikely for breakout")
            elif mc_expansion is not None and mc_expansion > 0.50:
                mc_mult = min(1.0, mc_mult * 1.10)
        elif regime_label in ("pinning", "mean_reversion") and trade_type in ("trend_continuation", "breakout"):
            # Directional trade in pinning/MR: if containment is high, reduce size
            if mc_containment > 0.65:
                mc_mult *= 0.75
                reasons.append(f"MC containment {mc_containment:.0%} in {regime_label} — range trade better")
        elif regime_label == "reversal_prone":
            # Large adverse tail → reduce aggressively
            if mc_eae is not None and mc_efe is not None and mc_eae > mc_efe * 1.3:
                mc_mult *= 0.60
                reasons.append(f"MC EAE exceeds EFE by {(mc_eae/mc_efe - 1):.0%} — adverse tail risk")

    # EFE too low relative to stop
    if mc_efe is not None and stop_distance and stop_distance > 0:
        if mc_efe < stop_distance * 0.5:
            mc_mult *= 0.70
            reasons.append("MC EFE too low for target")

    # == 5. LEVEL QUALITY MULTIPLIER ==========================================
    level_mult = 1.00

    # Opposing wall too close
    if dist_to_nearest_opposing_wall is not None:
        if dist_to_nearest_opposing_wall < 1.0:
            level_mult *= 0.40
            reasons.append(f"opposing wall {dist_to_nearest_opposing_wall:.1f}pts away")
        elif dist_to_nearest_opposing_wall < 2.0:
            level_mult *= 0.70
            reasons.append(f"opposing wall nearby ({dist_to_nearest_opposing_wall:.1f}pts)")

    # Void ahead supports larger size
    if has_void_ahead and level_mult < 1.0:
        level_mult = min(1.0, level_mult + 0.15)

    # == 6. RISK/REWARD FLOOR =================================================
    rr_mult = 1.00
    if reward_risk is not None:
        if reward_risk < 1.0:
            rr_mult = 0.25
            reasons.append(f"R:R below 1.0 ({reward_risk:.1f}x)")
        elif reward_risk < 1.5:
            rr_mult = 0.60
            reasons.append(f"R:R marginal ({reward_risk:.1f}x)")

    # == 7. TIME ADJUSTMENT ===================================================
    time_mult = 1.00
    if mins_to_close <= 30:
        time_mult = 0.0
        reasons.append("market closing")
    elif mins_to_close <= 60:
        time_mult = 0.40
        reasons.append(f"{int(mins_to_close)}min to close")
    elif mins_to_close <= 120:
        time_mult = 0.70
        reasons.append(f"{int(mins_to_close)}min to close")

    # == 8. VOLATILITY REGIME RISK MULTIPLIER ==================================
    # When vol regime widens stops (risk_mult > 1), reduce position for same $ risk
    vol_regime_mult = 1.0
    if vol_regime_risk_multiplier and vol_regime_risk_multiplier > 1.0:
        vol_regime_mult = min(1.0, 1.0 / vol_regime_risk_multiplier)
        reasons.append(f"vol regime wider stops ({vol_regime_risk_multiplier:.2f}x)")

    # =========================================================================
    # FINAL SIZE = product of all multipliers, clamped to 0-1.25
    # =========================================================================
    raw = conf_mult * regime_mult * vol_mult * mc_mult * level_mult * rr_mult * time_mult * vol_regime_mult
    r_units = round(max(0.0, min(1.25, raw)), 2)

    # Map to execution mode
    if r_units <= 0.0:
        exec_mode = "NO_TRADE"
    elif r_units <= 0.30:
        exec_mode = "PROBE"
    elif r_units <= 0.55:
        exec_mode = "REDUCED"
    elif r_units <= 1.00:
        exec_mode = "STANDARD"
    else:
        exec_mode = "MAX"

    # Map to size cue for backward compatibility
    if exec_mode == "NO_TRADE":
        size_cue = "SKIP"
    elif exec_mode == "PROBE":
        size_cue = "QUARTER"
    elif exec_mode == "REDUCED":
        size_cue = "HALF"
    else:
        size_cue = "FULL"

    # Summary
    if not reasons:
        summary = f"{exec_mode} ({r_units:.2f}R) — all factors favorable."
    else:
        summary = f"{exec_mode} ({r_units:.2f}R). {'; '.join(reasons)}."

    return {
        "r_units": r_units,
        "execution_mode": exec_mode,
        "size_cue": size_cue,
        "multipliers": {
            "confidence": round(conf_mult, 2),
            "regime": round(regime_mult, 2),
            "volatility": round(vol_mult, 2),
            "vol_regime": round(vol_regime_mult, 2),
            "monte_carlo": round(mc_mult, 2),
            "level_quality": round(level_mult, 2),
            "risk_reward": round(rr_mult, 2),
            "time": round(time_mult, 2),
        },
        "reduction_reasons": reasons,
        "summary": summary,
    }



def _validate_trade(
    *,
    final_signal,
    inp,
    micro_regime,
    micro,
    pred,
    fusion,
    canonical: CanonicalForecast,
    regime,
    regime_label,
    vol_regime=None,
    confluence_count: int = 0,
    pred_agrees: bool = False,
) -> dict:
    """
    Trade Validation Gate — 3-layer pass/fail per Trade Validation Gate Matrix v1.

    Layer 1 — Structural Validity: market structure supports the trade
    Layer 2 — Probabilistic Validity: predictive models agree
    Layer 3 — Risk Validity: risk environment acceptable

    Returns dict with trade_valid, structure_valid, probability_valid, risk_valid,
    plus reason strings for each failed layer.
    """
    from micro_structure import (
        R_BOS_UP, R_BOS_DOWN, R_CHOCH_BULL, R_CHOCH_BEAR,
        R_CHOP, R_COMPRESSION, R_RANGE,
    )

    result = {
        "trade_valid": True,
        "structure_valid": True,
        "probability_valid": True,
        "risk_valid": True,
        "structure_reason": "",
        "probability_reason": "",
        "risk_reason": "",
        "summary": "",
    }

    if final_signal == "wait":
        return result  # nothing to validate

    spot = inp.spot or 0
    reasons = []

    # ══════════════════════════════════════════════════════════════════════════
    # LAYER 1 — STRUCTURAL VALIDITY
    # ══════════════════════════════════════════════════════════════════════════
    structure_fails = []

    # 1a. Trading directly into a strong wall (long toward call wall, short toward put wall)
    if final_signal == "long" and inp.call_gamma_wall:
        dist_to_wall = inp.call_gamma_wall - spot
        if 0 < dist_to_wall < 1.0:
            structure_fails.append(f"long into call wall ({inp.call_gamma_wall:.0f}) only {dist_to_wall:.1f}pts away")

    if final_signal == "short" and inp.put_gamma_wall:
        dist_to_wall = spot - inp.put_gamma_wall
        if 0 < dist_to_wall < 1.0:
            structure_fails.append(f"short into put wall ({inp.put_gamma_wall:.0f}) only {dist_to_wall:.1f}pts away")

    # 1b. Pinning regime conflicting with breakout trade type
    if regime_label == "pinning" and micro_regime in (R_BOS_UP, R_BOS_DOWN):
        structure_fails.append("breakout structure in pinning regime — likely false breakout")

    # 1c. Chop regime — low structure quality; allow strong stack to proceed
    if micro_regime == R_CHOP and final_signal in ("long", "short"):
        _chop_ok = confluence_count >= 4 or (confluence_count >= 3 and pred_agrees)
        if not _chop_ok:
            structure_fails.append(
                "chop regime — need 4+ stack sources or 3+ with prediction agreement for a directional call"
            )

    if structure_fails:
        result["structure_valid"] = False
        result["structure_reason"] = "; ".join(structure_fails)

    # ══════════════════════════════════════════════════════════════════════════
    # LAYER 2 — PROBABILISTIC VALIDITY
    # ══════════════════════════════════════════════════════════════════════════
    prob_fails = []

    _fusion_available = fusion is not None and getattr(fusion, 'available', False)
    _vol_unstable = vol_regime and getattr(vol_regime, 'vol_regime', '') == "unstable"
    # Slightly lenient in normal vol: 0.25 veto'd almost all multi-model splits; stack still needs 2+ votes.
    _agree_threshold = 0.50 if _vol_unstable else 0.18

    # 2a. Model agreement strongly disagrees (threshold raised in unstable vol regime)
    if _fusion_available:
        agree = getattr(fusion, 'model_agreement', 0.5)
        n_active = getattr(fusion, 'n_sources_active', 0)
        if agree < _agree_threshold and n_active >= 2:
            prob_fails.append(f"model agreement below threshold ({agree:.0%} < {_agree_threshold:.0%}) with {n_active} models active")

    # 2b. Canonical forward forecast opposes the call with sufficient marginal probability
    if canonical and str(canonical.confidence or "").lower() not in ("low", ""):
        pdn = float(canonical.probability_down)
        pup = float(canonical.probability_up)
        cdir = str(canonical.direction or "flat").lower()
        if final_signal == "long" and cdir == "down" and pdn >= 0.50:
            prob_fails.append(f"canonical forward DOWN {pdn:.0%} vs long call")
        elif final_signal == "short" and cdir == "up" and pup >= 0.50:
            prob_fails.append(f"canonical forward UP {pup:.0%} vs short call")

    # 2c. Bayesian posterior strongly favors opposite outcome
    symbol = getattr(inp, 'ticker', '?') or '?'
    if _fusion_available:
        try:
            if final_signal == "long":
                reversal_p = getattr(fusion, 'reversal_posterior', 0.0)
                if reversal_p and reversal_p > 0.50:
                    prob_fails.append(f"fusion reversal posterior {reversal_p:.0%} — high reversal risk for longs")
                    log.debug(
                        "validate_trade: reversal gate fired — %s "
                        "reversal_posterior=%.2f blocking %s",
                        symbol, reversal_p, final_signal
                    )
            elif final_signal == "short":
                continuation_p = getattr(fusion, 'continuation_posterior', 0.0)
                breakout_p = getattr(fusion, 'breakout_posterior', 0.0)
                if (continuation_p > CONTINUATION_BLOCK_THRESHOLD and breakout_p > BREAKOUT_BLOCK_THRESHOLD
                        and (continuation_p + breakout_p) > 0.60):
                    prob_fails.append(f"fusion continuation+breakout {(continuation_p+breakout_p):.0%} — strong upside momentum for shorts")
                    log.debug(
                        "validate_trade: continuation/breakout gate fired — %s "
                        "continuation=%.2f breakout=%.2f blocking short",
                        symbol, continuation_p, breakout_p
                    )
        except Exception as e:
            log.debug("validate_trade: probability gate 2c error — %s", e)

    if prob_fails:
        result["probability_valid"] = False
        result["probability_reason"] = "; ".join(prob_fails)

    # ══════════════════════════════════════════════════════════════════════════
    # LAYER 3 — RISK VALIDITY
    # ══════════════════════════════════════════════════════════════════════════
    risk_fails = []

    # 3a. MC adverse excursion exceeds stop distance — regime-aware threshold
    if _fusion_available and getattr(fusion, 'mc_available', False):
        mc_eae = getattr(fusion, 'mc_eae', None)
        stop_dist = _stop_distance(inp)
        if mc_eae is not None and stop_dist > 0:
            # Regime-aware EAE threshold: breakout/expansion tolerate larger EAE
            eae_gate_mult = 2.0  # default: EAE > 2x stop = fail
            if regime_label in ("breakout", "acceleration", "vol_expansion"):
                eae_gate_mult = 2.5  # allow more room in expansion regimes
            elif regime_label in ("pinning", "mean_reversion"):
                eae_gate_mult = 1.5  # tighter gate in contained regimes
            elif regime_label == "reversal_prone":
                eae_gate_mult = 1.5  # reversals need tight risk
            if mc_eae > stop_dist * eae_gate_mult:
                risk_fails.append(f"MC EAE ({mc_eae:.1f}pts) exceeds {eae_gate_mult:.1f}x stop ({stop_dist:.1f}pts) for {regime_label} regime")

    # 3b. VIX extreme — risk environment hostile
    vix = inp.vix_level
    if vix and vix > 35:
        risk_fails.append(f"VIX at {vix:.1f} — extreme volatility, reduced reliability")

    # 3c. Compression detected — risk of violent breakout in either direction
    if micro and getattr(micro, 'is_compressing', False):
        comp_bars = getattr(micro, 'compression_bars', 0)
        if comp_bars >= 10:
            risk_fails.append(f"compression ({comp_bars} bars) — risk of unpredictable breakout")

    if risk_fails:
        result["risk_valid"] = False
        result["risk_reason"] = "; ".join(risk_fails)

    # ══════════════════════════════════════════════════════════════════════════
    # FINAL GATE
    # ══════════════════════════════════════════════════════════════════════════
    result["trade_valid"] = (
        result["structure_valid"] and
        result["probability_valid"] and
        result["risk_valid"]
    )

    if not result["trade_valid"]:
        layers_failed = []
        if not result["structure_valid"]:
            layers_failed.append("structure")
        if not result["probability_valid"]:
            layers_failed.append("probability")
        if not result["risk_valid"]:
            layers_failed.append("risk")
        result["summary"] = f"GATED — failed {', '.join(layers_failed)}"
    else:
        result["summary"] = "all gates passed"

    return result


def compute_call(
    inp: SignalInput,
    rules: RulesCard,
    pred: PredictiveCard,
    regime=None,
    fusion=None,
    vol_regime=None,
    canonical: Optional[CanonicalForecast] = None,
    *,
    mvp_features: dict,
    mh_policy: Optional[MultiHorizonSynthesis] = None,
) -> TheCall:
    """
    The Call — implements STACK ORDER 8, 9, 10:
      8. Decision Policy Layer (The Call): signal, conviction, trade interpretation
      9. Risk Engine: _validate_trade (structure, probability, risk gates)
     10. Position Sizing: compute_position_size (r_units, execution_mode)

    vol_regime is REQUIRED input; influences trade permissibility, conviction,
    probability gating, stop/risk scaling, and size impact.

    ``mvp_features`` is InferenceSnapshotV1[\"features\"] — canonical zone/VWAP/distances for
    governed semantics (no parallel SignalInput zone/vwap interpretation).
    """
    from features.regime_mvp_context import mvp_nearest_distances_for_regime, mvp_zone
    from micro_structure import (
        R_TREND_UP, R_TREND_DOWN, R_BOS_UP, R_BOS_DOWN,
        R_CHOCH_BULL, R_CHOCH_BEAR, R_COMPRESSION, R_RANGE,
        R_REVERSAL_UP, R_REVERSAL_DN, R_CHOP, R_UNKNOWN,
    )

    if canonical is None:
        u = 1.0 / 3.0
        canonical = CanonicalForecast(
            direction="flat",
            probability_up=u,
            probability_down=u,
            probability_flat=u,
            confidence="low",
            provenance="missing_canonical_fallback",
        )

    rules_signal = rules.signal
    pred_dir     = canonical.direction
    pred_conf    = canonical.confidence
    spot         = inp.spot
    zone         = mvp_zone(mvp_features)
    micro        = getattr(rules, 'micro', None)
    micro_regime = micro.regime if micro else R_UNKNOWN

    # ── STACK ORDER 8: Decision Policy Layer (The Call) ────────────────────────
    # Consumes vol_regime for trade permissibility, conviction, probability gating.
    _vol_regime   = getattr(vol_regime, 'vol_regime', 'unknown') if vol_regime else 'unknown'
    _vol_permissive = getattr(vol_regime, 'trade_permissive', True) if vol_regime else True
    _vol_conv_mult = getattr(vol_regime, 'conviction_multiplier', 1.0) or 1.0
    _vol_risk_mult = getattr(vol_regime, 'risk_multiplier', 1.0) or 1.0
    _vol_breakout_bias  = getattr(vol_regime, 'breakout_bias', 0.6) or 0.6
    _vol_reversal_bias  = getattr(vol_regime, 'reversal_bias', 0.5) or 0.5

    # ══════════════════════════════════════════════════════════════════════════
    # 1. STACK-DERIVED SIGNAL — full stack synthesis, no rules-first lock
    # Every layer (1–7) contributes; final signal from stack consensus.
    # ══════════════════════════════════════════════════════════════════════════
    _fusion_available = fusion is not None and getattr(fusion, 'available', False)
    _regime_label = getattr(regime, 'primary', 'unknown') if regime else 'unknown'
    greek_b = greek_bias(inp.net_delta, inp.charm_direction, inp.put_call_oi_ratio,
                         dex_magnitude=inp.dex_magnitude or "moderate",
                         charm_magnitude=inp.charm_magnitude or "moderate")
    cross_sig = _cross_instrument_signal(inp)

    # Broad tape: three independent basket/ETF reads (SPY, QQQ, IWM) — no cross-index veto.
    spy_basket_vote = _index_basket_vote(inp.spy_weighted_push, inp.spy_chg_pct)
    qqq_basket_vote = _index_basket_vote(inp.qqq_weighted_push, inp.qqq_chg_pct)
    iwm_basket_vote = _index_basket_vote(inp.iwm_weighted_push, inp.iwm_chg_pct)

    # Order flow direction from SignalInput (stack layer)
    _of_dir = (inp.order_flow_direction or "").strip().lower()
    of_vote = 1 if _of_dir in ("bullish", "call", "long") else (-1 if _of_dir in ("bearish", "put", "short") else 0)

    # Live-horizon Bayesian fusion dominant direction (authoritative model-stack direction; canonical triplet matches this path)
    _fus_dir = getattr(fusion, 'fusion_dominant_direction', None) or getattr(fusion, 'dominant_direction', 'flat') if _fusion_available else "flat"
    _fus_dir = str(_fus_dir or "flat").strip().lower()
    _fus_dom_raw = 1 if _fus_dir == "up" else (-1 if _fus_dir == "down" else 0)
    fus_vote = _fusion_authoritative_directional_vote(_fusion_available, _fus_dom_raw, canonical)

    mh_vote = int(mh_policy.mh_directional_vote()) if mh_policy is not None else 0
    _mh_promoted_directional = False

    # Regime + zone directional bias (breakout/breakdown from derive_zone)
    nd = inp.net_delta or 0.0
    regime_vote = 0
    if zone == "breakout":
        regime_vote = 1  # expansion up
    elif zone == "breakdown":
        regime_vote = -1  # expansion down
    elif _regime_label in ("trend_continuation", "breakout", "acceleration"):
        regime_vote = 1 if nd >= 0 else (-1 if nd < 0 else 0)

    # Stack votes: 1=long, -1=short, 0=abstain (9 sources; fusion slot = authoritative model dir, no duplicate canonical+fusion)
    stack_votes = {
        "micro":   1 if rules_signal == "long" else (-1 if rules_signal == "short" else 0),
        "Greeks":  1 if greek_b == "bullish" else (-1 if greek_b == "bearish" else 0),
        "spy_basket": spy_basket_vote,
        "qqq_basket": qqq_basket_vote,
        "iwm_basket": iwm_basket_vote,
        "regime": regime_vote,
        "fusion": fus_vote,
        "order_flow": of_vote,
        "multi_horizon": mh_vote,
    }
    long_count = sum(1 for v in stack_votes.values() if v == 1)
    short_count = sum(1 for v in stack_votes.values() if v == -1)
    long_names = [k for k, v in stack_votes.items() if v == 1]
    short_names = [k for k, v in stack_votes.items() if v == -1]

    # Stack-derived signal: stricter agreement on macro / issuer event sessions
    _evt = (getattr(inp, "event_risk_level", None) or "none").strip().lower()
    if _evt in ("elevated", "high"):
        STACK_THRESHOLD = 3
    else:
        STACK_THRESHOLD = 2
    if long_count >= STACK_THRESHOLD and long_count > short_count:
        final_signal = "long"
    elif short_count >= STACK_THRESHOLD and short_count > long_count:
        final_signal = "short"
    else:
        final_signal = "wait"

    # Confluence: sources agreeing with the stack-derived final signal
    confluence_sources = []
    if final_signal == "long":
        confluence_sources = [f"{n}" for n in long_names]
    elif final_signal == "short":
        confluence_sources = [f"{n}" for n in short_names]
    confluence_total = 9  # micro, Greeks, spy/qqq/iwm, regime, fusion, order_flow, multi_horizon
    confluence_count = len(confluence_sources)
    confluence_detail = " + ".join(confluence_sources) if confluence_sources else "no stack alignment"

    # ── Fusion / canonical posterior policy (Issue 13): provenance drives behavior ──
    # Uniform max-entropy posterior is not a tradable forecast — force WAIT, not a parallel stack call.
    wait_blocker = None
    _prov = str(getattr(canonical, "provenance", "") or "")
    if (
        _prov in _NON_TRADABLE_CANONICAL_PROVENANCE
        and final_signal in ("long", "short")
    ):
        final_signal = "wait"
        confluence_detail = (
            f"canonical provenance={_prov} — directional trades require an active fusion posterior"
        )
        wait_blocker = {
            "reason": "canonical_provenance",
            "provenance": _prov,
            "detail": "fusion or canonical posterior unavailable — forced WAIT",
        }

    # Re-align flags after a provenance-forced WAIT
    pred_agrees = (final_signal == "long" and canonical.direction == "up") or (
        final_signal == "short" and canonical.direction == "down"
    )

    # ── Multi-horizon policy (pre-risk): veto or promote inside The Call (not post-hoc in signals) ─
    if mh_policy is not None:
        if mh_policy.mh_veto_stack_directional(final_signal):
            final_signal = "wait"
            wait_blocker = {
                "reason": "multi_horizon_policy",
                "detail": (mh_policy.wait_reason or "mh_veto_stack_directional"),
            }
            confluence_detail = (confluence_detail or "no stack alignment") + " | MH policy veto"
        elif (
            final_signal == "wait"
            and mh_policy.final_tradeable_decision
            and str(getattr(canonical, "provenance", "") or "") not in _NON_TRADABLE_CANONICAL_PROVENANCE
        ):
            _mh_promoted_directional = True
            final_signal = "long" if mh_policy.final_bias == "long" else "short"
            wait_blocker = None
            confluence_sources = ["multi_horizon"]
            confluence_count = 1
            confluence_detail = "multi_horizon promoted directional"

    pred_agrees = (final_signal == "long" and canonical.direction == "up") or (
        final_signal == "short" and canonical.direction == "down"
    )

    # Wait blocker: explicit reason for WAIT (stack / vol_regime / gates)
    if final_signal == "wait" and wait_blocker is None:
        wait_blocker = {
            "reason": "stack",
            "long_count": long_count, "short_count": short_count,
            "long_names": long_names, "short_names": short_names,
            "threshold": STACK_THRESHOLD,
        }

    # ══════════════════════════════════════════════════════════════════════════
    # 2. CONVICTION — canonical forecast (confidence + marginal p) + env downgrades only
    # ══════════════════════════════════════════════════════════════════════════
    zone_fresh_bars_1m  = (inp.zone_since_bars_1m or inp.zone_since_bars) or 0   # execution timing
    zone_stable_bars_5m = (inp.zone_since_bars_5m or 0)                          # structure persistence
    prev_z = (inp.prev_zone or "").lower()

    if final_signal == "wait":
        conviction = "low"
    else:
        conviction = _conviction_from_canonical_forecast(
            canonical, pred_agrees=pred_agrees, final_signal=final_signal,
        )

    # Cross-instrument divergence → downgrade (SPY/QQQ/IWM disagree)
    if cross_sig in ("diverging", "strong_diverge") and final_signal != "wait":
        conviction = _downgrade(conviction)

    # Issuer earnings (or similar) on the traded symbol — extra caution beyond macro "elevated"
    if _evt == "high" and final_signal != "wait":
        conviction = _downgrade(conviction)

    # ── Regime conviction adjustment ──────────────────────────────────────────
    if _regime_label == "reversal_prone" and final_signal != "wait":
        conviction = _downgrade(conviction)  # reversal risk → reduce conviction

    # ── Volatility regime: conviction multiplier ──────────────────────────────
    # Policy layer — vol regime scales effective conviction (unstable = reduce)
    if _vol_conv_mult < 0.75 and final_signal != "wait":
        conviction = _downgrade(_downgrade(conviction))
    elif _vol_conv_mult < 0.85 and final_signal != "wait":
        conviction = _downgrade(conviction)

    # ── Zone transition: downgrades only (no confluence/fusion upgrades) ───────
    if zone_fresh_bars_1m <= 2 and prev_z != zone and final_signal != "wait":
        if is_pin_zone(zone) and prev_z in ("breakout", "breakdown"):
            conviction = _downgrade(conviction)

    if _mh_promoted_directional:
        conviction = "low"

    # Override logic removed — stack synthesis (all 9 sources) already determines
    # direction. No single layer can veto; consensus of 2+ sources wins.

    # ── Volatility regime: trade permissibility ───────────────────────────────
    # Policy layer — compression requires stronger breakout confirmation;
    # unstable may require stricter model agreement or force WAIT.
    _is_breakout_setup = zone in ("breakout", "breakdown") and micro_regime in (
        R_BOS_UP, R_BOS_DOWN, R_TREND_UP, R_TREND_DOWN
    )
    if final_signal != "wait":
        _vol_confluence_effective = (
            max(confluence_count, 4) if _mh_promoted_directional else confluence_count
        )
        if not _vol_permissive:
            # Unstable: require very strong confluence (4+) or force wait
            if _vol_confluence_effective < 4:
                final_signal = "wait"
                conviction = "low"
                confluence_detail = "vol regime: unstable — require stronger confirmation"
                wait_blocker = {"reason": "vol_regime", "detail": "unstable — require 4+ confluence", "full_detail": "Vol regime: unstable — require 4+ confluence for directional trade."}
        elif _vol_regime == "compression" and _is_breakout_setup and _vol_breakout_bias < 0.5:
            # Compression + breakout setup: require stronger confirmation (breakout_bias low)
            if _vol_confluence_effective < 4:
                final_signal = "wait"
                conviction = "low"
                detail = f"compression + breakout needs {confluence_count}/4 confluence"
                confluence_detail = (confluence_detail or "") + " [vol: breakout needs stronger confirmation]"
                wait_blocker = {"reason": "vol_regime", "detail": detail, "full_detail": confluence_detail}

    # ══════════════════════════════════════════════════════════════════════════
    # STACK ORDER 9: Risk Engine ────────────────────────────────────────────────
    # MUST run after Decision Policy (8). Validates structure, probability, risk.
    # If validation fails → trade rejected (WAIT). Position Sizing (10) runs after.
    # ══════════════════════════════════════════════════════════════════════════
    gate_result = _validate_trade(
        final_signal=final_signal,
        inp=inp,
        micro_regime=micro_regime,
        micro=micro,
        pred=pred,
        fusion=fusion,
        canonical=canonical,
        regime=regime,
        regime_label=_regime_label,
        vol_regime=vol_regime,
        confluence_count=confluence_count,
        pred_agrees=pred_agrees,
    )

    if final_signal != "wait" and not gate_result["trade_valid"]:
        final_signal = "wait"
        conviction = "low"
        _gate_reasons = []
        if not gate_result["structure_valid"]:
            _gate_reasons.append(gate_result.get("structure_reason", "structure failed"))
        if not gate_result["probability_valid"]:
            _gate_reasons.append(gate_result.get("probability_reason", "probability failed"))
        if not gate_result["risk_valid"]:
            _gate_reasons.append(gate_result.get("risk_reason", "risk failed"))
        confluence_detail = "GATED: " + "; ".join(_gate_reasons)
        wait_blocker = {"reason": "gates", "gate_reasons": _gate_reasons}

    # ══════════════════════════════════════════════════════════════════════════
    # 3. TRADE TYPE — what kind of trade is this?
    # ══════════════════════════════════════════════════════════════════════════
    trade_type = _classify_trade_type(micro_regime, zone, final_signal)

    # ══════════════════════════════════════════════════════════════════════════
    # 4. ENTRY / STOP / T1 / T2 (stop scaled by vol regime risk_multiplier)
    # ══════════════════════════════════════════════════════════════════════════
    entry, stop, target, target2 = _compute_levels(
        inp,
        final_signal,
        rules,
        pred=pred,
        risk_multiplier=_vol_risk_mult,
        governed_zone=zone,
    )

    # Reward/risk for T1 and T2
    rr1 = rr2 = None
    if entry and stop and abs(entry - stop) > 0:
        risk = abs(entry - stop)
        if target:
            rr1 = round(abs(target - entry) / risk, 1)
        if target2:
            rr2 = round(abs(target2 - entry) / risk, 1)

    # ══════════════════════════════════════════════════════════════════════════
    # 5. INVALIDATION — the reason, not just the price
    # ══════════════════════════════════════════════════════════════════════════
    invalidation = _build_invalidation(
        micro=micro, micro_regime=micro_regime, final_signal=final_signal,
        trade_type=trade_type, stop=stop, inp=inp,
    )

    # ══════════════════════════════════════════════════════════════════════════
    # 6. TIME QUALIFIER — how long is this setup valid?
    # ══════════════════════════════════════════════════════════════════════════
    time_qualifier = _time_qualifier(micro_regime, trade_type)
    replay_max_hold_bars = replay_max_hold_bars_for_setup(micro_regime, trade_type)

    # ══════════════════════════════════════════════════════════════════════════
    # STACK ORDER 10: Position Sizing / Execution ───────────────────────────────
    # MUST run last, after Risk Engine (9). Produces r_units, execution_mode.
    # ══════════════════════════════════════════════════════════════════════════
    _stop_dist_pts = abs(entry - stop) if entry and stop else _stop_distance(inp, risk_multiplier=_vol_risk_mult)

    # Determine opposing wall distance
    _opp_wall_dist = None
    if final_signal == "long" and inp.call_gamma_wall:
        _opp_wall_dist = inp.call_gamma_wall - spot
    elif final_signal == "short" and inp.put_gamma_wall:
        _opp_wall_dist = spot - inp.put_gamma_wall

    # Check if void exists ahead of price in trade direction
    _void_ahead = False
    _micro_sweeps = getattr(micro, 'sweeps', []) if micro else []
    # (void detection already handled via sweep_score in server.py — approximate here)

    _sizing = compute_position_size(
        signal=final_signal,
        conviction=conviction,
        trade_type=trade_type,
        confluence_count=confluence_count,
        confluence_total=confluence_total,
        regime_label=_regime_label,
        regime_confidence=getattr(regime, 'confidence', 'low') if regime else 'low',
        atr=inp.atr,  # SignalInput.atr field (was incorrectly '_atr')
        iv_level=inp.iv_level,
        vix=inp.vix_level,
        stop_distance=_stop_dist_pts,
        mc_eae=getattr(fusion, 'mc_eae', None) if _fusion_available else None,
        mc_efe=getattr(fusion, 'mc_efe', None) if _fusion_available else None,
        mc_containment=getattr(fusion, 'mc_containment', None) if _fusion_available else None,
        mc_expansion=getattr(fusion, 'mc_expansion', None) if _fusion_available else None,
        model_agreement=getattr(fusion, 'model_agreement', None) if _fusion_available else None,
        fusion_confidence=getattr(fusion, 'fusion_confidence', 'low') if _fusion_available else 'low',
        n_models_active=getattr(fusion, 'n_sources_active', 0) if _fusion_available else 0,
        dist_to_nearest_opposing_wall=_opp_wall_dist,
        has_void_ahead=_void_ahead,
        reward_risk=rr1,
        validation_passed=gate_result["trade_valid"],
        mins_to_close=inp.mins_to_close,
        vol_regime_risk_multiplier=_vol_risk_mult,
    )

    size_cue = _sizing["size_cue"]
    if (
        mh_policy is not None
        and final_signal in ("long", "short")
        and mh_policy.final_tradeable_decision
        and final_signal == mh_policy.final_bias
    ):
        size_cue = _merge_size_cue_with_mh(size_cue, mh_policy.size_modifier)

    # ══════════════════════════════════════════════════════════════════════════
    # 8. TIME WARNING (market close) — MUST run before headlines so final_signal,
    #    wait_blocker, and display fields stay consistent. No new entries ≤30min.
    # ══════════════════════════════════════════════════════════════════════════
    if inp.mins_to_close <= 30 and inp.mins_to_close > 0:
        time_warning = f"🛑 Only {int(inp.mins_to_close)}min to close — no new entries."
        final_signal = "wait"
        conviction   = "low"
        size_cue     = "SKIP"
        wait_blocker = {
            "reason": "time",
            "detail": f"≤{int(inp.mins_to_close)} min to close",
            "full_detail": f"Only {int(inp.mins_to_close)} min to close — no new entries.",
        }
    elif inp.mins_to_close <= 120 and inp.mins_to_close > 0:
        time_warning = f"⏰ {int(inp.mins_to_close)}min to close — reduce size, quick trades only."
        if size_cue == "FULL":
            size_cue = "HALF"
    else:
        time_warning = None

    _post_gate_ok = bool(gate_result["trade_valid"] and final_signal != "wait")

    # ── Diagnostics: log call decision bundle when signal=wait (set log level DEBUG to see)
    if final_signal == "wait":
        log.debug(
            "[call] WAIT decision: blocker=%s stack_votes=%s long=%d short=%d pred_dir=%s pred_conf=%s fus=%s",
            wait_blocker,
            {k: v for k, v in (stack_votes or {}).items()},
            long_count, short_count,
            pred_dir, pred_conf, _fus_dir,
        )

    # ══════════════════════════════════════════════════════════════════════════
    # 9. HEADLINES — built AFTER all overrides (stack, vol, gates, time) so
    #    headline, reasoning, badge, and wait_blocker reflect same final state.
    # ══════════════════════════════════════════════════════════════════════════
    headline, reasoning = _build_call_headlines(
        final_signal=final_signal, conviction=conviction,
        trade_type=trade_type, entry=entry, stop=stop,
        target=target, target2=target2,
        confluence_count=confluence_count, confluence_total=confluence_total,
        confluence_detail=confluence_detail,
        micro_regime=micro_regime, rules=rules, pred=pred,
        pred_agrees=pred_agrees,
        fusion=fusion,
        wait_blocker=wait_blocker,
    )

    size_note = _size_note(conviction, inp.mins_to_close, inp.vix_level)

    # ══════════════════════════════════════════════════════════════════════════
    # 10. CALL READINESS (V1 deterministic model)
    # ══════════════════════════════════════════════════════════════════════════
    _readiness_score = 0
    _readiness_call_state = "WAIT"
    _readiness_forecast_state = "dormant"
    _readiness_reasons: list = []
    _readiness_missing: list = []
    _readiness_component_scores: dict = {}
    try:
        from setup_readiness import compute_call_readiness
        _tf = getattr(pred, "timeframe_reads", None) or {}
        _nad_c, _nbd_c = mvp_nearest_distances_for_regime(mvp_features)
        _nearest_dist = None
        for _d in (inp.dist_call_gamma_wall, inp.dist_put_gamma_wall, inp.dist_gamma_inflection,
                    _nad_c, _nbd_c):
            if _d is not None:
                _ad = abs(float(_d))
                if _nearest_dist is None or _ad < _nearest_dist:
                    _nearest_dist = _ad
        _level_prox = "near" if _nearest_dist is not None and _nearest_dist <= 2.0 else (
            "mid" if _nearest_dist is not None and _nearest_dist <= 5.0 else "far"
        )
        _call_input = {
            "regime": _regime_label or "unknown",
            "trend": getattr(rules, "zone_label", "") or zone or "",
            "structure_confirmation": _tf.get("15m", ""),   # ~15m structure read
            "structure_higher_tf": _tf.get("1h", ""),       # ~1h trend read
            "prediction_direction": canonical.direction or "flat",
            "prediction_dominant_prob": canonical.dominant_probability(),
            "confluence_read": confluence_detail if confluence_sources else "no directional alignment",
            "validation_passed": _post_gate_ok,
            "level_proximity": _level_prox,
            "near_support": _nearest_dist is not None and _nearest_dist <= 2.0,
            "breakout_ready": zone in ("breakout", "breakdown"),
        }
        _rdy = compute_call_readiness(_call_input)
        _readiness_score = _rdy.get("readiness_score", 0)
        _readiness_call_state = _rdy.get("call_state", "WAIT")
        _readiness_forecast_state = _rdy.get("forecast_state", "dormant")
        _readiness_reasons = _rdy.get("reasons", []) or []
        _readiness_missing = _rdy.get("missing_conditions", []) or []
        _readiness_component_scores = _rdy.get("component_scores", {}) or {}
    except Exception as _re:
        log.debug("call_readiness: %s", _re)

    # ══════════════════════════════════════════════════════════════════════════
    # 11. PUT READINESS (V1, bearish mirror)
    # ══════════════════════════════════════════════════════════════════════════
    _put_score = 0
    _put_state = "WAIT"
    _put_forecast = "dormant"
    _put_reasons: list = []
    _put_missing: list = []
    _put_component_scores: dict = {}
    try:
        from setup_readiness import compute_put_readiness
        _tf = getattr(pred, "timeframe_reads", None) or {}
        _nearest_above, _nearest_below = mvp_nearest_distances_for_regime(mvp_features)
        _put_nearest = None
        if _nearest_above is not None:
            _put_nearest = abs(float(_nearest_above))  # resistance above for puts
        elif _nearest_below is not None:
            _put_nearest = abs(float(_nearest_below))
        _put_level_prox = "near" if _put_nearest is not None and _put_nearest <= 2.0 else (
            "mid" if _put_nearest is not None and _put_nearest <= 5.0 else "far"
        )
        _put_input = {
            "regime": _regime_label or "unknown",
            "trend": getattr(rules, "zone_label", "") or zone or "",
            "structure_confirmation": _tf.get("15m", ""),   # ~15m structure read
            "structure_higher_tf": _tf.get("1h", ""),       # ~1h trend read
            "prediction_direction": canonical.direction or "flat",
            "prediction_dominant_prob": canonical.dominant_probability(),
            "confluence_read": confluence_detail if confluence_sources else "no directional alignment",
            "validation_passed": _post_gate_ok,
            "level_proximity": _put_level_prox,
            "near_resistance": _put_nearest is not None and _put_nearest <= 2.0,
            "breakdown_ready": zone == "breakdown",
        }
        _prdy = compute_put_readiness(_put_input)
        _put_score = _prdy.get("readiness_score", 0)
        _put_state = _prdy.get("call_state", "WAIT")
        _put_forecast = _prdy.get("forecast_state", "dormant")
        _put_reasons = _prdy.get("reasons", []) or []
        _put_missing = _prdy.get("missing_conditions", []) or []
        _put_component_scores = _prdy.get("component_scores", {}) or {}
    except Exception as _re:
        log.debug("put_readiness: %s", _re)

    return TheCall(
        signal=final_signal, conviction=conviction,
        entry=entry, stop=stop, target=target, target2=target2,
        reward_risk=rr1, reward_risk2=rr2,
        headline=headline, reasoning=reasoning,
        wait_blocker=wait_blocker,
        trade_type=trade_type,
        invalidation=invalidation,
        confluence_count=confluence_count,
        confluence_total=confluence_total,
        confluence_detail=confluence_detail,
        time_qualifier=time_qualifier,
        size_cue=size_cue,
        rules_pred_agree=pred_agrees,
        time_warning=time_warning,
        size_note=size_note,
        validation_passed=gate_result["trade_valid"],
        structure_valid=gate_result["structure_valid"],
        probability_valid=gate_result["probability_valid"],
        risk_valid=gate_result["risk_valid"],
        validation_summary=gate_result.get("summary", ""),
        r_units=_sizing["r_units"],
        execution_mode=_sizing["execution_mode"],
        sizing_multipliers=_sizing["multipliers"],
        sizing_reasons=_sizing["reduction_reasons"],
        sizing_summary=_sizing["summary"],
        readiness_score=_readiness_score,
        call_state=_readiness_call_state,
        forecast_state=_readiness_forecast_state,
        readiness_reasons=_readiness_reasons,
        missing_conditions=_readiness_missing,
        readiness_component_scores=_readiness_component_scores,
        put_readiness_score=_put_score,
        put_state=_put_state,
        put_forecast_state=_put_forecast,
        put_readiness_reasons=_put_reasons,
        put_missing_conditions=_put_missing,
        put_readiness_component_scores=_put_component_scores,
        replay_max_hold_bars=replay_max_hold_bars,
    )
