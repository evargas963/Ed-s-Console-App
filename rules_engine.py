"""
rules_engine.py
Phase 1 extracted Card 1 logic from signals.py.
"""

from __future__ import annotations

import logging
from datetime import timezone, timedelta

from micro_structure import analyze_micro
from math_exposure import greek_bias, is_pin_zone, APPROACH_PTS
from signal_types import SignalInput, RulesCard
from features.regime_mvp_context import mvp_vwap_side, mvp_zone
from signal_helpers import _ordinal

log = logging.getLogger(__name__)
ET = timezone(timedelta(hours=-5))

def _derive_bias_from_micro(micro, approaching_ceiling, approaching_floor,
                             near_inflection, vwap_side, zone) -> tuple[str, str]:
    """
    Convert micro regime + level context into a structural bias.

    The micro regime tells us what candles are doing.
    Level proximity tells us where we are relative to options walls.
    The 1-min regime acts as an early warning — if it contradicts the
    5-min regime, conviction is reduced or lean is flipped to 'wait'.
    Together they produce a lean for The Call to use.
    """
    from micro_structure import (
        R_TREND_UP, R_TREND_DOWN, R_BOS_UP, R_BOS_DOWN,
        R_CHOCH_BULL, R_CHOCH_BEAR, R_COMPRESSION, R_RANGE,
        R_REVERSAL_UP, R_REVERSAL_DN, R_CHOP,
        regime_direction,
    )

    regime = micro.regime

    # ── Chop: no bias ─────────────────────────────────────────────────────────
    if regime == R_CHOP:
        return "wait", "low"

    # ── Compression: no directional bias, but alert ───────────────────────────
    if regime == R_COMPRESSION:
        return "wait", "medium"

    # ── Trend up + BOS up ─────────────────────────────────────────────────────
    if regime in (R_TREND_UP, R_BOS_UP):
        conv = "high" if regime == R_BOS_UP else "medium"
        # Approaching ceiling in an uptrend = caution, not reversal
        if approaching_ceiling:
            conv = "low"   # trend is up but near resistance — be careful
        return "long", conv

    # ── Trend down + BOS down ─────────────────────────────────────────────────
    if regime in (R_TREND_DOWN, R_BOS_DOWN):
        conv = "high" if regime == R_BOS_DOWN else "medium"
        if approaching_floor:
            conv = "low"
        return "short", conv

    # ── CHoCH: early reversal warning ─────────────────────────────────────────
    if regime == R_CHOCH_BULL:
        return "long", "low"     # early signal, not confirmed yet
    if regime == R_CHOCH_BEAR:
        return "short", "low"

    # ── Reversal: CHoCH + confirming pattern ──────────────────────────────────
    if regime == R_REVERSAL_UP:
        return "long", "medium"
    if regime == R_REVERSAL_DN:
        return "short", "medium"

    # ── Range: lean based on position within range + level proximity ──────────
    if regime == R_RANGE:
        if approaching_ceiling:
            return "short", "medium"
        if approaching_floor:
            return "long", "medium"
        # Middle of range: VWAP side gives a slight lean
        if vwap_side == "above":
            return "long", "low"
        elif vwap_side == "below":
            return "short", "low"
        return "wait", "low"

    return "wait", "low"

