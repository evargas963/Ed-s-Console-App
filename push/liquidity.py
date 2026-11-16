"""The `liquidity` panel: the session's liquidity and value zones, typed by their side of the price.

Read from State: the price-level snapshot (state.price_level_store), the published levels' option
levels (state.level_store), the bars and candles the bar writer holds and the live price.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from calc.liquidity_models import ZONE_DISPLAY, PlaybookConfig
from calc.liquidity_value_engine import (
    HOLD_BASELINE_LEVELS,
    HOLD_MIN_TOUCHES,
    HOLD_WINDOW_SESSIONS,
    LEVEL_NAMES,
    OPTION_LEVEL_TAGS,
    HoldCount,
    bars_from_candles,
    build_live_snapshot,
    hold_counts,
    wilson_interval,
)
from calc.terrain_read import LEVEL_ABOVE, LEVEL_BELOW, level_side, within
from instrument_identity import ticker_storage_key
from numeric_contract import price_text
from push.answers import unavailable
from push.levels import NO_PRICE_LEVELS_REASON
from push.spot import resolve_spot
from state import bar_store
from state.level_store import published_levels
from state.price_level_store import canonical_price_level_snapshot
from time_et import sessions


def _liquidity_option_levels(tk: str) -> list[tuple[float, str]]:
    """Return the ticker's option levels from its published terrain, tagged for liquidity zones."""
    published = published_levels(tk)
    return [
        (float(getattr(published.snap, k)), tag)
        for k, tag in OPTION_LEVEL_TAGS
        if published is not None and getattr(published.snap, k) is not None
    ]


def _distance_to_spot(lo: float, hi: float, spot: float) -> float:
    """Return how far the spot is outside the zone, 0.0 inside it."""
    return 0.0 if within(lo, hi, spot) else min(abs(spot - lo), abs(spot - hi))


#: what the hold rates are, shown on hover beside them
HOLD_NOTE = (
    f"Over the last {HOLD_WINDOW_SESSIONS} completed sessions held: a touch is a 1-minute bar "
    "reaching the level from one side, once per approach; it held when the close 15 minutes "
    "later (30 in brackets) is still on that side. Random is the same count for "
    f"{HOLD_BASELINE_LEVELS} levels a session spread over the open +- the month's largest move "
    "(Osler 2000): random levels hold about half the time, so only the difference means anything. "
    f"'-' below {HOLD_MIN_TOUCHES} touches. A past frequency, not a forecast."
)


def hold_text(c: HoldCount) -> str:
    """One horizon's hold rate in words: the rate, the random levels' and the 95% interval.

    "-" with the touches counted when they are fewer than HOLD_MIN_TOUCHES (or the random levels
    were never touched), for no rate is shown on so few.
    """
    if c.touches < HOLD_MIN_TOUCHES or c.baseline_touches == 0:
        return f"- ({c.touches} touches)"
    rate, base = c.holds / c.touches, c.baseline_holds / c.baseline_touches
    lo, hi = wilson_interval(c.holds, c.touches)
    return (
        f"held {rate:.0%} of {c.touches} touches; random {base:.0%}; "
        f"{(rate - base) * 100:+.0f} points (95%: {lo:.0%} to {hi:.0%})"
    )


def hold_rates(tk: str, now: datetime) -> list[dict[str, str]]:
    """Each fixed level type's hold rate at 15 and 30 minutes over the ticker's held bars.

    calc.liquidity_value_engine.hold_counts over every 1-minute bar the bar writer holds and
    Schwab's daily candles.
    """
    counts = hold_counts(
        bars_from_candles(bar_store.bars_1m(tk, bar_store.BARS_KEPT)),
        bar_store.series(tk, "1d"),
        now,
        sessions=sessions(),
        config=PlaybookConfig(),
    )
    return [
        {
            "level": LEVEL_NAMES[lid][0],
            "text": hold_text(by[15]) + " [30 min: " + hold_text(by[30]) + "]",
        }
        for lid, by in counts.items()
    ]


def _spot_location(zones: list[dict[str, Any]], spot: float | None) -> dict[str, int | None] | None:
    """Where spot sits among the zones, by index into `zones`.

    The zone it is inside, else the nearest zone above and below. None without a spot or a zone.
    """
    if spot is None or not zones:
        return None
    for i, z in enumerate(zones):
        if within(z.get("zone_low"), z.get("zone_high"), spot):
            return {"inside": i, "above": None, "below": None}
    above = [i for i, z in enumerate(zones) if level_side(z.get("zone_low"), spot) == LEVEL_ABOVE]
    below = [i for i, z in enumerate(zones) if level_side(z.get("zone_high"), spot) == LEVEL_BELOW]
    return {
        "inside": None,
        "above": min(above, key=lambda i: zones[i]["zone_low"]) if above else None,
        "below": max(below, key=lambda i: zones[i]["zone_high"]) if below else None,
    }


def liquidity_snapshot(ticker: str, now: datetime) -> dict[str, Any]:
    """Return the market session's liquidity & value zones for the ticker at `now`.

    Built from the one price-level snapshot (canonical_price_level_snapshot, the same values the
    `levels` panel sends) with the terrain's option levels fused in, each zone typed by its side
    of the live price. It computes no level of its own; the price is not a level.
    """
    ticker_upper = ticker_storage_key(ticker)
    config = PlaybookConfig(max_zone_width=2.0)
    extra = _liquidity_option_levels(ticker_upper)
    # the one spot (resolve_spot), the header's own
    spot_for_zones, _, _ = resolve_spot(ticker_upper, now=now.timestamp())
    _canon = canonical_price_level_snapshot(ticker_upper, now)
    if _canon is None:
        return unavailable(ticker_upper, NO_PRICE_LEVELS_REASON, zones=[])
    out = build_live_snapshot(
        ticker_upper,
        config,
        canonical=_canon,
        now=now,
        extra_levels=extra,
        price=spot_for_zones,
        sessions=sessions(),
    )
    zones_payload: list[dict[str, Any]] = [
        {
            "zone_label": ZONE_DISPLAY[z.zone_type][0],
            "zone_side": ZONE_DISPLAY[z.zone_type][1],
            "zone_low": z.zone_low,
            "zone_high": z.zone_high,
            "zone_low_text": price_text(z.zone_low),
            "zone_high_text": price_text(z.zone_high),
            "anchor": z.zone_mid,
            "source_levels": [{**s, "value_text": price_text(s["value"])} for s in z.source_levels],
            "confluence_score": z.confluence_score,
            "interpretation_notes": z.interpretation_notes,
        }
        for z in out.zones
    ]
    # by price, then (with a live price) nearest the price first
    zones_payload.sort(key=lambda x: x["zone_low"])
    if spot_for_zones is not None:
        spot = spot_for_zones
        zones_payload.sort(key=lambda x: _distance_to_spot(x["zone_low"], x["zone_high"], spot))
    return {
        "ticker": out.ticker,
        "zones": zones_payload,
        "summary": out.summary
        and {
            "value_state": out.summary.value_state,
            "vwap_relation": out.summary.vwap_relation,
        },
        "spot_location": _spot_location(zones_payload, spot_for_zones),
        "hold_rates": hold_rates(ticker_upper, now),
        "hold_note": HOLD_NOTE,
    }
