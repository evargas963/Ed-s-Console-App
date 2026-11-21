"""The `levels` panel: the session's price levels and the terrain's levels, each from the price.

Read from State: the price-level snapshot (state.price_level_store), the published gamma levels
(state.level_store) and the live price. Each input absent is answered once, by its own branch.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from calc.liquidity_models import VolumeProfile
from calc.liquidity_value_engine import LEVEL_NAMES, PriceLevelSnapshot
from calc.terrain_engine import OPTION_LEVELS, SAME_DAY_LEVELS, TerrainSnapshot
from calc.terrain_read import from_spot_text, level_side
from numeric_contract import price_text
from push.bars import aggregate_vwap
from push.spot import price_mark, resolve_spot
from push.verdict import terrain_cache_get
from state.level_store import PublishedLevels
from state.price_level_store import canonical_price_level_snapshot
from time_et import age_text, ct_label

#: why a route serves no price levels for a ticker
NO_PRICE_LEVELS_REASON = (
    "no price levels published for this ticker for the market's session yet (they are "
    "built from its 1-minute bars on each new bar and at the console's start)"
)


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
    """Return the pin's note, shown on hover: what it is and how far the price is from it.

    The distance in expected moves and in strike widths and the minutes to the close are
    calc.terrain_engine.pin_by_open_interest's; this only writes them. None without a pin.
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


#: the price-level snapshot's own fields in the panel, each None when none is published
SNAPSHOT_FIELDS = (
    "snapshot_time_ct",
    "snapshot_age_text",
    "bar_source",
    "vwap_series",
    "vwap_text",
    "volume_profile",
    "prior_value_area",
    "degraded",
)


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


def _stamp(as_of: float | None) -> dict[str, Any]:
    """Return a level's time as served: the label the page shows."""
    return {"as_of_time_ct": _ct(as_of)}


def _distance(level: float | None, price: float | None) -> float | None:
    """Return a level's distance from the live price (level minus price); None without both."""
    if level is None or price is None:
        return None
    return level - price


