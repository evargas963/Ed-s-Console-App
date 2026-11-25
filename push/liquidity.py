"""The `liquidity` panel: the session's liquidity and value zones, typed by their side of the price.

Read from State: the price-level snapshot (state.price_level_store), the published levels' option
levels with their verdict (push.verdict), the bars and candles the bar writer holds and the live
price.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, TypedDict

from calc.liquidity_models import ZONE_DISPLAY, PlaybookConfig, SnapshotSummary, SourceLevel
from calc.liquidity_value_engine import (
    HOLD_BASELINE_LEVELS,
    HOLD_MIN_TOUCHES,
    HOLD_WINDOW_SESSIONS,
    LEVEL_NAMES,
    ZONE_OPTION_LEVELS,
    HoldCount,
    bars_from_candles,
    build_zone_snapshot,
    wilson_interval,
)
from calc.terrain_engine import OPTION_LEVELS
from calc.terrain_read import LEVEL_ABOVE, LEVEL_BELOW, level_side, within
from instrument_identity import ticker_storage_key
from numeric_contract import price_text
from push.levels import NO_PRICE_LEVELS_REASON, SnapshotStamp, snapshot_stamp
from push.spot import resolve_spot
from push.verdict import LevelsVerdict, terrain_cache_get
from state import bar_store
from state.level_store import PublishedLevels
from state.price_level_store import canonical_price_level_snapshot, materialize_hold_counts
from time_et import sessions

#: every level a zone is clustered from, by id, as every screen names it: the session's levels
#: (LEVEL_NAMES) and the terrain's (OPTION_LEVELS)
ZONE_LEVEL_NAMES = {lid: name for lid, (name, _tag) in LEVEL_NAMES.items()} | dict(OPTION_LEVELS)


class ShownSourceLevel(SourceLevel):
    """A level a zone is clustered from, with its name and its price as the screen shows them."""

    label: str
    value_text: str | None


class ZoneRow(TypedDict):
    """One zone as the liquidity map draws it: its side of the price, its range and its levels."""

    zone_label: str
    zone_side: str
    zone_low: float
    zone_high: float
    zone_low_text: str
    zone_high_text: str
    anchor: float
    source_levels: list[ShownSourceLevel]
    confluence_score: int
    interpretation_notes: str


class ValueSummary(TypedDict):
    """Where today's value area sits against the prior day's, and VWAP against today's.

    Each with its words as the Desk's agreement strip says it.
    """

    value_state: str | None
    vwap_relation: str | None
    value_state_text: str | None
    vwap_relation_text: str | None


class HoldRate(TypedDict):
    """One fixed level type's hold rate in words, at 15 and 30 minutes."""

    level: str
    text: str


class LiquidityPanel(LevelsVerdict, SnapshotStamp):
    """The `liquidity` panel: the session's zones nearest the price first, and the hold rates.

    With what the zones are made of: the option levels' verdict (their state, time, age and why)
    and the price-level snapshot's time and age.
    """

    ticker: str
    zones: list[ZoneRow]
    no_zones_text: str | None
    summary: ValueSummary | None
    location_said: str | None
    hold_rates: list[HoldRate]
    hold_note: str


class NoLiquidity(TypedDict):
    """The `liquidity` panel's answer with no price levels published: no zone, and why."""

    ticker: str
    available: Literal[False]
    zones: list[ZoneRow]
    reason: str


def _option_levels(published: PublishedLevels | None) -> list[tuple[float, str]]:
    """Return the published terrain's option levels the zones are fused with; none before one."""
    return [
        (float(level), k)
        for k in ZONE_OPTION_LEVELS
        if published is not None and (level := published.snap.level(k)) is not None
    ]


def _distance_to_spot(lo: float, hi: float, spot: float) -> float:
    """Return how far the spot is outside the zone, 0.0 inside it."""
    return 0.0 if within(lo, hi, spot) else min(abs(spot - lo), abs(spot - hi))


#: where today's value area sits against the prior day's (liquidity_value_engine
#: .value_area_relation) and where VWAP sits against today's (vwap_against_value), each as the
#: Desk's agreement strip says it; no words where it is not known
VALUE_STATE_TEXT: dict[str | None, str | None] = {
    "unchanged": "unchanged",
    "higher": "higher",
    "lower": "lower",
    "inside": "inside",
    "outside": "outside",
    "overlapping_higher": "overlapping higher",
    "overlapping_lower": "overlapping lower",
    None: None,
}
VWAP_RELATION_TEXT: dict[str | None, str | None] = {
    "above_value": "above value",
    "below_value": "below value",
    "inside_value": "inside value",
    None: None,
}
#: what the map's zone list says when the session's levels make no zone
NO_ZONES_TEXT = "no zones for this session yet"
#: what the bounce frequencies are, shown on hover beside them
HOLD_NOTE = (
    f"Over the last {HOLD_WINDOW_SESSIONS} completed sessions held: a hit is a 1-minute bar "
    "reaching the level from one side, once per approach; it bounced when the close 15 minutes "
    "later (30 in brackets) is still on that side. Random is the same count for "
    f"{HOLD_BASELINE_LEVELS} levels a session spread over the open +- the month's largest move "
    "(Osler 2000): random levels bounce about half the time, so only the difference means "
    f"anything. '-' below {HOLD_MIN_TOUCHES} hits. A past frequency, not a forecast."
)


def hold_text(c: HoldCount) -> str:
    """One horizon's bounce frequency in words: it, the random levels' and the 95% interval.

    "-" with the hits counted when they are fewer than HOLD_MIN_TOUCHES (or the random levels
    were never hit), for no frequency is shown on so few.
    """
    if c.touches < HOLD_MIN_TOUCHES or c.baseline_touches == 0:
        return f"- ({c.touches} hits)"
    rate, base = c.holds / c.touches, c.baseline_holds / c.baseline_touches
    lo, hi = wilson_interval(c.holds, c.touches)
    return (
        f"bounced {rate:.0%} of {c.touches} hits; random {base:.0%}; "
        f"{(rate - base) * 100:+.0f} points (95%: {lo:.0%} to {hi:.0%})"
    )


