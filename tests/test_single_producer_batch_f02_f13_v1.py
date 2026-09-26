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


def test_rc345_feature_atr_variant_is_named_not_generic() -> None:
    """F08: the feature-layer EPS-floored ATR is a DISTINCT contract, explicitly documented
    so it is never conflated with the standard authority."""
    sl = _read("features/signal_layer_v1.py")
    assert "EPS-FLOORED" in sl and "F08" in sl, (
        "signal_layer_v1._atr must declare itself an explicitly distinct ATR contract")


# --------------------------------------------------------------------------- F09 session / RTH


# ------------------------------------------------------------------------- F12 relative volume
def test_rc345_relative_volume_variants_are_distinct_and_fail_closed() -> None:
    """F12 (was NOT_PROVEN): three RVOL-like quantities are ECONOMICALLY DISTINCT, each with
    its own numerator/denominator/window, each fail-closed with NO invalid fallback
    denominator (never a fake 1.0 / substitute average):

      volume_ratio          bar vol / fitted per-minute-of-day MEDIAN  (ml_train, feature) -> NaN
      part.relative_volume  latest bar / ROLLING-WINDOW MEAN           (signal_layer)      -> None
      rvol                  session-cumulative / DAILY 10d|1y AVERAGE  (order_flow)         -> None+reason

    They carry distinct field names, so no consumer can silently substitute one for another."""
    import numpy as np
    from ml_train import fk_volume_ratio

    # fk_volume_ratio: valid ratio, capped, and NaN (never 1.0) when the denominator is unusable.
    out = fk_volume_ratio(np.array([100.0, 100.0, 100.0]), np.array([50.0, 0.0, np.nan]))
    assert out[0] == 2.0
    assert np.isnan(out[1]) and np.isnan(out[2]), "median<=0/NaN must yield NaN, not a fake 1.0"

    # order_flow rvol never substitutes 1.0; missing average is an explicit unavailable reason.
    from app.options.order_flow.engine import _compute_rvol
    val, reason = _compute_rvol({"stream_total_volume": 1_000_000})  # no average anywhere
    assert val is None and reason == "avg_volume_unavailable"

    # signal_layer returns None (not 1.0) when the rolling mean is degenerate.
    sl = _read("features/signal_layer_v1.py")
    assert 'out["part.relative_volume"] = _safe_div(v_last, vm) if vm > EPS else None' in sl

    # F12 (reopened) CONSUMER CONTRACTS — each variant is produced for and consumed by ONE
    # named consumer; no consumer accepts a different RVOL semantic:
    #   volume_ratio          -> ML feature      feats["volume_ratio"] = fk_volume_ratio(...)
    #   part.relative_volume  -> signal feature  out["part.relative_volume"]
    #   rvol                  -> order-flow read  _compute_rvol -> "rvol" payload primitive
    #     (the readiness composite that consumed rvol is RETIRED, mission TRUTH_V1 RC-473/474;
    #      rvol stays an emitted primitive with an explicit unavailable reason)
    mlt = _read("ml_train.py")
    assert 'feats["volume_ratio"] = fk_volume_ratio(' in mlt, (
        "the ML feature consumer must take volume_ratio from fk_volume_ratio (F12/RC-345)")
    assert 'part.relative_volume' not in mlt, (
        "the ML feature path must not consume the signal-layer RVOL variant (F12/RC-345)")
    ofe = _read("app/options/order_flow/engine.py")
    assert "_compute_rvol(data)" in ofe and '"rvol": rvol' in ofe, (
        "order-flow must emit its own session-vs-daily rvol as a primitive (F12/RC-345)")
    assert "OF_RVOL_READINESS_OK" not in ofe, (
        "the retired readiness composite must not reappear as an rvol consumer (RC-474)")
    assert "volume_ratio" not in ofe and "part.relative_volume" not in ofe, (
        "order-flow must not consume the other RVOL variants (F12/RC-345)")


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


