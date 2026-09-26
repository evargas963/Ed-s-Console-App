"""Terrain pipeline — levels only, no model stack.

WHY THIS EXISTS (5-whys root cause, 2026-07-19):
  1. 24 of 31 tickers refreshed only every ~11 minutes.
  2. They were being SKIPPED, not computed slowly — `_live_operator_mode_active()`
     hard-skips non-SPY/QQQ/IWM background rotation whenever a viewer is connected.
  3. That gate exists because background collection competed with the live UI.
  4. It competed because `_fetch_state` is ONE pipeline — chain + greeks + the full ML
     stack (xgb/lstm/transformer x 4 horizons, fusion, decision bundle) — shared by the
     UI request path and the background logger, capped at 2 global chain slots.
  5. ROOT: the model stack made the data path so expensive that the only way to keep the
     UI responsive was to starve most of the board.

Terrain needs none of that. Measured: the entire levels computation is ~4.8 ms per
ticker (~0.15 s for all 31), and one chain call per ticker per minute is ~31 req/min
against a ~120 req/min Schwab budget. So terrain gets its OWN path: same app, same
process, same chain data — separate pipeline, no inference, no starvation.

This module is pure: it takes contracts + spot and returns a payload. Fetching and
scheduling live in the caller, so this stays trivially testable.
"""

from __future__ import annotations

import time as _time
from dataclasses import asdict, dataclass, field, replace
from typing import Any

from math_exposure_core import (
    compute_net_dex_dollars,
    compute_net_vanna,
    compute_zero_dte_gamma_share,
    exposure_books,
    exposures_have_dollar_gex,
    merge_exposure_books,
    put_call_oi_ratio,
    pick_delta_wall_strikes,
    pick_net_gex_peak_strike,
    pick_pin_and_strength,
    pick_gamma_wall_strikes,
    pick_key_delta_strike,
    pick_volatility_point_strikes,
    total_gex_dollars_at_strike,
)
from math_levels import compute_charm_by_strike, contract_inputs, compute_gamma_flip_v2, compute_gamma_profile, compute_gamma_support_levels, compute_max_pain, pick_charm_wall_strikes
from math_exposure_core import key_level_strikes_with_gamma
from terrain_read import build_terrain_read

