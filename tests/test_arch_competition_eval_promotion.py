"""Evaluation runner + promotion engine (offline; no production default change)."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from arch_competition.eval_runner import (
    EVALUATION_MANIFEST_REQUIRED_KEYS,
    EVALUATION_MANIFEST_SCHEMA_VERSION,
    run_architecture_pair_evaluation,
)
from arch_competition.exceptions import EvaluationLineageError, PromotionGovernanceError
from arch_competition.lineage import validate_parallel_cascade_manifest_lineage
from arch_competition.promotion_engine import (
    PROMOTION_RECORD_REQUIRED_KEYS,
    PROMOTION_RECORD_SCHEMA_VERSION,
    PromotionPolicy,
    decide_promotion,
)


def _dfp():
    return {
        "min_ts_utc": "2020-01-01",
        "max_ts_utc": "2020-06-01",
        "row_count": 1000,
        "table": "snap",
        "timeframe": "1m",
        "ticker": "SPY",
    }


def _base_lineage():
    return {
        "feature_cache_key": "shared_cache_key",
        "data_fingerprint": _dfp(),
        "ml_horizon_suffix": "1c",
        "canonical_feature_contract_version": "v-test",
        "canonical_timeframe": "1m",
    }


def _metrics(
    name: str,
    *,
    n: int,
    ll: float | None,
    bal: float,
    brier: float | None,
    stab: float | None,
    mid_bucket_bal: float = 0.5,
    calibration_ece: float | None = 0.08,
):
    return {
        "architecture": name,
        "n_rows_scored": n,
        "accuracy": 0.5,
        "balanced_accuracy": bal,
        "log_loss": ll,
        "brier_score": brier,
        "stability_log_loss_std_halves": stab,
        "calibration_ece": calibration_ece,
        "calibration_mce": 0.05,
        "brier_decomposition": {"brier_score": brier},
        "regime_slices": {
            "low": {"n": 0, "balanced_accuracy": None, "skipped_low_support": True},
            "mid": {
                "n": 50,
                "balanced_accuracy": mid_bucket_bal,
                "skipped_low_support": False,
            },
            "high": {"n": 0, "balanced_accuracy": None, "skipped_low_support": True},
        },
        "confidence_reliability": {},
        "realized_contract_metrics": {},
    }


def _empirical_shell():
    return {
        "calibration_summary": {"schema_version": "1", "by_architecture": {}},
        "confidence_reliability_summary": {
            "schema_version": "1",
            "by_architecture": {
                "parallel": {"confidence_hit_correlation": 0.1},
                "cascade": {"confidence_hit_correlation": 0.1},
            },
        },
        "rolling_stability_summary": {
            "schema_version": "1",
            "by_architecture": {
                "parallel": {"calibration_degradation_flag": False},
                "cascade": {"calibration_degradation_flag": False},
            },
        },
        "empirical_validation": {"schema_version": "1"},
    }


def _manifest(mp, mc, lineage=None):
    lg = lineage or _base_lineage()
    return {
        "schema_version": "1",
        "ticker": "SPY",
        "ml_horizon_slug": "1c",
        "lineage": lg,
        "metrics": {"parallel": mp, "cascade": mc},
        **_empirical_shell(),
    }


def test_promotion_record_schema_stable_keys():
    m = _manifest(
        _metrics("parallel", n=100, ll=0.8, bal=0.5, brier=0.2, stab=0.01),
        _metrics("cascade", n=100, ll=0.7, bal=0.55, brier=0.21, stab=0.02),
    )
    rec = decide_promotion(m)
    assert rec["schema_version"] == PROMOTION_RECORD_SCHEMA_VERSION
    assert PROMOTION_RECORD_REQUIRED_KEYS <= rec.keys()
    assert rec["auto_promote_executed"] is False
    assert rec["would_promote_challenger"] in (True, False)


def test_tie_or_insufficient_log_loss_keeps_incumbent():
    """Tie / below min_delta on primary metric → keep parallel (incumbent)."""
    m = _manifest(
        _metrics("parallel", n=100, ll=0.81, bal=0.5, brier=0.2, stab=0.01),
        _metrics("cascade", n=100, ll=0.80, bal=0.99, brier=0.19, stab=0.01),
    )
    rec = decide_promotion(m, PromotionPolicy(min_delta_log_loss=0.02))
    assert rec["promotion_decision"] == "keep_incumbent"
    assert rec["would_promote_challenger"] is False
    codes = [x["code"] for x in rec["blocked_promotion_flags"]]
    assert "PRIMARY_METRIC_INSUFFICIENT" in codes


def test_better_accuracy_alone_no_promote_if_primary_fails():
    """Higher balanced_accuracy does not promote when log_loss improvement is insufficient."""
    m = _manifest(
        _metrics("parallel", n=100, ll=0.50, bal=0.33, brier=0.2, stab=0.01),
        _metrics("cascade", n=100, ll=0.49, bal=0.95, brier=0.19, stab=0.01),
    )
    rec = decide_promotion(m, PromotionPolicy(min_delta_log_loss=0.02))
    assert rec["would_promote_challenger"] is False


def test_better_primary_not_enough_if_calibration_fails():
    """Large log_loss win does not promote when calibration (Brier) regresses past gate."""
    m = _manifest(
        _metrics("parallel", n=200, ll=0.9, bal=0.4, brier=0.20, stab=0.02, calibration_ece=0.08),
        _metrics("cascade", n=200, ll=0.5, bal=0.95, brier=0.50, stab=0.02, calibration_ece=0.09),
    )
    rec = decide_promotion(m, PromotionPolicy(min_delta_log_loss=0.02, max_brier_regression_vs_incumbent=0.02))
    assert rec["would_promote_challenger"] is False
    assert any(x["code"] == "CALIBRATION_REGRESSION" for x in rec["blocked_promotion_flags"])


def test_primary_improves_but_ece_regression_blocks_promotion():
    """Large log_loss improvement does not promote when cascade ECE materially worsens vs parallel."""
    m = _manifest(
        _metrics("parallel", n=200, ll=0.95, bal=0.4, brier=0.2, stab=0.02, calibration_ece=0.05),
        _metrics("cascade", n=200, ll=0.40, bal=0.95, brier=0.19, stab=0.02, calibration_ece=0.22),
    )
    rec = decide_promotion(m, PromotionPolicy(min_delta_log_loss=0.02, max_ece_regression_vs_incumbent=0.12))
    assert rec["would_promote_challenger"] is False
    assert any(x["code"] == "CALIBRATION_ECE_REGRESSION" for x in rec["blocked_promotion_flags"])


def test_confidence_reliability_regression_blocks():
    m = _manifest(
        _metrics("parallel", n=100, ll=0.7, bal=0.5, brier=0.2, stab=0.02, calibration_ece=0.08),
        _metrics("cascade", n=100, ll=0.5, bal=0.6, brier=0.19, stab=0.02, calibration_ece=0.08),
    )
    m["confidence_reliability_summary"]["by_architecture"]["parallel"]["confidence_hit_correlation"] = 0.5
    m["confidence_reliability_summary"]["by_architecture"]["cascade"]["confidence_hit_correlation"] = 0.2
    rec = decide_promotion(m, PromotionPolicy(min_delta_log_loss=0.02))
    assert rec["would_promote_challenger"] is False
    assert any(x["code"] == "CONFIDENCE_RELIABILITY_REGRESSION" for x in rec["blocked_promotion_flags"])


def test_missing_calibration_metric_blocks():
    m = _manifest(
        _metrics("parallel", n=100, ll=0.8, bal=0.5, brier=0.2, stab=0.01),
        _metrics("cascade", n=100, ll=0.5, bal=0.6, brier=None, stab=0.01),
    )
    rec = decide_promotion(m)
    assert rec["would_promote_challenger"] is False
    assert any(x["code"] == "MISSING_CALIBRATION_METRIC" for x in rec["blocked_promotion_flags"])


def test_horizon_mismatch_fails_closed():
    lg = _base_lineage()
    lg["ml_horizon_suffix"] = "5c"
    m = _manifest(
        _metrics("parallel", n=100, ll=0.8, bal=0.5, brier=0.2, stab=0.01),
        _metrics("cascade", n=100, ll=0.7, bal=0.6, brier=0.21, stab=0.02),
        lineage=lg,
    )
    m["ml_horizon_slug"] = "1c"
    with pytest.raises(PromotionGovernanceError, match="horizon mismatch"):
        decide_promotion(m)


def test_auto_promote_forbidden():
    m = _manifest(
        _metrics("parallel", n=100, ll=0.9, bal=0.5, brier=0.2, stab=0.01),
        _metrics("cascade", n=100, ll=0.5, bal=0.6, brier=0.21, stab=0.02),
    )
    with pytest.raises(PromotionGovernanceError, match="auto_promote"):
        decide_promotion(m, auto_promote=True)


def test_lineage_mismatch_raises(tmp_path: Path):
    fp = _dfp()
    common = {
        "schema_version": "2",
        "ticker": "SPY",
        "ml_horizon_suffix": "1c",
        "data_fingerprint": fp,
        "training_code_fingerprint": "trainfp",
    }
    pdir = tmp_path / "p"
    cdir = tmp_path / "c"
    pdir.mkdir()
    cdir.mkdir()
    (pdir / "scheduler_run_manifest.json").write_text(
        json.dumps({**common, "feature_cache_key": "A"}),
        encoding="utf-8",
    )
    (cdir / "scheduler_run_manifest.json").write_text(
        json.dumps({**common, "feature_cache_key": "B"}),
        encoding="utf-8",
    )
    with pytest.raises(EvaluationLineageError, match="feature_cache_key"):
        validate_parallel_cascade_manifest_lineage(pdir, cdir, ticker="SPY", expected_ml_horizon_suffix="1c")


def test_parallel_and_cascade_evaluators_invoked_with_same_signature():
    """Both architectures evaluated with identical DB/ticker/window/label column."""
    detail = {"prob_rows": [[0.34, 0.33, 0.33]], "y_true": [1], "rows_used": [{"vix_level": 18.0}]}
    mock_p = MagicMock(
        return_value=(0.5, 0.5, 1, 0.5, {}, detail),
    )
    mock_c = MagicMock(
        return_value=(0.5, 0.5, 1, 0.5, {}, detail),
    )
    lineage = {**_base_lineage(), "training_code_fingerprint": "x"}
    with (
        patch("arch_competition.eval_runner.validate_parallel_cascade_manifest_lineage", return_value=lineage),
        patch("ml_scheduler._evaluate_parallel_on_full_rth", mock_p),
        patch("ml_scheduler._evaluate_cascade_on_full_rth", mock_c),
    ):
        man = run_architecture_pair_evaluation(
            db_path=":memory:",
            ticker="SPY",
            parallel_model_dir=Path("/p"),
            cascade_model_dir=Path("/c"),
            ml_horizon_slug="1c",
            allowed_et_dates={"2024-01-02"},
        )
    assert man["schema_version"] == EVALUATION_MANIFEST_SCHEMA_VERSION
    assert EVALUATION_MANIFEST_REQUIRED_KEYS <= man.keys()
    assert man["lineage"]["feature_cache_key"] == "shared_cache_key"
    assert man["metrics"]["parallel"]["n_rows_scored"] == man["metrics"]["cascade"]["n_rows_scored"]
    kw_p = mock_p.call_args.kwargs
    kw_c = mock_c.call_args.kwargs
    assert kw_p["allowed_et_dates"] == kw_c["allowed_et_dates"]
    assert kw_p["target_column"] == kw_c["target_column"] == "outcome_1c"


def test_row_count_mismatch_fails():
    detail = {"prob_rows": [], "y_true": [], "rows_used": []}
    with (
        patch("arch_competition.eval_runner.validate_parallel_cascade_manifest_lineage", return_value=_base_lineage()),
        patch("ml_scheduler._evaluate_parallel_on_full_rth", return_value=(0.5, 0.5, 5, 0.5, {}, detail)),
        patch("ml_scheduler._evaluate_cascade_on_full_rth", return_value=(0.5, 0.5, 3, 0.5, {}, detail)),
    ):
        with pytest.raises(EvaluationLineageError, match="row-count mismatch"):
            run_architecture_pair_evaluation(
                db_path=":memory:",
                ticker="SPY",
                parallel_model_dir=Path("/p"),
                cascade_model_dir=Path("/c"),
                ml_horizon_slug="1c",
            )


def test_missing_probability_vectors_fail_closed_when_n_sufficient():
    detail = {"prob_rows": [], "y_true": [], "rows_used": []}
    with (
        patch("arch_competition.eval_runner.validate_parallel_cascade_manifest_lineage", return_value=_base_lineage()),
        patch("ml_scheduler._evaluate_parallel_on_full_rth", return_value=(0.5, 0.5, 20, 0.5, {}, detail)),
        patch("ml_scheduler._evaluate_cascade_on_full_rth", return_value=(0.5, 0.5, 20, 0.5, {}, detail)),
    ):
        with pytest.raises(EvaluationLineageError, match="missing prob_rows"):
            run_architecture_pair_evaluation(
                db_path=":memory:",
                ticker="SPY",
                parallel_model_dir=Path("/p"),
                cascade_model_dir=Path("/c"),
                ml_horizon_slug="1c",
            )


def test_arch_competition_modules_do_not_call_run_base_models_once():
    root = Path(__file__).resolve().parents[1] / "arch_competition"
    for name in ("eval_runner.py", "promotion_engine.py", "__init__.py", "lineage.py", "metrics.py", "exceptions.py"):
        src = (root / name).read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id == "run_base_models_once":
                    pytest.fail(f"{name} must not call run_base_models_once")
                if isinstance(node.func, ast.Attribute) and node.func.attr == "run_base_models_once":
                    pytest.fail(f"{name} must not call run_base_models_once")


def test_run_base_models_once_default_unchanged_parallel_runtime():
    """Guard: production entry remains parallel stack (this pass does not alter defaults)."""
    from ml_predict import run_base_models_once
    import inspect

    src = inspect.getsource(run_base_models_once)
    assert "parallel_runtime=True" in src
    assert "def run_base_models_once" in src