def test_rc345_imbalance_taxonomy_is_distinct_and_named() -> None:
    """F11: the several imbalance quantities are economically DISTINCT (different population/
    scope) and must not collapse into a generic field:
      L2 book imbalance / top-of-book pressure  (order_flow_engine, quote-book scope)
      options book imbalance near ATM           (compute_option_flow_imbalance, bid/ask SIZE)
      options call/put VOLUME imbalance ATM      (flow_imbalance volume fallback, ±window)
      options call/put VOLUME imbalance full-chain (order_flow_engine options_flow_score)
    Same formula over a different option population is a different quantity, kept separate."""
    ofe = _read("app/options/order_flow/engine.py")
    assert "options_flow_score = (call_vol - put_vol) / total_opt_vol" in ofe
    mp = _read("math_probabilities.py")
    # The ATM volume fallback is windowed (atm_flow_window_totals), a different population.
    assert "atm_flow_window_totals" in mp


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
def test_rc345_signals_py_carries_call_engine_decision_never_rederives() -> None:
    sig = _read("signals.py")
    assert "final_signal=call.signal" in sig, (
        "signals.py must carry the call_engine decision, not derive its own")
    assert not re.search(r"final_signal\s*=\s*['\"](long|short|wait)['\"]", sig), (
        "signals.py re-derives a final trade signal — call_engine is the one authority")


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
def test_rc345_vwap_bands_canonical_single_source_frontend_carries() -> None:
    """F14 (VWAP BANDS): the canonical operator/terrain VWAP band (volume-weighted session
    sigma of typical price) is produced once, by liquidity_value_engine.compute_vwap_bands.
    Every liquidity consumer calls it; the frontend CARRIES raw.vwap_bands and never
    recomputes vwap +/- sigma in JS. The signal-layer feature band (simple rolling residual
    std) is a DISTINCT methodology, explicitly named so it is not conflated."""
    lve = _read("liquidity_value_engine.py")
    assert lve.count("def compute_vwap_bands(") == 1, (
        "the volume-weighted VWAP band must have one producer (F14/RC-345)")
    # Frontend carries, never recomputes the band. Repointed to static/js/ed-gamma-levels.js
    # (/console cutover, operator directive 2026-09-14): the new console carries d.vwap_series
    # (a differently-named but equally honest carry-not-recompute pattern — its own comment
    # says "carried VWAP curve... disclosed (never fabricated)") rather than legacy's
    # raw.vwap_bands.
    html = _read("static/js/ed-gamma-levels.js")
    assert "d.vwap_series" in html, "frontend must carry the server vwap_series"
    assert not re.search(r"vwap\w*\s*[+\-]\s*[0-9.]*\s*\*?\s*(std|sigma)", html), (
        "frontend recomputes a VWAP band locally — it must carry the server value (F14/RC-345)")
    # The feature-layer band declares itself distinct (not the canonical band).
    sl = _read("features/signal_layer_v1.py")
    assert "EXPLICITLY DISTINCT band" in sl and "F14" in sl, (
        "signal_layer VWAP-band feature must be named as a distinct methodology (F14/RC-345)")


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
def test_rc345_atr_denominator_is_fully_classified(repo_index) -> None:
    """F08: the ATR semantic denominator is complete — the standard TR+SMA ATR has one
    producer (math_volatility.compute_atr); the RTH-session wrapper delegates; the feature
    EPS-floored variant is named distinct; db._snapshot_row_atr READS a stored value (not a
    producer); no Wilder/T-1 second producer exists."""
    from math_volatility import compute_atr

    assert callable(compute_atr)
    db = _read("db.py")
    seg = db[db.index("def _snapshot_row_atr"):]
    seg = seg[: seg.index("\ndef ", 1)]
    assert 'row["atr"]' in seg and "for " not in seg.split("return")[0], (
        "_snapshot_row_atr must READ the stored atr, not compute one (F08/RC-345)")
    # no production Wilder ATR producer
    for mod in ("math_volatility.py", "liquidity_value_engine.py", "features/signal_layer_v1.py"):
        assert "def wilder" not in _read(mod).lower()

    # F08 (reopened): the research Wilder ATR (research/pilot_step3/atr.wilder_atr_14) is
    # MECHANICALLY QUARANTINED — no production or model-serving module may import it, so a
    # different-methodology (RMA/Wilder) ATR can never masquerade as the standard SMA ATR.
    # TEST_SYSTEM_REHAB_V2 final remediation: migrated off an independent `git ls-files`
    # re-scan onto the shared `repo_index` fixture.
    excluded = ("tests/", "research/", "tools/", "calibration/", "arch_competition/",
                "scratchpad/", "governance/")
    for relpath, body, _tree in repo_index.items():
        rel = relpath.as_posix()
        if rel.startswith(excluded):
            continue
        assert "wilder_atr" not in body and "pilot_step3.atr" not in body, (
            f"{rel} reaches the research Wilder ATR — it must stay quarantined (F08/RC-345)")


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
def test_rc345_signal_layer_vwap_anchor_is_source_tagged() -> None:
    """F36: session-derived vl.* slots use canonical session VWAP or stay absent.

    A rolling VWAP must not occupy those slots — tagging the old mix was not fidelity.
    """
    sl = _read("features/signal_layer_v1.py")
    assert 'out["meta.vwap_source"] = "session"' in sl
    assert 'vwap_use = vwap_roll' not in sl
    assert 'out["meta.vwap_source"] = "roll"' not in sl
    assert "W_VWAP_ROLL" not in sl


