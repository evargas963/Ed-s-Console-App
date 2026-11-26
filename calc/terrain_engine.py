"""Terrain pipeline — levels only, no model stack.

This module is pure: it takes contracts + spot and returns a payload. Fetching and
scheduling live in the caller, so this stays trivially testable.
"""

from __future__ import annotations

import bisect
import math
import statistics
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import NamedTuple, TypedDict

from calc.confluence_composite import iv_by_strike
from calc.math_exposure_core import (
    Bucket,
    ExposureDiagnostics,
    book_net_gex,
    bucket_metric,
    exposure_books,
    exposures_have_dollar_gex,
    merge_exposure_books,
    net_gex_dollars_at_strike,
    pick_absolute_gamma_strike,
    pick_delta_wall_strikes,
    pick_gamma_wall_strikes,
    pick_key_delta_strike,
    pick_volatility_point_strikes,
    put_call_oi_ratio,
    put_call_volume_ratio,
    schwab_iv_to_sigma,
    strike_total_oi,
    strike_total_volume,
)
from calc.math_levels import (
    CharmBucket,
    compute_charm_by_strike,
    compute_gamma_profile,
    compute_gamma_support_levels,
    compute_max_pain,
    contract_inputs,
    gamma_at_price,
    gamma_flip_from_profile,
    merge_charm_maps,
    pick_charm_wall_strikes,
    repriced_to_close,
    unpriced_note,
)
from calc.terrain_read import (
    FLIP_RELATION_TEXT,
    LEVEL_ABOVE,
    LEVEL_BELOW,
    build_terrain_read,
    flip_note,
    level_side,
    price_side,
)
from numeric_contract import (
    count_text,
    dollars_text,
    fixed_text,
    price_text,
)
from option_contract import OptionContract
from time_et import (
    ET,
    SETTLEMENT_AM,
    Session,
    option_close_product,
    time_to_expiry_years,
)

#: Payload schema version — bump on any field change so the UI can fail closed.
TERRAIN_SCHEMA_VERSION = 7

#: an exposure book's key: (expiry, days to expiry)
type ExpiryKey = tuple[str | None, float | None]
#: one (expiry, days to expiry) group's book with its diagnostics, as exposure_books holds it
type Book = tuple[dict[float, Bucket], ExposureDiagnostics]


class StrikeValue(NamedTuple):
    """One strike's value on a per-strike bar (net DEX $, open interest, net vanna or charm).

    A value not known is None.
    """

    strike: float
    value: float | None


class StrikeRow(NamedTuple):
    """A GEX-by-strike row: its value is the strike's net GEX $; a value not known is None."""

    strike: float
    value: float | None
    volume: float | None


class MigrationRow(NamedTuple):
    """A strike's net GEX today against the prior session's; a value not known is None."""

    strike: float
    value: float | None
    prior: float | None
    change: float | None


class MeasureRows(TypedDict):
    """The full book's DEX, OI and net vanna rows, one per known strike."""

    dex: list[StrikeValue]
    oi: list[StrikeValue]
    vanna: list[StrikeValue]


class StrikeRows(MeasureRows):
    """One book's per-strike rows: its GEX rows beside its DEX, OI, net vanna and net charm rows.

    `settled`: the book's settled contracts, which vanna's and charm's sums leave out.
    """

    gex: list[StrikeRow]
    charm: list[StrikeValue]
    settled: int


class PerStrikeView(StrikeRows):
    """per_strike_view's rows: the whole book's, and each listed expiry's own (`by_expiry`)."""

    by_expiry: dict[str, StrikeRows]


#: where the busiest strikes sit against the walls (PositioningMigration's busiest_vs_walls): all
#: above the call wall, all below the put wall, all between the two, or on both sides of the put
#: wall, of the call wall, or of both (_busiest_vs_walls)
ABOVE_CALL_WALL, BELOW_PUT_WALL, INSIDE_WALLS = "ABOVE_CALL_WALL", "BELOW_PUT_WALL", "INSIDE_WALLS"
ACROSS_PUT_WALL, ACROSS_CALL_WALL, ACROSS_WALLS = (
    "ACROSS_PUT_WALL",
    "ACROSS_CALL_WALL",
    "ACROSS_WALLS",
)


class PositioningMigration(TypedDict):
    """positioning_migration's answer for one book: the whole book's, or one expiry's."""

    rows: list[MigrationRow]
    compared: bool
    grew: list[float]
    shrank: list[float]
    busiest: list[float]
    busiest_vs_walls: str | None
    volume_total: float | None


class TerrainFields(TypedDict):
    """A snapshot as the terrain panel carries it (TerrainSnapshot.to_dict).

    Each field a reader of the panel takes, as the snapshot holds it, then each number as the
    screen shows it.
    """

    ticker: str
    schema_version: int
    regime: str
    headline: str
    headline_source: str
    gamma_flip: float | None
    call_wall: float | None
    put_wall: float | None
    absolute_gamma_strike: float | None
    pin_candidate: float | None
    max_pain: float | None
    max_pain_dte: float | None
    call_charm_wall: float | None
    put_charm_wall: float | None
    key_delta_strike: float | None
    hvp: float | None
    lvp: float | None
    net_gex_at_spot: float | None
    gsf: float | None
    grc: float | None
    same_day: dict[str, float | None]
    call_delta_wall: float | None
    put_delta_wall: float | None
    contracts_used: int
    strikes_used: int
    dollarized: bool
    flip_note: str | None
    error: str
    pcr_by_expiry: dict[str, float | None]
    atm_iv_pct_by_expiry: dict[str, float | None]
    pcr_all: float | None
    expiries: list[str]
    computed_ts_utc: float | None
    net_gex_at_spot_text: str | None
    contracts_used_text: str | None
    call_wall_text: str | None
    put_wall_text: str | None
    gamma_flip_text: str | None
    max_pain_text: str | None
    absolute_gamma_strike_text: str | None
    pin_candidate_text: str | None
    gsf_text: str | None
    grc_text: str | None
    hvp_text: str | None
    lvp_text: str | None
    key_delta_strike_text: str | None
    call_delta_wall_text: str | None
    put_delta_wall_text: str | None
    call_charm_wall_text: str | None
    put_charm_wall_text: str | None
    same_day_text: dict[str, str | None]
    pcr_all_text: str | None
    pcr_volume_all_text: str | None
    pcr_by_expiry_text: dict[str, str | None]
    pcr_volume_by_expiry_text: dict[str, str | None]


def _no_same_day_levels() -> dict[str, float | None]:
    """Return every same-day level (SAME_DAY_LEVELS) as not known."""
    return {name: None for name, _label in SAME_DAY_LEVELS}


