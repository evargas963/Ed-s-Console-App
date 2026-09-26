"""
L1 operational thresholds and health assessment for /api/diagnostics/l1.

Tuned for: single _project_l1 authority, cache-first HTTP, debounced quote hooks,
OF probe optimization. Values are conservative to limit false positives during warm-up.
"""

from __future__ import annotations

import os
from typing import Any


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


# --- Configurable via environment (defaults below) ---
L1_OP_MIN_UPTIME_SEC_FOR_RATES = _env_float("L1_OP_MIN_UPTIME_SEC_FOR_RATES", 45.0)
L1_OP_MIN_BUILDS_FOR_LATENCY = _env_int("L1_OP_MIN_BUILDS_FOR_LATENCY", 15)

L1_OP_MAX_AVG_BUILD_MS_WARN = _env_float("L1_OP_MAX_AVG_BUILD_MS_WARN", 25.0)
L1_OP_MAX_AVG_BUILD_MS_CRITICAL = _env_float("L1_OP_MAX_AVG_BUILD_MS_CRITICAL", 80.0)

L1_OP_MAX_BUILDS_PER_MIN_WARN = _env_float("L1_OP_MAX_BUILDS_PER_MIN_WARN", 120.0)
L1_OP_MAX_BUILDS_PER_MIN_CRITICAL = _env_float("L1_OP_MAX_BUILDS_PER_MIN_CRITICAL", 400.0)

L1_OP_MIN_OF_HOOK_EVENTS = _env_int("L1_OP_MIN_OF_HOOK_EVENTS", 12)
L1_OP_MIN_OF_REUSE_RATIO_WARN = _env_float("L1_OP_MIN_OF_REUSE_RATIO_WARN", 0.35)
L1_OP_MIN_OF_REUSE_RATIO_CRITICAL = _env_float("L1_OP_MIN_OF_REUSE_RATIO_CRITICAL", 0.12)

L1_OP_MIN_HTTP_EVENTS = _env_int("L1_OP_MIN_HTTP_EVENTS", 20)
L1_OP_MIN_HTTP_CACHE_HIT_RATIO_WARN = _env_float("L1_OP_MIN_HTTP_CACHE_HIT_RATIO_WARN", 0.35)

L1_OP_MAX_EVICTIONS_PER_MIN_WARN = _env_float("L1_OP_MAX_EVICTIONS_PER_MIN_WARN", 8.0)
L1_OP_MAX_EVICTIONS_PER_MIN_CRITICAL = _env_float("L1_OP_MAX_EVICTIONS_PER_MIN_CRITICAL", 30.0)

L1_OP_CACHE_SCOPE_PRESSURE_RATIO_WARN = _env_float("L1_OP_CACHE_SCOPE_PRESSURE_RATIO_WARN", 0.92)

L1_OP_MIN_STALE_EVENTS = _env_int("L1_OP_MIN_STALE_EVENTS", 8)
L1_OP_MAX_STALE_REBUILDS_PER_MIN_WARN = _env_float("L1_OP_MAX_STALE_REBUILDS_PER_MIN_WARN", 25.0)


def _worst(a: str, b: str) -> str:
    order = {"healthy": 0, "unknown": 1, "warning": 2, "critical": 3}
    return a if order.get(a, 0) >= order.get(b, 0) else b


