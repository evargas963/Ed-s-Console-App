"""Terrain pipeline — levels only, no model stack.

This module is pure: it takes contracts + spot and returns a payload. Fetching and
scheduling live in the caller, so this stays trivially testable.
"""

from __future__ import annotations

import bisect
import math
import statistics
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from typing import Any, NamedTuple, TypedDict

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
)
from calc.terrain_read import (
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
    float_finite_or_none,
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
    """One strike's value on a per-strike bar (net DEX $, open interest, net vanna or charm)."""

    strike: float
    value: float


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


class PerStrikeView(MeasureRows):
    """per_strike_view's rows: the GEX rows of each DTE scope beside the DEX and OI rows."""

    all: list[StrikeRow]
    near: list[StrikeRow]
    far: list[StrikeRow]


class PositioningMigration(TypedDict):
    """positioning_migration's answer for one DTE scope."""

    rows: list[MigrationRow]
    compared: bool
    grew: list[float]
    shrank: list[float]
    busiest: list[float]
    busiest_vs_walls: str | None
    volume_total: float | None


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
    #: book. A GROSS GAMMA CONCENTRATION (SpotGamma's "Absolute Gamma" measure): where the
    #: most dealer re-hedging activity sits. It is a pin CANDIDATE input, NOT a demonstrated
    #: magnet — magnitude sets the SIZE of the hedging flow while the unobservable dealer
    #: SIGN decides pin vs repel. The raw value carries the metric's name; the pin is
    #: `pin_candidate` below, read on open interest.
    absolute_gamma_strike: float | None = None
    #: The pin strike (pin_by_open_interest): of an expiry settling at today's close, the strike
    #: with the most open interest within one expected move of the price, with its distance in
    #: expected moves (z = ln(price/strike) / (sigma * sqrt(T))), in strike widths, and the
    #: minutes to the close. None when nothing expires at today's close or no strike is that near.
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

    #: Signed net dealer GEX$ per 1% move AT SPOT — the regime's own number
    #: (regime = its sign). Disambiguates walls that share a strike.
    net_gex_at_spot: float | None = None

    #: Gamma Support Floor / Gamma Resistance Ceiling — computed from the SAME
    #: materialized profile as the flip. GSF = highest level
    #: below spot where the positive-gamma cushion has decayed to half its at-spot value
    #: (support ends BEFORE the flip's zero-crossing); GRC = the upside mirror, often
    #: at/beyond the call wall (resistance strengthens before it exhausts). None when not
    #: found, a negative regime included (no fabricated price).
    gsf: float | None = None
    grc: float | None = None

    #: The levels on a 0DTE basis (same_day_levels). Keys are SAME_DAY_LEVELS.
    #: absolute_gamma_strike in this dict is the one 0DTE pin.
    same_day: dict[str, float | None] = field(default_factory=dict[str, float | None])
    #: the expiry the same-day levels were re-priced from to today's close (a model, said on
    #: hover); None when they are today's own expiry as held, or absent
    same_day_repriced_from: str | None = None

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

    #: (price, net dealer gamma) samples; kept OUT of to_dict() (~240 pairs).
    profile: list[tuple[float, float]] = field(
        default_factory=list[tuple[float, float]], repr=False
    )

    #: The LIVE per-strike map the walls were picked from; the per-strike panel reads it, at
    #: no additional vendor cost — the chain is already in hand. Kept OUT of to_dict() for the
    #: same reason as `profile`: too heavy for every poll; the strikes endpoint reads it directly.
    #: per_strike_view's rows ({all, near, far, dex, oi}); with no book priced, each is empty.
    per_strike: PerStrikeView = field(default_factory=lambda: per_strike_view({}, {}), repr=False)
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

    def to_dict(self) -> dict[str, Any]:
        """Return the per-poll payload.

        It holds every field except the heavy maps (profile, per_strike, books,
        charm_by_strike), which the server reads off the snapshot, and the net gamma at spot and
        the contracts used as the screen shows them.
        """
        light = replace(self, **{n: None for n in _HEAVY_FIELDS})
        return {
            **{k: v for k, v in asdict(light).items() if k not in _HEAVY_FIELDS},
            "net_gex_at_spot_text": dollars_text(self.net_gex_at_spot),
            "contracts_used_text": count_text(self.contracts_used),
            # each option level's price, and each on the 0DTE basis, as the screen shows it
            **{f"{name}_text": price_text(getattr(self, name)) for name, _ in OPTION_LEVELS},
            "same_day_text": {name: price_text(v) for name, v in self.same_day.items()},
            # the put/call ratios, over the whole book and each expiry, as the screen shows them
            "pcr_all_text": fixed_text(self.pcr_all, 2),
            "pcr_volume_all_text": fixed_text(self.pcr_volume_all, 2),
            "pcr_by_expiry_text": {ex: fixed_text(v, 2) for ex, v in self.pcr_by_expiry.items()},
            "pcr_volume_by_expiry_text": {
                ex: fixed_text(v, 2) for ex, v in self.pcr_volume_by_expiry.items()
            },
        }


_HEAVY_FIELDS = (
    "profile",
    "per_strike",
    "books",
    "charm_by_strike",
    "charm_by_expiry",
    "iv_by_expiry",
)


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
        sk = float_finite_or_none(k)
        if sk is None:  # a NaN strike must never become a rendered bar
            continue
        gf = float_finite_or_none(net_gex_dollars_at_strike(b))
        vol = strike_total_volume(b)
        rows.append(StrikeRow(sk, gf, vol))
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


def positioning_migration(
    today: list[StrikeRow],
    prior: list[StrikeRow],
    call_wall: float | None,
    put_wall: float | None,
) -> PositioningMigration:
    """Return day-over-day positioning for one DTE scope.

    It is built from the GEX-by-strike rows of today and of the prior capture.

    rows: each strike's MigrationRow (None where either day has no value); grew / shrank: the
    two strikes that gained / lost the most GEX; busiest: the two strikes with the most volume
    and where they sit against the walls; volume_total: the scope's session volume (side_total).
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
    # where the busiest strikes sit against the walls; None when that is not known: no busiest
    # strike, a wall not known, or the busiest strikes on both sides of a wall
    where = None
    if busiest and call_wall is not None and min(busiest) > call_wall:
        where = "ABOVE_CALL_WALL"
    elif busiest and put_wall is not None and max(busiest) < put_wall:
        where = "BELOW_PUT_WALL"
    elif (
        busiest
        and call_wall is not None
        and put_wall is not None
        and put_wall <= min(busiest)
        and max(busiest) <= call_wall
    ):
        where = "INSIDE_WALLS"
    return {
        "rows": rows,
        "compared": bool(changes),
        "grew": grew,
        "shrank": shrank,
        "busiest": busiest,
        "busiest_vs_walls": where,
        "volume_total": side_total([r[2] for r in today]),
    }


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


class LadderRow(TypedDict):
    """One row of the chain ladder: a strike, and the call and put listed at it (chain_ladder)."""

    strike: float
    first: bool
    spot: bool
    call: dict[str, Any] | None
    put: dict[str, Any] | None
    call_itm: bool | None
    put_itm: bool | None


def chain_ladder(
    contracts: list[OptionContract], spot: float | None, shown: list[dict[str, Any]]
) -> tuple[list[LadderRow], int]:
    """Return one expiry's chain as the ladder draws it, and how many contracts it could not place.

    A contract it cannot place has no strike, or a putCall other than CALL/PUT. Strikes high to
    low; per strike one row per listed
    contract index (a second contract at one strike and side gets its own row), each contract as
    `shown` (option_contract.chain_row, in the order of `contracts`); `call_itm` / `put_itm`
    Schwab's own: its money intrinsic value positive (Schwab Streamer API, LEVELONE_OPTIONS field
    11), None when Schwab sent none; `spot` marks the first row of the strike nearest spot.
    """
    by_k: dict[float, dict[str, list[tuple[OptionContract, dict[str, Any]]]]] = {}
    unplaced = 0
    for c, row in zip(contracts, shown, strict=True):
        if c.strike is None or c.side is None:
            unplaced += 1
            continue
        by_k.setdefault(c.strike, {"call": [], "put": []})[c.side.lower()].append((c, row))
    spot_k = nearest_strike(by_k, spot)

    def leg(legs: list[tuple[OptionContract, dict[str, Any]]], i: int) -> dict[str, Any] | None:
        return legs[i][1] if i < len(legs) else None

    def itm(legs: list[tuple[OptionContract, dict[str, Any]]], i: int) -> bool | None:
        value = legs[i][0].money_intrinsic if i < len(legs) else None
        return None if value is None else value > 0

    rows: list[LadderRow] = []
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

    The value is the mean of the call and the put IV, each at its side's strike nearest spot
    (the lower one on a tie, as nearest_strike). Both legs or None: one side's IV never stands
    in for the mean, and a leg whose nearest contract has no IV from Schwab (-999, or 0: no
    sigma) has none -- the next strike's IV never stands in for it. Schwab `volatility` is a
    percent, converted by schwab_iv_to_sigma.
    """
    legs: dict[str | None, dict[str, tuple[tuple[float, float], float | None]]] = {}
    for c in contracts:
        sides = legs.setdefault(c.expiry, {})
        if c.strike is None or c.side is None:
            continue
        near = (abs(c.strike - float(spot)), c.strike)
        if c.side not in sides or near < sides[c.side][0]:
            sides[c.side] = (near, schwab_iv_to_sigma(c.volatility))
    out: dict[str | None, float | None] = {}
    # a contract with no expiry date keeps its own key (None), last
    for k, s in sorted(legs.items(), key=lambda kv: (kv[0] is None, kv[0])):
        # the call's and the put's sigma, each when known: their mean only with both
        sig = [v for x in ("CALL", "PUT") if x in s and (v := s[x][1]) is not None]
        out[k] = (sig[0] + sig[1]) / 2.0 if len(sig) == 2 else None
    return out