def compute_rules(inp: SignalInput, *, mvp_features: dict) -> RulesCard:
    """
    Right Now card — micro price-action cockpit.

    Reads 5-min and 1-min candle data to classify the current micro regime:
      TREND_UP, TREND_DOWN, BOS_UP, BOS_DOWN, CHOCH_BULL, CHOCH_BEAR,
      COMPRESSION, RANGE, REVERSAL_UP, REVERSAL_DOWN, CHOP

    Also layers on options-level proximity alerts (approaching ceiling/floor,
    near inflection). These alerts add context but don't override the micro read.

    Output:
      - headline:    5-min structure read
      - headline_1m: 1-min pattern read
      - detail:      what to watch for
      - zone_label:  micro regime badge
      - signal:      structural bias ('long', 'short', 'wait') — used by The Call
      - alerts:      BOS, CHoCH, compression, level proximity
      - micro:       full MicroRead object for downstream consumers
    """
    from micro_structure import (
        Candle, analyze_micro,
        R_TREND_UP, R_TREND_DOWN, R_BOS_UP, R_BOS_DOWN,
        R_CHOCH_BULL, R_CHOCH_BEAR, R_COMPRESSION, R_RANGE,
        R_REVERSAL_UP, R_REVERSAL_DN, R_CHOP, R_UNKNOWN,
    )

    spot = inp.spot

    # ── Run micro-structure analysis on candles ───────────────────────────────
    micro = analyze_micro(
        candles_5m=inp.candles_5m,
        candles_1m=inp.candles_1m,
        spot=spot,
    )

    # Start with alerts from the micro engine
    alerts = list(micro.alerts)

    # ── Layer on options-level proximity alerts ───────────────────────────────
    # These are valuable context even with candle-based analysis
    cgw = inp.call_gamma_wall
    pgw = inp.put_gamma_wall
    gi  = inp.gamma_inflection

    approaching_ceiling = (
        cgw is not None and
        inp.dist_call_gamma_wall is not None and
        0 < inp.dist_call_gamma_wall <= APPROACH_PTS
    )
    approaching_floor = (
        pgw is not None and
        inp.dist_put_gamma_wall is not None and
        0 < abs(inp.dist_put_gamma_wall) <= APPROACH_PTS
    )
    near_inflection = (
        gi is not None and
        inp.dist_gamma_inflection is not None and
        abs(inp.dist_gamma_inflection) <= APPROACH_PTS
    )

    if approaching_ceiling:
        cgw_s = f"{cgw:.2f}"
        alerts.append(f"⚠ Within {inp.dist_call_gamma_wall:.1f}pts of {cgw_s} ceiling")
    if approaching_floor:
        pgw_s = f"{pgw:.2f}"
        alerts.append(f"⚠ Within {abs(inp.dist_put_gamma_wall):.1f}pts of {pgw_s} floor")
    if near_inflection:
        gi_s = f"{gi:.2f}"
        alerts.append(f"⚠ Near regime flip zone at {gi_s}")

    # Level test counts
    if inp.ceiling_tests_today >= 2 and approaching_ceiling:
        alerts.append(f"🔁 {_ordinal(inp.ceiling_tests_today + 1)} test of ceiling — rejection probability rising")
    if inp.floor_tests_today >= 2 and approaching_floor:
        alerts.append(f"🔁 {_ordinal(inp.floor_tests_today + 1)} test of floor — bounce probability rising")

    # Recent cross events
    fresh_crosses = [c for c in (inp.recent_crosses or []) if c.get("bars_ago", 99) <= 2]
    for cross in fresh_crosses:
        lvl  = cross.get("level_name", "level")
        dirn = "up through" if cross.get("direction") == "up" else "down through"
        alerts.append(f"⚡ Just crossed {dirn} {lvl}")

    # Time context
    if inp.mins_to_close <= 30 and inp.mins_to_close > 0:
        alerts.append(f"🛑 {int(inp.mins_to_close)}min to close — no new entries")
    elif inp.mins_to_close <= 120 and inp.mins_to_close > 0:
        alerts.append(f"⏰ {int(inp.mins_to_close)}min to close — reduce size")

    # Zone transition context — separate execution-layer (1m) from structure-layer (5m)
    zone_fresh_bars_1m  = (inp.zone_since_bars_1m or inp.zone_since_bars) or 0   # execution timing
    zone_stable_bars_5m = (inp.zone_since_bars_5m or 0)                          # structure persistence
    prev_z = (inp.prev_zone or "").lower()
    cur_z = mvp_zone(mvp_features)

    if zone_fresh_bars_1m <= 2 and prev_z and prev_z != cur_z:
        # Fresh transition — 1m recency = execution timing (high-information event)
        alerts.append(f"🔄 Zone just changed: {prev_z} → {cur_z} ({zone_fresh_bars_1m} 1m bars ago)")
        if cur_z == "breakout" and is_pin_zone(prev_z):
            alerts.append("⚡ Breakout from pin zone — momentum starting, don't fade")
        elif cur_z == "breakdown" and is_pin_zone(prev_z):
            alerts.append("⚡ Breakdown from pin zone — sellers taking control")
        elif is_pin_zone(cur_z) and prev_z in ("breakout", "breakdown"):
            alerts.append("🛑 Failed breakout — reverting to pin. Fade the move.")
    elif zone_stable_bars_5m >= 20 and is_pin_zone(cur_z):
        # Stable structure — 5m recency = structure persistence (~100+ min in pin)
        alerts.append(f"📌 Stable pin zone for {zone_stable_bars_5m} five-min bars — fade edges, expect chop")

    # ── Derive structural bias for The Call ───────────────────────────────────
    # This is a LEAN, not a trade call. The Call decides what to do with it.
    signal, conviction = _derive_bias_from_micro(
        micro=micro,
        approaching_ceiling=approaching_ceiling,
        approaching_floor=approaching_floor,
        near_inflection=near_inflection,
        vwap_side=mvp_vwap_side(mvp_features),
        zone=mvp_zone(mvp_features),
    )

    # ── 1-min early warning / circuit breaker ─────────────────────────────────
    # If 1-min structure contradicts 5-min, reduce conviction or flip to wait.
    # This cuts reaction time from ~15 min (wait for 5-min bars) to ~3 min.
    from micro_structure import (
        regime_direction as _regime_dir,
        R_BOS_UP, R_BOS_DOWN, R_REVERSAL_UP, R_REVERSAL_DN,
        R_CHOCH_BULL, R_CHOCH_BEAR,
    )
    _r1m = getattr(micro, "regime_1m", "UNKNOWN")
    _dir_5m = _regime_dir(micro.regime)
    _dir_1m = _regime_dir(_r1m)

    if signal in ("long", "short") and _dir_1m != "neutral" and _dir_5m != _dir_1m:
        # 1-min contradicts 5-min direction
        _strong_1m = _r1m in (R_BOS_UP, R_BOS_DOWN, R_REVERSAL_UP, R_REVERSAL_DN)
        if _strong_1m:
            # Confirmed reversal on 1-min (BOS or REVERSAL against 5-min) → flip to wait
            signal = "wait"
            conviction = "medium"
            alerts.append(f"🔄 1-min confirmed reversal ({_r1m}) — overriding 5-min lean")
        else:
            # Early warning (CHoCH or trend on 1-min against 5-min) → downgrade conviction
            conviction = "low"
            alerts.append(f"⚠ 1-min diverging ({_r1m}) — conviction reduced")

    # Override: no new entries in last 30 min
    if inp.mins_to_close <= 30 and inp.mins_to_close > 0:
        signal = "wait"
        conviction = "low"

    return RulesCard(
        headline=micro.headline_5m,
        headline_1m=micro.headline_1m,
        detail=micro.detail,
        zone_label=micro.regime_label,
        zone_color=micro.regime_color,
        signal=signal,
        conviction=conviction,
        alerts=alerts,
        micro=micro,
    )
