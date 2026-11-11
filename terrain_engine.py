"""Terrain pipeline — levels only, no model stack.

This module is pure: it takes contracts + spot and returns a payload. Fetching and
scheduling live in the caller, so this stays trivially testable.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields, replace
from datetime import datetime
from typing import Any

from confluence_composite import iv_by_strike
from math_exposure_core import (
    book_net_gex,
    book_total_oi,
    bucket_metric,
    exposure_books,
    exposures_have_dollar_gex,
    merge_exposure_books,
    net_gex_dollars_at_strike,
    pick_delta_wall_strikes,
    pick_gamma_wall_strikes,
    pick_key_delta_strike,
    pick_pin_and_strength,
    pick_volatility_point_strikes,
    put_call_oi_ratio,
    put_call_volume_ratio,
    schwab_iv_to_sigma,
    strike_total_oi,
    strike_total_volume,
    total_gex_dollars_at_strike,
)
from math_levels import (
    compute_charm_by_strike,
    compute_gamma_flip_v2,
    compute_gamma_profile,
    compute_gamma_support_levels,
    compute_max_pain,
    contract_inputs,
    merge_charm_maps,
    pick_charm_wall_strikes,
    repriced_to_close,
)
from math_probabilities import compute_pin_score
from numeric_contract import float_finite_or_none
from option_contract import OptionContract
from terrain_read import LEVEL_ABOVE, LEVEL_BELOW, build_terrain_read, level_side, price_side
from time_et import ET, option_close_product, time_to_expiry_years

#: Payload schema version — bump on any field change so the UI can fail closed.
TERRAIN_SCHEMA_VERSION = 5


@dataclass(frozen=True)
class TerrainSnapshot:
    """Everything the terrain tab renders, computed from one chain."""

    ticker: str
    spot: float | None
    schema_version: int = TERRAIN_SCHEMA_VERSION

    # regime
    regime: str = "UNAVAILABLE"
    posture: str = "STAND_ASIDE"
    confidence: str = "UNAVAILABLE"
    headline: str = ""

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
    #: SIGN decides pin vs repel. The raw value carries the metric's name; the word "pin" is
    #: reserved for `pin_candidate` below, which must earn it. Strength = leader's margin
    #: over the runner-up on the same metric (a 1% lead is a coin flip; the label says so).
    absolute_gamma_strike: float | None = None
    absolute_gamma_strength_pct: float | None = None
    #: GEX$ / OI at absolute_gamma_strike plus book OI, from the SAME exposures
    #: book that picked the strike. pin_score reads these so strike and magnitude cannot
    #: split onto the analytics selected-expiry book. None = fail-closed
    #: (absent/stale/undollarized).
    absolute_gamma_gex_dollars: float | None = None
    absolute_gamma_oi: float | None = None
    book_oi_total: float | None = None
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
    #: at/beyond the call wall (resistance strengthens before it exhausts). gsf_state is
    #: the fail-closed verdict: OK | BELOW_SUPPORT (negative regime — no fabricated
    #: price) | UNAVAILABLE.
    gsf: float | None = None
    grc: float | None = None
    gsf_state: str = "UNAVAILABLE"

    #: The levels on a 0DTE basis (same_day_levels). Keys are SAME_DAY_LEVELS.
    #: absolute_gamma_strike in this dict is the one 0DTE pin.
    same_day: dict[str, float | None] = field(default_factory=dict)

    #: The institutional sigma band — {points, iv_pct_atm, dte_used, method} or None
    #: when ATM IV is unusable (fail-closed, never a fabricated band). `points` is the
    #: one-sigma half-width; the client centers it on the live spot. The wall RANGE itself
    #: is the put_wall↔call_wall corridor — already carried above, drawn client-side.
    implied_1d_move: dict[str, Any] | None = None

    #: Delta walls owned by THIS producer — same wide chain,
    #: one book. Concepts terrain does not compute (OI/vanna walls, inflections) do not
    #: get fields here and render BLANK with a withheld reason, never an analytics book.
    call_delta_wall: float | None = None
    put_delta_wall: float | None = None

    # provenance — never render a level without knowing where it came from
    contracts_used: int = 0
    strikes_used: int = 0
    dollarized: bool = False
    flip_diag: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    #: (price, net dealer gamma) samples; kept OUT of to_dict() (~240 pairs).
    profile: list[tuple[float, float]] = field(default_factory=list, repr=False)

    #: The LIVE per-strike map the walls were picked from; the per-strike panel reads it, at
    #: no additional vendor cost — the chain is already in hand. Kept OUT of to_dict() for the
    #: same reason as `profile`: too heavy for every poll; the strikes endpoint reads it directly.
    #: per_strike_view's rows ({all, near, far, dex, oi}); with no book priced, each is empty.
    per_strike: dict[str, list] = field(default_factory=lambda: per_strike_view({}, {}), repr=False)
    #: The exposure_books every number above was priced from ({(expiry, dte): (book, diag)}):
    #: the gamma-surface grid is shaped from them, so levels, per-strike rows and heatmap
    #: cells come from one pricing pass.
    books: dict = field(default_factory=dict, repr=False)
    #: {strike: charm bucket} from compute_charm_by_strike -- the charm walls above and the
    #: charm-by-strike panel read the same map.
    charm_by_strike: dict = field(default_factory=dict, repr=False)
    #: {expiry: {strike: charm bucket}} from the same function, one call per expiry.
    #: The confluence matrix reads the expiry it shows and does not call the function again.
    charm_by_expiry: dict = field(default_factory=dict, repr=False)
    #: {expiry: {strike: vol points}} from iv_by_strike, one call per expiry.
    #: The confluence matrix reads the expiry it shows and does not call the blend again.
    iv_by_expiry: dict = field(default_factory=dict, repr=False)
    #: {expiry: put OI / call OI} for each listed expiry
    pcr_by_expiry: dict = field(default_factory=dict)  # put/call OI (positions held)
    #: each expiry's ATM implied vol, percent (atm_sigma_by_expiry); None when a leg has no IV
    atm_iv_pct_by_expiry: dict = field(default_factory=dict)
    pcr_volume_by_expiry: dict = field(default_factory=dict)  # put/call volume (today's trading)
    #: the same two ratios over the whole book (every expiry)
    pcr_all: float | None = None
    pcr_volume_all: float | None = None
    #: every expiry the chain lists, ascending
    expiries: list = field(default_factory=list)
    #: {expiry: Schwab's daysToExpiration as sent with this chain}
    expiry_dte: dict = field(default_factory=dict)
    #: Wall-clock the chain behind per_strike was fetched — every consumer must be able to render
    #: an age on its face rather than implying "now".
    computed_ts_utc: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return the per-poll payload.

        It holds every field except the heavy maps (profile, per_strike, books,
        charm_by_strike), which the server reads off the snapshot.
        """
        light = replace(self, **{n: None for n in _HEAVY_FIELDS})
        return {k: v for k, v in asdict(light).items() if k not in _HEAVY_FIELDS}


