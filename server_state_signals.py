"""Expected-move, order-flow-signals, and charm phases of _fetch_state (server.py),
extracted (RC-REHAB-1, 2026-09-22). Third real module-level slice of the _fetch_state
decomposition, alongside server_state_volatility.py and server_state_candles.py -- see
server_state_volatility.py's own docstring for why this decomposition exists.

Unlike the first two slices, none of these three functions need server.py's own runtime
state (no _candles_1m, no terrain_cache_get, no module-level tracker singletons) --
confirmed by a full AST scan of every name each function references against server.py's
own top-level definitions, not just a fixed signal list (the first-pass scan that
classified the whole _fetch_state helper family missed this distinction for several
OTHER helpers still in server.py -- terrain_cache_get, canonical_price_level_snapshot,
_vix_tracker, _update_rest_cum_delta -- which is why those are NOT part of this slice;
see the mission memory for the corrected classification). All three here are pure
computation over their parameters plus module-level imports from math_exposure /
math_exposure_core / time_et / numeric_contract / math_volatility, so all three use
plain bound-name imports at this module's own top (or a scoped lazy import matching the
original inline code's own style, for compute_net_charm/charm_compute_unavailable_log_level
in _charm_for_state -- preserved verbatim, not changed by this extraction).
"""
from __future__ import annotations

from typing import NamedTuple, Optional

from math_exposure import (
    compute_expected_move_straddle,
    compute_expected_move_iv,
    compute_em_progress,
    compute_volume_oi_ratio,
    flow_imbalance_normalized_with_fallback,
    compute_smart_money_signal,
    compute_iv_model_spread,
    _f,
)

import logging

log = logging.getLogger(__name__)


class _ExpectedMoveForState(NamedTuple):
    em_straddle: dict
    em_iv: dict
    em_progress: dict
    em_up: Optional[float]
    em_lo: Optional[float]
    em_band_source: str
    kl_em_anchor: str
    mc_iv_level: Optional[float]
    mc_iv_source: str


def _expected_move_for_state(
    now_et_dt,
    price_levels,
    contracts_use: list,
    spot_f: float,
    atm_iv: Optional[float],
) -> _ExpectedMoveForState:
    """RC-REHAB-1 (Phase 4, _fetch_state decomposition, seventh slice): the Expected Move
    phase (ATM straddle + IV-based EM, progress, and the KL/MC anchor resolution), extracted
    verbatim. `em_band_source` is computed but has no downstream reader anywhere in
    server.py -- a pre-existing fact, not something narrowed by this extraction; kept in
    the return contract for behavior fidelity rather than silently dropped.

    RC-REHAB-1 (2026-09-22, module extraction): moved from server.py into its own file,
    verbatim -- zero server.py coupling to begin with.
    """
    em_straddle = {"straddle": None, "em_pts": None, "upper": None, "lower": None}
    em_iv = {"em_pts": None, "upper": None, "lower": None}
    em_progress = {
        "progress_pct": None,
        "breached": None,
        "direction": None,
        "severity": None,
    }
    em_up = None
    em_lo = None
    em_band_source = "unavailable"  # RC-345 / F06: which EM methodology produced the band
    from time_et import hours_until_session_close_et as _hours_until_close
    hours_rem = _hours_until_close(now_et_dt) or 0.0
    kl_em_anchor = "unavailable"
    mc_iv_level = None
    mc_iv_source = "unavailable"

    try:
        today_open = getattr(price_levels, "today_open", None)

        # ATM straddle: find ATM call + put mark from chain
        # single source: reject NaN via the finite reader (raw float() admitted NaN into
        # the strike set, corrupting sorting and the ATM-strike nearest-neighbour pick).
        from numeric_contract import float_finite_or_none as _fin
        all_strikes = sorted({
            sp
            for ct in contracts_use
            if (sp := _fin(ct.get("strikePrice"))) is not None
        })
        if all_strikes and spot_f > 0:
            atm_k = min(all_strikes, key=lambda k: abs(k - spot_f))
            atm_calls = [
                ct
                for ct in contracts_use
                if str(ct.get("putCall", "")).upper() == "CALL"  # caps-ok: ct is a live Schwab contract dict, not a guaranteed-shape object
                and (sp := _f(ct.get("strikePrice"))) is not None
                and abs(sp - atm_k) < 0.01
            ]
            atm_puts = [
                ct
                for ct in contracts_use
                if str(ct.get("putCall", "")).upper() == "PUT"  # caps-ok: ct is a live Schwab contract dict, not a guaranteed-shape object
                and (sp := _f(ct.get("strikePrice"))) is not None
                and abs(sp - atm_k) < 0.01
            ]
            c_mark = _f(atm_calls[0].get("mark")) if atm_calls else None
            p_mark = _f(atm_puts[0].get("mark")) if atm_puts else None

            if c_mark and p_mark and today_open:
                em_straddle = compute_expected_move_straddle(c_mark, p_mark, today_open)

        # IV-based EM (shrinks through the day)
        if atm_iv and atm_iv > 0 and spot_f > 0 and hours_rem > 0:
            em_iv = compute_expected_move_iv(spot_f, atm_iv, hours_rem)

        # EM progress (use straddle EM if available, fall back to IV) — no synthetic 6.5h session fill.
        # RC-345 / F06: the operator-facing EM band is ONE of two economically distinct
        # methodologies — STRADDLE_IMPLIED (market ATM straddle premium) or IV_MODEL
        # (spot x IV x sqrt(T)). Record WHICH produced the band so no consumer treats the
        # generic em_up/em_lo as method-agnostic or silently mistakes one for the other.
        if em_straddle.get("upper") is not None and em_straddle.get("lower") is not None:
            em_up, em_lo, em_band_source = (
                em_straddle.get("upper"), em_straddle.get("lower"), "STRADDLE_IMPLIED")
        elif em_iv.get("upper") is not None and em_iv.get("lower") is not None:
            em_up, em_lo, em_band_source = (
                em_iv.get("upper"), em_iv.get("lower"), "IV_MODEL")
        else:
            em_up, em_lo, em_band_source = None, None, "unavailable"
        if em_up and em_lo and today_open:
            em_progress = compute_em_progress(spot_f, today_open, em_up, em_lo)

        from math_volatility import resolve_kl_em_anchor, resolve_mc_iv_for_kl_em_anchor

        kl_em_anchor = resolve_kl_em_anchor(em_straddle, em_iv)
        mc_iv_level, mc_iv_source = resolve_mc_iv_for_kl_em_anchor(
            kl_em_anchor=kl_em_anchor,
            atm_iv=atm_iv,
            spot=spot_f,
            em_straddle=em_straddle,
            hours_remaining=hours_rem,
        )

    except Exception as e:
        log.warning(f"Expected move calc failed: {e}")

    return _ExpectedMoveForState(
        em_straddle=em_straddle,
        em_iv=em_iv,
        em_progress=em_progress,
        em_up=em_up,
        em_lo=em_lo,
        em_band_source=em_band_source,
        kl_em_anchor=kl_em_anchor,
        mc_iv_level=mc_iv_level,
        mc_iv_source=mc_iv_source,
    )


