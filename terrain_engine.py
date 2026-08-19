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
from dataclasses import asdict, dataclass, field
from typing import Any

from math_exposure_core import (
    compute_exposures_by_strike,
    compute_net_dex_dollars,
    compute_net_vanna,
    compute_zero_dte_gamma_share,
    exposures_have_dollar_gex,
    pick_delta_wall_strikes,
    pick_net_gex_peak_strike,
    pick_pin_and_strength,
    pick_gamma_wall_strikes,
    pick_key_delta_strike,
    pick_volatility_point_strikes,
    total_gex_dollars_at_strike,
)
from math_levels import (
    compute_charm_by_strike,
    compute_gamma_flip_v2,
    compute_gamma_profile,
    compute_gamma_support_levels,
    compute_max_pain,
    key_level_strikes_with_gamma,
    pick_charm_wall_strikes,
)
from terrain_read import build_terrain_read

#: Payload schema version — bump on any field change so the UI can fail closed.
#: v2 (2026-07-21): + net_gex_at_spot, key_delta_strike, hvp, lvp.
TERRAIN_SCHEMA_VERSION = 2


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

    # levels
    gamma_flip: float | None = None
    call_wall: float | None = None
    put_wall: float | None = None
    #: RC-124: THE standard pin — max TOTAL gamma (SpotGamma Absolute Gamma / sticky pin;
    #: Avellaneda–Lipkin magnitude mechanism). Strength = leader's margin over the runner-up
    #: on the same metric (a 1% lead is a coin flip; the label says so).
    gamma_pin: float | None = None
    gamma_pin_strength_pct: float | None = None
    #: RC-413: GEX$ / OI at gamma_pin plus book OI, from the SAME exposures book that
    #: picked the pin. pin_score reads these so strike and magnitude cannot split onto
    #: the analytics selected-expiry book. None = fail-closed (absent/stale/undollarized).
    gamma_pin_gex_dollars: float | None = None
    gamma_pin_oi: float | None = None
    book_oi_total: float | None = None
    #: RC-124: the former "pin" — max |net GEX$| (calls minus puts) — kept under its honest
    #: name; a real measure of where the SIGNED book peaks, distinct from the magnet.
    net_gex_peak: float | None = None
    #: RC-134: terrain `hvl` REMOVED — it equaled gamma_pin by construction (same total-GEX$
    #: metric as pick_hvl_strike / pick_pin_and_strength). Total-gamma renders once as
    #: GAMMA PIN. Analytics `kl_hvl` remains a DIFFERENT book (net_gex_peak → "Net Γ peak").
    max_pain: float | None = None
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
    #: Wall-clock the chain behind per_strike was fetched — every consumer must be able to render
    #: an age on its face rather than implying "now".
    computed_ts_utc: float | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("profile", None)
        # RC-68: per_strike is hundreds of entries — far too heavy for every poll, same reason
        # `profile` is excluded. /api/terrain/strikes reads it off the cached snapshot directly.
        # computed_ts_utc DOES stay in the payload: every consumer must be able to show an age.
        d.pop("per_strike", None)
        # RC-359: same weight class as per_strike — banked server-side, never per-poll.
        d.pop("oi_by_strike", None)
        return d


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

    RC-79. This used to hand back a map of raw parts which the endpoint reassembled into synthetic
    contract dicts and pushed back through compute_exposures_by_strike(require_oi=True). Those
    synthetics carried no open interest, so the engine rejected every one and the panel rendered
    ZERO rows — worse than the stale archive it replaced. The finished numbers were already here;
    they were being taken apart and recomputed from a shape that could not survive the trip.

    The metric is net_gex_1pct with the same raw-gamma fallback the prior-day ghost uses, because
    the two are drawn in the same frame: a live series on one scale beside a ghost on another is a
    picture of a positioning shift that did not happen.
    """
    from math_exposure_core import bucket_metric, total_gamma_raw_at_strike
    from numeric_contract import float_finite_or_none, float_nonnegative_or_none

    vol_by_k: dict[float, float] = {}
    for ct in contracts or []:
        if not isinstance(ct, dict):
            continue
        sk = float_finite_or_none(ct.get("strikePrice"))
        v = float_nonnegative_or_none(ct.get("totalVolume"))
        if sk is not None and v:
            vol_by_k[sk] = vol_by_k.get(sk, 0.0) + v

    rows: list[list] = []
    for k, b in (exposures or {}).items():
        sk = float_finite_or_none(k)
        if sk is None:                      # a NaN strike must never become a rendered bar
            continue
        g = bucket_metric(b, "net_gex_1pct")
        if g is None:
            g = total_gamma_raw_at_strike(b)
        if g is None:
            # RC-274: the same law as the NaN strike four lines up. With both the metric and the
            # raw fallback absent, `float(g or 0.0)` drew a bar at zero — visually identical to a
            # strike measured at flat gamma, on the surface used to read where dealers are short.
            continue
        gf = float_finite_or_none(g)
        if gf is None:
            continue
        rows.append([round(sk, 2), round(gf, 1), int(vol_by_k.get(sk, 0))])
    rows.sort(key=lambda r: r[0])
    return rows


def _dte_of(ct: object) -> float | None:
    """Days to expiration, or None when the contract does not say.

    RC-290: this returned 999.0 for an unreadable DTE and I annotated it "SORT KEY only,
    never rendered". Cursor executed the claim: `_per_strike_scopes` classifies contracts
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

    if wall is None or not exposures:
        return None
    key = (f"{side}_gex_1pct" if exposures_have_dollar_gex(exposures) else f"{side}_gamma")
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
        d = abs(strike - float(spot))
        if side not in ivs or d < ivs[side][0]:
            ivs[side] = (d, iv_pct / 100.0)
    if not ivs:
        return None
    sigma = sum(v[1] for v in ivs.values()) / len(ivs)   # ATM call/put mean (straddle IV)
    em = float(spot) * sigma * (1.0 / 252.0) ** 0.5
    return {
        "points": round(em, 4),
        "iv_pct_atm": round(sigma * 100.0, 4),
        "dte_used": front,
        "method": "S x sigma_ATM x sqrt(1/252), one standard deviation (68.3pct); "
                  "sigma = mean of nearest-expiry ATM call/put implied vol",
    }