# -------------------------------------------------------------- F22 dominant direction / confidence


# ------------------------------------------------------------------- F27 higher-timeframe OHLC


# ------------------------------------------------------------------- F23 negative-spread withhold


# ------------------------------------------------------------------------------- F20 pin width


# ------------------------------------------------------------------- F40 MC/GARCH sigma cadence
def test_rc345_mc_blend_sigma_uses_mc_cadence() -> None:
    """F40: the GARCH-unavailable fallback _blend_sigma annualizes the ATR leg at the MC's OWN
    cadence (BAR_MINUTES), not a hardcoded 252*78 (5m) factor that under-scaled the 1m ATR by
    sqrt(5) and mixed cadences with the 1m realized-vol/GARCH legs."""
    mc = _read("monte_carlo.py")
    assert "bars_per_year = 252 * (390.0 / BAR_MINUTES)" in mc, (
        "the blend ATR leg must annualize at the MC cadence (F40/RC-345)")
    assert "bars_per_year = 252 * 78" not in mc, (
        "the hardcoded 5m annualization must be gone (F40/RC-345)")


# ---------------------------------------------------------------- F38 training tensor cache identity
def test_rc345_tensor_cache_key_includes_data_content_identity() -> None:
    """F38 NEGATIVE CONTROL: two datasets with IDENTICAL metadata (min_ts/max_ts/row_count)
    but DIFFERENT underlying content (an in-place label mutation) must produce DIFFERENT cache
    keys — otherwise a stale tensor is reused. The fingerprint now carries a content_hash over
    the (ts_utc, label) pairs, and the key includes it."""
    from training_cache import compute_feature_cache_key

    base = {"table": "snapshots_1m_normalized", "timeframe": "1m", "ticker": "SPY",
            "min_ts_utc": 1000.0, "max_ts_utc": 2000.0, "row_count": 390}
    fp_a = {**base, "content_hash": "aaaaaaaaaaaaaaaa"}
    fp_b = {**base, "content_hash": "bbbbbbbbbbbbbbbb"}  # same metadata, mutated content
    key_a = compute_feature_cache_key("SPY", fp_a, "codefp", target_column="outcome_1c")
    key_b = compute_feature_cache_key("SPY", fp_b, "codefp", target_column="outcome_1c")
    assert key_a != key_b, (
        "same metadata + different content must MISS the cache (F38/RC-345)")
    # identical fingerprints still hit (same key)
    assert key_a == compute_feature_cache_key("SPY", dict(fp_a), "codefp", target_column="outcome_1c")
    # the DB fingerprint reads the label to build the content hash
    tc = _read("training_cache.py")
    assert "SELECT ts_utc, {label_column} FROM snapshots_1m_normalized" in tc, (
        "the DB fingerprint must read the label to detect in-place mutation (F38/RC-345)")
    assert '"content_hash"' in tc and 'data_fp, "content_hash"' in tc


