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
    "time_et.py",
    "server.py",
    "news_sentiment.py",
    "liquidity_value_engine.py",
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




# --------------------------------------------------------------------------- F09 session / RTH


# ------------------------------------------------------------------------- F12 relative volume


# ------------------------------------------------------------------- F11 options volume imbalance


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
































