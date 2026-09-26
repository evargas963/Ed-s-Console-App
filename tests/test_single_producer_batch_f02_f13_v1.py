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
def test_rc345_candle_direction_has_one_authority() -> None:
    """F10: up/down/flat from a candle's move is classified once, by
    math_probabilities.classify_direction (0.05%-of-open dead-band). The bar-rehydration
    path (snapshot_normalizer.resample_to_1m) must delegate, not re-derive a strict `c > o`
    sign — the two disagreed near zero, a train/serve equality-contract skew."""
    from math_probabilities import classify_direction

    assert classify_direction(1.0, 100.0) == "up"
    assert classify_direction(-1.0, 100.0) == "down"
    assert classify_direction(0.0, 100.0) == "flat"
    # inside the dead-band (< 0.05% of 100 = 0.05 pts) → flat, not a strict-sign up
    assert classify_direction(0.01, 100.0) == "flat"

    sn = _read("snapshot_normalizer.py")
    assert "classify_direction" in sn, "snapshot_normalizer must consume the one authority"
    code = "\n".join(ln for ln in sn.splitlines() if not ln.lstrip().startswith("#"))
    assert '"up" if c > o' not in code and "'up' if c > o" not in code, (
        "snapshot_normalizer re-derives candle direction with a strict `c > o` sign; it "
        "must call math_probabilities.classify_direction (F10/RC-345).")

    # F10 (reopened) SEMANTIC MIGRATION RESOLVED: the canonical candle-direction is DEAD-BAND
    # (classify_direction), which the LIVE server has always produced — that is the production
    # serve semantic. snapshot_normalizer's strict-sign was a backfill-only shadow (MEASURED
    # 19.1% label delta on 372 stored bars) now aligned, so train = backfill = live = replay.
    # Prove BOTH producers delegate to the one authority and no strict-sign shadow survives.
    srv3 = _read("server.py")
    assert "classify_direction as _classify_direction" in srv3, (
        "live server candle direction must be the dead-band authority (F10/RC-345)")
    assert "_candle_dir  = _classify_direction(_bar_move" in srv3
    # No production site reconstructs candle direction with a strict close-vs-open sign.
    for mod in ("server.py", "snapshot_normalizer.py", "market_state.py"):
        mcode = "\n".join(l for l in _read(mod).splitlines() if not l.lstrip().startswith("#"))
        assert '"up" if c > o' not in mcode and "'up' if" not in mcode, (
            f"{mod} has a strict-sign candle-direction shadow (F10/RC-345)")

    # F10: the candle-direction dead-band is the ONE canonical authority on every producer
    # (live server + snapshot_normalizer backfill), so a fresh train reads aligned dead-band
    # data. The PREPROCESSING_VERSION bump is DELIBERATELY NOT done here: the parity test
    # test_feature_schema_version_matches_trained_artifacts enforces (2026-06-11 outage class)
    # that the version flips only WITH the retrained artifacts, never ahead. The migration is a
    # coordinated scheduler retrain-then-bump; F10 stays OPEN until that runs. This lock only
    # guards the code-side single authority (above), not a premature version flip.
    from training_provenance import PREPROCESSING_VERSION
    assert PREPROCESSING_VERSION == "v5_no_m5_lag", (
        "PREPROCESSING_VERSION must NOT flip ahead of retrained artifacts (F10 outage class)")