# --------------------------------------------------------------- F26 empirical probability bias


# ------------------------------------------------------- F32 cf_* population / source / cadence
def test_rc345_confluence_features_full_contract_one_authority() -> None:
    """F32: cf_* has ONE authority end-to-end — ml_data_common.confluence_features_for_bar.
    SOURCE: it fetches the canonical population via fetch_confluence_history (a raw as-of DB
    read), not caller rows. KERNEL: compute_confluence_features is called ONLY inside the
    authority (never by a production lane with its own rows). MISSINGNESS: an absent
    population is a governed absence (cf_* stay 0.0), not a substitute. CONSUMERS: XGB
    (prepare_row_for_xgb_features) and LSTM (ml_predict) both go through the authority."""
    mdc = _read("ml_data_common.py")
    assert "def confluence_features_for_bar(" in mdc and "def fetch_confluence_history(" in mdc
    # the kernel is called only inside the authority (its single production call site)
    prod_kernel_calls = [ln for ln in mdc.splitlines()
                         if "compute_confluence_features(" in ln
                         and "def compute_confluence_features" not in ln]
    assert len(prod_kernel_calls) == 1, (
        "compute_confluence_features must be the authority's internal kernel only (F32/RC-345)")
    # governed absence: cf_* absence is 0.0, not a caller-rows fallback
    assert "GOVERNED ABSENCE" in mdc or "governed absence" in mdc
    # both model lanes consume via the authority
    assert "confluence_features_for_bar" in _read("ml_predict.py"), (
        "LSTM serve path must use the cf_* authority (F32/RC-345)")


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


