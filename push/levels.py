"""The `levels` panel: the session's price levels and the terrain's levels, each from the price.

Read from State: the price-level snapshot (state.price_level_store), the published gamma levels
(state.level_store) and the live price. Each input absent is answered once, by its own branch.
"""

from __future__ import annotations

from datetime import datetime
from typing import TypedDict

from calc.liquidity_models import VolumeProfile
from calc.liquidity_value_engine import (
    LEVEL_NAMES,
    AbsentFamily,
    PriceLevelFields,
    PriceLevelSnapshot,
)
from calc.terrain_engine import OPTION_LEVELS, SAME_DAY_LEVELS, TerrainSnapshot
from calc.terrain_read import from_spot_text, level_side
from numeric_contract import price_text
from push.bars import aggregate_vwap
from push.spot import resolve_spot
from push.verdict import LevelsVerdict, terrain_cache_get
from state.level_store import PublishedLevels
from state.price_level_store import canonical_price_level_snapshot
from time_et import age_text, ct_label

#: why a route serves no reference levels for a ticker
NO_PRICE_LEVELS_REASON = (
    "no reference levels published for this ticker for the market's session yet (they are "
    "built from its 1-minute bars on each new bar and at the console's start)"
)
#: the level types the zones chart draws as reference lines beside its zones: the prior day's
#: and the extended hours'. Each level says whether it is one (`reference_line`)
REFERENCE_LINE_FAMILIES = frozenset({"prior_day", "extended_hours"})


def same_day_note(snap: TerrainSnapshot) -> str | None:
    """Return the same-day levels' note, shown on hover: what they are when they are a model.

    None when they are today's own expiry as Schwab sent it (or there are none); with no expiry
    listed today, they are the next one re-priced to today's close
    (calc.terrain_engine.same_day_levels, calc.math_levels.repriced_to_close), and the note says so.
    """
    if snap.same_day_repriced_from is None:
        return None
    return (
        f"Modeled: the {snap.same_day_repriced_from} expiry re-priced as if it expired at today's "
        "close (Black-Scholes on Schwab's volatility, rate and dividend yield per contract)"
    )


def pin_note(snap: TerrainSnapshot) -> str | None:
    """Return the highest open interest strike's note (hover): what it is and the price's distance.

    The distance in expected moves and in strike widths and the minutes to the close are
    calc.terrain_engine.pin_by_open_interest's; this only writes them. None without that strike.
    """
    z, widths = snap.pin_expected_moves, snap.pin_strike_widths
    if snap.pin_candidate is None or z is None or snap.pin_minutes_to_close is None:
        return None
    side = "at" if z == 0 else "above" if z > 0 else "below"
    distance = f"{abs(z):.2f} expected moves"
    if widths is not None:  # an expiry listing one strike has no strike width
        distance += f" ({abs(widths):.1f} strike widths)"
    return (
        f"Most open interest within one expected move, of the expiry settling at today's close. "
        f"Price {distance} {side} it; {snap.pin_minutes_to_close:.0f} minutes to the close."
    )


class LevelStamp(TypedDict):
    """A level's time as served: the label the page shows."""

    as_of_time_ct: str | None


class Placement(TypedDict):
    """A level against the live price: its distance (level minus price) and side, each in words.

    With the level's own price as the screen shows it, and whether the liquidity map draws it as
    a reference line.
    """

    distance: float | None
    side: str | None
    from_spot_text: str | None
    price_text: str | None
    reference_line: bool


class SessionLevelRow(PriceLevelFields, Placement):
    """One of the session's price levels on the ladder, with its own time."""

    staleness: LevelStamp


class CarriedProvenance(TypedDict):
    """Where a carried level comes from: the terrain's producer."""

    producer: str
    carried: bool