# ---------------------------------------------------------------------------- F13 time-to-expiry
def test_rc345_valuation_T_has_one_authority() -> None:
    """F13: the Black-Scholes valuation-T (year fraction) is produced once, by
    time_et.time_to_expiry_years (intraday ACT/365 to session close). No production greek
    site may feed a local whole-day `dte / 365` into a bs_* pricer — math_exposure_core's
    vanna faucet used to, disagreeing with the charm/gamma clock near expiry."""
    from time_et import time_to_expiry_years

    assert callable(time_to_expiry_years)

    mec = _read("math_exposure_core.py")
    # The exact defect pattern: a /365 division sitting in a BS greek's T argument.
    assert not re.search(r"/\s*365(\.0)?\s*,\s*_iv", mec), (
        "math_exposure_core feeds a whole-day dte/365 as the BS-vanna T; it must use "
        "time_et.time_to_expiry_years (F13/RC-345).")
    assert "time_to_expiry_years" in mec, (
        "compute_exposures_by_strike must source T from the canonical authority")

    # A2 lifecycle greeks must also source T from the one authority, not a local dte/365.
    a2 = _read("v2_decision/a2_option_expression.py")
    assert "time_to_expiry_years" in a2, (
        "a2_option_expression must source valuation T from time_et (F13/RC-345)")
    a2code = "\n".join(ln for ln in a2.splitlines() if not ln.lstrip().startswith("#"))
    assert not re.search(r"return\s+dte\s*/\s*365", a2code), (
        "a2_option_expression re-derives T as dte/365; it must delegate to time_et (F13/RC-345)")


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
def test_rc345_rth_clock_boundary_has_one_authority() -> None:
    """F09: the RTH clock boundary (09:30–16:00 ET) is defined once, in time_et
    (RTH_START_MINS/RTH_END_MINS, is_rth_ts_utc). lstm_data and db must alias that authority,
    never re-hardcode 9/30/16/0 or 570/960."""
    import time_et

    assert time_et.RTH_START_MINS == 570 and time_et.RTH_END_MINS == 960
    assert time_et.is_rth_ts_utc  # canonical clock predicate exists

    lstm = _read("lstm_data.py")
    assert "_RTH_START_MINS" in lstm and "RTH_START_MINS as _RTH_START_MINS" in lstm, (
        "lstm_data must import the RTH boundary from time_et")
    code = "\n".join(ln for ln in lstm.splitlines() if not ln.lstrip().startswith("#"))
    assert "RTH_START_HOUR      = 9" not in code and "RTH_END_HOUR        = 16" not in code, (
        "lstm_data re-hardcodes the RTH boundary; it must alias time_et (F09/RC-345).")

    dbsrc = _read("db.py")
    dbcode = "\n".join(ln for ln in dbsrc.splitlines() if not ln.lstrip().startswith("#"))
    assert "ACCURACY_RTH_START_MIN: int = 570" not in dbcode, (
        "db.py re-hardcodes 570 for the RTH window; it must alias time_et (F09/RC-345).")
    assert "_RTH_START_MINS_AUTH" in dbsrc
    # F09 (reopened): db.market_session must NOT re-hardcode 570/960 either — it aliases the
    # authority; and it is calendar-aware (is_trading_day_et decides first).
    seg = dbsrc[dbsrc.index("def market_session("):]
    seg = seg[: seg.index("\ndef ", 1)]
    segcode = "\n".join(ln for ln in seg.splitlines() if not ln.lstrip().startswith("#"))
    assert "< 570" not in segcode and "< 960" not in segcode, (
        "db.market_session re-hardcodes the RTH boundary; alias time_et (F09/RC-345).")
    assert "_RTH_START_MINS_AUTH" in segcode and "is_trading_day_et" in segcode
    # F09 (reopened): the LSTM no-ts_utc fallback is calendar-aware (is_trading_day_et on the
    # row's ET date) or fails closed — never a silent clock-only RTH.
    lstm_fb = lstm[lstm.index("def extract_rth_snapshots"):]
    assert "is_trading_day_et(day_key)" in lstm_fb, (
        "lstm RTH fallback must be calendar-aware, not clock-only (F09/RC-345)")

    # F09 residual (2026-08-19, current main): live money-path still re-encoded
    # 570/960. Those sites must alias time_et, not a second literal.
    mv = _read("math_volatility.py")
    mv_fn = mv[mv.index("def session_bucket"):]
    mv_fn = mv_fn[: mv_fn.index("\ndef ", 1)]
    mv_code = "\n".join(ln for ln in mv_fn.splitlines() if not ln.lstrip().startswith("#"))
    assert "RTH_START_MINS" in mv_code and "RTH_END_MINS" in mv_code, (
        "session_bucket must cut RTH open/close via time_et (F09)")
    assert "570" not in mv_code and "960" not in mv_code, (
        "session_bucket re-hardcodes the RTH boundary (F09)")

    l1 = _read("planes/l1_thresholds.py")
    l1_code = "\n".join(ln for ln in l1.splitlines() if not ln.lstrip().startswith("#"))
    assert "from time_et import" in l1 and "RTH_START_MINS" in l1_code and "RTH_END_MINS" in l1_code
    assert "570" not in l1_code, "l1_thresholds re-hardcodes RTH open (F09)"

    # The A2 sidecar no longer computes minutes-since-open (it carries The Call's plan,
    # ONE FAUCET 2026-09-24), so it must not re-encode the RTH boundary anywhere.
    a2 = _read("v2_decision/a2_lifecycle_sidecar.py")
    a2_code = "\n".join(ln for ln in a2.splitlines() if not ln.lstrip().startswith("#"))
    assert "570" not in a2_code and "_mins_elapsed_since_open" not in a2_code, (
        "A2 sidecar re-derives the session clock (F09)")

    srv = _read("server.py")
    assert "RTH_CLOSE_MINS:      int   = RTH_END_MINS" in srv or "RTH_CLOSE_MINS: int = RTH_END_MINS" in srv.replace(" ", "")
    # tolerate formatting: the assignment must be the alias, not 960
    close_assign = [ln.split("#", 1)[0] for ln in srv.splitlines() if ln.startswith("RTH_CLOSE_MINS")]
    assert close_assign and "RTH_END_MINS" in close_assign[0] and "960" not in close_assign[0]
    # MARKET_CLOSE_HOUR (a second, hour-denominated close constant) was deleted: nothing in
    # server.py read it. RTH_CLOSE_MINS above is the one
    # close authority left in server.py; a re-added hour constant would be a second one.
    mkt_assign = [ln.split("#", 1)[0] for ln in srv.splitlines() if ln.startswith("MARKET_CLOSE_HOUR")]
    assert mkt_assign == [], "server.py re-grew a second RTH close constant (F09)"
    cont_assign = [ln.split("#", 1)[0] for ln in srv.splitlines() if ln.startswith("TERRAIN_CONTENTION_START_MINS")]
    assert cont_assign and "RTH_OPEN_MINS" in cont_assign[0] and "570" not in cont_assign[0]

    # F09 repo-wide (2026-08-19): frontend + research/tools/training consume time_et,
    # they do not re-author 570/960. Display-copy "09:30" in a stage name is not a cut.
    # The JS projection is served at request time from time_et — a committed static
    # blob is a second authority and must not exist.
    from pathlib import Path as _Path
    from time_et import rth_clock_js_source
    assert not (_Path("static") / "rth_clock_authority.js").exists(), (
        "committed static/rth_clock_authority.js is a second RTH clock (F09)"
    )
    assert "rth_clock_js_source" in srv and '"/static/rth_clock_authority.js"' in srv
    assert "app.add_api_route" in srv
    route_at = srv.index('"/static/rth_clock_authority.js"')
    mount_at = srv.index('app.mount("/static"')
    assert route_at < mount_at, "RTH clock route must precede StaticFiles mount (F09)"
    assert 'rth_clock_authority.js").write_text' not in srv
    assert "projection failed" not in srv
    js_src = rth_clock_js_source()
    assert "window.ED_RTH_START_MINS=" in js_src and "window.ED_RTH_END_MINS=" in js_src

    def _exec_js(path: str) -> str:
        src = _read(path)
        return "\n".join(
            ln for ln in src.splitlines()
            if not ln.lstrip().startswith(("//", "*", "<!--", "*"))
        )

    # Independent-review finding, REPRODUCED (/console cutover, operator directive
    # 2026-09-14): static/console.html does not include rth_clock_authority.js at all
    # (confirmed by direct grep) -- unlike legacy static/index.html, the new console never
    # does client-side RTH-boundary math; session labeling is carried entirely from the
    # server (d.session_label, painted by ed-core.js's paintSession()). The F09 invariant
    # this guards -- no second, hardcoded RTH-boundary authority on the client -- holds by
    # absence rather than by requiring the shared script, so the check here is that no
    # ed-*.js file reinvents the minute-boundary constants, not that it sources them from
    # rth_clock_authority.js.
    for js_path in Path(REPO / "static" / "js").glob("*.js"):
        js_src = js_path.read_text(encoding="utf-8", errors="replace")
        assert "RTH_START_MINS" not in js_src and "ED_RTH_START_MINS" not in js_src, (
            f"{js_path.name} reads an RTH-boundary constant with no rth_clock_authority.js "
            f"script tag to source it from — a silent second authority (F09/RC-345 class)"
        )
    chart = _exec_js("static/chart.html")
    assert 'src="/static/rth_clock_authority.js"' in _read("static/chart.html")
    assert "ED_RTH_START_MINS" in chart and "ED_RTH_END_MINS" in chart
    assert "mm >= 570" not in chart and "mm < 960" not in chart

    am = _read("audit_model_readiness.py")
    assert "from time_et import" in am and "RTH_START_MINS" in am
    assert ">= 570" not in am
    a2e = _read("v2_decision/a2_eod_force_exit.py")
    assert "RTH_OPEN_MINUTE_TOTAL = RTH_START_MINS" in a2e
    assert "9 * 60 + 30" not in a2e and "16 * 60" not in a2e
    a2o = _read("v2_decision/a2_option_expression.py")
    assert "_RTH_CLOSE_MINUTE_TOTAL = RTH_END_MINS" in a2o
    a2c = _read("v2_decision/a2_session_calendar.py")
    assert "open_minute = int(RTH_START_MINS)" in a2c
    ns = _read("news_sentiment.py")
    assert "RTH_START_MINS" in ns and "m < 30" not in ns
    lve = _read("liquidity_value_engine.py")
    assert "RTH_OPEN_MINS" in lve and "time(9, 29)" not in lve.split("def _cutoff_for_snapshot")[1][:800]
    tbr = _read("tools/terrain_backtest_report_v1.py")
    assert "RTH_START_MINS" in tbr and "9 * 60 + 45" not in tbr


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
def test_rc345_persisted_flow_imbalance_has_one_producer() -> None:
    """F11: the persisted `flow_imbalance` field is produced by exactly one authority —
    math_probabilities.option_flow_book_imbalance (book only; its call/put VOLUME fallback was
    deleted 2026-09-24, audit S-06) — on BOTH the live server path
    and backfill. The live path used to persist compute_option_flow_imbalance's book-only
    'normalized' (NULL when ATM book was ~0, later filled by backfill's volume fallback): two
    producers for one column and a train/serve skew."""
    srv = _read("server.py")
    assert "option_flow_book_imbalance" in srv, (
        "live server must persist flow_imbalance via the one authority")
    assert 'flow_imbalance=_flow_imbalance.get("normalized")' not in srv, (
        "live server still persists the book-only value; it must use the wrapper (F11/RC-345)")
    bf = _read("backfill_flow_imbalance.py")
    assert "option_flow_book_imbalance" in bf, (
        "backfill must use the same one authority as live")

    # The authority is governed: it always returns a source discriminator, never a bare value
    # that could silently substitute call/put VOLUME imbalance for bid/ask BOOK imbalance.
    from math_probabilities import option_flow_book_imbalance
    val, src = option_flow_book_imbalance({}, 0.0)
    assert val is None and src == "none", "empty input must fail closed with src='none'"

    # F11 (reopened) SOURCE travels beside the value: the live server captures the source
    # book and emits flow_imbalance_source into the payload, so a consumer can tell 'book'
    # (bid/ask size) from 'volume' (call/put traded volume) — not a bare generic number.
    assert "_flow_imb_norm, _flow_imb_source = option_flow_book_imbalance" in srv, (
        "live server must capture the flow_imbalance SOURCE, not discard it (F11/RC-345)")
    assert 'ms_dict["flow_imbalance_source"] = _flow_imb_source' in srv, (
        "the flow_imbalance source must reach the payload beside the value (F11/RC-345)")
    # F11 residual (2026-08-19): label must classify the SAME number, not a
    # second book-only compute. MEASURED: empty ATM book + call-heavy volume
    # used to publish 0.6 / volume beside label="balanced".
    srv_code = "\n".join(ln for ln in srv.splitlines() if not ln.lstrip().startswith("#"))
    assert "compute_option_flow_imbalance(" not in srv_code, (
        "live server must not independently compute the book-only kernel (F11)")
    assert "flow_imbalance_label_from_normalized(_flow_imb_norm)" in srv, (
        "flow_imbalance_label must be a function of the wrapper number (F11)")
    from math_probabilities import (
        compute_option_flow_imbalance,
        flow_imbalance_label_from_normalized,
        option_flow_book_imbalance,
    )
    exposures = {
        100.0: {
            "call_bid_size": 0, "call_ask_size": 0,
            "put_bid_size": 0, "put_ask_size": 0,
            "call_volume": 80, "put_volume": 20,
        }
    }
    book = compute_option_flow_imbalance(exposures, 100.0)
    val, src = option_flow_book_imbalance(exposures, 100.0)
    # empty displayed book: no imbalance, and no call/put VOLUME ratio standing in (S-06)
    assert (val, src) == (None, "none")
    assert book.get("label") is None and book.get("normalized") is None
    assert flow_imbalance_label_from_normalized(val) is None

    # F11 LIVE-handler contract: the /api/state assignment is these three fields from one
    # number -- all absent together on this tick.
    served = {
        "flow_imbalance": val,
        "flow_imbalance_source": src,
        "flow_imbalance_label": flow_imbalance_label_from_normalized(val),
    }
    assert served == {"flow_imbalance": None, "flow_imbalance_source": "none",
                      "flow_imbalance_label": None}


