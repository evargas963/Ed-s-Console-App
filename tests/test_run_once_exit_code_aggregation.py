"""PR2 P1-2/P1-3: run_once exit-code aggregation and --all-horizons OR semantics."""
from __future__ import annotations

import pytest

from ml_horizon import ALL_GOVERNED_HORIZONS
from training_outcome import TrainingOutcome, compute_run_exit_code, outcome_entry


def test_compute_run_exit_code_core_eval_failed():
    outcomes = [
        outcome_entry(ticker="SPY", horizon="1c", outcome=TrainingOutcome.eval_failed),
    ]
    assert compute_run_exit_code(outcomes) == 1


def test_compute_run_exit_code_core_train_failed():
    outcomes = [
        outcome_entry(ticker="QQQ", horizon="1c", outcome=TrainingOutcome.train_failed),
    ]
    assert compute_run_exit_code(outcomes) == 1


def test_compute_run_exit_code_cache_skipped_under_cap_is_success():
    outcomes = [
        outcome_entry(ticker="SPY", horizon="1c", outcome=TrainingOutcome.cache_skipped),
    ]
    assert compute_run_exit_code(outcomes) == 0


def test_compute_run_exit_code_cache_skip_streak_exceeded_fails_core():
    outcomes = [
        outcome_entry(ticker="IWM", horizon="1c", outcome=TrainingOutcome.cache_skip_streak_exceeded),
    ]
    assert compute_run_exit_code(outcomes) == 1


def test_compute_run_exit_code_non_core_partial_bundle_does_not_fail():
    outcomes = [
        outcome_entry(ticker="CRWD", horizon="1c", outcome=TrainingOutcome.promote_skipped),
    ]
    assert compute_run_exit_code(outcomes) == 0


def test_compute_run_exit_code_mixed_matrix():
    outcomes = [
        outcome_entry(ticker="SPY", horizon="1c", outcome=TrainingOutcome.trained),
        outcome_entry(ticker="QQQ", horizon="5c", outcome=TrainingOutcome.cache_skipped),
        outcome_entry(ticker="CRWD", horizon="1c", outcome=TrainingOutcome.promote_skipped),
    ]
    assert compute_run_exit_code(outcomes) == 0

    outcomes.append(
        outcome_entry(ticker="SPY", horizon="15c", outcome=TrainingOutcome.eval_failed),
    )
    assert compute_run_exit_code(outcomes) == 1


@pytest.mark.parametrize(
    "per_horizon_exits,expected",
    [
        ([0, 0, 0, 0], 0),
        ([0, 1, 0, 0], 1),
        ([0, 0, 0, 1], 1),
        ([1, 1, 1, 1], 1),
    ],
)
def test_all_horizons_ors_exit_codes(per_horizon_exits, expected):
    assert len(per_horizon_exits) == len(ALL_GOVERNED_HORIZONS)
    agg = 0
    for code in per_horizon_exits:
        agg |= int(code)
    assert agg == expected
