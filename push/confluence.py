"""The `confluence` panel: the Confluence matrix of one expiry, with its rail of levels.

Read from State: the published levels (state.level_store), the price-level snapshot
(state.price_level_store) and the live price.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from calc.confluence_composite import Matrix, at_price, build_matrix, window_rows
from calc.math_exposure_core import merge_exposure_books
from calc.terrain_engine import (
    OPTION_LEVELS,
    SAME_DAY_LEVELS,
    Book,
    ExpiryKey,
    TerrainSnapshot,
    nearest_strike,
)
from calc.terrain_read import REGIME_TEXT
from numeric_contract import price_text
from push.answers import unavailable
from push.levels import pin_note
from push.spot import price_mark, resolve_spot
from push.strike_rows import expiry_unreadable, window
from push.verdict import LevelsVerdict, terrain_staleness
from state.level_store import published_levels
from state.price_level_store import canonical_price_level_snapshot
from time_et import age_text, ct_label


def _expiry_order(item: tuple[str, float | None]) -> tuple[int, float, str]:
    """Known days-to-expiration first, then the date. A missing count sorts last."""
    dte = item[1]
    if isinstance(dte, (int, float)):
        return (0, float(dte), item[0])
    return (1, 0.0, item[0])


def _confluence_expiries(books: dict[ExpiryKey, Book]) -> list[dict[str, Any]]:
    """Each expiry of the chain with Schwab's daysToExpiration, the key of its book."""
    found = {str(exp)[:10]: dte for exp, dte in books if exp}
    return [{"expiry": exp, "dte": dte} for exp, dte in sorted(found.items(), key=_expiry_order)]


#: Pill text for the chain's option levels, each "Largest" level by its side and measure in the
#: same words. Same-day copies take "0DTE " in front.
_OPTION_SHORT = {
    "Largest call gamma strike": "Call gamma",
    "Largest put gamma strike": "Put gamma",
    "Gamma flip": "Gamma flip",
    "Max pain": "Max pain",
    "Largest total gamma strike": "Total gamma",
    "Largest open interest strike near price": "Open interest",
    "GSF": "GSF",
    "GRC": "GRC",
    "Largest negative net GEX strike": "−Net GEX",
    "Largest positive net GEX strike": "+Net GEX",
    "Largest total delta strike": "Total delta",
    "Largest call delta strike": "Call delta",
    "Largest put delta strike": "Put delta",
    "Largest call charm strike": "Call charm",
    "Largest put charm strike": "Put charm",
}


def _option_abbrev(label: str, same_day: bool) -> str:
    base = _OPTION_SHORT[label] if label in _OPTION_SHORT else label
    if same_day:
        return "0DTE " + base
    return base


def _confluence_markers(live: TerrainSnapshot, tk: str, now: datetime) -> list[dict[str, Any]]:
    """Levels carried from this same priced snapshot, plus the session levels already published."""
    markers: list[dict[str, Any]] = []
    snap = canonical_price_level_snapshot(tk, now)
    if snap is not None:
        for value in snap.levels.values():
            row = value.to_contract_dict()
            markers.append(
                {
                    "label": row["label"],
                    "short": row["short"],
                    "title": row["label"],
                    "lane": "session",
                    "price": row["price"],
                }
            )
    for gid, label in OPTION_LEVELS:
        price = live.level(gid)
        if price is not None:
            markers.append(
                {
                    "label": label,
                    "short": _option_abbrev(label, False),
                    "title": label,
                    "lane": "options",
                    "price": price,
                }
            )
    for gid, label in SAME_DAY_LEVELS:
        price = live.same_day[gid]  # None: not known (an unavailable snapshot's every one)
        if price is not None:
            markers.append(
                {
                    "label": "0DTE " + label,
                    "short": _option_abbrev(label, True),
                    "title": "0DTE " + label,
                    "lane": "options",
                    "price": price,
                }
            )
    return markers