def test_f11_api_state_volume_fallback_triple_after_lifespan() -> None:
    """F11 + S-06 (2026-09-24): after app lifespan, GET /api/state serves the flow_imbalance
    triple from the ONE book producer. On an empty ATM book with call-heavy VOLUME the triple
    is ABSENT (None / "none" / None) -- it used to serve the volume ratio 0.6 under the book
    field (the deleted volume fallback).

    This image has no Schwab token. The persist stamps are the live server
    imports (wrapper + label_from_normalized). The tick is SYNTHETIC_WIRE
    (empty ATM book, call 80 / put 20). GET /api/state is the live cache-serve
    path after that tick is published the way _fetch_state writes _state_cache.
    """
    import time

    import pytest

    pytest.importorskip("fastapi")
    import server as srv
    from math_probabilities import compute_option_flow_imbalance
    from starlette.testclient import TestClient
    from time_et import rth_clock_js_source

    exposures = {
        100.0: {
            "call_bid_size": 0, "call_ask_size": 0,
            "put_bid_size": 0, "put_ask_size": 0,
            "call_volume": 80, "put_volume": 20,
        }
    }
    book = compute_option_flow_imbalance(exposures, 100.0)
    val, src = srv.option_flow_book_imbalance(exposures, 100.0)
    label = srv.flow_imbalance_label_from_normalized(val)
    assert (val, src, label) == (None, "none", None)
    assert book.get("label") is None

    ms = {
        "ticker": "SPY",
        "spot": 100.0,
        "flow_imbalance": val,
        "flow_imbalance_source": src,
        "flow_imbalance_label": label,
        "f11_wire": "SYNTHETIC_EMPTY_BOOK_TICK",
    }
    now = time.time()
    cache_key = ("SPY", "2099-01-01")
    srv._state_cache[cache_key] = {
        "ts": now,
        "generated_at": now,
        "analytics_version": 1,
        "ms_dict": dict(ms),
        "pcr_val": None,
        "spot_f": 100.0,
        "vix": None,
        "price_levels": None,
        "pl_date": "",
        "pl_mono": None,
    }

    with TestClient(srv.app) as client:
        js = client.get("/static/rth_clock_authority.js")
        assert js.status_code == 200
        assert js.text == rth_clock_js_source()
        r = client.get("/api/state", params={"ticker": "SPY"})
        assert r.status_code == 200
        body = r.json()
        assert body.get("flow_imbalance") is None
        assert body.get("flow_imbalance_source") == "none"
        assert body.get("flow_imbalance_label") is None


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
def test_rc345_selected_dte_selectors_both_key_on_expiry() -> None:
    """F41: 'selected option DTE' is read by two population-scoped selectors —
    market_state._schwab_days_to_expiration_for_contract (over the caller's single-expiry
    slice) and server._selected_schwab_days_to_expiration (over the full chain, filters
    itself). They can never silently disagree on WHICH expiry: the market_state selector now
    self-enforces the expiry filter, and its callers pass the selected expiry."""
    ms = _read("market_state.py")
    # The selector accepts and filters on an expiry key.
    assert re.search(r"def _schwab_days_to_expiration_for_contract\([^)]*expiry", ms), (
        "market_state DTE selector must take an expiry argument (F41/RC-345)")
    assert 'str(ct.get("expirationDate") or "")[:10] != exp_key' in ms, (
        "market_state DTE selector must filter contracts by expiry (F41/RC-345)")
    # Both callers pass the selected expiry.
    assert ms.count("_schwab_days_to_expiration_for_contract(") >= 2
    assert "expiry=exp" in ms and "expiry=(ms.call_option_expiry or ms.selected_exp)" in ms, (
        "both market_state callers must pass the selected expiry (F41/RC-345)")
    # server's full-chain selector already keys on expiry (expirationDate slice).
    srv = _read("server.py")
    assert "def _selected_schwab_days_to_expiration(" in srv
    seg = srv[srv.index("def _selected_schwab_days_to_expiration("):]
    seg = seg[: seg.index("\ndef ", 1)]
    assert "expirationDate" in seg and "exp_key" in seg, (
        "server DTE selector must filter by expiry (F41/RC-345)")


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
def test_rc345_vwap_side_has_one_authority() -> None:
    """F21: vwap side (above/below) is classified once, by math_snapshot_derive.derive_vwap_side.
    market_state consumes it — it no longer re-derives `spot > vwap` inline (a shadow of the
    same semantic). Every other vwap_side= is a carrier of the produced value."""
    from math_snapshot_derive import derive_vwap_side

    assert derive_vwap_side(101, 100) == "above" and derive_vwap_side(99, 100) == "below"
    assert derive_vwap_side(100, 100) == "below" and derive_vwap_side(100, None) is None
    ms = _read("market_state.py")
    assert "derive_vwap_side(spot_f, _vwap_val)" in ms, (
        "market_state must consume the one vwap-side authority (F21/RC-345)")
    mcode = "\n".join(l for l in ms.splitlines() if not l.lstrip().startswith("#"))
    assert '"above" if spot_f > _vwap_val' not in mcode, (
        "market_state re-derives vwap side inline; it must call derive_vwap_side (F21/RC-345)")