#: Payload schema version — bump on any field change so the UI can fail closed.
#: v2 (2026-07-21): + net_gex_at_spot, key_delta_strike, hvp, lvp.
#: v3 (2026-08-24, RC-292): gamma_pin* renamed absolute_gamma_* (total-gamma concentration
#: under its metric's name, not a pin claim); + pin_candidate / pin_candidate_blockers
#: (the qualified pin claim, fail-closed with reasons).
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
    lines: list[str] = field(default_factory=list)

    # levels — chain scope for every level in this dataclass: FULL_BOOK (the wide
    # multi-expiry capture chain). The analytics summary_rows carry the SELECTED_EXPIRY
    # scope; the two scopes never share a payload field (RC-292/RC-303).
    gamma_flip: float | None = None
    call_wall: float | None = None
    put_wall: float | None = None
    #: RC-124/RC-292/RC-315: max TOTAL gamma — |call GEX$| + |put GEX$| — over the full
    #: book. A GROSS GAMMA CONCENTRATION (SpotGamma's "Absolute Gamma" measure): where the
    #: most dealer re-hedging activity sits. It is a pin CANDIDATE input, NOT a demonstrated
    #: magnet — magnitude sets the SIZE of the hedging flow while the unobservable dealer
    #: SIGN decides pin vs repel (RC-315). Renamed from `gamma_pin` per the operator's
    #: RC-292 disposition: the raw value carries the metric's name; the word "pin" is
    #: reserved for `pin_candidate` below, which must earn it. Strength = leader's margin
    #: over the runner-up on the same metric (a 1% lead is a coin flip; the label says so).
    absolute_gamma_strike: float | None = None
    absolute_gamma_strength_pct: float | None = None
    #: RC-413: GEX$ / OI at absolute_gamma_strike plus book OI, from the SAME exposures
    #: book that picked the strike. pin_score reads these so strike and magnitude cannot
    #: split onto the analytics selected-expiry book. None = fail-closed
    #: (absent/stale/undollarized).
    absolute_gamma_gex_dollars: float | None = None
    absolute_gamma_oi: float | None = None
    book_oi_total: float | None = None
    #: RC-292 operator disposition: `pin_candidate` is absolute_gamma_strike published as a
    #: candidate pin ONLY after regime, proximity, DTE, liquidity and completeness
    #: qualification (qualify_pin_candidate below). None = one or more gates failed;
    #: pin_candidate_blockers records WHICH, so absence renders with its reason, never as
    #: an unexplained dash (RC-128 pattern).
    pin_candidate: float | None = None
    pin_candidate_blockers: list[str] = field(default_factory=list)
    #: RC-124: the former "pin" — max |net GEX$| (calls minus puts) — kept under its honest
    #: name; a real measure of where the SIGNED book peaks, distinct from the concentration.
    #: Scope: FULL_BOOK here; ExposureRow.net_gex_peak is the SAME definition over the
    #: SELECTED_EXPIRY chain (declared, distinct surface — RC-303).
    net_gex_peak: float | None = None
    #: RC-134: terrain `hvl` REMOVED — it equaled the absolute-gamma strike by construction
    #: (same total-GEX$ metric as pick_hvl_strike / pick_pin_and_strength). Total-gamma
    #: renders once as ABS GAMMA. Analytics `kl_hvl` remains a DIFFERENT book
    #: (net_gex_peak → "Net Γ peak").
    #: Max pain is defined PER EXPIRY (standard: the settlement price minimising intrinsic
    #: payout on ONE expiry's open interest). It used to be computed over the whole wide
    #: chain -- every expiry pooled (research check, 2026-09-24). Now: the FRONT expiry only,
    #: and max_pain_dte says which.
    max_pain: float | None = None
    max_pain_dte: float | None = None
    call_charm_wall: float | None = None
    put_charm_wall: float | None = None
    key_delta_strike: float | None = None
    hvp: float | None = None   # most NEGATIVE net GEX$ strike (amplification pocket)
    lvp: float | None = None   # most POSITIVE net GEX$ strike (damping pocket)

    #: Signed net dealer GEX$ per 1% move AT SPOT — the regime's own number
    #: (regime = its sign). Disambiguates walls that share a strike.
    net_gex_at_spot: float | None = None

    #: RC-354: Gamma Support Floor / Gamma Resistance Ceiling — computed from the SAME
    #: materialized profile as the flip (RC-345 one-profile rule). GSF = highest level
    #: below spot where the positive-gamma cushion has decayed to half its at-spot value
    #: (support ends BEFORE the flip's zero-crossing); GRC = the upside mirror, often
    #: at/beyond the call wall (resistance strengthens before it exhausts). gsf_state is
    #: the fail-closed verdict: OK | BELOW_SUPPORT (negative regime — no fabricated
    #: price) | UNAVAILABLE.
    gsf: float | None = None
    grc: float | None = None
    gsf_state: str = "UNAVAILABLE"

    #: RC-357: % of |net GEX$| from SAME-DAY expiry — level persistence. High = today's
    #: walls/flip decay into the close (0DTE gamma dies at 4pm); low = levels persist.
    #: None (fail-closed) when the book is empty, never a fabricated 0%.
    zero_dte_gamma_share_pct: float | None = None

    #: RC-358: 25Δ risk reversal — {rr_pts, call_iv_25d, put_iv_25d, dte} or None.
    #: Skew steepness on the front expiry; deterioration toward −6 = the put bid
    #: building (the same-session GSF-breach confirm). Fail-closed None, never fabricated.
    rr_25d: dict | None = None

    #: RC-359: per-strike OI from the SAME exposures book — {strike: (call_oi, put_oi)}.
    #: HEAVY: popped from to_dict like per_strike; the server banks it daily at refresh
    #: time and computes the ΔOI walls vs the prior banked session.
    oi_by_strike: dict | None = None

    #: RC-361: aggregate dealer DEX $ — {net_dex, call_dex, put_dex} or None. The
    #: directional hedge-inventory complement to GEX-per-1%. Fail-closed None.
    dex_dollars: dict | None = None

    #: RC-362: aggregate dealer vanna — {net_vanna_dollars_per_volpt, net_vanna_shares_per_volpt}
    #: or None. Sizes the IV-driven hedge flow (vol-crush tailwind / vol-spike selling).
    vanna_agg: dict | None = None

    #: RC-113: the institutional sigma band — {points, iv_pct_atm, dte_used, method} or None
    #: when ATM IV is unusable (fail-closed, never a fabricated band). `points` is the
    #: one-sigma half-width; the client centers it on the live spot. The wall RANGE itself
    #: is the put_wall↔call_wall corridor — already carried above, drawn client-side.
    implied_1d_move: dict[str, Any] | None = None

    #: RC-115: each wall's EARNED per-side range — {lo, hi, coverage_pct, method} or None —
    #: the value-area of the wall's own side-gamma mass (never the strike grid).
    call_wall_range: dict[str, Any] | None = None
    put_wall_range: dict[str, Any] | None = None

    #: RC-128 (One Levels Faucet): delta walls owned by THIS producer — same wide chain,
    #: one book. Concepts terrain does not compute (OI/vanna walls, inflections) do not
    #: get fields here and render BLANK with a withheld reason, never an analytics book.
    call_delta_wall: float | None = None
    put_delta_wall: float | None = None

    #: RC-130: the wall's GEOMETRY state — "contains" (call wall above spot / put wall below
    #: spot, the configuration in which support/resistance language is true) or "breached"
    #: (spot at or through the wall). Institutional basis (researched 2026-07-29): the picker
    #: is deliberately NOT side-constrained — SpotGamma's wall stays at the concentration max
    #: and their own SPX stats track breach frequency and closes beyond it; what changes on a
    #: breach is the LABEL/state, not the strike. None = wall or spot missing (absence, never
    #: a guessed state). Recomputed by the server at every spot reprice via wall_geometry_state.
    call_wall_state: str | None = None
    put_wall_state: str | None = None

    # provenance — never render a level without knowing where it came from
    contracts_used: int = 0
    strikes_used: int = 0
    dollarized: bool = False
    flip_diag: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    #: (price, net dealer gamma) samples. Kept OUT of to_dict(): it is ~240 pairs, far too
    #: heavy for every poll, but it is what lets a cached payload be re-priced against a
    #: fresh spot without refetching the chain (RC-28). The levels are slow-moving; spot
    #: is not; the regime is the sign of this curve AT spot.
    profile: list[tuple[float, float]] = field(default_factory=list, repr=False)

    #: RC-68 — the LIVE per-strike map, kept instead of discarded. compute_exposures_by_strike
    #: already runs on every ~60s terrain refresh and its result was used to pick the walls and
    #: then thrown away, which forced /api/terrain/strikes to render the per-strike histogram from
    #: the FROZEN option_chain_morning_full archive (MEASURED 2026-07-27: 09:47 capture served at
    #: 11:31, session volume understated 281 percent). Retaining it makes that panel live at ZERO
    #: additional vendor cost — the chain is already in hand. Kept OUT of to_dict() for the same
    #: reason as `profile`: too heavy for every poll; the strikes endpoint reads it directly.
    per_strike: dict[float, dict[str, Any]] = field(default_factory=dict, repr=False)
    #: The exposure_books every number above was priced from ({(expiry, dte): (book, diag)}):
    #: the gamma-surface grid is shaped from them, so levels, per-strike rows and heatmap
    #: cells come from one pricing pass.
    books: dict = field(default_factory=dict, repr=False)
    #: {strike: charm bucket} from compute_charm_by_strike -- the charm walls above and the
    #: charm-by-strike panel read the same map.
    charm_by_strike: dict = field(default_factory=dict, repr=False)
    #: {expiry: put OI / call OI} for each listed expiry
    pcr_by_expiry: dict = field(default_factory=dict)
    #: Wall-clock the chain behind per_strike was fetched — every consumer must be able to render
    #: an age on its face rather than implying "now".
    computed_ts_utc: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """The per-poll payload: every field except the heavy maps (profile, per_strike,
        oi_by_strike, books, charm_by_strike), which the server reads off the snapshot."""
        light = replace(self, **{n: None for n in _HEAVY_FIELDS})
        return {k: v for k, v in asdict(light).items() if k not in _HEAVY_FIELDS}