def _screen_levels(markers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each level at its own price, for the rail. The page does not move it onto a strike."""
    levels: list[dict[str, Any]] = []
    for marker in markers:
        price = marker.get("price")
        if not isinstance(price, (int, float)):
            continue
        levels.append(
            {
                "lane": marker["lane"],
                "abbrev": marker["short"],
                "price": float(price),
                "price_text": price_text(price),
                "title": marker["title"],
            }
        )
    return levels


def _rail(levels: list[dict[str, Any]], rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Place the Confluence rail's levels against the shown strike rows (highest strike first).

    `rail_lanes`: each lane's levels inside the rows, highest price first; `rail_lines`: one
    price line per price inside, `session` when a session level sits at it; `levels_above` /
    `levels_below`: the levels past the rows, in the levels' order; `level_names`: each price's
    level titles, joined. With no rows nothing is inside, above or below.
    """
    names: dict[str, list[str]] = {}
    for lv in levels:
        names.setdefault(lv["price_text"], []).append(lv["title"])
    rail: dict[str, Any] = {
        "rail_lanes": {"session": [], "options": []},
        "rail_lines": [],
        "levels_above": [],
        "levels_below": [],
        "level_names": {p: " + ".join(t) for p, t in names.items()},
    }
    if not rows:
        return rail
    top, bottom = rows[0]["strike"], rows[-1]["strike"]
    inside = [lv for lv in levels if bottom <= lv["price"] <= top]
    rail["levels_above"] = [lv for lv in levels if lv["price"] > top]
    rail["levels_below"] = [lv for lv in levels if lv["price"] < bottom]
    for lane in ("session", "options"):
        rail["rail_lanes"][lane] = sorted(
            (lv for lv in inside if lv["lane"] == lane), key=lambda lv: -lv["price"]
        )
    lines: dict[str, dict[str, Any]] = {}
    for lv in inside:
        line = lines.setdefault(
            lv["price_text"],
            {"price": lv["price"], "price_text": lv["price_text"], "session": False},
        )
        line["session"] = line["session"] or lv["lane"] == "session"
    rail["rail_lines"] = list(lines.values())
    return rail


def _ranked_matrix(snap: TerrainSnapshot, spot: float, chosen: str, dte: float) -> Matrix:
    """Return the ranking of one expiry of a priced chain: the one the matrix request shows.

    `spot` is the price `snap` was priced at; `chosen` is an expiry of `snap`'s books with its
    days to expiration, `dte` (_confluence_expiries).
    """
    selected = [book for key, book in snap.books.items() if str(key[0])[:10] == chosen]
    exposures = selected[0][0] if len(selected) == 1 else merge_exposure_books(selected)[0]
    return build_matrix(
        exposures,
        snap.charm_by_expiry[chosen],
        snap.iv_by_expiry[chosen],
        float(spot),
        float(dte),
    )


def _chain_status(verdict: LevelsVerdict, fetched: float, now: float) -> str:
    """Return the matrix's status line: the levels' word, the chain's time and age, and why."""
    parts = [
        verdict["levels_state"],
        f"chain as of {ct_label(fetched)}, {age_text(now - fetched)} old",
    ]
    if verdict["levels_stale_reason"]:
        parts.append(verdict["levels_stale_reason"])
    return " · ".join(parts)


def confluence(tk: str, now: datetime, params: dict[str, Any]) -> dict[str, Any]:
    """Return the `confluence` panel at the page's one expiry choice (`params["expiry"]`)."""
    unreadable = expiry_unreadable(params)
    if unreadable is not None:
        return unavailable(tk, unreadable, **_rail([], []))
    return confluence_payload(tk, params["expiry"], now)


def confluence_payload(tk: str, expiry: str | None, now: datetime) -> dict[str, Any]:
    """Return the ranking of the priced chain, for the expiry the operator picks.

    `expiry`: the page's one expiry choice. None (All Expirations) is the front expiry still open:
    the matrix ranks one expiry, its preset set by that expiry's days to expiration. An expiry
    the chain does not list as open is answered with why, never another expiry's ranking.
    """
    published = published_levels(tk)
    if published is None or not published.snap.books or published.snap.spot is None:
        return unavailable(tk, "no priced chain is held for this ticker", **_rail([], []))
    live, priced_at = published.snap, published.snap.spot
    today = now.strftime("%Y-%m-%d")
    listed = [e for e in _confluence_expiries(live.books) if e["expiry"] >= today]
    if not listed:
        return unavailable(tk, "no expiry on this chain is still open", **_rail([], []))
    chosen = expiry
    if chosen is None:
        # All Expirations: the matrix ranks one expiry by its days to expiration (its preset),
        # so it shows the front one still open
        live_listed = [e for e in listed if e["dte"] is not None and e["dte"] >= 0]
        chosen = (live_listed or listed)[0]["expiry"]
    match = next((e for e in listed if e["expiry"] == chosen), None)
    if match is None or match["dte"] is None:
        absent = match is None
        reason = (
            f"the chain lists no open contracts for {chosen}"
            if absent
            else "that expiry did not carry days to expiration"
        )
        return unavailable(tk, reason, expiry=chosen, **_rail([], []))
    stored = _ranked_matrix(live, priced_at, chosen, match["dte"])
    fetched = published.computed_ts_utc
    live_spot, _src, live_ts = resolve_spot(tk, now=now.timestamp())
    markers = _confluence_markers(live, tk, now)
    levels = _screen_levels(markers)
    ranked = sorted(stored.ranked)
    lo, hi, view = window(ranked, nearest_strike(ranked, live_spot), "auto", None, 0)
    body: dict[str, Any] = {
        "preset": stored.preset,
        "scale_text": stored.scale_text,
        "ceiling": stored.ceiling,
        "notes": stored.notes if view["note"] is None else [*stored.notes, view["note"]],
        "peaks": stored.peaks,
        "rows": window_rows(stored, ranked[lo : hi + 1]),
    }
    body.update(at_price(body["rows"], stored.strikes, live_spot))
    body.update(
        {
            "ticker": tk,
            "available": True,
            "reason": None,
            "expiry": chosen,
            # the distances and the spot line are from the live price: its mark
            **price_mark(tk, live_ts, now.timestamp()),
            # the levels' one verdict (terrain_staleness): its word, the chain's time and age,
            # and why when it is not LIVE or CLOSE (AGENTS rule 5)
            "status_text": _chain_status(
                terrain_staleness(fetched, tk, now=now.timestamp()), fetched, now.timestamp()
            ),
            **_rail(levels, body["rows"]),
            "regime": live.regime,
            "regime_text": REGIME_TEXT[live.regime],
            "flip_text": price_text(live.gamma_flip),
            "pin_text": price_text(live.pin_candidate),
            "pin_note": pin_note(live),
        }
    )
    return body
