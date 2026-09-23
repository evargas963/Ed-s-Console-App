"""Exposures phase of _fetch_state (server.py), extracted (RC-REHAB-1, 2026-09-23).
Twenty-third real module-level slice of the _fetch_state decomposition, alongside
server_state_volatility.py, server_state_candles.py, server_state_signals.py,
server_state_order_flow.py, server_state_persistence_tail.py,
server_state_predictive_positioning.py, and server_state_vol_envelope_sector.py --
see server_state_volatility.py's own docstring for why this decomposition exists.

_exposures_for_state and its private return type (_ExposuresForState, a NamedTuple
with no external reader confirmed by a repo-wide search before moving) move together
as one unit, along with the private CANDLE_RESEED_GAP_SECONDS and EXPOSURE_WINDOWS
constants -- confirmed the ONLY reader of both, anywhere in server.py, before moving.

MONKEYPATCH/RUNTIME-STATE NOTE: this function calls 8 server.py-local names that have
OTHER callers elsewhere in server.py (confirmed before moving, so they correctly stay
in server.py rather than moving too): _candles_1m/_candles_5m (candle accumulator
singletons, 13/5 other occurrences respectively), get_client (defined in server.py,
27 other occurrences), _log_only_inline_leaf_fetches/_get_priority_leaf_executor/
_get_recompute_leaf_executor (each has a second call site in _fetch_state's own
Step-2 body), and terrain_cache_get. Reached via the same lazy `import server` pattern
proven in prior slices.

compute_exposures_by_strike/pick_net_gex_peak_strike/build_summary_rows/
build_walls_rows/build_totals_rows/safe_get_price_history (math_exposure.py /
schwab_client.py) are re-imported here directly from their own modules -- none of
this is server.py-specific logic, and none have an external `from server import`
caller (checked repo-wide before moving). safe_get_price_history's server.py
top-level import was ALSO removed: its only other apparent call site (the
enrollment-seed path) already does its own local `from schwab_client import
safe_get_price_history`, shadowing the module-level binding, so that top-level
import had no real caller left once this function moved -- caught by ruff -F401,
not assumed. key_level_strikes_with_gamma and consensus_walls_bind_terrain_ssot
were already lazily imported inline inside
the function body in the original code and stay that way, unchanged.
"""
from __future__ import annotations

import logging
import time
from typing import Any, NamedTuple, Optional

from math_exposure import (
    build_summary_rows,
    build_totals_rows,
    build_walls_rows,
    compute_exposures_by_strike,
    pick_net_gex_peak_strike,
)
from schwab_client import safe_get_price_history
import terrain_loop

log = logging.getLogger(__name__)

# Re-seed the in-memory 1m grid from Schwab pricehistory (canonical OHLCV leaf
# pricehistory.candles[]) whenever the last completed bar is older than this gap.
# Root cause (2026-06-11): seeding ran once per server lifetime, so background-logged
# tickers (visited ~1x/15min) built ~6%-density tick grids -- fill_outcomes could not
# find forward bars at +1/+5/+15/+60m and the daily scoreboard never scored them.
CANDLE_RESEED_GAP_SECONDS: float = 180.0  # 3 missed canonical bars → grid is stale
EXPOSURE_WINDOWS: list = [5, 10, 15, 20]   # window sizes passed to build_*_rows


class _ExposuresForState(NamedTuple):
    spot_f: float
    tick_ts: Optional[float]
    bars_5m_count: int
    bars_1m_count: int
    exposures: dict
    diag: Any
    cons_strikes: list
    gamma_strikes: list
    institutional_pin: Optional[float]
    rows: list
    walls: list
    totals: list
    client: Any