def _per_strike_measure_rows(exposures: dict[float, Bucket]) -> MeasureRows:
    """Return each strike's net DEX $, open interest and net vanna, as StrikeValue rows.

    Every strike whose value is known, by the heatmap cell's own readers (net_dex_dollars of a
    dollarized book; strike_total_oi; net_vanna, +call/-put as compute_exposures_by_strike
    computed it). Open interest keeps every digit; the screen rounds the count. A strike whose
    value is unknown has no row.
    """
    dex: list[StrikeValue] = []
    oi: list[StrikeValue] = []
    vanna: list[StrikeValue] = []
    dollarized = bool(exposures) and exposures_have_dollar_gex(exposures)
    for k, b in exposures.items():
        sk = float_finite_or_none(k)
        if sk is None:
            continue
        d = float_finite_or_none(bucket_metric(b, "net_dex_dollars")) if dollarized else None
        if d is not None:
            dex.append(StrikeValue(sk, d))
        o = strike_total_oi(b)
        if o is not None:
            oi.append(StrikeValue(sk, o))
        v = bucket_metric(b, "net_vanna")
        if v is not None:
            vanna.append(StrikeValue(sk, v))
    for rows in (dex, oi, vanna):
        rows.sort(key=lambda r: r.strike)
    return {"dex": dex, "oi": oi, "vanna": vanna}


