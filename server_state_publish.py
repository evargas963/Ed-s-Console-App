"""Finalize-and-publish phase of _fetch_state (server.py), extracted (RC-REHAB-1, 2026-09-23).
Thirty-seventh slice of the _fetch_state decomposition -- see server_state_volatility.py's own
docstring for why this decomposition exists.

_finalize_and_publish_state runs, in the original order:
  1. stack runtime / governance attach + trader-horizon contract;
  2. execution-identity seed -> production-decision finalize -> "decision" surface landing
     (EXEC_IDENTITY_DECISION_SURFACE_ORDERING_V1: only a write that actually landed marks it);
  3. cycle timing: _pipeline/_chain/_quote/_compute ms + the lane-3 stage breakdown + the UI_05
     chain-window attribution;
  4. v2 decision attach (the SAME object the persistence tail logs) + live-plane merge;
  5. version bump, level-cross detection, the generated_at-stamping cache write, expiry
     eviction, DB-contention surface, operator field lineage;
  6. post-pipeline observability (finalize-tail ms, cache counters, last post-publish errors).
It returns the published analytics_version, which the post-publish persistence tail
(FIX_B_PUBLISH_BEFORE_LOG_REORDER_V1) consumes AFTER this publish.

MONKEYPATCH/RUNTIME-STATE NOTE: server.py-owned state (_state_cache,
_analytics_cache_observability, _post_publish_last_errors, _lmp) and helpers
(_finalize_production_decision, _apply_trader_horizon_contract, the
_attach_stack_runtime_and_governance re-export, _evict_old_expiry_entries,
_attach_db_contention_operator_surface, get_db) are reached through the lazy `import server`
pattern; the dicts are MUTATED in place, never rebound.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Optional

from v2_decision import build_module_a_a1_decision
from v2_decision.a1_conformal_artifact_attachment import attach_a1_conformal_artifact_to_ms_dict
from v2_decision.a1_isotonic_calibration_attachment import attach_a1_isotonic_calibration_to_ms_dict
import stack_runtime_governance

log = logging.getLogger(__name__)


def _finalize_decision(ms_dict: dict, ms, *, ticker: str, decision_route: str,
                       stage_marks: list) -> None:
    import server as _srv

    stack_runtime_governance._attach_stack_runtime_and_governance(ms_dict, ticker=ticker)
    stage_marks.append(("stack_runtime_governance_attach", time.perf_counter()))
    if ms_dict.get("signals_engine_failed"):
        sr = ms_dict.get("stack_runtime")
        if isinstance(sr, dict):
            sr["signals_engine_failed"] = True
    _srv._apply_trader_horizon_contract(ms_dict)
    # execution_identity_v1: one cycle = one decision_id = one identity. Seed the anchored
    # pair so stamping binds the SAME decision the snapshot carries. decision_route is the
    # ONE route resolved before build_market_state (RC-534).
    xid_pair = getattr(ms, "_execution_identity_pair", None)
    if xid_pair:
        ms_dict["decision_id"] = xid_pair[0]
        ms_dict["execution_identity_sha256"] = xid_pair[1]
    _srv._finalize_production_decision(ms_dict, decision_route)
    if (
        xid_pair
        and ms_dict.get("decision_id") == xid_pair[0]
        and not ms_dict.get("decision_generation_skipped")
        # EXEC_IDENTITY_DECISION_SURFACE_ORDERING_V1: only a write that actually landed marks
        # the "decision" surface — a refused/skipped persist leaves the ledger honestly OPEN.
        and ms_dict.get("_decision_persist_landed")
    ):
        try:
            from execution_identity import mark_surface_landed

            with _srv.get_db()._connect() as conn:
                mark_surface_landed(conn, xid_pair[0], "decision")
        except Exception as exc:
            log.error("execution identity decision-surface landing failed: %s", exc)
    stage_marks.append(("payload_assembly_model_health_finalize", time.perf_counter()))


def _stamp_cycle_timing(ms_dict: dict, *, ticker: str, expiry: Optional[str],
                        update_source: Optional[str], fetch_start_mono: float, cq,
                        stage_t0: float, stage_marks: list, chain_window_marks: list) -> float:
    """Stamp the cycle's timing split; returns the pipeline-end monotonic time."""
    t_end = time.monotonic()
    ms_dict["_server_build_ts"] = time.time()
    ms_dict["_pipeline_ms"] = round((t_end - fetch_start_mono) * 1000)
    ms_dict["_chain_ms"] = round((cq.t_after_chain_mono - fetch_start_mono) * 1000)
    ms_dict["_quote_ms"] = round((cq.t_after_quote_mono - cq.t_after_chain_mono) * 1000)
    ms_dict["_compute_ms"] = round((t_end - cq.t_after_quote_mono) * 1000)
    # Lane-3 diagnostic: stage split of _compute_ms (+ chain/quote copies for one-stop reads).
    stage_ms: dict[str, float] = {}
    prev = stage_t0
    for name, pc in stage_marks:
        stage_ms[name] = round((pc - prev) * 1000.0, 1)
        prev = pc
    # Chain gate: schwab_chain_ms is the PURE Schwab fetch (helper-measured); gate wait is
    # split out; _chain_ms keeps its wall-clock-to-chain meaning.
    stage_ms["schwab_chain_ms"] = (
        round(cq.chain_fetch_pure_sec * 1000.0, 1)
        if cq.chain_fetch_pure_sec is not None
        else float(ms_dict["_chain_ms"])
    )
    stage_ms["chain_gate_wait_ms"] = round(cq.chain_gate_wait_sec * 1000.0, 1)
    stage_ms["schwab_quote_ms"] = float(ms_dict["_quote_ms"])
    # UI_05 tail attribution: consecutive deltas across the _chain_ms window
    # (preamble | mkt_ctx | leaf submit->result wall | contracts parse).
    prev = fetch_start_mono
    for name, mono in chain_window_marks:
        stage_ms[name] = round((mono - prev) * 1000.0, 1)
        prev = mono
    ms_dict["chain_gate_wait_sec"] = cq.chain_gate_wait_sec
    ms_dict["_compute_breakdown"] = dict(stage_ms)
    log.info(
        f"_fetch_state: {ticker} pipeline_ms={ms_dict['_pipeline_ms']} "
        f"quote_ms={ms_dict['_quote_ms']} chain_ms={ms_dict['_chain_ms']} compute_ms={ms_dict['_compute_ms']} expiry={expiry}"
    )
    log.info("_fetch_state_breakdown: %s %s", ticker, json.dumps(stage_ms, sort_keys=True))
    if update_source is not None:
        ms_dict["_update_source"] = update_source
    return t_end


