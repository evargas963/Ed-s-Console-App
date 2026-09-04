"""Aggregate training pipeline run status (P0-3)."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATUS_SCHEMA_VERSION = "training_pipeline_status_v1"
DEFAULT_STATUS_PATH = Path(__file__).resolve().parent / "models" / "training_pipeline_status.json"
DEFAULT_CACHE_SKIP_CAP = 3


def _resolve_status_path(path: Path | None) -> Path:
    if path is None:
        return DEFAULT_STATUS_PATH
    return path


def cache_skip_streak_key(ticker: str, horizon: str) -> str:
    from ml_horizon import normalize_ml_horizon_slug
    from app.domain.instrument_identity import ticker_storage_key

    # RC-345/F25: the streak dict key is canonical identity — write/read/lookup all flow through
    # this one producer, so SPX and $SPX share a single streak slot ("$SPX:..."). No .upper() faucet.
    return f"{ticker_storage_key(ticker)}:{normalize_ml_horizon_slug(horizon)}"


def read_status_payload(path: Path | None = None) -> dict[str, Any]:
    status_path = _resolve_status_path(path)
    if not status_path.is_file():
        return {}
    try:
        data = json.loads(status_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return {}
    return {}


def get_cache_skip_cap() -> int:
    raw_env = os.environ.get("ED_SCHEDULER_CACHE_SKIP_CAP")
    if raw_env is None:
        return DEFAULT_CACHE_SKIP_CAP
    raw = raw_env.strip()
    if raw == "":
        return DEFAULT_CACHE_SKIP_CAP
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_CACHE_SKIP_CAP


def get_cache_skip_streak(
    ticker: str,
    horizon: str,
    *,
    path: Path | None = None,
) -> int:
    payload = read_status_payload(path)
    streaks = payload.get("cache_skip_streaks")
    if not isinstance(streaks, dict):
        return 0
    val = streaks.get(cache_skip_streak_key(ticker, horizon), 0)
    try:
        return int(val)
    except (TypeError, ValueError):
        return 0


def set_cache_skip_streak(
    ticker: str,
    horizon: str,
    streak: int,
    *,
    path: Path | None = None,
) -> int:
    payload = read_status_payload(path)
    streaks = payload.get("cache_skip_streaks")
    if not isinstance(streaks, dict):
        streaks = {}
    key = cache_skip_streak_key(ticker, horizon)
    streaks[key] = max(0, int(streak))
    payload["cache_skip_streaks"] = streaks
    write_status(_resolve_status_path(path), payload)
    return streaks[key]


def bump_cache_skip_streak(
    ticker: str,
    horizon: str,
    *,
    path: Path | None = None,
) -> int:
    current = get_cache_skip_streak(ticker, horizon, path=path)
    return set_cache_skip_streak(ticker, horizon, current + 1, path=path)


def reset_cache_skip_streak(
    ticker: str,
    horizon: str,
    *,
    path: Path | None = None,
) -> None:
    set_cache_skip_streak(ticker, horizon, 0, path=path)


def enrollment_category_counts(db_path: str | Path) -> dict[str, int]:
    """Count logging_universe rows by category."""
    from db import EdDB

    rows = EdDB(str(db_path)).logging_universe_list_rows()
    counts: dict[str, int] = {}
    for row in rows:
        # Explicit None / empty-string handling (no GET_OR_DEFAULT / IF_TRUTHY_ELSE
        # anti-pattern). Schema guarantees category is a non-empty string on valid
        # enrollments; defensive fallback to "unknown" only when the row is malformed.
        cat_raw = row.get("category")
        if cat_raw is None:
            cat = "unknown"
        else:
            cat_str = str(cat_raw)
            if cat_str == "":
                cat = "unknown"
            else:
                cat = cat_str
        if cat in counts:
            counts[cat] = counts[cat] + 1
        else:
            counts[cat] = 1
    counts["total"] = len(rows)
    return counts


def write_status(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def record_run_start(
    *,
    path: Path | None = None,
    ml_horizon: str,
    target_column: str,
    tickers: list[str],
    db_path: str | Path,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    status_path = _resolve_status_path(path)
    payload: dict[str, Any] = {
        "schema_version": STATUS_SCHEMA_VERSION,
        "last_run_started_utc": datetime.now(timezone.utc).isoformat(),
        "ml_horizon": ml_horizon,
        "target_column": target_column,
        "tickers_selected": list(tickers),
        "tickers_selected_count": len(tickers),
        "enrollment_category_counts": enrollment_category_counts(db_path),
    }
    if extra:
        payload.update(extra)
    write_status(status_path, payload)
    return payload


def record_run_finish(
    *,
    path: Path | None = None,
    ml_horizon: str,
    ticker_outcomes: list[dict[str, Any]],
    exit_code_hint: int = 0,
) -> dict[str, Any]:
    status_path = _resolve_status_path(path)
    existing: dict[str, Any] = {}
    if status_path.is_file():
        try:
            existing = json.loads(status_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            existing = {}
    payload = {
        **existing,
        "schema_version": STATUS_SCHEMA_VERSION,
        "last_run_finished_utc": datetime.now(timezone.utc).isoformat(),
        "last_ml_horizon": ml_horizon,
        "last_ticker_outcomes": ticker_outcomes,
        "last_exit_code_hint": exit_code_hint,
    }
    write_status(status_path, payload)
    return payload
