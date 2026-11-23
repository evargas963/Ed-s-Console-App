"""The `strikes` panel: the published levels' per-strike rows of the chosen expiry, windowed.

GEX by Strike, the Gamma chart's profiles and Right Now's migration each read it with their own
window, at the page's one expiry choice. Read from State: the published levels and
the live price.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal, TypedDict

from calc.terrain_engine import (
    ABOVE_CALL_WALL,
    BELOW_PUT_WALL,
    INSIDE_WALLS,
    LEVELS_COMPARED,
    OPTION_LEVELS,
    LevelMove,
    MigrationRow,
    PositioningMigration,
    StrikeRow,
    StrikeRows,
    level_moves,
    nearest_strike,
    per_strike_view,
    positioning_migration,
)
from numeric_contract import dollars_text, strike_text
from push.answers import NotAvailable, not_available
from push.expiries import expiry_label
from push.spot import resolve_spot
from push.strike_rows import (
    BarView,
    ServedRow,
    ServedValue,
    expiry_unreadable,
    max_abs_served,
    rows_of,
    served,
    window_asked,
    windowed,
)
from push.verdict import LEVELS_STALE, LevelsVerdict, terrain_cache_get


class ShownMigrationRow(TypedDict):
    """A migration row as the page draws it (_served_migration): its fields, its change's text."""

    strike: float
    value: float | None
    prior: float | None
    change: float | None
    change_text: str | None


class ShownLevelMove(TypedDict):
    """One level's move since the prior day as the screen shows it (served_level_move).

    The level, each day's strike and the change between them, then each as its text: the level
    as the screen names it (LEVEL_TEXT).
    """

    level: str
    prior: float | None
    today: float | None
    change: float | None
    level_text: str
    prior_text: str | None
    today_text: str | None
    change_text: str | None


class ShownMigration(TypedDict):
    """The day-over-day migration as the screen shows it (_shown_migration).

    positioning_migration's answer with each row as the page draws it, then the strikes that
    grew, shrank and traded most as the screen lists them, where the busiest sit against the
    walls as the screen says it (BUSIEST_VS_WALLS_TEXT; None with no such place), why it compares
    nothing (None when it compares) and what a session volume of 0 means (None unless 0).
    """

    rows: list[ShownMigrationRow]
    compared: bool
    grew: list[float]
    shrank: list[float]
    busiest: list[float]
    busiest_vs_walls: str | None
    volume_total: float | None
    grew_text: str
    shrank_text: str
    busiest_text: str
    busiest_vs_walls_text: str | None
    note: str | None
    volume_zero_text: str | None


class MeasureWindow(TypedDict):
    """One of the Chart view's profiles, DEX or open interest (terrain_strikes_payload).

    Its window's rows as the page draws them, the window's view, and its row with the largest
    magnitude, on screen or not.
    """

    rows: list[ServedValue]
    view: BarView
    max_abs_row: ServedValue | None


class GexView(BarView):
    """The GEX window's view: its own, and the largest |value| drawn with the prior day's."""

    max_abs_with_prior: float | None


class StrikesPanel(LevelsVerdict):
    """The `strikes` panel (terrain_strikes_payload): one expiry's per-strike rows, windowed.

    The expiry as the screen names it, the GEX window's rows and view, the DEX and open interest
    profiles by name, the row with the largest net GEX, the day-over-day migration and the level
    moves, and the levels' verdict these rows carry.
    """

    ticker: str
    expiry: str | None
    expiry_text: str
    today: list[ServedRow]
    measures: dict[str, MeasureWindow]
    view: GexView
    max_abs_row: ServedRow | None
    migration: ShownMigration
    level_moves: list[ShownLevelMove]


class NotListed(LevelsVerdict):
    """The `strikes` panel's answer for an expiry the published chain does not list.

    Why, beside the levels' verdict.
    """

    ticker: str
    available: Literal[False]
    reason: str


#: each level compared day over day (terrain_engine.LEVELS_COMPARED) by its name in the one list
LEVEL_TEXT = {key: name for key, name in OPTION_LEVELS if key in LEVELS_COMPARED}
#: where the busiest strikes sit against the largest call and put gamma strikes, as the screen
#: says it
BUSIEST_VS_WALLS_TEXT = {
    ABOVE_CALL_WALL: "ABOVE the largest call gamma strike",
    BELOW_PUT_WALL: "BELOW the largest put gamma strike",
    INSIDE_WALLS: "between the largest put and call gamma strikes",
}


def _served_migration(row: MigrationRow) -> ShownMigrationRow:
    """Return a migration row as the page draws it: its fields by name, its change's text."""
    return {
        "strike": row.strike,
        "value": row.value,
        "prior": row.prior,
        "change": row.change,
        "change_text": migration_change_text(row.change),
    }


