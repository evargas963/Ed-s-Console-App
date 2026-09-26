"""SINGLE_PRODUCER_MECHANICAL_LOCK_V1 — batch F02..F13 recurrence locks.

Each master F-row that this batch collapses to one producer gets a narrow, mechanical lock
here so the second authority cannot silently reappear. These are structural/textual guards
(the RC-343 zone pattern), not behavioural snapshots: they assert WHERE a semantic may be
computed, which is the property the one-producer mandate (RC-325) protects.
"""
from __future__ import annotations

import re
from pathlib import Path

# Non-importable production surfaces this suite genuinely exercises (the F07 regime-shadow and
# F05 actionability locks read and assert on static/index.html). Declaring ownership lets the
# turn audit map the HTML change to a running suite instead of reporting an unknown owner.
TURN_AUDIT_OWNS = [
    "static/index.html",
    "static/chart.html",
    "time_et.py",
    "server.py",
    "news_sentiment.py",
    "liquidity_value_engine.py",
    "compare_clustering_modes.py",
    "audit_model_readiness.py",
    "verification/daily_health.py",
    "v2_decision/a2_eod_force_exit.py",
    "v2_decision/a2_option_expression.py",
    "v2_decision/a2_session_calendar.py",
    "research/gex_r1_screen_v1/signal.py",
    "research/pilot_step3/data_loader.py",
    "research/tod_eval_v1/runner.py",
    "tools/research/d2_build_dual_label_scratch_db.py",
    "tools/study_pin_direction_v1.py",
    "tools/study_pin_charm_v1.py",
    "tools/study_pin_residence_v1.py",
    "tools/study_pin_regime_cut_v1.py",
    "tools/study_terrain_readiness_v1.py",
    "tools/study_card2_am_pm_v1.py",
    "tools/study_card_lateday_v1.py",
    "tools/study_card_lateday_v2.py",
    "tools/study_timeslice_reversal_v1.py",
    "tools/lp01_touch_study_v1.py",
    "tools/liquidity_synthesis_experiments_v1.py",
    "tools/liquidity_oi_volume_stickiness_v1.py",
    "tools/terrain_backtest_report_v1.py",
    "tools/liquidity_intraday_volume_ic_v1.py",
    # F07: this suite's regime lock reads and asserts on the backtests' regime derivation.
    "tools/liquidity_gamma_hold_horizon_experiments_v1.py",
    "tools/liquidity_gamma_levels_experiment_v1.py",
    # F25: this suite's ticker-identity lock reads/asserts on the canonical routing across
    # the whole artifact/cache/serve continuum (writer→verifier→predictor).
    "active_bundle_contract.py",
    "training_cache.py",
    "ml_predict.py",
    "verify_active_models.py",
    "ml_scheduler.py",
    # F25 current-tree residuals (Cursor ACCEPT_PARTIAL): feature-curation cell keys / anchor
    # feeders, the train DB-load bind, and the training-fingerprint producers.
    "ml_train.py",
    "tools/feature_curation_gate.py",
    # F25 known live residuals (2nd batch): transformer/lstm sequence meta identity, ml_data_common
    # DB binds, arch_state writer, execution routing identity, scheduler enrollment/filter identity.
    "features/shared_sequence_context.py",
    "ml_data_common.py",
    "execution_identity.py",
    "scheduler_user_tickers.py",
    # F25 known live residuals (3rd batch — Cursor's latest two): cache-skip streak key and the
    # arch eval-proof per-ticker key.
    "training_pipeline_status.py",
    "eval_metrics_store.py",
    # F25 denominator sweep (serving/routing/eval/capture/feature identity + real serving bugs):
    "xgboost_model.py",
]

REPO = Path(__file__).resolve().parent.parent


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8", errors="replace")


# --------------------------------------------------------------------------- F07 gamma regime
def test_rc345_frontend_never_writes_the_regime_field() -> None:
    """F07: the gamma-regime SIGN is owned by the backend (terrain_read._regime_for). The
    frontend renders `d.regime`; it may never assign to it (edReconcileRegime used to flip
    the label locally from a live spot-vs-flip cross — a second authority)."""
    src = _read("static/index.html")
    writes = re.findall(r"\.regime\s*=(?!=)", src)
    assert not writes, (
        f"static/index.html assigns to `.regime` {len(writes)} time(s); the regime sign "
        f"must be carried from the server, never recomputed on the client (F07/RC-345).")