class CarriedLevelRow(Placement):
    """One of the terrain's levels carried on the ladder beside the session's, at its own time."""

    id: str
    price: float
    family: str
    label: str
    short: str
    evidence_tier: str
    provenance: CarriedProvenance
    staleness: LevelStamp
    note: str | None


class SameDayRow(TypedDict):
    """A level on the 0DTE basis (`price`) beside the whole book's of the same name (`carried`)."""

    id: str
    label: str
    price: float | None
    note: str | None
    carried: float | None
    price_text: str | None
    carried_text: str | None
    staleness: LevelStamp


class ProfileFields(TypedDict):
    """The session's volume profile as the chart draws it: each bin [price, volume, in value]."""

    basis: str
    bars: int
    bars_without_volume: int
    bins: list[list[float | bool]]
    max_volume: float | None
    poc: float
    poc_label: str
    vah: float
    val: float


class PriorValueArea(TypedDict):
    """The prior session's value area the chart shades: its VAL and VAH, and its words."""

    low: float
    high: float
    text: str


class SnapshotStamp(TypedDict):
    """The price-level snapshot's time and its age, each as the screen shows it (snapshot_stamp)."""

    snapshot_time_ct: str | None
    snapshot_age_text: str | None


class SessionFields(SnapshotStamp):
    """The price-level snapshot's own fields in the panel, each None when none is published."""

    bar_source: str | None
    vwap_series: list[list[float]] | None
    vwap_text: str | None
    volume_profile: ProfileFields | None
    prior_value_area: PriorValueArea | None
    degraded: list[str] | None


class LevelsPanel(LevelsVerdict, SessionFields):
    """The `levels` panel: the session's price levels and the terrain's, each from the price.

    The price itself is not served: the page draws it, and whether it is live, from the price row
    (one producer).
    """

    ticker: str
    schema_version: int
    levels: list[SessionLevelRow | CarriedLevelRow]
    by_distance: list[str]
    zero_dte: list[SameDayRow]
    tf: str
    families_absent: list[AbsentFamily]
    none_said: str | None
    walls_said: str | None


#: what the screen says when no level can be shown nearest the price: none published, or none
#: ordered by its distance (no live price) (AGENTS.md rule 4)
NO_LEVELS, NO_PRICED_LEVELS = "No levels", "No priced levels"
#: the largest put and call gamma strikes, in the order the context summary says them
WALLS = ("put_wall", "call_wall")
#: the price-level snapshot's own fields with none published: each unknown
NO_SNAPSHOT: SessionFields = {
    "snapshot_time_ct": None,
    "snapshot_age_text": None,
    "bar_source": None,
    "vwap_series": None,
    "vwap_text": None,
    "volume_profile": None,
    "prior_value_area": None,
    "degraded": None,
}


def _ct(as_of: float | None) -> str | None:
    """Return an instant as the screen shows it (time_et.ct_label); None when unknown."""
    if as_of is None:
        return None
    return ct_label(as_of)


def _age(as_of: float | None, served_ts: float) -> str | None:
    """Return an instant's age at `served_ts` as the screen shows it; None when unknown."""
    if as_of is None:
        return None
    return age_text(served_ts - as_of)


def _stamp(as_of: float | None) -> LevelStamp:
    """Return a level's time as served: the label the page shows."""
    return {"as_of_time_ct": _ct(as_of)}


def _placed(level: float, family: str, price: float | None) -> Placement:
    """Return a level against the live price; its distance and side unknown without a price."""
    distance = None if price is None else level - price
    side = level_side(level, price)
    return {
        "distance": distance,
        "side": side,
        "from_spot_text": from_spot_text(distance, side),
        "price_text": price_text(level),
        "reference_line": family in REFERENCE_LINE_FAMILIES,
    }


