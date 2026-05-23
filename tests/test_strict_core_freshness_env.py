"""P3-11 strict core freshness toggle for promote_skipped + would_promote."""
from __future__ import annotations

import os

import pytest

from training_outcome import TrainingOutcome, compute_run_exit_code, outcome_entry


def test_strict_off_promote_skipped_would_promote_no_exit_1(monkeypatch):
    monkeypatch.delenv("ED_SCHEDULER_AUTO_PROMOTE_STRICT_CORE_FRESHNESS", raising=False)
    outcomes = [
        outcome_entry(
            ticker="SPY",
            horizon="1c",
            outcome=TrainingOutcome.promote_skipped,
            extra={"would_promote": True},
        )
    ]
    assert compute_run_exit_code(outcomes) == 0


def test_strict_on_promote_skipped_would_promote_exit_1(monkeypatch):
    monkeypatch.setenv("ED_SCHEDULER_AUTO_PROMOTE_STRICT_CORE_FRESHNESS", "1")
    outcomes = [
        outcome_entry(
            ticker="SPY",
            horizon="1c",
            outcome=TrainingOutcome.promote_skipped,
            extra={"would_promote": True},
        )
    ]
    assert compute_run_exit_code(outcomes) == 1