def _per_strike_scopes(exposures: dict, contracts: list[dict], spot: float | None) -> dict:
    """`{all, near, far}` rows — the three the ALL / <=7DTE / MONTHLY+ chips switch between.

    RC-79: the live map had no DTE split at all, so two of the three chips would have shown an
    empty panel even after the rows themselves were fixed. `all` reuses the exposures already
    computed for this chain; the two subsets are computed here, where the chain is in hand.
    """
    out = {"all": _per_strike_rows(exposures, contracts), "near": [], "far": []}
    if not contracts or spot is None:
        return out
    # RC-290: a contract whose DTE cannot be read belongs to NEITHER maturity side. It used
    # to arrive here as 999.0 and land in `far`, so unknown maturity was rendered under the
    # MONTHLY+ chip as if it had been measured. `all` still carries it — that chip claims
    # no maturity — but a split the contract cannot answer must not be answered for it.
    _dted = [(c, _dte_of(c)) for c in contracts]
    for name, subset in (("near", [c for c, d in _dted if d is not None and d <= 7]),
                         ("far", [c for c, d in _dted if d is not None and d > 7])):
        if not subset:
            continue
        try:
            ex, _diag = compute_exposures_by_strike(subset, spot=spot, require_oi=True)
            out[name] = _per_strike_rows(ex, subset)
        except Exception:
            out[name] = []                  # a failed scope renders empty, never as `all`
    return out


def _per_strike_map(exposures: dict, contracts: list[dict]) -> dict[float, dict[str, Any]]:
    """Per-strike net GEX$ and SESSION VOLUME from the chain that just built `exposures` (RC-68).

    Volume is summed through the canonical non-negative reader — never a raw float(), which admits
    NaN silently (RC-38) — and strikes are read through the finite reader so a NaN strike can never
    become a dict key. One chain in, one map out: this is the single source for the per-strike
    histogram, replacing the frozen morning archive it used to read.
    """
    from numeric_contract import float_finite_or_none, float_nonnegative_or_none

    out: dict[float, dict[str, Any]] = {}
    for k, ex in (exposures or {}).items():
        sk = float_finite_or_none(k)
        if sk is None:
            continue
        # RC-290: None, not 0.0. I annotated this `caps-ok: a strike with no contract volume
        # genuinely traded zero` and Cursor executed the claim — a MISSING totalVolume and a
        # REAL zero both produced 0.0, so the rendered per-strike volume could not tell "no
        # contract reported" from "nobody traded". That is RC-274's defect, reintroduced by
        # me inside a comment excusing it. A strike only gets a number once a contract
        # actually supplies one.
        out[sk] = {"strike": sk, "net_gex": getattr(ex, "net_gex", None), "volume": None}  # caps-ok: the getattr default is None, which PRESERVES absence rather than substituting a value — the exact opposite of the pattern family; verified by test_absent_net_gex_stays_none_not_zero
    for ct in contracts or []:
        if not isinstance(ct, dict):
            continue
        sk = float_finite_or_none(ct.get("strikePrice"))
        if sk is None or sk not in out:
            continue
        v = float_nonnegative_or_none(ct.get("totalVolume"))
        if v is not None:
            prev = out[sk]["volume"]
            out[sk]["volume"] = v if prev is None else prev + v
    return out