def _profile(vp: VolumeProfile | None) -> ProfileFields | None:
    """Return the session's volume profile the value area is read from; None without one."""
    if vp is None:
        return None
    return {
        "basis": "Estimated volume by price: each RTH 1-minute bar's volume spread evenly "
        "over its range (not trades observed at a price)",
        "bars": vp.bars,
        "bars_without_volume": vp.bars_without_volume,
        # [price, volume, inside the value area]
        "bins": [[p, v, vp.val <= p <= vp.vah] for p, v in vp.bins],
        # the largest bin's volume: the profile's scale
        "max_volume": max((v for _p, v in vp.bins), default=None),
        "poc": vp.poc,
        # the POC's mark on the chart: TODAY_POC's short name and its price
        "poc_label": f"{LEVEL_NAMES['TODAY_POC'][1]} {price_text(vp.poc)}",
        "vah": vp.vah,
        "val": vp.val,
    }


def _prior_value_area(snap: PriceLevelSnapshot) -> PriorValueArea | None:
    """Return the prior session's value area the chart shades: its VAL and VAH, and its words.

    None when it is absent (families_absent names the `prior_day` or `prior_value_area` reason).
    """
    low, high = snap.price("PD_VAL"), snap.price("PD_VAH")
    if low is None or high is None:
        return None
    return {"low": low, "high": high, "text": f"VA {price_text(low)} – {price_text(high)}"}


def _session_rows(snap: PriceLevelSnapshot, price: float | None) -> list[SessionLevelRow]:
    """Return the session's price levels, each with its own time and against the live price."""
    return [
        {
            **value.to_contract_dict(),
            "staleness": _stamp(value.as_of_ts_utc),
            **_placed(value.price, value.family, price),
        }
        for value in snap.levels.values()
    ]


def snapshot_stamp(snap: PriceLevelSnapshot, served_ts: float) -> SnapshotStamp:
    """Return the price-level snapshot's time and its age at `served_ts`, as the screen shows them.

    Served with every panel that serves the snapshot's levels (the `levels` panel, the liquidity
    zones), so a snapshot no new bar has renewed stands with its time and age (AGENTS rule 5).
    """
    return {
        "snapshot_time_ct": _ct(snap.as_of_ts_utc),
        "snapshot_age_text": _age(snap.as_of_ts_utc, served_ts),
    }


def _snapshot(snap: PriceLevelSnapshot, tf: str, served_ts: float) -> SessionFields:
    """Return the price-level snapshot's own fields at `tf`."""
    return {
        **snapshot_stamp(snap, served_ts),
        "bar_source": snap.bar_source,
        # one point per chart bar of `tf`
        "vwap_series": aggregate_vwap(snap.vwap_series, tf),
        "vwap_text": price_text(snap.price("VWAP")),
        "volume_profile": _profile(snap.volume_profile),
        "prior_value_area": _prior_value_area(snap),
        "degraded": list(snap.degraded),
    }


def _carried_rows(published: PublishedLevels, price: float | None) -> list[CarriedLevelRow]:
    """Return the terrain's levels carried beside the session's, each with the terrain's own time.

    Against the live price; none for a level not known.
    """
    stamp = _stamp(published.levels_ts_utc)
    return [
        {
            "id": gid,
            "price": level,
            "family": "gamma",
            "label": label,
            "short": label,
            "evidence_tier": "DERIVED",
            "provenance": {"producer": "calc.terrain_engine.compute_terrain", "carried": True},
            "staleness": stamp.copy(),
            "note": pin_note(published.snap) if gid == "pin_candidate" else None,
            **_placed(level, "gamma", price),
        }
        for gid, label in OPTION_LEVELS
        if (level := published.snap.level(gid)) is not None
    ]