def test_rc345_f25_canonical_ticker_identity_one_producer():
    """F25 — CANONICAL_TICKER_STORAGE_AND_ARTIFACT_IDENTITY has exactly ONE live-reachable
    producer (instrument_identity.ticker_storage_key). Every artifact/model/cache/DB-query/
    verifier/predictor/scheduler identity delegates to it, so a single instrument can never
    acquire two artifact identities. Behavioral + mutation-grade: the SPX/$SPX collapse is the
    load-bearing case (bare 'SPX' and '$SPX' both map to the on-disk '$SPX' bundle)."""
    from instrument_identity import ticker_storage_key, BROKER_INDEX_BARE_ROOTS
    import training_cache as tc
    import active_bundle_contract as abc
    import ml_predict as mp
    import ml_scheduler as sched

    # ── The authority itself: SPX and $SPX are the SAME identity, and it is '$SPX'. ──
    assert ticker_storage_key("SPX") == ticker_storage_key("$SPX") == "$SPX"
    assert ticker_storage_key("spx") == ticker_storage_key("$spx") == "$SPX"  # case variants
    assert "SPX" in BROKER_INDEX_BARE_ROOTS

    # ── Every producer resolves to ticker_storage_key for the full identity contract. ──
    # (runtime → storage → artifact → model-dir → bundle-file → cache → predictor)
    CASES = ["SPX", "$SPX", "spx", "$spx", "SPY", "spy", "QQQ", "IWM"]
    for tk in CASES:
        canon = ticker_storage_key(tk)
        # artifact filename producers (training_cache) — the divergence surface
        assert tc.parallel_artifact_basenames(tk, "1c")[0] == f"xgb_{canon}_1c.pkl"
        assert tc.cascade_artifact_basenames(tk, "1c")[0] == f"xgb_{canon}_1c.pkl"
        # contract producers (active_bundle_contract)
        assert abc.bundle_role_filenames(tk, "1c")["xgb"] == f"xgb_{canon}_1c.pkl"
        assert abc.active_bundle_dir(tk, "1c").name == canon
        assert abc.meta_stack_artifact_filename(tk, "1c") == f"meta_{canon}_1c.pkl"
        assert abc.horizon_bundle_filenames(tk, "1c")[0] == f"xgb_{canon}_1c.pkl"
        # predictor / registry identity (ml_predict)
        assert mp._bundle_ticker_for_artifacts(tk) == canon
        assert mp._reg_key(tk).endswith(f":{canon}")
        # scheduler artifact identity flows from the same one producer
        assert sched._artifact_paths_relative.__module__  # importable/callable

    # ── Mutation 2 (SPX divergence): the TWO filename authorities agree for $SPX. ──
    # horizon_bundle_filenames delegates to training_cache.parallel_artifact_basenames;
    # bundle_role_filenames uses artifact_ticker_key. If either reverts to a local .upper(),
    # this equality breaks for the index root.
    for tk in ("SPX", "$SPX"):
        hz_names = set(abc.horizon_bundle_filenames(tk, "1c"))
        role_names = set(abc.bundle_role_filenames(tk, "1c").values())
        assert role_names.issubset(hz_names), f"role/horizon filename authorities diverged for {tk}"

    # ── Mutation 3 (scheduler vs predictor divergence): writer identity == loader identity. ──
    # scheduler writes to parallel_artifact_basenames names; predictor loads active_bundle_dir.
    for tk in ("SPX", "$SPX"):
        writer_name = tc.parallel_artifact_basenames(tk, "1c")[0]          # xgb_$SPX_1c.pkl
        loader_dirname = abc.active_bundle_dir(mp._bundle_ticker_for_artifacts(tk), "1c").name
        assert f"_{loader_dirname}_" in writer_name, "scheduler-written vs predictor-loaded identity diverged"

    # ── Mutation 4 (cache divergence): SPX and $SPX produce the SAME cache identity. ──
    data_fp = {"table": "snapshots_1m_normalized", "timeframe": "1m",
               "min_ts_utc": 1.0, "max_ts_utc": 2.0, "content_hash": "abc123", "row_count": 10}
    assert tc.compute_feature_cache_key("SPX", data_fp, "cfp") == \
           tc.compute_feature_cache_key("$SPX", data_fp, "cfp"), "cache identity split SPX vs $SPX"
    assert tc.compute_scheduler_cache_key("SPX", "parallel", data_fp, "cfp") == \
           tc.compute_scheduler_cache_key("$SPX", "parallel", data_fp, "cfp")

    # ── Mutation 1 (delegated second producer): no bare .upper() identity faucet remains in the
    # swept files (comment/docstring references excluded). A reintroduced local_model_key(t)=t.upper()
    # routed into any real path would reintroduce a `ticker.upper()` identity call here. ──
    for fname in ("training_cache.py", "ml_predict.py", "verify_active_models.py",
                  "ml_scheduler.py", "active_bundle_contract.py"):
        body = "\n".join(
            l for l in _read(fname).splitlines()
            if not l.lstrip().startswith("#") and not l.lstrip().startswith('"')
            and not l.lstrip().startswith("'")
        )
        assert "ticker.upper()" not in body, f"{fname}: bare .upper() ticker-identity faucet reintroduced (F25)"
        assert "from instrument_identity import ticker_storage_key" in _read(fname), (
            f"{fname} must consume the canonical ticker-identity authority")

    # ── Live-path proof: the real on-disk $SPX bundle resolves identically from bare 'SPX'. ──
    d_bare = abc.active_bundle_dir("SPX", "1c")
    d_dollar = abc.active_bundle_dir("$SPX", "1c")
    assert d_bare == d_dollar
    if d_dollar.is_dir():  # bundle present in this checkout
        assert (d_dollar / abc.bundle_role_filenames("SPX", "1c")["xgb"]).is_file(), (
            "bare-'SPX' resolves to the real on-disk $SPX artifact (no orphan)")


