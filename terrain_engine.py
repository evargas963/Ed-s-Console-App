"""Terrain pipeline — levels only, no model stack.

This module is pure: it takes contracts + spot and returns a payload. Fetching and
scheduling live in the caller, so this stays trivially testable.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields, replace
from datetime import datetime
from typing import Any

from math_exposure_core import (
    book_net_gex,
    compute_net_vanna,
    compute_zero_dte_gamma_share,
    exposure_books,
    exposures_have_dollar_gex,
    merge_exposure_books,
    pick_delta_wall_strikes,
    pick_gamma_wall_strikes,
    pick_key_delta_strike,
    pick_net_gex_peak_strike,
    pick_pin_and_strength,
    pick_volatility_point_strikes,
    put_call_oi_ratio,
    put_call_volume_ratio,
    total_gex_dollars_at_strike,
)
from math_levels import (
    _contract_inputs,
    bs_delta,
    bs_gamma,
    compute_charm_by_strike,
    compute_gamma_flip_v2,
    compute_gamma_profile,
    compute_gamma_support_levels,
    compute_max_pain,
    contract_inputs,
    merge_charm_maps,
    pick_charm_wall_strikes,
)
from numeric_contract import schwab_count, schwab_number
from terrain_read import LEVEL_ABOVE, LEVEL_BELOW, build_terrain_read, level_side, price_side
from time_et import ET, option_close_product, time_to_expiry_years

#: Payload schema version — bump on any field change so the UI can fail closed.
TERRAIN_SCHEMA_VERSION = 3


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
    #: Max |net GEX$| (calls minus puts): where the SIGNED book peaks, distinct from the
    #: concentration.
    #: Scope: FULL_BOOK here; ExposureRow.net_gex_peak is the SAME definition over the
    #: SELECTED_EXPIRY chain (declared, distinct surface).
    net_gex_peak: float | None = None
    #: Total-gamma renders once as ABS GAMMA. Analytics `kl_hvl` is a DIFFERENT book
    #: (net_gex_peak → "Net Γ peak").
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

    #: % of |net GEX$| from SAME-DAY expiry — level persistence. High = today's
    #: walls/flip decay into the close (0DTE gamma dies at 4pm); low = levels persist.
    #: None (fail-closed) when the book is empty, never a fabricated 0%.
    zero_dte_gamma_share_pct: float | None = None
    #: Nearest expiry repriced to today's option close. Keys are SAME_DAY_LEVELS.
    #: absolute_gamma_strike in this dict is the one 0DTE pin.
    same_day: dict[str, float | None] = field(default_factory=dict)

    #: 25Δ risk reversal — {rr_pts, call_iv_25d, put_iv_25d, dte} or None.
    #: Skew steepness on the expiry nearest 30 days out; deterioration toward −6 = the put bid
    #: building (the same-session GSF-breach confirm). Fail-closed None, never fabricated.
    rr_25d: dict | None = None

    #: Aggregate dealer vanna — {net_vanna_dollars_per_volpt, net_vanna_shares_per_volpt}
    #: or None. Sizes the IV-driven hedge flow (vol-crush tailwind / vol-spike selling).
    vanna_agg: dict | None = None

    #: The institutional sigma band — {points, iv_pct_atm, dte_used, method} or None
    #: when ATM IV is unusable (fail-closed, never a fabricated band). `points` is the
    #: one-sigma half-width; the client centers it on the live spot. The wall RANGE itself
    #: is the put_wall↔call_wall corridor — already carried above, drawn client-side.
    implied_1d_move: dict[str, Any] | None = None

    #: Each wall's EARNED per-side range — {lo, hi, coverage_pct, method} or None —
    #: the value-area of the wall's own side-gamma mass (never the strike grid).
    call_wall_range: dict[str, Any] | None = None
    put_wall_range: dict[str, Any] | None = None

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
    per_strike: dict[float, dict[str, Any]] = field(default_factory=dict, repr=False)
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
        """The per-poll payload: every field except the heavy maps (profile, per_strike,
        books, charm_by_strike), which the server reads off the snapshot."""
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


def _per_strike_rows(exposures: dict) -> list[list]:
    """`[[strike, net_gex_1pct$, session_volume], …]` — the EXACT shape the panel renders.

    THE one producer of GEX-by-strike rows (live panel AND the prior-day ghost).

    The finished numbers are handed over as-is, never reassembled into synthetic
    contracts and recomputed.

    No fallbacks:
      * the bar is net GEX$ from a DOLLARIZED book, exact (a strike whose contracts have open
        interest 0 is a $0 bar). A strike whose GEX is not known
        (bucket_metric), or a book built without spot, has no bar.
      * volume is strike_total_volume, the one reader: Schwab's volumes as sent (0 is a real
        zero); None ("—") when a contract at the strike did not report it, never a partial sum.
    """
    from math_exposure_core import (
        exposures_have_dollar_gex,
        net_gex_dollars_at_strike,
        strike_total_volume,
    )
    from numeric_contract import float_finite_or_none

    if not exposures or not exposures_have_dollar_gex(exposures):
        return []
    rows: list[list] = []
    for k, b in exposures.items():
        sk = float_finite_or_none(k)
        if sk is None:  # a NaN strike must never become a rendered bar
            continue
        gf = float_finite_or_none(net_gex_dollars_at_strike(b))
        if gf is None:
            continue
        vol = strike_total_volume(b)
        rows.append([sk, gf, vol])
    rows.sort(key=lambda r: r[0])
    return rows


#: Weighted positive-gamma strike move below which drift reads as none. Its origin is not
#: recorded -- NOT_PROVEN.
MIGRATION_DRIFT_STRIKES = 0.15


def positioning_migration(today: list, prior: list, call_wall, put_wall) -> dict:
    """Day-over-day positioning for one DTE scope, from GEX-by-strike rows
    [strike, net_gex_1pct$, volume] of today and of the prior capture.

    rows: [strike, gex today, gex prior, change] (None where either day has no value); drift:
    the positive-gamma-weighted strike today against the prior day, UP / DOWN / FLAT (None
    without positive gamma on both days); grew / shrank: the two strikes that gained / lost the
    most GEX; busiest: the two strikes with the most volume and where they sit against the walls;
    volume_total: the scope's session volume (None when no row reported volume)."""
    prior_gex = {r[0]: r[1] for r in prior or []}
    rows, pos_t, pos_p = [], [], []
    for k, gx, _vol in today or []:
        gy = prior_gex.get(k)
        both = gx is not None and gy is not None
        rows.append([k, gx, gy, (gx - gy) if both else None])
        if both and gx > 0:
            pos_t.append((k, gx))
        if both and gy > 0:
            pos_p.append((k, gy))

    def _wmean(pairs):
        w = sum(g for _k, g in pairs)
        return sum(k * g for k, g in pairs) / w if w else None

    wm_t, wm_p = _wmean(pos_t), _wmean(pos_p)
    drift = None
    if wm_t is not None and wm_p is not None:
        d = wm_t - wm_p
        drift = (
            "UP"
            if d > MIGRATION_DRIFT_STRIKES
            else "DOWN"
            if -d > MIGRATION_DRIFT_STRIKES
            else "FLAT"
        )
    changes = sorted((r for r in rows if r[3] is not None), key=lambda r: r[3], reverse=True)
    grew = [r[0] for r in changes if r[3] > 0][:2]
    shrank = [r[0] for r in changes if r[3] < 0][-2:]
    vols = [(r[0], r[2]) for r in today or [] if r[2]]
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
    reported = [r[2] for r in today or [] if r[2] is not None]
    return {
        "rows": rows,
        "compared": bool(changes),
        "drift": drift,
        "weighted_strike_today": wm_t,
        "weighted_strike_prior": wm_p,
        "grew": grew,
        "shrank": shrank,
        "busiest": busiest,
        "busiest_vs_walls": where,
        "volume_total": sum(reported) if reported else None,
    }