def strongest_strike_storm1(rows: list | None) -> dict | None:
    """RC-159 — the SPOT-INDEPENDENT strongest strike, from `[[strike, net_gex, volume], ...]`.

    OPERATOR DEFINITION (binding):
        inv_rank(x) = n + 1 - rank(x)          # rank 1 = highest value
        storm1(k)   = inv_rank(volume_k) * inv_rank(|net_gex_k|)
        strongest   = argmax_k storm1(k)

    SPOT DOES NOT SELECT THE CANDIDATE SET, and that is the whole point. The old
    strongest-strike notion ranked inside a +/-5 percent band around spot, which cannot express
    the situation the operator is actually asking about: a strike that is far away NOW and that
    price may migrate toward. A band centred on spot answers "what is strong near where we are";
    this answers "what is strong", and the two differ exactly when the answer matters.

    Ranking is over every strike PRESENT IN THE ROWS — the same liquid set the Chart paints, so
    the score describes the ladder an operator is looking at rather than a private universe.
    Ties take the average rank, so two equal volumes cannot be ordered by list position.

    Returns None when no row carries a finite strike, gex and volume — absence stays absence.
    NOT A SIGNAL: this is a Collect/analytics descriptor. It has no forward test, no admission,
    and no place in Decide.
    """
    clean: list[tuple[float, float, float]] = []
    for r in rows or []:
        if not isinstance(r, (list, tuple)) or len(r) < 3:
            continue
        try:
            k, g, v = float(r[0]), float(r[1]), float(r[2])
        except (TypeError, ValueError):
            continue
        if not (k == k and g == g and v == v):          # NaN never becomes a winner
            continue
        if k in (float("inf"), float("-inf")):
            continue
        clean.append((k, abs(g), v))
    if not clean:
        return None

    def _inv_ranks(vals: list[float]) -> list[float]:
        """n+1-rank with AVERAGE ranks for ties (rank 1 = highest)."""
        n = len(vals)
        order = sorted(range(n), key=lambda i: -vals[i])
        ranks = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and vals[order[j + 1]] == vals[order[i]]:
                j += 1
            avg = (i + 1 + j + 1) / 2.0                  # 1-based average rank for the tie group
            for t in range(i, j + 1):
                ranks[order[t]] = avg
            i = j + 1
        return [n + 1 - r for r in ranks]

    vol_inv = _inv_ranks([c[2] for c in clean])
    gex_inv = _inv_ranks([c[1] for c in clean])
    best_i, best_score = 0, -1.0
    for i in range(len(clean)):
        s = vol_inv[i] * gex_inv[i]
        # deterministic tie-break: higher volume, then lower strike — never list order
        if s > best_score or (s == best_score and (
                clean[i][2], -clean[i][0]) > (clean[best_i][2], -clean[best_i][0])):
            best_i, best_score = i, s
    n = len(clean)
    return {
        "strike": clean[best_i][0],
        "storm1": best_score,
        "vol": clean[best_i][2],
        "abs_gex": clean[best_i][1],
        "vol_rank": n + 1 - vol_inv[best_i],
        "gex_rank": n + 1 - gex_inv[best_i],
        "n_strikes": n,
        "universe": "all strikes present in the row set — spot did not select it",
    }


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


