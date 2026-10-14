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
from datetime import datetime
from typing import Any

from math_exposure_core import (
    book_net_gex,
    compute_net_vanna,
    compute_zero_dte_gamma_share,
    exposure_books,
    exposures_have_dollar_gex,
    merge_exposure_books,
    put_call_oi_ratio,
    put_call_volume_ratio,
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
    """Everything pricing one chain produces, at the spot it was priced at (`spot`). What is read
    from the spot -- the read, each wall's state, lean and distance, the flip side, the pin's
    proximity and the implied-move band -- is at_spot's, at the live spot (operator 2026-10-14:
    "the live spot for every distance, side, breached and band")."""

    ticker: str
    spot: float | None
    schema_version: int = TERRAIN_SCHEMA_VERSION

    #: the flip's confidence tier (compute_gamma_flip_v2): the read's input
    flip_confidence: str = "UNAVAILABLE"

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
    #: reserved for `pin_candidate` (at_spot's), which must earn it. Strength = leader's margin
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
    #: payout on ONE expiry's open interest): {expiry: strike} for each listed expiry. The one
    #: shown is the front expiry's (expiry_states, at the instant it is served).
    max_pain_by_expiry: dict = field(default_factory=dict)
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
    #: absolute gamma (pick_pin_and_strength) of the same-day expiry's book alone, or None with why
    zero_dte_abs_gamma_strike: float | None = None
    zero_dte_abs_gamma_reason: str | None = None

    #: RC-358: 25Δ risk reversal — {rr_pts, call_iv_25d, put_iv_25d, dte} or None.
    #: Skew steepness on the front expiry; deterioration toward −6 = the put bid
    #: building (the same-session GSF-breach confirm). Fail-closed None, never fabricated.
    rr_25d: dict | None = None

    #: RC-362: aggregate dealer vanna — {net_vanna_dollars_per_volpt, net_vanna_shares_per_volpt}
    #: or None. Sizes the IV-driven hedge flow (vol-crush tailwind / vol-spike selling).
    vanna_agg: dict | None = None

    #: RC-113: the sigma of the institutional band -- {iv_pct_atm, dte_used, method} (the front
    #: expiry at least a day out's ATM implied vol, compute_implied_one_day_move) or None when ATM
    #: IV is unusable; the band itself (`points`) is at_spot's, at the live spot.
    implied_move_sigma: dict[str, Any] | None = None

    #: RC-115: each wall's EARNED per-side range — {lo, hi, coverage_pct, method} or None —
    #: the value-area of the wall's own side-gamma mass (never the strike grid).
    call_wall_range: dict[str, Any] | None = None
    put_wall_range: dict[str, Any] | None = None

    #: RC-128 (One Levels Faucet): delta walls owned by THIS producer — same wide chain,
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
    pcr_by_expiry: dict = field(default_factory=dict)          # put/call OI (positions held)
    #: each expiry's ATM implied vol, percent (atm_sigma_by_expiry); None when a leg has no IV
    atm_iv_pct_by_expiry: dict = field(default_factory=dict)
    pcr_volume_by_expiry: dict = field(default_factory=dict)   # put/call volume (today's trading)
    #: the same two ratios over the whole book (every expiry)
    pcr_all: float | None = None
    pcr_volume_all: float | None = None
    #: the one expiry list (listed_expiries): every expiry the chain lists, ascending, with
    #: Schwab's daysToExpiration and its settlement instant
    expiries: list = field(default_factory=list)
    expiry_dte: dict = field(default_factory=dict)
    expiry_settles: dict = field(default_factory=dict)
    #: Wall-clock the chain behind per_strike was fetched — every consumer must be able to render
    #: an age on its face rather than implying "now".
    computed_ts_utc: float | None = None

    def to_dict(self) -> dict[str, Any]:
        """The per-poll payload: every field except the heavy maps (profile, per_strike,
        books, charm_by_strike), which the server reads off the snapshot."""
        light = replace(self, **{n: None for n in _HEAVY_FIELDS})
        return {k: v for k, v in asdict(light).items() if k not in _HEAVY_FIELDS}


_HEAVY_FIELDS = ("profile", "per_strike", "books", "charm_by_strike")


def _unavailable(ticker: str, spot: float | None, reason: str) -> TerrainSnapshot:
    return TerrainSnapshot(ticker=ticker, spot=spot, error=reason)


#: no levels published: every value read from the spot is absent, with the read's reason
_NO_LEVELS: dict[str, Any] = {"flip_confidence": TerrainSnapshot.flip_confidence, "flip_diag": None,
                              "expiries": [], "expiry_dte": {}, "expiry_settles": {}, "max_pain_by_expiry": {}}


def at_spot(pub: "dict[str, Any] | None", spot: float | None, now: float) -> dict[str, Any]:
    """Every value read from the spot, at `spot` (the live one), from the levels the chain was
    priced to (`pub`: the published TerrainSnapshot's fields with the one strike list `_strikes`,
    None when none is published) -- the one producer of each (operator 2026-10-14: "the live spot
    for every distance, side, breached and band"): the strike nearest `spot` on the one strike
    list, the read (regime from the priced book's gamma at spot; posture, confidence, headline and
    lines worded at `spot`), each wall's state (RC-130: "contains" when the call wall is above /
    the put wall below the spot, else "breached"; the strike never moves) and dealer lean, the
    spot's distance to each wall and side of the flip, the pin candidate (its proximity gate at
    `spot`, its expiry gate on the front expiry's days) and the implied 1-day move (`points` =
    spot x sigma_ATM x sqrt(1/252)); and at `now`, each expiry's `expired` and the `front` one
    (expiry_states, operator 2026-10-14: "one front-expiry rule from Schwab's session,
    everywhere"), whose max pain is the one shown (`max_pain`, `max_pain_expiry`, `max_pain_dte`)."""
    p = pub if pub is not None else _NO_LEVELS
    states = expiry_states(p, now)
    front = states["front"]
    front_dte = None if front is None else p["expiry_dte"][front]
    flip, call_wall, put_wall = p.get("gamma_flip"), p.get("call_wall"), p.get("put_wall")
    diag = p["flip_diag"]
    read = build_terrain_read(
        spot=spot, flip=flip, flip_confidence=p["flip_confidence"],
        put_wall=put_wall, call_wall=call_wall,
        gamma_at_spot=None if diag is None else diag.get("gamma_at_spot"),
        flip_curve_agrees=None if diag is None else diag.get("curve_agrees_with_schwab_at_spot"))
    call_state, put_state = wall_geometry_state(spot, call_wall, "call"), wall_geometry_state(spot, put_wall, "put")
    call_lean, put_lean = wall_lean(call_wall, put_wall, call_state, put_state, read.regime, read.confidence)
    pin, pin_blockers = qualify_pin_candidate(
        spot=spot, absolute_gamma_strike=p.get("absolute_gamma_strike"),
        absolute_gamma_strength_pct=p.get("absolute_gamma_strength_pct"),
        absolute_gamma_gex_dollars=p.get("absolute_gamma_gex_dollars"),
        absolute_gamma_oi=p.get("absolute_gamma_oi"), book_oi_total=p.get("book_oi_total"),
        net_gex_at_spot=p.get("net_gex_at_spot"), front_dte=front_dte)
    sigma = p.get("implied_move_sigma")
    return {
        **states, "max_pain_expiry": front, "max_pain_dte": front_dte, "max_pain_dte_label": dte_label(front_dte),
        "max_pain": None if front is None else p["max_pain_by_expiry"].get(front),
        "spot_strike": nearest_strike(p.get("_strikes"), spot),
        "regime": read.regime, "posture": read.posture, "confidence": read.confidence,
        "headline": read.headline, "lines": read.lines,
        "call_wall_state": call_state, "put_wall_state": put_state,
        "call_wall_lean": call_lean, "put_wall_lean": put_lean,
        "dist_to_call_wall": None if call_wall is None or spot is None else call_wall - spot,
        "dist_to_put_wall": None if put_wall is None or spot is None else spot - put_wall,
        "flip_relation": None if flip is None or spot is None else "ABOVE" if spot >= flip else "BELOW",
        "pin_candidate": pin, "pin_candidate_blockers": pin_blockers,
        "implied_1d_move": None if sigma is None or spot is None else {
            **sigma, "points": float(spot) * sigma["sigma"] * (1.0 / 252.0) ** 0.5},
    }


def _per_strike_rows(exposures: dict) -> list[list]:
    """`[[strike, net_gex_1pct$, session_volume], …]` — the EXACT shape the panel renders.

    THE one producer of GEX-by-strike rows (live panel AND the prior-day ghost -- server.py
    carried a second copy, removed 2026-09-24).

    RC-79: the finished numbers are handed over as-is, never reassembled into synthetic
    contracts and recomputed.

    Audit T-01 / T-02 (2026-09-24, operator rule: no fallbacks):
      * the bar is net GEX$ from a DOLLARIZED book, exact (a strike whose contracts have open
        interest 0 is a $0 bar). It used to fall back to total_gamma_raw_at_strike -- UNSIGNED
        raw gamma drawn on the signed GEX$ axis. A strike whose GEX is not known
        (bucket_metric), or a book built without spot, has no bar.
      * volume is strike_total_volume, the one reader: Schwab's volumes as sent (0 is a real
        zero); None ("—") when a contract at the strike did not report it, never a partial sum.
    """
    from math_exposure_core import (exposures_have_dollar_gex, net_gex_dollars_at_strike,
                                    strike_total_volume)
    from numeric_contract import float_finite_or_none

    if not exposures or not exposures_have_dollar_gex(exposures):
        return []
    rows: list[list] = []
    for k, b in exposures.items():
        sk = float_finite_or_none(k)
        if sk is None:                      # a NaN strike must never become a rendered bar
            continue
        gf = float_finite_or_none(net_gex_dollars_at_strike(b))
        if gf is None:
            continue
        vol = strike_total_volume(b)
        rows.append([sk, gf, None if vol is None else int(vol)])
    rows.sort(key=lambda r: r[0])
    return rows


#: Weighted positive-gamma strike move below which drift reads as none. Carried unchanged from
#: the former /chart page's gamma panel (2026-09-27); its origin is not recorded -- NOT_PROVEN.
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
        drift = "UP" if d > MIGRATION_DRIFT_STRIKES else "DOWN" if -d > MIGRATION_DRIFT_STRIKES else "FLAT"
    changes = sorted((r for r in rows if r[3] is not None), key=lambda r: r[3], reverse=True)
    grew = [r[0] for r in changes if r[3] > 0][:2]
    shrank = [r[0] for r in changes if r[3] < 0][-2:]
    vols = [(r[0], r[2]) for r in today or [] if r[2]]
    busiest = sorted(k for k, _v in sorted(vols, key=lambda kv: kv[1], reverse=True)[:2])
    where = None
    if busiest:
        where = ("ABOVE_CALL_WALL" if call_wall is not None and min(busiest) > call_wall else
                 "BELOW_PUT_WALL" if put_wall is not None and max(busiest) < put_wall else "INSIDE_WALLS")
    reported = [r[2] for r in today or [] if r[2] is not None]
    return {"rows": rows, "compared": bool(changes), "drift": drift,
            "weighted_strike_today": wm_t, "weighted_strike_prior": wm_p,
            "grew": grew, "shrank": shrank, "busiest": busiest, "busiest_vs_walls": where,
            "volume_total": sum(reported) if reported else None}


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


def strike_window(strikes, centre, scope: str, shift: int = 0) -> "tuple[int, int, float | None]":
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


def listed_strikes(contracts) -> list[float]:
    """The one strike list: every strike Schwab lists in the chain (`strikePrice`, rule 2),
    ascending, once each. Every per-strike panel draws its rows on it."""
    from numeric_contract import schwab_number
    return sorted({k for c in contracts if (k := schwab_number(c.get("strikePrice"))) is not None})


def listed_expiries(contracts) -> dict[str, Any]:
    """The one expiry list: every expiry Schwab lists in the chain (its `expirationDate`'s date),
    ascending (`expiries`), each with its days to expiry (`expiry_dte`: Schwab's
    daysToExpiration as sent; None when its contracts send none, or disagree) and its settlement
    (`expiry_settles`: the latest of its contracts', time_et.settles_at, as a timestamp -- an
    expiry with AM- and PM-settled contracts has settled once all have; None while one
    contract's is not known)."""
    from numeric_contract import schwab_number
    from time_et import settles_at
    dtes: dict[str, set] = {}
    settles: dict[str, list] = {}
    for c in contracts:
        sent = c.get("expirationDate")
        e = str(sent)[:10]
        if sent is None or len(e) != 10:        # Schwab sent no date: no column of its own
            continue
        dtes.setdefault(e, set()).add(schwab_number(c.get("daysToExpiration")))
        s = settles_at(c.get("expirationDate"), c.get("settlementType"))
        settles.setdefault(e, []).append(None if s is None else s.timestamp())
    exps = sorted(dtes)
    return {"expiries": exps,
            "expiry_dte": {e: next(iter(dtes[e])) if len(dtes[e]) == 1 else None for e in exps},
            "expiry_settles": {e: None if None in settles[e] else max(settles[e]) for e in exps}}


def dte_label(dte: float | None) -> str | None:
    """Schwab's daysToExpiration as every screen words it ("0DTE", "9DTE"); None without one."""
    return None if dte is None else f"{dte:g}DTE"


def expiry_states(listed: dict[str, Any], now: float) -> dict[str, Any]:
    """The listed expiries (listed_expiries) at `now`: each one's `expired` (its settlement has
    passed; None while its settlement is not known) and the `front` expiry (the nearest that has
    not expired; None when none is known not to have) -- the one rule of both for every panel."""
    settles = listed["expiry_settles"]
    expired = {e: None if settles[e] is None else settles[e] <= now for e in listed["expiries"]}
    front = next((e for e in listed["expiries"] if expired[e] is False), None)
    return {"expired": expired, "front": front}


def on_strikes(rows: list, strikes: list, width: int) -> list:
    """`rows` ([strike, value, ...], `width` long) on the one strike list `strikes`: one row per
    listed strike, its own where `rows` has it, else the strike with no value ("-")."""
    by_k = {r[0]: r for r in rows}
    return [by_k[k] if k in by_k else [k] + [None] * (width - 1) for k in strikes]


def chain_ladder(contracts, spot, strikes, spot_strike) -> tuple[list[dict], int]:
    """One expiry's chain as the ladder draws it, and how many contracts it could not place (no
    strike, or a putCall other than CALL/PUT). Rows on the one strike list `strikes`, high to low
    (a strike with no contract in this expiry: one row, neither side); per strike one row per
    listed contract index (a second contract at one strike and side gets its own row); each
    contract's numbers read by rule 2 (-999, text, NaN absent); `call_itm` / `put_itm` against
    `spot` (None without one); `spot` marks the first row of `spot_strike` (at_spot's)."""
    from numeric_contract import schwab_number
    by_k: dict[float, dict[str, list]] = {k: {"call": [], "put": []} for k in strikes}
    unplaced = 0
    for c in contracts or []:
        k = schwab_number(c.get("strikePrice"))
        side = {"CALL": "call", "PUT": "put"}.get(str(c.get("putCall") or "").upper())
        if k is None or side is None:
            unplaced += 1
            continue
        shown = {f: (schwab_number(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v)
                 for f, v in c.items()}
        by_k[k][side].append(shown)
    rows = []
    for k in sorted(by_k, reverse=True):
        g = by_k[k]
        for i in range(max(len(g["call"]), len(g["put"]), 1)):
            rows.append({
                "strike": k, "first": i == 0, "spot": i == 0 and k == spot_strike,
                "call": g["call"][i] if i < len(g["call"]) else None,
                "put": g["put"][i] if i < len(g["put"]) else None,
                "call_itm": None if spot is None else k < spot,
                "put_itm": None if spot is None else k > spot,
            })
    return rows, unplaced


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
    from numeric_contract import schwab_number
    return schwab_number(ct.get("daysToExpiration")) if isinstance(ct, dict) else None


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


def atm_sigma_by_expiry(contracts: list[dict], spot: float) -> dict[tuple[str, float | None], float | None]:
    """Each expiry's ATM implied vol as a fraction, keyed like exposure_books ((expirationDate,
    daysToExpiration)): the mean of the call and the put IV, each at its side's strike nearest
    spot. Both legs or None: one side's IV never stands in for the mean (audit T-06, 2026-09-24),
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

    Returns the band's sigma {sigma, iv_pct_atm, dte_used, method}, the ATM pair picked at the
    spot the chain is priced at; the band itself (`points`, the one-sigma half-width in price
    points) is at_spot's, at the live spot, so it can never disagree with the price beside it.
    """
    if spot is None or spot <= 0 or not contracts:
        return None
    # RC-290: nearest expiry present in the chain. `_dte_of` now returns None for a contract
    # that does not state its DTE instead of a 999.0 stand-in, so those are dropped BEFORE
    # the min rather than being carried through it and screened out afterwards by a
    # magic-number comparison — which also means an all-unreadable chain yields None here
    # (no front expiry) rather than a confident 999.
    # the first expiry at least one day out: a same-day expiry's IV prices hours, not a day
    _dtes = [d for d in (_dte_of(c) for c in contracts if isinstance(c, dict))
             if d is not None and d >= 1]
    front = min(_dtes, default=None)
    if front is None:
        return None
    at_front = [s for (_e, d), s in atm_sigma_by_expiry(contracts, spot).items() if d == front]
    if len(at_front) != 1 or at_front[0] is None:
        return None
    sigma = at_front[0]
    return {
        "sigma": sigma,
        "iv_pct_atm": sigma * 100.0,
        "dte_used": front,
        "method": "S x sigma_ATM x sqrt(1/252), one standard deviation (68.3pct); "
                  "sigma = mean ATM call/put implied vol of the first expiry at least a day out",
    }


def _per_strike_measure_rows(exposures: dict) -> dict:
    """`{"dex": [[strike, net DEX $], …], "oi": [[strike, total OI], …]}`: every strike whose value
    is known, by the heatmap cell's own readers (net_dex_dollars of a dollarized book;
    strike_total_oi). A strike whose value is unknown has no row."""
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
            oi.append([sk, int(o)])
    dex.sort(key=lambda r: r[0])
    oi.sort(key=lambda r: r[0])
    return {"dex": dex, "oi": oi}


def per_strike_view(books: dict, exposures: dict) -> dict:
    """`{all, near, far}` GEX rows -- the ALL / <=7DTE / MONTHLY+ chips -- from the chain's
    exposure_books and their merged full book `exposures` (one pricing pass), and the full
    book's DEX and OI rows (`dex`, `oi`: _per_strike_measure_rows). A contract whose
    days-to-expiry cannot be read belongs to `all` only: a maturity split it cannot answer is
    not answered for it (RC-290)."""
    from math_exposure_core import merge_exposure_books

    def rows(keep) -> list:
        chosen = [b for (_exp, d), b in books.items() if keep(d)]
        if not chosen:
            return []
        subset_exposures, _diag = merge_exposure_books(chosen)
        return _per_strike_rows(subset_exposures)

    return {"all": _per_strike_rows(exposures),
            "near": rows(lambda d: d is not None and d <= 7),
            "far": rows(lambda d: d is not None and d > 7),
            **_per_strike_measure_rows(exposures)}






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


def wall_lean(call_wall, put_wall, call_state, put_state, regime, confidence) -> tuple:
    """(call, put) wall labels as the chart states them: one strike holding both walls is
    TWO-SIDED (a magnet, not a barrier); a breached wall says so; a containing wall earns the
    dealer lean (resistance: dealers sell, support: dealers buy) only on a TRUSTED flip with a
    regime; otherwise None. Moved from the former /chart page (RC-83/RC-130/RC-131)."""
    if call_wall is not None and call_wall == put_wall:
        return ("TWO-SIDED — magnet, not a barrier",) * 2
    earn = regime != "UNAVAILABLE" and confidence == "TRUSTED"
    def one(state, breached, lean):
        return breached if state == "breached" else lean if state == "contains" and earn else None
    return (one(call_state, "BREACHED — spot above", "DEALERS SELL"),
            one(put_state, "BREACHED — spot below", "DEALERS BUY"))


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
                    spot: float | None, *, now: datetime) -> TerrainSnapshot:
    """Full terrain for one ticker. Fails closed — never invents a level.

    `now`: the valuation instant for every time-to-expiry in this snapshot, read once by the
    caller's entry point (the live reprice: its own instant; a replay of a stored chain: the
    snapshot's time, so it reproduces what the live reprice saw).

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

    # ONE valuation instant for every book below
    _terrain_now = now
    # One pricing pass: exposures per (expiry, DTE) group; every book below is a merge of them.
    books = exposure_books(contracts, spot=spot, now=_terrain_now)
    exposures, diag = merge_exposure_books(books.values())
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
    # the gamma profile, built once at one instant, feeds the flip verdict and the regime read
    parsed, unpriced = contract_inputs(contracts, _terrain_now)   # one parse for profile + charm
    profile = compute_gamma_profile(contracts, spot, now=_terrain_now, parsed=parsed)
    flip, confidence, flip_diag = compute_gamma_flip_v2(contracts, spot, profile=profile)
    # ONE gamma at spot: Schwab's gamma as sent, summed over the book (the walls' own gamma).
    # The model curve places the flip only (Schwab sends gamma at its own price, never at
    # other prices); where the curve's sign at spot disagrees with Schwab's, the flip says so.
    _curve_at_spot = flip_diag.get("curve_gamma_at_spot")
    _gamma_at_spot = book_net_gex(exposures)
    flip_diag = {**flip_diag, "unpriced": unpriced,
                 "gamma_at_spot": _gamma_at_spot,
                 "curve_agrees_with_schwab_at_spot": (
                     None if _gamma_at_spot is None or _curve_at_spot is None
                     else (_gamma_at_spot > 0) == (_curve_at_spot > 0))}
    # RC-354: GSF/GRC from the SAME materialized profile — no second materialization.
    # Snap-to-shelf deliberately deferred until strike-GEX history is banked (theta wants a
    # trailing-60-session percentile; a session-local stand-in would be a fake calibration).
    _gsl = compute_gamma_support_levels(profile, spot)
    # RC-357: the 0DTE book from the SAME producer with the dte filter — same parser,
    # same sign model; the share is pure attribution, zero new math.
    # a contract with no readable DTE belongs to no expiry's book (it was counted as 0DTE)
    _exp_0dte, _ = merge_exposure_books(b for (_e, d), b in books.items() if d is not None and d <= 0)
    _zero_dte_share = compute_zero_dte_gamma_share(exposures, _exp_0dte)
    _zero_dte_pin = pick_pin_and_strength(_exp_0dte, sorted(_exp_0dte))[0]
    _zero_dte_pin_reason = (None if _zero_dte_pin is not None else
                            "no same-day expiry in the chain" if not _exp_0dte else
                            "the same-day expiry has no dollar gamma")
    # Max pain per expiry (its books merged: one per expiry date)
    _by_expiry: dict[str, list] = {}
    for (e, _d), b in books.items():
        _by_expiry.setdefault(e, []).append(b)
    _max_pain_by_expiry = {e: compute_max_pain(merge_exposure_books(bs)[0]) for e, bs in sorted(_by_expiry.items())
                           if len(e) == 10}
    # RC-358: 25Δ risk reversal from the same wide chain (front expiry, tolerance-gated).
    from math_volatility import compute_25d_risk_reversal
    _rr25 = compute_25d_risk_reversal(contracts)
    charm_by_strike = compute_charm_by_strike(contracts, spot, now=_terrain_now, parsed=parsed)
    call_charm_wall, put_charm_wall = pick_charm_wall_strikes(charm_by_strike)

    return TerrainSnapshot(
        ticker=ticker,
        spot=float(spot),
        flip_confidence=confidence,
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
        net_gex_peak=pick_net_gex_peak_strike(exposures, strikes),
        key_delta_strike=pick_key_delta_strike(exposures, strikes),
        hvp=hvp,
        lvp=lvp,
        net_gex_at_spot=flip_diag.get("gamma_at_spot"),
        gsf=_gsl["gsf"],
        grc=_gsl["grc"],
        gsf_state=_gsl["state"],
        zero_dte_gamma_share_pct=_zero_dte_share,
        zero_dte_abs_gamma_strike=_zero_dte_pin,
        zero_dte_abs_gamma_reason=_zero_dte_pin_reason,
        rr_25d=_rr25,
        vanna_agg=compute_net_vanna(exposures, spot),     # RC-362: same book, one sum
        implied_move_sigma=compute_implied_one_day_move(contracts, spot),   # RC-113
        call_wall_range=compute_wall_value_area(exposures, call_wall, "call"),   # RC-115
        put_wall_range=compute_wall_value_area(exposures, put_wall, "put"),      # RC-115
        call_delta_wall=call_delta_wall,   # RC-128: one book for delta walls too
        put_delta_wall=put_delta_wall,
        max_pain_by_expiry=_max_pain_by_expiry,
        **listed_expiries(contracts),
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
        per_strike=per_strike_view(books, exposures),
        books=books,
        charm_by_strike=charm_by_strike,
        pcr_by_expiry={e: put_call_oi_ratio(book) for (e, _d), (book, _diag) in sorted(books.items(), key=lambda kv: kv[0][0])},
        atm_iv_pct_by_expiry={e: None if s is None else s * 100.0
                              for (e, _d), s in atm_sigma_by_expiry(contracts, spot).items() if e},
        pcr_volume_by_expiry={e: put_call_volume_ratio(book) for (e, _d), (book, _diag) in books.items()},
        pcr_all=put_call_oi_ratio(exposures),
        pcr_volume_all=put_call_volume_ratio(exposures),
        computed_ts_utc=_time.time(),
    )
