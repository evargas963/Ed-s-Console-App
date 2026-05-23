"""Per-ticker training pipeline outcomes (PR2 / Phase 1 fail-closed)."""
from __future__ import annotations

from enum import Enum
from typing import Any


class TrainingOutcome(str, Enum):
    trained = "trained"
    promote_ok = "promote_ok"
    promote_skipped = "promote_skipped"
    cache_skipped = "cache_skipped"
    cache_skip_streak_exceeded = "cache_skip_streak_exceeded"
    train_failed = "train_failed"
    eval_failed = "eval_failed"
    verify_failed = "verify_failed"


CORE_SUCCESS_OUTCOMES: frozenset[TrainingOutcome] = frozenset(
    {
        TrainingOutcome.trained,
        TrainingOutcome.promote_ok,
        TrainingOutcome.cache_skipped,
    }
)


def core_tickers_upper() -> frozenset[str]:
    from server import CORE_TICKERS

    return frozenset(t.upper() for t in CORE_TICKERS)


def is_core_ticker(ticker: str) -> bool:
    return ticker.upper() in core_tickers_upper()


def outcome_fails_core_run(outcome: TrainingOutcome | str) -> bool:
    if isinstance(outcome, str):
        outcome = TrainingOutcome(outcome)
    return outcome not in CORE_SUCCESS_OUTCOMES


def compute_run_exit_code(ticker_outcomes: list[dict[str, Any]]) -> int:
    for entry in ticker_outcomes:
        ticker = str(entry.get("ticker") or "").upper()
        if ticker not in core_tickers_upper():
            continue
        raw = entry.get("outcome")
        if raw is None:
            return 1
        if outcome_fails_core_run(str(raw)):
            return 1
    return 0


def outcome_entry(
    *,
    ticker: str,
    horizon: str,
    outcome: TrainingOutcome,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "ticker": ticker.upper(),
        "horizon": horizon,
        "outcome": outcome.value,
    }
    if extra:
        row.update(extra)
    return row