def nearest_strike(strikes, spot) -> float | None:
    """The listed strike nearest `spot` (the lower one on a tie): the row every panel marks as
    spot. None without a spot or a strike."""
    ks = sorted(float(k) for k in strikes or [])
    if spot is None or not ks:
        return None
    return min(ks, key=lambda k: abs(k - float(spot)))


#: The strikes a panel shows per scope: Auto and Wider a count centred on the price, All every one.
SCOPES = ("auto", "wider", "all")
SCOPE_ROWS = {"auto": 11, "wider": 23}


def strike_window(strikes, centre, scope: str, shift: int = 0) -> tuple[int, int, float | None]:
    """The rows a per-strike panel shows, for every panel and the heatmap alike: (first index,
    last index, the centre strike) into `strikes` (ascending). `scope`'s count of strikes centred
    on the listed strike nearest `centre` (the operator's panned strike, else the price) moved
    `shift` rows (a drag), held inside the list; every strike for "all"; the middle of the list
    when there is no centre (no price). (0, -1, None) for no strikes."""
    ks = [float(k) for k in strikes or []]
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


def chain_ladder(contracts, spot) -> tuple[list[dict], int]:
    """One expiry's chain as the ladder draws it, and how many contracts it could not place (no
    strike, or a putCall other than CALL/PUT). Strikes high to low; per strike one row per listed
    contract index (a second contract at one strike and side gets its own row); each contract's
    numbers read by rule 2 (-999, text, NaN absent); `call_itm` / `put_itm` against `spot` (None
    without one); `spot` marks the first row of the strike nearest spot."""
    from numeric_contract import schwab_number

    by_k: dict[float, dict[str, list]] = {}
    unplaced = 0
    for c in contracts or []:
        k = schwab_number(c.get("strikePrice"))
        side = {"CALL": "call", "PUT": "put"}.get(str(c.get("putCall") or "").upper())
        if k is None or side is None:
            unplaced += 1
            continue
        shown = {
            f: (schwab_number(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v)
            for f, v in c.items()
        }
        by_k.setdefault(k, {"call": [], "put": []})[side].append(shown)
    spot_k = nearest_strike(by_k, spot)
    rows = []
    for k in sorted(by_k, reverse=True):
        g = by_k[k]
        for i in range(max(len(g["call"]), len(g["put"]))):
            rows.append(
                {
                    "strike": k,
                    "first": i == 0,
                    "spot": i == 0 and k == spot_k,
                    "call": g["call"][i] if i < len(g["call"]) else None,
                    "put": g["put"][i] if i < len(g["put"]) else None,
                    "call_itm": None if spot is None else k < spot,
                    "put_itm": None if spot is None else k > spot,
                }
            )
    return rows, unplaced


def _dte_of(ct: object) -> float | None:
    """Days to expiration, or None when the contract does not say.

    None cannot be compared to 7 by accident — a caller must decide what unknown means,
    which for a maturity SPLIT is "belongs to neither side".
    """
    from numeric_contract import schwab_number

    return schwab_number(ct.get("daysToExpiration")) if isinstance(ct, dict) else None


def compute_wall_value_area(
    exposures: dict, wall: float | None, side: str, frac: float = 0.682
) -> dict | None:
    """The wall's EARNED range — Market-Profile value-area math on SIDE gamma mass.

    THE STANDARD, named: the Value Area algorithm (CQG-documented, the Market/Volume Profile
    industry method) — start at the point of control and expand one strike at a time toward
    whichever neighbor holds more mass, until 68.2 percent (one sigma) is enclosed. Here the
    distribution is the wall's own SIDE gamma (call gamma for the call wall, put gamma for
    the put wall), so the range is a property of the POSITIONING — different every day and
    every ticker — never of the strike grid.

    Fail-closed: no wall, wall absent from the mass, or degenerate mass -> None.
    """
    from math_exposure_core import bucket_metric_abs, exposures_have_dollar_gex

    # SIDE GEX$ mass on a dollarized book, valid-gamma strikes only.
    if wall is None or not exposures or not exposures_have_dollar_gex(exposures):
        return None
    key = f"{side}_gex_1pct"
    mass: dict[float, float] = {}
    for k, b in exposures.items():
        v = bucket_metric_abs(b, key)
        if v is not None and v > 0:
            mass[float(k)] = float(v)
    w = float(wall)
    if w not in mass:
        return None
    total = sum(mass.values())
    if total <= 0:
        return None
    ks = sorted(mass)
    li = ri = ks.index(w)
    s = mass[w]
    while s / total < frac and (li > 0 or ri < len(ks) - 1):
        lv = mass[ks[li - 1]] if li > 0 else -1.0
        rv = mass[ks[ri + 1]] if ri < len(ks) - 1 else -1.0
        if rv >= lv:
            ri += 1
            s += rv
        else:
            li -= 1
            s += lv
    return {
        "lo": ks[li],
        "hi": ks[ri],
        "coverage_pct": s / total * 100.0,
        "method": "gamma value area: Market-Profile POC expansion on "
        f"{side}-side GEX mass to 68.2pct (one sigma)",
    }


def atm_sigma_by_expiry(
    contracts: list[dict], spot: float
) -> dict[tuple[str, float | None], float | None]:
    """Each expiry's ATM implied vol as a fraction, keyed like exposure_books ((expirationDate,
    daysToExpiration)): the mean of the call and the put IV, each at its side's strike nearest
    spot. Both legs or None: one side's IV never stands in for the mean,
    and a leg whose nearest contract has no IV from Schwab (-999, or 0: no sigma) has none --
    the next strike's IV never stands in for it. Schwab `volatility` is a percent, converted by
    schwab_iv_to_sigma."""
    from math_exposure_core import schwab_iv_to_sigma
    from numeric_contract import schwab_number

    legs: dict[tuple[str, float | None], dict[str, tuple[float, float | None]]] = {}
    for c in contracts:
        if not isinstance(c, dict):
            continue
        key = (str(c.get("expirationDate") or "")[:10], _dte_of(c))
        sides = legs.setdefault(key, {})
        strike = schwab_number(c.get("strikePrice"))
        side = str(c.get("putCall") or "").upper()
        if strike is None or side not in ("CALL", "PUT"):
            continue
        d = abs(strike - float(spot))
        if side not in sides or d < sides[side][0]:
            sides[side] = (d, schwab_iv_to_sigma(schwab_number(c.get("volatility"))))
    out: dict[tuple[str, float | None], float | None] = {}
    for k, s in sorted(legs.items(), key=lambda kv: kv[0][0]):
        sig = [s[x][1] for x in ("CALL", "PUT") if x in s]
        out[k] = (sig[0] + sig[1]) / 2.0 if len(sig) == 2 and None not in sig else None
    return out


def compute_implied_one_day_move(contracts: list[dict], spot: float | None) -> dict | None:
    """The institutional sigma band: EM_1d = S x sigma_ATM x sqrt(1/252).

    THE STANDARD, named: SpotGamma — whose levels product ships on Bloomberg — treats the
    wall as a single strike, the RANGE as the put-wall-to-call-wall corridor, and overlays
    the Implied 1-Day Move: a one-standard-deviation band (68.3 percent confidence). The
    textbook EM uses front-expiry ATM implied volatility, annualized, scaled by
    sqrt(1/252) for one trading day.

    IV source: the call+put pair closest to spot on the first expiry at least one day out (a
    same-day expiry's IV prices hours, not a day). Schwab `volatility` is PERCENT, not a fraction
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
    _dtes = [
        d
        for d in (_dte_of(c) for c in contracts if isinstance(c, dict))
        if d is not None and d >= 1
    ]
    front = min(_dtes, default=None)
    if front is None:
        return None
    at_front = [s for (_e, d), s in atm_sigma_by_expiry(contracts, spot).items() if d == front]
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
    """`{"dex": [[strike, net DEX $], …], "oi": [[strike, total OI], …]}`: every strike whose value
    is known, by the heatmap cell's own readers (net_dex_dollars of a dollarized book;
    strike_total_oi). Open interest keeps every digit; the screen rounds the count. A strike
    whose value is unknown has no row."""
    from math_exposure_core import bucket_metric, exposures_have_dollar_gex, strike_total_oi
    from numeric_contract import float_finite_or_none

    dex: list[list] = []
    oi: list[list] = []
    dollarized = bool(exposures) and exposures_have_dollar_gex(exposures)
    for k, b in (exposures or {}).items():
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
    """`{all, near, far}` GEX rows -- the ALL / <=7DTE / MONTHLY+ chips -- from the chain's
    exposure_books and their merged full book `exposures` (one pricing pass), and the full
    book's DEX and OI rows (`dex`, `oi`: _per_strike_measure_rows). A contract whose
    days-to-expiry cannot be read belongs to `all` only: a maturity split it cannot answer is
    not answered for it."""
    from math_exposure_core import merge_exposure_books

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
    """Whether this wall is in the configuration its support/resistance label claims, by
    level_side: WALL_CONTAINS = a call wall above the price / a put wall below it, the only
    geometry in which dealer-hedging containment language is true; WALL_BREACHED = the price at or
    through the wall (a wall at the price contains nothing). None when the wall or the price is
    unknown."""
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
    """Every relation of `price` to the published levels (`terrain`, a snapshot's to_dict): each
    wall's state and lean, the price's side of the flip, the pin candidate and the read's lines.
    The levels are the publication's; the price is the one given, the live price on every route.
    A level's distance from the price is served with the level (/api/levels)."""
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
    """(call, put) wall labels as the chart states them at `price`: one strike holding both walls
    is TWO-SIDED (a magnet, not a barrier); a breached wall says where the price is (above, at or
    below it); a containing wall earns the dealer lean (resistance: dealers sell, support: dealers
    buy) only on a TRUSTED flip with a regime; otherwise None."""
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
    """Publish `pin_candidate` ONLY after regime, proximity,
    DTE, liquidity and completeness qualification.

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
    from math_probabilities import compute_pin_score

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


#: The levels a same-day clock can move, in the order the levels list shows them.
SAME_DAY_LEVELS = (
    ("call_wall", "Call wall"),
    ("put_wall", "Put wall"),
    ("gamma_flip", "Gamma flip"),
    ("absolute_gamma_strike", "Abs Γ"),
    ("net_gex_peak", "Net Γ peak"),
    ("gsf", "GSF"),
    ("grc", "GRC"),
    ("hvp", "HVP"),
    ("lvp", "LVP"),
    ("key_delta_strike", "Key Δ strike"),
    ("call_charm_wall", "Call charm wall"),
    ("put_charm_wall", "Put charm wall"),
)


def _listed_expiry_day(ct: dict) -> str | None:
    """Schwab's expirationDate, the calendar day, or None when it was not sent as text."""
    raw = ct.get("expirationDate")
    if not isinstance(raw, str) or len(raw) < 10:
        return None
    return raw[:10]


def same_day_levels(
    ticker: str,
    contracts: list[dict] | None,
    spot: float | None,
    *,
    now: datetime,
    held_charm: dict | None = None,
) -> dict[str, float | None]:
    """Nearest listed expiry, its open interest and implied volatility kept, gamma and
    delta rebuilt to today's option close for this ticker. Every ticker, one function.
    Absent when that close is not held or has passed, or the chain has no expiry left.
    Charm walls of a front expiry that settles today are that expiry's map. A later front
    expiry is repriced to today's close, one call."""
    blank = {name: None for name, _label in SAME_DAY_LEVELS}
    if not contracts or spot is None or spot <= 0:
        return blank
    today = now.astimezone(ET).date().isoformat()
    t_close = time_to_expiry_years(today, now, product=option_close_product(ticker))
    if t_close is None:
        return blank
    front = None
    for ct in contracts:
        if not isinstance(ct, dict):
            continue
        exp = _listed_expiry_day(ct)
        if exp is None or exp < today:
            continue
        if front is None or exp < front:
            front = exp
    if front is None:
        return blank
    parsed: list = []
    priced: list[dict] = []
    repriced: list[dict] = []
    built: list[tuple[dict, tuple | None, float | None]] = []
    blocked: set[float] = set()
    for ct in contracts:
        if not isinstance(ct, dict) or _listed_expiry_day(ct) != front:
            continue
        copied = dict(ct)
        # gamma and delta below are ours, not Schwab's: nothing of Schwab's times them
        copied.pop("greeksTime", None)
        strike = schwab_number(ct.get("strikePrice"))
        row = _contract_inputs(ct, now, t_years=t_close)
        gamma = delta = None
        if isinstance(row, tuple):
            _strike, _oi, _mult, t_years, sigma, sign = row
            gamma = bs_gamma(float(spot), _strike, t_years, sigma)
            delta = bs_delta(float(spot), _strike, t_years, sigma, call=sign > 0)
        if gamma is None or delta is None:
            copied["gamma"] = None
            copied["delta"] = None
            oi = schwab_count(ct.get("openInterest"))
            if strike is not None and oi is not None and oi > 0:
                blocked.add(float(strike))
            built.append((copied, None, strike))
            continue
        copied["gamma"] = gamma
        copied["delta"] = delta
        built.append((copied, row, strike))
    for copied, row, strike in built:
        if strike is not None and float(strike) in blocked:
            # One contract at this strike has open interest and no rebuilt greek.
            # No sibling names the strike either: not a wall, and not a charm wall.
            copied["gamma"] = None
            copied["delta"] = None
            repriced.append(copied)
            continue
        repriced.append(copied)
        if row is not None:
            parsed.append(row)
            priced.append(copied)
    if not repriced:
        return blank
    books = exposure_books(repriced, spot=spot, now=now)
    exposures, _diag = merge_exposure_books(books.values())
    (call_wall, _), (put_wall, _) = pick_gamma_wall_strikes(exposures)
    pin, _strength = pick_pin_and_strength(exposures)
    hvp, lvp = pick_volatility_point_strikes(exposures)
    if priced:
        profile = compute_gamma_profile(priced, float(spot), now=now, parsed=parsed)
        flip, _confidence, _flip_diag = compute_gamma_flip_v2(priced, float(spot), profile=profile)
        support = compute_gamma_support_levels(profile, float(spot))
        part = None
        if front == today and isinstance(held_charm, dict):
            found = held_charm.get(front)
            if isinstance(found, dict):
                part = found
        if isinstance(part, dict):
            eligible = {
                strike_key: bucket
                for strike_key, bucket in part.items()
                if strike_key not in blocked
            }
            call_charm, put_charm = pick_charm_wall_strikes(eligible)
        else:
            charm = compute_charm_by_strike(priced, float(spot), now=now, parsed=parsed)
            call_charm, put_charm = pick_charm_wall_strikes(charm)
    else:
        flip = None
        support = {"gsf": None, "grc": None}
        call_charm = put_charm = None
    return {
        "call_wall": call_wall,
        "put_wall": put_wall,
        "gamma_flip": flip,
        "absolute_gamma_strike": pin,
        "net_gex_peak": pick_net_gex_peak_strike(exposures),
        "gsf": support["gsf"],
        "grc": support["grc"],
        "hvp": hvp,
        "lvp": lvp,
        "key_delta_strike": pick_key_delta_strike(exposures),
        "call_charm_wall": call_charm,
        "put_charm_wall": put_charm,
    }


def compute_terrain(
    ticker: str, contracts: list[dict] | None, spot: float | None, *, now: datetime
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
    if not ticker:
        return _unavailable(ticker or "", spot, "no ticker")
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
    from math_exposure_core import book_total_oi, strike_total_oi

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
    parsed, unpriced = contract_inputs(
        contracts, _terrain_now, product=product
    )  # one parse for profile + charm
    profile = compute_gamma_profile(contracts, spot, now=_terrain_now, parsed=parsed)
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
    # the 0DTE book from the SAME producer with the dte filter — same parser,
    # same sign model; the share is pure attribution, zero new math.
    # a contract with no readable DTE belongs to no expiry's book
    _exp_0dte, _ = merge_exposure_books(
        b for (_e, d), b in books.items() if d is not None and d <= 0
    )
    _zero_dte_share = compute_zero_dte_gamma_share(exposures, _exp_0dte)
    # Max pain on the FRONT expiry only.
    _front_max_pain = None
    if _front_dte is not None:
        _exp_front, _ = merge_exposure_books(
            b for (_e, d), b in books.items() if d is not None and d <= _front_dte
        )
        _front_max_pain = compute_max_pain(_exp_front)
    # 25Δ risk reversal from the same wide chain (the expiry nearest 30 days out, tolerance-gated).
    from math_volatility import compute_25d_risk_reversal

    _rr25 = compute_25d_risk_reversal(contracts)
    from confluence_composite import iv_by_strike

    charm_by_expiry = {}
    iv_by_expiry = {}
    expiry_rows: dict[str, list] = {}
    for ct in contracts:
        if not isinstance(ct, dict):
            continue
        exp = _listed_expiry_day(ct)
        if exp is None:
            continue
        expiry_rows.setdefault(exp, []).append(ct)
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
        net_gex_peak=pick_net_gex_peak_strike(exposures),
        key_delta_strike=pick_key_delta_strike(exposures),
        hvp=hvp,
        lvp=lvp,
        net_gex_at_spot=flip_diag.get("gamma_at_spot"),
        gsf=_gsl["gsf"],
        grc=_gsl["grc"],
        gsf_state=_gsl["state"],
        zero_dte_gamma_share_pct=_zero_dte_share,
        same_day=same_day_levels(
            ticker, contracts, spot, now=_terrain_now, held_charm=charm_by_expiry
        ),
        rr_25d=_rr25,
        vanna_agg=compute_net_vanna(exposures, spot),  # same book, one sum
        implied_1d_move=compute_implied_one_day_move(contracts, spot),
        call_wall_range=compute_wall_value_area(exposures, call_wall, "call"),
        put_wall_range=compute_wall_value_area(exposures, put_wall, "put"),
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
        flip_diag=dict(flip_diag or {}),
        profile=profile,
        # the LIVE per-strike map, computed from THIS chain; session volume is carried alongside.
        per_strike=per_strike_view(books, exposures),
        books=books,
        charm_by_strike=charm_by_strike,
        charm_by_expiry=charm_by_expiry,
        iv_by_expiry=iv_by_expiry,
        pcr_by_expiry={
            e: put_call_oi_ratio(book)
            for (e, _d), (book, _diag) in sorted(books.items(), key=lambda kv: kv[0][0])
        },
        atm_iv_pct_by_expiry={
            e: None if s is None else s * 100.0
            for (e, _d), s in atm_sigma_by_expiry(contracts, spot).items()
            if e
        },
        pcr_volume_by_expiry={
            e: put_call_volume_ratio(book) for (e, _d), (book, _diag) in books.items()
        },
        pcr_all=put_call_oi_ratio(exposures),
        pcr_volume_all=put_call_volume_ratio(exposures),
        expiries=sorted({e for (e, _d) in books}),
        expiry_dte={e: d for (e, d) in books},
    )
