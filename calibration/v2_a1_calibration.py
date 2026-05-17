"""Fit/apply A1 advisory probability calibration for v2 Pilot 1B.

Scope is intentionally training-time only: post-fusion ``P_entry_success``,
JSON-serializable isotonic artifacts, separate models per horizon, and no
runtime adapter wiring.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from calibration.json_utils import parse_json_mapping
from calibration.schema import ensure_calibration_schema
from calibration.trust import TRUSTED_PREDICATE_SQL
from calibration.v2_advisory_backfill import WalkForwardSplit, validate_purged_embargo_splits
from timeframe_config import CANONICAL_TIMEFRAME

log = logging.getLogger(__name__)

try:
    from db import configure_sqlite_connection
except ImportError as e:
    log.warning(
        "db.configure_sqlite_connection not available — using no-op stub: %s",
        e,
    )

    def configure_sqlite_connection(conn: sqlite3.Connection, **kwargs: Any) -> None:
        return None


A1_CALIBRATION_ARTIFACT_SCHEMA_VERSION = "1"
A1_CALIBRATION_METHOD = "isotonic_regression"
A1_CALIBRATION_HORIZONS = ("1c", "5c", "15c", "60c")
A1_CALIBRATION_HORIZON = "5c"
A1_CALIBRATION_AGGREGATE_HOLDOUT_MIN_SAMPLES = 500  # O-24
A1_CALIBRATION_PER_REGIME_MIN_SAMPLES = 50  # O-25
A1_CALIBRATION_PER_RELIABILITY_BIN_MIN_SAMPLES = 30  # O-26
A1_RELIABILITY_BIN_EDGES = tuple(round(i / 10.0, 1) for i in range(11))
# Distinct from volatility_regime classifier vocabulary ("unknown" is a real class).
A1_REGIME_AXIS_MISSING = "__missing__"


def load_a1_calibration_rows(db_path: Path, *, horizon: str) -> list[dict[str, Any]]:
    """Load trusted rows with advisory v2 snapshots and outcomes for one horizon."""
    hz = _validate_horizon(horizon)
    outcome_col = f"outcome_{hz}"
    outcome_pts_col = f"outcome_{hz}_pts"
    conn = sqlite3.connect(str(db_path), timeout=60.0)
    conn.row_factory = sqlite3.Row
    configure_sqlite_connection(conn)
    ensure_calibration_schema(conn)
    try:
        rows = conn.execute(
            f"""
            SELECT
              id,
              ticker,
              decision_ts_utc,
              advisory_v2_decision_snapshot_json,
              advisory_v2_adapter_version,
              {outcome_col} AS outcome,
              {outcome_pts_col} AS outcome_pts,
              vol_regime,
              session_bucket,
              expiry,
              canonical_timeframe
            FROM calibration_decision_log
            WHERE {outcome_col} IS NOT NULL
              AND advisory_v2_decision_snapshot_json IS NOT NULL
              AND canonical_timeframe = ?
              AND ({TRUSTED_PREDICATE_SQL})
            ORDER BY decision_ts_utc, id
            """,
            (CANONICAL_TIMEFRAME,),
        ).fetchall()
    finally:
        conn.close()

    examples: list[dict[str, Any]] = []
    skipped_reasons: dict[str, int] = {}
    for row in rows:
        try:
            examples.append(_row_to_calibration_example(dict(row), horizon=hz))
        except ValueError as e:
            reason = str(e)[:80] or "row_not_calibratable"
            skipped_reasons[reason] = skipped_reasons.get(reason, 0) + 1
    if skipped_reasons:
        log.info(
            "a1_calibration load: skipped %d unusable rows, reasons=%s",
            sum(skipped_reasons.values()),
            skipped_reasons,
        )
    return examples


def load_a1_5c_calibration_rows(db_path: Path) -> list[dict[str, Any]]:
    """Load trusted rows with advisory v2 snapshots and 5c outcomes."""
    return load_a1_calibration_rows(db_path, horizon=A1_CALIBRATION_HORIZON)


def fit_a1_isotonic_artifact(
    rows: list[dict[str, Any]],
    *,
    horizon: str,
    split: WalkForwardSplit,
    calibration_run_id: str | None = None,
    calibration_window_id: str | None = None,
    min_holdout_samples: int = A1_CALIBRATION_AGGREGATE_HOLDOUT_MIN_SAMPLES,
) -> dict[str, Any]:
    """Fit isotonic calibration and return a JSON-serializable artifact."""
    hz = _validate_horizon(horizon)
    validate_purged_embargo_splits([split], embargo_span=split.holdout_start - split.calibration_end)
    train_rows, holdout_rows = _rows_for_split(rows, split)
    holdout_gate = {
        "n": len(holdout_rows),
        "min_required": min_holdout_samples,
        "sufficient_sample": len(holdout_rows) >= min_holdout_samples,
        "status": "ok" if len(holdout_rows) >= min_holdout_samples else "insufficient_sample",
        "operator_decision": "O-24",
    }
    run_id = calibration_run_id or _stable_id(f"a1-{hz}-calibration-run", rows, split)
    window_id = calibration_window_id or _stable_id(f"a1-{hz}-calibration-window", rows, split)
    base = {
        "schema_version": A1_CALIBRATION_ARTIFACT_SCHEMA_VERSION,
        "calibration_run_id": run_id,
        "calibration_window_id": window_id,
        "module_id": "A",
        "expression_profile_id": "A1",
        "horizon": hz,
        "method": A1_CALIBRATION_METHOD,
        "raw_probability_field": "v2_decision.decision.P_entry_success",
        "target_label": f"outcome_{hz}_direction_matches_v2_direction",
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
            "outcome": row["outcome"],
            f"outcome_{hz}": row["outcome"],
            "volatility_regime": row.get("volatility_regime"),
            "time_of_day_bucket": row.get("time_of_day_bucket"),
            "expiry_dte_bucket": row.get("expiry_dte_bucket"),
            "direction": row.get("direction"),
            "primary_horizon": row.get("primary_horizon"),
        }
        for row in holdout_rows
    ]
    artifact = {
        **base,
        "status": "ok",
        "reason": None,
        "model": model,
        "fit_sample_count": len(train_rows),
        "holdout_predictions": predictions,
    }
    artifact["health"] = build_a1_calibration_health(artifact)
    return artifact


def fit_a1_5c_isotonic_artifact(
    rows: list[dict[str, Any]],
    *,
    split: WalkForwardSplit,
    calibration_run_id: str | None = None,
    calibration_window_id: str | None = None,
    min_holdout_samples: int = A1_CALIBRATION_AGGREGATE_HOLDOUT_MIN_SAMPLES,
) -> dict[str, Any]:
    """Fit the 5c isotonic calibration artifact."""
    return fit_a1_isotonic_artifact(
        rows,
        horizon=A1_CALIBRATION_HORIZON,
        split=split,
        calibration_run_id=calibration_run_id,
        calibration_window_id=calibration_window_id,
        min_holdout_samples=min_holdout_samples,
    )


def build_a1_calibration_health(artifact: dict[str, Any]) -> dict[str, Any]:
    """Compute holdout ECE, Brier, reliability, and deterministic regime slices."""
    horizon_raw = artifact.get("horizon")
    if horizon_raw is None or not str(horizon_raw).strip():
        raise ValueError("artifact horizon is required for A1 calibration health")
    hz = _validate_horizon(str(horizon_raw))
    holdout_raw = artifact.get("holdout_predictions")
    if holdout_raw is None:
        predictions: list[dict[str, Any]] = []
    elif not isinstance(holdout_raw, list):
        log.warning(
            "v2_a1_calibration: holdout_predictions is not a list (%s); treating as empty",
            type(holdout_raw).__name__,
        )
        predictions = []
    else:
        predictions = holdout_raw
    aggregate_gate = _sample_gate(len(predictions), A1_CALIBRATION_AGGREGATE_HOLDOUT_MIN_SAMPLES, "O-24")
    health: dict[str, Any] = {
        "horizon": hz,
        "sample_gates": {
            "aggregate_holdout": aggregate_gate,
        },
        "ece": None,
        "brier_score": None,
        "reliability_table": _reliability_table(predictions),
        "regime_reliability": _regime_reliability(predictions),
    }
    if aggregate_gate["sufficient_sample"]:
        health["ece"] = _expected_calibration_error(health["reliability_table"])
        health["brier_score"] = _brier_score(predictions)
    from calibration.statistical_integrity import verify_a1_calibration_health_no_numeric_leak

    health["numeric_leak_check"] = (
        "pass" if verify_a1_calibration_health_no_numeric_leak(health) else "fail"
    )
    return health


def build_a1_5c_calibration_health(artifact: dict[str, Any]) -> dict[str, Any]:
    """Compute 5c holdout health metrics."""
    return build_a1_calibration_health({**artifact, "horizon": A1_CALIBRATION_HORIZON})


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
    x_raw = float(raw_probability)
    if x_raw < 0.0 or x_raw > 1.0:
        log.warning(
            "apply_isotonic_model: raw_probability %s outside [0, 1]; clamping before interpolation",
            x_raw,
        )
    x_train_min = model.get("x_train_min")
    x_train_max = model.get("x_train_max")
    if x_train_min is not None and x_train_max is not None:
        tmin, tmax = float(x_train_min), float(x_train_max)
        if x_raw < tmin or x_raw > tmax:
            log.warning(
                "apply_isotonic_model: raw_probability %s outside training range [%s, %s] "
                "(sklearn out_of_bounds=clip applies at apply time)",
                x_raw,
                tmin,
                tmax,
            )
    x = min(1.0, max(0.0, x_raw))
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
    raise ValueError("apply_isotonic_model: x not bracketed by isotonic thresholds")


def _reliability_table(predictions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for idx in range(len(A1_RELIABILITY_BIN_EDGES) - 1):
        lo = A1_RELIABILITY_BIN_EDGES[idx]
        hi = A1_RELIABILITY_BIN_EDGES[idx + 1]
        bucket = [
            row
            for row in predictions
            if lo <= float(row["calibrated_probability"]) <= hi
            if idx == len(A1_RELIABILITY_BIN_EDGES) - 2 or float(row["calibrated_probability"]) < hi
        ]
        gate = _sample_gate(len(bucket), A1_CALIBRATION_PER_RELIABILITY_BIN_MIN_SAMPLES, "O-26")
        out = {
            "bin_low": lo,
            "bin_high": hi,
            "n": len(bucket),
            "sample_gate": gate,
            "predicted_mean": None,
            "observed_hit_rate": None,
        }
        if gate["sufficient_sample"] and bucket:
            out["predicted_mean"] = round(sum(float(row["calibrated_probability"]) for row in bucket) / len(bucket), 6)
            out["observed_hit_rate"] = round(sum(int(row["label"]) for row in bucket) / len(bucket), 6)
        rows.append(out)
    return rows


def axis_reliability_bucket_value(raw: Any) -> str:
    if raw is None:
        return A1_REGIME_AXIS_MISSING
    text = str(raw).strip()
    return text if text else A1_REGIME_AXIS_MISSING


def _regime_reliability(predictions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    axes = ("volatility_regime", "time_of_day_bucket", "expiry_dte_bucket", "ticker", "direction", "primary_horizon")
    out: dict[str, dict[str, Any]] = {}
    for axis in axes:
        values = sorted({axis_reliability_bucket_value(row.get(axis)) for row in predictions})
        for value in values:
            bucket = [row for row in predictions if axis_reliability_bucket_value(row.get(axis)) == value]
            gate = _sample_gate(len(bucket), A1_CALIBRATION_PER_REGIME_MIN_SAMPLES, "O-25")
            key = f"{axis}:{value}"
            out[key] = {
                "axis": axis,
                "value": value,
                "n": len(bucket),
                "sample_gate": gate,
                "predicted_mean": None,
                "observed_hit_rate": None,
            }
            if gate["sufficient_sample"] and bucket:
                out[key]["predicted_mean"] = round(sum(float(row["calibrated_probability"]) for row in bucket) / len(bucket), 6)
                out[key]["observed_hit_rate"] = round(sum(int(row["label"]) for row in bucket) / len(bucket), 6)
    return out


def _expected_calibration_error(reliability_table: list[dict[str, Any]]) -> float | None:
    total = sum(int(row["n"]) for row in reliability_table if row["sample_gate"]["sufficient_sample"])
    if total <= 0:
        return None
    err = 0.0
    for row in reliability_table:
        if not row["sample_gate"]["sufficient_sample"]:
            continue
        err += (int(row["n"]) / total) * abs(float(row["observed_hit_rate"]) - float(row["predicted_mean"]))
    return round(err, 6)


def _brier_score(predictions: list[dict[str, Any]]) -> float | None:
    if not predictions:
        return None
    terms = [
        (float(row["calibrated_probability"]) - int(row["label"])) ** 2
        for row in predictions
    ]
    return round(sum(terms) / len(terms), 6)


def _sample_gate(n: int, min_required: int, operator_decision: str) -> dict[str, Any]:
    return {
        "n": int(n),
        "min_required": int(min_required),
        "sufficient_sample": int(n) >= int(min_required),
        "status": "ok" if int(n) >= int(min_required) else "insufficient_sample",
        "operator_decision": operator_decision,
    }


def _fit_isotonic_model(raw_probabilities: list[float], labels: list[int]) -> dict[str, Any]:
    try:
        from sklearn.isotonic import IsotonicRegression
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(f"sklearn IsotonicRegression is required for A1 calibration: {exc}") from exc

    iso = IsotonicRegression(y_min=0.0, y_max=1.0, increasing=True, out_of_bounds="clip")
    iso.fit(raw_probabilities, labels)
    train_x = [float(v) for v in raw_probabilities]
    return {
        "type": "isotonic_regression",
        "x_thresholds": [round(float(v), 10) for v in iso.X_thresholds_],
        "y_thresholds": [round(float(v), 10) for v in iso.y_thresholds_],
        "x_train_min": round(min(train_x), 10),
        "x_train_max": round(max(train_x), 10),
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


def _row_to_calibration_example(row: dict[str, Any], *, horizon: str) -> dict[str, Any]:
    hz = _validate_horizon(horizon)
    payload = parse_json_mapping(
        row.get("advisory_v2_decision_snapshot_json"),
        context="v2_a1_calibration: advisory_v2_decision_snapshot_json",
    )
    v2 = payload.get("v2_decision") if isinstance(payload.get("v2_decision"), dict) else {}
    decision = v2.get("decision") if isinstance(v2.get("decision"), dict) else {}
    action = _leaf_value(decision.get("action"))
    direction = _leaf_value(decision.get("direction"))
    raw_p = _float_or_none(_leaf_value(decision.get("P_entry_success")))
    outcome_raw = row.get("outcome")
    outcome = str(outcome_raw).lower() if outcome_raw is not None else None
    label = _success_label(direction, outcome)
    if action != "TRADE":
        raise ValueError(f"non_trade_action:{action!r}")
    if raw_p is None:
        raise ValueError("missing_p_entry_success")
    if label is None:
        raise ValueError(f"unusable_label:direction={direction!r}_outcome={outcome!r}")
    return {
        "calibration_row_id": int(row["id"]),
        "ticker": row.get("ticker"),
        "decision_ts_utc": float(row["decision_ts_utc"]),
        "raw_probability": raw_p,
        "label": label,
        "direction": direction,
        "outcome": outcome,
        f"outcome_{hz}": outcome,
        "outcome_pts": row.get("outcome_pts"),
        f"outcome_{hz}_pts": row.get("outcome_pts"),
        "adapter_version": row.get("advisory_v2_adapter_version"),
        "volatility_regime": row.get("vol_regime"),
        "time_of_day_bucket": row.get("session_bucket"),
        "expiry_dte_bucket": "not_options_applicable",
        "primary_horizon": hz,
    }


def _success_label(direction: Any, outcome: str | None) -> int | None:
    if not outcome:
        return None
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


def _float_or_none(value: Any) -> float | None:
    try:
        if value is not None:
            return float(value)
    except (TypeError, ValueError):
        return None
    return None


def _validate_horizon(horizon: str) -> str:
    hz = str(horizon or "").strip().lower()
    if hz not in A1_CALIBRATION_HORIZONS:
        raise ValueError(f"unsupported A1 calibration horizon: {horizon!r}")
    return hz


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
