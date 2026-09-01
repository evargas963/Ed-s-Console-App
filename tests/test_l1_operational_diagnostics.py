"""
L1 operational diagnostics: thresholds, health verdicts, /api/diagnostics/l1 operational block.
"""
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _base_reasons(**kwargs):
    r = {
        "cold_start": 0,
        "http_serve_stale_rebuild": 0,
        "http_force_refresh": 0,
        "quote_path_serve_age": 0,
    }
    r.update(kwargs)
    return r


def test_operational_healthy_baseline():
    from planes.l1_operational import build_l1_operational_assessment

    rep = build_l1_operational_assessment(
        l1_build_total=40,
        l1_build_ms_sum=400.0,
        reasons=_base_reasons(cold_start=5, http_serve_stale_rebuild=4, quote_path_serve_age=4),
        l1_http_cache_hit_total=80,
        l1_quote_material_skip_total=100,
        l1_cache_eviction_total=2,
        l1_of_quote_hook_engine_total=10,
        l1_of_quote_hook_reuse_total=40,
        cache_scope_count=3,
        l1_max_cache_scopes=64,
        uptime_sec=120.0,
    )
    assert rep["verdict"] == "healthy"
    assert rep["areas"]["build_load"]["status"] == "healthy"
    assert rep["areas"]["of_quote_hook"]["status"] == "healthy"
    assert rep["areas"]["http_cache"]["status"] == "healthy"
    assert rep["areas"]["cache_lifecycle"]["status"] == "healthy"
    assert rep["areas"]["staleness"]["status"] == "healthy"


def test_operational_warning_high_avg_build_latency():
    from planes.l1_operational import build_l1_operational_assessment, L1_OP_MAX_AVG_BUILD_MS_WARN

    n = 20
    ms_sum = n * (L1_OP_MAX_AVG_BUILD_MS_WARN + 5.0)
    rep = build_l1_operational_assessment(
        l1_build_total=n,
        l1_build_ms_sum=ms_sum,
        reasons=_base_reasons(),
        l1_http_cache_hit_total=0,
        l1_quote_material_skip_total=0,
        l1_cache_eviction_total=0,
        l1_of_quote_hook_engine_total=0,
        l1_of_quote_hook_reuse_total=0,
        cache_scope_count=1,
        l1_max_cache_scopes=64,
        uptime_sec=300.0,
    )
    assert rep["areas"]["build_load"]["status"] == "warning"
    assert rep["areas"]["build_load"]["latency"]["status"] == "warning"
    assert "elevated" in rep["areas"]["build_load"]["latency"]["interpretation"].lower()
    assert rep["verdict"] == "warning"


def test_operational_critical_avg_build_latency():
    from planes.l1_operational import build_l1_operational_assessment, L1_OP_MAX_AVG_BUILD_MS_CRITICAL

    n = 20
    ms_sum = n * (L1_OP_MAX_AVG_BUILD_MS_CRITICAL + 10.0)
    rep = build_l1_operational_assessment(
        l1_build_total=n,
        l1_build_ms_sum=ms_sum,
        reasons=_base_reasons(),
        l1_http_cache_hit_total=0,
        l1_quote_material_skip_total=0,
        l1_cache_eviction_total=0,
        l1_of_quote_hook_engine_total=0,
        l1_of_quote_hook_reuse_total=0,
        cache_scope_count=1,
        l1_max_cache_scopes=64,
        uptime_sec=300.0,
    )
    assert rep["areas"]["build_load"]["latency"]["status"] == "critical"
    assert rep["verdict"] == "critical"


def test_operational_warning_build_rate():
    from planes.l1_operational import build_l1_operational_assessment, L1_OP_MAX_BUILDS_PER_MIN_WARN

    uptime = 60.0
    total = int((L1_OP_MAX_BUILDS_PER_MIN_WARN + 20) * (uptime / 60.0)) + 5
    rep = build_l1_operational_assessment(
        l1_build_total=total,
        l1_build_ms_sum=float(total) * 5.0,
        reasons=_base_reasons(),
        l1_http_cache_hit_total=0,
        l1_quote_material_skip_total=0,
        l1_cache_eviction_total=0,
        l1_of_quote_hook_engine_total=0,
        l1_of_quote_hook_reuse_total=0,
        cache_scope_count=1,
        l1_max_cache_scopes=64,
        uptime_sec=uptime,
    )
    assert rep["areas"]["build_load"]["rate"]["status"] == "warning"
    assert rep["verdict"] == "warning"