_HEAVY_FIELDS = ("profile", "per_strike", "oi_by_strike", "books", "charm_by_strike")


def _unavailable(ticker: str, spot: float | None, reason: str) -> TerrainSnapshot:
    # Pass ticker even on the unavailable path so SIGN-DEMOTION's fail-closed
    # contract stays visible at every call site (AST-audited 2026-07-22).
    read = build_terrain_read(spot=spot, flip=None, flip_confidence="UNAVAILABLE",
                              ticker=ticker)
    return TerrainSnapshot(
        ticker=ticker, spot=spot, regime=read.regime, posture=read.posture,
        confidence=read.confidence, headline=read.headline, lines=read.lines,
        error=reason,
    )


def _per_strike_rows(exposures: dict, contracts: list[dict]) -> list[list]:
    """`[[strike, net_gex_1pct$, session_volume], …]` — the EXACT shape the panel renders.

    THE one producer of GEX-by-strike rows (live panel AND the prior-day ghost -- server.py
    carried a second copy, removed 2026-09-24).

    RC-79: the finished numbers are handed over as-is, never reassembled into synthetic
    contracts and recomputed.

    Audit T-01 / T-02 (2026-09-24, operator rule: no fallbacks):
      * the bar is net GEX$ from a DOLLARIZED book on a strike whose gamma was VALID. It used
        to fall back to total_gamma_raw_at_strike -- UNSIGNED raw gamma drawn on the signed
        GEX$ axis. A strike with no valid gamma, or a book built without spot, has no bar.
      * volume is the summed totalVolume of the strike's contracts that REPORTED one (0 is a
        real zero); a strike where no contract reported volume is None ("—"), not 0.
    """
    from math_exposure_core import exposures_have_dollar_gex, net_gex_dollars_at_strike
    from numeric_contract import float_finite_or_none, float_nonnegative_or_none

    if not exposures or not exposures_have_dollar_gex(exposures):
        return []
    vol_by_k: dict[float, float] = {}
    for ct in contracts or []:
        if not isinstance(ct, dict):
            continue
        sk = float_finite_or_none(ct.get("strikePrice"))
        v = float_nonnegative_or_none(ct.get("totalVolume"))
        if sk is not None and v is not None:
            vol_by_k[sk] = vol_by_k.get(sk, 0.0) + v

    vol_int = {k: int(v) for k, v in vol_by_k.items()}   # absent key = no volume reported
    rows: list[list] = []
    for k, b in exposures.items():
        sk = float_finite_or_none(k)
        if sk is None:                      # a NaN strike must never become a rendered bar
            continue
        # has_oi: the strike's contracts cleared the OI gate (a no-OI strike drew a $0 bar,
        # reproduced live on SPX 2026-09-14); has_valid_gamma: its 0.0 net GEX is not the
        # bucket initialiser.
        if not (isinstance(b, dict) and b.get("has_oi") and b.get("has_valid_gamma")):
            continue
        gf = float_finite_or_none(net_gex_dollars_at_strike(b))
        if gf is None:
            continue
        rows.append([round(sk, 2), round(gf, 1), vol_int.get(sk)])
    rows.sort(key=lambda r: r[0])
    return rows


