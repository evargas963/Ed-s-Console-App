"""eval_runner sample-size floor and manifest flags (Finding Y)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from arch_competition.eval_runner import run_architecture_pair_evaluation
from arch_competition.exceptions import EvaluationLineageError
from calibration.statistical_integrity import MIN_SAMPLES_STATISTICAL


def _base_lineage():
    return {
        "feature_cache_key": "shared_cache_key",
        "data_fingerprint": {"ticker": "SPY"},
        "ml_horizon_suffix": "1c",
        "training_code_fingerprint": "trainfp",
    }


def _detail(*, n: int, prob_rows: list | None = None):
    rows = prob_rows if prob_rows is not None else [[0.34, 0.33, 0.33]] * n
    return {
        "prob_rows": rows,
        "y_true": [1] * n,
        "rows_used": [{"vix_level": 18.0}] * n,
    }


def _run_mocked_eval(n: int, detail: dict):
    mock_ret = (0.5, 0.5, n, 0.5, {}, detail)
    with (
        patch(
            "arch_competition.eval_runner.validate_parallel_cascade_manifest_lineage",
            return_value=_base_lineage(),
        ),
        patch("ml_scheduler._evaluate_parallel_on_full_rth", return_value=mock_ret),
        patch("ml_scheduler._evaluate_cascade_on_full_rth", return_value=mock_ret),
    ):
        return run_architecture_pair_evaluation(
            db_path=":memory:",
            ticker="SPY",
            parallel_model_dir=Path("/p"),
            cascade_model_dir=Path("/c"),
            ml_horizon_slug="1c",
        )


def test_eval_manifest_flags_below_min_samples_statistical():
    n = MIN_SAMPLES_STATISTICAL - 1
    man = _run_mocked_eval(n, _detail(n=n))
    assert man["evaluation_n_below_min_samples_statistical"] is True
    assert man["metrics"]["parallel"]["n_rows_scored"] == n


def test_eval_manifest_no_flag_at_min_samples_statistical():
    n = MIN_SAMPLES_STATISTICAL
    man = _run_mocked_eval(n, _detail(n=n))
    assert man["evaluation_n_below_min_samples_statistical"] is False


def test_eval_missing_prob_rows_raises_at_min_samples_statistical():
    n = MIN_SAMPLES_STATISTICAL
    with pytest.raises(EvaluationLineageError, match="missing prob_rows"):
        _run_mocked_eval(n, _detail(n=n, prob_rows=[]))
