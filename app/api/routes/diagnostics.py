"""Operator diagnostics API routes: L1 runtime, ticker-switch timing, SQLite contention,
chain-fetch gate (RC-REHAB-1, Phase 3).

Unlike the terrain diagnostics route (which moved with its own domain into terrain.py),
these five routes span five unrelated subsystems and share nothing with each other -- they
are grouped here only because they share the /api/diagnostics URL namespace, the same way
app/api/routes/ops.py already groups disparate operator-facing routes. Each route's own
shared module state stays in server.py and is imported back lazily, per the established
pattern.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Body, Query
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/api/diagnostics/l1")
def get_l1_diagnostics():
    """
    L1 operational metrics: build counts, reason histogram, cache hits/skips, policy constants.
    For live validation and tuning materiality / TTL without log scraping.
    """
    from planes.l1_runtime import (
        L1_CACHE_ENTRY_TTL_SEC,
        L1_HTTP_SERVE_MAX_AGE_SEC,
        L1_MAX_CACHE_SCOPES,
        L1_OF_MIN_COMPUTE_INTERVAL_SEC,
        L1_OF_PROBE_FORCE_REFRESH_SEC,
        L1_ORDER_FLOW_STALE_SEC,
    )
    from planes.l1_cache_lifecycle import l1_cache_invariants
    from planes.l1_operational import build_l1_operational_assessment
    from server import (
        _l1_adaptive_materiality_context,
        _l1_diag_start_mono,
        _l1_instrumentation,
        _l1_scope_lru,
        _l1_snapshot_cache,
        _l1_sse_light_diag_payload,
        _lmp,
    )

    bt = int(_l1_instrumentation["l1_build_total"])
    # RC-291: divide by builds whose timing was MEASURED, not by all builds. Dividing a sum
    # that excludes unmeasured builds by a count that includes them understates the average
    # and can hold it under the warn threshold — measured at 24.7 ms for a true 26.0 ms.
    bt_measured = int(_l1_instrumentation["l1_build_ms_measured"])
    avg_ms = float(_l1_instrumentation["l1_build_ms_sum"]) / max(1, bt_measured)
    reasons = {str(k): int(v) for k, v in _l1_instrumentation["l1_build_by_reason"].items()}
    uptime_sec = max(0.0, time.monotonic() - _l1_diag_start_mono)
    operational = build_l1_operational_assessment(
        # RC-293: the TRUE build count drives the rate alarm; the TIMED count drives the
        # latency average. RC-291 passed bt_measured as l1_build_total, which fixed the
        # average and made builds_per_min report timed builds — a true 500/min read as
        # 100/min and graded healthy. Two questions, two inputs.
        l1_build_total=bt,
        timing_sample_count=bt_measured,
        l1_build_ms_sum=float(_l1_instrumentation["l1_build_ms_sum"]),
        reasons=reasons,
        l1_http_cache_hit_total=int(_l1_instrumentation["l1_http_cache_hit_total"]),
        l1_quote_material_skip_total=int(_l1_instrumentation["l1_quote_material_skip_total"]),
        l1_cache_eviction_total=int(_l1_instrumentation["l1_cache_eviction_total"]),
        l1_of_quote_hook_engine_total=int(_l1_instrumentation["l1_of_quote_hook_engine_total"]),
        l1_of_quote_hook_reuse_total=int(_l1_instrumentation["l1_of_quote_hook_reuse_total"]),
        cache_scope_count=len(_l1_snapshot_cache),
        l1_max_cache_scopes=L1_MAX_CACHE_SCOPES,
        uptime_sec=uptime_sec,
    )
    sample = []
    for k, v in list(_l1_snapshot_cache.items())[:64]:
        inst = v.get("l1_instrumentation") or {}
        sample.append(
            {
                "scope": {"ticker": k[0], "expiry": k[1]},
                "as_of_ts": v.get("as_of_ts"),
                "l1_build_reason_last": inst.get("l1_build_reason"),
            }
        )
    now_diag = time.time()
    from planes.l1_thresholds import resolve_l1_materiality_engine

    row_spy = _lmp.get_quote("SPY") or {}
    ctx_spy = _l1_adaptive_materiality_context("SPY", row_spy, now_diag)
    res_spy = resolve_l1_materiality_engine("SPY", context=ctx_spy)
    row_penny = {"spot": 4.5, "spread": 0.002}
    ctx_penny = _l1_adaptive_materiality_context("XYZ", row_penny, now_diag)
    res_penny = resolve_l1_materiality_engine("XYZ", context=ctx_penny)
    l1_adaptive_materiality = {
        "l1_materiality_engine_schema_version": 1,
        "sample_spy_adaptive": res_spy.as_dict(),
        "sample_penny_equity_adaptive": res_penny.as_dict(),
        "context_inputs_spy": {
            "session_label": ctx_spy.session_label,
            "vix_level": ctx_spy.vix_level,
            "spot": ctx_spy.spot,
            "spread_frac": ctx_spy.spread_frac,
        },
        "context_inputs_penny_sample": {
            "session_label": ctx_penny.session_label,
            "vix_level": ctx_penny.vix_level,
            "spot": ctx_penny.spot,
            "spread_frac": ctx_penny.spread_frac,
        },
        "static_defaults_reference": resolve_l1_materiality_engine("SPY", context=None).as_dict(),
    }

    return JSONResponse(
        {
            "ed_l1": {
                "schema_version": 2,
                "l1_diag_uptime_sec": round(uptime_sec, 4),
                "l1_build_total": bt,
                "l1_build_ms_avg": round(avg_ms, 4),
                "l1_build_ms_sum": float(_l1_instrumentation["l1_build_ms_sum"]),
                "l1_build_by_reason": reasons,
                "l1_http_cache_hit_total": int(_l1_instrumentation["l1_http_cache_hit_total"]),
                "l1_quote_material_skip_total": int(_l1_instrumentation["l1_quote_material_skip_total"]),
                "l1_cache_eviction_total": int(_l1_instrumentation["l1_cache_eviction_total"]),
                "l1_cache_eviction_ttl_total": int(_l1_instrumentation["l1_cache_eviction_ttl_total"]),
                "l1_cache_eviction_cap_total": int(_l1_instrumentation["l1_cache_eviction_cap_total"]),
                "l1_cache_reconcile_lru_pruned_total": int(_l1_instrumentation["l1_cache_reconcile_lru_pruned_total"]),
                "l1_cache_reconcile_lru_backfilled_total": int(
                    _l1_instrumentation["l1_cache_reconcile_lru_backfilled_total"]
                ),
                "l1_cache_lifecycle": l1_cache_invariants(_l1_snapshot_cache, _l1_scope_lru),
                "l1_of_quote_hook_engine_total": int(_l1_instrumentation["l1_of_quote_hook_engine_total"]),
                "l1_of_quote_hook_reuse_total": int(_l1_instrumentation["l1_of_quote_hook_reuse_total"]),
                "l1_cache_scope_count": len(_l1_snapshot_cache),
                "l1_lru_order_len": len(_l1_scope_lru),
                "policy": {
                    "L1_CACHE_ENTRY_TTL_SEC": L1_CACHE_ENTRY_TTL_SEC,
                    "L1_HTTP_SERVE_MAX_AGE_SEC": L1_HTTP_SERVE_MAX_AGE_SEC,
                    "L1_MAX_CACHE_SCOPES": L1_MAX_CACHE_SCOPES,
                    "L1_ORDER_FLOW_STALE_SEC": L1_ORDER_FLOW_STALE_SEC,
                    "L1_OF_MIN_COMPUTE_INTERVAL_SEC": L1_OF_MIN_COMPUTE_INTERVAL_SEC,
                    "L1_OF_PROBE_FORCE_REFRESH_SEC": L1_OF_PROBE_FORCE_REFRESH_SEC,
                },
                "cached_scopes_sample": sample,
                "operational": operational,
                "l1_adaptive_materiality": l1_adaptive_materiality,
                "l1_sse_light": _l1_sse_light_diag_payload(),
            }
        }
    )


@router.post("/api/diagnostics/ticker-switch")
def post_ticker_switch_diagnostics(payload: dict = Body(default={})):
    """Ingest client ticker-switch timing records into in-memory ring buffer."""
    from ticker_switch_diagnostics import record_switch_event

    record_switch_event(payload if isinstance(payload, dict) else {})
    return JSONResponse({"ok": True})


@router.get("/api/diagnostics/ticker-switch")
def get_ticker_switch_diagnostics(limit: int = Query(50, ge=1, le=200)):
    """Recent ticker-switch timing events (newest first)."""
    from ticker_switch_diagnostics import get_recent_events

    return JSONResponse({"events": get_recent_events(limit), "buffer_max": 100})


@router.get("/api/diagnostics/sqlite-contention")
def get_sqlite_contention_diagnostics():
    """
    Tier-1 SQLite lock-wait / busy / locked counters (process-local).

    For operator trust audits — does not change retry policy. See Card Trust Contract §8.
    """
    from db import sqlite_contention_metrics_snapshot
    from verification.db_sqlite_contention_impact_audit import (
        build_db_contention_operator_surface,
    )

    metrics = sqlite_contention_metrics_snapshot()
    return JSONResponse(
        {
            **metrics,
            "operator": build_db_contention_operator_surface(metrics),
        }
    )


@router.get("/api/diagnostics/chain-gate")
def api_chain_gate_diagnostics():
    """Read-only chain-gate observability: slots, waits, coalescing, breaker."""
    from server import (
        CHAIN_FETCH_GATE_ACQUIRE_TIMEOUT_SEC,
        CHAIN_GATE_BREAKER_COOLDOWN_SEC,
        CHAIN_GATE_BREAKER_FAILURE_THRESHOLD,
        _chain_fetch_gate_timeout_count,
        _chain_inflight,
        _chain_inflight_lock,
        _schwab_chain_fetch_gate,
    )

    with _chain_inflight_lock:
        # Keys are (ticker, strike_count); render as SPY@20 for operators.
        inflight = sorted(
            f"{k[0]}@{k[1]}" if isinstance(k, tuple) and len(k) == 2 else str(k)
            for k in _chain_inflight
        )
    return {
        "gate": _schwab_chain_fetch_gate.snapshot(),
        "inflight_tickers": inflight,
        "acquire_timeout_sec": CHAIN_FETCH_GATE_ACQUIRE_TIMEOUT_SEC,
        "fail_open_timeout_count": _chain_fetch_gate_timeout_count,
        "breaker_cooldown_sec": CHAIN_GATE_BREAKER_COOLDOWN_SEC,
        "breaker_failure_threshold": CHAIN_GATE_BREAKER_FAILURE_THRESHOLD,
    }
