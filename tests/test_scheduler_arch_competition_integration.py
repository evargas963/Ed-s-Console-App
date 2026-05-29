"""Scheduler integration: governed eval/promotion persistence, no default active/ copy."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from arch_competition.exceptions import (
    PromotionGovernanceError,
    PromotionGovernanceInvalidError,
    PromotionGovernanceMissingError,
)
from arch_competition.scheduler_integration import (
    GOVERNED_ARCH_STATE_REQUIRED_KEYS,
    GOVERNED_ARCH_STATE_SCHEMA_VERSION,
    _merge_summary_file,
    arch_competition_summary_path,
    assert_no_active_directory_write,
    build_arch_competition_summary_tick,
    build_governed_arch_state_slice,
    evaluation_manifest_path,
    promotion_decision_path,
    run_governed_architecture_competition_pass,
    scheduler_auto_promote_to_active_enabled,
    validate_persisted_governed_artifacts_or_raise,
    load_architecture_competition_visibility,
)
from arch_competition.eval_runner import EVALUATION_MANIFEST_SCHEMA_VERSION
from arch_competition.promotion_engine import PROMOTION_RECORD_SCHEMA_VERSION


def _minimal_manifest():
    return {
        "schema_version": EVALUATION_MANIFEST_SCHEMA_VERSION,
        "created_at_utc": "2026-01-01T00:00:00+00:00",
        "ticker": "SPY",
        "ml_horizon_slug": "1c",
        "target_column": "outcome_1c",
        "db_path": "/tmp/x.db",
        "parallel_model_dir": "/p",
        "cascade_model_dir": "/c",
        "allowed_et_dates": None,
        "oos_et_dates_fingerprint": None,
        "lineage": {
            "feature_cache_key": "fk",
            "data_fingerprint": {
                "min_ts_utc": "a",
                "max_ts_utc": "b",
                "row_count": 1,
                "table": "t",
                "timeframe": "1m",
                "ticker": "SPY",
            },
            "ml_horizon_suffix": "1c",
            "training_code_fingerprint": "tc",
            "canonical_feature_contract_version": "v1",
            "canonical_timeframe": "1m",
        },
        "lineage_fingerprints": {},
        "metrics": {
            "parallel": {
                "architecture": "parallel",
                "n_rows_scored": 100,
                "accuracy": 0.5,
                "balanced_accuracy": 0.5,
                "log_loss": 0.9,
                "brier_score": 0.2,
                "stability_log_loss_std_halves": 0.01,
                "regime_slices": {"mid": {"n": 50, "balanced_accuracy": 0.5, "skipped_low_support": False}},
                "confidence_reliability": {},
                "realized_contract_metrics": {},
            },
            "cascade": {
                "architecture": "cascade",
                "n_rows_scored": 100,
                "accuracy": 0.5,
                "balanced_accuracy": 0.5,
                "log_loss": 0.95,
                "brier_score": 0.21,
                "stability_log_loss_std_halves": 0.02,
                "regime_slices": {"mid": {"n": 50, "balanced_accuracy": 0.5, "skipped_low_support": False}},
                "confidence_reliability": {},
                "realized_contract_metrics": {},
            },
        },
        "metric_breakdown": {},
        "rolling_oos_windows": [],
        "architecture_comparison_summary": {},
    }


def _minimal_record():
    return {
        "schema_version": PROMOTION_RECORD_SCHEMA_VERSION,
        "created_at_utc": "2026-01-01T00:00:00+00:00",
        "incumbent_architecture": "parallel",
        "challenger_architecture": "cascade",
        "promotion_decision": "keep_incumbent",
        "would_promote_challenger": False,
        "auto_promote_executed": False,
        "policy": {},
        "reason_codes": [],
        "blocked_promotion_flags": [{"code": "PRIMARY_METRIC_INSUFFICIENT", "detail": "x"}],
        "rollback_demotion_ready": True,
        "evaluation_manifest_reference": {},
    }


def test_scheduler_auto_promote_defaults_on_panic_off(monkeypatch):
    """Train-success-live: auto-promote defaults ON; panic opt-out turns it OFF."""
    monkeypatch.delenv("ED_ML_SCHEDULER_AUTO_PROMOTE_TO_ACTIVE", raising=False)  # retired name, ignored
    monkeypatch.delenv("ED_SCHEDULER_AUTO_PROMOTE", raising=False)
    monkeypatch.delenv("ED_DISABLE_AUTO_PROMOTE", raising=False)
    assert scheduler_auto_promote_to_active_enabled() is True
    monkeypatch.setenv("ED_DISABLE_AUTO_PROMOTE", "1")
    assert scheduler_auto_promote_to_active_enabled() is False
    monkeypatch.delenv("ED_DISABLE_AUTO_PROMOTE", raising=False)
    monkeypatch.setenv("ED_SCHEDULER_AUTO_PROMOTE", "0")
    assert scheduler_auto_promote_to_active_enabled() is False


def test_run_governed_writes_manifest_and_record(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("ED_ML_SCHEDULER_AUTO_PROMOTE_TO_ACTIVE", raising=False)
    man = _minimal_manifest()
    rec = _minimal_record()

    with (
        patch("arch_competition.scheduler_integration.run_architecture_pair_evaluation", return_value=man),
        patch("arch_competition.scheduler_integration.decide_promotion", return_value=rec),
    ):
        out = run_governed_architecture_competition_pass(
            model_dir=tmp_path,
            db_path=":memory:",
            ticker="SPY",
            parallel_model_dir=tmp_path / "p",
            cascade_model_dir=tmp_path / "c",
            ml_horizon_slug="1c",
        )
    assert out["promotion_record"]["blocked_promotion_flags"]
    ev = evaluation_manifest_path(tmp_path, "1c", "SPY")
    pr = promotion_decision_path(tmp_path, "1c", "SPY")
    assert ev.is_file() and pr.is_file()
    assert json.loads(ev.read_text(encoding="utf-8"))["schema_version"] == EVALUATION_MANIFEST_SCHEMA_VERSION
    assert json.loads(pr.read_text(encoding="utf-8"))["schema_version"] == PROMOTION_RECORD_SCHEMA_VERSION
    assert arch_competition_summary_path(tmp_path, "1c").is_file()


def test_validate_persisted_missing_file_fails(tmp_path: Path):
    with pytest.raises(PromotionGovernanceMissingError, match="missing evaluation manifest"):
        validate_persisted_governed_artifacts_or_raise(tmp_path, "1c", "SPY")


def test_validate_persisted_raises_missing_subtype_when_promotion_absent(tmp_path: Path):
    ev = evaluation_manifest_path(tmp_path, "1c", "SPY")
    ev.parent.mkdir(parents=True)
    ev.write_text(json.dumps({"schema_version": EVALUATION_MANIFEST_SCHEMA_VERSION}), encoding="utf-8")
    with pytest.raises(PromotionGovernanceMissingError, match="missing promotion decision"):
        validate_persisted_governed_artifacts_or_raise(tmp_path, "1c", "SPY")


def test_validate_persisted_raises_invalid_subtype_on_corrupt_json(tmp_path: Path):
    ev = evaluation_manifest_path(tmp_path, "1c", "SPY")
    pr = promotion_decision_path(tmp_path, "1c", "SPY")
    ev.parent.mkdir(parents=True)
    ev.write_text("{bad", encoding="utf-8")
    pr.write_text(json.dumps({"schema_version": PROMOTION_RECORD_SCHEMA_VERSION}), encoding="utf-8")
    with pytest.raises(PromotionGovernanceInvalidError, match="invalid JSON"):
        validate_persisted_governed_artifacts_or_raise(tmp_path, "1c", "SPY")


def test_validate_persisted_raises_invalid_subtype_on_schema_mismatch(tmp_path: Path):
    ev = evaluation_manifest_path(tmp_path, "1c", "SPY")
    pr = promotion_decision_path(tmp_path, "1c", "SPY")
    ev.parent.mkdir(parents=True)
    ev.write_text(json.dumps({"schema_version": "wrong"}), encoding="utf-8")
    pr.write_text(json.dumps({"schema_version": PROMOTION_RECORD_SCHEMA_VERSION}), encoding="utf-8")
    with pytest.raises(PromotionGovernanceInvalidError, match="schema mismatch"):
        validate_persisted_governed_artifacts_or_raise(tmp_path, "1c", "SPY")


def test_validate_persisted_subtypes_inherit_parent():
    assert issubclass(PromotionGovernanceMissingError, PromotionGovernanceError)
    assert issubclass(PromotionGovernanceInvalidError, PromotionGovernanceError)


def test_governed_arch_state_schema_stable():
    sl = build_governed_arch_state_slice(
        manifest=_minimal_manifest(),
        promotion_record=_minimal_record(),
        paths={"evaluation_manifest": "/a", "promotion_decision": "/b"},
        auto_promote_to_active=False,
    )
    assert GOVERNED_ARCH_STATE_REQUIRED_KEYS <= sl.keys()
    assert sl["schema_version"] == GOVERNED_ARCH_STATE_SCHEMA_VERSION
    assert sl["production_write_held"] is True
    assert sl["latest_promotion_decision"] == "keep_incumbent"
    assert sl["blocked_promotion_flags"][0]["code"] == "PRIMARY_METRIC_INSUFFICIENT"


def test_merge_summary_file_raises_on_corrupt_existing(tmp_path: Path):
    path = tmp_path / "arch_competition" / "1c" / "arch_competition_summary.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not valid json", encoding="utf-8")
    tick = build_arch_competition_summary_tick(
        ticker="QQQ",
        ml_horizon_slug="1c",
        manifest=_minimal_manifest(),
        promotion_record=_minimal_record(),
        paths={"evaluation_manifest": "/e", "promotion_decision": "/p"},
    )
    with pytest.raises(PromotionGovernanceError, match="invalid JSON"):
        _merge_summary_file(path, "QQQ", tick)


def test_merge_summary_file_raises_on_corrupt_tickers_field(tmp_path: Path):
    path = tmp_path / "arch_competition" / "1c" / "arch_competition_summary.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema_version": "1", "tickers": ["SPY"]}),
        encoding="utf-8",
    )
    tick = build_arch_competition_summary_tick(
        ticker="QQQ",
        ml_horizon_slug="1c",
        manifest=_minimal_manifest(),
        promotion_record=_minimal_record(),
        paths={"evaluation_manifest": "/e", "promotion_decision": "/p"},
    )
    with pytest.raises(PromotionGovernanceError, match="non-dict 'tickers'"):
        _merge_summary_file(path, "QQQ", tick)


def test_merge_summary_file_preserves_other_tickers(tmp_path: Path):
    path = tmp_path / "arch_competition" / "1c" / "arch_competition_summary.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "1",
                "tickers": {"SPY": {"ticker": "SPY", "latest_promotion_decision": "keep_incumbent"}},
            }
        ),
        encoding="utf-8",
    )
    tick = build_arch_competition_summary_tick(
        ticker="QQQ",
        ml_horizon_slug="1c",
        manifest=_minimal_manifest(),
        promotion_record=_minimal_record(),
        paths={"evaluation_manifest": "/e", "promotion_decision": "/p"},
    )
    _merge_summary_file(path, "QQQ", tick)
    merged = json.loads(path.read_text(encoding="utf-8"))
    assert merged["tickers"]["SPY"]["ticker"] == "SPY"
    assert merged["tickers"]["QQQ"]["ticker"] == "QQQ"


def test_load_visibility_prefers_tick_summary_empty_blocked_list(tmp_path: Path):
    hz_path = tmp_path / "arch_state.json"
    hz_path.write_text(
        json.dumps(
            {
                "SPY": {
                    "active_architecture": "parallel",
                    "governed_competition": {
                        "latest_promotion_decision": "keep_incumbent",
                        "blocked_promotion_flags": [{"code": "STALE_GV"}],
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "arch_competition" / "1c").mkdir(parents=True)
    (tmp_path / "arch_competition" / "1c" / "arch_competition_summary.json").write_text(
        json.dumps(
            {
                "tickers": {
                    "SPY": {
                        "blocked_promotion_flags": [],
                        "manifest_paths": {"evaluation_manifest": "/e"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    v = load_architecture_competition_visibility(tmp_path, "1c", ticker="SPY")
    assert v["blocked_reasons"] == []


def test_validate_persisted_returns_parsed_artifacts(tmp_path: Path):
    from arch_competition.eval_runner import EVALUATION_MANIFEST_SCHEMA_VERSION
    from arch_competition.promotion_engine import PROMOTION_RECORD_SCHEMA_VERSION

    ev = evaluation_manifest_path(tmp_path, "1c", "SPY")
    pr = promotion_decision_path(tmp_path, "1c", "SPY")
    ev.parent.mkdir(parents=True)
    ev.write_text(json.dumps({"schema_version": EVALUATION_MANIFEST_SCHEMA_VERSION, "ticker": "SPY"}), encoding="utf-8")
    pr.write_text(json.dumps({"schema_version": PROMOTION_RECORD_SCHEMA_VERSION, "ticker": "SPY"}), encoding="utf-8")
    manifest, record = validate_persisted_governed_artifacts_or_raise(tmp_path, "1c", "SPY")
    assert manifest["schema_version"] == EVALUATION_MANIFEST_SCHEMA_VERSION
    assert record["schema_version"] == PROMOTION_RECORD_SCHEMA_VERSION


def test_validate_persisted_schema_mismatch_includes_versions(tmp_path: Path):
    ev = evaluation_manifest_path(tmp_path, "1c", "SPY")
    pr = promotion_decision_path(tmp_path, "1c", "SPY")
    ev.parent.mkdir(parents=True)
    ev.write_text(json.dumps({"schema_version": "wrong"}), encoding="utf-8")
    pr.write_text(json.dumps({"schema_version": PROMOTION_RECORD_SCHEMA_VERSION}), encoding="utf-8")
    with pytest.raises(PromotionGovernanceInvalidError, match="expected='1' got='wrong'"):
        validate_persisted_governed_artifacts_or_raise(tmp_path, "1c", "SPY")


def test_build_summary_tick_surfaces_both_architecture_row_counts():
    tick = build_arch_competition_summary_tick(
        ticker="SPY",
        ml_horizon_slug="1c",
        manifest=_minimal_manifest(),
        promotion_record=_minimal_record(),
        paths={},
    )
    assert tick["n_rows_scored_parallel"] == 100
    assert tick["n_rows_scored_cascade"] == 100


def test_load_visibility_single_ticker(tmp_path: Path):
    hz_path = tmp_path / "arch_state.json"
    hz_path.write_text(
        json.dumps(
            {
                "SPY": {
                    "active_architecture": "parallel",
                    "governed_competition": {"latest_promotion_decision": "keep_incumbent"},
                }
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "arch_competition" / "1c").mkdir(parents=True)
    (tmp_path / "arch_competition" / "1c" / "arch_competition_summary.json").write_text(
        json.dumps(
            {
                "tickers": {
                    "SPY": {
                        "blocked_promotion_flags": [{"code": "X"}],
                        "manifest_paths": {"evaluation_manifest": "/e"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    v = load_architecture_competition_visibility(tmp_path, "1c", ticker="SPY")
    assert v["production_default_runtime"] == "parallel"
    assert v["blocked_reasons"][0]["code"] == "X"


def test_ml_scheduler_auto_promote_helper_true_by_default(monkeypatch):
    """Train-success-live: helper mirrors policy default ON."""
    monkeypatch.delenv("ED_SCHEDULER_AUTO_PROMOTE", raising=False)
    monkeypatch.delenv("ED_DISABLE_AUTO_PROMOTE", raising=False)
    from ml_scheduler import _scheduler_auto_promote_to_active

    assert _scheduler_auto_promote_to_active() is True


def test_assert_no_active_directory_write_ok_when_env_off(monkeypatch):
    """With auto-promote panic-disabled, the no-active-write hook must not raise."""
    monkeypatch.setenv("ED_DISABLE_AUTO_PROMOTE", "1")
    assert_no_active_directory_write()


def test_run_base_models_once_unchanged_parallel(monkeypatch):
    """Production default remains parallel; integration does not alter run_base_models_once."""
    monkeypatch.delenv("ED_ML_SCHEDULER_AUTO_PROMOTE_TO_ACTIVE", raising=False)
    import inspect
    from ml_predict import run_base_models_once

    src = inspect.getsource(run_base_models_once)
    assert "parallel_runtime=True" in src
    assert "def run_base_models_once" in src


def test_ml_scheduler_invokes_governed_architecture_pass():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    src = (root / "ml_scheduler.py").read_text(encoding="utf-8")
    assert "run_governed_architecture_competition_pass" in src
    assert "governed_competition" in src
    assert "execute_promotion_if_eligible" in src


def test_resolve_ticker_outcome_eval_failed_on_governed_failed_closed():
    from ml_scheduler import _resolve_ticker_outcome
    from training_outcome import TrainingOutcome, compute_run_exit_code, outcome_entry

    outcome, streak = _resolve_ticker_outcome(
        ticker="SPY",
        horizon="1c",
        skip_governed_eval=False,
        governed_slice={"failed_closed": True, "error": "boom"},
        parallel_skip=False,
        cascade_skip=False,
        promoted=False,
        consecutive_cache_skips=0,
    )
    assert outcome == TrainingOutcome.eval_failed.value
    assert streak == 0
    assert compute_run_exit_code(
        [outcome_entry(ticker="SPY", horizon="1c", outcome=TrainingOutcome(outcome))]
    ) == 1


def test_resolve_ticker_outcome_non_core_partial_bundle_promote_skipped():
    from ml_scheduler import _resolve_ticker_outcome
    from training_outcome import TrainingOutcome, compute_run_exit_code, outcome_entry

    outcome, streak = _resolve_ticker_outcome(
        ticker="CRWD",
        horizon="1c",
        skip_governed_eval=True,
        governed_slice={"failed_closed": True, "error": "partial_candidate_bundle"},
        parallel_skip=False,
        cascade_skip=False,
        promoted=False,
        consecutive_cache_skips=0,
    )
    assert outcome == TrainingOutcome.promote_skipped.value
    assert compute_run_exit_code(
        [outcome_entry(ticker="CRWD", horizon="1c", outcome=TrainingOutcome(outcome))]
    ) == 0


def test_resolve_ticker_outcome_cache_skipped_under_cap_exit_zero(monkeypatch, tmp_path: Path):
    import training_pipeline_status as tps
    from ml_scheduler import _resolve_ticker_outcome
    from training_outcome import TrainingOutcome, compute_run_exit_code, outcome_entry
    from training_pipeline_status import reset_cache_skip_streak

    status_path = tmp_path / "training_pipeline_status.json"
    monkeypatch.setattr(tps, "DEFAULT_STATUS_PATH", status_path)
    reset_cache_skip_streak("SPY", "15c", path=status_path)

    outcome, _ = _resolve_ticker_outcome(
        ticker="SPY",
        horizon="15c",
        skip_governed_eval=False,
        governed_slice={"failed_closed": False},
        parallel_skip=True,
        cascade_skip=True,
        promoted=False,
        consecutive_cache_skips=0,
    )
    assert outcome == TrainingOutcome.cache_skipped.value
    assert compute_run_exit_code(
        [outcome_entry(ticker="SPY", horizon="15c", outcome=TrainingOutcome(outcome))]
    ) == 0
