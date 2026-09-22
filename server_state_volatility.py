"""Volatility-signals phase of _fetch_state (server.py), extracted (RC-REHAB-1, 2026-09-22).

IV skew, realized vol, ATR, IV rank/percentile, and the GARCH volatility forecast that
consumes them — pure computation over parameters passed in, plus one PCR read-through.
This is the first real module-level slice of server.py's _fetch_state decomposition: the
prior pass (Phase 4, "thirteenth slice") only pulled this logic into a same-file named
function, which left server.py's actual size and coupling unchanged. This module has zero
server.py coupling for the functions themselves.

MONKEYPATCH/RUNTIME-STATE NOTE: _volatility_signals_for_state needs three pieces of live
server-process state -- the in-memory 1-minute candle accumulator (server._candles_1m,
a singleton object, not a pure value) and two boot-time-anchored warmup helpers
(server._atr_warmup_active/_seconds_since_boot, which read server._l1_diag_start_mono).
These are genuine runtime infrastructure, not computation, and moving them here would just
relocate the coupling rather than remove it. Rather than widen this function's signature
(it already has 10+ existing call sites across tests/test_fetch_state_volatility_signals_
phase_v1.py, tests/test_card_wiring_transport_locks.py, and others, all passing positional
args to the current 6-parameter shape -- changing it would force updating every one of them
for a purity gain with no behavior change), this function does a lazy `import server` at
call time and reads them via `server.<name>`, matching the exact pattern already
established and verified in this repo's db.py decomposition (db_snapshots.py's lazy
`import db` for genuinely monkeypatch-sensitive/must-stay-current values). No circularity:
server.py imports this module at its own top level; this module only imports server.py
inside the function body, which executes after both modules have finished loading.
"""
from __future__ import annotations

from typing import NamedTuple, Optional

from math_exposure import (
    compute_iv_skew,
    compute_realized_vol,
    compute_atr,
    compute_iv_rank,
    compute_iv_percentile,
    compute_garch_forecast,
    blend_garch_sigma,
)
from timeframe_config import CANONICAL_TIMEFRAME

import logging

log = logging.getLogger(__name__)


def _garch_horizon_bars() -> int:
    from governed_stack_contract import horizon_slug_to_mc_bars
    from ml_horizon import ALL_GOVERNED_HORIZONS

    return max(horizon_slug_to_mc_bars(s) for s in ALL_GOVERNED_HORIZONS)


GARCH_HORIZON_BARS: int = _garch_horizon_bars()   # 60 bars = the longest governed horizon

# IV history lookback for IV rank / percentile
IV_HISTORY_LOOKBACK: int = 5000   # max rows pulled from DB for IV rank calc

#: RC-REHAB-1 (2026-09-22): moved from server.py -- server.py's own ATR_WARMUP_HORIZON_SEC
#: (which _atr_warmup_active still uses, staying in server.py as runtime state) imports
#: this back: `from server_state_volatility import ATR_MIN_BARS`.
ATR_MIN_BARS: int = 16


class _VolatilitySignalsForState(NamedTuple):
    iv_skew: dict
    realized_vol: Optional[float]
    atr: Optional[float]
    iv_rank: Optional[float]
    iv_percentile: Optional[float]
    closes: Optional[list]