def test_rc345_f25_train_writers_match_canonical_read_basenames():
    """F25 (train-write faucet — Cursor RC-345 reopening). The MODEL WRITERS must emit the
    SAME artifact basename the readers/verifier/predictor expect. Before this lock, bare 'SPX'
    wrote xgb_SPX_1c.pkl while bundle_role_filenames/active_bundle_dir expected xgb_$SPX_1c.pkl —
    a live second producer of ticker-artifact identity. This asserts WRITE basename == canonical
    READ basename for XGB/LSTM/Transformer/meta across the SPX/$SPX negative control."""
    import ml_train, lstm_model, transformer_train
    from active_bundle_contract import bundle_role_filenames, meta_stack_artifact_filename
    from instrument_identity import ticker_storage_key

    MATRIX = ["SPY", "QQQ", "IWM", "SPX", "$SPX", "spx", "$spx"]
    for tk in MATRIX:
        read = bundle_role_filenames(tk, "1c")
        canon = ticker_storage_key(tk)
        # XGB writer (ml_train) == canonical read
        assert ml_train.model_path(tk).name == read["xgb"] == f"xgb_{canon}_1c.pkl", (
            f"XGB train-write vs read divergence for {tk}: "
            f"{ml_train.model_path(tk).name} != {read['xgb']}")
        assert ml_train.meta_path(tk).name == read["xgb_meta"]
        # LSTM writer == canonical read
        assert lstm_model.lstm_model_path(tk).name == read["lstm"] == f"lstm_{canon}_1c.pt"
        assert lstm_model.lstm_meta_path(tk).name == read["lstm_meta"]
        # Transformer writer == canonical read
        assert transformer_train.transformer_model_path(tk).name == read["transformer"] == \
            f"transformer_{canon}_1c.pt"
        assert transformer_train.transformer_meta_path(tk).name == read["transformer_meta"]
        # META writer basename == canonical
        assert meta_stack_artifact_filename(tk, "1c") == f"meta_{canon}_1c.pkl"

    # SPX and $SPX must collapse to the identical write basename (the load-bearing case)
    for kind, wf in (("xgb", lambda t: ml_train.model_path(t).name),
                     ("lstm", lambda t: lstm_model.lstm_model_path(t).name),
                     ("transformer", lambda t: transformer_train.transformer_model_path(t).name)):
        assert wf("SPX") == wf("$SPX"), f"{kind} writer splits SPX vs $SPX"

    # source guard: the train writers must consume the canonical authority, no local .upper()
    for fname in ("ml_train.py", "lstm_model.py", "transformer_train.py"):
        assert "from instrument_identity import ticker_storage_key" in _read(fname), (
            f"{fname} must import the canonical ticker-identity authority (F25 train-write)")








def test_rc345_f25_load_data_binds_canonical_storage_key():
    """F25 (Cursor ACCEPT_PARTIAL — train DB-load faucet). ml_train.load_data must bind the
    CANONICAL storage identity to the SQL query: load_data('SPX', ...) binds '$SPX'. The callee
    itself consumes the canonical identity — a caller passing bare 'SPX' still queries the '$SPX'
    stored rows. Mutation guard: reverting to ``params.append(ticker)`` binds raw 'SPX' and fails."""
    import ml_train
    import pandas as pd
    import normalized_training_sync as nts

    captured: dict = {}
    orig_read = pd.read_sql_query
    orig_norm = nts.inline_normsync_enabled
    try:
        pd.read_sql_query = lambda sql, conn, params=None, **k: (captured.__setitem__("params", params), __import__("pandas").DataFrame())[1]
        nts.inline_normsync_enabled = lambda: False  # no side effects in the test
        import tempfile, os, sqlite3
        p = os.path.join(tempfile.mkdtemp(), "e.db")
        sqlite3.connect(p).close()
        ml_train.load_data(db_path=p, ticker="SPX")
    finally:
        pd.read_sql_query = orig_read
        nts.inline_normsync_enabled = orig_norm

    assert "$SPX" in (captured.get("params") or []), (
        f"load_data must bind canonical '$SPX', bound: {captured.get('params')!r}")
    assert "SPX" not in [x for x in (captured.get("params") or []) if x == "SPX"], (
        "load_data bound raw 'SPX' — DB identity faucet still live")

    # Source guard: the DB-facing function canonicalizes at entry.
    src = _read("ml_train.py")
    assert "ticker = ticker_storage_key(ticker)" in src, (
        "ml_train.load_data must canonicalize ticker at function entry (F25)")


