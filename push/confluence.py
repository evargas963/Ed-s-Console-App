"""The `confluence` panel: the Confluence matrix of one expiry, with its rail of levels.

Read from State: the published levels (state.level_store), the price-level snapshot
(state.price_level_store) and the live price.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from confluence_composite import at_price, build_matrix, window_rows
from math_exposure_core import merge_exposure_books
from numeric_contract import price_text
from push.answers import unavailable
from push.levels import expected_move, pin_note
from push.spot import price_mark, resolve_spot
from push.strike_rows import window
from push.verdict import LevelsVerdict, terrain_staleness
from state.level_store import published_levels
from state.price_level_store import canonical_price_level_snapshot
from terrain_engine import (
    OPTION_LEVELS,
    SAME_DAY_LEVELS,
    Book,
    ExpiryKey,
    TerrainSnapshot,
    nearest_strike,
)
from terrain_read import within
from time_et import age_text, ct_label


def _expiry_order(item: tuple[str, float | None]) -> tuple[int, float, str]:
    """Known days-to-expiration first, then the date. A missing count sorts last."""
    dte = item[1]
    if isinstance(dte, (int, float)):
        return (0, float(dte), item[0])
    return (1, 0.0, item[0])


def _confluence_expiries(
    books: dict[ExpiryKey, Book], expiry_dte: dict[str, float | None]
) -> list[dict[str, Any]]:
    found: dict[str, float | None] = {}
    for key in books:
        if not key[0]:
            continue
        exp = str(key[0])[:10]
        dte = expiry_dte.get(exp)
        if dte is None:
            dte = key[1]
        if exp not in found or (found[exp] is None and dte is not None):
            found[exp] = dte
    listed: list[dict[str, Any]] = []
    for exp, dte in sorted(found.items(), key=_expiry_order):
        label = exp
        if isinstance(dte, (int, float)) and float(dte) == 0:
            label = "0DTE · " + exp
        elif isinstance(dte, (int, float)) and float(dte) == int(dte):
            label = exp + " · " + str(int(dte))
        elif isinstance(dte, (int, float)):
            label = exp + " · " + str(dte)
        listed.append({"expiry": exp, "dte": dte, "label": label})
    return listed


#: Pill text for the chain's option levels. Same-day copies take "0D " in front.
_OPTION_SHORT = {
    "Call wall": "CW",
    "Put wall": "PW",
    "Γ flip": "Flip",
    "Max pain": "Pain",
    "Abs Γ": "Abs Γ",
    "Pin candidate": "Pin",
    "GSF": "GSF",
    "GRC": "GRC",
    "Net put Γ peak": "Net PΓ",
    "Net call Γ peak": "Net CΓ",
    "Key Δ strike": "Key Δ",
    "Call Δ wall": "CΔW",
    "Put Δ wall": "PΔW",
    "Call charm wall": "CCh",
    "Put charm wall": "PCh",
}


def _option_abbrev(label: str, same_day: bool) -> str:
    base = _OPTION_SHORT[label] if label in _OPTION_SHORT else label
    if same_day:
        return "0D " + base
    return base


def _confluence_markers(
    live: TerrainSnapshot, tk: str, now: datetime, spot: float | None
) -> list[dict[str, Any]]:
    """Levels carried from this same priced snapshot, plus the session levels already published.

    And the one-day move around the live price `spot`.
    """
    markers: list[dict[str, Any]] = []
    snap = canonical_price_level_snapshot(tk, now)
    if snap is not None:
        for value in snap.levels.values():
            row = value.to_contract_dict()
            price = row.get("price")
            if price is not None:
                short = row.get("short")
                markers.append(
                    {
                        "label": row["label"],
                        "short": short if isinstance(short, str) and short else row["label"],
                        "title": row["label"],
                        "lane": "session",
                        "price": price,
                    }
                )
    served = live.to_dict()
    for gid, label in OPTION_LEVELS:
        price = served[gid]
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
        price = live.same_day.get(gid)  # an unavailable snapshot holds no same-day level
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
    move = expected_move(live.implied_1d_move, spot)
    if move is not None:
        markers.append(
            {
                "label": "+1σ move",
                "short": "EM+",
                "title": "Expected move, one day, upper",
                "lane": "session",
                "price": move[0],
            }
        )
        markers.append(
            {
                "label": "−1σ move",
                "short": "EM−",
                "title": "Expected move, one day, lower",
                "lane": "session",
                "price": move[1],
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


def _level_named(levels: list[dict[str, Any]], abbrev: str) -> dict[str, Any] | None:
    for level in levels:
        if level["abbrev"] == abbrev:
            return level
    return None


def _move_text(low: dict[str, Any] | None, high: dict[str, Any] | None) -> str | None:
    if low is None or high is None:
        return None
    return low["price_text"] + "–" + high["price_text"]


def _ranked_matrix(snap: TerrainSnapshot, spot: float, chosen: str, dte: float) -> dict[str, Any]:
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
    """The matrix's status line: the levels' word, the chain's time and age, and why."""
    parts = [
        verdict["levels_state"],
        f"chain as of {ct_label(fetched)}, {age_text(now - fetched)} old",
    ]
    if verdict["levels_stale_reason"]:
        parts.append(verdict["levels_stale_reason"])
    return " · ".join(parts)


