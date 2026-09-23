"""Decision phase of _fetch_state (server.py): MarketState build, the pre-publish v2 decision,
and the execution-identity anchor, extracted (RC-REHAB-1, 2026-09-23). Thirty-fifth slice of
the _fetch_state decomposition -- see server_state_volatility.py's own docstring for why this
decomposition exists.

- _emission_gate_for_state: RC-534 -- the decision route class and market-data sanity facts
  The Call consumes, computed ONCE before the state is built.
- _build_market_state_for_state: the adapter from the earlier phases' NamedTuples to
  build_market_state's keyword contract. Before this slice, _fetch_state unpacked every phase
  result into ~45 locals just to thread them into this one call.
- _v2_decision_for_state: FIX_B_PUBLISH_BEFORE_LOG_REORDER_V1 -- the decision is computed
  BEFORE the bundle publish, and the SAME object is served and logged.
- _anchor_execution_identity_for_state: EXEC_IDENTITY_DECISION_SURFACE_ORDERING_V1 -- the ONE
  (decision_id, execution_identity) pair is anchored before every governed consumer.

MONKEYPATCH/RUNTIME-STATE NOTE: server.py-owned names (_ms_to_dict,
_attach_stack_runtime_and_governance's re-export, _apply_trader_horizon_contract,
_snapshot_row_insert_allowed, _get_prediction_override, the crash-trace hooks, the
_candles_1m/_candles_5m singletons, RTH_CLOSE_MINS) are reached through the lazy
`import server` pattern.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

from live_decision_bundle import stamp_decision_bundle
from market_state import build_market_state
from v2_decision import build_module_a_a1_decision
from v2_decision.a1_conformal_artifact_attachment import attach_a1_conformal_artifact_to_ms_dict
from v2_decision.a1_isotonic_calibration_attachment import attach_a1_isotonic_calibration_to_ms_dict
import stack_runtime_governance

log = logging.getLogger(__name__)


def _emission_gate_for_state(update_source: Optional[str], *, ticker: str, spot_f,
                             spread_age_ms) -> tuple[str, Any]:
    """RC-534: the emission facts The Call must consume -- decision route class + market-data
    sanity (ticker, spot, spread age) -- computed ONCE by the gate's own validator on the facts
    known before the state is built, and handed to the owner through SignalInput. The Call
    vetoes itself; the post-build gate in stamp_decision_bundle stamps quarantine and blocks
    decision_id / persistence and REWRITES NOTHING."""
    from trade_impacting_gate import resolve_fetch_state_decision_route, validate_trade_impacting_gate

    route = resolve_fetch_state_decision_route(update_source)
    gate = validate_trade_impacting_gate(
        {"ticker": ticker, "spot": spot_f, "spread_age_ms": spread_age_ms}, route=route,
    )
    return route, gate


def _build_market_state_for_state(
    *, ticker: str, selected_exp: str, session_label, contracts_use, q, exp, gfvz, charm, cd,
    em, vs, garch_sigma_bars, ofs, pp, ves, zt: dict, dbcc, price_levels, mkt_ctx, c_vol,
    order_flow_data, db, now_et, refresh_ts_utc, emission_gate,
):
    import server as _srv

    et_h, et_m = now_et.hour, now_et.minute
    if _srv._diag_on():
        _srv._diag_step("pre_build_market_state", ticker)
    try:
        ms = build_market_state(
            ticker=ticker,
            selected_exp=selected_exp,
            session_label=session_label,
            spot=exp.spot_f,
            bid=q.bid,
            ask=q.ask,
            consensus_summary=gfvz.consensus_summary,
            contracts_use=contracts_use,
            walls=exp.walls,
            totals=exp.totals,
            price_levels=price_levels,
            mkt_ctx=mkt_ctx,
            vol_ctx=ves.vol_ctx,
            live_on=True,
            zone_since_bars=zt["since_bars_1m"],
            zone_since_bars_5m=zt["since_bars_5m"],
            prev_zone=zt["prev_zone"],
            ceiling_tests_today=dbcc.ceil_tests,
            floor_tests_today=dbcc.floor_tests,
            recent_crosses=dbcc.recent_crosses,
            total_snapshots=dbcc.db_counts["total"],  # always keyed; None = unknown
            filled_snapshots=dbcc.db_counts["filled"],
            et_hour=et_h,
            et_minute=et_m,
            mins_to_close=max(0.0, _srv.RTH_CLOSE_MINS - (et_h * 60 + et_m)),
            candle_direction=cd.candle_dir,
            candle_body_pts=cd.candle_body,
            candles_5m=_srv._candles_5m.get_bars(ticker),
            candles_1m=_srv._candles_1m.get_bars(ticker),
            charm_net=charm.charm_net,
            charm_direction=charm.charm_dir,
            charm_drift_toward=charm.charm_toward,
            charm_magnitude=charm.charm_mag,
            charm_top_drivers=charm.charm_drivers,
            # RC-292/RC-295: terrain SSOT absolute-gamma strike — the same fail-closed read
            # the pin score uses (None when the terrain cache is absent or stale).
            absolute_gamma_strike=pp.pin_strike,
            # Cursor-audit F9: dealer gamma AT SPOT — the regime SIGN authority — read from the
            # TERRAIN SSOT (the full multi-expiry capture book the terrain card renders as
            # net_gex_at_spot), never the selected-expiry slice. Fail-closed: no or stale
            # terrain snapshot -> None and the consumers emit NO regime claim.
            net_gamma_at_spot=pp.regime_gamma_at_spot,
            iv_direction=gfvz.iv_direction,
            em_upper=em.em_up,
            em_lower=em.em_lo,
            mc_iv_level=em.mc_iv_level,
            mc_em_anchor=em.kl_em_anchor,
            mc_iv_source=em.mc_iv_source,
            realized_vol=vs.realized_vol,
            atr=vs.atr,
            garch_sigma_bars=garch_sigma_bars,
            candle_volume=c_vol,
            flow_imbalance=ofs.flow_imb_norm,
            spread=q.spread_pts,
            iv_rank=vs.iv_rank,
            smart_money_score=ofs.smart_money.get("score") if ofs.smart_money else None,
            breakout_score=pp.breakout_score.get("normalized") if pp.breakout_score else None,
            pin_score=pp.pin_score_val.get("normalized") if pp.pin_score_val else None,
            order_flow_data=order_flow_data,
            db=db,
            pred_override=_srv._get_prediction_override(ticker),
            refresh_ts_utc=refresh_ts_utc,
            emission_gate=emission_gate,
        )
    except Exception as _bms_e:
        _srv._diag_crash("build_market_state", _bms_e, ticker)
        raise
    if _srv._diag_on():
        _srv._diag_done("build_market_state", ticker)
    return ms


def _v2_decision_for_state(ms, *, ticker: str, selected_exp: str,
                           refresh_ts_utc: float) -> tuple[Optional[dict], Optional[dict]]:
    """(served-and-logged v2 decision, the v2 logging ms_dict the identity anchor reads).
    A build failure is logged and yields (None, <dict so far or None>) -- the full-path
    publish then builds the decision from the served payload instead."""
    import server as _srv

    decision = None
    logging_ms_dict = None
    try:
        logging_ms_dict = _srv._ms_to_dict(ms)
        logging_ms_dict["selected_exp"] = selected_exp
        logging_ms_dict["decision_time_ms"] = int(refresh_ts_utc * 1000)
        logging_ms_dict["_server_build_ts"] = time.time()
        stack_runtime_governance._attach_stack_runtime_and_governance(logging_ms_dict, ticker=ticker)
        _srv._apply_trader_horizon_contract(logging_ms_dict)
        stamp_decision_bundle(logging_ms_dict)
        attach_a1_conformal_artifact_to_ms_dict(logging_ms_dict, ticker=ticker)
        attach_a1_isotonic_calibration_to_ms_dict(logging_ms_dict, ticker=ticker)
        decision = build_module_a_a1_decision(logging_ms_dict)
    except Exception as _v2_build_e:
        log.warning("v2 decision build failed: %s", _v2_build_e)
    return decision, logging_ms_dict


def _calibration_info(v2md: dict) -> Optional[dict]:
    """Exact calibration state USED by this cycle's decision (attached at the v2 build,
    BEFORE the anchor); None records its absence explicitly."""
    conf = v2md.get("a1_conformal_artifact")
    iso_lineage = v2md.get("a1_calibrated_probability_lineage_id")
    if not (isinstance(conf, dict) or iso_lineage):
        return None
    return {
        str(v2md.get("primary_horizon") or "1c"): {  # caps-ok: identity-ledger KEY only; primary_horizon is always stamped by _apply_trader_horizon_contract before this read, "1c" is the live inference horizon default it mirrors
            "conformal": (
                {k: conf.get(k)
                 for k in ("run_id", "lineage_id", "artifact_id", "created_at", "horizon", "ticker")
                 if conf.get(k) is not None}
                if isinstance(conf, dict) else None
            ),
            "isotonic_lineage_id": iso_lineage,
        }
    }


def _anchor_execution_identity_for_state(
    ms, *, ticker: str, db, refresh_ts_utc: float, v2_decision: Optional[dict],
    v2_logging_ms_dict: Optional[dict], log_only: bool, decision_route: str,
) -> tuple[bool, bool]:
    """EXEC_IDENTITY_DECISION_SURFACE_ORDERING_V1 -- returns (do_snapshot_insert, model_derived).

    Anchors the ONE (decision_id, execution_identity) pair for this cycle BEFORE every
    governed consumer: the production-decision finalize (full path), the log_only early
    return, and the post-publish persistence tail. Root cause of the 2026-07-13 RTH
    contradiction: the anchor lived inside the tail, which ran AFTER finalize, so stamping
    minted a decision_id with no identity and the linkage trigger refused every write.
    expected_surfaces mirror the cycle's REAL writers: "decision" only when this cycle
    finalizes on a production route (never log_only), "snapshot" only when the per-minute
    throttle admits this cycle, "calibration" only when logging is on and the payload + served
    v2 decision exist. A writer-side divergence after anchoring leaves the ledger OPEN.

    Schwab CSV authority checked: yes
    CSV row(s): NO_SCHWAB_EQUIVALENT — provenance anchor ordering only.
    Derived-field disposition: none required.
    All consumers checked: yes — finalize, tail snapshot kwargs, tail calibration append, v2
      logging dict all consume the one anchored pair.
    SCHWAB_CSV_CHECKED
    """
    import server as _srv

    do_snapshot_insert = False
    if db:
        try:
            # Reservation hoisted from the tail (same key: ticker + refresh ts; still exactly
            # one reservation per cycle). The tail releases it on a failed insert.
            do_snapshot_insert = bool(_srv._snapshot_row_insert_allowed(ticker, refresh_ts_utc, db=db))
        except Exception as _thr_e:
            log.warning("snapshot throttle reservation failed ticker=%s: %s", ticker, _thr_e)
    # The model-derived predicate reads the SAME source the snapshot writer uses (the tail
    # sets combined_signal=ms.call_signal).
    model_derived = ms.call_signal is not None
    if not (db and model_derived):
        return do_snapshot_insert, model_derived

    from calibration.writer import calibration_logging_enabled
    from decision_record import new_decision_id
    from execution_identity import ExecutionIdentityError, anchor_production_execution
    from trade_impacting_gate import classify_route

    v2md = v2_logging_ms_dict
    # ONE cycle = ONE decision: the v2 build's stamped decision_id is the single owner.
    decision_id = str(v2md.get("decision_id") or "") or new_decision_id()
    expected_decision = (
        (not log_only)
        and bool(v2md.get("decision_id"))
        # The ONE route resolved by _emission_gate_for_state (RC-534); the anchor used to
        # re-resolve it from update_source under an alias -- one route per fetch now.
        and classify_route(decision_route) == "production"
    )
    # FP-24: expect calibration only when this cycle reserved a snapshot slot -- otherwise
    # decision_ts drifts past tol=29 from the minute's single snapshot.
    expected_cal = bool(
        calibration_logging_enabled()
        and getattr(ms, "_calibration_payload", None)
        and v2_decision is not None
        and do_snapshot_insert
    )
    surfaces = [name for name, on in (("decision", expected_decision),
                                      ("snapshot", do_snapshot_insert),
                                      ("calibration", expected_cal)) if on]
    if surfaces:
        try:
            with db._connect() as conn:
                sha = anchor_production_execution(
                    requested_ticker=ticker,
                    serving_provenance=ms.model_serving_provenance_v1,
                    calibration_info=_calibration_info(v2md),
                    db_conn=conn,
                    decision_id=decision_id,
                    executed_at_utc=float(refresh_ts_utc),
                    expected_surfaces=surfaces,
                )
        except ExecutionIdentityError as exc:
            log.error(
                "EXECUTION_IDENTITY_REFUSED ticker=%s reason=%s — every model-derived "
                "persistence surface REFUSED this cycle (fail closed)", ticker, exc,
            )
        else:
            setattr(ms, "_execution_identity_pair", (decision_id, sha))
            v2_logging_ms_dict["decision_id"] = decision_id
            v2_logging_ms_dict["execution_identity_sha256"] = sha
    return do_snapshot_insert, model_derived
