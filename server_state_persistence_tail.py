"""Post-publish Persistence Tail phase of _fetch_state (server.py), extracted
(RC-REHAB-1, 2026-09-23). Twentieth real module-level slice of the _fetch_state
decomposition, alongside server_state_volatility.py, server_state_candles.py,
server_state_signals.py, and server_state_order_flow.py -- see
server_state_volatility.py's own docstring for why this decomposition exists.

_post_publish_persistence_tail was already promoted from a nested closure inside
_fetch_state to a module-level function (server.py, nineteenth slice) -- this slice
moves that module-level function, and its sole private module-global
(_dpi_normalized_prev_by_ticker, no external reader confirmed by a repo-wide search
before moving, same "self-contained function + its own private state moves as one
unit" rule already applied to server_state_order_flow.py's _rest_cum_delta_session),
into its own file.

MONKEYPATCH/RUNTIME-STATE NOTE: this function calls 11 server.py-local helpers that
have OTHER callers elsewhere in server.py (confirmed before moving, so they correctly
stay in server.py rather than moving too): _current_pred_model_version,
_ensure_mkt_ctx_confluence_complete, _gated_safe_get_chain,
_get_db_fill_outcomes_executor, _record_post_publish_failure,
_selected_schwab_days_to_expiration, _snapshot_expiry_hours_from_schwab_dte,
_snapshot_row_insert_committed, _snapshot_row_insert_release, terrain_cache_get,
flatten_chain_contracts. Reached via the same lazy `import server` pattern proven in
server_state_volatility.py/server_state_candles.py/server_state_order_flow.py.

get_db, session_bucket/vix_bucket, CANONICAL_TIMEFRAME, and crash_trace's diagnostic
hooks are re-imported here directly from their own true origin modules (db.py,
math_exposure.py, timeframe_config.py, crash_trace.py) rather than reached lazily --
none of this is server.py-specific logic, matching the same principle
server_state_order_flow.py's own docstring states for crash_trace.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Optional

log = logging.getLogger(__name__)

from db import get_db
from math_exposure import session_bucket as _session_bucket, vix_bucket as _vix_bucket
from math_snapshot_derive import derive_pressure_trend, derive_vwap_side
from realized_contract_eval import serialize_option_chain_for_eval, build_replay_context_payload
from time_et import is_capturable_session
from timeframe_config import CANONICAL_TIMEFRAME
import terrain_loop

try:
    from crash_trace import step as _diag_step, step_done as _diag_done, trace_crash as _diag_crash, _on as _diag_on
except ImportError:
    _diag_on = lambda: False  # noqa: E731
    _diag_step = _diag_done = lambda n, t="": None  # noqa: E731
    _diag_crash = lambda n, e, t="": None  # noqa: E731

# RC-REHAB-1: moved with _post_publish_persistence_tail -- confirmed no other reference
# anywhere in server.py before moving (each had exactly one: its own definition).
ACCURACY_INTERVAL: int = 600  # seconds between accuracy computations (~10 min)
ETF_ZONE_THRESHOLD_PCT: float = 0.3  # chg_pct beyond +/-0.3% -> bullish/bearish_trend

# RC-REHAB-1: moved from server.py with _post_publish_persistence_tail (its only
# reader/writer, confirmed by a repo-wide search before moving) -- no external caller,
# so no re-export/aliasing hazard (matches server_state_order_flow.py's own
# _rest_cum_delta_session precedent).
_dpi_normalized_prev_by_ticker: dict[str, Optional[float]] = {}


def _post_publish_persistence_tail(
    published_version,
    v2_decision_for_log,
    *,
    ms,
    ticker: str,
    client,
    mkt_ctx,
    contracts_use: list,
    selected_exp,
    session_label,
    price_levels,
    zt: dict,
    pcr_val,
    now_et,
    _ed_db,
    update_source,
    logger_source,
    _refresh_ts_utc: float,
    q,
    exp,
    gfvz,
    cd,
    c_vol,
    vs,
    charm,
    pp,
    sweep_score: dict,
    ofs,
    ves,
    xid_do_snapshot_insert: bool,
    xid_model_derived: bool,
    stage_marks: list,
) -> None:
    """RC-REHAB-1 (Phase 4, _fetch_state decomposition, nineteenth slice): the
    post-publish Persistence Tail (DB snapshot logging + periodic accuracy tracking +
    V2 calibration logging), promoted from a nested closure inside _fetch_state to a
    module-level function, extracted verbatim otherwise.

    RC-REHAB-1 (thirty-sixth slice): the ~60 scalar keyword parameters became the phase
    NamedTuples (q / exp / gfvz / cd / vs / charm / pp / ofs / ves) plus the few genuinely
    cycle-level values; they are bound to the body's historical local names once, at the
    top of the body. Original rationale, kept for the history:

    This was the single most closure-heavy phase in _fetch_state: symtable analysis
    (not manual counting) found 61 free variables read from the enclosing scope. Every
    one is threaded here as an explicit KEYWORD-ONLY parameter (the bare `*` after the
    two original positional params forces every call site to name every argument --
    with 61 of them, a positional call would be unreviewable and one silent
    transposition could corrupt a persisted trading snapshot). Parameter names are
    IDENTICAL to the original free-variable names (including their leading
    underscores, `_fetch_state`'s own scratch-variable convention) specifically so the
    819-line body below required ZERO renaming -- every reference resolves exactly as
    it did as a closure read, just now to a parameter instead.

    `mkt_ctx` was the ONE `nonlocal`-mutated name in the original closure (a single
    confluence-completion reassignment, `mkt_ctx = _srv._ensure_mkt_ctx_confluence_complete(
    client, mkt_ctx)`, inside the DB-snapshot-insert branch). As a plain module-level
    function this reassignment is now an ordinary local rebinding with no `nonlocal`
    needed -- and it does NOT need to be returned to the caller: verified directly that
    _fetch_state never reads `mkt_ctx` again after either of this function's two call
    sites (one on the log_only early-return path, one on the full-publish path; they
    are mutually exclusive per invocation). The reassignment's only consumer is this
    same function's own snapshot-kwargs construction, further down in this same call.

    Two independent top-level sections, siblings (NOT nested in each other), each with
    its OWN failure boundary:
    - DB Snapshot Logging (gated on `_ed_db`): internally a SINGLE sequential
      try/except wraps ~11 sub-steps (field derivation, snapshot-kwargs construction,
      once-daily morning full-chain persist, dynamic model-health/fusion-policy field
      injection, a starvation guard, execution-identity consumption, the actual
      SnapshotRow insert, a background bars/outcome-fill submission, a feature-flagged
      materialize step, and periodic accuracy tracking) -- preserved EXACTLY as a
      single shared failure domain, not split into independently-isolated steps: if
      any one of them raises, every step after it is skipped for this cycle, exactly
      as the nested closure's own single try/except already did. This is NOT the
      "independent try per computation" pattern used elsewhere in this decomposition
      (e.g. Order Flow Signals) -- deliberately preserved as-is, not "fixed," because
      changing it would be an unreviewed behavior change.
    - V2 Calibration Logging (its own separate try/except): runs regardless of whether
      DB Snapshot Logging succeeded, but silently DEPENDS on `_snap_ts`, a variable
      DB Snapshot Logging only assigns when `_ed_db` is truthy. When `_ed_db` is
      falsy, this section's read of `_snap_ts` raises NameError, caught by its own
      except -- an existing "fails safely but always fails in that case" edge case,
      preserved exactly, not treated as a bug to fix here.
    """
    import server as _srv

    # RC-REHAB-1 (thirty-sixth slice): the caller hands over each phase's own NamedTuple
    # instead of ~60 pre-unpacked locals; they are bound ONCE here under the names the body
    # below has always used, so the body itself is unchanged.
    spot, spot_f, walls, totals = q.spot, exp.spot_f, exp.walls, exp.totals
    consensus_summary = gfvz.consensus_summary
    vol_ctx = ves.vol_ctx
    parsed_bid, parsed_ask, _session_q = q.bid, q.ask, q.session_q
    et_h, et_m = now_et.hour, now_et.minute
    _total_vol, _quote_spread = q.total_vol, q.spread_pts
    _candle_dir, _candle_body, _c_vol = cd.candle_dir, cd.candle_body, c_vol
    _atr, _iv_skew, _realized_vol = vs.atr, vs.iv_skew, vs.realized_vol
    _iv_rank, _iv_percentile = vs.iv_rank, vs.iv_percentile
    _charm_net, _charm_dir = charm.charm_net, charm.charm_dir
    _charm_toward, _charm_mag = charm.charm_toward, charm.charm_mag
    _dpi, _hedging_flow, _gamma_gradient = pp.dpi, pp.hedging_flow, pp.gamma_gradient
    _breakout_score, _pin_score_val, _vol_expansion = pp.breakout_score, pp.pin_score_val, pp.vol_expansion
    _sweep_score = sweep_score
    _vol_oi_ratio, _flow_imb_norm, _flow_imb_source = ofs.vol_oi_ratio, ofs.flow_imb_norm, ofs.flow_imb_source
    _smart_money, _iv_model_spread = ofs.smart_money, ofs.iv_model_spread
    _vol_envelope, _level_density = ves.vol_envelope, ves.level_density
    _sector_strength, _index_strength = ves.sector_strength, ves.index_strength
    _spy_strength, _iwm_deep = ves.spy_strength, ves.iwm_deep
    _xid_do_snapshot_insert, _xid_model_derived = xid_do_snapshot_insert, xid_model_derived
    _stage_marks = stage_marks

    # ── DB snapshot logging ───────────────────────────────────────────────────
    # Initialized outside `if _ed_db` so the calibration gate below can read it.
    _snap_insert_landed = False
    if _ed_db:  # snapshot INSERT, bars persist + outcome backfill all throttled (see ED_DB_SNAPSHOT_THROTTLE)
        if _diag_on():
            _diag_step("pre_db_snapshot", ticker)
        # Reservation lifecycle: released in the except below iff the insert never
        # landed (failure between reserve and insert must not burn the minute;
        # releasing after a landed insert would re-open it). Initialized before
        # the try so the handler can never NameError.
        _snap_ts = _refresh_ts_utc
        _do_insert = False
        try:
            from db import SnapshotRow, build_ts_et
            from math_exposure import _f as _mf
            # EXEC_IDENTITY_DECISION_SURFACE_ORDERING_V1: the throttle
            # reservation was taken at the pre-publish identity anchor so
            # expected_surfaces could include "snapshot" truthfully; this
            # tail consumes that single reservation (release-on-failure
            # semantics below are unchanged).
            _do_insert = _xid_do_snapshot_insert
            if not _do_insert:
                log.debug(
                    "DB snapshot insert skipped (throttle: max 1 insert/ticker/UTC minute; set ED_DB_SNAPSHOT_THROTTLE=0 to disable): %s",
                    ticker,
                )
            if _do_insert:
                _et_now = now_et
                from base_money_path_capture import resolve_logger_source_from_update_source

                _resolved_logger_source = logger_source or resolve_logger_source_from_update_source(
                    update_source
                )

                # DTE is Schwab-native. Missing daysToExpiration fails closed for snapshot persistence.
                _dte = _srv._selected_schwab_days_to_expiration(
                    contracts_use,
                    selected_exp,
                    preferred_strike=getattr(ms, "rec_strike", None),
                    preferred_side=getattr(ms, "call_option_right", None),
                )
                _hours_to_expiry = _srv._snapshot_expiry_hours_from_schwab_dte(
                    _dte, _et_now, expiry_et_date=selected_exp
                )
    
                # ── Compute fields from available data ─────────────────────────────
    
                # Candle OHLC from canonical (1m) accumulator's current bar
                _cur_bar = _srv._candles_1m._current.get(ticker)
                _c_open  = _cur_bar["o"] if _cur_bar else None
                _c_high  = _cur_bar["h"] if _cur_bar else None
                _c_low   = _cur_bar["l"] if _cur_bar else None
                _c_close = _cur_bar["c"] if _cur_bar else None
                _c_range = round(_c_high - _c_low, 4) if (_c_high and _c_low) else None
                # _c_vol computed above before build_market_state
    
                # VWAP distance — the PERSISTED vwap is the carried canonical value.
                # Phase 2A: the old `_compute_vwap_from_bars` fallback here was a
                # SECOND VWAP materialization writing into the snapshot table and
                # from there into model features, so a row's vwap could be a number
                # /api/levels never served. A fallback that produces a different
                # answer is not resilience; absence is the honest output (RC-68).
                _vwap = getattr(price_levels, "vwap", None)
                _vwap_f = float(_vwap) if _vwap is not None else None
                if _vwap_f is None:
                    from liquidity_value_engine import (
                        SESSION_VWAP_RTH_PRODUCER_FAILURE,
                        classify_session_vwap_presence,
                    )
                    _is_index_symbol = isinstance(ticker, str) and ticker.startswith("$")
                    _vwap_status = classify_session_vwap_presence(
                        vwap=_vwap_f,
                        session_date=_et_now.date(),
                        now_et_dt=_et_now,
                        session_rth_positive_volume_bars=int(
                            getattr(price_levels, "session_rth_positive_volume_bars", 0) or 0  # caps-ok: PriceLevels.session_rth_positive_volume_bars field itself defaults to 0 (market_context.py) -- matches
                        ),
                    )
                    # Index symbols have no volume by definition; weekend/premarket
                    # absence is expected. WARN only on genuine RTH producer failure.
                    _vwap_log = (
                        log.warning
                        if (not _is_index_symbol and _vwap_status == SESSION_VWAP_RTH_PRODUCER_FAILURE)
                        else log.debug
                    )
                    _vwap_log(
                        "VWAP absent for %s (canonical snapshot generation=%s status=%s) — writing NULL",
                        ticker, getattr(price_levels, "level_generation", None), _vwap_status,
                    )
                _vwap_dist = round(spot_f - _vwap_f, 4) if _vwap_f else None
    
                # VWAP side follows the persisted canonical session VWAP (None stays None).
                _row_vwap_side = getattr(ms, "vwap_side", None)
                if _row_vwap_side is None:
                    _row_vwap_side = derive_vwap_side(spot_f, _vwap_f)
    
                global _dpi_normalized_prev_by_ticker
                _prev_dn = _dpi_normalized_prev_by_ticker.get(ticker)
                _cur_raw = _dpi.get("normalized") if _dpi else None
                try:
                    _cur_dn_f = float(_cur_raw) if _cur_raw is not None else None
                except (TypeError, ValueError):
                    _cur_dn_f = None
                _pressure_trend_live = derive_pressure_trend(_prev_dn, _cur_dn_f)
                _dpi_normalized_prev_by_ticker[ticker] = _cur_dn_f
                _pressure_label_live = None
                if _dpi:
                    _pressure_label_live = _dpi.get("direction")
                if not _pressure_label_live and _hedging_flow:
                    _pressure_label_live = _hedging_flow.get("direction")
                if not _pressure_label_live:
                    _pressure_label_live = "unavailable_no_dpi_or_hedging_flow_direction"
    
                # Wall absolute values
                _cgw = _mf(getattr(walls[0], "call_gamma_wall", None)) if walls else None
                _pgw = _mf(getattr(walls[0], "put_gamma_wall",  None)) if walls else None
                _cdw = _mf(getattr(walls[0], "call_delta_wall", None)) if walls else None
                _pdw = _mf(getattr(walls[0], "put_delta_wall",  None)) if walls else None
                _cow = _mf(getattr(walls[0], "call_oi_wall",    None)) if walls else None
                _pow = _mf(getattr(walls[0], "put_oi_wall",     None)) if walls else None
                _cvw = _mf(getattr(walls[0], "call_vanna_wall", None)) if walls else None
                _pvw = _mf(getattr(walls[0], "put_vanna_wall",  None)) if walls else None
                # Inflection points live on ExposureRow (consensus), NOT WallsRow
                _gi  = _mf(getattr(consensus_summary, "gamma_inflection", None)) if consensus_summary else None
                _di  = _mf(getattr(consensus_summary, "delta_inflection", None)) if consensus_summary else None
    
                # Distance = wall_level - spot (positive = above, negative = below)
                _d = lambda lvl: round(lvl - spot_f, 4) if lvl is not None else None
                _dist_cgw = _d(_cgw)
                _dist_pgw = _d(_pgw)
                _dist_cdw = _d(_cdw)
                _dist_pdw = _d(_pdw)
                _dist_cow = _d(_cow)
                _dist_pow = _d(_pow)
                _dist_cvw = _d(_cvw)
                _dist_pvw = _d(_pvw)
                _dist_gi  = _d(_gi)
                _dist_di  = _d(_di)
    
                # Pin width (call gamma wall - put gamma wall) — RC-345/F20 one authority
                from math_levels import compute_pin_width_pts
                _pin_w = compute_pin_width_pts(_cgw, _pgw)
    
                # Constituents from market context — wrap each fetch independently for partial results
                mkt_ctx = _srv._ensure_mkt_ctx_confluence_complete(client, mkt_ctx)
                _const_map = {}
                if hasattr(mkt_ctx, "constituents"):
                    for cq in mkt_ctx.constituents:
                        try:
                            if cq.chg_pct is not None:
                                _const_map[cq.symbol.upper()] = round(float(cq.chg_pct), 4)
                        except Exception as e:
                            log.warning(f"Constituent {getattr(cq, 'symbol', '?')} chg_pct fetch failed: {e}")  # caps-ok: diagnostic log message inside an already-failing except block, defensive against a malformed cq
                try:
                    _spw = getattr(getattr(mkt_ctx, "confluence", None), "weighted_push", None)
                except Exception as e:
                    log.warning(f"spy_weighted_push (confluence) failed: {e}")
                    _spw = None
                try:
                    _qqqw = getattr(getattr(mkt_ctx, "qqq_confluence", None), "weighted_push", None)
                except Exception as e:
                    log.warning(f"qqq_weighted_push (qqq_confluence) failed: {e}")
                    _qqqw = None

                # IWM sectors from market context — wrap each fetch independently for partial results
                _sect_map = {}
                if hasattr(mkt_ctx, "iwm_sectors"):
                    for sq in mkt_ctx.iwm_sectors:
                        try:
                            if sq.chg_pct is not None:
                                _sect_map[sq.symbol.upper()] = round(float(sq.chg_pct), 4)
                        except Exception as e:
                            log.warning(f"Sector {getattr(sq, 'symbol', '?')} chg_pct fetch failed: {e}")  # caps-ok: diagnostic log message inside an already-failing except block, defensive against a malformed sq
                try:
                    from market_context import iwm_blended_participation_push
                    _iwp = iwm_blended_participation_push(mkt_ctx)
                except Exception as e:
                    log.warning(f"iwm_weighted_push (blended participation) failed: {e}")
                    _iwp = None
    
                # VOL_INPUT_CONTRACT 1.0.0: snapshot row consumes the one
                # per-cycle context (no re-tick, no independent vs-prev).
                _vix_vs_prev = vol_ctx.market_iv_change
                _vix_dir = vol_ctx.market_iv_direction
    
                # ETF zone helper: derive bullish/bearish/neutral from chg_pct.
                # Used for spy_zone / qqq_zone / iwm_zone in snapshot row.
                def _etf_zone(chg):
                    if chg is None: return None
                    if float(chg) >  ETF_ZONE_THRESHOLD_PCT: return "bullish_trend"
                    if float(chg) < -ETF_ZONE_THRESHOLD_PCT: return "bearish_trend"
                    return "neutral"

                # Price-action cone (operator 2026-06-11): persist bar-derived
                # momentum/structure primitives from the in-memory 1m accumulator
                # (completed bars only; bar_end <= ts_utc — leak-free). Honest
                # nulls when history is short; never fabricated fills.
                _pa_cols: dict[str, Any] = {}
                try:
                    from types import SimpleNamespace as _PA_NS
                    from features.signal_layer_v1 import compute_price_action_snapshot_columns
                    _pa_bars = [
                        {
                            "bar_start_ts_utc": float(_cb.ts),
                            "bar_end_ts_utc": float(_cb.ts) + float(_srv.CANDLE_1M_SECONDS),
                            "open": _cb.open, "high": _cb.high, "low": _cb.low,
                            "close": _cb.close, "volume": _cb.volume,
                        }
                        for _cb in (_srv._candles_1m.get_bars(ticker) or [])
                    ]
                    _pa_cols = compute_price_action_snapshot_columns(
                        _pa_bars, decision_ts_utc=float(_snap_ts), inp=_PA_NS(vwap=_vwap_f),
                    )
                except Exception as e:
                    log.warning("price-action snapshot columns failed (%s): %s", ticker, e)
                    _pa_cols = {}

                # RC-292/RC-429: the persisted quantity is UNCHANGED — terrain
                # total-gamma, read from the renamed payload field. The DB column
                # stays `gamma_pin` (historical schema; time_et.py owns its era
                # semantics) so no third era is created by the rename.
                _t_pin_snap = terrain_loop.terrain_cache_get(ticker) or {}
                _ssot_gamma_pin = (
                    _t_pin_snap.get("absolute_gamma_strike")
                    if _t_pin_snap and not _t_pin_snap.get("levels_stale")
                    else None
                )

                _snapshot_kwargs = dict(
                    **_pa_cols,
                    ticker=ticker,
                    timeframe=CANONICAL_TIMEFRAME,
                    expiry=selected_exp,
                    dte=_dte,
                    hours_to_expiry=_hours_to_expiry,
                    ts_utc=_snap_ts,
                    ts_et=build_ts_et(_et_now),
                    et_hour=et_h,
                    et_minute=et_m,
                    market_session=(session_label or "unknown").lower().replace("-", ""),
                    session_bucket=_session_bucket(et_h, et_m),
                    spot=spot_f,
                    spread=_quote_spread,
                    # Raw Schwab quote primitives (same parsed node as bid/ask/spread):
                    # quotes.{SYM}.bidPrice/askPrice/bidSize/askSize/lastSize/totalVolume.
                    bid_price=parsed_bid,
                    ask_price=parsed_ask,
                    bid_size=_session_q.get("bid_size"),
                    ask_size=_session_q.get("ask_size"),
                    last_size=_session_q.get("last_size"),
                    total_volume=(_total_vol if _total_vol is not None else _session_q.get("total_volume")),
                    candle_open=_c_open, candle_high=_c_high, candle_low=_c_low,
                    candle_close=_c_close, candle_volume=_c_vol, candle_direction=_candle_dir,
                    candle_body_pts=_candle_body, candle_range_pts=_c_range,
                    vwap=_vwap_f,
                    vwap_side=_row_vwap_side,
                    vwap_dist_pts=_vwap_dist,
                    pressure_label=_pressure_label_live,
                    pressure_trend=_pressure_trend_live,
                    pdh=getattr(price_levels, "pdh", None),
                    pdl=getattr(price_levels, "pdl", None),
                    pdc=getattr(price_levels, "pdc", None),
                    orb_high=getattr(price_levels, "orb_high", None),
                    orb_low=getattr(price_levels, "orb_low", None),
                    zone=ms.zone,
                    zone_since_bars=zt["since_bars_1m"],
                    zone_since_bars_1m=zt["since_bars_1m"],
                    zone_since_bars_5m=zt["since_bars_5m"],
                    prev_zone=zt["prev_zone"],
                    dist_call_gamma_wall=_dist_cgw, dist_put_gamma_wall=_dist_pgw,
                    dist_call_delta_wall=_dist_cdw, dist_put_delta_wall=_dist_pdw,
                    dist_gamma_inflection=_dist_gi, dist_delta_inflection=_dist_di,
                    dist_call_oi_wall=_dist_cow, dist_put_oi_wall=_dist_pow,
                    dist_call_vanna_wall=_dist_cvw, dist_put_vanna_wall=_dist_pvw,
                    call_gamma_wall=_cgw, put_gamma_wall=_pgw,
                    call_delta_wall=_cdw, put_delta_wall=_pdw,
                    gamma_inflection=_gi, delta_inflection=_di,
                    call_oi_wall=_cow, put_oi_wall=_pow,
                    call_vanna_wall=_cvw, put_vanna_wall=_pvw,
                    pin_width_pts=_pin_w,
                    nearest_above_name=ms.nearest_above_name if hasattr(ms, "nearest_above_name") else None,
                    nearest_above_val=ms.nearest_above_val if hasattr(ms, "nearest_above_val") else None,
                    nearest_above_dist=ms.nearest_above_dist if hasattr(ms, "nearest_above_dist") else None,
                    nearest_below_name=ms.nearest_below_name if hasattr(ms, "nearest_below_name") else None,
                    nearest_below_val=ms.nearest_below_val if hasattr(ms, "nearest_below_val") else None,
                    nearest_below_dist=ms.nearest_below_dist if hasattr(ms, "nearest_below_dist") else None,
                    net_gamma=ms.net_gamma, net_delta=ms.net_delta,
                    net_vanna=getattr(ms, "net_vanna", None),
                    charm_net=_charm_net, charm_direction=_charm_dir, charm_drift_toward=_charm_toward,
                    charm_magnitude=_charm_mag,
                    iv_level=(float(getattr(totals[0], "atm_iv")) if totals and getattr(totals[0], "atm_iv", None) is not None else None),  # percent for DB / iv_rank history  # caps-ok: None-check via defaulting getattr before the real, defaultless getattr() that raises if truly missing
                    iv_direction=getattr(ms, "iv_direction", None),
                    put_call_oi_ratio=pcr_val,
                    oi_center=getattr(consensus_summary, "oi_center", None) if consensus_summary else None,
                    gamma_pin=_ssot_gamma_pin,
                    spy_spot=mkt_ctx.spy_last, spy_chg_pct=mkt_ctx.spy_chg_pct,
                    spy_zone=_etf_zone(mkt_ctx.spy_chg_pct), spy_vwap_side=None, spy_net_delta=None,
                    qqq_spot=mkt_ctx.qqq_last, qqq_chg_pct=mkt_ctx.qqq_chg_pct,
                    qqq_zone=_etf_zone(mkt_ctx.qqq_chg_pct), qqq_vwap_side=None, qqq_net_delta=None,
                    qqq_vs_spy=(round(float(mkt_ctx.qqq_chg_pct) - float(mkt_ctx.spy_chg_pct), 4)
                                if mkt_ctx.qqq_chg_pct is not None and mkt_ctx.spy_chg_pct is not None else None),
                    qqq_vs_spy_delta=None,
                    iwm_spot=mkt_ctx.iwm_last, iwm_chg_pct=mkt_ctx.iwm_chg_pct,
                    iwm_zone=_etf_zone(mkt_ctx.iwm_chg_pct), iwm_vwap_side=None, iwm_net_delta=None,
                    iwm_vs_spy=(round(float(mkt_ctx.iwm_chg_pct) - float(mkt_ctx.spy_chg_pct), 4)
                                if mkt_ctx.iwm_chg_pct is not None and mkt_ctx.spy_chg_pct is not None else None),
                    iwm_risk_signal=None,
                    nvda_chg_pct=_const_map.get("NVDA"),
                    aapl_chg_pct=_const_map.get("AAPL"),
                    msft_chg_pct=_const_map.get("MSFT"),
                    amzn_chg_pct=_const_map.get("AMZN"),
                    googl_chg_pct=_const_map.get("GOOGL"),
                    goog_chg_pct=_const_map.get("GOOG"),
                    avgo_chg_pct=_const_map.get("AVGO"),
                    meta_chg_pct=_const_map.get("META"),
                    tsla_chg_pct=_const_map.get("TSLA"),
                    spy_weighted_push=round(float(_spw), 4) if _spw is not None else None,
                    qqq_weighted_push=round(float(_qqqw), 4) if _qqqw is not None else None,
                    kre_chg_pct=_sect_map.get("KRE"),
                    xbi_chg_pct=_sect_map.get("XBI"),
                    psci_chg_pct=_sect_map.get("PSCI"),
                    xrt_chg_pct=_sect_map.get("XRT"),
                    iwm_weighted_push=round(float(_iwp), 4) if _iwp is not None else None,
                    vix_level=vol_ctx.market_iv_level,
                    vix_direction=_vix_dir,
                    vix_vs_prev=_vix_vs_prev,
                    vix_bucket=(
                        _vix_bucket(vol_ctx.market_iv_level)
                        if vol_ctx.market_iv_level is not None else None
                    ),
                    rules_signal=ms.rules_signal,
                    rules_conviction=ms.rules_conviction,
                    rules_entry=ms.entry, rules_stop=ms.stop, rules_target=ms.target,
                    call_target2=ms.target2,
                    reward_risk=ms.reward_risk,
                    reward_risk2=ms.reward_risk2,
                    rules_summary=ms.rules_headline,
                    pred_1c_up_prob=ms.up_prob_1c, pred_1c_down_prob=ms.down_prob_1c,
                    pred_1c_flat_prob=ms.flat_prob_1c,
                    pred_5c_up_prob=ms.up_prob_5c, pred_5c_down_prob=ms.down_prob_5c,
                    pred_5c_flat_prob=ms.flat_prob_5c,
                    pred_15c_up_prob=ms.up_prob_15c, pred_15c_down_prob=ms.down_prob_15c,
                    pred_15c_flat_prob=ms.flat_prob_15c,
                    pred_60c_up_prob=getattr(ms, "up_prob_60c", None),
                    pred_60c_down_prob=getattr(ms, "down_prob_60c", None),
                    pred_60c_flat_prob=getattr(ms, "flat_prob_60c", None),
                    pred_model_version=ms.model_version or "rules_v1",
                    pred_model_source=getattr(ms, 'pred_model_source', None),
                    pred_override_source=getattr(ms, 'pred_override_source', None),
                    logger_source=_resolved_logger_source,
                    pred_confidence=ms.confidence,
                    pred_samples_used=ms.samples_used,
                    prediction_direction=getattr(ms, 'dominant_dir', None),
                    prediction_dominant_prob=getattr(ms, 'dominant_prob', None),
                    combined_signal=ms.call_signal,
                    combined_conviction=ms.call_conviction,
                    rules_pred_agree=ms.rules_pred_agree,
                    # ── Model stack (regime, fusion, MC, individual models) ────
                    regime_primary=getattr(ms, 'regime_primary', None),
                    regime_confidence=getattr(ms, 'regime_confidence', None),
                    regime_score=getattr(ms, 'regime_score', None),
                    fusion_dominant=getattr(ms, 'fusion_dominant', None),
                    fusion_dominant_prob=getattr(ms, 'fusion_dominant_prob', None),
                    fusion_confidence=getattr(ms, 'fusion_confidence', None),
                    fusion_breakout=getattr(ms, 'fusion_breakout', None),
                    fusion_pinning=getattr(ms, 'fusion_pinning', None),
                    fusion_continuation=getattr(ms, 'fusion_continuation', None),
                    fusion_reversal=getattr(ms, 'fusion_reversal', None),
                    fusion_vol_expansion=getattr(ms, 'fusion_vol_expansion', None),
                    fusion_mean_reversion=getattr(ms, 'fusion_mean_reversion', None),
                    fusion_model_agreement=getattr(ms, 'fusion_model_agreement', None),
                    fusion_n_models_active=getattr(ms, 'fusion_n_models_active', None),
                    fusion_prob_up=getattr(ms, 'fusion_prob_up', None),
                    fusion_prob_down=getattr(ms, 'fusion_prob_down', None),
                    fusion_prob_flat=getattr(ms, 'fusion_prob_flat', None),
                    fusion_dominant_direction=getattr(ms, 'fusion_dominant_direction', None),
                    mc_efe=getattr(ms, 'mc_efe', None),
                    mc_eae=getattr(ms, 'mc_eae', None),
                    mc_containment=getattr(ms, 'mc_containment', None),
                    mc_expansion=getattr(ms, 'mc_expansion', None),
                    mc_upper_50=getattr(ms, 'mc_upper_50', None),
                    mc_lower_50=getattr(ms, 'mc_lower_50', None),
                    mc_paths=getattr(ms, 'mc_paths', None),
                    mc_horizon=getattr(ms, 'mc_horizon', None),
                    mc_vol_source=getattr(ms, 'mc_vol_source', None),
                    mc_sigma_value=getattr(ms, 'mc_sigma_value', None),
                    mc_conditioning=getattr(ms, 'mc_conditioning', None),
                    # ── Individual model outputs (stack visibility) ─────────────────
                    xgb_available=getattr(ms, 'xgb_available', None),
                    xgb_dominant=getattr(ms, 'xgb_dominant', None),
                    xgb_confidence=getattr(ms, 'xgb_confidence', None),
                    xgb_approved=getattr(ms, 'xgb_approved', None),
                    lstm_available=getattr(ms, 'lstm_available', None),
                    lstm_dominant=getattr(ms, 'lstm_dominant', None),
                    lstm_confidence=getattr(ms, 'lstm_confidence', None),
                    lstm_approved=getattr(ms, 'lstm_approved', None),
                    transformer_available=getattr(ms, 'transformer_available', None),
                    transformer_dominant=getattr(ms, 'transformer_dominant', None),
                    transformer_confidence=getattr(ms, 'transformer_confidence', None),
                    transformer_approved=getattr(ms, 'transformer_approved', None),
                    # ── Volatility signals ─────────────────────────────────
                    iv_skew=_iv_skew.get("skew"),
                    realized_vol=_realized_vol,
                    atr=_atr,
                    iv_rank=_iv_rank,
                    iv_percentile=_iv_percentile,
                    # ── Section 8 predictive signals ───────────────────────
                    dpi_raw=_dpi.get("raw"),
                    dpi_normalized=_dpi.get("normalized"),
                    dpi_direction=_dpi.get("direction"),
                    hedging_flow_score=_hedging_flow.get("normalized"),
                    hedging_flow_direction=_hedging_flow.get("direction"),
                    gamma_gradient=_gamma_gradient,
                    breakout_score=_breakout_score.get("normalized"),
                    pin_score=_pin_score_val.get("normalized"),
                    vol_expansion_score=_vol_expansion.get("normalized"),
                    sweep_score=_sweep_score.get("normalized"),
                    # ── Session levels + sweeps ────────────────────────────
                    session_high=getattr(ms, 'session_high', None),
                    session_low=getattr(ms, 'session_low', None),
                    last_sweep_type=getattr(ms, 'last_sweep_type', None),
                    last_sweep_level=getattr(ms, 'last_sweep_level', None),
                    last_sweep_held=getattr(ms, 'last_sweep_held', None),
                    n_sweeps_today=getattr(ms, 'n_sweeps_today', 0),  # caps-ok: MarketState.n_sweeps_today field default is also 0 (market_state.py) -- matches, not a masked bug
                    # ── Trade Validation Gate ──────────────────────────
                    validation_passed=getattr(ms, 'validation_passed', None),
                    structure_valid=getattr(ms, 'structure_valid', None),
                    probability_valid=getattr(ms, 'probability_valid', None),
                    risk_valid=getattr(ms, 'risk_valid', None),
                    validation_summary=getattr(ms, 'validation_summary', ''),  # caps-ok: MarketState.validation_summary field default is also '' (market_state.py) -- matches, not a masked bug
                    # ── Position Sizing ────────────────────────────────────
                    r_units=getattr(ms, 'r_units', None),
                    execution_mode=getattr(ms, 'execution_mode', 'NO_TRADE'),  # caps-ok: MarketState.execution_mode field default is also 'NO_TRADE' (market_state.py) -- matches, not a masked bug
                    # ── Catalog signals ────────────────────────────────────
                    vol_env_upper=_vol_envelope.get("upper"),
                    vol_env_lower=_vol_envelope.get("lower"),
                    level_density_count=_level_density.get("count"),
                    level_density_label=_level_density.get("density_label"),
                    sector_leader=_sector_strength.get("leader"),
                    sector_laggard=_sector_strength.get("laggard"),
                    sector_breadth=_sector_strength.get("breadth"),
                    sector_risk_signal=_sector_strength.get("risk_signal"),
                    index_leader=_index_strength.get("leader"),
                    index_laggard=_index_strength.get("laggard"),
                    index_breadth=_index_strength.get("breadth"),
                    index_risk_signal=_index_strength.get("risk_signal"),
                    spy_holdings_leader=_spy_strength.get("leader"),
                    spy_holdings_laggard=_spy_strength.get("laggard"),
                    spy_holdings_breadth=_spy_strength.get("breadth"),
                    spy_holdings_risk=_spy_strength.get("risk_signal"),
                    # ── IWM Deep Confluence ────────────────────────────────
                    iwm_risk_regime=_iwm_deep.get("risk_regime"),
                    iwm_risk_score=_iwm_deep.get("risk_score"),
                    spy_iwm_divergence=_iwm_deep.get("spy_iwm_divergence"),
                    spy_iwm_fragile=_iwm_deep.get("spy_iwm_fragile"),
                    iwm_early_warning=_iwm_deep.get("early_warning"),
                    rotation_signal=_iwm_deep.get("rotation_signal"),
                    # ── Bond Yields ────────────────────────────────────────
                    tnx_yield=getattr(mkt_ctx, 'tnx_yield', None),
                    tnx_chg=getattr(mkt_ctx, 'tnx_chg', None),
                    bond_signal=getattr(mkt_ctx, 'bond_signal', None),
                    # ── Order Flow Signals ─────────────────────────────────
                    vol_oi_ratio=_vol_oi_ratio.get("ratio"),
                    flow_imbalance=_flow_imb_norm,
                    flow_imbalance_source=_flow_imb_source,  # RC-345/F11: persist economic book identity
                    smart_money_score=_smart_money.get("score"),
                    smart_money_direction=_smart_money.get("direction"),
                    iv_model_spread=_iv_model_spread.get("spread"),
                    option_chain_json=serialize_option_chain_for_eval(contracts_use, selected_exp),
                    replay_context_json=build_replay_context_payload(
                        walls=walls,
                        totals=totals,
                        option_chain_selection_proof=getattr(ms, "option_chain_selection_proof", None),
                        regime_primary=getattr(ms, "regime_primary", None),
                        regime_confidence=getattr(ms, "regime_confidence", None),
                        zone=getattr(ms, "zone", None),
                        vol_regime=getattr(ms, "vol_regime", None),
                        trade_type=getattr(ms, "trade_type", None),
                        time_qualifier=getattr(ms, "time_qualifier", None),
                        replay_max_hold_bars_live=getattr(ms, "replay_max_hold_bars", None),
                        vwap=_vwap_f,
                        vwap_side=_row_vwap_side,
                    ),
                    absorption_score=(getattr(ms, "liquidity_behavior", None) or {}).get("absorption_score"),
                    continuation_score=(getattr(ms, "liquidity_behavior", None) or {}).get("continuation_score"),
                    liquidity_behavior_label=(getattr(ms, "liquidity_behavior", None) or {}).get("behavior_label"),
                    sentiment_composite=(getattr(ms, "news_context", None) or {}).get("sentiment_composite"),
                    sentiment_buzz=(getattr(ms, "news_context", None) or {}).get("sentiment_buzz"),
                    sentiment_finnhub=(getattr(ms, "news_context", None) or {}).get("sentiment_finnhub"),
                    sentiment_av=(getattr(ms, "news_context", None) or {}).get("sentiment_av"),
                    breaking_news_flag=(1 if (getattr(ms, "news_context", None) or {}).get("breaking_news_flag") else 0),
                    breaking_news_headline=(getattr(ms, "news_context", None) or {}).get("breaking_news_headline"),
                    pre_market_sentiment=(getattr(ms, "news_context", None) or {}).get("pre_market_sentiment"),
                )
                # FIND-GAMMA-FULLCHAIN-STRIKES-V1: once/day morning *wide*
                # near-term chain (strike_count=GEX_FULL_CHAIN_STRIKE_COUNT).
                # Does NOT reuse the live UI 20-strike ``contracts`` list.
                # Idempotent before fetch; never widens option_chain_json;
                # try/except so live path is untouched on any failure.
                try:
                    _gex_tk = str(ticker).upper()
                    if _gex_tk in ("SPY", "QQQ", "IWM"):
                        from calibration.option_chain_morning_full import (
                            GEX_FULL_CHAIN_STRIKE_COUNT as _GEX_STRIKES,
                            MORNING_END_MINS as _GEX_END,
                            MORNING_START_MINS as _GEX_START,
                            SOURCE_WIDE as _GEX_SRC,
                            et_date_and_mins as _gex_et,
                            has_morning_full_capture,
                            maybe_persist_morning_full_chain,
                        )
                        from db import DB_PATH as _gex_db_path

                        _gex_date, _gex_mins = _gex_et(float(_snap_ts))
                        if _GEX_START <= _gex_mins <= _GEX_END and not has_morning_full_capture(
                            _gex_db_path, _gex_tk, _gex_date
                        ):
                            _wide_resp, _, _ = _srv._gated_safe_get_chain(
                                client,
                                ticker,
                                # The once-daily WIDE research capture deliberately takes the
                                # maximum vendor-safe width, not this ticker's minimum
                                # sufficient width: its whole purpose is to preserve strikes
                                # the live faucet would trim.
                                strike_count=_GEX_STRIKES,  # chain-width-faucet-ok: wide research capture takes max width by design
                                priority=False,
                            )
                            _wide_contracts: list = []
                            if (
                                _wide_resp is not None
                                and getattr(_wide_resp, "status_code", None) == 200
                            ):
                                _wide_contracts = _srv.flatten_chain_contracts(_wide_resp.json())
                            if _wide_contracts:
                                maybe_persist_morning_full_chain(
                                    _gex_db_path,
                                    ticker=_gex_tk,
                                    contracts=_wide_contracts,
                                    spot=float(spot) if spot is not None else None,
                                    ts_utc=float(_snap_ts),
                                    source=_GEX_SRC,
                                )
                except Exception as _gex_chain_e:
                    log.warning(
                        "option_chain_morning_full persist failed ticker=%s: %s",
                        ticker,
                        _gex_chain_e,
                    )
                _mh_live = getattr(ms, "movement_head_probs", None)
                if isinstance(_mh_live, dict):
                    for _k, _v in _mh_live.items():
                        if not isinstance(_k, str) or _v is None:
                            continue
                        try:
                            _fv = float(_v)
                        except (TypeError, ValueError):
                            continue
                        if _fv == _fv and abs(_fv) != float("inf"):
                            _snapshot_kwargs[_k] = _fv
                _fp_live = getattr(ms, "fusion_policy_snapshot_cols", None)
                if isinstance(_fp_live, dict):
                    for _k, _v in _fp_live.items():
                        if not isinstance(_k, str) or _v is None:
                            continue
                        if _k.startswith("fused_contributing_models_") or _k.startswith("fused_stack_status_"):
                            if isinstance(_v, str):
                                _snapshot_kwargs[_k] = _v[:8000]
                            continue
                        try:
                            _fv = float(_v)
                        except (TypeError, ValueError):
                            continue
                        if _fv == _fv and abs(_fv) != float("inf"):
                            _snapshot_kwargs[_k] = _fv
                # ECON-01 producer guard (fail-LOUD, 2026-07-11): a tradeable
                # decision row persisting without execution-replay context is
                # starvation at the source — replay can never recover it later
                # without fabricating history. Coverage at audit was 100%
                # (1,263/1,263 trailing-30d long/short rows); this guard keeps
                # any regression visible on the day it happens.
                # Schwab CSV authority checked: yes
                # CSV row(s): NO_SCHWAB_EQUIVALENT — observability guard only;
                #   no market field read, derived, or emitted by this block.
                # Derived-field disposition: none required.
                # All consumers checked: yes — log line only; snapshot insert
                #   proceeds unchanged (history is never dropped).
                # SCHWAB_CSV_CHECKED
                from realized_contract_eval import decision_row_context_starvation_reason

                _starve_reason = decision_row_context_starvation_reason(
                    combined_signal=_snapshot_kwargs.get("combined_signal"),
                    replay_context_json=_snapshot_kwargs.get("replay_context_json"),
                    option_chain_json=_snapshot_kwargs.get("option_chain_json"),
                )
                if _starve_reason:
                    log.error(
                        "REPLAY_CONTEXT_STARVATION ticker=%s signal=%s reason=%s "
                        "(ECON-01 producer guard: tradeable row missing execution context)",
                        ticker,
                        _snapshot_kwargs.get("combined_signal"),
                        _starve_reason,
                    )
                # EXEC_IDENTITY_DECISION_SURFACE_ORDERING_V1: the identity
                # anchor now lives at the pre-publish site (before the
                # decision finalize AND this tail); the tail only CONSUMES
                # the anchored pair. Fail-closed unchanged: a MODEL-DERIVED
                # snapshot with no anchored identity is REFUSED (loud ERROR
                # + skip) — never persisted without its immutable identity.
                # Quote-only rows (no combined_signal) stay NOT_APPLICABLE.
                # Schwab CSV authority checked: yes
                # CSV row(s): NO_SCHWAB_EQUIVALENT — provenance linkage only;
                #   no market field read, derived, or emitted by this block.
                # Derived-field disposition: none required.
                # All consumers checked: yes — additive identity fields.
                # SCHWAB_CSV_CHECKED
                _xid_refused = False
                if _snapshot_kwargs.get("combined_signal") is not None:
                    _xid_pair_snap = getattr(ms, "_execution_identity_pair", None)
                    if _xid_pair_snap:
                        _snapshot_kwargs["decision_id"] = _xid_pair_snap[0]
                        _snapshot_kwargs["execution_identity_sha256"] = _xid_pair_snap[1]
                        _snapshot_kwargs["execution_identity_class"] = "MODEL_DERIVED"
                    else:
                        log.error(
                            "EXECUTION_IDENTITY_REFUSED ticker=%s reason=%s — "
                            "model-derived snapshot write REFUSED (fail closed)",
                            ticker,
                            "no anchored execution identity for this cycle "
                            "(pre-publish anchor missing or refused)",
                        )
                        _xid_refused = True
                _snapshotrow_field_names = set(getattr(SnapshotRow, "__annotations__", {}).keys())  # caps-ok: __annotations__ always exists on any class (even empty) -- default is unreachable, not a masked bug
                _dropped_snapshot_fields = sorted(k for k in _snapshot_kwargs if k not in _snapshotrow_field_names)
                if _dropped_snapshot_fields:
                    log.warning("SnapshotRow field drift detected; dropping unsupported fields: %s", _dropped_snapshot_fields)
                if _xid_refused:
                    _srv._snapshot_row_insert_release(ticker, _snap_ts)
                elif not is_capturable_session():
                    # RC-48: off-hours (overnight / weekend / full holiday) snapshot carries
                    # no signal — options don't trade and spot doesn't move — is excluded from
                    # training (ml_train RTH filter) and read by nothing. The SSE _fetch_state
                    # path had no session gate (only the 1/min throttle), so a viewer left
                    # connected off-hours wrote a row every minute. Do not persist; release the
                    # minute reservation so throttle bookkeeping stays clean. Premarket/RTH/
                    # afterhours are unaffected (is_capturable_session is True for [04:00,20:00)
                    # ET on a trading calendar day).
                    _srv._snapshot_row_insert_release(ticker, _snap_ts)
                    log.debug("RC-48 off-hours snapshot skip: %s (session not capturable)", ticker)
                else:
                    _snap = SnapshotRow(**{k: v for k, v in _snapshot_kwargs.items() if k in _snapshotrow_field_names})
                    _ed_db.insert_snapshot(_snap)
                    _srv._snapshot_row_insert_committed(ticker, _snap_ts)
                    _snap_insert_landed = True
                    if _snapshot_kwargs.get("execution_identity_sha256"):
                        from execution_identity import mark_surface_landed as _xid_mark

                        with _ed_db._connect() as _xconn2:
                            _xid_mark(_xconn2, _snapshot_kwargs["decision_id"], "snapshot")
            # LIVE_OPERATOR_MODE_RESET_V1 Step 3 — bars persist + outcome backfill ride
            # the snapshot throttle (1/min/ticker): per-refresh writes contended with the
            # live path; bars re-seed from Schwab pricehistory after any gap and labels
            # only advance when new rows exist.
            #
            # Lane-4 (2026-07-05) measured the bar write at 8,090.8ms of the 10,760ms
            # db_snapshot_write_accuracy stage and moved it off the synchronous path onto
            # this ordered background task.
            # RC-69 (2026-07-27) went further and removed the bar write from this render
            # path ENTIRELY. Persisting bars here made COLLECTION a side-effect of DISPLAY:
            # a ticker only got bars while it was on screen. The bar collection service
            # (_bars_loop) is now the single writer, running the whole enrolled universe on
            # its own cadence, so bars are durable independently of any render and the
            # old upsert-before-fill ordering race disappears with the upsert.
            # What remains on this task is outcome labelling for the snapshot just written.
            # Schwab CSV authority checked: yes
            # CSV row(s): pricehistory.candles[].open/high/low/close/volume — persistence
            #   scheduling only; no market field read, derivation, emission, or
            #   actionability logic changed; bar values and their Schwab leaf unchanged.
            # Derived-field disposition: none required.
            # All consumers checked: yes — upsert return value unread at this call site;
            #   fill_outcomes ordering preserved by the max_workers=1 executor.
            # SCHWAB_CSV_CHECKED
            if _do_insert:
                # RC-69 SINGLE BAR FAUCET: this render path no longer PERSISTS bars. It used
                # to be the only writer, which made bar collection a side-effect of display —
                # MEASURED 2026-07-27 11:59 ET: SPY (on screen) bar lag 3.1 min vs QQQ 19.1
                # and IWM 19.1 (off screen), while all three had ~1.0 min snapshot lag, and
                # 39.8% of all snapshots carry unfilled outcomes because the forward bars they
                # needed were never written. `_bars_loop` is now the ONE writer of
                # price_bars_1m, running for every enrolled ticker regardless of the viewport.
                # The accumulator is still ticked above for this card's own forming candle.
                # fill_outcomes stays here: it labels the snapshot just inserted.
                def _bg_persist_bars_then_fill_outcomes() -> None:
                    try:
                        get_db().fill_outcomes(ticker, CANONICAL_TIMEFRAME, _snap_ts)
                    except Exception as ex:
                        log.warning(
                            "fill_outcomes_bg failed ticker=%s thread=%s: %s",
                            ticker,
                            threading.current_thread().name,
                            ex,
                        )

                _srv._get_db_fill_outcomes_executor().submit(_bg_persist_bars_then_fill_outcomes)
            # Heavy normalized-table materialize must not run from every snapshot by default;
            # set ED_LIVE_SNAPSHOT_MATERIALIZE=1 to re-enable debounced refresh on this path, or use ml_scheduler/CLI.
            if os.environ.get("ED_LIVE_SNAPSHOT_MATERIALIZE", "0").strip().lower() in (  # caps-ok: standard opt-in environment-variable read with a documented default (0 = disabled)
                "1",
                "true",
                "yes",
                "on",
            ):
                try:
                    from normalized_training_sync import schedule_debounced_normalized_refresh

                    schedule_debounced_normalized_refresh(_ed_db.db_path, logger=log)
                except Exception as _nz:
                    log.warning("schedule normalized refresh: %s", _nz)
            db_counts = _ed_db.count_snapshots(ticker, CANONICAL_TIMEFRAME)
            if _do_insert:
                log.info(f"DB snapshot logged: {ticker} total={db_counts['total']} filled={db_counts['filled']} signal={ms.rules_signal}")

            # ── Periodic accuracy tracking (~every 10 min per ticker) ─────────
            _last_acc = _srv._accuracy_cache.get(ticker, {}).get("ts", 0)  # caps-ok: first-time cache miss for a not-yet-computed ticker -- 0 correctly means 'never computed'
            if time.time() - _last_acc > ACCURACY_INTERVAL and db_counts["filled"] >= 50:
                try:
                    # RTH-scoped accuracy is the trading-relevance primary
                    # (operator decision 2026-07-06); all-hours kept as audit
                    # context only. Fail-closed: an empty RTH scope yields
                    # accuracy None — never silently widened to all-hours.
                    _acc_version = _srv._current_pred_model_version(ticker)
                    acc = _ed_db.compute_accuracy(
                        ticker, CANONICAL_TIMEFRAME,
                        model_version=_acc_version, rth_only=True,
                    )
                    _acc_all_hours = _ed_db.compute_accuracy(
                        ticker, CANONICAL_TIMEFRAME,
                        model_version=_acc_version, rth_only=False,
                    )
                    _srv._accuracy_cache[ticker] = {
                        "ts": time.time(), "results": acc, "all_hours": _acc_all_hours,
                    }
                    _acc_5c = acc.get("5c", {}).get("accuracy")  # caps-ok: PRIMARY_DECISION_HORIZONS=(1c,5c,15c,60c) guarantees compute_accuracy always populates '5c'
                    _acc_n  = acc.get("5c", {}).get("total", 0)  # caps-ok: PRIMARY_DECISION_HORIZONS=(1c,5c,15c,60c) guarantees compute_accuracy always populates '5c'
                    _acc_edge = acc.get("5c", {}).get("edge_vs_baseline_pp")  # caps-ok: PRIMARY_DECISION_HORIZONS=(1c,5c,15c,60c) guarantees compute_accuracy always populates '5c'
                    log.info(
                        f"Accuracy computed (RTH scope): {ticker} 5c={_acc_5c}% "
                        f"({_acc_n} predictions, edge_vs_baseline={_acc_edge}pp)"
                    )
                except Exception as _ae:
                    log.warning(f"Accuracy computation failed: {_ae}")
        except Exception as e:
            if _do_insert and not _snap_insert_landed:
                _srv._snapshot_row_insert_release(ticker, _snap_ts)
            _diag_crash("db_snapshot", e, ticker)
            import traceback as _tb
            _srv._analytics_cache_observability["post_publish_snapshot_failures"] += 1
            _srv._record_post_publish_failure("snapshot", ticker, published_version, e)
            log.warning(
                f"post-publish snapshot persistence failed ticker={ticker} "
                f"published_version={published_version}: {e}\n{_tb.format_exc()}"
            )
        if _diag_on():
            _diag_done("db_snapshot", ticker)
    _stage_marks.append(("db_snapshot_write_accuracy", time.perf_counter()))

    try:
        from calibration.v2_live_logging import (
            LIVE_ADVISORY_V2_TAIL_APPEND,
            append_live_v2_calibration_decision,
            resolve_live_v2_calibration_tail_action,
        )
        from db import DB_PATH as _calibration_db_path

        _xid_pair_cal = getattr(ms, "_execution_identity_pair", None)
        _tail_action = resolve_live_v2_calibration_tail_action(
            model_derived_cycle=bool(_xid_model_derived),
            has_execution_identity=_xid_pair_cal is not None,
            snap_insert_landed=bool(_snap_insert_landed),
        )
        if _tail_action != LIVE_ADVISORY_V2_TAIL_APPEND:
            # Idle/non-model skip or FP-24 no-colocated-snapshot skip.
            _v2_log_result = {"status": "skipped", "reason": _tail_action}
        else:
            _v2_log_result = append_live_v2_calibration_decision(
                db_path=_calibration_db_path,
                calibration_payload=getattr(ms, "_calibration_payload", None),
                v2_decision=v2_decision_for_log,
                decision_id=_xid_pair_cal[0] if _xid_pair_cal else None,
                execution_identity_sha256=_xid_pair_cal[1] if _xid_pair_cal else None,
                colocated_snapshot_ts_utc=float(_snap_ts),
            )
        if _v2_log_result and _v2_log_result.get("status") != "ok":
            log.debug("live v2 calibration logging skipped: %s", _v2_log_result)
        if _v2_log_result and _v2_log_result.get("status") == "ok" and _xid_pair_cal:
            from execution_identity import mark_surface_landed as _xid_mark_cal

            with get_db()._connect() as _xconn_cal:
                _xid_mark_cal(_xconn_cal, _xid_pair_cal[0], "calibration")
    except Exception as _v2_log_e:
        _srv._analytics_cache_observability["post_publish_calibration_failures"] += 1
        _srv._record_post_publish_failure("calibration", ticker, published_version, _v2_log_e)
        log.warning(
            "post-publish calibration append failed ticker=%s published_version=%s: %s",
            ticker,
            published_version,
            _v2_log_e,
        )
    _stage_marks.append(("v2_calibration_logging", time.perf_counter()))