# ----------------------------------------------------------------------- F17 realized volatility


# ---------------------------------------------------------------------- F24 signed dist to VWAP
def test_rc345_vwap_dist_is_signed_train_and_serve() -> None:
    """F24: vwap_dist_pts is the SIGNED distance (spot - vwap) on BOTH the training producer
    (backfill_snapshot_derived) and the live serve (market_state). The prior abs() in
    market_state made the live feature absolute while training was signed — a train/serve skew
    that discarded the sign. Direction is carried separately by vwap_side."""
    ms = _read("market_state.py")
    assert "vwap_dist_pts=round(spot_f - _vwap_val, 4)" in ms, (
        "market_state vwap_dist_pts must be SIGNED (spot - vwap) (F24/RC-345)")
    assert "round(abs(spot_f - _vwap_val)" not in ms, (
        "market_state must not store an ABSOLUTE vwap distance (F24/RC-345)")
    bf = _read("backfill_snapshot_derived.py")
    assert "round(spot_f - eff_vwap, 4)" in bf, (
        "the training producer must also be signed (F24/RC-345)")


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
def test_rc345_higher_tf_ohlc_one_feature_synthesizer() -> None:
    """F27: the batch 1m->N-minute OHLC synthesis used for FEATURES has one authority,
    signal_layer_v1._aggregate_bars (both the 5m and the 15m multi-timeframe features flow
    through it). The server's display/context rollup (server.aggregate_bars over the streamed
    price_bars_1m) is a DISTINCT consumer — a different population — and is itself ONE
    synthesizer: _bars_5m and the chart's /api/bars1m timeframes both roll up through it."""
    sl = _read("features/signal_layer_v1.py")
    assert sl.count("def _aggregate_bars(") == 1, (
        "one batch higher-timeframe OHLC synthesizer for features (F27/RC-345)")
    assert "_aggregate_bars(tail5, 5)" in sl and "_aggregate_bars(tail15, 15)" in sl, (
        "both 5m and 15m features must flow through the one synthesizer (F27/RC-345)")
    # the server's display rollup has one synthesizer of its own, fed by price_bars_1m
    srv = _read("server.py")
    assert srv.count("def aggregate_bars(") == 1, "one server-side 1m->N-minute rollup"
    i = srv.index("def _bars_5m(")
    assert 'aggregate_bars([_bar_dict(c) for c in _bars_1m(' in srv[i:i + 600], (
        "the server's 5m bars must roll up from price_bars_1m through aggregate_bars")
    assert "_CandleAccumulator" not in srv, "a second, tick-accumulated bar source reappeared"


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
def test_rc345_adversarial_residuals_backend_only_paths() -> None:
    """The backend half of the surviving adversarial defects (frontend half retired above)."""
    # F18: charm_drift_toward is WITHHELD — server no longer feeds the net-GEX peak as the
    # charm target (a different-Greek substitution).
    srv18 = _read("server.py")
    assert "drift_toward_strike=None" in srv18 and "drift_toward_strike=_institutional_pin" not in srv18, (
        "charm must not borrow the net-GEX peak as its target (F18/RC-345)")

    # F22 accuracy: no `or 0` fabrication — rows with a missing pred triplet are SKIPPED.
    _dbc_for_f22 = _read("db.py")
    assert "row[f\"pred_{horizon}_up_prob\"]   or 0" not in _dbc_for_f22, (
        "accuracy must not fabricate a pred from `or 0` (F22/RC-345)")
    assert "if _pu is None or _pd is None or _pf is None:" in _dbc_for_f22

    # F25 (foundation pointer): full canonical-ticker-identity adjudication lives in
    # test_rc345_f25_canonical_ticker_identity_one_producer below (SPX/$SPX + all producers).
    from active_bundle_contract import artifact_ticker_key
    from instrument_identity import ticker_storage_key
    assert artifact_ticker_key("spy") == ticker_storage_key("spy") == "SPY"

    # F11: flow_imbalance_source is PERSISTED (SnapshotRow field + schema column + write).
    from db import SnapshotRow
    assert "flow_imbalance_source" in SnapshotRow.__dataclass_fields__
    dbsrc = _read("db.py")
    assert "flow_imbalance_source   TEXT" in dbsrc and '("flow_imbalance_source",   "TEXT")' in dbsrc
    assert "flow_imbalance_source=_flow_imb_source" in _read("server.py"), (
        "the source must be persisted on the snapshot row (F11/RC-345)")

    # F22: db.py accuracy uses the ONE argmax authority.
    dbcode = "\n".join(l for l in dbsrc.splitlines() if not l.lstrip().startswith("#"))
    assert "predicted = max(probs, key=probs.get)" not in dbcode, (
        "db.py must not re-argmax the pred triplet (F22/RC-345)")
    assert "direction_from_normalized_triplet" in dbsrc
    assert "pred_dominant_by_horizon" in _read("market_state.py"), (
        "backend must emit the per-horizon dominant from the authority (F22/RC-345)")

    # F23: the REAL live authority (contract_spread_pts_from_bid_ask) withholds crossed quotes.
    from v2_decision.a2_price_precedence import contract_spread_pts_from_bid_ask, resolve_a2_contract_spread
    assert contract_spread_pts_from_bid_ask(1.0, 1.2) == 0.2
    assert contract_spread_pts_from_bid_ask(1.2, 1.2) == 0.0
    assert contract_spread_pts_from_bid_ask(1.3, 1.2) is None  # crossed -> withheld
    assert resolve_a2_contract_spread(bid=1.3, ask=1.2) == (None, None)




