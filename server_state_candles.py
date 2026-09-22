"""Candle direction/volume + post-build sweep-score phases of _fetch_state (server.py),
extracted (RC-REHAB-1, 2026-09-22). Second real module-level slice of the _fetch_state
decomposition, alongside server_state_volatility.py -- see that module's own docstring
for why this decomposition exists and what the prior ("Phase 4") pass got wrong.

MONKEYPATCH/RUNTIME-STATE NOTE: _candle_direction_for_state and _candle_volume_for_state
both need server's in-memory 1-minute candle accumulator (server._candles_1m, a
singleton, not a pure value). Like server_state_volatility.py's
_volatility_signals_for_state, these keep their exact existing signatures (both already
have dedicated test files patching this dependency) and reach it via a lazy `import
server` at call time, matching the same pattern already established and verified in this
session's db.py decomposition. No circularity: server.py imports this module at its own
top level; this module only imports server.py inside function bodies.

compute_sweep_score (math_exposure) and safe_get_price_history (schwab_client) are bound-
name imports at this module's own top -- NOT runtime state, so no lazy access needed for
them. safe_get_price_history is ALSO still imported directly in server.py itself
(_exposures_for_state, which stayed there, uses it too) -- both imports point at the same
schwab_client function; there is no duplicate implementation, just two legitimate
importers of one source.
"""
from __future__ import annotations

from typing import NamedTuple, Optional

from math_exposure import classify_direction as _classify_direction, compute_sweep_score
from schwab_client import safe_get_price_history

import logging

log = logging.getLogger(__name__)


class _CandleDirectionForState(NamedTuple):
    candle_dir: Optional[str]
    candle_body: Optional[float]
    c_open: Optional[float]
    c_high: Optional[float]
    c_low: Optional[float]
    c_close: Optional[float]
    c_range: Optional[float]


def _candle_direction_for_state(ticker: str) -> _CandleDirectionForState:
    """RC-REHAB-1 (Phase 4, _fetch_state decomposition, fifth slice): the Candle
    Direction + Body phase, extracted verbatim. Reads the last COMPLETED 1m bar (not a
    30s tick delta) to classify bar direction and OHLC/range.

    NOTE for anyone extracting a LATER phase near this one: _fetch_state reassigns
    c_open/c_high/c_low/c_close/c_range again further down its own body, from the
    forming/live bar under a different branch -- this function only ever produces the
    FIRST assignment (from the last completed bar), exactly as the original inline block
    did. That later reassignment is untouched by this extraction.

    RC-REHAB-1 (2026-09-22, module extraction): moved from server.py into its own file.
    Behavior unchanged; see this module's own docstring for why it still reaches into
    server.py at call time for _candles_1m.
    """
    import server as _srv

    candle_dir: Optional[str] = None
    candle_body: Optional[float] = None
    c_open = c_high = c_low = c_close = None
    c_range: Optional[float] = None
    completed_bars_now = _srv._candles_1m.get_bars(ticker)
    if completed_bars_now:
        lb = completed_bars_now[-1]
        lb_open  = lb.open
        lb_high  = lb.high
        lb_low   = lb.low
        lb_close = lb.close
        try:
            if lb_open is not None:
                c_open = float(lb_open)
            if lb_high is not None:
                c_high = float(lb_high)
            if lb_low is not None:
                c_low = float(lb_low)
            if lb_close is not None:
                c_close = float(lb_close)
            if c_high is not None and c_low is not None:
                c_range = round(c_high - c_low, 4)
        except (TypeError, ValueError):
            pass
        if lb_open and lb_close and float(lb_open) > 0:
            bar_move    = round(float(lb_close) - float(lb_open), 4)
            candle_dir  = _classify_direction(bar_move, float(lb_open))
            candle_body = abs(bar_move)
    return _CandleDirectionForState(
        candle_dir=candle_dir,
        candle_body=candle_body,
        c_open=c_open,
        c_high=c_high,
        c_low=c_low,
        c_close=c_close,
        c_range=c_range,
    )