def _profile(vp: VolumeProfile | None) -> dict[str, Any] | None:
    """Return the session's volume profile the value area is read from; None without one."""
    if vp is None:
        return None
    return {
        "basis": "Estimated volume by price: each RTH 1-minute bar's volume spread evenly "
        "over its range (not trades observed at a price)",
        "bars": vp.bars,
        "bars_without_volume": vp.bars_without_volume,
        "tick_size": vp.tick_size,
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


def _prior_value_area(snap: PriceLevelSnapshot) -> dict[str, Any] | None:
    """Return the prior session's value area the chart shades: its VAL and VAH, and its words.

    None when it is absent (families_absent names the `prior_day` or `prior_value_area` reason).
    """
    low, high = snap.price("PD_VAL"), snap.price("PD_VAH")
    if low is None or high is None:
        return None
    return {"low": low, "high": high, "text": f"VA {price_text(low)} – {price_text(high)}"}


def _session_rows(snap: PriceLevelSnapshot) -> list[dict[str, Any]]:
    """Return the session's price levels, each with its own time."""
    rows: list[dict[str, Any]] = []
    for value in snap.levels.values():
        row = value.to_contract_dict()
        row["staleness"] = _stamp(value.as_of_ts_utc)
        rows.append(row)
    return rows


def _snapshot(snap: PriceLevelSnapshot | None, tf: str, served_ts: float) -> dict[str, Any]:
    """Return the price-level snapshot's own fields at `tf`; with none published, each unknown."""
    if snap is None:
        return dict.fromkeys(SNAPSHOT_FIELDS)
    return {
        "snapshot_time_ct": _ct(snap.as_of_ts_utc),
        "snapshot_age_text": _age(snap.as_of_ts_utc, served_ts),
        "bar_source": snap.bar_source,
        # one point per chart bar of `tf`
        "vwap_series": aggregate_vwap(snap.vwap_series, tf),
        "vwap_text": price_text(snap.price("VWAP")),
        "volume_profile": _profile(snap.volume_profile),
        "prior_value_area": _prior_value_area(snap),
        "degraded": list(snap.degraded),
    }


def _gamma(
    published: PublishedLevels | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return the terrain's levels carried beside the session's, and the 0DTE rows.

    Each with the terrain's own time. With no levels published: none carried, and each 0DTE level
    unknown.
    """
    if published is None:
        absent = {
            "price": None,
            "note": None,
            "carried": None,
            "price_text": None,
            "carried_text": None,
            "staleness": _stamp(None),
        }
        return [], [{"id": gid, "label": label, **absent} for gid, label in SAME_DAY_LEVELS]
    t = published.served()
    stamp = _stamp(published.levels_ts_utc)
    carried = [
        {
            "id": gid,
            "price": t[gid],
            "family": "gamma",
            "label": label,
            "short": label,
            "evidence_tier": "DERIVED",
            "provenance": {"producer": "calc.terrain_engine.compute_terrain", "carried": True},
            "staleness": dict(stamp),
            "note": pin_note(published.snap) if gid == "pin_candidate" else None,
        }
        for gid, label in OPTION_LEVELS
        if t[gid] is not None
    ]
    # the nearest listed expiry's own levels, beside the whole book's level of the same name, at
    # the terrain's own compute time: both as the screen shows them (TerrainSnapshot.to_dict)
    zero_dte = [
        {
            "id": gid,
            "label": label,
            "price": published.snap.same_day.get(gid),
            "note": same_day_note(published.snap),
            "carried": t[gid],
            "price_text": t["same_day_text"].get(gid),
            "carried_text": t[f"{gid}_text"],
            "staleness": dict(stamp),
        }
        for gid, label in SAME_DAY_LEVELS
    ]
    return carried, zero_dte


def levels_payload(tk: str, tf: str, now: datetime) -> dict[str, Any]:
    """Return the levels panel at `now`: the published price-level snapshot for the session.

    The terrain's levels carried beside it, each with its distance from the live price.
    """
    served_ts = now.timestamp()
    spot, spot_source, spot_ts = resolve_spot(tk, now=served_ts)
    mark = price_mark(tk, spot_ts, served_ts)  # each value computed from that price carries it
    snap = canonical_price_level_snapshot(tk, now)
    session = _snapshot(snap, tf, served_ts)
    published, verdict = terrain_cache_get(tk, served_ts)
    carried, zero_dte = _gamma(published)
    levels: list[dict[str, Any]] = []
    families_absent: list[dict[str, Any]] = []
    if snap is None:
        families_absent.append({"family": "price_levels", "reason": NO_PRICE_LEVELS_REASON})
    else:
        levels += _session_rows(snap)
        families_absent += snap.families_absent
    levels += carried
    for row in levels:
        price = row.get("price")
        row["distance"] = _distance(price, spot)
        row["side"] = level_side(price, spot)
        row["from_spot_text"] = from_spot_text(row["distance"], row["side"])
        row["price_text"] = price_text(price)
    # the ladder in price order (highest first, unpriced last), and the order by distance to spot
    levels = sorted(
        (r for r in levels if r.get("price") is not None), key=lambda r: r["price"], reverse=True
    ) + [r for r in levels if r.get("price") is None]
    # the order the chart draws them in: nearest Schwab's last price (spot, with its trade time)
    by_distance: list[str] = []
    if spot is not None:
        by_distance = [
            r["id"]
            for r in sorted(
                (r for r in levels if r.get("price") is not None),
                key=lambda r: abs(r["price"] - spot),
            )
        ]

    return {
        "ticker": tk,
        "schema_version": 1,
        "spot": spot,
        "spot_text": price_text(spot),
        "spot_source": spot_source,
        **mark,  # each level's distance and side are from that price
        "snapshot_time_ct": session["snapshot_time_ct"],
        "snapshot_age_text": session["snapshot_age_text"],
        # the gamma levels' verdict (terrain_staleness: LIVE, CLOSE, STALE, NOT LIVE)
        **verdict,
        "bar_source": session["bar_source"],
        "levels": levels,
        "by_distance": by_distance,
        "zero_dte": zero_dte,
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
