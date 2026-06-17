"""PR2 P1-6: consecutive cache-skip cap in training_pipeline_status.json."""
from __future__ import annotations

from pathlib import Path


from training_outcome import TrainingOutcome
from training_pipeline_status import (
    bump_cache_skip_streak,
    get_cache_skip_cap,
    get_cache_skip_streak,
    reset_cache_skip_streak,
    set_cache_skip_streak,
)


def test_cache_skip_streak_increments_on_bump(tmp_path: Path):
    status_path = tmp_path / "training_pipeline_status.json"
    assert get_cache_skip_streak("SPY", "1c", path=status_path) == 0
    assert bump_cache_skip_streak("SPY", "1c", path=status_path) == 1
    assert bump_cache_skip_streak("SPY", "1c", path=status_path) == 2
    assert get_cache_skip_streak("SPY", "1c", path=status_path) == 2


def test_cache_skip_streak_resets_on_trained_path(tmp_path: Path):
    status_path = tmp_path / "training_pipeline_status.json"
    set_cache_skip_streak("QQQ", "5c", 2, path=status_path)
    reset_cache_skip_streak("QQQ", "5c", path=status_path)
    assert get_cache_skip_streak("QQQ", "5c", path=status_path) == 0


def test_cache_skip_streak_exceeded_outcome_via_cap(monkeypatch, tmp_path: Path):
    import training_pipeline_status as tps
    from ml_scheduler import _resolve_ticker_outcome

    status_path = tmp_path / "training_pipeline_status.json"
    monkeypatch.setenv("ED_SCHEDULER_CACHE_SKIP_CAP", "2")
    monkeypatch.setattr(tps, "DEFAULT_STATUS_PATH", status_path)

    outcome, streak = _resolve_ticker_outcome(
        ticker="ZZZCACHE",
        horizon="1c",
        skip_governed_eval=False,
        governed_slice=None,
        parallel_skip=True,
        cascade_skip=True,
        promoted=False,
        consecutive_cache_skips=0,
    )
    assert outcome == TrainingOutcome.cache_skipped.value
    assert streak == 1

    outcome, streak = _resolve_ticker_outcome(
        ticker="ZZZCACHE",
        horizon="1c",
        skip_governed_eval=False,
        governed_slice=None,
        parallel_skip=True,
        cascade_skip=True,
        promoted=False,
        consecutive_cache_skips=streak,
    )
    assert outcome == TrainingOutcome.cache_skipped.value
    assert streak == 2

    outcome, streak = _resolve_ticker_outcome(
        ticker="ZZZCACHE",
        horizon="1c",
        skip_governed_eval=False,
        governed_slice=None,
        parallel_skip=True,
        cascade_skip=True,
        promoted=False,
        consecutive_cache_skips=streak,
    )
    assert outcome == TrainingOutcome.cache_skip_streak_exceeded.value
    assert streak == 3


def test_cache_skip_cap_env_override(monkeypatch):
    monkeypatch.setenv("ED_SCHEDULER_CACHE_SKIP_CAP", "5")
    assert get_cache_skip_cap() == 5
    monkeypatch.delenv("ED_SCHEDULER_CACHE_SKIP_CAP", raising=False)
    assert get_cache_skip_cap() == 3


def test_cache_skip_cap_invalid_env_falls_back(monkeypatch):
    monkeypatch.setenv("ED_SCHEDULER_CACHE_SKIP_CAP", "not-a-number")
    assert get_cache_skip_cap() == 3
