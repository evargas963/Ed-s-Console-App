"""PYTEST_TRUST_REBUILD_V1 — census, CI parity, and critical-invariant mutations.

A test is proof only if breaking the claimed invariant fails it. This file
calls the subjects. It does not invent a second obligation checklist.

# next-rth-ok: suite-trust is not a live-session residual
# universal-scope-ok: collected estate, not a ticker sample
# chart-intent-ok: does not claim Chart Done
"""
from __future__ import annotations

import ast
from pathlib import Path

import l1_trade_observation as l1
import order_flow_engine as ofe
import order_flow_live_state as ofls
from tools.pytest_trust_census_v1 import (
    archive_legacy_test_count,
    ci_parity_facts,
    classify_function,
)

REPO = Path(__file__).resolve().parent.parent


def _parse_test(rel: str, name: str) -> ast.FunctionDef:
    tree = ast.parse((REPO / rel).read_text(encoding="utf-8"))
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef) and fn.name == name:
            return fn
    raise AssertionError(f"{rel}::{name} not found")


def test_archive_legacy_audits_are_intentionally_uncollected():
    facts = ci_parity_facts()
    assert facts["archive_legacy_collect_ignore"] is True
    assert archive_legacy_test_count() > 0


def test_ci_pytest_wave_ignores_then_runs_playwright_must_run():
    facts = ci_parity_facts()
    assert facts["ci_offline"] is True
    assert facts["ci_noncanonical_db"] is True
    assert facts["ci_placeholder_schwab"] is True
    assert facts["xdist_ignores_playwright_must_run"] is True
    assert facts["after_e2e_runs_playwright_must_run"] is True
    assert facts["ci_xdist_nproc"] is True
    assert facts["local_make_runs_e2e_then_pytest"] is True
    assert facts["local_make_does_not_drop_playwright_must_run"] is True


def test_census_classifies_l1_behavioral_vs_source_text():
    rel = "tests/test_l1_trade_observation_v1.py"
    replay = classify_function(_parse_test(rel, "test_replay_matches_live_receive_order_semantics"), rel=rel)
    assert replay["proof_type"] in {"TEMPORAL_CAUSAL", "PRODUCTION_PATH", "BEHAVIORAL"}
    assert replay["source_text_only"] is False
    src = classify_function(_parse_test(rel, "test_engine_does_not_sort_by_vendor_time"), rel=rel)
    assert src["proof_type"] == "SOURCE_TEXT"
    assert src["source_text_only"] is True


def test_charm_sign_product_gt_zero_is_not_a_weak_len_assert():
    rel = "tests/test_charm_sign_finite_difference.py"
    row = classify_function(
        _parse_test(rel, "test_bs_charm_sign_matches_finite_difference"), rel=rel
    )
    # fd * bs > 0 is a sign lock, not len(...) > 0.
    assert row["n_asserts"] >= 2
    assert row["weak_asserts"] < row["n_asserts"]


def test_weekday_only_rth_clock_is_a_killed_mutation():
    """The pre-fix is_rth_open (weekday + 16:00) must disagree with the calendar faucet."""
    import datetime as _dt

    from time_et import ET, RTH_END_MINS, RTH_OPEN_MINS, is_tradable_session_ts_utc

    def old_weekday_only(dt: _dt.datetime) -> bool:
        if dt.weekday() >= 5:
            return False
        mins = dt.hour * 60 + dt.minute
        return RTH_OPEN_MINS <= mins < RTH_END_MINS

    holiday = _dt.datetime(2026, 7, 3, 10, 0, tzinfo=ET)
    early_after = _dt.datetime(2026, 11, 27, 14, 0, tzinfo=ET)
    friday = _dt.datetime(2026, 8, 7, 12, 0, tzinfo=ET)
    assert old_weekday_only(holiday) is True
    assert is_tradable_session_ts_utc(holiday.timestamp()) is False
    assert old_weekday_only(early_after) is True
    assert is_tradable_session_ts_utc(early_after.timestamp()) is False
    assert old_weekday_only(friday) is True
    assert is_tradable_session_ts_utc(friday.timestamp()) is True
    assert ofls.is_tradable_session_ts_utc is is_tradable_session_ts_utc