def test_operational_critical_build_rate():
    from planes.l1_operational import build_l1_operational_assessment, L1_OP_MAX_BUILDS_PER_MIN_CRITICAL

    uptime = 60.0
    total = int((L1_OP_MAX_BUILDS_PER_MIN_CRITICAL + 50) * (uptime / 60.0))
    rep = build_l1_operational_assessment(
        l1_build_total=total,
        l1_build_ms_sum=float(total) * 4.0,
        reasons=_base_reasons(),
        l1_http_cache_hit_total=0,
        l1_quote_material_skip_total=0,
        l1_cache_eviction_total=0,
        l1_of_quote_hook_engine_total=0,
        l1_of_quote_hook_reuse_total=0,
        cache_scope_count=1,
        l1_max_cache_scopes=64,
        uptime_sec=uptime,
    )
    assert rep["areas"]["build_load"]["rate"]["status"] == "critical"
    assert rep["verdict"] == "critical"


def test_operational_of_hook_low_reuse_warning_and_critical():
    from planes.l1_operational import (
        build_l1_operational_assessment,
        L1_OP_MIN_OF_REUSE_RATIO_CRITICAL,
    )

    rep_w = build_l1_operational_assessment(
        l1_build_total=30,
        l1_build_ms_sum=300.0,
        reasons=_base_reasons(),
        l1_http_cache_hit_total=0,
        l1_quote_material_skip_total=0,
        l1_cache_eviction_total=0,
        l1_of_quote_hook_engine_total=20,
        l1_of_quote_hook_reuse_total=6,
        cache_scope_count=1,
        l1_max_cache_scopes=64,
        uptime_sec=120.0,
    )
    assert rep_w["areas"]["of_quote_hook"]["status"] == "warning"

    rep_c = build_l1_operational_assessment(
        l1_build_total=30,
        l1_build_ms_sum=300.0,
        reasons=_base_reasons(),
        l1_http_cache_hit_total=0,
        l1_quote_material_skip_total=0,
        l1_cache_eviction_total=0,
        l1_of_quote_hook_engine_total=90,
        l1_of_quote_hook_reuse_total=5,
        cache_scope_count=1,
        l1_max_cache_scopes=64,
        uptime_sec=120.0,
    )
    ratio = 5 / 95
    assert ratio < L1_OP_MIN_OF_REUSE_RATIO_CRITICAL
    assert rep_c["areas"]["of_quote_hook"]["status"] == "critical"


def test_operational_http_cache_low_hit_ratio_warning():
    from planes.l1_operational import build_l1_operational_assessment

    rep = build_l1_operational_assessment(
        l1_build_total=50,
        l1_build_ms_sum=500.0,
        reasons=_base_reasons(cold_start=15, http_serve_stale_rebuild=10, http_force_refresh=5),
        l1_http_cache_hit_total=8,
        l1_quote_material_skip_total=0,
        l1_cache_eviction_total=0,
        l1_of_quote_hook_engine_total=0,
        l1_of_quote_hook_reuse_total=0,
        cache_scope_count=1,
        l1_max_cache_scopes=64,
        uptime_sec=120.0,
    )
    assert rep["areas"]["http_cache"]["status"] == "warning"
    assert rep["areas"]["http_cache"]["hit_ratio"] is not None
    assert rep["verdict"] == "warning"


def test_operational_eviction_pressure_warning_and_critical():
    from planes.l1_operational import (
        build_l1_operational_assessment,
        L1_OP_MAX_EVICTIONS_PER_MIN_WARN,
        L1_OP_MAX_EVICTIONS_PER_MIN_CRITICAL,
    )

    uptime = 60.0
    ev_w = int(L1_OP_MAX_EVICTIONS_PER_MIN_WARN * (uptime / 60.0) + 3)
    rep_w = build_l1_operational_assessment(
        l1_build_total=20,
        l1_build_ms_sum=200.0,
        reasons=_base_reasons(),
        l1_http_cache_hit_total=0,
        l1_quote_material_skip_total=0,
        l1_cache_eviction_total=ev_w,
        l1_of_quote_hook_engine_total=0,
        l1_of_quote_hook_reuse_total=0,
        cache_scope_count=1,
        l1_max_cache_scopes=64,
        uptime_sec=uptime,
    )
    assert rep_w["areas"]["cache_lifecycle"]["status"] == "warning"

    ev_c = int(L1_OP_MAX_EVICTIONS_PER_MIN_CRITICAL * (uptime / 60.0) + 5)
    rep_c = build_l1_operational_assessment(
        l1_build_total=20,
        l1_build_ms_sum=200.0,
        reasons=_base_reasons(),
        l1_http_cache_hit_total=0,
        l1_quote_material_skip_total=0,
        l1_cache_eviction_total=ev_c,
        l1_of_quote_hook_engine_total=0,
        l1_of_quote_hook_reuse_total=0,
        cache_scope_count=1,
        l1_max_cache_scopes=64,
        uptime_sec=uptime,
    )
    assert rep_c["areas"]["cache_lifecycle"]["status"] == "critical"


