"""Fit/apply A1 advisory probability calibration for v2 Pilot 1B.

Scope is intentionally narrow: 5c horizon first, post-fusion
``P_entry_success`` only, JSON-serializable isotonic artifact, and no runtime
adapter wiring.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from calibration.schema import ensure_calibration_schema
from calibration.trust import TRUSTED_PREDICATE_SQL
from calibration.v2_advisory_backfill import WalkForwardSplit, validate_purged_embargo_splits
from timeframe_config import CANONICAL_TIMEFRAME

try:
    from db import configure_sqlite_connection
except Exception:

    def configure_sqlite_connection(conn: sqlite3.Connection, **kwargs: Any) -> None:
        return None


A1_CALIBRATION_ARTIFACT_SCHEMA_VERSION = "1"
A1_CALIBRATION_METHOD = "isotonic_regression"
A1_CALIBRATION_HORIZON = "5c"
A1_CALIBRATION_AGGREGATE_HOLDOUT_MIN_SAMPLES = 500  # O-24


def load_a1_5c_calibration_rows(db_path: Path) -> list[dict[str, Any]]:
    """Load trusted rows with advisory v2 snapshots and 5c outcomes."""
    conn = sqlite3.connect(str(db_path), timeout=60.0)
    conn.row_factory = sqlite3.Row
    configure_sqlite_connection(conn)
    ensure_calibration_schema(conn)
    rows = conn.execute(
        f"""
        SELECT
          id,
          ticker,
          decision_ts_utc,
          advisory_v2_decision_snapshot_json,
          advisory_v2_adapter_version,
          outcome_5c,
          outcome_5c_pts,
          vol_regime,
          session_bucket,
          expiry,
          canonical_timeframe
        FROM calibration_decision_log
        WHERE outcome_5c IS NOT NULL
          AND advisory_v2_decision_snapshot_json IS NOT NULL
          AND canonical_timeframe = ?
          AND ({TRUSTED_PREDICATE_SQL})
        ORDER BY decision_ts_utc, id
        """,
        (CANONICAL_TIMEFRAME,),
    ).fetchall()
    conn.close()
    return [_row_to_calibration_example(dict(row)) for row in rows]


def fit_a1_5c_isotonic_artifact(
    rows: list[dict[str, Any]],
    *,
    split: WalkForwardSplit,
    calibration_run_id: str | None = None,
    calibration_window_id: str | None = None,
    min_holdout_samples: int = A1_CALIBRATION_AGGREGATE_HOLDOUT_MIN_SAMPLES,
) -> dict[str, Any]:
    """Fit isotonic calibration and return a JSON-serializable artifact."""
    validate_purged_embargo_splits([split], embargo_span=split.holdout_start - split.calibration_end)
    train_rows, holdout_rows = _rows_for_split(rows, split)
    holdout_gate = {
        "n": len(holdout_rows),
        "min_required": min_holdout_samples,
        "sufficient_sample": len(holdout_rows) >= min_holdout_samples,
        "status": "ok" if len(holdout_rows) >= min_holdout_samples else "insufficient_sample",
        "operator_decision": "O-24",
    }
    run_id = calibration_run_id or _stable_id("a1-calibration-run", rows, split)
    window_id = calibration_window_id or _stable_id("a1-calibration-window", rows, split)
    base = {
        "schema_version": A1_CALIBRATION_ARTIFACT_SCHEMA_VERSION,
        "calibration_run_id": run_id,
        "calibration_window_id": window_id,
        "module_id": "A",
        "expression_profile_id": "A1",
        "horizon": A1_CALIBRATION_HORIZON,
        "method": A1_CALIBRATION_METHOD,
        "raw_probability_field": "v2_decision.decision.P_entry_success",
        "target_label": "outcome_5c_direction_matches_v2_direction",
        "sample_gate": {
            "aggregate_holdout": holdout_gate,
        },
        "window": {
            "train_start": split.train_start,
            "train_end": split.train_end,
            "calibration_start": split.calibration_start,
            "calibration_end": split.calibration_end,
            "holdout_start": split.holdout_start,
            "holdout_end": split.holdout_end,
        },
        "runtime_adapter_unchanged": True,
    }
    if not holdout_gate["sufficient_sample"]:
        return {
            **base,
            "status": "calibration_skipped_insufficient_samples",
            "reason": "aggregate_holdout_below_o24",
            "model": None,
            "holdout_predictions": [],
        }
    if len(train_rows) < 2 or len({row["label"] for row in train_rows}) < 2:
        return {
            **base,
            "status": "calibration_skipped_insufficient_training_variance",
            "reason": "training_rows_need_both_success_and_failure",
            "model": None,
            "holdout_predictions": [],
        }

    model = _fit_isotonic_model([row["raw_probability"] for row in train_rows], [row["label"] for row in train_rows])
    predictions = [
        {
            "calibration_row_id": row["calibration_row_id"],
            "ticker": row["ticker"],
            "decision_ts_utc": row["decision_ts_utc"],
            "raw_probability": row["raw_probability"],
            "calibrated_probability": apply_isotonic_model(model, row["raw_probability"]),
            "label": row["label"],
            "outcome_5c": row["outcome_5c"],
        }
        for row in holdout_rows
    ]
    return {
        **base,
        "status": "ok",
        "reason": None,
        "model": model,
        "fit_sample_count": len(train_rows),
        "holdout_predictions": predictions,
    }


def write_a1_calibration_artifact(artifact_dir: Path, artifact: dict[str, Any]) -> Path:
    """Persist the calibration artifact as deterministic JSON, not pickle."""
    artifact_dir.mkdir(parents=True, exist_ok=True)
    run_id = str(artifact["calibration_run_id"])
    path = artifact_dir / f"{run_id}.json"
    path.write_text(json.dumps(artifact, indent=2, sort_keys=True, default=str), encoding="utf-8")
    return path


def apply_isotonic_model(model: dict[str, Any], raw_probability: float) -> float:
    """Apply JSON-serialized isotonic step function with clipped bounds."""
    xs = [float(x) for x in model.get("x_thresholds", [])]
    ys = [float(y) for y in model.get("y_thresholds", [])]
    if not xs or not ys or len(xs) != len(ys):
        raise ValueError("invalid isotonic model thresholds")
    x = min(1.0, max(0.0, float(raw_probability)))
    if x <= xs[0]:
        return round(ys[0], 6)
    if x >= xs[-1]:
        return round(ys[-1], 6)
    for idx in range(1, len(xs)):
        if x <= xs[idx]:
            x0, x1 = xs[idx - 1], xs[idx]
            y0, y1 = ys[idx - 1], ys[idx]
            if x1 == x0:
                return round(y1, 6)
            frac = (x - x0) / (x1 - x0)
            return round(y0 + frac * (y1 - y0), 6)
    return round(ys[-1], 6)


def _fit_isotonic_model(raw_probabilities: list[float], labels: list[int]) -> dict[str, Any]:
    try:
        from sklearn.isotonic import IsotonicRegression
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(f"sklearn IsotonicRegression is required for A1 calibration: {exc}") from exc

    iso = IsotonicRegression(y_min=0.0, y_max=1.0, increasing=True, out_of_bounds="clip")
    iso.fit(raw_probabilities, labels)
    return {
        "type": "isotonic_regression",
        "x_thresholds": [round(float(v), 10) for v in iso.X_thresholds_],
        "y_thresholds": [round(float(v), 10) for v in iso.y_thresholds_],
    }


def _rows_for_split(rows: list[dict[str, Any]], split: WalkForwardSplit) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    train_rows = [
        row
        for row in rows
        if split.train_start <= float(row["decision_ts_utc"]) < split.calibration_end
    ]
    holdout_rows = [
        row
        for row in rows
        if split.holdout_start <= float(row["decision_ts_utc"]) < split.holdout_end
    ]
    return train_rows, holdout_rows


def _row_to_calibration_example(row: dict[str, Any]) -> dict[str, Any]:
    payload = _json_obj(row.get("advisory_v2_decision_snapshot_json"))
    v2 = payload.get("v2_decision") if isinstance(payload.get("v2_decision"), dict) else {}
    decision = v2.get("decision") if isinstance(v2.get("decision"), dict) else {}
    action = _leaf_value(decision.get("action"))
    direction = _leaf_value(decision.get("direction"))
    raw_p = _float_or_none(_leaf_value(decision.get("P_entry_success")))
    outcome = str(row.get("outcome_5c") or "").lower()
    label = _success_label(direction, outcome)
    if action != "TRADE" or raw_p is None or label is None:
        raise ValueError("row cannot be used for A1 calibration")
    return {
        "calibration_row_id": int(row["id"]),
        "ticker": row.get("ticker"),
        "decision_ts_utc": float(row["decision_ts_utc"]),
        "raw_probability": raw_p,
        "label": label,
        "direction": direction,
        "outcome_5c": outcome,
        "outcome_5c_pts": row.get("outcome_5c_pts"),
        "adapter_version": row.get("advisory_v2_adapter_version"),
        "volatility_regime": row.get("vol_regime"),
        "time_of_day_bucket": row.get("session_bucket"),
        "expiry_dte_bucket": "not_options_applicable",
        "primary_horizon": A1_CALIBRATION_HORIZON,
    }


def _success_label(direction: Any, outcome: str) -> int | None:
    d = str(direction or "").lower()
    if d == "long":
        return 1 if outcome == "up" else 0
    if d == "short":
        return 1 if outcome == "down" else 0
    return None


def _leaf_value(value: Any) -> Any:
    if isinstance(value, dict) and "value" in value:
        return value.get("value")
    return value


def _json_obj(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _float_or_none(value: Any) -> float | None:
    try:
        if value is not None:
            return float(value)
    except (TypeError, ValueError):
        return None
    return None


def _stable_id(prefix: str, rows: Iterable[dict[str, Any]], split: WalkForwardSplit) -> str:
    material = {
        "prefix": prefix,
        "rows": [
            (row.get("calibration_row_id"), row.get("decision_ts_utc"), row.get("raw_probability"), row.get("label"))
            for row in rows
        ],
        "split": split.__dict__,
    }
    digest = hashlib.sha256(json.dumps(material, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"
