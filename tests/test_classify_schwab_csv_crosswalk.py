from __future__ import annotations

from tools.classify_schwab_csv_crosswalk import classify, disposition_for


def _row(**overrides):
    base = {
        "file": "server.py",
        "line": "1",
        "tags": "",
        "names": "",
        "candidate_schwab_fields": "",
        "code": "x = 1",
    }
    base.update(overrides)
    return base


def test_classifier_flags_schwab_primitive_default_risk():
    classification, reason = classify(
        _row(
            tags="DEFAULT_ZERO_OR",
            names="spot",
            candidate_schwab_fields="quotes.quote.lastPrice|quotes.quote.mark",
            code='spot = row.get("spot") or 0.0',
        )
    )

    assert classification == "CSV_PRIMITIVE_RISK_REVIEW"
    assert "Schwab primitive" in reason


def test_classifier_excludes_tests_and_docs_from_runtime_residual():
    classification, _reason = classify(
        _row(
            file="tests/test_example.py",
            tags="DEFAULT_ZERO_OR",
            names="spot",
            candidate_schwab_fields="quotes.quote.lastPrice",
            code='spot = row.get("spot") or 0.0',
        )
    )

    assert classification == "NOT_MARKET_RUNTIME"


def test_classifier_flags_time_authority_review():
    classification, _reason = classify(
        _row(
            file="features/inference_snapshot.py",
            tags="TIME_NOW_FALLBACK",
            code="as_of_ts = time.time()",
        )
    )

    assert classification == "TIME_AUTHORITY_REVIEW"


def test_classifier_marks_true_analytics_for_provenance_review():
    classification, _reason = classify(
        _row(
            file="math_exposure_core.py",
            tags="DEFAULT_ZERO_OR",
            names="gamma",
            candidate_schwab_fields="chains.callExpDateMap.*.gamma",
            code="b['net_gamma'] = b.get('call_gamma', 0.0) - b.get('put_gamma', 0.0)",
        )
    )

    assert classification == "TRUE_ANALYTIC_REVIEW"


def test_disposition_marks_primitive_risk_for_manual_review():
    row = _row(
        tags="DEFAULT_ZERO_OR",
        names="spot",
        candidate_schwab_fields="quotes.quote.lastPrice",
        code='spot = row.get("spot") or 0.0',
    )

    classification, _reason = classify(row)
    disposition, _disp_reason, manual = disposition_for(classification, row)

    assert disposition == "REPLACE_WITH_SCHWAB_OR_GATE"
    assert manual is True


def test_disposition_auto_closes_non_market_runtime():
    row = _row(file="tests/test_example.py", tags="DEFAULT_ZERO_OR", names="spot")

    classification, _reason = classify(row)
    disposition, _disp_reason, manual = disposition_for(classification, row)

    assert disposition == "NOT_MARKET_DATA"
    assert manual is False


def test_call_engine_qqq_spy_delta_is_not_option_chain_delta():
    classification, reason = classify(
        _row(
            file="call_engine.py",
            names="delta",
            candidate_schwab_fields="chains.callExpDateMap.*.delta",
            code="delta = qqq - spy",
        )
    )
    assert classification == "NOT_MARKET_DATA"
    assert "QQQ" in reason


def test_debug_flow_snapshot_classifies_as_offline_echo():
    classification, reason = classify(
        _row(
            file="debug_flow_snapshot.py",
            tags="DEFAULT_ZERO_OR",
            names="totalVolume|volume",
            code='''"totalVolume": ct.get("totalVolume") or 0''',
        )
    )
    assert classification == "NOT_MARKET_DATA"
    assert "offline" in reason.lower()


def test_monte_carlo_mc_feature_volatility_coercion_is_true_analytic():
    classification, reason = classify(
        _row(
            file="monte_carlo.py",
            tags="DEFAULT_ZERO_OR",
            names="volatility",
            candidate_schwab_fields="chains.volatility",
            code='"volatility": float(self.volatility or 0.0),',
        )
    )
    assert classification == "TRUE_ANALYTIC_REVIEW"
    assert "MonteCarloOutput" in reason or "fusion" in reason.lower()


def test_monte_carlo_main_selftest_literals_not_market_data():
    classification, reason = classify(
        _row(
            file="monte_carlo.py",
            names="high|spot",
            code='r_pin = simulate(spot=570.0, iv=0.18, regime="pinning", regime_confidence="high",',
        )
    )
    assert classification == "NOT_MARKET_DATA"
    assert "self-test" in reason.lower()


def test_live_drift_monitoring_delta_ece_string_not_option_delta():
    classification, reason = classify(
        _row(
            file="arch_competition/live_drift_monitoring.py",
            names="delta",
            code='"evidence": f"max abs delta ECE={max_d:.4f}",',
        )
    )
    assert classification == "NOT_MARKET_DATA"
    assert "ECE" in reason


def test_db_coverage_timestamp_delta_not_option_greek():
    classification, reason = classify(
        _row(
            file="verification/db_coverage.py",
            names="delta",
            code="gap_hint = f\"{gc} pairwise gap(s) with delta(ts_utc) > 120s (1m continuity heuristic)\"",
        )
    )
    assert classification == "NOT_MARKET_DATA"
    assert "timestamp" in reason.lower() or "ts_utc" in reason.lower()


def test_batch3_db_utc_ts_is_operational_clock():
    classification, reason = classify(
        _row(
            file="db.py",
            tags="TIME_NOW_FALLBACK",
            code="return _wall_time.time()",
        )
    )
    assert classification == "NOT_MARKET_DATA"
    assert "utc_ts" in reason.lower() or "bookkeeping" in reason.lower()


def test_batch3_fetch_state_monotonic_pipeline_not_time_authority():
    classification, reason = classify(
        _row(
            tags="TIME_NOW_FALLBACK",
            code='_minimal["_pipeline_ms"] = round((_minimal_end_mono - _fetch_start_mono) * 1000)',
        )
    )
    assert classification == "NOT_MARKET_DATA"
    assert "monotonic" in reason.lower()


def test_batch3_candle_tick_ts_uses_schwab_parse_not_wall():
    classification, reason = classify(
        _row(
            tags="TIME_NOW_FALLBACK",
            code="_tick_ts = parsed.quote_time or parsed.trade_time",
        )
    )
    assert classification == "NOT_MARKET_DATA"
    assert "schwab" in reason.lower() or "candle" in reason.lower()
