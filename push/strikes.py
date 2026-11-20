"""The `strikes` panel: the published levels' per-strike rows of the chosen expiry, windowed.

GEX by Strike, the Gamma chart's profiles and Right Now's migration each read it with their own
window, at the page's one expiry choice. Read from State: the published levels and
the live price.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict
from typing import Any

from calc.terrain_engine import (
    LevelMove,
    MigrationRow,
    PerStrikeView,
    PositioningMigration,
    StrikeRows,
    level_moves,
    nearest_strike,
    per_strike_view,
    positioning_migration,
)
from numeric_contract import dollars_text, strike_text
from push.answers import unavailable
from push.expiries import expiry_label
from push.spot import resolve_spot
from push.strike_rows import BarRow, max_abs_served, served, window_asked, windowed
from push.verdict import terrain_cache_get


def _served_migration(row: MigrationRow) -> dict[str, Any]:
    """Return a migration row as the page draws it: its fields by name, its change's text."""
    return {**row._asdict(), "change_text": migration_change_text(row.change)}


def served_level_move(move: LevelMove) -> dict[str, Any]:
    """Return one level's move since the prior day with its texts, as the screen shows them.

    Each day as its strike (None: not known), and the change (level_change_text).
    """
    return {
        **asdict(move),
        "prior_text": strike_text(move.prior),
        "today_text": strike_text(move.today),
        "change_text": level_change_text(move.change),
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


def _scale_with_prior(
    window: tuple[Sequence[BarRow], dict[str, Any]], migration: PositioningMigration
) -> float | None:
    """Return the largest |value| the migration panel draws: today's and the prior day's.

    Of the strikes in today's window; None when none of them has a value on either day.
    """
    drawn = {r.strike for r in window[0]}
    both = [
        abs(v)
        for r in migration["rows"]
        if r.strike in drawn
        for v in (r.value, r.prior)
        if v is not None
    ]
    drawn_max = window[1]["max_abs"]
    if drawn_max is not None:
        both.append(drawn_max)
    return max(both) if both else None


#: the expiry choice of every expiry (None), as the expiry dropdown names it
ALL_EXPIRATIONS = "All Expirations"
#: why the migration compares nothing while no prior day's levels are held
NO_PRIOR_DAY = "The first day-over-day comparison lands after the next wide morning capture."
#: why the migration compares nothing while both days are held but no strike is known on both
NO_STRIKE_ON_BOTH_DAYS = "No strike has a net GEX on both days."


def _shown_migration(m: PositioningMigration, note: str | None) -> dict[str, Any]:
    """The migration as the screen shows it, with `note`: why it compares nothing (None: it does).

    Each row with its change's text (_served_migration), and the strikes that grew, shrank and
    traded most, each list as the screen shows it.
    """
    return {
        **m,
        "rows": [_served_migration(r) for r in m["rows"]],
        "grew_text": "/".join(map(strike_text, m["grew"])),
        "shrank_text": "/".join(map(strike_text, m["shrank"])),
        "busiest_text": "–".join(map(strike_text, m["busiest"])),
        "note": note,
    }


def strikes(ticker: str, now: float, params: dict[str, Any]) -> dict[str, Any]:
    """Return the per-strike rows at `now` in the window and expiry `params` ask for.

    The `strikes` panel. `ticker` is the levels' own key; `params` the reader's window
    (window_asked) and the page's one expiry choice, `expiry`: a listed expiry date, or None for
    every expiry. The page's socket sends it to GEX by Strike, the Gamma chart's profile and
    Right Now's migration, each its own panel with its own window (terrain_strikes_payload).
    """
    asked = window_asked(params)
    if isinstance(asked, str):
        return unavailable(ticker, asked)
    expiry = params.get("expiry")
    if "expiry" not in params or not (expiry is None or isinstance(expiry, str)):
        return unavailable(ticker, f"expiry {expiry!r} is not an expiry date or null")
    return terrain_strikes_payload(ticker, *asked, expiry, now)


def _not_compared(
    m: PositioningMigration, prior_held: bool, prior: StrikeRows | None, expiry: str | None
) -> str | None:
    """Return why the migration compares no strike; None when it compares one.

    No prior day's levels held (`prior_held` false); the prior day's chain not listing `expiry`
    (`prior` None); or no strike with a net GEX on both days.
    """
    if m["compared"]:
        return None
    if not prior_held:
        return NO_PRIOR_DAY
    if prior is None:
        return f"The prior day's chain lists no contracts for {expiry}."
    return NO_STRIKE_ON_BOTH_DAYS


def _rows_of(view: PerStrikeView, expiry: str | None) -> StrikeRows | None:
    """Return the rows of `expiry` (None: the whole book's); None when `view` lists no such one."""
    return view if expiry is None else view["by_expiry"].get(expiry)


def terrain_strikes_payload(
    tk: str, scope: str, centre: float | None, shift: int, expiry: str | None, now: float
) -> dict[str, Any]:
    """Return the per-strike rows of the published levels at `now`, each windowed for its panel.

    The rows are `expiry`'s (None: every expiry's, the whole book). Windowed by windowed: its GEX
    and volume and the Chart view's DEX and OI, with each list's view; the largest-GEX strike and
    the day-over-day migration are of every strike of that expiry, the prior day's rows its own
    of the same expiry. An expiry the published chain does not list is answered with why, never
    with another expiry's rows.
    """
    # the published levels' own per-strike rows (calc.terrain_engine.per_strike_view), served
    # as-is; with no levels published, that view of no book: no rows
    levels, verdict = terrain_cache_get(tk, now)
    # no levels published for tk: no rows, no walls; no prior day captured: no prior rows. The
    # prior day's levels are set with every chain the levels are published from.
    snap = None if levels is None else levels.snap
    prior_day = None if levels is None else levels.prior_day
    no_book = per_strike_view({}, {})
    today = no_book if snap is None else _rows_of(snap.per_strike, expiry)
    if today is None:
        return unavailable(tk, f"the chain lists no contracts for {expiry}", **verdict)
    prior = None if prior_day is None else _rows_of(prior_day.per_strike, expiry)
    # a prior day that holds no levels, or lists no contract of this expiry, holds no book of it:
    # the producer's view of no book, so no strike is compared
    prior_book = no_book if prior is None else prior
    walls = (None, None) if snap is None else (snap.call_wall, snap.put_wall)
    live_spot, _live_src, _live_ts = resolve_spot(tk, now=now)  # the one spot on every screen
    migration = positioning_migration(today["gex"], prior_book["gex"], *walls)
    lists = {m: today[m] for m in ("gex", "dex", "oi")}
    windows = {
        name: windowed(
            rows, nearest_strike([r.strike for r in rows], live_spot), scope, centre, shift
        )
        for name, rows in lists.items()
    }
    # every row's marks, in every list: the strike at the price (of this expiry's GEX strikes)
    # and the walls of the levels these rows are
    marks = {
        "spot": nearest_strike([r.strike for r in today["gex"]], live_spot),
        "call": walls[0],
        "put": walls[1],
    }
    return {
        "ticker": tk,
        # the expiry these rows are (None: every expiry), as the screen names it
        "expiry": expiry,
        "expiry_text": ALL_EXPIRATIONS if expiry is None else expiry_label(expiry),
        # each strike's net GEX $ and volume, by name, with their texts and marks (served)
        "today": [served(r, "gex", marks) for r in windows["gex"][0]],
        # the Chart view's DEX and OI profiles: each measure's window (terrain_engine
        # _per_strike_measure_rows) and its largest-magnitude row, on screen or not (the label)
        "measures": {
            m: {
                "rows": [served(r, m, marks) for r in windows[m][0]],
                "view": windows[m][1],
                "max_abs_row": max_abs_served(lists[m], m, marks),
            }
            for m in ("dex", "oi")
        },
        # the GEX window: its centre strike, the largest |value| drawn, and with the prior day's
        "view": {
            **windows["gex"][1],
            "max_abs_with_prior": _scale_with_prior(windows["gex"], migration),
        },
        # the row with the largest net GEX magnitude, on screen or not (the chart labels it)
        "max_abs_row": max_abs_served(today["gex"], "gex", marks),
        "migration": _shown_migration(
            migration, _not_compared(migration, prior_day is not None, prior, expiry)
        ),
        # the call wall, put wall and gamma flip today against the prior day's own, each with its
        # texts as the screen shows them
        "level_moves": [served_level_move(v) for v in level_moves(snap, prior_day)],
        # the levels verdict these rows carry (LIVE, CLOSE, STALE, NOT LIVE), their time and age
        **verdict,
    }