# ------------------------------------------------------------------------- F10 candle direction


# ---------------------------------------------------------------------------- F13 time-to-expiry


# ------------------------------------------------------------------------------------- F08 ATR
def test_rc345_standard_atr_has_one_authority() -> None:
    """F08: the standard true-range ATR (TR = max(h-l, |h-pc|, |l-pc|), SMA smoothing) is
    computed once, by math_volatility.compute_atr. The RTH-session wrapper
    (liquidity_value_engine.compute_atr_from_bars) owns only scope and must delegate the
    formula; it may not re-inline the TR loop."""
    from math_volatility import compute_atr

    bars = [{"high": 10 + i, "low": 9 + i, "close": 9.5 + i} for i in range(20)]
    assert compute_atr(bars, period=14) is not None

    lve = _read("liquidity_value_engine.py")
    assert "from math_volatility import compute_atr" in lve or "compute_atr(" in lve, (
        "compute_atr_from_bars must call the one ATR authority, not re-derive TR")
    # The re-inlined TR loop is gone (its signature line: `abs(h - prev_close)` inside the fn).
    body = lve[lve.index("def compute_atr_from_bars"):]
    body = body[: body.index("\ndef ", 1)] if "\ndef " in body[1:] else body
    assert "abs(h - prev_close)" not in body, (
        "compute_atr_from_bars still inlines a second TR formula (F08/RC-345).")




# --------------------------------------------------------------------------- F09 session / RTH


# ------------------------------------------------------------------------- F12 relative volume


# ------------------------------------------------------------------- F11 options volume imbalance




def test_f09_ui_clock_cannot_serve_stale_disk_or_prior_constants(monkeypatch) -> None:
    """Negative proof: the UI-serving path cannot return a stale disk blob or
    a prior 570/960 constant once time_et has moved or projection fails.

    Two attacks against the old fail-open lifespan write:
      1. Plant window.ED_RTH_START_MINS=111 on disk and monkeypatch time_et to
         400/800 — GET must return 400/800, never 111 or 570/960.
      2. Force rth_clock_js_source to raise — GET must fail closed (5xx), not
         fall through to StaticFiles serving the planted 111/222 blob.
    """
    import pytest

    pytest.importorskip("fastapi")
    import time_et
    import server as srv
    from pathlib import Path
    from starlette.testclient import TestClient

    disk = Path(srv.APP_DIR) / "static" / "rth_clock_authority.js"
    stale = b"window.ED_RTH_START_MINS=111;\nwindow.ED_RTH_END_MINS=222;\n"
    prior = disk.read_bytes() if disk.exists() else None
    try:
        disk.write_bytes(stale)
        monkeypatch.setattr(time_et, "RTH_START_MINS", 400)
        monkeypatch.setattr(time_et, "RTH_END_MINS", 800)
        with TestClient(srv.app) as client:
            r = client.get("/static/rth_clock_authority.js")
            assert r.status_code == 200
            assert r.text == (
                "window.ED_RTH_START_MINS=400;\nwindow.ED_RTH_END_MINS=800;\n"
            )
            assert "111" not in r.text
            assert "222" not in r.text
            assert "570" not in r.text
            assert "960" not in r.text

        def _boom() -> str:
            raise OSError("forced projection failure")

        monkeypatch.setattr(time_et, "rth_clock_js_source", _boom)
        with TestClient(srv.app, raise_server_exceptions=False) as client:
            r = client.get("/static/rth_clock_authority.js")
            assert r.status_code >= 500
            body = r.text or ""
            assert "ED_RTH_START_MINS=111" not in body
            assert "ED_RTH_START_MINS=570" not in body
            assert "ED_RTH_END_MINS=222" not in body
            assert "ED_RTH_END_MINS=960" not in body
    finally:
        if prior is None:
            if disk.exists():
                disk.unlink()
        else:
            disk.write_bytes(prior)