def test_rc345_f25_training_fingerprint_producers_are_canonical():
    """F25 (Cursor ACCEPT_PARTIAL — fingerprint faucets). db_training_fingerprint and
    _normalize_data_fp must emit the CANONICAL ticker so SPX and $SPX fingerprints compare equal.
    Behavioral: same-DB SPX vs $SPX fingerprints carry the same ticker field; two fps differing
    only in the alias normalize equal. Mutation guard: raw ``str(t)`` passthrough splits them."""
    import training_cache as tc
    import tempfile, os, sqlite3

    # db_training_fingerprint: SPX and $SPX emit the same canonical ticker identity (empty-table
    # path still stamps the ticker field, so no real rows are required for the identity assertion).
    p = os.path.join(tempfile.mkdtemp(), "e.db")
    sqlite3.connect(p).close()
    fp_bare = tc.db_training_fingerprint(p, "SPX")
    fp_dollar = tc.db_training_fingerprint(p, "$SPX")
    assert fp_bare["ticker"] == fp_dollar["ticker"] == "$SPX", (
        f"db_training_fingerprint split identity: {fp_bare['ticker']!r} vs {fp_dollar['ticker']!r}")
    # SPY (non-dollar) is preserved as SPY — not blindly prefixed.
    assert tc.db_training_fingerprint(p, "spy")["ticker"] == "SPY"

    # _normalize_data_fp: two otherwise-identical fps differing only in alias normalize equal.
    base = {"table": "snapshots_1m_normalized", "timeframe": "1m",
            "min_ts_utc": 1.0, "max_ts_utc": 2.0, "row_count": 10}
    n_bare = tc._normalize_data_fp({**base, "ticker": "SPX"})
    n_dollar = tc._normalize_data_fp({**base, "ticker": "$SPX"})
    assert n_bare == n_dollar, f"_normalize_data_fp did not converge: {n_bare} != {n_dollar}"
    assert n_bare["ticker"] == "$SPX"

    # Source guard: both producers consume the one authority (no raw ticker passthrough).
    src = _read("training_cache.py")
    assert "t = ticker_storage_key(ticker)" in src, "db_training_fingerprint must canonicalize at entry"
    assert 'ticker_storage_key(str(d.get("ticker"' in src, "_normalize_data_fp must canonicalize the ticker field"


def test_rc345_f25_db_training_floor_stats_canonical_bind():
    """F25 (Cursor: floor_stats fix accepted, RECURRENCE LOCK missing). db_training_floor_stats
    must bind + emit the canonical storage identity: SPX and $SPX resolve to '$SPX'. Mutation
    guard here (source): a reverted ``str(ticker).strip().upper()`` producer fails the check."""
    import training_cache as tc
    import tempfile, os, sqlite3

    p = os.path.join(tempfile.mkdtemp(), "e.db")
    sqlite3.connect(p).close()  # schema-absent path still stamps the ticker identity field
    a = tc.db_training_floor_stats(p, "SPX")
    b = tc.db_training_floor_stats(p, "$SPX")
    assert a["ticker"] == b["ticker"] == "$SPX", (
        f"db_training_floor_stats split identity: {a['ticker']!r} vs {b['ticker']!r}")
    assert tc.db_training_floor_stats(p, "spy")["ticker"] == "SPY"  # non-dollar preserved

    # Recurrence lock: the function canonicalizes at entry; a raw local producer is rejected.
    lines = _read("training_cache.py").splitlines()
    idx = next(i for i, l in enumerate(lines) if l.startswith("def db_training_floor_stats("))
    body = "\n".join(lines[idx:idx + 40])
    assert "ticker = ticker_storage_key(ticker)" in body, (
        "db_training_floor_stats must canonicalize ticker at entry")
    assert ".strip().upper()" not in body, "floor_stats: raw local ticker producer reintroduced"










