"""Volatility Envelope, Level Density, and Sector Strength phase of _fetch_state
(server.py), extracted (RC-REHAB-1, 2026-09-23). Twenty-second real module-level
slice of the _fetch_state decomposition, alongside server_state_volatility.py,
server_state_candles.py, server_state_signals.py, server_state_order_flow.py,
server_state_persistence_tail.py, and server_state_predictive_positioning.py --
see server_state_volatility.py's own docstring for why this decomposition exists.

_vol_envelope_and_sector_for_state and its private return type
(_VolEnvelopeAndSectorForState, a NamedTuple with no external reader confirmed by a
repo-wide search before moving) move together as one unit, along with the private
_VIXTracker class, its module-level _vix_tracker singleton, and the
VIX_DIRECTION_THRESHOLD constant it alone reads -- confirmed the ONLY reader/caller
of all three, anywhere in server.py, before moving (server.py's own _IVTracker/
_iv_tracker/IV_DIRECTION_THRESHOLD are a separate, unrelated tracker and stay put).

MONKEYPATCH/RUNTIME-STATE NOTE: this function calls 2 server.py-local names that have
OTHER callers elsewhere in server.py (confirmed before moving, so they correctly stay in
server.py rather than moving too): _state_cache (45 occurrences repo-file-wide) and
terrain_cache_get. Reached via the same lazy `import server` pattern proven in prior
slices.

MarketVolContextV1 (market_state.py), record_market_vol_observation
(vol_observability.py), and compute_volatility_envelope/compute_level_density/
compute_sector_strength/compute_iwm_confluence (math_exposure.py) are re-imported here
directly from their own modules -- none of this is server.py-specific logic, and none
have any external `from server import` caller (checked repo-wide before moving).
"""
from __future__ import annotations

import logging
import time
from typing import NamedTuple

log = logging.getLogger(__name__)

from market_state import MarketVolContextV1
from math_exposure import (
    compute_iwm_confluence,
    compute_level_density,
    compute_sector_strength,
    compute_volatility_envelope,
)
from vol_observability import record_market_vol_observation
import terrain_loop

# RC-REHAB-1: moved with _vol_envelope_and_sector_for_state -- confirmed the only
# reader anywhere in server.py before moving.
VIX_DIRECTION_THRESHOLD: float = 0.3   # ±0.3 pts tick-to-tick to call rising/falling


class _VIXTracker:
    """Track VIX direction across refreshes."""
    def __init__(self):
        self._prev: float | None = None
        self._direction: str = "flat"

    def tick(self, vix_now: float | None):
        if vix_now is None or vix_now <= 0:
            return
        if self._prev is not None and self._prev > 0:
            diff = vix_now - self._prev
            if diff > VIX_DIRECTION_THRESHOLD:
                self._direction = "rising"
            elif diff < -VIX_DIRECTION_THRESHOLD:
                self._direction = "falling"
            else:
                self._direction = "flat"
        self._prev = vix_now

    @property
    def direction(self) -> str:
        return self._direction

    @property
    def vs_prev(self) -> float | None:
        return None  # filled from market_context vix_vs_prev if available


_vix_tracker = _VIXTracker()


class _VolEnvelopeAndSectorForState(NamedTuple):
    vol_ctx: MarketVolContextV1
    vol_envelope: dict
    level_density: dict
    sector_strength: dict
    index_strength: dict
    spy_strength: dict
    iwm_deep: dict