# ----------------------------------------------------------------------------- F09 clock vs calendar


# ---------------------------------------------------------------------------- F06 expected move
def test_rc345_operator_em_band_carries_its_methodology() -> None:
    """F06: the operator-facing EM band is never anonymous — server records em_band_source
    (STRADDLE_IMPLIED vs IV_MODEL vs unavailable) alongside the band so a consumer cannot
    treat a straddle-implied band as an IV-model band or vice versa."""
    srv = _read("server.py")
    # F06 END-TO-END: the OPERATOR-FACING kl_em band (terrain implied-1d-move) carries its
    # methodology to the served payload — kl_em_source travels beside kl_em_upper/lower, and
    # is 'unavailable' (never dropped) when the band is absent.
    assert 'md["kl_em_source"] = "IV_SIGMA_1D"' in srv and 'md["kl_em_source"] = "unavailable"' in srv, (
        "the operator kl_em band must carry its methodology to the payload (F06/RC-345)")
    kl = srv[srv.index('md["kl_em_upper"] = round'):]
    kl = kl[:900]
    assert "kl_em_source" in kl, "kl_em_source must be emitted with kl_em_upper (F06/RC-345)"
    # the diagnostic straddle/iv path still records its own source too
    assert "_em_band_source" in srv and "STRADDLE_IMPLIED" in srv and "IV_MODEL" in srv
    assert '_em_up = _em_straddle.get("upper") or _em_iv.get("upper")' not in srv
    # RC-433: density congestion must bind terrain IV_SIGMA_1D, not remaining-risk binders.
    dens = srv.split("# Build levels dict for density check", 1)[1].split(
        "_level_density = compute_level_density", 1
    )[0]
    dens_code = "\n".join(
        ln for ln in dens.split("_all_levels = {}", 1)[1].splitlines()
        if ln.strip() and not ln.lstrip().startswith("#")
    )
    assert "implied_1d_move" in dens_code
    assert "if _em_up:" not in dens_code
    assert "_em_up" not in dens_code


