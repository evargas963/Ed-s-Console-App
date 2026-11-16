"""The `strikes` panel: the published levels' per-strike rows, each windowed for its reader.

GEX by Strike, the Gamma chart's profiles, Right Now's migration and the Desk map each read it
with their own window. Read from State: the published levels and the live price.
"""

from __future__ import annotations

from typing import Any

from numeric_contract import dollars_text, strike_text
from push.answers import unavailable
from push.spot import resolve_spot
from push.strike_rows import max_abs_served, served, window_asked, windowed
from push.verdict import terrain_cache_get
from terrain_engine import (
    MigrationRow,
    StrikeRow,
    level_moves,
    nearest_strike,
    per_strike_view,
    positioning_migration,
    side_total,
)


def _served_migration(row: MigrationRow) -> dict[str, Any]:
    """Return a migration row as the page draws it: its fields by name, its change's text."""
    return {**row._asdict(), "change_text": migration_change_text(row.change)}


def served_level_move(move: dict[str, Any]) -> dict[str, Any]:
    """Return one level's move since the prior day with its texts, as the screen shows them.

    Each day as its strike (None: not known), and the change (level_change_text).
    """
    return {
        **move,
        "prior_text": strike_text(move["prior"]),
        "today_text": strike_text(move["today"]),
        "change_text": level_change_text(move["change"]),
    }


def level_change_text(change: float | None) -> str | None:
    """Return a level's move since the prior day as the screen shows it.

    Signed, as a strike is listed ('+5', '-2.5'); 'unchanged' for none; None unless both days
    are known.
    """
    if change is None:
        return None
    if change == 0:
        return "unchanged"
    return ("+" if change > 0 else "-") + strike_text(abs(change))


def migration_change_text(change: float | None) -> str | None:
    """Return a strike's net GEX change since the prior session as the screen shows it.

    "▲$1.23M" grew, "▼$1.23M" shrank; None when either day has no value.
    """
    if change is None:
        return None
    return ("▲" if change >= 0 else "▼") + dollars_text(abs(change))


def _side_sums(rows: list[StrikeRow], spot: float | None) -> dict[str, Any] | None:
    """Return the GEX summed below and above `spot`, with their texts; None without both."""
    if not rows or spot is None:
        return None
    # each row as _per_strike_rows made it: a finite strike, its GEX finite or None
    below = side_total([r.value for r in rows if r.strike < spot])
    above = side_total([r.value for r in rows if r.strike > spot])
    return {
        "gex_below": below,
        "gex_above": above,
        "gex_below_text": dollars_text(below),
        "gex_above_text": dollars_text(above),
    }


def strikes(ticker: str, now: float, params: dict[str, Any]) -> dict[str, Any]:
    """Return the per-strike rows at `now` in the window `params` ask for (the `strikes` panel).

    `ticker` is the levels' own key; `params` the reader's window (window_asked). The page's
    socket sends it to GEX by Strike, the Gamma chart's profile, Right Now's migration and the
    Desk map, each its own panel with its own window (terrain_strikes_payload).
    """
    asked = window_asked(params)
    if isinstance(asked, str):
        return unavailable(ticker, asked)
    return terrain_strikes_payload(ticker, *asked, now)


def terrain_strikes_payload(
    tk: str, scope: str, centre: float | None, shift: int, now: float
) -> dict[str, Any]:
    """Return the per-strike rows of the published levels at `now`, each windowed for its panel.

    Windowed by windowed: today's GEX and volume (all, near, far expiries), the Chart view's DEX
    and OI, with each list's view; the side sums, the largest-GEX strike and the day-over-day
    migration are of every strike.
    """
    # today's per-strike rows: the published levels' own (_publish_levels' `_per_strike`,
    # terrain_engine.per_strike_view: {all, near, far} of StrikeRow, and the dex and oi rows),
    # served as-is; with no levels published, that view of no book: no rows
    levels, verdict = terrain_cache_get(tk, now)
    # no levels published for tk: no rows, no walls; no prior day captured: no prior rows. The
    # prior day's levels are set with every chain the levels are published from.
    snap = None if levels is None else levels.snap
    prior_day = None if levels is None else levels.prior_day
    rows = per_strike_view({}, {}) if snap is None else snap.per_strike
    prior = per_strike_view({}, {}) if prior_day is None else prior_day.per_strike
    walls = (None, None) if snap is None else (snap.call_wall, snap.put_wall)
    today = {k: rows[k] for k in ("all", "near", "far")}
    measures = {m: rows[m] for m in ("dex", "oi")}
    live_spot, _live_src, _live_ts = resolve_spot(tk, now=now)  # the one spot on every screen
    migration = {
        sc: positioning_migration(today[sc], prior[sc], *walls) for sc in ("all", "near", "far")
    }
    lists = {**today, **measures}
    windows = {
        name: windowed(
            rows, nearest_strike([r.strike for r in rows], live_spot), scope, centre, shift
        )
        for name, rows in lists.items()
    }
    for sc in ("all", "near", "far"):  # the migration panel scales today's and the prior day's bars
        drawn = {r.strike for r in windows[sc][0]}
        both = [
            abs(v)
            for r in migration[sc]["rows"]
            if r.strike in drawn
            for v in (r.value, r.prior)
            if v is not None
        ]
        both += [windows[sc][1]["max_abs"]] if windows[sc][1]["max_abs"] is not None else []
        windows[sc][1]["max_abs_with_prior"] = max(both) if both else None
    return {
        "ticker": tk,
        # each strike's net GEX $ and volume, by name, with their texts (served)
        "today": {sc: [served(r, "gex") for r in windows[sc][0]] for sc in ("all", "near", "far")},
        # the Chart view's DEX and OI profiles: each measure's window (terrain_engine
        # _per_strike_measure_rows) and its largest-magnitude row, on screen or not (the label)
        "measures": {
            m: {
                "rows": [served(r, m) for r in windows[m][0]],
                "view": windows[m][1],
                "max_abs_row": max_abs_served(rows, m),
            }
            for m, rows in measures.items()
        },
        # each scope's window: its centre strike and the largest |value| drawn
        "views": {sc: windows[sc][1] for sc in ("all", "near", "far")},
        "today_side_sums": _side_sums(today["all"], live_spot),
        "spot_strike": nearest_strike([r.strike for r in today["all"]], live_spot),
        # the row with the largest net GEX magnitude, on screen or not (the chart labels it)
        "max_abs_row": max_abs_served(today["all"], "gex"),
        # each row with its change as the screen shows it (_served_migration), and the strikes
        # that grew, shrank and traded most, each list as the screen shows it
        "migration": {
            sc: {
                **m,
                "rows": [_served_migration(r) for r in m["rows"]],
                "grew_text": "/".join(map(strike_text, m["grew"])),
                "shrank_text": "/".join(map(strike_text, m["shrank"])),
                "busiest_text": "–".join(map(strike_text, m["busiest"])),
            }
            for sc, m in migration.items()
        },
        # the call wall, put wall and gamma flip today against the prior day's own, each with its
        # texts as the screen shows them
        "level_moves": [served_level_move(v) for v in level_moves(snap, prior_day)],
        # the levels verdict these rows carry (LIVE, CLOSE, STALE, NOT LIVE), their time and age
        **verdict,
    }