def _dte_of(ct: object) -> float | None:
    """Days to expiration, or None when the contract does not say.

    RC-290: this returned 999.0 for an unreadable DTE and I annotated it "SORT KEY only,
    never rendered". Cursor executed the claim: the per-strike maturity split classifies contracts
    with `_dte_of(c) > 7` as `far`, so 999.0 put every unknown-maturity contract into the
    FAR scope and rendered it there. The reason was false and the fabricated number was
    reaching the operator as a maturity claim.

    None cannot be compared to 7 by accident — a caller must decide what unknown means,
    which for a maturity SPLIT is "belongs to neither side".
    """
    from numeric_contract import float_finite_or_none
    return float_finite_or_none(ct.get("daysToExpiration")) if isinstance(ct, dict) else None


def compute_wall_value_area(
    exposures: dict, wall: float | None, side: str, frac: float = 0.682
) -> dict | None:
    """RC-115: the wall's EARNED range — Market-Profile value-area math on SIDE gamma mass.

    THE STANDARD, named: the Value Area algorithm (CQG-documented, the Market/Volume Profile
    industry method) — start at the point of control and expand one strike at a time toward
    whichever neighbor holds more mass, until 68.2 percent (one sigma) is enclosed. Here the
    distribution is the wall's own SIDE gamma (call gamma for the call wall, put gamma for
    the put wall), so the range is a property of the POSITIONING — different every day and
    every ticker — never of the strike grid (the RC-86 falsehood this replaces).

    Fail-closed: no wall, wall absent from the mass, or degenerate mass -> None.
    """
    from math_exposure_core import bucket_metric_abs, exposures_have_dollar_gex

    # SIDE GEX$ mass on a dollarized book, valid-gamma strikes only. It used to switch to RAW
    # side gamma when the book had no spot -- still labelled "GEX mass" (audit T-05).
    if wall is None or not exposures or not exposures_have_dollar_gex(exposures):
        return None
    key = f"{side}_gex_1pct"
    mass: dict[float, float] = {}
    for k, b in exposures.items():
        if not (isinstance(b, dict) and b.get("has_valid_gamma")):
            continue
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
        "coverage_pct": round(s / total * 100.0, 1),
        "method": "gamma value area: Market-Profile POC expansion on "
                  f"{side}-side GEX mass to 68.2pct (one sigma)",
    }


