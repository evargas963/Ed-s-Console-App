"""Scheduler integration: governed eval/promotion persistence, no default active/ copy."""

from __future__ import annotations

from pathlib import Path








































def test_ml_scheduler_auto_promote_helper_true_by_default(monkeypatch):
    """Train-success-live: helper mirrors policy default ON."""
    monkeypatch.delenv("ED_SCHEDULER_AUTO_PROMOTE", raising=False)
    monkeypatch.delenv("ED_DISABLE_AUTO_PROMOTE", raising=False)
    from ml_scheduler import _scheduler_auto_promote_to_active

    assert _scheduler_auto_promote_to_active() is True






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
