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
    exposures_have_dollar_gex,
    pick_net_gex_peak_strike,
    pick_pin_and_strength,
    pick_gamma_wall_strikes,
    pick_hvl_strike,
    pick_key_delta_strike,
    pick_volatility_point_strikes,
)
from math_levels import (
    compute_charm_by_strike,
    compute_gamma_flip_v2,
    compute_gamma_profile,
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
    #: RC-124: the former "pin" — max |net GEX$| (calls minus puts) — kept under its honest
    #: name; a real measure of where the SIGNED book peaks, distinct from the magnet.
    net_gex_peak: float | None = None
    hvl: float | None = None
    max_pain: float | None = None
    call_charm_wall: float | None = None
    put_charm_wall: float | None = None
    key_delta_strike: float | None = None
    hvp: float | None = None   # most NEGATIVE net GEX$ strike (amplification pocket)
    lvp: float | None = None   # most POSITIVE net GEX$ strike (damping pocket)

    #: Signed net dealer GEX$ per 1% move AT SPOT — the regime's own number
    #: (regime = its sign). Disambiguates walls that share a strike.
    net_gex_at_spot: float | None = None

    #: RC-113: the institutional sigma band — {points, iv_pct_atm, dte_used, method} or None
    #: when ATM IV is unusable (fail-closed, never a fabricated band). `points` is the
    #: one-sigma half-width; the client centers it on the live spot. The wall RANGE itself
    #: is the put_wall↔call_wall corridor — already carried above, drawn client-side.
    implied_1d_move: dict[str, Any] | None = None

    #: RC-115: each wall's EARNED per-side range — {lo, hi, coverage_pct, method} or None —
    #: the value-area of the wall's own side-gamma mass (never the strike grid).
    call_wall_range: dict[str, Any] | None = None
    put_wall_range: dict[str, Any] | None = None

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
        rows.append([round(sk, 2), round(float(g or 0.0), 1), int(vol_by_k.get(sk, 0))])
    rows.sort(key=lambda r: r[0])
    return rows


def _dte_of(ct: object) -> float:
    """Finite DTE; junk sorts as far-dated rather than poisoning the comparison with NaN."""
    from numeric_contract import float_finite_or_none
    d = float_finite_or_none(ct.get("daysToExpiration")) if isinstance(ct, dict) else None
    return d if d is not None else 999.0


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
    # nearest expiry present in the chain (weekends/junk sort far-dated via _dte_of)
    front = min((_dte_of(c) for c in contracts if isinstance(c, dict)), default=None)
    if front is None or front >= 999.0:
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
    for name, subset in (("near", [c for c in contracts if _dte_of(c) <= 7]),
                         ("far", [c for c in contracts if _dte_of(c) > 7])):
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
        out[sk] = {"strike": sk, "net_gex": getattr(ex, "net_gex", None), "volume": 0.0}
    for ct in contracts or []:
        if not isinstance(ct, dict):
            continue
        sk = float_finite_or_none(ct.get("strikePrice"))
        if sk is None or sk not in out:
            continue
        v = float_nonnegative_or_none(ct.get("totalVolume"))
        if v is not None:
            out[sk]["volume"] += v
    return out


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
    flip, confidence, flip_diag = compute_gamma_flip_v2(contracts, spot)
    profile = compute_gamma_profile(contracts, spot)
    charm_by_strike = compute_charm_by_strike(contracts, spot)
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
        net_gex_peak=pick_net_gex_peak_strike(exposures, strikes, institutional=True),
        hvl=pick_hvl_strike(exposures, strikes),
        key_delta_strike=pick_key_delta_strike(exposures, strikes),
        hvp=hvp,
        lvp=lvp,
        net_gex_at_spot=flip_diag.get("gamma_at_spot"),
        implied_1d_move=compute_implied_one_day_move(contracts, spot),   # RC-113
        call_wall_range=compute_wall_value_area(exposures, call_wall, "call"),   # RC-115
        put_wall_range=compute_wall_value_area(exposures, put_wall, "put"),      # RC-115
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