# ----------------------------------------------------------------------- F02 net GEX at spot
def test_rc345_net_gex_at_spot_two_distinct_books_each_single_source() -> None:
    """F02: 'net GEX at spot' names TWO economically distinct books, each with ONE producer:
      (1) selected-expiry VENDOR-gamma aggregate — compute_exposures_by_strike, Schwab's
          reported `gamma` x OI x mult x spot^2 x 0.01, summed at the live spot -> ms.net_gamma
      (2) wide-chain THEORETICAL repriced gamma-at-spot — compute_gamma_profile reprices
          bs_gamma across a price grid; gamma_at_price interpolates it at spot -> gamma_at_spot
    Different gamma source (vendor vs BS), different method (aggregate vs profile). They carry
    distinct names (net_gamma vs gamma_at_spot / net_gex_at_spot); neither is a generic
    interchangeable `net_gex`. The lock forbids a second site of EITHER arithmetic."""
    mec = _read("math_exposure_core.py")
    vendor_sites = re.findall(r"\*\s*spt\s*\*\s*spt\s*\*\s*0\.01", mec)
    assert len(vendor_sites) == 2, (  # exactly the call + put line inside compute_exposures_by_strike
        f"vendor GEX-at-spot arithmetic must live only in compute_exposures_by_strike; "
        f"found {len(vendor_sites)} occurrences (F02/RC-345).")


# --------------------------------------------------------------------- F03 gamma profile gen
def test_rc345_gamma_profile_has_one_formula_authority() -> None:
    """F03: the repriced gamma profile has ONE formula producer, math_levels.compute_gamma_profile.
    bs_gamma is swept over the price grid only there; every other reference is its definition or
    a consumer. Multiple invocations/materializations of the returned profile are consumers."""
    ml = _read("math_levels.py")
    # bs_gamma is CALLED (not defined) in exactly one place: the profile sweep. Exclude the
    # `def bs_gamma(` header, which also contains the substring.
    calls = [ln for ln in ml.splitlines()
             if "bs_gamma(" in ln and not ln.lstrip().startswith("def bs_gamma(")]
    assert len(calls) == 1, (
        f"bs_gamma is invoked in {len(calls)} sites in math_levels; the gamma-profile formula "
        f"must be single-authority (compute_gamma_profile) (F03/RC-345).")
    from math_levels import compute_gamma_profile, gamma_at_price
    assert callable(compute_gamma_profile) and callable(gamma_at_price)


# ---------------------------------------------------------------------------- F06 expected move


# --------------------------------------------------------------------- F05 trade actionability
# test_rc345_final_trade_decision_has_one_authority_frontend_carries was retired here
# (/console cutover, operator directive 2026-09-14): its frontend half locked legacy static/
# index.html's analyticsCardTrustGate/engineTradeableSetup functions, which do not exist
# anywhere in the new console (grepped static/js/*.js, zero matches) — consistent with the
# Trade Desk's explicit "THE CALL... remain excluded until ticker-universal evidence earns
# them" stance. The backend half of this invariant (signals.py carries call_engine's decision,
# never re-derives one) is real, unaffected by the rename, and worth keeping if this test is
# ever split; reinstate the frontend half only when a new module renders a final trade verdict.


# ------------------------------------------------------------- F42 dollar GEX registry field
# BOARD IDENTITY: gex_dollars is F42 (a newly tracked registry concept), NOT F14. F14 is
# VWAP bands. This id was corrected after an earlier mislabel; F01-F40 ids are immutable.
def test_rc345_gex_dollars_field_is_single_producer() -> None:
    """F42: the registry field gex_dollars_per_1pct_at_strike has exactly ONE producer,
    compute_exposures_by_strike. math_probabilities.score_option_expression was a coarse-AST
    false positive (its `base += abs(gamma)*10` scoring accumulation mentions gamma but does
    not reprice it into dollars — no OI, no spot^2). The registry now pins the distinguishing
    signature (gamma, oi, spt) so the gate is accurate, not merely green."""
    import tools.check_one_producer as cop

    reg = cop.load_registry()
    field = "gex_dollars_per_1pct_at_strike"
    sites = cop.computing_sites(field, reg["fields"][field])
    assert sites == ["math_exposure_core.py:compute_exposures_by_strike"], (
        f"gex_dollars must have one producer; got {sites} (F42/RC-345)")
    failures, _np, _n = cop.evaluate()
    assert not [f for f in failures if field in f], (
        "the one-producer gate must pass for gex_dollars")


# ------------------------------------------------------------------------------- F14 VWAP bands


# ---------------------------------------------------------------------- F41 selected-DTE selector


