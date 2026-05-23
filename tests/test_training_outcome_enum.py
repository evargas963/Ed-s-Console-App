"""PR2 P1-1: TrainingOutcome enum matches Appendix D.1 exactly."""
from __future__ import annotations

from training_outcome import TrainingOutcome


def test_training_outcome_enum_membership_appendix_d1():
    expected = {
        "trained",
        "promote_ok",
        "promote_skipped",
        "cache_skipped",
        "cache_skip_streak_exceeded",
        "train_failed",
        "eval_failed",
        "verify_failed",
    }
    actual = {member.value for member in TrainingOutcome}
    assert actual == expected
    assert len(TrainingOutcome) == 8


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
    ):
        assert TrainingOutcome[name].value == name