def confluence_payload(tk: str, expiry: str | None, now: datetime) -> dict[str, Any]:
    """Return the ranking of the priced chain, for the expiry the operator picks."""
    published = published_levels(tk)
    if published is None or not published.snap.books or published.snap.spot is None:
        return unavailable(tk, "no priced chain is held for this ticker", **_rail([], []))
    live, priced_at = published.snap, published.snap.spot
    today = now.strftime("%Y-%m-%d")
    listed = [e for e in _confluence_expiries(live.books, live.expiry_dte) if e["expiry"] >= today]
    if not listed:
        return unavailable(tk, "no expiry on this chain is still open", **_rail([], []))
    chosen = expiry
    if not isinstance(chosen, str) or chosen < today:
        live_listed = [e for e in listed if e["dte"] is not None and e["dte"] >= 0]
        chosen = (live_listed or listed)[0]["expiry"]
    match = next((e for e in listed if e["expiry"] == chosen), None)
    if match is None or match["dte"] is None:
        absent = match is None
        reason = (
            "that expiry is not on the priced chain"
            if absent
            else "that expiry did not carry days to expiration"
        )
        return unavailable(tk, reason, expiries=listed, **_rail([], []))
    stored = _ranked_matrix(live, priced_at, chosen, match["dte"])
    fetched = published.computed_ts_utc
    live_spot, _src, live_ts = resolve_spot(tk, now=now.timestamp())
    markers = _confluence_markers(live, tk, now, live_spot)
    levels = _screen_levels(markers)
    flip = _level_named(levels, "Flip")
    pin = _level_named(levels, "Pin")
    em_up = _level_named(levels, "EM+")
    em_dn = _level_named(levels, "EM−")
    body = {key: value for key, value in stored.items() if key not in ("ranked", "strikes")}
    ranked = sorted(stored["ranked"])
    lo, hi, view = window(ranked, nearest_strike(ranked, live_spot), "auto", None, 0)
    body["rows"] = window_rows(stored, ranked[lo : hi + 1])
    if view["note"] is not None:
        body["notes"] = [*body["notes"], view["note"]]
    body.update(at_price(body["rows"], stored["strikes"], live_spot))
    low = None
    high = None
    if em_dn is not None:
        low = em_dn["price"]
    if em_up is not None:
        high = em_up["price"]
    for row in body["rows"]:
        row["inside"] = within(low, high, row["strike"])  # inside the one-day move
    body.update(
        {
            "ticker": tk,
            "available": True,
            "reason": None,
            "expiry": chosen,
            "expiries": listed,
            "spot_as_of_ts_utc": live_ts,
            # the distances and the spot line are from the live price: its mark
            **price_mark(tk, live_ts, now.timestamp()),
            # the levels' one verdict (terrain_staleness): its word, the chain's time and age,
            # and why when it is not LIVE or CLOSE (AGENTS rule 5)
            "status_text": _chain_status(
                terrain_staleness(fetched, tk, now=now.timestamp()), fetched, now.timestamp()
            ),
            **_rail(levels, body["rows"]),
            "regime": live.regime,
            "flip_text": None if flip is None else flip["price_text"],
            "pin_text": None if pin is None else pin["price_text"],
            "pin_note": pin_note(live),
            "move_text": _move_text(em_dn, em_up),
        }
    )
    return body
