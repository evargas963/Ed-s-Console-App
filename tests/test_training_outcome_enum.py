"""PR2 P1-1: TrainingOutcome enum matches Appendix D.1 exactly."""
from __future__ import annotations

from training_outcome import TrainingOutcome


def test_training_outcome_enum_membership_appendix_d1():
    # PR2 Appendix D.1 baseline + Pass 2 of DATA-PIPELINE-INTEGRITY-CHAIN
    # (2026-05-26) added preflight_failed. Net 9 members.
    expected = {
        "trained",
        "promote_ok",
        "promote_skipped",
        "cache_skipped",
        "cache_skip_streak_exceeded",
        "train_failed",
        "eval_failed",
        "verify_failed",
        "preflight_failed",
    }
    actual = {member.value for member in TrainingOutcome}
    assert actual == expected
    assert len(TrainingOutcome) == 9


def test_training_outcome_named_identically():
    for name in (
        "trained",
        "promote_ok",
        "promote_skipped",
        "cache_skipped",
        "cache_skip_streak_exceeded",
        "train_failed",
        "eval_failed",
        "verify_failed",
        "preflight_failed",
    ):
        assert TrainingOutcome[name].value == name


def test_preflight_failed_is_not_core_success() -> None:
    """Pass 2 of DATA-PIPELINE-INTEGRITY-CHAIN — preflight_failed must
    cause compute_run_exit_code to return 1 when a core ticker carries it,
    so a fully-preflight-blocked run is reported as a failed run."""
    from training_outcome import (
        CORE_SUCCESS_OUTCOMES,
        compute_run_exit_code,
        outcome_entry,
    )

    assert TrainingOutcome.preflight_failed not in CORE_SUCCESS_OUTCOMES

    # Mock a core-ticker preflight failure -> exit code 1.
    entries = [
        outcome_entry(
            ticker="SPY",
            horizon="1c",
            outcome=TrainingOutcome.preflight_failed,
            extra={"error": "row 0: MVP coercion failed: liquidity.range_imbalance_stall_score"},
        )
    ]
    assert compute_run_exit_code(entries) == 1