def test_ml_scheduler_rth_ticker_filter_is_calendar_aware():
    """Training ticker selection must not treat Saturday/holiday 10:00 ET as a session."""
    import datetime as _dt
    from pathlib import Path

    from time_et import ET, is_rth_ts_utc, is_tradable_session_ts_utc

    holiday = _dt.datetime(2026, 7, 3, 10, 0, tzinfo=ET).timestamp()
    saturday = _dt.datetime(2026, 8, 22, 10, 0, tzinfo=ET).timestamp()
    friday = _dt.datetime(2026, 8, 7, 12, 0, tzinfo=ET).timestamp()
    assert is_rth_ts_utc(holiday) is True
    assert is_tradable_session_ts_utc(holiday) is False
    assert is_rth_ts_utc(saturday) is True
    assert is_tradable_session_ts_utc(saturday) is False
    assert is_tradable_session_ts_utc(friday) is True
    from tools.find_prove_locks import clock_only_session_gate_violations

    src = (Path(__file__).resolve().parents[1] / "ml_scheduler.py").read_text(encoding="utf-8")
    assert clock_only_session_gate_violations("ml_scheduler.py", src) == []


def test_session_gate_callers_are_calendar_aware_not_clock_only():
    """Scoring/eval session gates: clock-only filter BLOCKS; live files are silent."""
    from pathlib import Path

    from tools.find_prove_locks import clock_only_session_gate_violations

    bare = "def load():\n    if not is_rth_ts_utc(ts):\n        return\n"
    assert clock_only_session_gate_violations("calibration/daily_scoreboard.py", bare)

    repo = Path(__file__).resolve().parents[1]
    session_gate_files = (
        "ml_scheduler.py",
        "calibration/daily_scoreboard.py",
        "calibration/fusion_temperature.py",
        "research/incumbent_eval_v1/runner.py",
        "research/challenger_eval_v1/runner.py",
        "research/structural_eval_v1/runner.py",
    )
    for rel in session_gate_files:
        src = (repo / rel).read_text(encoding="utf-8")
        hits = clock_only_session_gate_violations(rel, src)
        assert hits == [], (rel, hits)


def test_is_rth_open_uses_tradable_session_faucet(monkeypatch):
    import datetime as _dt

    from time_et import ET

    monkeypatch.setattr(
        ofls, "now_et",
        lambda: _dt.datetime(2026, 7, 3, 10, 0, tzinfo=ET),
        raising=True,
    )
    assert ofls.is_rth_open() is False
    monkeypatch.setattr(
        ofls, "now_et",
        lambda: _dt.datetime(2026, 8, 7, 12, 0, tzinfo=ET),
        raising=True,
    )
    assert ofls.is_rth_open() is True


def test_l1_tick_rule_mutation_oracles():
    assert l1.tick_rule_signed_size(100.0, 101.0, 3) == 3.0
    assert l1.tick_rule_signed_size(101.0, 100.0, 3) == -3.0
    assert l1.tick_rule_signed_size(100.0, 101.0, None) is None
    content = [
        {"LAST_PRICE": 100.0, "LAST_SIZE": 10, "TRADE_TIME_MILLIS": 1},
        {"LAST_PRICE": 100.1, "LAST_SIZE": 4, "TRADE_TIME_MILLIS": 1},
    ]
    assert ofe._compute_cum_delta_proxy({"content": content}) == 4


def test_conftest_autouse_admission_is_documented_not_production():
    src = (REPO / "tests/conftest.py").read_text(encoding="utf-8")
    assert "_decision_path_admitted_by_default" in src
    assert "_no_fusion_temperature_calibration" in src
    assert "_equal_mh_pool_weights" in src
    from decision_gate import _DEFAULT_REGISTRY_PATH, evaluate_decision_path_admission

    v = evaluate_decision_path_admission(path=_DEFAULT_REGISTRY_PATH)
    assert v.admitted is False
    assert v.registry_state == "empty"
