"""Aggregate training pipeline run status (P0-3)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATUS_SCHEMA_VERSION = "training_pipeline_status_v1"
DEFAULT_STATUS_PATH = Path(__file__).resolve().parent / "models" / "training_pipeline_status.json"


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
    path: Path = DEFAULT_STATUS_PATH,
    ml_horizon: str,
    target_column: str,
    tickers: list[str],
    db_path: str | Path,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
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
    write_status(path, payload)
    return payload


def record_run_finish(
    *,
    path: Path = DEFAULT_STATUS_PATH,
    ml_horizon: str,
    ticker_outcomes: list[dict[str, Any]],
    exit_code_hint: int = 0,
) -> dict[str, Any]:
    existing: dict[str, Any] = {}
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}
    payload = {
        **existing,
        "schema_version": STATUS_SCHEMA_VERSION,
        "last_run_finished_utc": datetime.now(timezone.utc).isoformat(),
        "last_ml_horizon": ml_horizon,
        "last_ticker_outcomes": ticker_outcomes,
        "last_exit_code_hint": exit_code_hint,
    }
    write_status(path, payload)
    return payload