def _vol_envelope_and_sector_for_state(
    ticker: str,
    spot_f: float,
    atr,
    walls: list,
    mkt_ctx,
    cache_key,
) -> _VolEnvelopeAndSectorForState:
    """RC-REHAB-1 (Phase 4, _fetch_state decomposition, sixteenth slice): the Volatility
    Envelope, Level Density, and Sector Strength phase, extracted verbatim.

    vol_ctx's own computation (VIX tracker tick, MarketVolContextV1 construction,
    record_market_vol_observation) is DELIBERATELY kept OUTSIDE the try/except that
    wraps envelope/density/sector-strength/iwm-deep, exactly as the original inline
    code did: vol_ctx must be bound on every path that reaches build_market_state /
    the persistence tail / ms_dict -- a swallowed envelope exception must degrade
    envelope fields only, never unbind the vol context (a NameError there would break
    the whole serve cycle)."""
    import server as _srv

    vol_envelope: dict = {}
    level_density: dict = {}
    sector_strength: dict = {}
    index_strength: dict = {}
    spy_strength: dict = {}
    iwm_deep: dict = {}

    vol_prev_published_vix = _srv._state_cache.get(cache_key, {}).get("vix")
    vol_vix_now = None
    if getattr(mkt_ctx, "vix", None) is not None:
        try:
            vol_vix_now = float(mkt_ctx.vix)
            _vix_tracker.tick(vol_vix_now)
        except (TypeError, ValueError):
            vol_vix_now = None
    vol_ctx = MarketVolContextV1(
        market_iv_level=vol_vix_now,
        market_iv_change=(
            round(vol_vix_now - float(vol_prev_published_vix), 4)
            if vol_vix_now is not None and vol_prev_published_vix is not None
            else None
        ),
        market_iv_direction=(_vix_tracker.direction if vol_vix_now is not None else None),
        quality_status=("VALID" if vol_vix_now is not None else "UNAVAILABLE"),
        as_of_ts=time.time(),
    )
    record_market_vol_observation(mkt_ctx, vol_ctx)
    try:
        vol_envelope = compute_volatility_envelope(spot_f, atr)

        # Build levels dict for density check
        # RC-432: density is a live congestion read. It must count the SAME terrain-bound
        # walls and terrain flip the KL table paints.
        all_levels: dict = {}
        t_dens = terrain_loop.terrain_cache_get(ticker) or {}
        dens_fresh = bool(t_dens) and not t_dens.get("levels_stale")
        if dens_fresh and t_dens.get("absolute_gamma_strike") is not None:
            all_levels["absolute_gamma_strike"] = float(t_dens["absolute_gamma_strike"])
        w0 = walls[0] if walls else None
        if w0 is not None:
            for dn, attr_name in (
                ("call_gamma_wall", "call_gamma_wall"),
                ("put_gamma_wall", "put_gamma_wall"),
                ("call_delta_wall", "call_delta_wall"),
                ("put_delta_wall", "put_delta_wall"),
            ):
                dv = getattr(w0, attr_name, None)
                if dv is not None:
                    all_levels[dn] = float(dv)
        if dens_fresh and t_dens.get("gamma_flip") is not None:
            all_levels["gamma_flip"] = float(t_dens["gamma_flip"])
        # RC-433 / F06: density counts the SAME EM band KL paints (terrain IV_SIGMA_1D =
        # spot ± implied_1d_move.points).
        if dens_fresh:
            em_move = t_dens.get("implied_1d_move") or {}
            em_pts = em_move.get("points")
            em_spot = t_dens.get("spot")
            if em_pts is not None and em_spot is not None:
                all_levels["em_upper"] = float(em_spot) + float(em_pts)
                all_levels["em_lower"] = float(em_spot) - float(em_pts)
        level_density = compute_level_density(all_levels, spot_f)

        # Sector strength — 3 groups
        # Group 1: Indices (SPY, QQQ, IWM)
        idx_data = {}
        for ik, ig in [('SPY', mkt_ctx.spy_chg_pct), ('QQQ', mkt_ctx.qqq_chg_pct), ('IWM', mkt_ctx.iwm_chg_pct)]:
            if ig is not None: idx_data[ik] = float(ig)
        index_strength = compute_sector_strength(idx_data)

        # Group 2: SPY top holdings (from mkt_ctx.constituents)
        spy_holdings = {}
        for cq in getattr(mkt_ctx, 'constituents', []):  # caps-ok: market_context.MarketContextV1.constituents is a dataclass field with default_factory=list -- always present, default never fires
            sym = getattr(cq, 'symbol', '').upper()  # caps-ok: ConstituentQuote.symbol is a required (non-Optional, no default) dataclass field -- always present, default never fires
            chg = getattr(cq, 'chg_pct', None)
            if sym and chg is not None:
                spy_holdings[sym] = float(chg)
        spy_strength = compute_sector_strength(spy_holdings)

        # Group 3: IWM sector proxies (from mkt_ctx.iwm_sectors)
        sector_data = {}
        for sq in getattr(mkt_ctx, 'iwm_sectors', []):  # caps-ok: market_context.MarketContextV1.iwm_sectors is a dataclass field with default_factory=list -- always present, default never fires
            sym = getattr(sq, 'symbol', '').upper()  # caps-ok: SectorQuote.symbol is a required (non-Optional, no default) dataclass field -- always present, default never fires
            chg = getattr(sq, 'chg_pct', None)
            if sym and chg is not None:
                sector_data[sym] = float(chg)
        sector_strength = compute_sector_strength(sector_data)

        vix_dir_for_confluence = vol_ctx.market_iv_direction
        iwm_deep = compute_iwm_confluence(
            spy_chg=mkt_ctx.spy_chg_pct,
            qqq_chg=mkt_ctx.qqq_chg_pct,
            iwm_chg=mkt_ctx.iwm_chg_pct,
            kre_chg=sector_data.get('KRE'),
            xbi_chg=sector_data.get('XBI'),
            psci_chg=sector_data.get('PSCI'),
            xrt_chg=sector_data.get('XRT'),
            vix_level=vol_ctx.market_iv_level,
            vix_direction=vix_dir_for_confluence,
        )
    except Exception as e:
        log.debug(f"Envelope/density/sector calc: {e}")

    return _VolEnvelopeAndSectorForState(
        vol_ctx=vol_ctx,
        vol_envelope=vol_envelope,
        level_density=level_density,
        sector_strength=sector_strength,
        index_strength=index_strength,
        spy_strength=spy_strength,
        iwm_deep=iwm_deep,
    )
