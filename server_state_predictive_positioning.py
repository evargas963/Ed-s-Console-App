"""Section 8 Predictive Positioning Signals phase of _fetch_state (server.py),
extracted (RC-REHAB-1, 2026-09-23). Twenty-first real module-level slice of the
_fetch_state decomposition, alongside server_state_volatility.py,
server_state_candles.py, server_state_signals.py, server_state_order_flow.py, and
server_state_persistence_tail.py -- see server_state_volatility.py's own docstring for
why this decomposition exists.

_predictive_positioning_for_state and its private return type
(_PredictivePositioningForState, a NamedTuple with no external reader confirmed by a
repo-wide search before moving) move together as one unit.

MONKEYPATCH/RUNTIME-STATE NOTE: this function calls 2 server.py-local helpers that have
OTHER callers elsewhere in server.py (confirmed before moving, so they correctly stay in
server.py rather than moving too): _bucket_total_oi (a second call site in _fetch_state's
own Level Density sub-phase) and terrain_cache_get. Reached via the same lazy `import
server` pattern proven in prior slices.

aggregate_net_gex, bucket_metric, compute_breakout_score, compute_dealer_pressure_index,
compute_gamma_gradient, compute_hedging_flow_score, compute_pin_score, and
compute_vol_expansion_signal are re-imported here directly from math_exposure.py --
none of this is server.py-specific logic.
"""
from __future__ import annotations

import logging
from typing import NamedTuple, Optional

log = logging.getLogger(__name__)

from math_exposure import (
    aggregate_net_gex,
    bucket_metric,
    compute_breakout_score,
    compute_dealer_pressure_index,
    compute_gamma_gradient,
    compute_hedging_flow_score,
    compute_pin_score,
    compute_vol_expansion_signal,
)

# RC-REHAB-1: moved with _predictive_positioning_for_state -- confirmed no other
# reference anywhere in server.py before moving.
GEX_NEAR_SPOT_RADIUS: float = 2.0   # strikes within $2 of spot are "near spot"
VOID_DIST_FALLOFF:   float = 5.0    # $5 from void edge -> factor decays to 0


def _unit(x: Optional[float]) -> Optional[float]:
    """Scale an aggregate into -1..+1 by its own magnitude (floored at 1.0); None stays None."""
    return None if x is None else x / max(abs(x), 1.0)


class _PredictivePositioningForState(NamedTuple):
    dpi: dict
    hedging_flow: dict
    gamma_gradient: Optional[float]
    breakout_score: dict
    pin_score_val: dict
    vol_expansion: dict
    void_factor: float
    pin_strike: Optional[float]
    regime_gamma_at_spot: Optional[float]