def _detect_level_crosses(ms_dict: dict, prev_ent: dict, *, ticker: str, spot_f, db,
                          gen_ts: float) -> None:
    """Pass 4: writer for level_crosses (consumer: /api/level_crosses + the Decision Command
    "third test of ceiling" pattern via db.count_level_tests). Debounced by
    (ticker, level_name, direction) per EdDB.LEVEL_CROSS_DEBOUNCE_S."""
    if db is None:
        return
    try:
        from live_decision_bundle import _key_levels_from_ms_dict
        from time_et import now_et

        prev_spot = prev_ent.get("spot_f")
        levels = _key_levels_from_ms_dict(ms_dict)
        if prev_spot is None or spot_f is None or not levels:
            return
        crosses = db.detect_and_log_level_crosses(
            ticker=ticker,
            prev_spot=float(prev_spot),
            cur_spot=float(spot_f),
            levels=levels,
            ts_utc=gen_ts,
            ts_et=now_et().strftime("%Y-%m-%d %H:%M:%S ET"),
            timeframe="1m",
            zone_before=(prev_ent.get("ms_dict") or {}).get("zone"),
            zone_after=ms_dict.get("zone"),
        )
        for xc in crosses:
            log.info(
                "level_cross ticker=%s level=%s value=%.2f direction=%s spot=%.2f",
                ticker, xc["level_name"], xc["level_value"], xc["direction"], xc["spot_at_cross"],
            )
    except Exception as exc:
        log.debug("level cross detection failed ticker=%s: %s", ticker, exc)