@dataclass(frozen=True)
class TerrainSnapshot:
    """Everything the terrain tab renders, computed from one chain."""

    ticker: str
    spot: float | None
    schema_version: int = TERRAIN_SCHEMA_VERSION

    # regime
    regime: str = "UNAVAILABLE"
    headline: str = ""
    #: the headline's sources, shown on hover
    headline_source: str = ""

    # levels — chain scope for every level in this dataclass: FULL_BOOK (the wide
    # multi-expiry capture chain). The analytics summary_rows carry the SELECTED_EXPIRY
    # scope; the two scopes never share a payload field.
    gamma_flip: float | None = None
    call_wall: float | None = None
    put_wall: float | None = None
    #: Max TOTAL gamma — |call GEX$| + |put GEX$| — over the full
    #: book: the gross size, with no sign, so it says nothing about which way hedging goes.
    absolute_gamma_strike: float | None = None
    #: The highest open interest strike near the price (pin_by_open_interest): of an expiry
    #: settling at today's close, the strike with the most open interest within one expected move
    #: of the price, with its distance in expected moves (z = ln(price/strike) / (sigma *
    #: sqrt(T))), in strike widths, and the minutes to the close. None when nothing expires at
    #: today's close or no strike is that near.
    pin_candidate: float | None = None
    pin_expected_moves: float | None = None
    pin_strike_widths: float | None = None
    pin_minutes_to_close: float | None = None
    #: Max pain is defined PER EXPIRY (standard: the settlement price minimising intrinsic
    #: payout on ONE expiry's open interest): the FRONT expiry only, and max_pain_dte says
    #: which.
    max_pain: float | None = None
    max_pain_dte: float | None = None
    call_charm_wall: float | None = None
    put_charm_wall: float | None = None
    key_delta_strike: float | None = None
    hvp: float | None = None  # most NEGATIVE net GEX$ strike (amplification pocket)
    lvp: float | None = None  # most POSITIVE net GEX$ strike (damping pocket)

    #: Net GEX$ per 1% move AT SPOT — the regime's own number (regime = its sign).
    #: Disambiguates walls that share a strike.
    net_gex_at_spot: float | None = None

    #: Gamma Support Floor / Gamma Resistance Ceiling — computed from the SAME
    #: materialized profile as the flip. GSF = highest level
    #: below spot where the positive-gamma cushion has decayed to half its at-spot value
    #: (support ends BEFORE the flip's zero-crossing); GRC = the upside mirror, often
    #: at/beyond the call wall (resistance strengthens before it exhausts). None when not
    #: found, a negative regime included (no fabricated price).
    gsf: float | None = None
    grc: float | None = None

    #: The levels on a 0DTE basis (same_day_levels), every one of SAME_DAY_LEVELS; each is None
    #: while not known, an unavailable snapshot's all of them
    same_day: dict[str, float | None] = field(default_factory=_no_same_day_levels)
    #: the expiry the same-day levels were re-priced from to today's close (a model, said on
    #: hover); None when they are today's own expiry as held, or absent
    same_day_repriced_from: str | None = None
    #: which contracts the same-day levels' gamma curve could not price (unpriced_note, said on
    #: hover); None when it priced every one, or they are absent
    same_day_left_out: str | None = None

    #: Delta walls owned by THIS producer — same wide chain,
    #: one book. Concepts terrain does not compute (OI/vanna walls, inflections) do not
    #: get fields here and render BLANK with a withheld reason, never an analytics book.
    call_delta_wall: float | None = None
    put_delta_wall: float | None = None

    # provenance — never render a level without knowing where it came from
    contracts_used: int = 0
    strikes_used: int = 0
    dollarized: bool = False
    #: the note shown beside the gamma flip (calc.terrain_read.flip_note), None for none
    flip_note: str | None = None
    error: str = ""

    #: (price, net GEX) samples; kept OUT of to_dict() (~240 pairs).
    profile: list[tuple[float, float]] = field(
        default_factory=list[tuple[float, float]], repr=False
    )

    #: The LIVE per-strike map the walls were picked from; the per-strike panel reads it, at
    #: no additional vendor cost — the chain is already in hand. Kept OUT of to_dict() for the
    #: same reason as `profile`: too heavy for every poll; the strikes endpoint reads it directly.
    #: per_strike_view's rows (the whole book's gex, dex, oi, vanna and charm, and each expiry's);
    #: with no book priced, each is empty.
    per_strike: PerStrikeView = field(
        default_factory=lambda: per_strike_view({}, {}, {}, {}), repr=False
    )
    #: The exposure_books every number above was priced from ({(expiry, dte): (book, diag)}):
    #: the gamma-surface grid is shaped from them, so levels, per-strike rows and heatmap
    #: cells come from one pricing pass.
    books: dict[ExpiryKey, Book] = field(default_factory=dict[ExpiryKey, Book], repr=False)
    #: {strike: charm bucket} from compute_charm_by_strike -- the charm walls above and the
    #: charm-by-strike panel read the same map.
    charm_by_strike: dict[float, CharmBucket] = field(
        default_factory=dict[float, CharmBucket], repr=False
    )
    #: {expiry: {strike: charm bucket}} from the same function, one call per expiry.
    #: The confluence matrix reads the expiry it shows and does not call the function again.
    charm_by_expiry: dict[str | None, dict[float, CharmBucket]] = field(
        default_factory=dict[str | None, dict[float, CharmBucket]], repr=False
    )
    #: {expiry: {strike: vol points}} from iv_by_strike, one call per expiry.
    #: The confluence matrix reads the expiry it shows and does not call the blend again.
    iv_by_expiry: dict[str | None, dict[float, float | None]] = field(
        default_factory=dict[str | None, dict[float, float | None]], repr=False
    )
    #: the valuation instant every time to expiry in it was taken at (compute_terrain's `now`):
    #: a reader pricing more of the same chain prices it at that instant. None: nothing priced.
    valued_at: datetime | None = None
    #: {expiry: put OI / call OI} for each listed expiry: put/call OI (positions held)
    pcr_by_expiry: dict[str, float | None] = field(default_factory=dict[str, float | None])
    #: each expiry's ATM implied vol, percent (atm_sigma_by_expiry); None when a leg has no IV
    atm_iv_pct_by_expiry: dict[str, float | None] = field(default_factory=dict[str, float | None])
    #: {expiry: put volume / call volume} (today's trading)
    pcr_volume_by_expiry: dict[str, float | None] = field(default_factory=dict[str, float | None])
    #: the same two ratios over the whole book (every expiry)
    pcr_all: float | None = None
    pcr_volume_all: float | None = None
    #: every expiry the chain lists, ascending
    expiries: list[str] = field(default_factory=list[str])
    #: {expiry: Schwab's daysToExpiration as sent with this chain}
    expiry_dte: dict[str, float | None] = field(default_factory=dict[str, float | None])
    #: Wall-clock the chain behind per_strike was fetched — every consumer must be able to render
    #: an age on its face rather than implying "now".
    computed_ts_utc: float | None = None

    def level(self, name: str) -> float | None:
        """Return the option level `name`'s price (OPTION_LEVELS); None where it is not known."""
        price: float | None = getattr(self, name)
        return price

    def to_dict(self) -> TerrainFields:
        """Return the per-poll payload.

        The snapshot's fields, then the net gamma at spot, the contracts used, each option
        level's price (and each on the 0DTE basis) and the put/call ratios as the screen shows
        them. Not the heavy maps (profile, per_strike, books, charm_by_strike, charm_by_expiry,
        iv_by_expiry), which the server reads off the snapshot, nor the fields no reader of the
        payload takes: the pin's distances and the expiry the same-day levels were re-priced from
        (the notes say them), each expiry's days, and the volume ratios as numbers (their text
        is served). Nor the price they were computed at (`spot`): the price on every screen is
        the price row's alone (one producer).
        """
        return {
            "ticker": self.ticker,
            "schema_version": self.schema_version,
            "regime": self.regime,
            "headline": self.headline,
            "headline_source": self.headline_source,
            "gamma_flip": self.gamma_flip,
            "call_wall": self.call_wall,
            "put_wall": self.put_wall,
            "absolute_gamma_strike": self.absolute_gamma_strike,
            "pin_candidate": self.pin_candidate,
            "max_pain": self.max_pain,
            "max_pain_dte": self.max_pain_dte,
            "call_charm_wall": self.call_charm_wall,
            "put_charm_wall": self.put_charm_wall,
            "key_delta_strike": self.key_delta_strike,
            "hvp": self.hvp,
            "lvp": self.lvp,
            "net_gex_at_spot": self.net_gex_at_spot,
            "gsf": self.gsf,
            "grc": self.grc,
            "same_day": dict(self.same_day),
            "call_delta_wall": self.call_delta_wall,
            "put_delta_wall": self.put_delta_wall,
            "contracts_used": self.contracts_used,
            "strikes_used": self.strikes_used,
            "dollarized": self.dollarized,
            "flip_note": self.flip_note,
            "error": self.error,
            "pcr_by_expiry": dict(self.pcr_by_expiry),
            "atm_iv_pct_by_expiry": dict(self.atm_iv_pct_by_expiry),
            "pcr_all": self.pcr_all,
            "expiries": list(self.expiries),
            "computed_ts_utc": self.computed_ts_utc,
            "net_gex_at_spot_text": dollars_text(self.net_gex_at_spot),
            "contracts_used_text": count_text(self.contracts_used),
            "call_wall_text": price_text(self.call_wall),
            "put_wall_text": price_text(self.put_wall),
            "gamma_flip_text": price_text(self.gamma_flip),
            "max_pain_text": price_text(self.max_pain),
            "absolute_gamma_strike_text": price_text(self.absolute_gamma_strike),
            "pin_candidate_text": price_text(self.pin_candidate),
            "gsf_text": price_text(self.gsf),
            "grc_text": price_text(self.grc),
            "hvp_text": price_text(self.hvp),
            "lvp_text": price_text(self.lvp),
            "key_delta_strike_text": price_text(self.key_delta_strike),
            "call_delta_wall_text": price_text(self.call_delta_wall),
            "put_delta_wall_text": price_text(self.put_delta_wall),
            "call_charm_wall_text": price_text(self.call_charm_wall),
            "put_charm_wall_text": price_text(self.put_charm_wall),
            "same_day_text": {name: price_text(v) for name, v in self.same_day.items()},
            "pcr_all_text": fixed_text(self.pcr_all, 2),
            "pcr_volume_all_text": fixed_text(self.pcr_volume_all, 2),
            "pcr_by_expiry_text": {ex: fixed_text(v, 2) for ex, v in self.pcr_by_expiry.items()},
            "pcr_volume_by_expiry_text": {
                ex: fixed_text(v, 2) for ex, v in self.pcr_volume_by_expiry.items()
            },
        }