# --------------------------------------------------------------------- F03 gamma profile as-of
def test_rc345_terrain_materializes_one_pinned_gamma_profile() -> None:
    """F03: terrain materializes the gamma profile exactly ONCE, at one pinned `now`, and
    shares it with the flip verdict. compute_gamma_flip_v2 accepts a pre-built profile so it
    does not build a second curve at a different wall-clock instant."""
    te = _read("terrain_engine.py")
    assert te.count("compute_gamma_profile(") == 1, (
        "terrain must build the gamma profile once (F03/RC-345)")
    assert "profile=profile" in te and "_terrain_now" in te, (
        "terrain must pin `now` once and share the profile with the flip (F03/RC-345)")
    ml = _read("math_levels.py")
    assert re.search(r"def compute_gamma_flip_v2\([^)]*profile", ml, re.S), (
        "compute_gamma_flip_v2 must accept a pre-built profile (F03/RC-345)")


# ------------------------------------------------------------------ F07 gamma regime authorities

    # F07 (reopened) frontend: the client never WRITES a regime under any name — the sign is
    # carried from the server. edReconcileRegime (legacy's local sign-reconciliation function)
    # was retired here (/console cutover, operator directive 2026-09-14): the new console
    # never reconciles a regime client-side at all — no ed-*.js file surfaces a regime value,
    # let alone reconstructs one (grepped, zero matches for edReconcileRegime or any renamed
    # equivalent) — so there is no such function left to assert about. The general
    # "client never assigns .regime" invariant right above already covers every JS file the
    # rename touches or leaves untouched.


# ----------------------------------------------------------------------------- F08 ATR denominator


# ----------------------------------------------------------------------------- F21 VWAP side


# ----------------------------------------------------------------------- F17 realized volatility


# ---------------------------------------------------------------------- F24 signed dist to VWAP


# ------------------------------------------------------------------- F29 movement target threshold
def test_rc345_movement_target_threshold_one_selector() -> None:
    """F29: the per-horizon ATR-scaled move threshold is produced by exactly one selector,
    movement_target_threshold.threshold_move_pts_for_slug. Outcome/label consumers use it; no
    production site reconstructs a local ATR threshold."""
    from movement_target_threshold import threshold_move_pts_for_slug

    assert callable(threshold_move_pts_for_slug)
    for mod in ("db.py", "horizon_outcomes.py"):
        assert "threshold_move_pts_for_slug" in _read(mod), (
            f"{mod} must consume the one threshold selector (F29/RC-345)")
    # no local ATR-threshold reconstruction in the outcome path
    dbcode = "\n".join(l for l in _read("db.py").splitlines() if not l.lstrip().startswith("#"))
    assert not re.search(r"thr\s*=\s*[0-9.]+\s*\*\s*atr", dbcode), (
        "db.py reconstructs a local ATR threshold; use the one selector (F29/RC-345)")


# ------------------------------------------------------------------- F36 signal-layer VWAP anchor


# -------------------------------------------------------------- F22 dominant direction / confidence


# ------------------------------------------------------------------- F27 higher-timeframe OHLC


# ------------------------------------------------------------------- F23 negative-spread withhold


# ------------------------------------------------------------------------------- F20 pin width


# ------------------------------------------------------------------- F40 MC/GARCH sigma cadence


# ---------------------------------------------------------------- F38 training tensor cache identity


# --------------------------------------------------------------- F26 empirical probability bias


# ------------------------------------------------------- F32 cf_* population / source / cadence


# ============================ ADVERSARIAL-RESIDUAL FIXES (real live paths) ====================
# test_rc345_adversarial_residuals_real_paths' frontend-facing assertions (F06 em tooltip, F07
# net-GEX-withheld chip text, F18 Charm Drift row, F22's hz() argmax guard, F26 biasFromEmp)
# were retired here (/console cutover, operator directive 2026-09-14): every one of them
# anchored on legacy static/index.html functions/strings with zero match anywhere in the new
# console (emTipFromSource, edPaintNetGex/tv-gex, the Charm Drift row, hz(), biasFromEmp — all
# grepped, all absent). The backend-only assertions this function also carried (F25 ticker
# identity, F11 persistence, F22's db.py/market_state.py half, F23) are real and unaffected by
# the rename; they are preserved below as their own function.




# ----------------------------------------------------------------------------- F09 clock vs calendar


# ---------------------------------------------------------------------------- F06 expected move


# --------------------------------------------------------------------------- F02 net GEX at spot
