def _finalize_and_publish_state(
    ms_dict: dict, ms, *, ticker: str, expiry: Optional[str], selected_exp: str,
    cache_key: tuple, update_source: Optional[str], decision_route: str,
    v2_decision: Optional[dict], spot_f, pcr_val, vol_ctx, db, fetch_start_mono: float, cq,
    stage_t0: float, stage_marks: list, chain_window_marks: list,
) -> int:
    """Finalize the decision, stamp timing, publish to _state_cache; returns the version."""
    import server as _srv
    from market_state import attach_operator_visible_field_lineage

    _finalize_decision(ms_dict, ms, ticker=ticker, decision_route=decision_route,
                       stage_marks=stage_marks)
    t_pipeline_end = _stamp_cycle_timing(
        ms_dict, ticker=ticker, expiry=expiry, update_source=update_source,
        fetch_start_mono=fetch_start_mono, cq=cq, stage_t0=stage_t0,
        stage_marks=stage_marks, chain_window_marks=chain_window_marks,
    )

    attach_a1_conformal_artifact_to_ms_dict(ms_dict, ticker=ticker)
    attach_a1_isotonic_calibration_to_ms_dict(ms_dict, ticker=ticker)
    ms_dict["v2_decision"] = v2_decision or build_module_a_a1_decision(ms_dict)
    _srv._lmp.merge_into_state(ms_dict, ticker)

    prev_ent = _srv._state_cache.get(cache_key) or {}
    gen_ts = time.time()
    next_ver = int(prev_ent.get("analytics_version", 0)) + 1  # caps-ok: generation counter increment -- no previous version means 0 so the first published bundle is version 1
    if not prev_ent:
        # Version restarts at 1 — a cold entry write (fresh key or prior eviction).
        _srv._analytics_cache_observability["cold_entry_writes"] += 1
    _detect_level_crosses(ms_dict, prev_ent, ticker=ticker, spot_f=spot_f, db=db, gen_ts=gen_ts)

    _srv._state_cache[cache_key] = {
        "ts": gen_ts,
        "generated_at": gen_ts,
        "analytics_version": next_ver,
        "ms_dict": ms_dict, "pcr_val": pcr_val, "spot_f": spot_f,
        # VOL_INPUT_CONTRACT 1.0.0 single-source: publish the context level — this is the
        # value the next cycle's market_iv_change diffs against.
        "vix": vol_ctx.market_iv_level,
        "price_levels": prev_ent.get("price_levels"),
        "pl_date": prev_ent.get("pl_date", ""),  # caps-ok: price-level cache-validity key carried forward; "" never matches today's date -> cache MISS (refetch)
        "pl_generation": prev_ent.get("pl_generation"),
        "pl_mono": prev_ent.get("pl_mono"),
    }
    _srv._evict_old_expiry_entries(ticker, selected_exp)
    _srv._attach_db_contention_operator_surface(ms_dict)
    attach_operator_visible_field_lineage(ms_dict)
    # TIER_C_STAGE_TIMER_INSTRUMENTATION_V1 — the post-pipeline tail (merge_into_state,
    # level-cross detection, cache write, eviction, lineage) runs AFTER _pipeline_ms stops;
    # time it separately so cycle totals attribute fully. Passive observation.
    ms_dict["_finalize_tail_ms"] = round((time.monotonic() - t_pipeline_end) * 1000)
    ms_dict["analytics_cache_observability_v1"] = dict(_srv._analytics_cache_observability)
    # EXEC-03 POST_PUBLISH_LAST_ERROR_OBSERVABILITY_V1 — failure cause detail for the counters
    # above; recorded by the tail, so it reflects failures up to the PREVIOUS cycle.
    ms_dict["post_publish_last_errors_v1"] = {
        k: dict(v) for k, v in _srv._post_publish_last_errors.items()
    }
    return next_ver
