"""ml_scheduler.py orchestration-support cluster (RC-REHAB-1, ml_scheduler.py decomposition
slice 1): config/env helpers, training-report field shaping + outcome resolution, and the
calendar/wait helpers `run_once`/`start_background_scheduler` use around the nightly run.

No monkeypatch hazard was found for any function here (verified via repo-wide grep before
the move). Module-level scheduler config (MODEL_DIR, ARCH_STATE_PATH, TRAINING_REPORT_PATH,
RUN_AT_HOUR, RUN_AT_MINUTE) stays defined in ml_scheduler.py and is reached here via a LAZY
`import ml_scheduler` inside each function body that needs it -- ml_scheduler.py imports this
module right after defining those constants, before its own module load finishes, so a
top-level `from ml_scheduler import MODEL_DIR` here would fail at ml_scheduler.py's own
import time.
"""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Optional

from ml_horizon import DEFAULT_ML_HORIZON_SLUG, normalize_ml_horizon_slug


def scheduler_arch_state_path(ml_horizon_slug: str):
    import ml_scheduler  # module-attribute access only -- see this file's own docstring

    su = normalize_ml_horizon_slug(ml_horizon_slug)
    if su == DEFAULT_ML_HORIZON_SLUG:
        return ml_scheduler.ARCH_STATE_PATH
    return ml_scheduler.MODEL_DIR / f"arch_state_{su}.json"


def scheduler_active_root(ml_horizon_slug: str):
    import ml_scheduler  # module-attribute access only -- see this file's own docstring
    from active_bundle_contract import scheduler_active_root as _contract_root

    return _contract_root(ml_scheduler.MODEL_DIR, ml_horizon_slug)


def _infer_slug_from_target_column(target_column: str) -> str:
    col = (target_column or "").strip().lower()
    if col.startswith("outcome_"):
        return normalize_ml_horizon_slug(col[len("outcome_") :])
    return DEFAULT_ML_HORIZON_SLUG


def _now_et() -> datetime:
    from time_et import now_et

    return now_et()


def _scheduler_auto_promote_to_active() -> bool:
    from arch_competition.scheduler_integration import scheduler_auto_promote_to_active_enabled

    return scheduler_auto_promote_to_active_enabled()


def _scheduler_skip_parallel_train() -> bool:
    """Operator: ED_ML_SCHEDULER_SKIP_PARALLEL_TRAIN=1 — train/eval cascade only; keep parallel artifacts."""
    return os.environ.get("ED_ML_SCHEDULER_SKIP_PARALLEL_TRAIN", "").strip().lower() in (  # caps-ok: optional operator env var, "" is the correct unset default, not a masked required value
        "1",
        "true",
        "yes",
    )


@contextmanager
def _strict_off_for_candidate_inference():
    """Temporarily disable strict-active-only resolution for candidate model inference."""
    key = "ED_XGB_STRICT_ACTIVE_ONLY"
    prior = os.environ.get(key)
    os.environ[key] = "0"
    try:
        yield
    finally:
        if prior is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = prior


def _append_training_report(report: dict):
    """Append a per-ticker training report line to training_report.jsonl."""
    import ml_scheduler  # module-attribute access only -- see this file's own docstring

    report["timestamp"] = _now_et().strftime("%Y-%m-%d %H:%M:%S ET")
    ml_scheduler.MODEL_DIR.mkdir(parents=True, exist_ok=True)
    with open(ml_scheduler.TRAINING_REPORT_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(report) + "\n")


def _governed_report_fields(governed_slice: Optional[dict[str, Any]]) -> dict[str, Any]:
    blocked: list[Any] = []
    promotion_decision = None
    governed_failed_closed = False
    if isinstance(governed_slice, dict):
        governed_failed_closed = bool(governed_slice.get("failed_closed"))
        promotion_decision = governed_slice.get("latest_promotion_decision")
        if governed_failed_closed:
            err = governed_slice.get("error")
            blocked = [{"code": "governed_failed_closed", "detail": str(err) if err is not None else ""}]
        else:
            flags = governed_slice.get("blocked_promotion_flags")
            if isinstance(flags, list):
                blocked = list(flags)
    return {
        "governed_failed_closed": governed_failed_closed,
        "promotion_decision": promotion_decision,
        "blocked_promotion_flags": blocked,
    }