def _exposures_for_state(
    ticker: str,
    client,
    spot,
    contracts_use: list,
    parsed_quote_time,
    parsed_trade_time,
    total_vol,
    log_only: bool,
    chain_priority: bool,
) -> _ExposuresForState:
    """RC-REHAB-1 (Phase 4, _fetch_state decomposition, ninth slice): the Exposures phase
    (candle tick feed + seed-from-history + GEX/DEX/vanna by strike + summary/wall/totals
    rows), extracted verbatim from _fetch_state's body. Callers must have already handled
    the `spot is None` guard -- this function assumes a real, non-None spot.

    `client` is returned rather than only consumed: the original inline code rebinds
    _fetch_state's own `client` local via `client = get_client()` inside the candle-seed
    try block (get_client() is a cached singleton in practice, so this is normally a
    no-op, but the rebinding is preserved exactly so _fetch_state's downstream `client`
    reads -- e.g. the Price Levels phase -- see the identical value the original inline
    code would have produced).
    """
    import server as _srv

    spot_f = float(spot)

    # Feed tick into candle accumulators
    tick_ts = parsed_quote_time or parsed_trade_time

    # Seed candles from Schwab price history when the canonical 1m grid is stale —
    # first visit OR a gap since the last completed bar (background-logged tickers
    # are polled ~1×/15min; tick-built bars alone leave the outcome grid ~94% empty).
    # Canonical (1m) drives snapshot/state; 5m remains derived context.
    _seed_ref_ts = float(tick_ts) if tick_ts is not None else time.time()
    if _srv._candles_1m.grid_stale(ticker, _seed_ref_ts, CANDLE_RESEED_GAP_SECONDS):
        def _seed_candles(freq_min: int) -> None:
            resp = safe_get_price_history(client, ticker, frequency_minutes=freq_min, period_days=1)
            if resp and resp.status_code == 200:
                payload = resp.json()
                if "candles" not in payload:
                    raise ValueError(
                        f"Schwab pricehistory response missing 'candles' key (status={resp.status_code})"
                    )
                raw_bars = payload["candles"]
                if freq_min == 5:
                    _srv._candles_5m.seed(ticker, raw_bars)
                    log.info("Seeded %s 5m candles: %d bars from price history", ticker, len(raw_bars))
                else:
                    _srv._candles_1m.seed(ticker, raw_bars)
                    log.info("Seeded %s 1m candles: %d bars from price history", ticker, len(raw_bars))

        try:
            client = _srv.get_client()
            if _srv._log_only_inline_leaf_fetches(log_only):
                # OPERATOR_CARD_PRIORITY_ISOLATION_V1_STEP_1: background
                # log_only seeds run sequentially inline — identical calls,
                # identical consumption, no shared-pool occupancy.
                _seed_candles(5)
                _seed_candles(1)
            else:
                # UI-MAXIMIZE: parallel seed — must NOT use _analytics_executor (same pool as
                # _fetch_state worker); nested submit+.result() deadlocks all Tier C jobs.
                # OPERATOR_CARD_PRIORITY_ISOLATION_V1_STEP_2: dedicated leaf pool.
                # UI_05 residual: priority recomputes seed on the priority
                # leaf lane (same selection as the chain/quote leg).
                _seed_pool = (
                    _srv._get_priority_leaf_executor()
                    if chain_priority
                    else _srv._get_recompute_leaf_executor()
                )
                _f5 = _seed_pool.submit(_seed_candles, 5)
                _f1 = _seed_pool.submit(_seed_candles, 1)
                _f5.result(timeout=45)
                _f1.result(timeout=45)
        except Exception as e:
            log.debug("Candle seeding failed for %s: %s", ticker, e)

    if tick_ts is not None:
        _srv._candles_5m.tick(ticker, spot_f, tick_ts, total_volume=total_vol)
        _srv._candles_1m.tick(ticker, spot_f, tick_ts, total_volume=total_vol)

    bars_5m_count = len(_srv._candles_5m.get_bars(ticker))
    bars_1m_count = len(_srv._candles_1m.get_bars(ticker))
    log.info(f"Candles: {ticker} 5m={bars_5m_count} bars, 1m={bars_1m_count} bars")

    exposures, diag = compute_exposures_by_strike(contracts_use, spot=spot_f, require_oi=True)
    from math_exposure_core import key_level_strikes_with_gamma
    cons_strikes = sorted(float(k) for k in exposures.keys())
    gamma_strikes = key_level_strikes_with_gamma(exposures) or cons_strikes
    institutional_pin = (
        pick_net_gex_peak_strike(exposures, gamma_strikes, institutional=True)
        if gamma_strikes
        else None
    )

    rows = build_summary_rows(exposures, spot_f, windows=EXPOSURE_WINDOWS)
    walls = build_walls_rows(exposures, spot_f)
    # RC-420: CONSENSUS gamma/delta wall strikes are terrain SSOT (wide chain).
    # Selected-expiry analytics must not occupy walls[0] while kl_* paints terrain.
    from math_levels import consensus_walls_bind_terrain_ssot
    walls = consensus_walls_bind_terrain_ssot(walls, terrain_loop.terrain_cache_get(ticker) or {})
    totals = build_totals_rows(exposures, spot_f, windows=EXPOSURE_WINDOWS, contracts_for_iv=contracts_use)

    return _ExposuresForState(
        spot_f=spot_f,
        tick_ts=tick_ts,
        bars_5m_count=bars_5m_count,
        bars_1m_count=bars_1m_count,
        exposures=exposures,
        diag=diag,
        cons_strikes=cons_strikes,
        gamma_strikes=gamma_strikes,
        institutional_pin=institutional_pin,
        rows=rows,
        walls=walls,
        totals=totals,
        client=client,
    )