def _unavailable(ticker: str, spot: float | None, reason: str) -> TerrainSnapshot:
    read = build_terrain_read(spot=spot)
    return TerrainSnapshot(
        ticker=ticker,
        spot=spot,
        regime=read.regime,
        headline=read.headline,
        headline_source=read.headline_source,
        error=reason,
    )


def side_total(values: list[float | None]) -> float | None:
    """Return a total of strikes.

    Unknown with a strike not known or no strike at all, never the sum of the rest.
    """
    known = [v for v in values if v is not None]
    return sum(known) if values and len(known) == len(values) else None


def _per_strike_rows(exposures: dict[float, Bucket]) -> list[StrikeRow]:
    """Each strike's StrikeRow: its net GEX $ (1% move) and session volume.

    THE one producer of GEX-by-strike rows (live panel AND the prior-day ghost).

    The finished numbers are handed over as-is, never reassembled into synthetic
    contracts and recomputed.

    No fallbacks:
      * the bar is net GEX$ from a DOLLARIZED book, exact (a strike whose contracts have open
        interest 0 is a $0 bar). A strike whose GEX is not known (bucket_metric) keeps its row
        with None, so a total of its side is unknown too; a book built without spot has no rows.
      * volume is strike_total_volume, the one reader: Schwab's volumes as sent (0 is a real
        zero); None ("-") when a contract at the strike did not report it, never a partial sum.
    """
    if not exposures or not exposures_have_dollar_gex(exposures):
        return []
    rows: list[StrikeRow] = []
    for k, b in exposures.items():
        rows.append(StrikeRow(k, net_gex_dollars_at_strike(b), strike_total_volume(b)))
    rows.sort(key=lambda r: r.strike)
    return rows


#: the levels compared day over day (level_moves), in the order the page lists them
LEVELS_COMPARED = ("call_wall", "put_wall", "gamma_flip")


@dataclass(frozen=True)
class LevelMove:
    """One level today against the prior day's: change = today - prior, None without both."""

    level: str
    prior: float | None
    today: float | None
    change: float | None


def level_moves(today: TerrainSnapshot | None, prior: TerrainSnapshot | None) -> list[LevelMove]:
    """Return the call wall, put wall and gamma flip today against the prior day's own.

    Both days' levels are the one producer's (compute_terrain); none is held without that day.
    """
    moves: list[LevelMove] = []
    for name in LEVELS_COMPARED:
        was = None if prior is None else getattr(prior, name)
        now = None if today is None else getattr(today, name)
        change = None if was is None or now is None else now - was
        moves.append(LevelMove(level=name, prior=was, today=now, change=change))
    return moves


#: the largest total gamma strike last known in each column of Key Levels: the whole book's and the
#: same-day book's
type TotalGammaStrikes = tuple[float | None, float | None]
#: the columns, as the screen names them
TOTAL_GAMMA_COLUMNS = ("Regular", "0DTE")


@dataclass(frozen=True)
class TotalGammaChange:
    """The largest total gamma strike of one column, as it was and as it is."""

    column: str
    before: float
    after: float


@dataclass(frozen=True)
class TotalGammaMove:
    """The columns one publication moved the largest total gamma strike in, and its levels' time."""

    changes: tuple[TotalGammaChange, ...]
    at: float


@dataclass(frozen=True)
class TotalGammaRecord:
    """Each column's largest total gamma strike last known, and the newest move (None: none yet)."""

    known: TotalGammaStrikes = (None, None)
    move: TotalGammaMove | None = None


def total_gamma_strikes(snap: TerrainSnapshot) -> TotalGammaStrikes:
    """Return the largest total gamma strike of the whole book and of the same-day book."""
    return snap.absolute_gamma_strike, snap.same_day["absolute_gamma_strike"]


def total_gamma_record(
    last: TotalGammaRecord | None, snap: TerrainSnapshot, at: float
) -> TotalGammaRecord:
    """Return the record after the levels `snap`, published at `at`, from the one before them.

    `last` is the record of the levels published before (None: none were since the program
    started). A column moves when its strike is known now and differs from the one known last; a
    strike not known now keeps the one known last, so a strike gone for a while and back where it
    was is no move, and the first one known is none (nothing was known before it). With no column
    moved the newest move stands.
    """
    was = TotalGammaRecord() if last is None else last
    now = total_gamma_strikes(snap)
    known = tuple(n if n is not None else w for w, n in zip(was.known, now, strict=True))
    changes = tuple(
        TotalGammaChange(column, w, n)
        for column, w, n in zip(TOTAL_GAMMA_COLUMNS, was.known, now, strict=True)
        if w is not None and n is not None and n != w
    )
    move = TotalGammaMove(changes, at) if changes else was.move
    return TotalGammaRecord((known[0], known[1]), move)