def compute_implied_one_day_move(contracts: list[dict], spot: float | None) -> dict | None:
    """The institutional sigma band (RC-113): EM_1d = S x sigma_ATM x sqrt(1/252).

    THE STANDARD, named: SpotGamma — whose levels product ships on Bloomberg — treats the
    wall as a single strike, the RANGE as the put-wall-to-call-wall corridor, and overlays
    the Implied 1-Day Move: a one-standard-deviation band (68.3 percent confidence). The
    textbook EM uses front-expiry ATM implied volatility, annualized, scaled by
    sqrt(1/252) for one trading day.

    IV source: the nearest-expiry call+put pair closest to spot. Schwab `volatility` is
    PERCENT, not a fraction (unproven-register row 50, PROVEN on 1,600 sampled contracts)
    — divided by 100 here. Fails closed: no usable ATM IV means None, never a fabricated
    band (a made-up sigma is worse than no sigma).

    Returns {points, iv_pct_atm, dte_used, method} — `points` is the one-sigma HALF-width
    in price points; the client centers it on the LIVE spot so the band can never disagree
    with the price beside it (the RC-28/RC-77 one-spot discipline).
    """
    from numeric_contract import float_finite_or_none

    if spot is None or spot <= 0 or not contracts:
        return None
    # RC-290: nearest expiry present in the chain. `_dte_of` now returns None for a contract
    # that does not state its DTE instead of a 999.0 stand-in, so those are dropped BEFORE
    # the min rather than being carried through it and screened out afterwards by a
    # magic-number comparison — which also means an all-unreadable chain yields None here
    # (no front expiry) rather than a confident 999.
    _dtes = [d for d in (_dte_of(c) for c in contracts if isinstance(c, dict))
             if d is not None]
    front = min(_dtes, default=None)
    if front is None:
        return None
    ivs: dict[str, tuple[float, float]] = {}   # side -> (|strike-spot|, iv_frac)
    for c in contracts:
        if not isinstance(c, dict) or _dte_of(c) != front:
            continue
        strike = float_finite_or_none(c.get("strikePrice"))
        iv_pct = float_finite_or_none(c.get("volatility"))
        side = str(c.get("putCall") or "").upper()
        if strike is None or iv_pct is None or iv_pct <= 0 or side not in ("CALL", "PUT"):
            continue
        # Cursor-audit A3: single IV-conversion authority (was an unguarded inline /100 that would
        # mis-scale on a silent Schwab units flip, unlike the guarded charm/levels/vanna paths).
        from math_exposure_core import schwab_iv_to_sigma
        _sig = schwab_iv_to_sigma(iv_pct)
        if _sig is None:
            continue
        d = abs(strike - float(spot))
        if side not in ivs or d < ivs[side][0]:
            ivs[side] = (d, _sig)
    # Both legs or no implied move: one side's IV used to stand in for the call/put mean
    # (audit T-06, 2026-09-24: no fallbacks).
    if set(ivs) != {"CALL", "PUT"}:
        return None
    sigma = (ivs["CALL"][1] + ivs["PUT"][1]) / 2.0   # ATM call/put mean (straddle IV)
    em = float(spot) * sigma * (1.0 / 252.0) ** 0.5
    return {
        "points": round(em, 4),
        "iv_pct_atm": round(sigma * 100.0, 4),
        "dte_used": front,
        "method": "S x sigma_ATM x sqrt(1/252), one standard deviation (68.3pct); "
                  "sigma = mean of nearest-expiry ATM call/put implied vol",
    }


def per_strike_view(books: dict, exposures: dict, contracts: list[dict]) -> dict:
    """`{all, near, far}` rows -- the ALL / <=7DTE / MONTHLY+ chips -- from the chain's
    exposure_books and their merged full book `exposures` (one pricing pass). A contract whose
    days-to-expiry cannot be read belongs to `all` only: a maturity split it cannot answer is
    not answered for it (RC-290)."""
    from math_exposure_core import merge_exposure_books

    def rows(keep) -> list:
        chosen = [b for (_exp, d), b in books.items() if keep(d)]
        if not chosen:
            return []
        subset_exposures, _diag = merge_exposure_books(chosen)
        subset = [c for c in contracts if isinstance(c, dict) and keep(_dte_of(c))]
        return _per_strike_rows(subset_exposures, subset)

    return {"all": _per_strike_rows(exposures, contracts),
            "near": rows(lambda d: d is not None and d <= 7),
            "far": rows(lambda d: d is not None and d > 7)}