def _volatility_signals_for_state(
    ticker: str,
    contracts_use: list,
    spot_f: float,
    atm_iv: Optional[float],
    ed_db,
    tick_ts,
) -> _VolatilitySignalsForState:
    """RC-REHAB-1 (Phase 4, _fetch_state decomposition, fourth slice): the Volatility
    Signals phase (IV skew, realized vol, ATR, IV rank/percentile), extracted verbatim,
    including its own ATR-warmup diagnostic logging (same banner scope in the original).

    Bug fixed as part of this extraction, not a separate change: the original inline code
    pre-initialized every OTHER output (`_iv_skew = {}`, `_realized_vol = None`, `_atr =
    None`, `_iv_rank = None`, `_iv_percentile = None`, `_bars = None`) but never
    `_closes = None` -- so on a cold ticker (`_bars` empty, the exact ATR-warmup case this
    same block already logs specially), `_closes` was never assigned. The immediately
    following GARCH phase referenced `_closes` as a bare call argument
    (`_garch_sigma_bars_for_state(_closes, ...)`), evaluated in the CALLER's frame before
    the callee's own try/except could ever run -- so as of the GARCH extraction (the first
    slice of this decomposition), that reference raised an uncaught NameError out of
    _fetch_state on every cold ticker, a live regression this present extraction closes by
    giving `closes` the same explicit `None` initializer its five siblings already had.
    Before the GARCH extraction, the equivalent reference lived INSIDE the GARCH phase's
    own try/except and was silently swallowed to a debug log with the observable outcome
    already `_garch_sigma_bars is None` -- this fix restores exactly that outcome, just
    without the (already unhelpfully-worded) debug log line.

    RC-REHAB-1 (2026-09-22, module extraction): moved from server.py into its own file.
    Behavior unchanged; see this module's own docstring for why it still reaches into
    server.py at call time for _candles_1m/_atr_warmup_active/_seconds_since_boot.
    """
    import server as _srv

    iv_skew: dict = {}
    realized_vol: Optional[float] = None
    atr: Optional[float] = None
    iv_rank: Optional[float] = None
    iv_percentile: Optional[float] = None
    bars = None
    closes: Optional[list] = None
    try:
        iv_skew = compute_iv_skew(contracts_use, spot_f)
        # Realized vol + ATR from canonical (1m) candle bars
        bars = _srv._candles_1m.get_bars(ticker)
        if bars:
            closes = [float(b.close) for b in bars if b.close is not None]
            if closes:
                realized_vol = compute_realized_vol(closes, bar_minutes=1.0)
            atr = compute_atr(bars)
        # IV Rank/Percentile from DB historical iv_level
        # Burndown (2026-07-05): narrow iv_level projection — the full-width
        # get_recent_snapshots read (5,000 rows x 200+ cols incl. chain blobs)
        # was ~all of the vol_flow_signals stage (py-spy 1,258/3,062 samples).
        # Same row window/order/as-of as before; values identical.
        # Schwab CSV authority checked: yes
        # CSV row(s): NO_SCHWAB_EQUIVALENT — persisted-snapshot SQLite read
        #   (iv_level history for rank/percentile); no market field derivation,
        #   emission, or actionability logic changed.
        # Derived-field disposition: none required.
        # All consumers checked: yes — _iv_history filter semantics unchanged.
        # SCHWAB_CSV_CHECKED
        if atm_iv and ed_db and tick_ts is not None:
            try:
                iv_hist_vals = ed_db.get_recent_iv_levels(
                    ticker,
                    CANONICAL_TIMEFRAME,
                    n=IV_HISTORY_LOOKBACK,
                    as_of_ts_utc=tick_ts,
                )
                iv_history = [
                    float(v) for v in iv_hist_vals
                    if v is not None and float(v) > 0
                ]
                if iv_history:
                    iv_rank = compute_iv_rank(atm_iv, iv_history)
                    iv_percentile = compute_iv_percentile(atm_iv, iv_history)
            except Exception as e:
                log.debug(
                    "IV rank/percentile history load failed ticker=%s: %s",
                    ticker,
                    e,
                    exc_info=True,
                )
    except Exception as e:
        log.debug(f"Volatility signals calc: {e}")
    # RC-236 (same calibration law as the tier-1 lock waits): a bar deficit during ACCUMULATOR
    # WARMUP is the designed state — the in-memory series re-seeds from zero on every restart
    # and cannot hold 16 one-minute bars until 16 minutes of wall clock have passed. Logging
    # that at WARNING makes the quiet gate fail for doing exactly what it must do, and trains
    # the operator to ignore the channel. Past the warmup horizon the SAME deficit is genuine
    # starvation and keeps its WARNING; the deficit is always logged, only the severity moves.
    if atr is None:
        warm = _srv._atr_warmup_active()
        msg = (f"ATR NULL for {ticker}: only {len(bars)} bars, need {ATR_MIN_BARS}"
                if bars else f"ATR NULL for {ticker}: no bars, need {ATR_MIN_BARS}")
        if warm:
            log.info("%s (accumulator warmup, %.0fs since boot)", msg, _srv._seconds_since_boot())
        else:
            log.warning(msg)
    return _VolatilitySignalsForState(
        iv_skew=iv_skew,
        realized_vol=realized_vol,
        atr=atr,
        iv_rank=iv_rank,
        iv_percentile=iv_percentile,
        closes=closes,
    )