def positioning_migration(
    today: list[StrikeRow],
    prior: list[StrikeRow],
    call_wall: float | None,
    put_wall: float | None,
) -> PositioningMigration:
    """Return day-over-day positioning of one book (the whole book's, or one expiry's).

    It is built from that book's GEX-by-strike rows today and in the prior capture.

    rows: each strike's MigrationRow (None where either day has no value); grew / shrank: the
    two strikes that gained / lost the most GEX; busiest: the two strikes with the most volume
    and where they sit against the walls; volume_total: the book's session volume (side_total).
    """
    prior_gex = {r.strike: r.value for r in prior}
    rows: list[MigrationRow] = []
    for r in today:
        gy = prior_gex.get(r.strike)
        change = r.value - gy if r.value is not None and gy is not None else None
        rows.append(MigrationRow(r.strike, r.value, gy, change))
    # each strike with a known change, largest gain first
    changes = sorted(
        ((r.strike, r.change) for r in rows if r.change is not None),
        key=lambda kc: kc[1],
        reverse=True,
    )
    grew = [k for k, c in changes if c > 0][:2]
    shrank = [k for k, c in changes if c < 0][-2:]
    vols = [(r.strike, r.volume) for r in today if r.volume]
    busiest = sorted(k for k, _v in sorted(vols, key=lambda kv: kv[1], reverse=True)[:2])
    return {
        "rows": rows,
        "compared": bool(changes),
        "grew": grew,
        "shrank": shrank,
        "busiest": busiest,
        "busiest_vs_walls": _busiest_vs_walls(busiest, call_wall, put_wall),
        "volume_total": side_total([r[2] for r in today]),
    }


def _busiest_vs_walls(
    busiest: list[float], call_wall: float | None, put_wall: float | None
) -> str | None:
    """Return where the busiest strikes sit against the walls; None when that is not known.

    Not known: no busiest strike, or a wall the place depends on not known. A strike on a wall
    is inside it; the busiest strikes on both sides of a wall are across it.
    """
    if not busiest:
        return None
    lo, hi = min(busiest), max(busiest)
    if call_wall is not None and lo > call_wall:
        return ABOVE_CALL_WALL
    if put_wall is not None and hi < put_wall:
        return BELOW_PUT_WALL
    across_put = put_wall is not None and lo < put_wall <= hi
    across_call = call_wall is not None and lo <= call_wall < hi
    if across_put and across_call:
        return ACROSS_WALLS
    if across_put and (call_wall is None or hi <= call_wall):
        return ACROSS_PUT_WALL
    if across_call and (put_wall is None or put_wall <= lo):
        return ACROSS_CALL_WALL
    if call_wall is not None and put_wall is not None and put_wall <= lo and hi <= call_wall:
        return INSIDE_WALLS
    return None


def nearest_position(ascending: list[float], spot: float) -> int:
    """Return where the strike nearest `spot` stands in `ascending` (the lower one on a tie).

    The one rule of nearness, for a caller that holds its strikes in order. -1 with no strike.
    """
    i = bisect.bisect_left(ascending, spot)
    if i == len(ascending) or (i > 0 and spot - ascending[i - 1] <= ascending[i] - spot):
        i -= 1
    return i


def nearest_strike(strikes: Iterable[float], spot: float | None) -> float | None:
    """Return the listed strike nearest `spot` (the lower one on a tie).

    It is the row every panel marks as spot. None without a spot or a strike.
    """
    ks = sorted(float(k) for k in strikes)
    if spot is None or not ks:
        return None
    return ks[nearest_position(ks, float(spot))]


#: The strikes a panel shows per scope: Auto and Wider a count centred on the price, All every one.
SCOPES = ("auto", "wider", "all")
SCOPE_ROWS = {"auto": 11, "wider": 23}