def _same_day_rows(published: PublishedLevels | None) -> list[SameDayRow]:
    """Return the 0DTE rows; with no levels published, each level unknown.

    The nearest listed expiry's own levels, beside the whole book's level of the same name, at
    the terrain's own compute time: both as the screen shows them.
    """
    if published is None:
        return [
            {
                "id": gid,
                "label": label,
                "price": None,
                "note": None,
                "carried": None,
                "price_text": None,
                "carried_text": None,
                "staleness": _stamp(None),
            }
            for gid, label in SAME_DAY_LEVELS
        ]
    snap, stamp = published.snap, _stamp(published.levels_ts_utc)
    return [
        {
            "id": gid,
            "label": label,
            "price": snap.same_day[gid],
            "note": same_day_note(snap),
            "carried": snap.level(gid),
            "price_text": price_text(snap.same_day[gid]),
            "carried_text": price_text(snap.level(gid)),
            "staleness": stamp.copy(),
        }
        for gid, label in SAME_DAY_LEVELS
    ]


def _walls_said(levels: list[SessionLevelRow | CarriedLevelRow]) -> str | None:
    """Return where the largest put and call gamma strikes sit from the price, as one sentence.

    Each by its name and its distance in words ("Gamma Put 2.92 above spot, Gamma Call 17.92
    above spot"). None unless both are placed against a live price: a sentence whose fact is not
    known is left out (AGENTS.md rule 5).
    """
    said = [
        f"{r['label']} {r['from_spot_text']}"
        for wall in WALLS
        for r in levels
        if r["id"] == wall and r["from_spot_text"] is not None
    ]
    return ", ".join(said) if len(said) == len(WALLS) else None


def levels_payload(tk: str, tf: str, now: datetime) -> LevelsPanel:
    """Return the levels panel at `now`: the published price-level snapshot for the session.

    The terrain's levels carried beside it, each with its distance from the live price and
    whether the liquidity map draws it as a reference line.
    """
    served_ts = now.timestamp()
    spot = resolve_spot(tk, now=served_ts)[0]  # each level's distance and side are from it
    snap = canonical_price_level_snapshot(tk, now)
    published, verdict = terrain_cache_get(tk, served_ts)
    levels: list[SessionLevelRow | CarriedLevelRow] = []
    families_absent: list[AbsentFamily] = []
    if snap is None:
        session = NO_SNAPSHOT
        families_absent.append({"family": "price_levels", "reason": NO_PRICE_LEVELS_REASON})
    else:
        session = _snapshot(snap, tf, served_ts)
        levels += _session_rows(snap, spot)
        families_absent += snap.families_absent
    if published is not None:
        levels += _carried_rows(published, spot)
    # the ladder in price order (highest first), and the order by distance to spot
    levels.sort(key=lambda r: r["price"], reverse=True)
    # the order the chart draws them in: nearest Schwab's last price (spot, with its trade time)
    by_distance: list[str] = []
    if spot is not None:
        by_distance = [r["id"] for r in sorted(levels, key=lambda r: abs(r["price"] - spot))]

    return {
        "ticker": tk,
        "schema_version": 1,
        "snapshot_time_ct": session["snapshot_time_ct"],
        "snapshot_age_text": session["snapshot_age_text"],
        # the gamma levels' verdict (terrain_staleness: LIVE, CLOSE, STALE, NOT LIVE)
        **verdict,
        "bar_source": session["bar_source"],
        "levels": levels,
        "by_distance": by_distance,
        "none_said": NO_LEVELS if not levels else NO_PRICED_LEVELS if not by_distance else None,
        "walls_said": _walls_said(levels),
        "zero_dte": _same_day_rows(published),
        # The VWAP curve, CARRIED: the one VWAP of the session, which no page accumulates for
        # itself. [epoch_sec, vwap]
        "vwap_series": session["vwap_series"],
        # the session's VWAP as the VWAP family's switch shows it
        "vwap_text": session["vwap_text"],
        # the session's volume profile the value area is read from (absent: families_absent
        # names the value_area reason)
        "volume_profile": session["volume_profile"],
        # the prior session's value area, the chart's band and the prior-day switch's words
        "prior_value_area": session["prior_value_area"],
        "tf": tf,
        "families_absent": families_absent,
        "degraded": session["degraded"],
    }