def hold_rates(tk: str, now: datetime) -> list[HoldRate]:
    """Each fixed level type's hold rate at 15 and 30 minutes over the ticker's held bars.

    calc.liquidity_value_engine.hold_counts over every 1-minute bar the bar writer holds and
    Schwab's daily candles, counted once per input (state.price_level_store).
    """
    counts = materialize_hold_counts(
        tk,
        bars_from_candles(bar_store.bars_1m(tk, bar_store.BARS_KEPT)),
        daily=bar_store.series(tk, "1d"),
        now=now,
    )
    return [
        {
            "level": LEVEL_NAMES[lid][0],
            "text": hold_text(by[15]) + " [30 min: " + hold_text(by[30]) + "]",
        }
        for lid, by in counts.items()
    ]


def _location_said(zones: list[ZoneRow], spot: float | None) -> str | None:
    """Where the price sits among the zones, as one sentence.

    The zone it is inside, with its range and how many levels it holds; else between the nearest
    zone above and the nearest below, each with its near edge. A price outside every zone has one
    on at least one side. None without a price or a zone: the sentence is left out (AGENTS.md
    rule 5).
    """
    if spot is None or not zones:
        return None
    for z in zones:
        if within(z["zone_low"], z["zone_high"], spot):
            return (
                f"{z['zone_label']} ({z['zone_low_text']}–{z['zone_high_text']}, levels in zone "
                f"{z['confluence_score']})"
            )
    above = [z for z in zones if level_side(z["zone_low"], spot) == LEVEL_ABOVE]
    below = [z for z in zones if level_side(z["zone_high"], spot) == LEVEL_BELOW]
    near: list[str] = []
    if above:
        z = min(above, key=lambda z: z["zone_low"])
        near.append(_near_said(z, "above", z["zone_low_text"]))
    if below:
        z = max(below, key=lambda z: z["zone_high"])
        near.append(_near_said(z, "below", z["zone_high_text"]))
    return "Between zones — " + ", ".join(near)


def _near_said(z: ZoneRow, side: str, edge: str) -> str:
    """Return the nearest zone on one side of the price: its name, its near edge, its levels."""
    return f"{z['zone_label']} zone {side} at {edge} (levels in zone {z['confluence_score']})"


def _summary(summary: SnapshotSummary | None) -> ValueSummary | None:
    """Return the value read with each relation's words; None when the snapshot reads none."""
    if summary is None:
        return None
    return {
        "value_state": summary.value_state,
        "vwap_relation": summary.vwap_relation,
        # each as the Desk's agreement strip says it
        "value_state_text": VALUE_STATE_TEXT[summary.value_state],
        "vwap_relation_text": VWAP_RELATION_TEXT[summary.vwap_relation],
    }


def _no_liquidity(ticker: str) -> NoLiquidity:
    """Return the panel's answer with no price levels published for the session: no zone, why."""
    return {"ticker": ticker, "available": False, "zones": [], "reason": NO_PRICE_LEVELS_REASON}


def liquidity_snapshot(ticker: str, now: datetime) -> LiquidityPanel | NoLiquidity:
    """Return the market session's liquidity & value zones for the ticker at `now`.

    Built from the one price-level snapshot (canonical_price_level_snapshot, the same values the
    `levels` panel sends) with the terrain's option levels fused in, each zone typed by its side
    of the live price. It computes no level of its own; the price is not a level. Served with the
    zones: the option levels' verdict at `now` (terrain_cache_get: the one every screen shows) and
    the snapshot's time and age (snapshot_stamp, the `levels` panel's own). Levels that make no
    zone are answered with the words the map's list says for that (`no_zones_text`).
    """
    ticker_upper = ticker_storage_key(ticker)
    at = now.timestamp()
    config = PlaybookConfig(max_zone_width=2.0)
    published, verdict = terrain_cache_get(ticker_upper, at)
    extra = _option_levels(published)
    # the one spot (resolve_spot), the header's own
    spot_for_zones, _, _ = resolve_spot(ticker_upper, now=at)
    _canon = canonical_price_level_snapshot(ticker_upper, now)
    if _canon is None:
        return _no_liquidity(ticker_upper)
    out = build_zone_snapshot(
        ticker_upper,
        config,
        canonical=_canon,
        now=now,
        extra_levels=extra,
        price=spot_for_zones,
        sessions=sessions(),
    )
    zones_payload: list[ZoneRow] = [
        {
            "zone_label": ZONE_DISPLAY[z.zone_type][0],
            "zone_side": ZONE_DISPLAY[z.zone_type][1],
            "zone_low": z.zone_low,
            "zone_high": z.zone_high,
            "zone_low_text": price_text(z.zone_low),
            "zone_high_text": price_text(z.zone_high),
            "anchor": z.zone_mid,
            "source_levels": [
                {**s, "label": ZONE_LEVEL_NAMES[s["id"]], "value_text": price_text(s["value"])}
                for s in z.source_levels
            ],
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
        **verdict,
        **snapshot_stamp(_canon, at),
        "zones": zones_payload,
        # the zone list's words when it lists none; with no levels published, `reason` says why
        "no_zones_text": None if zones_payload else NO_ZONES_TEXT,
        "summary": _summary(out.summary),
        "location_said": _location_said(zones_payload, spot_for_zones),
        "hold_rates": hold_rates(ticker_upper, now),
        "hold_note": HOLD_NOTE,
    }