class _OrderFlowSignalsForState(NamedTuple):
    vol_oi_ratio: dict
    flow_imb_norm: Optional[float]
    flow_imb_source: str
    smart_money: dict
    iv_model_spread: dict


def _order_flow_signals_for_state(
    exposures: dict,
    spot_f: float,
    contracts_use: list,
) -> _OrderFlowSignalsForState:
    """RC-REHAB-1 (Phase 4, _fetch_state decomposition, third slice): the Order Flow
    Signals phase (option volume + bid/ask size), extracted verbatim. Four independent
    computations, each already delegated to its own module and each fail-closed to an
    empty/None default on its own exception -- one signal's failure must never take
    another down with it, exactly as the original inline try/except-per-call did.

    RC-REHAB-1 (2026-09-22, module extraction): moved from server.py into its own file,
    verbatim -- zero server.py coupling to begin with.
    """
    vol_oi_ratio: dict = {}
    smart_money: dict = {}
    iv_model_spread: dict = {}
    try:
        vol_oi_ratio = compute_volume_oi_ratio(exposures, spot_f)
    except Exception as e:
        log.debug(f"Order flow signals calc: {e}")
    # RC-345 / F11 residual: ONE computation for the served number AND its label.
    # The live path used to call compute_option_flow_imbalance independently for
    # flow_imbalance_label while persisting flow_imbalance_normalized_with_fallback.
    # MEASURED on current main: empty ATM book + call-heavy volume → number 0.6
    # (source=volume) beside label "balanced" (book-only zero). Label is now a
    # function of the same normalized value the wrapper returns.
    flow_imb_norm: Optional[float] = None
    flow_imb_source = "none"
    try:
        flow_imb_norm, flow_imb_source = flow_imbalance_normalized_with_fallback(exposures, spot_f)
    except Exception as e:
        log.warning(f"flow_imbalance (one-producer authority) failed: {e}")
    try:
        smart_money = compute_smart_money_signal(exposures, spot_f)
    except Exception as e:
        log.warning(f"smart_money_score failed: {e}")
    try:
        iv_model_spread = compute_iv_model_spread(contracts_use, spot_f)
    except Exception as e:
        log.debug(f"Order flow signals calc: {e}")
    return _OrderFlowSignalsForState(
        vol_oi_ratio=vol_oi_ratio,
        flow_imb_norm=flow_imb_norm,
        flow_imb_source=flow_imb_source,
        smart_money=smart_money,
        iv_model_spread=iv_model_spread,
    )