# --------------------------------------------------------------------------- F02 net GEX at spot
def test_rc345_net_gex_books_are_consumer_separated() -> None:
    """F02: the vendor-gamma aggregate (net_gamma) and the repriced profile-at-spot book
    (net_gex_at_spot / gamma_at_spot) reach consumers under DISTINCT names. terrain sources
    net_gex_at_spot from the repriced gamma_at_spot; the frontend reads d.net_gamma (vendor
    chip) and d.net_gex_at_spot separately — neither is a generic interchangeable `net_gex`.

    Repointed to static/js/ed-trade-desk.js (/console cutover, operator directive 2026-09-14):
    d.net_gex_at_spot (the repriced profile-at-spot book) has a real consumer there. The
    vendor-aggregate book (net_gamma / "Total Net GEX (per 1%)") has NO consumer anywhere in
    the new console (grepped static/js/*.js and static/console.html, zero matches) — flagged
    for the operator as a real, if minor, gap rather than asserted here."""
    te = _read("terrain_engine.py")
    assert 'net_gex_at_spot=flip_diag.get("gamma_at_spot")' in te, (
        "terrain net_gex_at_spot must come from the repriced profile book (F02/RC-345)")
    html = _read("static/js/ed-trade-desk.js")
    assert "d.net_gex_at_spot" in html, "the repriced profile-at-spot book name is missing"
    srv = _read("server.py")
    assert '_net_gex_raw = getattr(cs, "net_gamma", None)' in srv, (
        "kl_net_gex must be the vendor aggregate (cs.net_gamma), same book as net_gamma")
    # the gex label/regime helpers are book-agnostic PURE functions (take a value arg).
    mec = _read("math_exposure_core.py")
    assert "def gex_regime_label(net_gex" in mec and "def gex_magnitude_label(net_gex" in mec


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