def test_operational_stale_rebuild_rate_warning():
    from planes.l1_operational import build_l1_operational_assessment, L1_OP_MAX_STALE_REBUILDS_PER_MIN_WARN

    uptime = 60.0
    stale_n = int(L1_OP_MAX_STALE_REBUILDS_PER_MIN_WARN * (uptime / 60.0) + 5)
    rep = build_l1_operational_assessment(
        l1_build_total=stale_n + 10,
        l1_build_ms_sum=float(stale_n + 10) * 8.0,
        reasons=_base_reasons(http_serve_stale_rebuild=stale_n // 2, quote_path_serve_age=stale_n - stale_n // 2),
        l1_http_cache_hit_total=0,
        l1_quote_material_skip_total=0,
        l1_cache_eviction_total=0,
        l1_of_quote_hook_engine_total=0,
        l1_of_quote_hook_reuse_total=0,
        cache_scope_count=1,
        l1_max_cache_scopes=64,
        uptime_sec=uptime,
    )
    assert rep["areas"]["staleness"]["status"] == "warning"
    assert rep["verdict"] == "warning"


def test_operational_scope_pressure_warning():
    from planes.l1_operational import build_l1_operational_assessment

    rep = build_l1_operational_assessment(
        l1_build_total=30,
        l1_build_ms_sum=300.0,
        reasons=_base_reasons(),
        l1_http_cache_hit_total=0,
        l1_quote_material_skip_total=0,
        l1_cache_eviction_total=0,
        l1_of_quote_hook_engine_total=0,
        l1_of_quote_hook_reuse_total=0,
        cache_scope_count=62,
        l1_max_cache_scopes=64,
        uptime_sec=120.0,
    )
    assert rep["areas"]["cache_lifecycle"]["status"] == "warning"
    assert "near cap" in rep["areas"]["cache_lifecycle"]["interpretation"].lower()


def test_l1_diagnostics_endpoint_includes_operational_and_legacy_fields():
    """TEST_SYSTEM_REHAB_V2 final remediation: get_l1_diagnostics is a plain sync
    handler with no auth/middleware/serialization-shaping dependency -- the HTTP
    round trip added nothing a direct call doesn't already prove."""
    import json

    import server as srv

    j = json.loads(srv.get_l1_diagnostics().body)
    ed = j["ed_l1"]
    assert ed.get("schema_version") == 2
    assert "l1_diag_uptime_sec" in ed
    assert "operational" in ed
    op = ed["operational"]
    assert "verdict" in op and "summary" in op and "areas" in op
    assert "thresholds" in op
    # Legacy counters preserved
    for k in (
        "l1_build_total",
        "l1_build_ms_avg",
        "l1_build_by_reason",
        "l1_http_cache_hit_total",
        "l1_quote_material_skip_total",
        "l1_cache_eviction_total",
        "l1_cache_eviction_ttl_total",
        "l1_cache_eviction_cap_total",
        "l1_cache_reconcile_lru_pruned_total",
        "l1_cache_reconcile_lru_backfilled_total",
        "l1_cache_lifecycle",
        "l1_adaptive_materiality",
        "l1_sse_light",
        "l1_of_quote_hook_engine_total",
        "l1_of_quote_hook_reuse_total",
        "l1_cache_scope_count",
        "policy",
        "cached_scopes_sample",
    ):
        assert k in ed, f"missing {k}"


def test_operational_high_of_reuse_ratio_healthy():
    from planes.l1_operational import build_l1_operational_assessment

    rep = build_l1_operational_assessment(
        l1_build_total=25,
        l1_build_ms_sum=250.0,
        reasons=_base_reasons(),
        l1_http_cache_hit_total=0,
        l1_quote_material_skip_total=0,
        l1_cache_eviction_total=0,
        l1_of_quote_hook_engine_total=5,
        l1_of_quote_hook_reuse_total=80,
        cache_scope_count=2,
        l1_max_cache_scopes=64,
        uptime_sec=90.0,
    )
    assert rep["areas"]["of_quote_hook"]["reuse_ratio"] > 0.9
    assert rep["areas"]["of_quote_hook"]["status"] == "healthy"


def test_operational_configurable_thresholds_via_monkeypatch(monkeypatch):
    import planes.l1_operational as lo

    monkeypatch.setattr(lo, "L1_OP_MAX_AVG_BUILD_MS_WARN", 9999.0)
    rep = lo.build_l1_operational_assessment(
        l1_build_total=20,
        l1_build_ms_sum=20 * 50.0,
        reasons={"cold_start": 0},
        l1_http_cache_hit_total=0,
        l1_quote_material_skip_total=0,
        l1_cache_eviction_total=0,
        l1_of_quote_hook_engine_total=0,
        l1_of_quote_hook_reuse_total=0,
        cache_scope_count=1,
        l1_max_cache_scopes=64,
        uptime_sec=200.0,
    )
    assert rep["areas"]["build_load"]["latency"]["status"] == "healthy"