class _CharmForState(NamedTuple):
    charm_net: Optional[float]
    charm_dir: Optional[str]
    charm_toward: Optional[float]
    charm_mag: Optional[float]
    charm_drivers: list


def _charm_for_state(
    ticker: str,
    contracts_use: list,
    spot_f: float,
    selected_exp: Optional[str],
) -> _CharmForState:
    """RC-REHAB-1 (Phase 4, _fetch_state decomposition, eleventh slice): the Charm phase
    (dealer net charm + direction), extracted verbatim. Pre-initializes all five outputs
    to their "unavailable" defaults BEFORE the try block -- an exception anywhere inside
    (compute_net_charm itself, or the unavailable-log-level branch) is caught and logged,
    never raised, leaving every field safely at its pre-initialized default, exactly as
    the original inline try/except did.

    RC-REHAB-1 (2026-09-22, module extraction): moved from server.py into its own file,
    verbatim -- zero server.py coupling to begin with. compute_net_charm /
    charm_compute_unavailable_log_level stay as scoped lazy imports inside this function,
    exactly matching the original inline code's own style (not changed by this move).
    """
    charm_net: Optional[float] = None
    charm_dir: Optional[str] = None
    charm_toward: Optional[float] = None
    charm_mag: Optional[float] = None
    charm_drivers: list = []
    try:
        from math_exposure import compute_net_charm
        # Per-tick diagnostic — demoted from INFO: fires every refresh regardless of
        # outcome, no operator-actionable signal (success and failure logs below carry it).
        log.debug(f"Charm: {ticker} calling compute_net_charm with {len(contracts_use)} contracts, exp={selected_exp}")
        # RC-345 / F18: charm measures the net-charm DIRECTION, not a target STRIKE. It must
        # NOT borrow the net-GEX peak (a gamma quantity) as its drift target — that was a
        # different-Greek substitution masquerading under the charm name. drift_toward is
        # WITHHELD (governed absence); the net-GEX peak keeps its own field, net_gex_peak.
        charm_raw = compute_net_charm(
            contracts_use, spot_f, selected_exp, drift_toward_strike=None
        )
        # caps-ok (both below): compute_net_charm's return dict always includes these two
        # keys on both its error-branch and success-branch returns (math_exposure_core.py) --
        # a same-code-version function result, not a persisted/vendor artifact that could
        # predate a schema change, so the default can never actually be exercised.
        charm_used = charm_raw["contracts_used"]
        charm_err = charm_raw["error"]
        if charm_used > 0:
            charm_net = charm_raw["net_charm_daily"]
            charm_dir = charm_raw["charm_direction"]
            charm_toward = charm_raw.get("drift_toward")
            charm_mag = charm_raw.get("charm_magnitude")
            # RC-85: the read of "top_drivers" is GONE. compute_net_charm has never emitted that
            # key — it returns call_charm_daily, charm_direction, charm_magnitude, contracts_used,
            # drift_toward, error, net_charm_daily, put_charm_daily (its duplicate `gamma_pin`
            # alias was deleted by RC-302) — so
            # `.get("top_drivers", [])` returned [] on every call since the line was written, and
            # charm_top_drivers has been permanently empty. The default was the whole problem: []
            # reads as "computed, no drivers found" when the truth is "never computed", so the
            # name mismatch had no symptom. charm_drivers stays [] from its initialiser above,
            # which is the same value WITHOUT the claim that a producer was consulted. Populating
            # it needs compute_net_charm to actually rank the contributing strikes; that is a
            # feature, not a rename, and it is not being smuggled in behind a default.
            # RC-292: the log label must not call charm's (withheld) drift target a pin —
            # a pin claim ships only as pin_candidate after qualification.
            log.info(f"Charm: {ticker} ✅ net={charm_net:.0f} dir={charm_dir} mag={charm_mag} drift_toward={charm_toward} "
                     f"({charm_used} contracts)")
        else:
            from math_exposure_core import charm_compute_unavailable_log_level

            lvl = charm_compute_unavailable_log_level(charm_err)
            if lvl == logging.DEBUG:
                log_fn = log.debug
            elif lvl == logging.INFO:
                log_fn = log.info
            else:
                log_fn = log.warning
            log_fn(
                "Charm: %s ❌ 0 contracts matched. error='%s' input_contracts=%s exp=%s",
                ticker,
                charm_err,
                len(contracts_use),
                selected_exp,
            )
    except Exception as _ce:
        import traceback
        log.warning(f"Charm: {ticker} 💥 EXCEPTION: {_ce}\n{traceback.format_exc()}")
    return _CharmForState(
        charm_net=charm_net,
        charm_dir=charm_dir,
        charm_toward=charm_toward,
        charm_mag=charm_mag,
        charm_drivers=charm_drivers,
    )