def build_l1_operational_assessment(
    *,
    l1_build_total: int,
    l1_build_ms_sum: float,
    #: RC-293: builds whose pipeline timing was actually READ. Separate from l1_build_total
    #: because this function uses that count for TWO unrelated quantities — the latency
    #: average and the build RATE. RC-291 fixed the average by passing the measured count as
    #: l1_build_total, which silently fed the rate calculation a timed-build count: a true
    #: 500 builds/min reported as 100 and graded healthy where it should grade critical.
    #: One parameter cannot serve two questions; defaults to l1_build_total when omitted so
    #: existing callers keep their previous behaviour rather than silently changing it.
    timing_sample_count: int | None = None,
    reasons: dict[str, int],
    l1_http_cache_hit_total: int,
    l1_quote_material_skip_total: int,
    l1_cache_eviction_total: int,
    l1_of_quote_hook_engine_total: int,
    l1_of_quote_hook_reuse_total: int,
    cache_scope_count: int,
    l1_max_cache_scopes: int,
    uptime_sec: float,
) -> dict[str, Any]:
    """
    Returns operational.health-style dict: verdict, areas with status/thresholds/interpretation.
    Does not mutate counters.
    """
    thresholds_flat = {
        "min_uptime_sec_for_rates": L1_OP_MIN_UPTIME_SEC_FOR_RATES,
        "min_builds_for_latency": float(L1_OP_MIN_BUILDS_FOR_LATENCY),
        "L1_OP_MAX_AVG_BUILD_MS_WARN": L1_OP_MAX_AVG_BUILD_MS_WARN,
        "L1_OP_MAX_AVG_BUILD_MS_CRITICAL": L1_OP_MAX_AVG_BUILD_MS_CRITICAL,
        "L1_OP_MAX_BUILDS_PER_MIN_WARN": L1_OP_MAX_BUILDS_PER_MIN_WARN,
        "L1_OP_MAX_BUILDS_PER_MIN_CRITICAL": L1_OP_MAX_BUILDS_PER_MIN_CRITICAL,
        "min_of_hook_events": float(L1_OP_MIN_OF_HOOK_EVENTS),
        "L1_OP_MIN_OF_REUSE_RATIO_WARN": L1_OP_MIN_OF_REUSE_RATIO_WARN,
        "L1_OP_MIN_OF_REUSE_RATIO_CRITICAL": L1_OP_MIN_OF_REUSE_RATIO_CRITICAL,
        "min_http_events": float(L1_OP_MIN_HTTP_EVENTS),
        "L1_OP_MIN_HTTP_CACHE_HIT_RATIO_WARN": L1_OP_MIN_HTTP_CACHE_HIT_RATIO_WARN,
        "L1_OP_MAX_EVICTIONS_PER_MIN_WARN": L1_OP_MAX_EVICTIONS_PER_MIN_WARN,
        "L1_OP_MAX_EVICTIONS_PER_MIN_CRITICAL": L1_OP_MAX_EVICTIONS_PER_MIN_CRITICAL,
        "L1_OP_CACHE_SCOPE_PRESSURE_RATIO_WARN": L1_OP_CACHE_SCOPE_PRESSURE_RATIO_WARN,
        "min_stale_events": float(L1_OP_MIN_STALE_EVENTS),
        "L1_OP_MAX_STALE_REBUILDS_PER_MIN_WARN": L1_OP_MAX_STALE_REBUILDS_PER_MIN_WARN,
    }

    # RC-293: two questions, two denominators. The average divides by builds whose timing
    # was measured; the RATE counts every build that happened. Sharing one count made a fix
    # to the first a corruption of the second.
    _timed = int(l1_build_total if timing_sample_count is None else timing_sample_count)
    avg_ms = float(l1_build_ms_sum) / max(1, _timed)
    builds_per_min = (l1_build_total / max(uptime_sec, 1e-6)) * 60.0
    evictions_per_min = (l1_cache_eviction_total / max(uptime_sec, 1e-6)) * 60.0

    eng = int(l1_of_quote_hook_engine_total)
    reuse = int(l1_of_quote_hook_reuse_total)
    of_total = eng + reuse
    of_reuse_ratio = (reuse / of_total) if of_total > 0 else None

    cold = int(reasons.get("cold_start", 0))
    stale_http = int(reasons.get("http_serve_stale_rebuild", 0))
    force = int(reasons.get("http_force_refresh", 0))
    http_miss_like = cold + stale_http + force
    http_den = int(l1_http_cache_hit_total) + http_miss_like
    http_hit_ratio = (l1_http_cache_hit_total / http_den) if http_den > 0 else None

    stale_reason = int(reasons.get("http_serve_stale_rebuild", 0)) + int(reasons.get("quote_path_serve_age", 0))
    stale_per_min = (stale_reason / max(uptime_sec, 1e-6)) * 60.0

    scope_pressure = (cache_scope_count / max(1, l1_max_cache_scopes)) if l1_max_cache_scopes else 0.0

    rates_reliable = uptime_sec >= L1_OP_MIN_UPTIME_SEC_FOR_RATES

    areas: dict[str, Any] = {}

    # --- build_load (latency vs rate evaluated separately, then merged) ---
    lat_status = "unknown"
    lat_msg = f"Need ≥{L1_OP_MIN_BUILDS_FOR_LATENCY} builds for rolling average latency."
    if _timed >= L1_OP_MIN_BUILDS_FOR_LATENCY:      # RC-293: latency needs TIMED samples
        if avg_ms >= L1_OP_MAX_AVG_BUILD_MS_CRITICAL:
            lat_status = "critical"
            lat_msg = (
                f"Average L1 build latency {avg_ms:.1f}ms exceeds critical threshold "
                f"{L1_OP_MAX_AVG_BUILD_MS_CRITICAL}ms — investigate CPU, OF engine, or Tier C contention."
            )
        elif avg_ms >= L1_OP_MAX_AVG_BUILD_MS_WARN:
            lat_status = "warning"
            lat_msg = f"Average L1 build latency {avg_ms:.1f}ms is elevated (warn ≥{L1_OP_MAX_AVG_BUILD_MS_WARN}ms)."
        else:
            lat_status = "healthy"
            lat_msg = f"Rolling average build latency {avg_ms:.1f}ms is within bounds."

    rate_status = "unknown"
    rate_msg = f"Need ≥{L1_OP_MIN_UPTIME_SEC_FOR_RATES:.0f}s uptime for sustained build-rate assessment."
    if rates_reliable:
        if builds_per_min >= L1_OP_MAX_BUILDS_PER_MIN_CRITICAL:
            rate_status = "critical"
            rate_msg = (
                f"Sustained L1 build rate ~{builds_per_min:.0f}/min exceeds critical threshold "
                f"({L1_OP_MAX_BUILDS_PER_MIN_CRITICAL}/min) — churn or tight materiality loops."
            )
        elif builds_per_min >= L1_OP_MAX_BUILDS_PER_MIN_WARN:
            rate_status = "warning"
            rate_msg = f"L1 build rate ~{builds_per_min:.0f}/min is high (warn ≥{L1_OP_MAX_BUILDS_PER_MIN_WARN}/min)."
        else:
            rate_status = "healthy"
            rate_msg = f"Build rate ~{builds_per_min:.0f}/min is within expected bounds."

    bl_status = _worst(lat_status, rate_status)
    if bl_status == "healthy":
        bl_msg = "Build latency and sustained build rate are within expected bounds."
    else:
        parts_bl = []
        if lat_status != "healthy":
            parts_bl.append(lat_msg)
        if rate_status != "healthy":
            parts_bl.append(rate_msg)
        bl_msg = " ".join(parts_bl) if parts_bl else "Build load assessed."

    areas["build_load"] = {
        "status": bl_status,
        "avg_build_ms": round(avg_ms, 4),
        "builds_per_minute": round(builds_per_min, 2),
        "thresholds": {
            "max_avg_build_ms_warn": L1_OP_MAX_AVG_BUILD_MS_WARN,
            "max_avg_build_ms_critical": L1_OP_MAX_AVG_BUILD_MS_CRITICAL,
            "max_builds_per_min_warn": L1_OP_MAX_BUILDS_PER_MIN_WARN,
            "max_builds_per_min_critical": L1_OP_MAX_BUILDS_PER_MIN_CRITICAL,
        },
        "interpretation": bl_msg,
        "latency": {"status": lat_status, "interpretation": lat_msg},
        "rate": {"status": rate_status, "interpretation": rate_msg},
    }

    # --- of_quote_hook ---
    ofh_status = "unknown"
    ofh_msg = "Insufficient quote-hook OF samples."
    if of_total >= L1_OP_MIN_OF_HOOK_EVENTS and of_reuse_ratio is not None:
        if of_reuse_ratio < L1_OP_MIN_OF_REUSE_RATIO_CRITICAL:
            ofh_status = "critical"
            ofh_msg = (
                f"OF hook reuse ratio {of_reuse_ratio:.2f} is critically low — engine dominates; "
                "check probe drift or pathological quote cadence."
            )
        elif of_reuse_ratio < L1_OP_MIN_OF_REUSE_RATIO_WARN:
            ofh_status = "warning"
            ofh_msg = (
                f"OF hook reuse ratio {of_reuse_ratio:.2f} is below target (warn <{L1_OP_MIN_OF_REUSE_RATIO_WARN})."
            )
        else:
            ofh_status = "healthy"
            ofh_msg = "Quote-hook OF optimization is effective (reuse dominates vs engine)."
    areas["of_quote_hook"] = {
        "status": ofh_status,
        "engine_total": eng,
        "reuse_total": reuse,
        "reuse_ratio": round(of_reuse_ratio, 4) if of_reuse_ratio is not None else None,
        "thresholds": {
            "min_reuse_ratio_warn": L1_OP_MIN_OF_REUSE_RATIO_WARN,
            "min_reuse_ratio_critical": L1_OP_MIN_OF_REUSE_RATIO_CRITICAL,
        },
        "interpretation": ofh_msg,
    }

    # --- http_cache ---
    hc_status = "unknown"
    hc_msg = "Insufficient HTTP L1 traffic for hit-ratio assessment."
    if http_den >= L1_OP_MIN_HTTP_EVENTS and http_hit_ratio is not None:
        if http_hit_ratio < L1_OP_MIN_HTTP_CACHE_HIT_RATIO_WARN:
            hc_status = "warning"
            hc_msg = (
                f"HTTP cache hit ratio {http_hit_ratio:.2f} is low — clients may be forcing refresh or "
                "serve-age expiry is frequent."
            )
        else:
            hc_status = "healthy"
            hc_msg = "Cache-first HTTP projection is behaving (hits dominate vs cold/stale/force)."
    areas["http_cache"] = {
        "status": hc_status,
        "http_cache_hits": int(l1_http_cache_hit_total),
        "http_path_denominator": http_den,
        "hit_ratio": round(http_hit_ratio, 4) if http_hit_ratio is not None else None,
        "thresholds": {"min_hit_ratio_warn": L1_OP_MIN_HTTP_CACHE_HIT_RATIO_WARN},
        "interpretation": hc_msg,
    }

    # --- cache_lifecycle ---
    cl_status = "healthy"
    cl_msg = "Eviction rate and scope pressure are normal."
    if rates_reliable and evictions_per_min >= L1_OP_MAX_EVICTIONS_PER_MIN_CRITICAL:
        cl_status = "critical"
        cl_msg = f"Eviction rate ~{evictions_per_min:.1f}/min is critically high — scope churn or TTL pressure."
    elif rates_reliable and evictions_per_min >= L1_OP_MAX_EVICTIONS_PER_MIN_WARN:
        cl_status = "warning"
        cl_msg = f"Eviction rate ~{evictions_per_min:.1f}/min is elevated (warn ≥{L1_OP_MAX_EVICTIONS_PER_MIN_WARN}/min)."
    elif scope_pressure >= L1_OP_CACHE_SCOPE_PRESSURE_RATIO_WARN and rates_reliable:
        cl_status = _worst(cl_status, "warning")
        cl_msg = (
            f"Scope table near cap ({cache_scope_count}/{l1_max_cache_scopes}) — LRU churn likely; "
            "expect more evictions."
        )
    areas["cache_lifecycle"] = {
        "status": cl_status,
        "cache_scope_count": cache_scope_count,
        "max_scopes": l1_max_cache_scopes,
        "scope_pressure_ratio": round(scope_pressure, 4),
        "evictions_total": int(l1_cache_eviction_total),
        "evictions_per_minute": round(evictions_per_min, 2),
        "thresholds": {
            "max_evictions_per_min_warn": L1_OP_MAX_EVICTIONS_PER_MIN_WARN,
            "max_evictions_per_min_critical": L1_OP_MAX_EVICTIONS_PER_MIN_CRITICAL,
            "scope_pressure_warn_ratio": L1_OP_CACHE_SCOPE_PRESSURE_RATIO_WARN,
        },
        "interpretation": cl_msg,
    }

    # --- staleness_rebuilds ---
    st_status = "unknown"
    st_msg = "Insufficient stale-rebuild samples."
    if stale_reason >= L1_OP_MIN_STALE_EVENTS:
        if rates_reliable and stale_per_min >= L1_OP_MAX_STALE_REBUILDS_PER_MIN_WARN:
            st_status = "warning"
            st_msg = (
                f"Stale-driven rebuilds ~{stale_per_min:.1f}/min — HTTP or quote serve-age may be tight for UX."
            )
        else:
            st_status = "healthy"
            st_msg = "Stale rebuild rate is within bounds."
    areas["staleness"] = {
        "status": st_status,
        "stale_rebuild_events_total": stale_reason,
        "stale_rebuilds_per_minute": round(stale_per_min, 2),
        "thresholds": {"max_stale_rebuilds_per_min_warn": L1_OP_MAX_STALE_REBUILDS_PER_MIN_WARN},
        "interpretation": st_msg,
    }

    statuses = [str(a.get("status", "unknown")) for a in areas.values()]
    material = [s for s in statuses if s != "unknown"]
    if not material:
        verdict = "unknown"
    else:
        verdict = "healthy"
        for s in material:
            verdict = _worst(verdict, s)

    parts = []
    for key, v in areas.items():
        if key == "build_load":
            for sub in ("latency", "rate"):
                s = v.get(sub) or {}
                if s.get("status") in ("warning", "critical"):
                    parts.append(str(s.get("interpretation", "")))
            if v.get("status") in ("warning", "critical") and not parts:
                parts.append(str(v.get("interpretation", "")))
        elif v.get("status") in ("warning", "critical"):
            parts.append(str(v.get("interpretation", "")))
    summary = "; ".join(parts) if parts else "All assessed L1 operational areas are within thresholds."

    return {
        "schema_version": 1,
        "verdict": verdict,
        "summary": summary,
        "uptime_sec": round(uptime_sec, 3),
        "rates_reliable": rates_reliable,
        "min_uptime_sec_for_rates": L1_OP_MIN_UPTIME_SEC_FOR_RATES,
        "areas": areas,
        "thresholds": thresholds_flat,
    }