def _apply_pr2_report_fields(
    report: dict[str, Any],
    *,
    outcome: str,
    horizon: str,
    artifact_complete: bool,
    consecutive_cache_skips: int,
    governed_slice: Optional[dict[str, Any]],
) -> None:
    report["outcome"] = outcome
    report["horizon"] = horizon
    report["artifact_complete"] = artifact_complete
    report["consecutive_cache_skips"] = consecutive_cache_skips
    report.update(_governed_report_fields(governed_slice))


def _resolve_ticker_outcome(
    *,
    ticker: str,
    horizon: str,
    skip_governed_eval: bool,
    governed_slice: Optional[dict[str, Any]],
    parallel_skip: bool,
    cascade_skip: bool,
    promoted: bool,
    consecutive_cache_skips: int,
    auto_exec_result: Optional[dict[str, Any]] = None,
) -> tuple[str, int]:
    from training_outcome import TrainingOutcome, is_training_anchor_ticker
    from training_pipeline_status import (
        bump_cache_skip_streak,
        get_cache_skip_cap,
        reset_cache_skip_streak,
    )

    if skip_governed_eval:
        from training_outcome import is_training_anchor_ticker

        if is_training_anchor_ticker(ticker):
            return TrainingOutcome.eval_failed.value, consecutive_cache_skips
        return TrainingOutcome.promote_skipped.value, consecutive_cache_skips

    if isinstance(governed_slice, dict) and governed_slice.get("failed_closed"):
        return TrainingOutcome.eval_failed.value, consecutive_cache_skips

    if isinstance(auto_exec_result, dict):
        if auto_exec_result.get("skipped_reason") == "verify_failed":
            return TrainingOutcome.verify_failed.value, consecutive_cache_skips
        if auto_exec_result.get("executed"):
            reset_cache_skip_streak(ticker, horizon)
            return TrainingOutcome.promote_ok.value, 0
        would_promote = bool(
            isinstance(governed_slice, dict)
            and governed_slice.get("would_promote_challenger")
            and not governed_slice.get("failed_closed")
        )
        if would_promote and not auto_exec_result.get("executed"):
            if parallel_skip and cascade_skip:
                streak = bump_cache_skip_streak(ticker, horizon)
                cap = get_cache_skip_cap()
                if streak > cap:
                    return TrainingOutcome.cache_skip_streak_exceeded.value, streak
                return TrainingOutcome.cache_skipped.value, streak
            reset_cache_skip_streak(ticker, horizon)
            return TrainingOutcome.promote_skipped.value, 0

    if parallel_skip and cascade_skip:
        streak = bump_cache_skip_streak(ticker, horizon)
        cap = get_cache_skip_cap()
        if streak > cap:
            return TrainingOutcome.cache_skip_streak_exceeded.value, streak
        return TrainingOutcome.cache_skipped.value, streak

    reset_cache_skip_streak(ticker, horizon)
    if promoted:
        return TrainingOutcome.promote_ok.value, 0
    return TrainingOutcome.trained.value, 0


def _is_market_day(dt: datetime) -> bool:
    if dt.weekday() >= 5:
        return False
    md = (dt.month, dt.day)
    holidays = [
        (1, 1), (1, 20), (2, 17), (4, 18), (5, 26),
        (6, 19), (7, 4), (9, 1), (11, 27), (12, 25),
    ]
    return md not in holidays


def _wait_until_1615():
    import ml_scheduler  # module-attribute access only -- see this file's own docstring

    now = _now_et()
    target = now.replace(hour=ml_scheduler.RUN_AT_HOUR, minute=ml_scheduler.RUN_AT_MINUTE, second=0, microsecond=0)
    if now >= target:
        return
    import time
    time.sleep(min((target - now).total_seconds(), 86400))