def wall_geometry_state(spot: float | None, wall: float | None,
                        side: str) -> str | None:
    """RC-130: is this wall in the configuration its support/resistance label claims?

    "contains" = call wall strictly above spot / put wall strictly below spot — the only
    geometry in which dealer-hedging containment language is true. "breached" = spot at or
    through the wall — institutionally a DISTINCT state (SpotGamma reports closes beyond the
    wall and tracks them separately; the strike does not move). Equality counts as breached:
    a wall at spot is not containing anything. None = absent input, absence stays absence.

    ONE definition, called by both compute_terrain and the server's spot-reprice path, so the
    state can never disagree with the spot painted beside it.
    """
    if spot is None or wall is None:
        return None
    if side == "call":
        return "contains" if float(wall) > float(spot) else "breached"
    if side == "put":
        return "contains" if float(wall) < float(spot) else "breached"
    raise ValueError(f"side must be 'call' or 'put', got {side!r}")


#: RC-292 pin-candidate qualification thresholds. Hardwired, not configurable. Each cites
#: its source; neither is a new invention:
#: — proximity: strike within 0.5% of spot — the "strike near spot" cut of the operator's
#:   pinning framework as committed in tools/study_pin_residence_v1.py (`near`, 0.005).
PIN_CANDIDATE_PROXIMITY_MAX_FRAC = 0.005
#: — DTE: pinning is an expiration effect (expiration-date clustering turns on positioning
#:   into expiry — Ni, Pearson & Poteshman, JFE 2005, doi:10.1016/j.jfineco.2004.08.005);
#:   the framework's committed cut is dte <= 1 (tools/study_pin_residence_v1.py `exp`).
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
    """RC-292 operator disposition: publish `pin_candidate` ONLY after regime, proximity,
    DTE, liquidity and completeness qualification.

    The raw absolute-gamma strike is a gross gamma concentration — a pin CANDIDATE input,
    never a demonstrated magnet (RC-315: magnitude sizes the hedging flow; the unobservable
    dealer sign decides pin vs repel). This gate is the difference between the metric and
    the claim. Gates, each fail-closed (missing input = gate failed, never assumed passed):

    — completeness: the RC-413 magnitude bundle (strike, strength, GEX$, OI, book OI) is
      present from the SAME book that picked the strike.
    — regime: dealers net LONG gamma at spot (net_gex_at_spot > 0). A long-gamma dealer
      sells rallies and buys dips, which pins; short gamma repels (RC-315). The framework
      cut committed in tools/study_pin_residence_v1.py (`lng`).
    — proximity: |strike − spot| / spot <= PIN_CANDIDATE_PROXIMITY_MAX_FRAC.
    — DTE: front expiry of THIS book within PIN_CANDIDATE_DTE_MAX days (pinning is an
      expiration effect); unknown maturity fails, never passes (RC-290).
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
        if abs(float(absolute_gamma_strike) - float(spot)) / float(spot) > \
                PIN_CANDIDATE_PROXIMITY_MAX_FRAC:
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


def compute_terrain(ticker: str, contracts: list[dict] | None,
                    spot: float | None, *, now=None) -> TerrainSnapshot:
    """Full terrain for one ticker. Fails closed — never invents a level.

    `now` (gamma audit 2026-08-26): the valuation instant for every time-to-expiry in this
    snapshot. Live callers omit it and get now_et(). OFFLINE/REPLAY callers MUST pass the
    SNAPSHOT's time — repricing a stored historical chain against today's clock silently drops
    every contract whose expiry has since passed (time_to_expiry_years returns None past
    settlement) and understates T for the rest, so the replay does not reproduce what the live
    reprice saw. _contract_inputs already documented this contract; compute_terrain had no hook
    to honor it, which is why tools/terrain_backtest_report_v1.py was scoring on the wrong clock.

    SINGLE SOURCE OF TRUTH (RC-33, 2026-07-24): this is the ONE terrain engine;
    /api/analytics/state no longer computes a competing terrain read. It must be
    fed the wide-capture multi-expiry chain — the operator-locked full-chain
    basis (dealers hedge the whole delta book across weekly/monthly expiries, not
    just the 0DTE slice). The narrow-chain confidence gate in compute_gamma_flip_v2
    is RETAINED as the fail-closed backstop: a genuinely narrow chain (e.g. wide
    capture unavailable) still yields STAND_ASIDE, never a trusted-looking verdict.
    """
    if not ticker:
        return _unavailable(ticker or "", spot, "no ticker")
    if not contracts:
        return _unavailable(ticker, spot, "no option chain")
    if spot is None or spot <= 0:
        return _unavailable(ticker, spot, "no spot price")

    # ONE valuation instant for every book below (gamma audit: replay pins the snapshot
    # instant). Resolved BEFORE the first exposure book -- it used to be read later, so the
    # exposures (and the vanna aggregate built from them) priced T at the wall clock while
    # the profile priced it at `now` (2026-09-25).
    from time_et import now_et as _now_et
    _terrain_now = now if now is not None else _now_et()
    # One pricing pass: exposures per (expiry, DTE) group; every book below is a merge of them.
    books = exposure_books(contracts, spot=spot, now=_terrain_now)
    exposures, diag = merge_exposure_books(books.values())
    _dtes = [d for (_e, d) in books if d is not None]
    _front_dte = min(_dtes, default=None)
    if not exposures:
        return _unavailable(ticker, spot, "chain produced no exposures")

    # key levels only on strikes with usable gamma -- no all-strikes fallback (T-03): with
    # none the pickers return None instead of ranking initialiser zeros.
    strikes = key_level_strikes_with_gamma(exposures)
    (call_wall, _cw_str), (put_wall, _pw_str) = pick_gamma_wall_strikes(exposures, strikes)
    hvp, lvp = pick_volatility_point_strikes(exposures, strikes)
    # RC-124/RC-292: max TOTAL gamma — the absolute-gamma concentration, full book.
    _abs_gamma_strike, _abs_gamma_strength = pick_pin_and_strength(exposures, strikes)
    # RC-413: pin_score GEX/OI from THIS same exposures book — never a second analytics book.
    # T-04 (2026-09-24): OI from the ONE reader -- unknown (a contract that never reported
    # OI) is None, never 0; the old loop added a missing leg as 0 and silently skipped
    # unparsable ones.
    from math_exposure_core import book_total_oi, strike_total_oi
    _book_oi_total = book_total_oi(exposures)
    _abs_gamma_gex_dollars = None
    _abs_gamma_oi = None
    _abs_gamma_bucket = (exposures.get(float(_abs_gamma_strike))
                         if _abs_gamma_strike is not None else None)
    if isinstance(_abs_gamma_bucket, dict):
        _abs_gamma_gex_dollars = total_gex_dollars_at_strike(_abs_gamma_bucket)
        _abs_gamma_oi = strike_total_oi(_abs_gamma_bucket)
    # RC-128 (One Levels Faucet): the SSOT producer owns the delta walls too — same wide
    # chain, same exposures, one book. OI/vanna walls stay unowned and therefore BLANK on
    # every operator surface until this producer computes them.
    (call_delta_wall, _cdw_str), (put_delta_wall, _pdw_str) = pick_delta_wall_strikes(
        exposures, strikes)
    # RC-345 / F03: the gamma profile is materialized ONCE, at one pinned instant, and shared
    # by both the flip verdict and the regime/gamma-at-spot read. Previously the flip built a
    # profile inside compute_gamma_flip_v2 and this function built a SECOND one, each defaulting
    # `now` to its own wall-clock read — two materializations of the same curve at two instants.
    parsed = contract_inputs(contracts, _terrain_now)       # one parse for profile + charm
    profile = compute_gamma_profile(contracts, spot, now=_terrain_now, parsed=parsed)
    flip, confidence, flip_diag = compute_gamma_flip_v2(
        contracts, spot, now=_terrain_now, profile=profile)
    # RC-354: GSF/GRC from the SAME materialized profile — no second materialization.
    # Snap-to-shelf deliberately deferred until strike-GEX history is banked (theta wants a
    # trailing-60-session percentile; a session-local stand-in would be a fake calibration).
    _gsl = compute_gamma_support_levels(profile, spot)
    # RC-357: the 0DTE book from the SAME producer with the dte filter — same parser,
    # same sign model; the share is pure attribution, zero new math.
    # a contract with no readable DTE is kept, as use_only_dte_max always kept it
    _exp_0dte, _ = merge_exposure_books(b for (_e, d), b in books.items() if d is None or d <= 0)
    _zero_dte_share = compute_zero_dte_gamma_share(exposures, _exp_0dte)
    # Max pain on the FRONT expiry only.
    _front_max_pain = None
    if _front_dte is not None:
        _exp_front, _ = merge_exposure_books(
            b for (_e, d), b in books.items() if d is None or d <= _front_dte)
        _front_max_pain = compute_max_pain(_exp_front)
    # RC-358: 25Δ risk reversal from the same wide chain (front expiry, tolerance-gated).
    from math_volatility import compute_25d_risk_reversal
    _rr25 = compute_25d_risk_reversal(contracts)
    charm_by_strike = compute_charm_by_strike(contracts, spot, now=_terrain_now, parsed=parsed)
    call_charm_wall, put_charm_wall = pick_charm_wall_strikes(charm_by_strike)

    # RC-292: _front_dte (the nearest readable DTE; RC-290: a contract that does not state
    # its maturity is dropped, never defaulted) feeds the DTE gate.
    _pin_candidate, _pin_candidate_blockers = qualify_pin_candidate(
        spot=float(spot),
        absolute_gamma_strike=_abs_gamma_strike,
        absolute_gamma_strength_pct=_abs_gamma_strength,
        absolute_gamma_gex_dollars=_abs_gamma_gex_dollars,
        absolute_gamma_oi=_abs_gamma_oi,
        book_oi_total=_book_oi_total,
        net_gex_at_spot=flip_diag.get("gamma_at_spot"),
        front_dte=_front_dte,
    )

    read = build_terrain_read(
        spot=spot, flip=flip, flip_confidence=confidence,
        put_wall=put_wall, call_wall=call_wall,
        gamma_at_spot=flip_diag.get("gamma_at_spot"),
        ticker=ticker,   # SIGN-DEMOTION: single names get regime withheld, levels stand
    )

    return TerrainSnapshot(
        ticker=ticker,
        spot=float(spot),
        regime=read.regime,
        posture=read.posture,
        confidence=read.confidence,
        headline=read.headline,
        lines=read.lines,
        gamma_flip=flip,
        call_wall=call_wall,
        put_wall=put_wall,
        # RC-124/RC-292: the max-TOTAL-gamma concentration under its metric's name with
        # its decisiveness; the old net-argmax lives on honestly as net_gex_peak. The pin
        # CLAIM is pin_candidate, and only qualification can publish it.
        absolute_gamma_strike=_abs_gamma_strike,
        absolute_gamma_strength_pct=_abs_gamma_strength,
        absolute_gamma_gex_dollars=_abs_gamma_gex_dollars,
        absolute_gamma_oi=_abs_gamma_oi,
        book_oi_total=_book_oi_total,
        pin_candidate=_pin_candidate,
        pin_candidate_blockers=_pin_candidate_blockers,
        net_gex_peak=pick_net_gex_peak_strike(exposures, strikes, institutional=True),
        key_delta_strike=pick_key_delta_strike(exposures, strikes),
        hvp=hvp,
        lvp=lvp,
        net_gex_at_spot=flip_diag.get("gamma_at_spot"),
        gsf=_gsl["gsf"],
        grc=_gsl["grc"],
        gsf_state=_gsl["state"],
        zero_dte_gamma_share_pct=_zero_dte_share,
        rr_25d=_rr25,
        # RC-359: per-strike OI exported from the SAME exposures book (no second parse)
        oi_by_strike={float(k): (b.get("call_oi"), b.get("put_oi"))
                      for k, b in exposures.items() if isinstance(b, dict)},
        dex_dollars=compute_net_dex_dollars(exposures),   # RC-361: same book, one sum
        vanna_agg=compute_net_vanna(exposures, spot),     # RC-362: same book, one sum
        implied_1d_move=compute_implied_one_day_move(contracts, spot),   # RC-113
        call_wall_range=compute_wall_value_area(exposures, call_wall, "call"),   # RC-115
        put_wall_range=compute_wall_value_area(exposures, put_wall, "put"),      # RC-115
        call_delta_wall=call_delta_wall,   # RC-128: one book for delta walls too
        put_delta_wall=put_delta_wall,
        # RC-130: the geometry state ships WITH the wall so no paint site can claim
        # support/resistance the spot contradicts (live SPY 2026-07-29: put wall 740
        # painted "dealer support" while spot sat at 735.13 below it).
        call_wall_state=wall_geometry_state(spot, call_wall, "call"),
        put_wall_state=wall_geometry_state(spot, put_wall, "put"),
        max_pain=_front_max_pain,
        max_pain_dte=_front_dte,
        call_charm_wall=call_charm_wall,
        put_charm_wall=put_charm_wall,
        # ExposureDiagnostics is a frozen dataclass; contracts_used is ALWAYS an int.
        # The old getattr(...,0) or 0 fabricated a neutral where absence is impossible —
        # a broken diag would silently report "0 contracts" instead of failing (CAPS).
        contracts_used=diag.contracts_used,
        strikes_used=len(exposures),
        dollarized=exposures_have_dollar_gex(exposures),
        flip_diag=dict(flip_diag or {}),
        profile=profile,
        # RC-68: keep the LIVE per-strike map instead of discarding it. `exposures` was just
        # computed from THIS chain; the per-strike histogram was previously rendered from the
        # frozen morning archive purely because nothing persisted this. Session volume is carried
        # alongside so the volume panel stops serving a 09:47 corpse at 11:31.
        per_strike=per_strike_view(books, exposures, contracts),
        books=books,
        charm_by_strike=charm_by_strike,
        pcr_by_expiry={e: put_call_oi_ratio(book) for (e, _d), (book, _diag) in books.items()},
        computed_ts_utc=_time.time(),
    )