def test_rc345_f25_scheduler_user_tickers_enrollment_identity_canonical():
    """F25 (Cursor: scheduler_user_tickers enrollment/filter faucet). Membership/enrollment identity
    routes through ticker_storage_key so SPX and $SPX are one instrument. SPY/QQQ/IWM are unchanged.
    Mutation: a raw .upper() membership compare would let 'SPX' and '$SPX' disagree."""
    import scheduler_user_tickers as sut

    # anchor membership: canonical, SPY/QQQ/IWM preserved
    assert sut.is_training_anchor_ticker("spy") is True
    assert sut.is_training_anchor_ticker("SPY") is True
    # index alias collapse in the guard (expansion on so any ticker is allowed, identity canonical)
    import os
    os.environ["ED_ML_SCHEDULER_TRAINING_EXPAND"] = "1"
    try:
        assert sut.require_ml_training_ticker_allowed("SPX") == \
            sut.require_ml_training_ticker_allowed("$SPX") == "$SPX"
    finally:
        del os.environ["ED_ML_SCHEDULER_TRAINING_EXPAND"]

    # filter membership: SPX vs $SPX are one identity for skip/enrolled comparisons
    key = sut.ticker_storage_key
    assert key("SPX") == key("$SPX") == "$SPX"

    # Source guard: no raw .upper() ticker-membership compare remains in the file (code, not docstring)
    body = "\n".join(l for l in _read("scheduler_user_tickers.py").splitlines()
                     if not l.lstrip().startswith("#"))
    assert ".upper()" not in body, "scheduler_user_tickers: raw .upper() membership faucet remains"


def test_rc345_f25_cache_skip_streak_key_canonical():
    """F25 (Cursor latest #1). cache_skip_streak_key is the ONE producer of the streak dict key;
    write/read/lookup all flow through it, so SPX and $SPX must share one streak slot ("$SPX:...").
    Mutation: reverting to f"{ticker.upper()}:..." splits the aliases and fails."""
    import training_pipeline_status as tps

    keys = {tps.cache_skip_streak_key(a, "1c") for a in ("SPX", "$SPX", "spx", "$spx")}
    assert keys == {"$SPX:1c"}, f"cache_skip_streak_key split the index identity: {keys}"
    assert tps.cache_skip_streak_key("spy", "1c") == "SPY:1c"  # non-dollar preserved

    lines = _read("training_pipeline_status.py").splitlines()
    idx = next(i for i, l in enumerate(lines) if l.startswith("def cache_skip_streak_key("))
    body = "\n".join(lines[idx:idx + 8])
    assert "ticker_storage_key(ticker)" in body, "cache_skip_streak_key must delegate to the authority"
    assert "ticker.upper()" not in body, "cache_skip_streak_key: raw .upper() faucet reintroduced"


def test_rc345_f25_arch_eval_proof_key_canonical(tmp_path):
    """F25 (Cursor latest #2). save_arch_eval_proof_merge keys by_ticker on canonical identity, so a
    $SPX merge lands on the same slot a prior SPX merge wrote (one identity, one row). Mutation:
    reverting to ticker.upper() would leave two rows ('SPX' and '$SPX')."""
    import eval_metrics_store as ems
    import json

    proof = tmp_path / "proof.json"
    orig = ems.arch_eval_proof_path
    try:
        ems.arch_eval_proof_path = lambda: proof
        ems.save_arch_eval_proof_merge("SPX", {"updated_at": "t1", "v": 1})
        ems.save_arch_eval_proof_merge("$SPX", {"updated_at": "t2", "v": 2})
    finally:
        ems.arch_eval_proof_path = orig

    doc = json.loads(proof.read_text(encoding="utf-8"))
    assert list(doc["by_ticker"].keys()) == ["$SPX"], (
        f"arch_eval_proof kept two identities: {list(doc['by_ticker'].keys())}")
    assert doc["by_ticker"]["$SPX"]["v"] == 2  # $SPX merge overwrote the SPX slot

    src = _read("eval_metrics_store.py")
    assert "ticker_storage_key(ticker)" in src, "save_arch_eval_proof_merge must key on the authority"
    assert "ticker.upper()" not in src, "arch eval proof: raw .upper() key faucet reintroduced"