_HEAVY_FIELDS = (
    "profile",
    "per_strike",
    "books",
    "charm_by_strike",
    "charm_by_expiry",
    "iv_by_expiry",
)


def _unavailable(ticker: str, spot: float | None, reason: str) -> TerrainSnapshot:
    read = build_terrain_read(spot=spot, flip=None, flip_confidence="UNAVAILABLE")
    return TerrainSnapshot(
        ticker=ticker,
        spot=spot,
        regime=read.regime,
        posture=read.posture,
        confidence=read.confidence,
        headline=read.headline,
        error=reason,
    )


def side_total(values: list[float | None]) -> float | None:
    """Return a total of strikes.

    Unknown with a strike not known or no strike at all, never the sum of the rest.
    """
    return None if not values or None in values else sum(values)


def _per_strike_rows(exposures: dict) -> list[list]:
    """`[[strike, net_gex_1pct$, session_volume], …]` — the EXACT shape the panel renders.

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
    rows: list[list] = []
    for k, b in exposures.items():
        sk = float_finite_or_none(k)
        if sk is None:  # a NaN strike must never become a rendered bar
            continue
        gf = float_finite_or_none(net_gex_dollars_at_strike(b))
        vol = strike_total_volume(b)
        rows.append([sk, gf, vol])
    rows.sort(key=lambda r: r[0])
    return rows


#: the levels compared day over day (level_moves), in the order the page lists them
LEVELS_COMPARED = ("call_wall", "put_wall", "gamma_flip")


def level_moves(today: TerrainSnapshot | None, prior: TerrainSnapshot | None) -> list[dict]:
    """Return the call wall, put wall and gamma flip today against the prior day's own.

    Each as {level, prior, today, change}: change = today - prior, None (unknown) without both.
    Both days' levels are the one producer's (compute_terrain); none is held without that day.
    """
    moves = []
    for name in LEVELS_COMPARED:
        was = None if prior is None else getattr(prior, name)
        now = None if today is None else getattr(today, name)
        change = None if was is None or now is None else now - was
        moves.append({"level": name, "prior": was, "today": now, "change": change})
    return moves


def positioning_migration(today: list, prior: list, call_wall, put_wall) -> dict:
    """Return day-over-day positioning for one DTE scope.

    It is built from GEX-by-strike rows [strike, net_gex_1pct$, volume] of today and of the
    prior capture.

    rows: [strike, gex today, gex prior, change] (None where either day has no value); grew /
    shrank: the two strikes that gained / lost the most GEX; busiest: the two strikes with the
    most volume and where they sit against the walls; volume_total: the scope's session volume
    (side_total).
    """
    prior_gex = {r[0]: r[1] for r in prior}
    rows = []
    for k, gx, _vol in today:
        gy = prior_gex.get(k)
        rows.append([k, gx, gy, (gx - gy) if gx is not None and gy is not None else None])
    changes = sorted((r for r in rows if r[3] is not None), key=lambda r: r[3], reverse=True)
    grew = [r[0] for r in changes if r[3] > 0][:2]
    shrank = [r[0] for r in changes if r[3] < 0][-2:]
    vols = [(r[0], r[2]) for r in today if r[2]]
    busiest = sorted(k for k, _v in sorted(vols, key=lambda kv: kv[1], reverse=True)[:2])
    where = None
    if busiest:
        where = (
            "ABOVE_CALL_WALL"
            if call_wall is not None and min(busiest) > call_wall
            else "BELOW_PUT_WALL"
            if put_wall is not None and max(busiest) < put_wall
            else "INSIDE_WALLS"
        )
    return {
        "rows": rows,
        "compared": bool(changes),
        "grew": grew,
        "shrank": shrank,
        "busiest": busiest,
        "busiest_vs_walls": where,
        "volume_total": side_total([r[2] for r in today]),
    }


def nearest_strike(strikes, spot) -> float | None:
    """Return the listed strike nearest `spot` (the lower one on a tie).

    It is the row every panel marks as spot. None without a spot or a strike.
    """
    ks = sorted(float(k) for k in strikes)
    if spot is None or not ks:
        return None
    return min(ks, key=lambda k: abs(k - float(spot)))


#: The strikes a panel shows per scope: Auto and Wider a count centred on the price, All every one.
SCOPES = ("auto", "wider", "all")
SCOPE_ROWS = {"auto": 11, "wider": 23}


def strike_window(strikes, centre, scope: str, shift: int = 0) -> tuple[int, int, float | None]:
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


def chain_ladder(
    contracts: list[OptionContract], spot, shown: list[dict]
) -> tuple[list[dict], int]:
    """Return one expiry's chain as the ladder draws it, and how many contracts it could not place.

    A contract it cannot place has no strike, or a putCall other than CALL/PUT. Strikes high to
    low; per strike one row per listed
    contract index (a second contract at one strike and side gets its own row), each contract as
    `shown` (option_contract.chain_row, in the order of `contracts`); `call_itm` / `put_itm`
    against `spot` (None without one); `spot` marks the first row of the strike nearest spot.
    """
    by_k: dict[float, dict[str, list]] = {}
    unplaced = 0
    for c, row in zip(contracts, shown, strict=True):
        if c.strike is None or c.side is None:
            unplaced += 1
            continue
        by_k.setdefault(c.strike, {"call": [], "put": []})[c.side.lower()].append(row)
    spot_k = nearest_strike(by_k, spot)
    rows = []
    for k in sorted(by_k, reverse=True):
        g = by_k[k]
        rows.extend(
            {
                "strike": k,
                "first": i == 0,
                "spot": i == 0 and k == spot_k,
                "call": g["call"][i] if i < len(g["call"]) else None,
                "put": g["put"][i] if i < len(g["put"]) else None,
                "call_itm": None if spot is None else k < spot,
                "put_itm": None if spot is None else k > spot,
            }
            for i in range(max(len(g["call"]), len(g["put"])))
        )
    return rows, unplaced


def atm_sigma_by_expiry(
    contracts: list[OptionContract], spot: float
) -> dict[tuple[str | None, float | None], float | None]:
    """Return each expiry's ATM implied vol as a fraction, keyed like exposure_books.

    The key is (expiry, days to expiry). The value is the mean of the call and the put IV, each
    at its side's strike nearest spot. Both legs or None: one side's IV never stands in for the
    mean, and a leg whose nearest contract has no IV from Schwab (-999, or 0: no sigma) has
    none -- the next strike's IV never stands in for it. Schwab `volatility` is a percent,
    converted by schwab_iv_to_sigma.
    """
    legs: dict[tuple[str | None, float | None], dict[str, tuple[float, float | None]]] = {}
    for c in contracts:
        sides = legs.setdefault((c.expiry, c.days_to_expiry), {})
        if c.strike is None or c.side is None:
            continue
        d = abs(c.strike - float(spot))
        if c.side not in sides or d < sides[c.side][0]:
            sides[c.side] = (d, schwab_iv_to_sigma(c.volatility))
    out: dict[tuple[str | None, float | None], float | None] = {}
    # a contract with no expiry date keeps its own key (None), last
    for k, s in sorted(legs.items(), key=lambda kv: (kv[0][0] is None, kv[0][0])):
        sig = [s[x][1] for x in ("CALL", "PUT") if x in s]
        out[k] = (sig[0] + sig[1]) / 2.0 if len(sig) == 2 and None not in sig else None
    return out


def compute_implied_one_day_move(
    contracts: list[OptionContract], spot: float | None, atm_sigma: dict
) -> dict | None:
    """Compute the institutional sigma band: EM_1d = S x sigma_ATM x sqrt(1/252).

    THE STANDARD, named: SpotGamma — whose levels product ships on Bloomberg — treats the
    wall as a single strike, the RANGE as the put-wall-to-call-wall corridor, and overlays
    the Implied 1-Day Move: a one-standard-deviation band (68.3 percent confidence). The
    textbook EM uses front-expiry ATM implied volatility, annualized, scaled by
    sqrt(1/252) for one trading day.

    IV source: the call+put pair closest to spot on the first expiry at least one day out (a
    same-day expiry's IV prices hours, not a day), from `atm_sigma` (atm_sigma_by_expiry of the
    same contracts, computed once by the caller). Schwab `volatility` is PERCENT, not a fraction
    (measured on 1,600 sampled contracts); atm_sigma_by_expiry converts it through
    schwab_iv_to_sigma. Fails closed: no usable ATM IV means None, never a fabricated band (a
    made-up sigma is worse than no sigma).

    Returns {points, iv_pct_atm, dte_used, method} — `points` is the one-sigma HALF-width
    in price points; the client centers it on the LIVE spot so the band can never disagree
    with the price beside it.
    """
    if spot is None or spot <= 0 or not contracts:
        return None
    # A contract that does not state its DTE is dropped BEFORE the min, so an all-unreadable
    # chain yields None here (no front expiry).
    # the first expiry at least one day out: a same-day expiry's IV prices hours, not a day
    _dtes = [d for c in contracts if (d := c.days_to_expiry) is not None and d >= 1]
    front = min(_dtes, default=None)
    if front is None:
        return None
    at_front = [s for (_e, d), s in atm_sigma.items() if d == front]
    if len(at_front) != 1 or at_front[0] is None:
        return None
    sigma = at_front[0]
    em = float(spot) * sigma * (1.0 / 252.0) ** 0.5
    return {
        "points": em,
        "iv_pct_atm": sigma * 100.0,
        "dte_used": front,
        "method": "S x sigma_ATM x sqrt(1/252), one standard deviation (68.3pct); "
        "sigma = mean ATM call/put implied vol of the first expiry at least a day out",
    }


def _per_strike_measure_rows(exposures: dict) -> dict:
    """`{"dex": [[strike, net DEX $], …], "oi": [[strike, total OI], …]}` per known strike.

    Every strike whose value is known, by the heatmap cell's own readers (net_dex_dollars of a
    dollarized book; strike_total_oi). Open interest keeps every digit; the screen rounds the
    count. A strike whose value is unknown has no row.
    """
    dex: list[list] = []
    oi: list[list] = []
    dollarized = bool(exposures) and exposures_have_dollar_gex(exposures)
    for k, b in exposures.items():
        sk = float_finite_or_none(k)
        if sk is None or not isinstance(b, dict):
            continue
        d = float_finite_or_none(bucket_metric(b, "net_dex_dollars")) if dollarized else None
        if d is not None:
            dex.append([sk, d])
        o = strike_total_oi(b)
        if o is not None:
            oi.append([sk, o])
    dex.sort(key=lambda r: r[0])
    oi.sort(key=lambda r: r[0])
    return {"dex": dex, "oi": oi}


def per_strike_view(books: dict, exposures: dict) -> dict:
    """`{all, near, far}` GEX rows -- the ALL / <=7DTE / MONTHLY+ chips -- and DEX and OI rows.

    The GEX rows come from the chain's exposure_books and their merged full book `exposures`
    (one pricing pass), and the full book's DEX and OI rows (`dex`, `oi`:
    _per_strike_measure_rows). A contract whose days-to-expiry cannot be read belongs to `all`
    only: a maturity split it cannot answer is not answered for it.
    """

    def rows(keep) -> list:
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
    pin_candidate: float | None
    pin_candidate_blockers: list[str]
    lines: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


#: the names of the relations served beside the levels
PRICE_RELATIONS = frozenset(f.name for f in fields(PriceRelations))


def price_relations(terrain: dict, price: float | None) -> PriceRelations:
    """Return every relation of `price` to the published levels (`terrain`, a snapshot's to_dict).

    Each wall's state and lean, the price's side of the flip, the pin candidate and the read's
    lines. The levels are the publication's; the price is the one given, the live price on
    every panel. A level's distance from the price is served with the level (the levels panel).
    """
    call, put, flip = terrain["call_wall"], terrain["put_wall"], terrain["gamma_flip"]
    call_lean, put_lean = wall_lean(call, put, price, terrain["regime"], terrain["confidence"])
    read = build_terrain_read(
        spot=price,
        flip=flip,
        flip_confidence=terrain["confidence"],
        put_wall=put,
        call_wall=call,
        gamma_at_spot=terrain["net_gex_at_spot"],
        flip_curve_agrees=terrain["flip_diag"].get("curve_agrees_with_schwab_at_spot"),
    )
    pin, pin_blockers = qualify_pin_candidate(
        spot=price,
        absolute_gamma_strike=terrain["absolute_gamma_strike"],
        absolute_gamma_strength_pct=terrain["absolute_gamma_strength_pct"],
        absolute_gamma_gex_dollars=terrain["absolute_gamma_gex_dollars"],
        absolute_gamma_oi=terrain["absolute_gamma_oi"],
        book_oi_total=terrain["book_oi_total"],
        net_gex_at_spot=terrain["net_gex_at_spot"],
        front_dte=terrain["max_pain_dte"],
    )
    return PriceRelations(
        call_wall_state=wall_geometry_state(price, call, "call"),
        put_wall_state=wall_geometry_state(price, put, "put"),
        call_wall_lean=call_lean,
        put_wall_lean=put_lean,
        flip_relation=price_side(flip, price),
        pin_candidate=pin,
        pin_candidate_blockers=list(pin_blockers),
        lines=read.lines,
    )


def wall_lean(call_wall, put_wall, price, regime, confidence) -> tuple:
    """(call, put) wall labels as the chart states them at `price`.

    One strike holding both walls is TWO-SIDED (a magnet, not a barrier); a breached wall says
    where the price is (above, at or below it); a containing wall earns the dealer lean
    (resistance: dealers sell, support: dealers buy) only on a TRUSTED flip with a regime;
    otherwise None.
    """
    if call_wall is not None and call_wall == put_wall:
        return ("TWO-SIDED — magnet, not a barrier",) * 2
    earn = regime != "UNAVAILABLE" and confidence == "TRUSTED"

    def one(wall, side, lean):
        state = wall_geometry_state(price, wall, side)
        if state == WALL_BREACHED:
            return f"BREACHED — spot {price_side(wall, price).lower()}"
        return lean if state == WALL_CONTAINS and earn else None

    return one(call_wall, "call", "DEALERS SELL"), one(put_wall, "put", "DEALERS BUY")


#: Pin-candidate qualification thresholds. Hardwired, not configurable.
#: — proximity: strike within 0.5% of spot — the "strike near spot" cut of a pin-residence
#:   study that is not in this repository, so the value is NOT_PROVEN here.
PIN_CANDIDATE_PROXIMITY_MAX_FRAC = 0.005
#: — DTE: pinning is an expiration effect (expiration-date clustering turns on positioning
#:   into expiry — Ni, Pearson & Poteshman, JFE 2005, doi:10.1016/j.jfineco.2004.08.005);
#:   the cut is dte <= 1 (from the same study, NOT_PROVEN here).
PIN_CANDIDATE_DTE_MAX = 1.0


def qualify_pin_candidate(
    *,
    spot: float | None,
    absolute_gamma_strike: float | None,
    absolute_gamma_strength_pct: float | None,
    absolute_gamma_gex_dollars: float | None,
    absolute_gamma_oi: float | None,
    book_oi_total: float | None,
    net_gex_at_spot: float | None,
    front_dte: float | None,
) -> tuple[float | None, list[str]]:
    """Publish `pin_candidate` ONLY after qualification.

    The qualification is regime, proximity, DTE, liquidity and completeness.

    The raw absolute-gamma strike is a gross gamma concentration — a pin CANDIDATE input,
    never a demonstrated magnet (magnitude sizes the hedging flow; the unobservable
    dealer sign decides pin vs repel). This gate is the difference between the metric and
    the claim. Gates, each fail-closed (missing input = gate failed, never assumed passed):

    — completeness: the magnitude bundle (strike, strength, GEX$, OI, book OI) is
      present from the SAME book that picked the strike.
    — regime: dealers net LONG gamma at spot (net_gex_at_spot > 0). A long-gamma dealer
      sells rallies and buys dips, which pins; short gamma repels.
    — proximity: |strike − spot| / spot <= PIN_CANDIDATE_PROXIMITY_MAX_FRAC.
    — DTE: front expiry of THIS book within PIN_CANDIDATE_DTE_MAX days (pinning is an
      expiration effect); unknown maturity fails, never passes.
    — liquidity: the committed pin-score thresholds (math_probabilities.compute_pin_score,
      GEX magnitude × OI concentration) grade the strike above "negligible". No new
      threshold is invented here — the gate reuses the one already on the operator's
      screen as PIN SCORE.

    Returns (pin_candidate, blockers): the strike with an EMPTY blockers list when every
    gate passes, else (None, [failed gate names]) so absence renders with its reason.
    """
    blockers: list[str] = []
    complete = not (
        spot is None
        or absolute_gamma_strike is None
        or absolute_gamma_strength_pct is None
        or absolute_gamma_gex_dollars is None
        or absolute_gamma_oi is None
        or book_oi_total is None
        or book_oi_total <= 0
    )
    if not complete:
        blockers.append("completeness")
    if net_gex_at_spot is None or net_gex_at_spot <= 0:
        blockers.append("regime")
    if spot is not None and spot > 0 and absolute_gamma_strike is not None:
        if (
            abs(float(absolute_gamma_strike) - float(spot)) / float(spot)
            > PIN_CANDIDATE_PROXIMITY_MAX_FRAC
        ):
            blockers.append("proximity")
    elif "completeness" not in blockers:
        blockers.append("completeness")
    if front_dte is None or float(front_dte) > PIN_CANDIDATE_DTE_MAX:
        blockers.append("dte")
    if complete:
        score = compute_pin_score(
            absolute_gamma_gex_dollars,
            (float(absolute_gamma_oi) / float(book_oi_total)),
        )
        if score.get("label") in (None, "negligible", "missing_oi"):
            blockers.append("liquidity")
    else:
        blockers.append("liquidity")
    if blockers:
        return None, blockers
    return float(absolute_gamma_strike), []


#: The terrain's price levels and the name each is shown under, in the order they are listed.
OPTION_LEVELS = (
    ("call_wall", "Call wall"),
    ("put_wall", "Put wall"),
    ("gamma_flip", "Gamma flip"),
    ("max_pain", "Max pain"),
    ("absolute_gamma_strike", "Abs Γ"),
    ("pin_candidate", "Pin candidate"),
    ("gsf", "GSF"),
    ("grc", "GRC"),
    ("hvp", "Net put Γ peak"),
    ("lvp", "Net call Γ peak"),
    ("key_delta_strike", "Key Δ strike"),
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
    product: str,
    books: dict,
    charm_by_expiry: dict[str | None, dict],
) -> dict[str, float | None]:
    """Return the whole book's levels on a 0DTE basis, read on the nearest listed expiry alone.

    Every ticker, one function, the same producers as the whole book, over the book's contracts
    by expiry day (`expiry_rows`). An expiry listed today is read as the book holds it: its
    exposure books (`books`, from Schwab's gamma and delta as sent), its gamma profile and its
    charm map (`charm_by_expiry`). With none listed today Schwab
    sends no Greek at today's close, so the next listed expiry is priced as if it expired at
    today's option close (math_levels.repriced_to_close) and read the same way. Absent when the
    chain lists no expiry from today on. A later expiry's are absent too when `now` is past
    today's close (a chain is valued at that close, time_et.valuation_instant, so they stand
    there) or no option window is held for today.
    """
    blank = {name: None for name, _label in SAME_DAY_LEVELS}
    today = now.astimezone(ET).date().isoformat()
    front = min((e for e in expiry_rows if e is not None and e >= today), default=None)
    if front is None:
        return blank
    rows = expiry_rows[front]
    if front == today:
        front_books = (b for (e, _d), b in books.items() if e == front)
        parsed, _unpriced = contract_inputs(rows, now, product=product)
        charm = charm_by_expiry[front]
    else:
        t_close = time_to_expiry_years(today, now, product=product)
        if not t_close:
            return blank
        rows, parsed = repriced_to_close(rows, spot, now, t_close, product)
        front_books = exposure_books(rows, spot=spot, now=now, product=product).values()
        charm = compute_charm_by_strike(rows, spot, now=now, t_years=t_close, product=product)
    exposures, _diag = merge_exposure_books(front_books)
    (call_wall, _), (put_wall, _) = pick_gamma_wall_strikes(exposures)
    pin, _strength = pick_pin_and_strength(exposures)
    hvp, lvp = pick_volatility_point_strikes(exposures)
    profile = compute_gamma_profile(parsed, spot)
    flip, _confidence, _flip_diag = compute_gamma_flip_v2(rows, spot, profile=profile)
    support = compute_gamma_support_levels(profile, spot)
    call_charm, put_charm = pick_charm_wall_strikes(charm)
    return {
        "call_wall": call_wall,
        "put_wall": put_wall,
        "gamma_flip": flip,
        "absolute_gamma_strike": pin,
        "gsf": support["gsf"],
        "grc": support["grc"],
        "hvp": hvp,
        "lvp": lvp,
        "key_delta_strike": pick_key_delta_strike(exposures),
        "call_charm_wall": call_charm,
        "put_charm_wall": put_charm,
    }


def compute_terrain(
    ticker: str, contracts: list[OptionContract] | None, spot: float | None, *, now: datetime
) -> TerrainSnapshot:
    """Full terrain for one ticker. Fails closed — never invents a level.

    `now`: the valuation instant for every time-to-expiry in this snapshot, read once by the
    caller's entry point (the live reprice: its own instant; a replay of a stored chain: the
    snapshot's time, so it reproduces what the live reprice saw).

    This is the ONE terrain engine. It must be
    fed the wide-capture multi-expiry chain — the full-chain
    basis (dealers hedge the whole delta book across weekly/monthly expiries, not
    just the 0DTE slice). The narrow-chain confidence gate in compute_gamma_flip_v2
    is the fail-closed backstop: a genuinely narrow chain (e.g. wide
    capture unavailable) still yields STAND_ASIDE, never a trusted-looking verdict.
    """
    if not contracts:
        return _unavailable(ticker, spot, "no option chain")
    if spot is None or spot <= 0:
        return _unavailable(ticker, spot, "no spot price")

    # ONE valuation instant for every book below, on this ticker's option close
    _terrain_now = now
    product = option_close_product(ticker)
    # One pricing pass: exposures per (expiry, DTE) group; every book below is a merge of them.
    books = exposure_books(contracts, spot=spot, now=_terrain_now, product=product)
    exposures, diag = merge_exposure_books(books.values())
    dated = {k: b for k, b in books.items() if k[0] is not None}
    _dtes = [d for (_e, d) in books if d is not None]
    _front_dte = min(_dtes, default=None)
    if not exposures:
        return _unavailable(ticker, spot, "chain produced no exposures")

    (call_wall, _cw_str), (put_wall, _pw_str) = pick_gamma_wall_strikes(exposures)
    hvp, lvp = pick_volatility_point_strikes(exposures)
    # max TOTAL gamma — the absolute-gamma concentration, full book.
    _abs_gamma_strike, _abs_gamma_strength = pick_pin_and_strength(exposures)
    # pin_score GEX/OI from THIS same exposures book — never a second analytics book.
    # OI from the ONE reader -- unknown (a contract that never reported OI) is None, never 0.

    _book_oi_total = book_total_oi(exposures)
    _abs_gamma_gex_dollars = None
    _abs_gamma_oi = None
    _abs_gamma_bucket = (
        exposures.get(float(_abs_gamma_strike)) if _abs_gamma_strike is not None else None
    )
    if isinstance(_abs_gamma_bucket, dict):
        _abs_gamma_gex_dollars = total_gex_dollars_at_strike(_abs_gamma_bucket)
        _abs_gamma_oi = strike_total_oi(_abs_gamma_bucket)
    # the SSOT producer owns the delta walls too — same wide
    # chain, same exposures, one book. OI/vanna walls stay unowned and therefore BLANK on
    # every operator surface until this producer computes them.
    (call_delta_wall, _cdw_str), (put_delta_wall, _pdw_str) = pick_delta_wall_strikes(exposures)
    # the gamma profile, built once at one instant, feeds the flip verdict and the regime read
    parsed, unpriced = contract_inputs(contracts, _terrain_now, product=product)
    profile = compute_gamma_profile(parsed, spot)
    flip, confidence, flip_diag = compute_gamma_flip_v2(contracts, spot, profile=profile)
    # ONE gamma at spot: Schwab's gamma as sent, summed over the book (the walls' own gamma).
    # The model curve places the flip only (Schwab sends gamma at its own price, never at
    # other prices); where the curve's sign at spot disagrees with Schwab's, the flip says so.
    _curve_at_spot = flip_diag.get("curve_gamma_at_spot")
    _gamma_at_spot = book_net_gex(exposures)
    flip_diag = {
        **flip_diag,
        "unpriced": unpriced,
        "gamma_at_spot": _gamma_at_spot,
        "curve_agrees_with_schwab_at_spot": (
            None
            if _gamma_at_spot is None or _curve_at_spot is None
            else (_gamma_at_spot > 0) == (_curve_at_spot > 0)
        ),
    }
    # GSF/GRC from the SAME materialized profile — no second materialization.
    _gsl = compute_gamma_support_levels(profile, spot)
    # Max pain on the FRONT expiry only.
    _front_max_pain = None
    if _front_dte is not None:
        _exp_front, _ = merge_exposure_books(
            b for (_e, d), b in books.items() if d is not None and d <= _front_dte
        )
        _front_max_pain = compute_max_pain(_exp_front)
    # each expiry's ATM implied vol, once: the one-day move's and the per-expiry ATM IV's
    atm_sigma = atm_sigma_by_expiry(contracts, spot)

    charm_by_expiry = {}
    iv_by_expiry = {}
    expiry_rows: dict[str | None, list] = {}
    for c in contracts:
        # no readable date keeps its row under None, so its side is unknown
        expiry_rows.setdefault(c.expiry, []).append(c)
    for exp, rows in expiry_rows.items():
        charm_by_expiry[exp] = compute_charm_by_strike(
            rows, float(spot), now=_terrain_now, product=product
        )
        iv_by_expiry[exp] = iv_by_strike(rows)
    charm_by_strike = merge_charm_maps(charm_by_expiry)
    call_charm_wall, put_charm_wall = pick_charm_wall_strikes(charm_by_strike)

    read = build_terrain_read(
        spot=spot,
        flip=flip,
        flip_confidence=confidence,
        put_wall=put_wall,
        call_wall=call_wall,
        gamma_at_spot=flip_diag.get("gamma_at_spot"),
        flip_curve_agrees=flip_diag.get("curve_agrees_with_schwab_at_spot"),
    )

    return TerrainSnapshot(
        ticker=ticker,
        spot=float(spot),
        regime=read.regime,
        posture=read.posture,
        confidence=read.confidence,
        headline=read.headline,
        gamma_flip=flip,
        call_wall=call_wall,
        put_wall=put_wall,
        absolute_gamma_strike=_abs_gamma_strike,
        absolute_gamma_strength_pct=_abs_gamma_strength,
        absolute_gamma_gex_dollars=_abs_gamma_gex_dollars,
        absolute_gamma_oi=_abs_gamma_oi,
        book_oi_total=_book_oi_total,
        key_delta_strike=pick_key_delta_strike(exposures),
        hvp=hvp,
        lvp=lvp,
        net_gex_at_spot=flip_diag.get("gamma_at_spot"),
        gsf=_gsl["gsf"],
        grc=_gsl["grc"],
        gsf_state=_gsl["state"],
        same_day=same_day_levels(
            expiry_rows,
            spot,
            now=_terrain_now,
            product=product,
            books=books,
            charm_by_expiry=charm_by_expiry,
        ),
        implied_1d_move=compute_implied_one_day_move(contracts, spot, atm_sigma),
        call_delta_wall=call_delta_wall,  # one book for delta walls too
        put_delta_wall=put_delta_wall,
        max_pain=_front_max_pain,
        max_pain_dte=_front_dte,
        call_charm_wall=call_charm_wall,
        put_charm_wall=put_charm_wall,
        # ExposureDiagnostics is a frozen dataclass; contracts_used is ALWAYS an int.
        contracts_used=diag.contracts_used,
        strikes_used=len(exposures),
        dollarized=exposures_have_dollar_gex(exposures),
        flip_diag=dict(flip_diag),
        profile=profile,
        # the LIVE per-strike map, computed from THIS chain; session volume is carried alongside.
        per_strike=per_strike_view(books, exposures),
        books=books,
        charm_by_strike=charm_by_strike,
        charm_by_expiry=charm_by_expiry,
        iv_by_expiry=iv_by_expiry,
        # each expiry's own: a contract with no expiry date is in the book, under no expiry
        pcr_by_expiry={
            e: put_call_oi_ratio(book)
            for (e, _d), (book, _diag) in sorted(dated.items(), key=lambda kv: kv[0][0])
        },
        atm_iv_pct_by_expiry={
            e: None if s is None else s * 100.0 for (e, _d), s in atm_sigma.items() if e is not None
        },
        pcr_volume_by_expiry={
            e: put_call_volume_ratio(book) for (e, _d), (book, _diag) in dated.items()
        },
        pcr_all=put_call_oi_ratio(exposures),
        pcr_volume_all=put_call_volume_ratio(exposures),
        expiries=sorted({e for (e, _d) in dated}),
        expiry_dte={e: d for (e, d) in dated},
    )