def per_strike_view(books: dict[ExpiryKey, Book], exposures: dict[float, Bucket]) -> PerStrikeView:
    """`{all, near, far}` GEX rows -- the ALL / <=7DTE / MONTHLY+ chips -- and DEX and OI rows.

    The GEX rows come from the chain's exposure_books and their merged full book `exposures`
    (one pricing pass), and the full book's DEX and OI rows (`dex`, `oi`:
    _per_strike_measure_rows). A contract whose days-to-expiry cannot be read belongs to `all`
    only: a maturity split it cannot answer is not answered for it.
    """

    def rows(keep: Callable[[float | None], bool]) -> list[StrikeRow]:
        chosen = [b for (_exp, d), b in books.items() if keep(d)]
        if not chosen:
            return []
        subset_exposures, _diag = merge_exposure_books(chosen)
        return _per_strike_rows(subset_exposures)

    return {
        "all": _per_strike_rows(exposures),
        "near": rows(lambda d: d is not None and d <= 7),
        "far": rows(lambda d: d is not None and d > 7),
        **_per_strike_measure_rows(exposures),
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


@dataclass(frozen=True)
class PriceRelations:
    """Every relation of a price to the published levels, as the routes serve it beside them."""

    call_wall_state: str | None
    put_wall_state: str | None
    call_wall_lean: str | None
    put_wall_lean: str | None
    flip_relation: str | None

    def to_dict(self) -> dict[str, str | float | None]:
        return asdict(self)


def price_relations(terrain: dict[str, Any], price: float | None) -> PriceRelations:
    """Return every relation of `price` to the published levels (`terrain`, a snapshot's to_dict).

    Each wall's state and label and the price's side of the flip. The levels are the
    publication's; the price is the one given, the live price on every panel. A level's
    distance from the price is served with the level (the levels panel).
    """
    call, put, flip = terrain["call_wall"], terrain["put_wall"], terrain["gamma_flip"]
    return PriceRelations(
        call_wall_state=wall_geometry_state(price, call, "call"),
        put_wall_state=wall_geometry_state(price, put, "put"),
        call_wall_lean=wall_lean(call, price, "call"),
        put_wall_lean=wall_lean(put, price, "put"),
        flip_relation=price_side(flip, price),
    )


def wall_lean(wall: float | None, price: float | None, side: str) -> str | None:
    """The wall's label on the chart at `price`: "BREACHED — spot above", "at" or "below".

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
#: minutes in a year of ACT/365 (time_et.YEAR_SECONDS / 60)
_MINUTES_PER_YEAR = 365.0 * 24.0 * 60.0


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


#: The terrain's price levels and the name each is shown under, in the order they are listed.
OPTION_LEVELS = (
    ("call_wall", "Call wall"),
    ("put_wall", "Put wall"),
    ("gamma_flip", "Γ flip"),
    ("max_pain", "Max pain"),
    ("absolute_gamma_strike", "Abs Γ"),
    ("pin_candidate", "Pin candidate"),
    ("gsf", "GSF"),
    ("grc", "GRC"),
    ("hvp", "Net put Γ peak"),
    ("lvp", "Net call Γ peak"),
    ("key_delta_strike", "Key Δ strike"),
    ("call_delta_wall", "Call Δ wall"),
    ("put_delta_wall", "Put Δ wall"),
    ("call_charm_wall", "Call charm wall"),
    ("put_charm_wall", "Put charm wall"),
)
#: The levels a same-day clock can move: all but the two read on the whole book alone.
SAME_DAY_LEVELS = tuple(
    level for level in OPTION_LEVELS if level[0] not in ("max_pain", "pin_candidate")
)


def same_day_levels(
    expiry_rows: dict[str | None, list[OptionContract]],
    spot: float,
    *,
    now: datetime,
    sessions: Mapping[str, Session],
    product: str,
    books: dict[ExpiryKey, Book],
    charm_by_expiry: dict[str | None, dict[float, CharmBucket]],
) -> tuple[dict[str, float | None], str | None]:
    """Return the whole book's levels on a 0DTE basis, read on the nearest listed expiry alone.

    With the expiry they were re-priced from (None when an expiry listed today was read as held,
    or when there are no levels): a re-priced set is a model, and the screen says so on hover.

    Every ticker, one function, the same producers as the whole book, over the book's contracts
    by expiry day (`expiry_rows`). An expiry listed today is read as the book holds it: its
    exposure books (`books`, from Schwab's gamma and delta as sent), its gamma profile and its
    charm map (`charm_by_expiry`). With none listed today Schwab
    sends no Greek at today's close, so the next listed expiry is priced as if it expired at
    today's option close (calc.math_levels.repriced_to_close) and read the same way. Absent when the
    chain lists no expiry from today on. A later expiry's are absent too when `now` is past
    today's close (a chain is valued at that close, time_et.valuation_instant, so they stand
    there) or no option window is held for today.
    """
    blank: dict[str, float | None] = {name: None for name, _label in SAME_DAY_LEVELS}
    today = now.astimezone(ET).date().isoformat()
    front = min((e for e in expiry_rows if e is not None and e >= today), default=None)
    if front is None:
        return blank, None
    rows = expiry_rows[front]
    repriced_from = None if front == today else front
    if front == today:
        front_books = (b for (e, _d), b in books.items() if e == front)
        parsed, _unpriced = contract_inputs(rows, now, sessions=sessions, product=product)
        charm = charm_by_expiry[front]
    else:
        t_close = time_to_expiry_years(today, now, sessions=sessions, product=product)
        if not t_close:
            return blank, None
        rows, parsed = repriced_to_close(rows, spot, t_close)
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
    return levels, repriced_from


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
    regime is the sign of dealer gamma at the price (build_terrain_read). `now`: the valuation
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
    same_day, same_day_repriced_from = same_day_levels(
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
        same_day=same_day,
        same_day_repriced_from=same_day_repriced_from,
        **_front_max_pain(books),
        # ExposureDiagnostics is a frozen dataclass; contracts_used is ALWAYS an int.
        contracts_used=diag.contracts_used,
        strikes_used=len(exposures),
        dollarized=exposures_have_dollar_gex(exposures),
        # the LIVE per-strike map, computed from THIS chain; session volume is carried alongside.
        per_strike=per_strike_view(books, exposures),
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
    note says so.
    """
    parsed, _unpriced = contract_inputs(contracts, now, sessions=sessions, product=product)
    profile = compute_gamma_profile(parsed, spot)
    # GSF/GRC from the SAME materialized profile — no second materialization.
    gsl = compute_gamma_support_levels(profile, spot)
    return {
        "gamma_flip": gamma_flip_from_profile(profile, spot),
        "gsf": gsl["gsf"],
        "grc": gsl["grc"],
        "flip_note": flip_note(gamma_at_spot, gamma_at_price(profile, spot)),
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