def test_rc345_f25_resume_and_arch_competition_identity_canonical():
    """F25 (Cursor's second reopening — resume artifacts + arch_competition). The training
    RESUME checkpoints and the arch_competition per-instrument state/log paths must use the SAME
    canonical ticker identity as the model artifacts, so bare 'SPX' and '$SPX' resolve to the same
    resume file and the same arch dir the writers/readers expect."""
    from instrument_identity import ticker_storage_key
    from arch_competition.notification_delivery import (
        notification_delivery_log_path, notification_dedup_state_path)
    from arch_competition.operational_policy import operational_policy_artifact_path
    from pathlib import Path

    md = Path("models")
    MATRIX = ["SPY", "QQQ", "IWM", "SPX", "$SPX", "spx", "$spx"]
    for tk in MATRIX:
        canon = ticker_storage_key(tk)
        # arch_competition per-instrument dirs must carry the canonical identity segment
        assert notification_delivery_log_path(md, "1c", tk).parent.name == canon, (
            f"arch notification dir identity != canonical for {tk}")
        assert notification_dedup_state_path(md, "1c", tk).parent.name == canon
        assert operational_policy_artifact_path(md, "1c", tk).parent.name == canon
    # SPX and $SPX collapse to the same arch dir (load-bearing)
    assert notification_delivery_log_path(md, "1c", "SPX").parent.name == \
        notification_delivery_log_path(md, "1c", "$SPX").parent.name == "$SPX"

    # resume checkpoint identity: save_ticker/save_ticker_early are canonical, and the resume
    # filename is built from them (so resume WRITE identity == canonical artifact identity).
    lstm_src = _read("lstm_model.py")
    tfmr_src = _read("transformer_train.py")
    assert "save_ticker = ticker_storage_key(" in lstm_src
    assert "lstm_{save_ticker}_{hz}_train_resume.pt" in lstm_src
    assert "save_ticker_early = ticker_storage_key(" in tfmr_src
    assert "transformer_{save_ticker_early}_{hz}_train_resume.pt" in tfmr_src

    # every swept arch_competition file consumes the one authority
    for fname in ("arch_competition/promotion_execution.py", "arch_competition/stack_bundle_eval_v1.py",
                  "arch_competition/ablation_bundle_inference.py", "arch_competition/notification_delivery.py",
                  "arch_competition/operational_policy.py", "arch_competition/scheduler_integration.py",
                  "arch_competition/manual_control.py", "arch_competition/governance_visibility.py",
                  "arch_competition/live_drift_monitoring.py", "tools/feature_curation_gate.py"):
        assert "from instrument_identity import ticker_storage_key" in _read(fname), (
            f"{fname} must consume the canonical ticker-identity authority (F25 sibling sweep)")






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






