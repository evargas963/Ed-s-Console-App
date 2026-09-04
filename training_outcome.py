"""Per-ticker training pipeline outcomes (PR2 / Phase 1 fail-closed)."""
from __future__ import annotations

from enum import Enum
from typing import Any

from app.domain.instrument_identity import ticker_storage_key


class TrainingOutcome(str, Enum):
    trained = "trained"
    promote_ok = "promote_ok"
    promote_skipped = "promote_skipped"
    cache_skipped = "cache_skipped"
    cache_skip_streak_exceeded = "cache_skip_streak_exceeded"
    train_failed = "train_failed"
    eval_failed = "eval_failed"
    verify_failed = "verify_failed"
    # DATA-PIPELINE-INTEGRITY-CHAIN Pass 2 (2026-05-26): MVP coercion
    # preflight rejected this ticker BEFORE training started. Distinct from
    # train_failed so operators can grep "preflight_failed" in
    # training_pipeline_status.json to find aborted-early tickers without
    # confusing them with mid-training failures. Not a CORE_SUCCESS_OUTCOMES
    # — compute_run_exit_code returns 1 if any core ticker is preflight_failed.
    preflight_failed = "preflight_failed"


CORE_SUCCESS_OUTCOMES: frozenset[TrainingOutcome] = frozenset(
    {
        TrainingOutcome.trained,
        TrainingOutcome.promote_ok,
        TrainingOutcome.cache_skipped,
    }
)


def training_anchor_tickers_upper() -> frozenset[str]:
    from scheduler_user_tickers import training_anchor_tickers_upper as _anchors

    return _anchors()


def is_training_anchor_ticker(ticker: str) -> bool:
    from scheduler_user_tickers import is_training_anchor_ticker as _is_anchor

    return _is_anchor(ticker)


def core_tickers_upper() -> frozenset[str]:
    from server import CORE_TICKERS

    return frozenset(ticker_storage_key(t) for t in CORE_TICKERS)  # RC-345/F25: canonical membership


def is_core_ticker(ticker: str) -> bool:
    return ticker_storage_key(ticker) in core_tickers_upper()  # RC-345/F25: canonical membership


def outcome_fails_core_run(
    outcome: TrainingOutcome | str,
    *,
    would_promote: bool = False,
) -> bool:
    if isinstance(outcome, str):
        outcome = TrainingOutcome(outcome)
    if (
        outcome == TrainingOutcome.promote_skipped
        and would_promote
    ):
        from arch_competition.scheduler_auto_promote_policy import (
            scheduler_auto_promote_strict_core_freshness,
        )

        if not scheduler_auto_promote_strict_core_freshness():
            return False
    return outcome not in CORE_SUCCESS_OUTCOMES


def compute_run_exit_code(ticker_outcomes: list[dict[str, Any]]) -> int:
    anchors = training_anchor_tickers_upper()
    for entry in ticker_outcomes:
        ticker = ticker_storage_key(entry.get("ticker"))  # RC-345/F25: canonical vs canonical anchor set
        if ticker not in anchors:
            continue
        raw = entry.get("outcome")
        if raw is None:
            return 1
        would_promote = bool(entry.get("would_promote"))
        if outcome_fails_core_run(str(raw), would_promote=would_promote):
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
        "ticker": ticker_storage_key(ticker),  # RC-345/F25: canonical outcome-record identity
        "horizon": horizon,
        "outcome": outcome.value,
    }
    if extra:
        row.update(extra)
    return row
