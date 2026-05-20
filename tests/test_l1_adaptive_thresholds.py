"""
Adaptive L1 materiality thresholds — ticker, session, volatility, integration, diagnostics.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_no_context_matches_static_runtime_constants():
    from planes.l1_runtime import L1_SPOT_REL_EPS, L1_SPREAD_FRAC_ABS_EPS, build_input_fingerprint
    from planes.l1_runtime import input_fingerprint_materially_changed
    from planes.l1_thresholds import resolve_l1_adaptive_thresholds

    assert resolve_l1_adaptive_thresholds("SPY", context=None).spot_rel_eps == L1_SPOT_REL_EPS
    assert resolve_l1_adaptive_thresholds("SPY", context=None).spread_frac_abs_eps == L1_SPREAD_FRAC_ABS_EPS

    ent = {"analytics_version": 1, "ms_dict": {}}
    row = {"spot": 100.0, "spread": 0.01, "fast_generation_id": 1.0}
    fp = build_input_fingerprint(row, ent)
    row2 = dict(row)
    row2["spot"] = 100.0 + L1_SPOT_REL_EPS * 0.5 * 100.0
    assert not input_fingerprint_materially_changed(fp, row2, ent, ticker="SPY", adaptive_context=None)
    row3 = dict(row)
    row3["spot"] = 100.0 + L1_SPOT_REL_EPS * 1.5 * 100.0
    assert input_fingerprint_materially_changed(fp, row3, ent, ticker="SPY", adaptive_context=None)


def test_ticker_aware_broad_etf_vs_equity():
    from planes.l1_thresholds import AdaptiveMaterialityContext, resolve_l1_adaptive_thresholds

    ctx = AdaptiveMaterialityContext(
        session_label="RTH",
        vix_level=18.0,
        spot=450.0,
        spread_frac=0.0002,
        now_ts=1_700_000_000.0,
    )
    r_etf = resolve_l1_adaptive_thresholds("SPY", context=ctx)
    r_eq = resolve_l1_adaptive_thresholds("PLTR", context=ctx)
    assert r_etf.instrument_kind == "broad_etf"
    assert r_eq.instrument_kind == "equity_general"
    assert r_etf.spot_rel_eps < r_eq.spot_rel_eps


def test_session_extended_widens_thresholds_vs_rth():
    from planes.l1_thresholds import AdaptiveMaterialityContext, resolve_l1_adaptive_thresholds

    base = dict(vix_level=18.0, spot=100.0, spread_frac=0.0002, now_ts=1_700_000_000.0)
    ext = resolve_l1_adaptive_thresholds(
        "SPY",
        context=AdaptiveMaterialityContext(session_label="Pre-Market", **base),
    )
    rth = resolve_l1_adaptive_thresholds(
        "SPY",
        context=AdaptiveMaterialityContext(session_label="RTH", **base),
    )
    assert ext.session_bucket == "extended_or_closed"
    assert rth.session_bucket in ("rth_open", "rth_midday", "rth_close", "rth_other")
    assert ext.spot_rel_eps > rth.spot_rel_eps
    assert ext.spread_frac_abs_eps > rth.spread_frac_abs_eps


def test_volatility_high_vix_widens_thresholds():
    from planes.l1_thresholds import AdaptiveMaterialityContext, resolve_l1_adaptive_thresholds

    ctx_lo = AdaptiveMaterialityContext(
        session_label="RTH",
        vix_level=12.0,
        spot=450.0,
        spread_frac=0.0002,
        now_ts=1_700_000_000.0,
    )
    ctx_hi = AdaptiveMaterialityContext(
        session_label="RTH",
        vix_level=45.0,
        spot=450.0,
        spread_frac=0.0002,
        now_ts=1_700_000_000.0,
    )
    lo = resolve_l1_adaptive_thresholds("SPY", context=ctx_lo)
    hi = resolve_l1_adaptive_thresholds("SPY", context=ctx_hi)
    assert lo.vol_regime == "low"
    assert hi.vol_regime == "high"
    assert hi.spot_rel_eps > lo.spot_rel_eps
    assert hi.spread_frac_abs_eps > lo.spread_frac_abs_eps


def test_price_tier_penny_widens_spot_threshold():
    from planes.l1_thresholds import AdaptiveMaterialityContext, resolve_l1_adaptive_thresholds

    ctx = AdaptiveMaterialityContext(
        session_label="RTH",
        vix_level=18.0,
        spot=4.5,
        spread_frac=0.0002,
        now_ts=1_700_000_000.0,
    )
    r = resolve_l1_adaptive_thresholds("XYZ", context=ctx)
    assert r.price_tier == "penny_small"
    assert r.spot_rel_eps > resolve_l1_adaptive_thresholds(
        "XYZ",
        context=AdaptiveMaterialityContext(
            session_label="RTH", vix_level=18.0, spot=150.0, spread_frac=0.0002, now_ts=1_700_000_000.0
        ),
    ).spot_rel_eps


def test_bounded_thresholds():
    from planes.l1_thresholds import (
        L1_SPOT_REL_EPS_MAX,
        L1_SPOT_REL_EPS_MIN,
        L1_SPREAD_FRAC_ABS_EPS_MAX,
        L1_SPREAD_FRAC_ABS_EPS_MIN,
        AdaptiveMaterialityContext,
        resolve_l1_adaptive_thresholds,
    )

    ctx = AdaptiveMaterialityContext(
        session_label="Pre-Market",
        vix_level=80.0,
        spot=2.0,
        spread_frac=0.05,
        now_ts=1_700_000_000.0,
    )
    r = resolve_l1_adaptive_thresholds("XYZ", context=ctx)
    assert L1_SPOT_REL_EPS_MIN <= r.spot_rel_eps <= L1_SPOT_REL_EPS_MAX
    assert L1_SPREAD_FRAC_ABS_EPS_MIN <= r.spread_frac_abs_eps <= L1_SPREAD_FRAC_ABS_EPS_MAX


def test_materiality_uses_adaptive_eps_from_diagnostics():
    from planes.l1_runtime import build_input_fingerprint, input_fingerprint_materially_changed
    from planes.l1_thresholds import AdaptiveMaterialityContext, resolve_l1_adaptive_thresholds

    ent = {"analytics_version": 1, "ms_dict": {}}
    row = {"spot": 100.0, "spread": 0.0002, "fast_generation_id": 1.0}
    fp = build_input_fingerprint(row, ent)
    ctx = AdaptiveMaterialityContext(
        session_label="RTH",
        vix_level=18.0,
        spot=100.0,
        spread_frac=0.0002,
        now_ts=1_700_000_000.0,
    )
    expected = resolve_l1_adaptive_thresholds("SPY", context=ctx)
    diag: dict = {}
    input_fingerprint_materially_changed(
        fp, row, ent, ticker="SPY", adaptive_context=ctx, adaptive_diagnostics_out=diag
    )
    assert diag["spot_rel_eps"] == expected.spot_rel_eps
    assert diag["spread_frac_abs_eps"] == expected.spread_frac_abs_eps
    assert diag["mode"] == "adaptive_engine"

    rel_move = expected.spot_rel_eps * 0.5
    row_same = {**row, "spot": 100.0 * (1.0 + rel_move)}
    assert not input_fingerprint_materially_changed(fp, row_same, ent, ticker="SPY", adaptive_context=ctx)
    row_mat = {**row, "spot": 100.0 * (1.0 + expected.spot_rel_eps * 1.1)}
    assert input_fingerprint_materially_changed(fp, row_mat, ent, ticker="SPY", adaptive_context=ctx)


def test_diagnostics_explainability_fields():
    from planes.l1_thresholds import AdaptiveMaterialityContext, resolve_l1_adaptive_thresholds

    ctx = AdaptiveMaterialityContext(
        session_label="RTH",
        vix_level=22.0,
        spot=450.0,
        spread_frac=0.0003,
        now_ts=1_700_000_000.0,
    )
    d = resolve_l1_adaptive_thresholds("SPY", context=ctx).as_dict()
    assert d["mode"] == "adaptive_engine"
    assert "rules_applied" in d and len(d["rules_applied"]) >= 3
    assert d["instrument_kind"] == "broad_etf"
    assert d["vol_regime"] in ("elevated", "normal", "low", "high", "unknown")
    assert d["materiality_regime"] in (
        "midday_rth",
        "session_tail_rth_open",
        "session_tail_rth_close",
        "normal_rth",
        "calm_rth",
        "elevated_volatility_rth",
        "high_volatility_rth",
        "microstructure_stress",
    )
    assert d["sensitivity_vs_baseline_spot"] in (
        "less_sensitive_than_baseline",
        "more_sensitive_than_baseline",
        "similar_to_baseline",
    )


def test_diagnostics_endpoint_includes_adaptive_block():
    import server as srv
    from fastapi.testclient import TestClient

    client = TestClient(srv.app)
    r = client.get("/api/diagnostics/l1")
    assert r.status_code == 200
    j = r.json()["ed_l1"]
    assert "l1_adaptive_materiality" in j
    assert "sample_spy_adaptive" in j["l1_adaptive_materiality"]
    assert "static_defaults_reference" in j["l1_adaptive_materiality"]
    assert j["l1_adaptive_materiality"]["static_defaults_reference"]["mode"] == "static_defaults"
    assert j["l1_adaptive_materiality"]["l1_materiality_engine_schema_version"] == 1


def test_vix_smooth_monotonic_increases_thresholds():
    from planes.l1_thresholds import AdaptiveMaterialityContext, resolve_l1_materiality_engine

    base = dict(session_label="RTH", spot=200.0, spread_frac=0.0002, now_ts=1_700_000_000.0)
    a = resolve_l1_materiality_engine("SPY", context=AdaptiveMaterialityContext(vix_level=14.0, **base))
    b = resolve_l1_materiality_engine("SPY", context=AdaptiveMaterialityContext(vix_level=16.0, **base))
    c = resolve_l1_materiality_engine("SPY", context=AdaptiveMaterialityContext(vix_level=35.0, **base))
    assert a.spot_rel_eps <= b.spot_rel_eps <= c.spot_rel_eps
    assert abs(b.spot_rel_eps - a.spot_rel_eps) < abs(c.spot_rel_eps - a.spot_rel_eps)


def test_spread_instability_raises_spread_materiality_threshold():
    from planes.l1_thresholds import AdaptiveMaterialityContext, resolve_l1_materiality_engine

    base = dict(session_label="RTH", vix_level=18.0, spot=50.0, now_ts=1_700_000_000.0)
    calm = resolve_l1_materiality_engine("SPY", context=AdaptiveMaterialityContext(spread_frac=0.00015, **base))
    wide = resolve_l1_materiality_engine("SPY", context=AdaptiveMaterialityContext(spread_frac=0.012, **base))
    assert wide.spread_frac_abs_eps > calm.spread_frac_abs_eps
    assert wide.spread_stress_score > calm.spread_stress_score


def test_rth_open_vs_midday_differ_via_intraday_ramp():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from planes.l1_thresholds import AdaptiveMaterialityContext, resolve_l1_materiality_engine

    from time_et import ET as et  # noqa: F401
    ts_open = datetime(2024, 6, 14, 9, 35, tzinfo=et).timestamp()
    ts_mid = datetime(2024, 6, 14, 12, 15, tzinfo=et).timestamp()
    ctx = dict(session_label="RTH", vix_level=18.0, spot=500.0, spread_frac=0.0002)
    ro = resolve_l1_materiality_engine("SPY", context=AdaptiveMaterialityContext(now_ts=ts_open, **ctx))
    md = resolve_l1_materiality_engine("SPY", context=AdaptiveMaterialityContext(now_ts=ts_mid, **ctx))
    assert ro.session_bucket == "rth_open"
    assert md.session_bucket == "rth_midday"
    assert ro.session_intraday_ramp != md.session_intraday_ramp or ro.spot_rel_eps != md.spot_rel_eps


def test_materiality_boolean_differs_when_only_engine_context_differs():
    from planes.l1_runtime import build_input_fingerprint, input_fingerprint_materially_changed
    from planes.l1_thresholds import AdaptiveMaterialityContext, resolve_l1_materiality_engine

    ent = {"analytics_version": 1, "ms_dict": {}}
    row = {"spot": 100.0, "spread": 0.0002, "fast_generation_id": 1.0}
    fp = build_input_fingerprint(row, ent)
    ts = 1_700_000_000.0
    ctx_tight = AdaptiveMaterialityContext(
        session_label="RTH", vix_level=12.0, spot=100.0, spread_frac=0.0002, now_ts=ts
    )
    ctx_wide = AdaptiveMaterialityContext(
        session_label="RTH", vix_level=45.0, spot=100.0, spread_frac=0.0002, now_ts=ts
    )
    rt = resolve_l1_materiality_engine("SPY", context=ctx_tight)
    rw = resolve_l1_materiality_engine("SPY", context=ctx_wide)
    assert rt.spot_rel_eps < rw.spot_rel_eps
    mid_rel = (rt.spot_rel_eps + rw.spot_rel_eps) / 2.0
    row_edge = {**row, "spot": 100.0 * (1.0 + mid_rel)}
    assert input_fingerprint_materially_changed(fp, row_edge, ent, ticker="SPY", adaptive_context=ctx_tight) is True
    assert input_fingerprint_materially_changed(fp, row_edge, ent, ticker="SPY", adaptive_context=ctx_wide) is False