def strike_window(
    strikes: Iterable[float], centre: float | None, scope: str, shift: int = 0
) -> tuple[int, int, float | None]:
    """Return the rows a per-strike panel shows, for every panel and the heatmap alike.

    They are (first index, last index, the centre strike) into `strikes` (ascending).
    `scope`'s count of strikes centred on the listed strike nearest `centre` (the operator's
    panned strike, else the price) moved `shift` rows (a drag), held inside the list; every
    strike for "all"; the middle of the list when there is no centre (no price). (0, -1, None)
    for no strikes.
    """
    ks = [float(k) for k in strikes]
    if not ks:
        return 0, -1, None
    n = None if scope == "all" else SCOPE_ROWS[scope]
    k = nearest_strike(ks, centre)
    c = ks.index(k) if k is not None else len(ks) // 2
    c = min(len(ks) - 1, max(0, c + int(shift)))
    if n is None or n >= len(ks):
        return 0, len(ks) - 1, ks[c]
    lo = min(max(0, c - (n - 1) // 2), len(ks) - n)
    return lo, lo + n - 1, ks[c]


class LadderRow[L](TypedDict):
    """One row of the chain ladder: a strike, and the call and put listed at it (chain_ladder).

    `L` is a listed contract as the caller shows it.
    """

    strike: float
    first: bool
    spot: bool
    call: L | None
    put: L | None
    call_itm: bool | None
    put_itm: bool | None


def chain_ladder[L](
    contracts: list[OptionContract], spot: float | None, shown: list[L]
) -> tuple[list[LadderRow[L]], int]:
    """Return one expiry's chain as the ladder draws it, and how many contracts it could not place.

    A contract it cannot place has no strike, or a putCall other than CALL/PUT. Strikes high to
    low; per strike one row per listed
    contract index (a second contract at one strike and side gets its own row), each contract as
    `shown` (option_contract.chain_row, in the order of `contracts`); `call_itm` / `put_itm`
    Schwab's own: its money intrinsic value positive (Schwab Streamer API, LEVELONE_OPTIONS field
    11), None when Schwab sent none; `spot` marks the first row of the strike nearest spot.
    """
    by_k: dict[float, dict[str, list[tuple[OptionContract, L]]]] = {}
    unplaced = 0
    for c, row in zip(contracts, shown, strict=True):
        if c.strike is None or c.side is None:
            unplaced += 1
            continue
        by_k.setdefault(c.strike, {"call": [], "put": []})[c.side.lower()].append((c, row))
    spot_k = nearest_strike(by_k, spot)

    def leg(legs: list[tuple[OptionContract, L]], i: int) -> L | None:
        return legs[i][1] if i < len(legs) else None

    def itm(legs: list[tuple[OptionContract, L]], i: int) -> bool | None:
        value = legs[i][0].money_intrinsic if i < len(legs) else None
        return None if value is None else value > 0

    rows: list[LadderRow[L]] = []
    for k in sorted(by_k, reverse=True):
        g = by_k[k]
        rows.extend(
            {
                "strike": k,
                "first": i == 0,
                "spot": i == 0 and k == spot_k,
                "call": leg(g["call"], i),
                "put": leg(g["put"], i),
                "call_itm": itm(g["call"], i),
                "put_itm": itm(g["put"], i),
            }
            for i in range(max(len(g["call"]), len(g["put"])))
        )
    return rows, unplaced


def atm_sigma_by_expiry(
    contracts: list[OptionContract], spot: float
) -> dict[str | None, float | None]:
    """Return each expiry date's ATM implied vol as a fraction, over all its contracts.

    Schwab sends one volatility for a strike, and a strike below the forward price and one above
    it differ by a step the size of the interest to the expiry (docs/derived_register.md). The
    value is the mean volatility of the two listed strikes that step lies between
    (_sigma_at_the_step), one from each side of it. A strike's legs are its first call and its
    first put. None for an expiry Schwab sent no rate or no days for (interestRate, a percent;
    daysToExpiration).
    """
    strikes: dict[str | None, dict[float, dict[str, OptionContract]]] = {}
    # each expiry's interest to it as a share of the price, by each contract that carries both
    interest: dict[str | None, set[float]] = {}
    for c in contracts:
        legs = strikes.setdefault(c.expiry, {})
        if c.strike is None or c.side is None:
            continue
        legs.setdefault(c.strike, {}).setdefault(c.side, c)
        if c.interest_rate is not None and c.days_to_expiry is not None:
            interest.setdefault(c.expiry, set()).add(
                c.interest_rate / 100.0 * c.days_to_expiry / _DAYS_PER_YEAR
            )
    out: dict[str | None, float | None] = {}
    # a contract with no expiry date keeps its own key (None), last
    for k, legs in sorted(strikes.items(), key=lambda kv: (kv[0] is None, kv[0])):
        # one chain sends one rate and one count of days for an expiry: the least were there two
        out[k] = _sigma_at_the_step(legs, float(spot), min(interest[k])) if k in interest else None
    return out


def _sigma_at_the_step(
    legs: Mapping[float, Mapping[str, OptionContract]], spot: float, interest: float
) -> float | None:
    """Return the mean volatility of the two listed strikes the volatility's step lies between.

    The step sits at the forward, between two readings of it: the one the expiry's own options
    imply (the listed strike where the call's and the put's mid prices are nearest, the forward
    at or above it when the call is the dearer and below it when the put is: Cboe's VIX
    methodology, docs/SOURCES.md) and the price plus the interest to the expiry (`interest`, a
    share of `spot`). Of the pairs of neighbouring strikes from one below the lower of those two
    to one above the higher, the step is the pair across which the volatility rises the most,
    when it rises there by more than across the pair on each side of it. With no such pair, or
    no interest (the expiry's own day: the step is the interest's), the value is the implied
    forward's own pair's. A strike's volatility is the mean of its call's and its put's, both or
    none: one side's IV never stands in for the mean. None when no strike has both legs quoted,
    or the implied forward's own pair lacks a strike or a volatility: the next pair's never
    stands in for it.
    """
    listed = sorted(legs)
    # by a strike's place in `listed`: its call's mid price less its put's, and its volatility
    gaps: dict[int, float] = {}
    sigmas: dict[int, float] = {}
    for n, strike in enumerate(listed):
        mids = _call_and_put(legs[strike], _mid)
        vols = _call_and_put(legs[strike], lambda c: schwab_iv_to_sigma(c.volatility))
        if mids is not None:
            gaps[n] = mids[0] - mids[1]
        if vols is not None:
            sigmas[n] = (vols[0] + vols[1]) / 2.0
    if not gaps:
        return None
    nearest = min(gaps, key=lambda n: (abs(gaps[n]), n))
    implied = nearest if gaps[nearest] >= 0.0 else nearest - 1
    by_interest = bisect.bisect_right(listed, spot * (1.0 + interest)) - 1
    # each pair of neighbouring strikes' rise in volatility, by its lower strike's place
    rises = {low: sigmas[low + 1] - sigmas[low] for low in sigmas if low + 1 in sigmas}
    if implied not in rises:
        return None
    searched = range(min(implied, by_interest) - 1, max(implied, by_interest) + 2)
    # the largest rise, the pair nearest the implied forward's own on a tie
    step = max(
        (low for low in searched if interest > 0.0 and low in rises),
        default=implied,
        key=lambda low: (rises[low], -abs(low - implied)),
    )
    stands_out = (
        step - 1 in rises
        and step + 1 in rises
        and rises[step] > max(0.0, rises[step - 1], rises[step + 1])
    )
    read = step if stands_out else implied
    return (sigmas[read] + sigmas[read + 1]) / 2.0


def _call_and_put(
    legs: Mapping[str, OptionContract], read: Callable[[OptionContract], float | None]
) -> tuple[float, float] | None:
    """Return a strike's call's and its put's value by `read`, or None unless both have one."""
    if "CALL" not in legs or "PUT" not in legs:
        return None
    call, put = read(legs["CALL"]), read(legs["PUT"])
    return None if call is None or put is None else (call, put)


def _mid(c: OptionContract) -> float | None:
    """Return a contract's mid price, or None without a bid and an ask above 0.

    The price of an option in Cboe's VIX methodology is the midpoint of its bid and its ask,
    and only an option with a non-zero bid is counted (docs/SOURCES.md); an ask of 0 is no ask.
    """
    if c.bid is None or c.ask is None or c.bid <= 0.0 or c.ask <= 0.0:
        return None
    return (c.bid + c.ask) / 2.0


def _per_strike_measure_rows(exposures: dict[float, Bucket]) -> MeasureRows:
    """Return each strike's net DEX $, open interest and net vanna, as StrikeValue rows.

    Every strike of the book, by the heatmap cell's own readers (net_dex_dollars of a dollarized
    book; strike_total_oi; net_vanna, +call/-put as compute_exposures_by_strike computed it).
    Open interest keeps every digit; the screen rounds the count. A strike whose value is unknown
    keeps its row with None, as a GEX row does, so no strike is left out without a word; a book
    built without spot (not dollarized) has no DEX rows, as it has no GEX rows.
    """
    dex: list[StrikeValue] = []
    oi: list[StrikeValue] = []
    vanna: list[StrikeValue] = []
    dollarized = bool(exposures) and exposures_have_dollar_gex(exposures)
    for k, b in exposures.items():
        if dollarized:
            dex.append(StrikeValue(k, bucket_metric(b, "net_dex_dollars")))
        oi.append(StrikeValue(k, strike_total_oi(b)))
        vanna.append(StrikeValue(k, bucket_metric(b, "net_vanna")))
    for rows in (dex, oi, vanna):
        rows.sort(key=lambda r: r.strike)
    return {"dex": dex, "oi": oi, "vanna": vanna}


def _strike_rows(exposures: dict[float, Bucket], charm: dict[float, CharmBucket]) -> StrikeRows:
    """Return one book's GEX rows (_per_strike_rows), DEX, OI and vanna rows, and charm rows.

    A charm row is each strike's net charm exposure of `charm` (compute_charm_by_strike's map, the
    largest charm strikes' own), ascending; a strike whose net charm is not known keeps its row
    with None. The book's settled contracts are counted from its buckets, the same contracts
    charm's map was priced from.
    """
    return {
        "gex": _per_strike_rows(exposures),
        **_per_strike_measure_rows(exposures),
        "charm": sorted(
            (StrikeValue(k, b["net_charm"]) for k, b in charm.items()), key=lambda r: r.strike
        ),
        "settled": sum(b["settled"] for b in exposures.values()),
    }


def per_strike_view(
    books: dict[ExpiryKey, Book],
    exposures: dict[float, Bucket],
    charm_by_expiry: dict[str | None, dict[float, CharmBucket]],
    charm_by_strike: dict[float, CharmBucket],
) -> PerStrikeView:
    """Return the per-strike rows of the whole book and of each listed expiry, from one pricing.

    The whole book is `exposures`, the merge of the chain's exposure_books `books`, with its charm
    map `charm_by_strike` (the merge of `charm_by_expiry`); an expiry's rows are the merge of its
    own books alone (its contracts under whatever daysToExpiration Schwab sent them) and its own
    charm map. A contract with no expiry date is in the whole book only: it belongs to no expiry
    a page can choose.
    """
    by_date: dict[str, list[Book]] = {}
    for (expiry, _dte), book in books.items():
        if expiry is not None:
            by_date.setdefault(expiry, []).append(book)
    return {
        **_strike_rows(exposures, charm_by_strike),
        "by_expiry": {
            expiry: _strike_rows(merge_exposure_books(dated)[0], charm_by_expiry[expiry])
            for expiry, dated in sorted(by_date.items())
        },
    }


#: a wall's geometry against the price (wall_geometry_state)
WALL_CONTAINS, WALL_BREACHED = "contains", "breached"


def wall_geometry_state(spot: float | None, wall: float | None, side: str) -> str | None:
    """Tell whether this wall is in the configuration its support/resistance label claims.

    By level_side: WALL_CONTAINS = a call wall above the price / a put wall below it, the only
    geometry in which dealer-hedging containment language is true; WALL_BREACHED = the price at
    or through the wall (a wall at the price contains nothing). None when the wall or the price
    is unknown.
    """
    where = level_side(wall, spot)
    if where is None:
        return None
    if side == "call":
        return WALL_CONTAINS if where == LEVEL_ABOVE else WALL_BREACHED
    if side == "put":
        return WALL_CONTAINS if where == LEVEL_BELOW else WALL_BREACHED
    raise ValueError(f"side must be 'call' or 'put', got {side!r}")


class RelationFields(TypedDict):
    """A price's relations to the published levels as the terrain panel carries them."""

    call_wall_state: str | None
    put_wall_state: str | None
    call_wall_lean: str | None
    put_wall_lean: str | None
    flip_relation: str | None
    flip_relation_text: str | None


@dataclass(frozen=True)
class PriceRelations:
    """Every relation of a price to the published levels, as the routes serve it beside them.

    The price's side of the flip is served with its words (terrain_read.FLIP_RELATION_TEXT).
    """

    call_wall_state: str | None
    put_wall_state: str | None
    call_wall_lean: str | None
    put_wall_lean: str | None
    flip_relation: str | None
    flip_relation_text: str | None

    def to_dict(self) -> RelationFields:
        return {
            "call_wall_state": self.call_wall_state,
            "put_wall_state": self.put_wall_state,
            "call_wall_lean": self.call_wall_lean,
            "put_wall_lean": self.put_wall_lean,
            "flip_relation": self.flip_relation,
            "flip_relation_text": self.flip_relation_text,
        }


def price_relations(terrain: TerrainFields, price: float | None) -> PriceRelations:
    """Return every relation of `price` to the published levels (`terrain`, a snapshot's to_dict).

    Each wall's state and label and the price's side of the flip. The levels are the
    publication's; the price is the one given, the live price on every panel. A level's
    distance from the price is served with the level (the levels panel).
    """
    call, put, flip = terrain["call_wall"], terrain["put_wall"], terrain["gamma_flip"]
    of_flip = price_side(flip, price)
    return PriceRelations(
        call_wall_state=wall_geometry_state(price, call, "call"),
        put_wall_state=wall_geometry_state(price, put, "put"),
        call_wall_lean=wall_lean(call, price, "call"),
        put_wall_lean=wall_lean(put, price, "put"),
        flip_relation=of_flip,
        flip_relation_text=FLIP_RELATION_TEXT[of_flip],
    )


def wall_lean(wall: float | None, price: float | None, side: str) -> str | None:
    """Return the wall's label on the chart at `price`: "BREACHED — spot above", "at" or "below".

    Only a breached wall (wall_geometry_state) has one, saying where the price is; a containing
    wall has none (its side of the price is its state), nor does an unknown wall or price.
    """
    where = price_side(wall, price)
    if wall_geometry_state(price, wall, side) == WALL_BREACHED and where is not None:
        return f"BREACHED — spot {where.lower()}"
    return None


#: How far from the price a strike may be to be the pin strike, in expected moves: within one
#: (|z| <= 1, the distance measure of Avellaneda & Lipkin 2003's pinning model; pin_research.md).
PIN_MAX_EXPECTED_MOVES = 1.0
#: days and minutes in a year of ACT/365 (time_et.YEAR_SECONDS / 60)
_DAYS_PER_YEAR = 365.0
_MINUTES_PER_YEAR = _DAYS_PER_YEAR * 24.0 * 60.0


@dataclass(frozen=True)
class PinStrike:
    """The pin strike and how far it is: in expected moves, in strike widths, in minutes left."""

    strike: float
    expected_moves: float
    strike_widths: float | None  # None: the expiry lists no other strike
    minutes_to_close: float


def pin_by_open_interest(
    contracts: list[OptionContract],
    spot: float,
    *,
    now: datetime,
    sessions: Mapping[str, Session],
    product: str,
) -> PinStrike | None:
    """Return the strike with the most open interest near the price, of an expiry closing today.

    The pinning studies' measure (pin_research.md: Ni, Pearson & Poteshman 2005; Golez &
    Jackwerth 2012; Avellaneda & Lipkin 2003), from Schwab's chain alone and no dealer sign:
    of today's expiry settled at today's close (an AM-settled one, Schwab's settlementType "A",
    is out), each strike's open interest (calls plus puts, as Schwab sent it) and its distance
    from the price in expected moves, z = ln(price/strike) / (sigma * sqrt(T)), sigma the strike's
    implied volatility (the mean of its call's and put's, as sent) and T the time to today's
    close. The strike with the most open interest with |z| <= PIN_MAX_EXPECTED_MOVES; on equal
    open interest, the nearer. Its distance is also given in strike widths (the gap to its
    nearest listed neighbour) and its minutes to the close. None when no expiry settles at
    today's close, the close has passed, or no strike with known open interest and volatility is
    that near. It says nothing about where the price will close.
    """
    today = now.astimezone(ET).date().isoformat()
    t_close = time_to_expiry_years(today, now, sessions=sessions, product=product)
    if not t_close or spot <= 0:
        return None
    listed: set[float] = set()
    oi: dict[float, float] = {}
    sigmas: dict[float, list[float]] = {}
    unknown: set[float] = set()  # a strike with a contract whose open interest is not known
    for c in contracts:
        if c.expiry != today or c.settlement == SETTLEMENT_AM or c.strike is None:
            continue
        listed.add(c.strike)
        if c.open_interest is None:
            unknown.add(c.strike)
            continue
        oi[c.strike] = oi.get(c.strike, 0.0) + c.open_interest
        sigma = schwab_iv_to_sigma(c.volatility)
        if sigma is not None and sigma > 0:
            sigmas.setdefault(c.strike, []).append(sigma)
    near: list[tuple[float, float, float, float]] = []  # (open interest, -|z|, strike, z)
    for k, k_oi in oi.items():
        if k in unknown or k not in sigmas or k <= 0:
            continue  # a strike whose open interest or volatility is not known is not ranked
        z = math.log(spot / k) / (statistics.fmean(sigmas[k]) * math.sqrt(t_close))
        if abs(z) <= PIN_MAX_EXPECTED_MOVES:
            near.append((k_oi, -abs(z), k, z))
    if not near:
        return None
    _oi, _neg_z, strike, z = max(near)
    width = min((abs(strike - k) for k in listed if k != strike), default=None)
    return PinStrike(
        strike=strike,
        expected_moves=z,
        strike_widths=None if width is None else (spot - strike) / width,
        minutes_to_close=t_close * _MINUTES_PER_YEAR,
    )


#: The terrain's price levels and the name each is shown under, in the order they are listed: the
#: operator's pattern (AGENTS.md rule 17), the Greek or OI first, then the side or the kind of
#: level: Gamma Call is the strike of the largest call gamma, Gamma Total of the largest call plus
#: put gamma, Gamma Net Positive of the most positive net GEX, OI Pin of the largest open interest
#: near the price.
OPTION_LEVELS = (
    ("call_wall", "Gamma Call"),
    ("put_wall", "Gamma Put"),
    ("gamma_flip", "Gamma Flip"),
    ("max_pain", "Max Pain"),
    ("absolute_gamma_strike", "Gamma Total"),
    ("pin_candidate", "OI Pin"),
    ("gsf", "GSF"),
    ("grc", "GRC"),
    ("hvp", "Gamma Net Negative"),
    ("lvp", "Gamma Net Positive"),
    ("key_delta_strike", "Delta Total"),
    ("call_delta_wall", "Delta Call"),
    ("put_delta_wall", "Delta Put"),
    ("call_charm_wall", "Charm Call"),
    ("put_charm_wall", "Charm Put"),
)
#: The levels a same-day clock can move: all but the two read on the whole book alone.
SAME_DAY_LEVELS = tuple(
    level for level in OPTION_LEVELS if level[0] not in ("max_pain", "pin_candidate")
)


class SameDayLevels(TypedDict):
    """The levels on a 0DTE basis as the snapshot holds them (same_day_levels).

    The levels, every one of SAME_DAY_LEVELS; the expiry they were re-priced from; and which
    contracts their gamma curve could not price.
    """

    same_day: dict[str, float | None]
    same_day_repriced_from: str | None
    same_day_left_out: str | None


def same_day_levels(
    expiry_rows: dict[str | None, list[OptionContract]],
    spot: float,
    *,
    now: datetime,
    sessions: Mapping[str, Session],
    product: str,
    books: dict[ExpiryKey, Book],
    charm_by_expiry: dict[str | None, dict[float, CharmBucket]],
) -> SameDayLevels:
    """Return the whole book's levels on a 0DTE basis, read on the nearest listed expiry alone.

    With the expiry re-priced from (a model, said on hover; None when read as held, or none) and
    which contracts their gamma curve could not price (unpriced_note; None: none, or no levels).

    Every ticker, one function, the same producers as the whole book, over the book's contracts
    by expiry day (`expiry_rows`). An expiry listed today is read as the book holds it: its
    exposure books (`books`, from Schwab's gamma and delta as sent), its gamma profile and its
    charm map (`charm_by_expiry`). With none listed today Schwab sends no Greek at today's
    close, so the next listed expiry is priced as if it expired at today's option close
    (calc.math_levels.repriced_to_close) and read the same way. Absent when the chain lists no
    expiry from today on. A later expiry's are absent too when `now` is past
    today's close (a chain is valued at that close, time_et.valuation_instant, so they stand
    there) or no option window is held for today.
    """
    blank: SameDayLevels = {
        "same_day": _no_same_day_levels(),
        "same_day_repriced_from": None,
        "same_day_left_out": None,
    }
    today = now.astimezone(ET).date().isoformat()
    front = min((e for e in expiry_rows if e is not None and e >= today), default=None)
    if front is None:
        return blank
    rows = expiry_rows[front]
    repriced_from = None if front == today else front
    if front == today:
        front_books = (b for (e, _d), b in books.items() if e == front)
        parsed, unpriced = contract_inputs(rows, now, sessions=sessions, product=product)
        charm = charm_by_expiry[front]
    else:
        t_close = time_to_expiry_years(today, now, sessions=sessions, product=product)
        if not t_close:
            return blank
        rows, parsed, unpriced = repriced_to_close(rows, spot, t_close)
        front_books = exposure_books(
            rows, spot=spot, now=now, sessions=sessions, product=product
        ).values()
        charm = compute_charm_by_strike(
            rows, spot, now=now, sessions=sessions, t_years=t_close, product=product
        )
    exposures, _diag = merge_exposure_books(front_books)
    (call_wall, _), (put_wall, _) = pick_gamma_wall_strikes(exposures)
    abs_gamma = pick_absolute_gamma_strike(exposures)
    hvp, lvp = pick_volatility_point_strikes(exposures)
    profile = compute_gamma_profile(parsed, spot)
    flip = gamma_flip_from_profile(profile, spot)
    support = compute_gamma_support_levels(profile, spot)
    call_charm, put_charm = pick_charm_wall_strikes(charm)
    (call_delta_wall, _), (put_delta_wall, _) = pick_delta_wall_strikes(exposures)
    levels: dict[str, float | None] = {
        "call_wall": call_wall,
        "put_wall": put_wall,
        "gamma_flip": flip,
        "absolute_gamma_strike": abs_gamma,
        "gsf": support["gsf"],
        "grc": support["grc"],
        "hvp": hvp,
        "lvp": lvp,
        "key_delta_strike": pick_key_delta_strike(exposures),
        "call_delta_wall": call_delta_wall,
        "put_delta_wall": put_delta_wall,
        "call_charm_wall": call_charm,
        "put_charm_wall": put_charm,
    }
    return {
        "same_day": levels,
        "same_day_repriced_from": repriced_from,
        "same_day_left_out": unpriced_note(unpriced),
    }


def compute_terrain(
    ticker: str,
    contracts: list[OptionContract] | None,
    spot: float | None,
    *,
    now: datetime,
    sessions: Mapping[str, Session],
) -> TerrainSnapshot:
    """Full terrain for one ticker, the ONE terrain engine; never invents a level.

    Fed the whole multi-expiry chain (dealers hedge the whole delta book, not the 0DTE slice); the
    regime is the sign of net GEX at the price (build_terrain_read). `now`: the valuation
    instant for every time-to-expiry, read once by the caller's entry point (the live reprice: its
    own; a replay of a stored chain: the snapshot's). `sessions`: Schwab's /markets answers by ET
    date, the settlement of each expiry.
    """
    if not contracts:
        return _unavailable(ticker, spot, "no option chain")
    if spot is None or spot <= 0:
        return _unavailable(ticker, spot, "no spot price")

    # ONE valuation instant for every book below, on this ticker's option close
    product = option_close_product(ticker)
    # One pricing pass: exposures per (expiry, DTE) group; every book below is a merge of them.
    books = exposure_books(contracts, spot=spot, now=now, sessions=sessions, product=product)
    exposures, diag = merge_exposure_books(books.values())
    if not exposures:
        return _unavailable(ticker, spot, "chain produced no exposures")
    pin = pin_by_open_interest(contracts, spot, now=now, sessions=sessions, product=product)
    # ONE gamma at spot: Schwab's gamma as sent, summed over the book (the walls' own gamma)
    gamma_at_spot = book_net_gex(exposures)
    flip = _flip_fields(contracts, spot, gamma_at_spot, now, sessions, product)
    expiry_rows = _expiry_rows(contracts)
    by_expiry = _by_expiry(expiry_rows, spot, now, sessions, product)
    read = build_terrain_read(spot=spot, gamma_at_spot=gamma_at_spot)
    same_day = same_day_levels(
        expiry_rows,
        spot,
        now=now,
        sessions=sessions,
        product=product,
        books=books,
        charm_by_expiry=by_expiry["charm_by_expiry"],
    )

    return TerrainSnapshot(
        ticker=ticker,
        spot=float(spot),
        valued_at=now,
        regime=read.regime,
        headline=read.headline,
        headline_source=read.headline_source,
        **flip,
        net_gex_at_spot=gamma_at_spot,
        **_walls(exposures),
        pcr_all=put_call_oi_ratio(exposures.values()),
        pcr_volume_all=put_call_volume_ratio(exposures.values()),
        pin_candidate=None if pin is None else pin.strike,
        pin_expected_moves=None if pin is None else pin.expected_moves,
        pin_strike_widths=None if pin is None else pin.strike_widths,
        pin_minutes_to_close=None if pin is None else pin.minutes_to_close,
        **same_day,
        **_front_max_pain(books),
        contracts_used=diag.contracts_used,
        strikes_used=len(exposures),
        dollarized=exposures_have_dollar_gex(exposures),
        # the LIVE per-strike map, computed from THIS chain; session volume is carried alongside.
        per_strike=per_strike_view(
            books, exposures, by_expiry["charm_by_expiry"], by_expiry["charm_by_strike"]
        ),
        books=books,
        **by_expiry,
        **_expiry_fields(books),
        atm_iv_pct_by_expiry={
            e: None if s is None else s * 100.0
            for e, s in atm_sigma_by_expiry(contracts, spot).items()
            if e is not None
        },
    )


class _ByExpiry(TypedDict):
    """Each expiry's charm and implied vol by strike, and the charm walls of their merge."""

    charm_by_expiry: dict[str | None, dict[float, CharmBucket]]
    charm_by_strike: dict[float, CharmBucket]
    call_charm_wall: float | None
    put_charm_wall: float | None
    iv_by_expiry: dict[str | None, dict[float, float | None]]


def _by_expiry(
    expiry_rows: dict[str | None, list[OptionContract]],
    spot: float,
    now: datetime,
    sessions: Mapping[str, Session],
    product: str,
) -> _ByExpiry:
    """Return each expiry's charm (one call per expiry) and IV by strike, and the charm walls."""
    charm_by_expiry = {
        exp: compute_charm_by_strike(rows, float(spot), now=now, sessions=sessions, product=product)
        for exp, rows in expiry_rows.items()
    }
    charm_by_strike = merge_charm_maps(charm_by_expiry)
    call_charm_wall, put_charm_wall = pick_charm_wall_strikes(charm_by_strike)
    return {
        "charm_by_expiry": charm_by_expiry,
        "charm_by_strike": charm_by_strike,
        "call_charm_wall": call_charm_wall,
        "put_charm_wall": put_charm_wall,
        "iv_by_expiry": {exp: iv_by_strike(rows) for exp, rows in expiry_rows.items()},
    }


class _Walls(TypedDict):
    """The book's walls and pockets, each a strike (None: none found)."""

    call_wall: float | None
    put_wall: float | None
    absolute_gamma_strike: float | None
    key_delta_strike: float | None
    hvp: float | None
    lvp: float | None
    call_delta_wall: float | None
    put_delta_wall: float | None


def _walls(exposures: dict[float, Bucket]) -> _Walls:
    """Return the book's gamma and delta walls, its pockets and its largest-gamma strike."""
    (call_wall, _cw_str), (put_wall, _pw_str) = pick_gamma_wall_strikes(exposures)
    hvp, lvp = pick_volatility_point_strikes(exposures)
    # the SSOT producer owns the delta walls too — same wide
    # chain, same exposures, one book. OI/vanna walls stay unowned and therefore BLANK on
    # every operator surface until this producer computes them.
    (call_delta_wall, _cdw_str), (put_delta_wall, _pdw_str) = pick_delta_wall_strikes(exposures)
    return {
        "call_wall": call_wall,
        "put_wall": put_wall,
        # max TOTAL gamma — the absolute-gamma concentration, full book.
        "absolute_gamma_strike": pick_absolute_gamma_strike(exposures),
        "key_delta_strike": pick_key_delta_strike(exposures),
        "hvp": hvp,
        "lvp": lvp,
        "call_delta_wall": call_delta_wall,
        "put_delta_wall": put_delta_wall,
    }


class _Flip(TypedDict):
    """The gamma flip, its note, the support and resistance levels, and the profile."""

    gamma_flip: float | None
    gsf: float | None
    grc: float | None
    flip_note: str | None
    profile: list[tuple[float, float]]


def _flip_fields(
    contracts: list[OptionContract],
    spot: float,
    gamma_at_spot: float | None,
    now: datetime,
    sessions: Mapping[str, Session],
    product: str,
) -> _Flip:
    """Return the flip's fields, from one gamma profile at `now`.

    The model curve places the flip only (Schwab sends gamma at its own price, never at other
    prices): where it crosses zero over the strikes the chain lists, nearest the price, else
    None; where the curve's sign at spot disagrees with Schwab's (`gamma_at_spot`), the flip's
    note says so, and it says which contracts the curve could not price (unpriced_note).
    """
    parsed, unpriced = contract_inputs(contracts, now, sessions=sessions, product=product)
    profile = compute_gamma_profile(parsed, spot)
    # GSF/GRC from the SAME materialized profile — no second materialization.
    gsl = compute_gamma_support_levels(profile, spot)
    notes = [
        note
        for note in (
            flip_note(gamma_at_spot, gamma_at_price(profile, spot)),
            unpriced_note(unpriced),
        )
        if note is not None
    ]
    return {
        "gamma_flip": gamma_flip_from_profile(profile, spot),
        "gsf": gsl["gsf"],
        "grc": gsl["grc"],
        "flip_note": " ".join(notes) if notes else None,
        "profile": profile,
    }


class _MaxPain(TypedDict):
    """Max pain on the front expiry, and that expiry's DTE."""

    max_pain: float | None
    max_pain_dte: float | None


def _front_max_pain(books: dict[ExpiryKey, Book]) -> _MaxPain:
    """Return max pain on the FRONT expiry only, with that expiry's DTE (None: no DTE known)."""
    front_dte = min((d for (_e, d) in books if d is not None), default=None)
    max_pain = None
    if front_dte is not None:
        front, _ = merge_exposure_books(
            b for (_e, d), b in books.items() if d is not None and d <= front_dte
        )
        max_pain = compute_max_pain(front)
    return {"max_pain": max_pain, "max_pain_dte": front_dte}


def _expiry_rows(contracts: list[OptionContract]) -> dict[str | None, list[OptionContract]]:
    """Return the contracts by expiry; no readable date keeps its row under None (side unknown)."""
    expiry_rows: dict[str | None, list[OptionContract]] = {}
    for c in contracts:
        expiry_rows.setdefault(c.expiry, []).append(c)
    return expiry_rows


class _ExpiryFields(TypedDict):
    """Each dated expiry's put/call ratios and DTE, and the expiries listed."""

    pcr_by_expiry: dict[str, float | None]
    pcr_volume_by_expiry: dict[str, float | None]
    expiries: list[str]
    expiry_dte: dict[str, float | None]


def _expiry_fields(books: dict[ExpiryKey, Book]) -> _ExpiryFields:
    """Return each dated expiry's own, over every book of that date.

    A contract with no expiry date is in the book only. An expiry's DTE is Schwab's
    daysToExpiration for its contracts; None when they were not all sent the same one.
    """
    buckets: dict[str, list[Bucket]] = {}
    dtes: dict[str, set[float | None]] = {}
    for (e, d), (book, _diag) in books.items():
        if e is not None:
            buckets.setdefault(e, []).extend(book.values())
            dtes.setdefault(e, set()).add(d)
    return {
        "pcr_by_expiry": {e: put_call_oi_ratio(buckets[e]) for e in sorted(buckets)},
        "pcr_volume_by_expiry": {e: put_call_volume_ratio(b) for e, b in buckets.items()},
        "expiries": sorted(buckets),
        "expiry_dte": {e: next(iter(d)) if len(d) == 1 else None for e, d in dtes.items()},
    }