def _predictive_positioning_for_state(
    ticker: str,
    exposures: dict,
    cons_strikes: list,
    spot_f: float,
    charm_net: Optional[float],
    gamma_voids: list,
    iv_direction: str,
) -> _PredictivePositioningForState:
    """RC-REHAB-1 (Phase 4, _fetch_state decomposition, eighth slice): the Section 8
    Predictive Positioning Signals phase (DPI, hedging flow, gamma gradient, breakout,
    pin score, vol expansion, void factor, and the terrain-SSOT pin/regime reads that
    also feed build_market_state), extracted verbatim.

    Sweep Score is deliberately NOT part of this phase's output -- the original inline
    code only pre-initializes `_sweep_score = {}` in this same banner scope (a
    placeholder) and computes its REAL value in a LATER block that needs
    ms.nearest_above_dist/ms.nearest_below_dist, only available after build_market_state
    runs. `_fetch_state` keeps that pre-initializer itself, unmoved.

    `_bucket_total_oi` was promoted to a module-level function (see its own docstring)
    since a SECOND call site much later in _fetch_state's body (the Level Density
    sub-phase) also needs it and a nested def would not have been visible there once
    Section 8 became its own top-level function.

    Pre-initialization ordering preserved deliberately (gamma-audit 2026-08-26 finding,
    already documented at the original call site): pin_strike/regime_gamma_at_spot are
    initialized to None BEFORE the try block, not inside it, so a raise anywhere earlier
    in this phase still leaves them safely None for build_market_state to read rather
    than raising NameError there instead -- this function preserves that same ordering.
    """
    import server as _srv

    dpi: dict = {}
    hedging_flow: dict = {}
    gamma_gradient: Optional[float] = None
    breakout_score: dict = {}
    pin_score_val: dict = {}
    vol_expansion: dict = {}
    void_factor = 0.0
    pin_strike: Optional[float] = None
    regime_gamma_at_spot: Optional[float] = None
    try:
        # Aggregate totals — same full-chain Σ net_gex_1pct as kl_net_gex / ExposureRow CONSENSUS
        # RC-REHAB-1 (2026-09-23, CAPS review): every aggregate stays None until a real value
        # contributes -- the same shape sum_oi already used. Previously an absent net GEX
        # became 0.0 (under a marker claiming the normalization "has no null-safe path") and
        # sum_dex / sum_vanna started at 0.0, so a chain with no dex/vanna data reported a
        # measured zero. Every consumer below handles None by EXCLUDING the term:
        # compute_dealer_pressure_index returns null-shaped output, compute_hedging_flow_score
        # re-weights over the terms present, compute_vol_expansion_signal drops the GEX part.
        # A fabricated 0.0 instead took a full weight share and pulled scores toward neutral.
        sum_gex = aggregate_net_gex(exposures, cons_strikes)
        sum_dex: Optional[float] = None
        sum_oi: Optional[float] = None
        sum_vanna: Optional[float] = None
        for bkt in exposures.values():
            dex = bucket_metric(bkt, "net_dex_dollars")
            if dex is not None:
                sum_dex = (sum_dex or 0.0) + dex
            bucket_oi = _srv._bucket_total_oi(bkt)
            if bucket_oi is not None:
                sum_oi = (sum_oi or 0.0) + bucket_oi
            for leg in ("call_vanna", "put_vanna"):
                v = bucket_metric(bkt, leg)
                if v is not None:
                    sum_vanna = (sum_vanna or 0.0) + v

        # 1. DPI — null-shaped result when net GEX, net DEX or OI is absent.
        dpi = compute_dealer_pressure_index(sum_dex, sum_gex, sum_oi)

        # 2. Hedging Flow Score — each input normalized to -1..+1 by its own magnitude
        # (floored at 1.0); an absent input stays None and is excluded from the score.
        hedging_flow = compute_hedging_flow_score(
            net_gex_normalized=_unit(sum_gex),
            net_dex_normalized=_unit(sum_dex),
            charm_normalized=_unit(charm_net),
            vanna_normalized=_unit(sum_vanna),
        )

        # 3. Gamma Gradient
        gamma_gradient = compute_gamma_gradient(exposures, spot_f)

        # 4. Breakout Score
        gex_near_spot = 0.0
        for k, b in exposures.items():
            if abs(float(k) - spot_f) > GEX_NEAR_SPOT_RADIUS:
                continue
            ng = bucket_metric(b, "net_gex_1pct")
            if ng is not None:
                gex_near_spot += abs(ng)
        void_factor = 0.0
        for vz in (gamma_voids or []):
            if vz.get("contains_spot"):
                void_factor = 1.0
                break
            vz_dist = min(abs(vz.get("lower", spot_f) - spot_f), abs(vz.get("upper", spot_f) - spot_f))  # caps-ok: math_levels.compute_gamma_void_zones always sets lower/upper/contains_spot -- default never fires, kept as defense against a future producer change
            void_factor = max(void_factor, max(0, 1.0 - vz_dist / VOID_DIST_FALLOFF))
        try:
            breakout_score = compute_breakout_score(gex_near_spot, gamma_gradient, void_factor)
        except Exception as e:
            log.warning(f"breakout_score failed: {e}")
            breakout_score = {}

        # 5. Pin Score — strike AND GEX/OI from the terrain SSOT book (RC-124/RC-292/RC-413).
        # Never consensus_summary.net_gex_peak (analytics |net GEX$| peak) and never analytics
        # `exposures` for magnitude at that strike. RC-292 rename: the terrain payload field
        # is absolute_gamma_strike — the raw total-gamma concentration; pin_score grades it.
        t_pin_snap = _srv.terrain_cache_get(ticker) or {}
        pin_strike = (
            t_pin_snap.get("absolute_gamma_strike")
            if t_pin_snap and not t_pin_snap.get("levels_stale")
            else None
        )
        gex_at_pin = None
        oi_concentration = None
        if pin_strike is not None and t_pin_snap and not t_pin_snap.get("levels_stale"):
            try:
                tg = t_pin_snap.get("absolute_gamma_gex_dollars")
                toi = t_pin_snap.get("absolute_gamma_oi")
                tbook = t_pin_snap.get("book_oi_total")
                if tg is not None and toi is not None and tbook is not None:
                    book_oi = float(tbook)
                    gex_at_pin = float(tg)
                    oi_concentration = (
                        (float(toi) / book_oi) if book_oi > 0 else None
                    )
            except (TypeError, ValueError):
                gex_at_pin = None
                oi_concentration = None
        try:
            pin_score_val = compute_pin_score(gex_at_pin, oi_concentration)
        except Exception as e:
            log.warning(f"pin_score failed: {e}")
            pin_score_val = {}

        # Cursor-audit F9 / gamma audit: the dealer dampen/amplify REGIME sign, read from the SAME
        # terrain SSOT snapshot as the pin above and on the SAME fail-closed terms. net_gex_at_spot
        # IS gamma_at_spot over the wide multi-expiry book (terrain_engine) — the exact value the
        # terrain card renders — so the Call/regime consumers and the card read ONE number and cannot
        # disagree in sign. Sourcing it from the selected-expiry analytics diag (the first cut of this
        # fix) could disagree, and a one-expiry slice is the wrong basis for a whole-book hedging
        # claim. Missing or stale snapshot -> None -> every consumer withholds its regime claim.
        regime_gamma_at_spot = (
            t_pin_snap.get("net_gex_at_spot")
            if t_pin_snap and not t_pin_snap.get("levels_stale")
            else None
        )

        # 6. Vol Expansion Signal
        iv_dir_num = 1.0 if iv_direction == "expanding" else -1.0 if iv_direction == "contracting" else 0.0
        vol_expansion = compute_vol_expansion_signal(sum_gex, iv_dir_num, gamma_gradient)

        # Sweep Score moved below: needs ms.nearest_above_dist / ms.nearest_below_dist
        # which are only populated by build_market_state. The previous compute here read
        # `getattr(ms, _wname, None) if 'ms' in dir() else None` — `ms` was undefined at
        # this point in execution, so the loop always set _nearest_wall_dist=None and
        # sweep_score was silently degraded every tick.

    except Exception as e:
        log.debug(f"Section 8 signals calc: {e}")

    return _PredictivePositioningForState(
        dpi=dpi,
        hedging_flow=hedging_flow,
        gamma_gradient=gamma_gradient,
        breakout_score=breakout_score,
        pin_score_val=pin_score_val,
        vol_expansion=vol_expansion,
        void_factor=void_factor,
        pin_strike=pin_strike,
        regime_gamma_at_spot=regime_gamma_at_spot,
    )