def _candle_volume_for_state(ticker: str, client) -> Optional[float]:
    """RC-REHAB-1 (Phase 4, _fetch_state decomposition, fifteenth slice): the Candle
    Volume Resolution phase, extracted verbatim.

    A pre-existing quirk preserved, not fixed: the original inline banner comment says
    "priority: 1) Price history primary, 2) accumulator secondary", but the actual code
    order tries the accumulator FIRST (this function's first block), price history SECOND
    (only when the accumulator had no usable volume), then re-checks the accumulator a
    THIRD time with the IDENTICAL condition as the first check -- since `completed_for_vol`
    never changes between the first and third check, that third block is unreachable dead
    code whenever the first block already failed. Preserved verbatim for behavior fidelity.

    RC-REHAB-1 (2026-09-22, module extraction): moved from server.py into its own file.
    Behavior unchanged; see this module's own docstring for why it still reaches into
    server.py at call time for _candles_1m.
    """
    import server as _srv

    completed_for_vol = _srv._candles_1m.get_bars(ticker)

    c_vol = None
    if completed_for_vol:
        raw_vol = getattr(completed_for_vol[-1], "volume", None)
        if raw_vol is not None:
            try:
                v = float(raw_vol)
                if v > 0:
                    c_vol = v
            except (TypeError, ValueError):
                pass
    # Price history fetch only when accumulator has no usable volume (avoid duplicate Schwab RTT).
    if c_vol is None and ticker:
        try:
            resp_ph = safe_get_price_history(client, ticker, frequency_minutes=1, period_days=1)
            if (not resp_ph or resp_ph.status_code != 200 or not resp_ph.json().get("candles")) and ticker.startswith("$"):
                resp_ph = safe_get_price_history(client, ticker[1:], frequency_minutes=1, period_days=1)
            if resp_ph and resp_ph.status_code == 200:
                payload_ph = resp_ph.json()
                if "candles" not in payload_ph:
                    raise ValueError(
                        f"Schwab pricehistory response missing 'candles' key (status={resp_ph.status_code})"
                    )
                ph_candles = payload_ph["candles"]
                if ph_candles and completed_for_vol:
                    last_ts = getattr(completed_for_vol[-1], "ts", None)

                    def _ph_candle_ts_sec(bar: dict) -> Optional[float]:
                        dt = bar.get("datetime")
                        if dt is None:
                            return None
                        try:
                            dt_f = float(dt)
                        except (TypeError, ValueError):
                            return None
                        if dt_f <= 0:
                            return None
                        return dt_f / 1000.0 if dt_f > 1e10 else dt_f

                    timed = [b for b in ph_candles if _ph_candle_ts_sec(b) is not None]
                    if last_ts is not None and timed:
                        best = min(timed, key=lambda b: abs(_ph_candle_ts_sec(b) - last_ts))
                    elif timed:
                        best = timed[-1]
                    else:
                        best = ph_candles[-1]
                    ph_vol = best.get("volume")
                    if ph_vol is not None:
                        try:
                            v = float(ph_vol)
                            if v > 0:
                                c_vol = v
                        except (TypeError, ValueError):
                            pass
                if c_vol is None and ph_candles:
                    v = ph_candles[-1].get("volume")
                    if v is not None:
                        try:
                            vf = float(v)
                            if vf > 0:
                                c_vol = vf
                        except (TypeError, ValueError):
                            pass
        except Exception as _ph_e:
            log.debug(f"Price history volume for {ticker}: {_ph_e}")
    # 2. Accumulator secondary — WebSocket TOTAL_VOLUME or REST quote delta
    if c_vol is None and completed_for_vol:
        raw_vol = getattr(completed_for_vol[-1], "volume", None)
        if raw_vol is not None:
            try:
                v = float(raw_vol)
                if v > 0:
                    c_vol = v
            except (TypeError, ValueError):
                pass
    return c_vol


def _post_build_sweep_score_for_state(ms, atr, candle_body, void_factor) -> dict:
    """RC-REHAB-1 (Phase 4, _fetch_state decomposition, seventeenth slice): the Sweep
    Score phase, extracted verbatim. Must run AFTER build_market_state -- ms.
    nearest_above_dist / ms.nearest_below_dist are populated by build_market_state
    from walls + price_levels, and are not available any earlier (this is the fix for
    FIND-SERVER-SWEEP-DEAD-FEED: a defunct dir()-membership guard on the name ms used
    to run this computation before ms existed at all, always evaluating False and
    silently degrading sweep_score to empty on every tick -- see
    tests/test_server_sweep_score_post_build_market_state.py).

    Fails closed to {} (the pre-initialized default the caller already holds) on any
    exception, logged at debug -- never raises.

    RC-REHAB-1 (2026-09-22, module extraction): moved from server.py into its own file,
    verbatim -- zero server.py coupling to begin with.
    """
    sweep_score: dict = {}
    try:
        nearest_wall_dist = None
        for wname in ("nearest_above_dist", "nearest_below_dist"):
            wd = getattr(ms, wname, None)
            if wd is None:
                continue
            try:
                wd_abs = abs(float(wd))
            except (TypeError, ValueError):
                continue
            if nearest_wall_dist is None or wd_abs < nearest_wall_dist:
                nearest_wall_dist = wd_abs
        momentum = 0.0
        if atr and atr > 0 and candle_body:
            momentum = min(1.0, abs(candle_body) / atr)
        sweep_score = compute_sweep_score(nearest_wall_dist, void_factor, momentum) or {}
    except Exception as e:
        log.debug("sweep_score post build_market_state: %s", e)
    return sweep_score