def compute_terrain(ticker: str, contracts: list[dict] | None,
                    spot: float | None) -> TerrainSnapshot:
    """Full terrain for one ticker. Fails closed — never invents a level.

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

    exposures, diag = compute_exposures_by_strike(contracts, spot=spot, require_oi=True)
    if not exposures:
        return _unavailable(ticker, spot, "chain produced no exposures")

    strikes = key_level_strikes_with_gamma(exposures) or sorted(
        float(k) for k in exposures
    )
    (call_wall, _cw_str), (put_wall, _pw_str) = pick_gamma_wall_strikes(exposures, strikes)
    hvp, lvp = pick_volatility_point_strikes(exposures, strikes)
    _pin, _pin_strength = pick_pin_and_strength(exposures, strikes)   # RC-124: the standard pin
    # RC-413: pin_score GEX/OI from THIS same exposures book — never a second analytics book.
    _pin_gex_dollars = None
    _pin_oi = None
    _book_oi_total = None
    _oi_acc = 0.0
    _oi_seen = False
    _pin_bucket = None
    for _k, _v in exposures.items():
        if not isinstance(_v, dict):
            continue
        _co, _po = _v.get("call_oi"), _v.get("put_oi")
        if _co is not None or _po is not None:
            try:
                _oi_acc += (float(_co) if _co is not None else 0.0) + (
                    float(_po) if _po is not None else 0.0
                )
                _oi_seen = True
            except (TypeError, ValueError):
                pass
        if _pin is not None:
            try:
                if float(_k) == float(_pin):
                    _pin_bucket = _v
            except (TypeError, ValueError):
                pass
    if _oi_seen:
        _book_oi_total = _oi_acc
    if _pin_bucket is not None:
        _pin_gex_dollars = total_gex_dollars_at_strike(_pin_bucket)
        _co, _po = _pin_bucket.get("call_oi"), _pin_bucket.get("put_oi")
        if _co is not None or _po is not None:
            try:
                _pin_oi = (float(_co) if _co is not None else 0.0) + (
                    float(_po) if _po is not None else 0.0
                )
            except (TypeError, ValueError):
                _pin_oi = None
    # RC-128 (One Levels Faucet): the SSOT producer owns the delta walls too — same wide
    # chain, same exposures, one book. OI/vanna walls stay unowned and therefore BLANK on
    # every operator surface until this producer computes them.
    (call_delta_wall, _cdw_str), (put_delta_wall, _pdw_str) = pick_delta_wall_strikes(
        exposures, strikes)
    # RC-345 / F03: the gamma profile is materialized ONCE, at one pinned instant, and shared
    # by both the flip verdict and the regime/gamma-at-spot read. Previously the flip built a
    # profile inside compute_gamma_flip_v2 and this function built a SECOND one, each defaulting
    # `now` to its own wall-clock read — two materializations of the same curve at two instants.
    from time_et import now_et as _now_et
    _terrain_now = _now_et()
    profile = compute_gamma_profile(contracts, spot, now=_terrain_now)
    flip, confidence, flip_diag = compute_gamma_flip_v2(
        contracts, spot, now=_terrain_now, profile=profile)
    # RC-354: GSF/GRC from the SAME materialized profile — no second materialization.
    # Snap-to-shelf deliberately deferred until strike-GEX history is banked (theta wants a
    # trailing-60-session percentile; a session-local stand-in would be a fake calibration).
    _gsl = compute_gamma_support_levels(profile, spot)
    # RC-357: the 0DTE book from the SAME producer with the dte filter — same parser,
    # same sign model; the share is pure attribution, zero new math.
    _exp_0dte, _ = compute_exposures_by_strike(
        contracts, spot=spot, require_oi=True, use_only_dte_max=0)
    _zero_dte_share = compute_zero_dte_gamma_share(exposures, _exp_0dte)
    # RC-358: 25Δ risk reversal from the same wide chain (front expiry, tolerance-gated).
    from math_volatility import compute_25d_risk_reversal
    _rr25 = compute_25d_risk_reversal(contracts)
    charm_by_strike = compute_charm_by_strike(contracts, spot, now=_terrain_now)
    call_charm_wall, put_charm_wall = pick_charm_wall_strikes(charm_by_strike)

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
        # RC-124: gamma_pin is THE standard pin — max TOTAL gamma (SpotGamma Absolute
        # Gamma / sticky pin) with its decisiveness; the old net-argmax lives on honestly
        # as net_gex_peak. Assigned below from _pin/_pin_strength.
        gamma_pin=_pin,
        gamma_pin_strength_pct=_pin_strength,
        gamma_pin_gex_dollars=_pin_gex_dollars,
        gamma_pin_oi=_pin_oi,
        book_oi_total=_book_oi_total,
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
        max_pain=compute_max_pain(exposures),
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
        per_strike=_per_strike_scopes(exposures, contracts, spot),
        computed_ts_utc=_time.time(),
    )