def _garch_sigma_bars_for_state(
    closes: list[float] | None,
    atm_iv: Optional[float],
    realized_vol: Optional[float],
    spot_f: float,
) -> Optional[list]:
    """RC-REHAB-1 (Phase 4, _fetch_state decomposition, first slice): the GARCH Volatility
    Forecast phase, extracted verbatim from _fetch_state with an explicit input/output
    contract instead of reading/writing the enclosing function's locals. Behavior is
    UNCHANGED, including the pre-existing quirk this phase's own comment already flags:
    the RC-334 bar-mismatch RuntimeError is deliberately loud in wording ("must fail
    loudly") but is still caught by this same try/except and only debug-logged, exactly
    as it was inline -- not "fixed" here, since that would be an unreviewed behavior
    change smuggled into a refactor, not a decomposition.

    Returns per-bar sigma (monte_carlo.BAR_MINUTES units) or None on insufficient data,
    a missing GARCH result, or any computation failure.

    RC-REHAB-1 (2026-09-22, module extraction): moved from server.py into its own file,
    verbatim -- zero server.py coupling to begin with.
    """
    try:
        # RC-REHAB-1 (route-extraction/decomposition audit fix): this guard originally
        # sat BEFORE the try (as `if not closes or len(closes) <= 20: return None`).
        # The pre-existing inline code had it INSIDE the try (`if _closes and
        # len(_closes) > 20:`), so an exception evaluating the predicate itself (e.g. a
        # `closes` whose __bool__/__len__ raised) was swallowed to this function's fail-
        # closed None, not propagated. Moved back inside to restore that exact coverage
        # -- currently unreachable in practice since the caller guarantees closes is
        # None-or-list, but the extraction claimed byte-for-byte fidelity and this was
        # the one place it wasn't.
        if not closes or len(closes) <= 20:
            return None
        _garch_raw = compute_garch_forecast(closes, horizon=GARCH_HORIZON_BARS)
        if not _garch_raw:
            return None
        from volatility_regime import vol_percent_to_decimal

        _iv_dec = vol_percent_to_decimal(atm_iv)
        _rv_dec = vol_percent_to_decimal(realized_vol)
        # RC-334: closes are ONE-MINUTE closes — _candles_1m.get_bars above, and the
        # realized-vol call on this same list passes bar_minutes=1.0 — so the GARCH
        # sigmas are per-minute and the IV/RV terms must be de-annualized to the same
        # minute. Monte Carlo then consumes this list DIRECTLY as per-bar sigma at
        # monte_carlo.BAR_MINUTES, so a third party has to agree too. The interval is
        # stated from the DATA, not borrowed from MC's constant, and the agreement is
        # asserted: if MC's bar ever moves, this must fail loudly rather than keep
        # feeding it minute sigmas under a five-minute name.
        from monte_carlo import BAR_MINUTES as _MC_BAR_MINUTES

        _GARCH_BAR_MINUTES = 1.0          # _candles_1m is one-minute by construction
        if float(_MC_BAR_MINUTES) != _GARCH_BAR_MINUTES:
            raise RuntimeError(
                f"GARCH/Monte-Carlo bar mismatch: sigmas built on "
                f"{_GARCH_BAR_MINUTES}-minute closes but monte_carlo.BAR_MINUTES is "
                f"{_MC_BAR_MINUTES}. MC consumes these as per-bar sigma, so the "
                f"units must match (RC-334).")
        return blend_garch_sigma(
            _garch_raw, _iv_dec, _rv_dec, spot_f,
            bar_minutes=_GARCH_BAR_MINUTES,
        )
    except Exception as e:
        log.debug(f"GARCH forecast calc: {e}")
        return None


def _pcr_val_for_state(totals: list) -> Optional[float]:
    """RC-REHAB-1 (Phase 4, _fetch_state decomposition, second slice): the PCR (put/call
    ratio) phase, extracted verbatim. Reads the open-interest-based PCR off the first
    per-strike-bucket total row (`build_totals_rows`'s own `pcr_oi` field, computed by
    math_exposure_core) -- no computation of its own, purely a read-through. Returns
    None when `totals` is empty or the row has no `pcr_oi` value.

    RC-REHAB-1 (2026-09-22, module extraction): moved from server.py into its own file,
    verbatim -- zero server.py coupling to begin with.
    """
    if not totals:
        return None
    v = getattr(totals[0], "pcr_oi", None)
    return float(v) if v is not None else None