def served_level_move(move: LevelMove) -> ShownLevelMove:
    """Return one level's move since the prior day with its texts, as the screen shows them.

    Each day as its strike (None: not known), and the change (level_change_text).
    """
    return {
        "level": move.level,
        "prior": move.prior,
        "today": move.today,
        "change": move.change,
        "level_text": LEVEL_TEXT[move.level],
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
    window: tuple[Sequence[StrikeRow], BarView], migration: PositioningMigration
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
#: what a session volume of 0 means, by the chain's verdict: a stale chain's rows are its snapshot
ZERO_VOLUME_STALE = (
    "zero volume here is the SNAPSHOT, not the session — this chain is stale; see the source "
    "badge above"
)
ZERO_VOLUME = (
    "no option volume yet this session — the counter resets at the new session and fills from "
    "the open"
)


def _shown_migration(
    m: PositioningMigration, note: str | None, levels_state: str
) -> ShownMigration:
    """Return the migration as the screen shows it, with `note`: why it compares nothing.

    `note` is None when it compares. Each row with its change's text (_served_migration), the
    strikes that grew, shrank and traded most, each list as the screen shows it, and what a
    session volume of 0 means (None unless 0).
    """
    zero = None
    if m["volume_total"] == 0:
        zero = ZERO_VOLUME_STALE if levels_state == LEVELS_STALE else ZERO_VOLUME
    where = m["busiest_vs_walls"]
    return {
        "rows": [_served_migration(r) for r in m["rows"]],
        "compared": m["compared"],
        "grew": m["grew"],
        "shrank": m["shrank"],
        "busiest": m["busiest"],
        "busiest_vs_walls": m["busiest_vs_walls"],
        "volume_total": m["volume_total"],
        "grew_text": "/".join(map(strike_text, m["grew"])),
        "shrank_text": "/".join(map(strike_text, m["shrank"])),
        "busiest_text": "–".join(map(strike_text, m["busiest"])),
        "busiest_vs_walls_text": None if where is None else BUSIEST_VS_WALLS_TEXT[where],
        "note": note,
        "volume_zero_text": zero,
    }


def strikes(
    ticker: str, now: float, params: dict[str, Any]
) -> StrikesPanel | NotListed | NotAvailable:
    """Return the per-strike rows at `now` in the window and expiry `params` ask for.

    The `strikes` panel. `ticker` is the levels' own key; `params` the reader's window
    (window_asked) and the page's one expiry choice, `expiry`: a listed expiry date, or None for
    every expiry. The page's socket sends it to GEX by Strike, the Gamma chart's profile and
    Right Now's migration, each its own panel with its own window (terrain_strikes_payload).
    """
    asked = window_asked(params)
    if isinstance(asked, str):
        return not_available(ticker, asked)
    unreadable = expiry_unreadable(params)
    if unreadable is not None:
        return not_available(ticker, unreadable)
    return terrain_strikes_payload(ticker, *asked, params["expiry"], now)


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


def terrain_strikes_payload(
    tk: str, scope: str, centre: float | None, shift: int, expiry: str | None, now: float
) -> StrikesPanel | NotListed:
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
    no_book = per_strike_view({}, {}, {}, {})
    today = no_book if snap is None else rows_of(snap.per_strike, expiry)
    if today is None:
        return {
            "ticker": tk,
            "available": False,
            **verdict,
            "reason": f"the chain lists no contracts for {expiry}",
        }
    prior = None if prior_day is None else rows_of(prior_day.per_strike, expiry)
    # a prior day that holds no levels, or lists no contract of this expiry, holds no book of it:
    # the producer's view of no book, so no strike is compared
    prior_book = no_book if prior is None else prior
    walls = (None, None) if snap is None else (snap.call_wall, snap.put_wall)
    live_spot, _live_src, _live_ts = resolve_spot(tk, now=now)  # the one spot on every screen
    migration = positioning_migration(today["gex"], prior_book["gex"], *walls)
    # the GEX window is around the strike at the price of this expiry's GEX strikes; each of the
    # Chart view's profiles around the one of its own strikes
    spot_strike = nearest_strike([r.strike for r in today["gex"]], live_spot)
    gex = windowed(today["gex"], spot_strike, scope, centre, shift)
    windows = {
        m: windowed(
            today[m], nearest_strike([r.strike for r in today[m]], live_spot), scope, centre, shift
        )
        for m in ("dex", "oi")
    }
    # every row's marks, in every list: the strike at the price (of this expiry's GEX strikes)
    # and the walls of the levels these rows are
    marks = {"spot": spot_strike, "call": walls[0], "put": walls[1]}
    return {
        "ticker": tk,
        # the expiry these rows are (None: every expiry), as the screen names it
        "expiry": expiry,
        "expiry_text": ALL_EXPIRATIONS if expiry is None else expiry_label(expiry),
        # each strike's net GEX $ and volume, by name, with their texts and marks (served)
        "today": [served(r, "gex", marks) for r in gex[0]],
        # the Chart view's DEX and OI profiles: each measure's window (terrain_engine
        # _per_strike_measure_rows) and its largest-magnitude row, on screen or not (the label)
        "measures": {
            m: {
                "rows": [served(r, m, marks) for r in windows[m][0]],
                "view": windows[m][1],
                "max_abs_row": max_abs_served(today[m], m, marks),
            }
            for m in ("dex", "oi")
        },
        # the GEX window: its centre strike, the largest |value| drawn, and with the prior day's
        "view": {**gex[1], "max_abs_with_prior": _scale_with_prior(gex, migration)},
        # the row with the largest net GEX magnitude, on screen or not (the chart labels it)
        "max_abs_row": max_abs_served(today["gex"], "gex", marks),
        "migration": _shown_migration(
            migration,
            _not_compared(migration, prior_day is not None, prior, expiry),
            verdict["levels_state"],
        ),
        # the call wall, put wall and gamma flip today against the prior day's own, each with its
        # texts as the screen shows them
        "level_moves": [served_level_move(v) for v in level_moves(snap, prior_day)],
        # the levels verdict these rows carry (LIVE, CLOSE, STALE, NOT LIVE), their time and age
        **verdict,
    }