def test_rc345_f25_arch_state_writer_reader_share_canonical_key():
    """F25 (Cursor: arch_state writer/reader identity split). ml_scheduler writes arch_state keyed
    by ticker_storage_key; server.py reads with ticker_storage_key. Behavioral: a state written
    under 'SPX' is retrieved under '$SPX' (and reverse). Mutation: a raw writer key OR raw reader
    key breaks the cross-alias retrieval."""
    from instrument_identity import ticker_storage_key

    # The contract: writer key == reader key == canonical. Simulate the exact key derivation.
    arch_state: dict = {}
    arch_state[ticker_storage_key("SPX")] = {"active_architecture": "parallel"}      # writer("SPX")
    assert arch_state.get(ticker_storage_key("$SPX")) == {"active_architecture": "parallel"}, (
        "reader('$SPX') must hit writer('SPX') state")
    arch_state2: dict = {}
    arch_state2[ticker_storage_key("$SPX")] = {"active_architecture": "cascade"}      # writer("$SPX")
    assert arch_state2.get(ticker_storage_key("SPX")) == {"active_architecture": "cascade"}, (
        "reader('SPX') must hit writer('$SPX') state")

    # Source guards: both sides route through the one authority.
    sched = _read("ml_scheduler.py")
    assert "arch_key = ticker_storage_key(ticker)" in sched, "arch_state writer key must be canonical"
    assert "arch_state[arch_key]" in sched, "arch_state must be written under the canonical key"
    srv = _read("server.py")
    assert "arch.get(ticker_storage_key(ticker))" in srv, "arch_state reader key must be canonical"




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


