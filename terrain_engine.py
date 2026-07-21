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

from dataclasses import asdict, dataclass, field
from typing import Any

from math_exposure_core import (
    compute_exposures_by_strike,
    exposures_have_dollar_gex,
    pick_gamma_pin_strike,
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
    gamma_pin: float | None = None
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

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("profile", None)
        return d


def _unavailable(ticker: str, spot: float | None, reason: str) -> TerrainSnapshot:
    read = build_terrain_read(spot=spot, flip=None, flip_confidence="UNAVAILABLE")
    return TerrainSnapshot(
        ticker=ticker, spot=spot, regime=read.regime, posture=read.posture,
        confidence=read.confidence, headline=read.headline, lines=read.lines,
        error=reason,
    )


def compute_terrain(ticker: str, contracts: list[dict] | None,
                    spot: float | None) -> TerrainSnapshot:
    """Full terrain for one ticker. Fails closed — never invents a level."""
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
    flip, confidence, flip_diag = compute_gamma_flip_v2(contracts, spot)
    profile = compute_gamma_profile(contracts, spot)
    charm_by_strike = compute_charm_by_strike(contracts, spot)
    call_charm_wall, put_charm_wall = pick_charm_wall_strikes(charm_by_strike)

    read = build_terrain_read(
        spot=spot, flip=flip, flip_confidence=confidence,
        put_wall=put_wall, call_wall=call_wall,
        gamma_at_spot=flip_diag.get("gamma_at_spot"),
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
        gamma_pin=pick_gamma_pin_strike(exposures, strikes, institutional=True),
        hvl=pick_hvl_strike(exposures, strikes),
        key_delta_strike=pick_key_delta_strike(exposures, strikes),
        hvp=hvp,
        lvp=lvp,
        net_gex_at_spot=flip_diag.get("gamma_at_spot"),
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
    )
