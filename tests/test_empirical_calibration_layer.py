"""Empirical calibration + rolling stability: stable schemas; no production runtime change."""
from __future__ import annotations

import numpy as np

from arch_competition.eval_runner import (
    EMPIRICAL_VALIDATION_SCHEMA_VERSION,
    EMPIRICAL_SECTION_SCHEMA_VERSION,
    EVALUATION_MANIFEST_REQUIRED_KEYS,
)
from arch_competition.metrics import (
    architecture_win_consistency_by_window,
    expected_calibration_error_multiclass,
    reliability_bins_table,
    rolling_calibration_and_loss_stability,
)


def _synthetic_probs(n: int, seed: int = 42) -> tuple[list[int], list[list[float]]]:
    rng = np.random.default_rng(seed)
    y_true: list[int] = []
    prob_rows: list[list[float]] = []
    for _ in range(n):
        y = int(rng.integers(0, 3))
        p = rng.random(3)
        p = p / p.sum()
        prob_rows.append(p.tolist())
        y_true.append(y)
    return y_true, prob_rows


def test_calibration_summary_schema_stable():
    y, p = _synthetic_probs(200)
    ece = expected_calibration_error_multiclass(y, p, n_bins=10)
    bins = reliability_bins_table(y, p, n_bins=10)
    assert ece is not None and 0.0 <= ece <= 1.0
    assert len(bins) == 10
    assert all(
        ("bin_index" in b and ("calibration_gap" in b or b.get("skipped_low_support"))) for b in bins
    )


def test_rolling_stability_schema_stable():
    y, pr = _synthetic_probs(120)
    roll = rolling_calibration_and_loss_stability(y, pr, n_windows=3)
    assert "ece_by_window" in roll
    assert "calibration_degradation_flag" in roll
    assert "log_loss_by_window" in roll


def test_architecture_win_consistency_schema():
    y, pp = _synthetic_probs(90, seed=1)
    _, cp = _synthetic_probs(90, seed=2)
    w = architecture_win_consistency_by_window(y, pp, cp, n_windows=3)
    assert "cascade_win_rate_by_log_loss" in w
    assert w.get("insufficient_rows") is False


def test_evaluation_manifest_required_keys_include_empirical():
    assert "calibration_summary" in EVALUATION_MANIFEST_REQUIRED_KEYS
    assert "empirical_validation" in EVALUATION_MANIFEST_REQUIRED_KEYS


def test_empirical_section_schema_constants():
    assert EMPIRICAL_VALIDATION_SCHEMA_VERSION == "1"
    assert EMPIRICAL_SECTION_SCHEMA_VERSION == "1"


def test_ml_predict_run_base_models_once_default_unchanged():
    from ml_predict import run_base_models_once
    import inspect

    src = inspect.getsource(run_base_models_once)
    assert "parallel_runtime=True" in src
