"""Backfill advisory v2 decision snapshots for calibration rows.

This uses additive columns on ``calibration_decision_log`` rather than a new
v2 table so existing calibration outcome joins keep their row identity.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from calibration.backfill_outcomes import resolve_snapshot_for_backfill
from calibration.canonical_enforcement import enforce_calibration_decision_log_only_1m
from calibration.schema import ensure_calibration_schema
from timeframe_config import CANONICAL_TIMEFRAME
from v2_decision import SCHEMA_VERSION, V2_STATUS, build_module_a_a1_decision

try:
    from db import configure_sqlite_connection
except Exception:

    def configure_sqlite_connection(conn: sqlite3.Connection, **kwargs: Any) -> None:
        return None


ADVISORY_V2_SNAPSHOT_SCHEMA_VERSION = "1"
ADVISORY_V2_ADAPTER_VERSION = f"module_a_adapter:{SCHEMA_VERSION}:{V2_STATUS}"
RECONSTRUCTED_LIVE_MS_SOURCE = "reconstructed_from_snapshot"

ADVISORY_V2_DECISION_LOG_COLUMNS = (
    "advisory_v2_decision_snapshot_json",
    "advisory_v2_snapshot_schema_version",
    "advisory_v2_adapter_version",
    "advisory_v2_backfilled_ts_utc",
    "advisory_v2_backfill_status",
    "advisory_v2_backfill_reason",
)


@dataclass(frozen=True)
class WalkForwardSplit:
    train_start: float
    train_end: float
    calibration_start: float
    calibration_end: float
    holdout_start: float
    holdout_end: float


def ms_dict_from_snapshot_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Reconstruct the subset of Tier C state needed by the v2 advisory adapter."""
    ms = dict(row)
    field_sources: dict[str, str] = {}
    ticker = _first_present(ms, "ticker")
    ts_utc = _float_or_none(_first_present(ms, "ts_utc", "decision_ts_utc"))
    snapshot_id = _first_present(ms, "snapshot_id", "id")

    def _alias_if_absent_stamped(target: str, source: str) -> None:
        if ms.get(target) is None and ms.get(source) is not None:
            ms[target] = ms.get(source)
            field_sources[target] = RECONSTRUCTED_LIVE_MS_SOURCE

    _alias_if_absent_stamped("rules_headline", "rules_summary")
    _alias_if_absent_stamped("entry", "rules_entry")
    _alias_if_absent_stamped("stop", "rules_stop")
    _alias_if_absent_stamped("target", "rules_target")
    _alias_if_absent_stamped("target2", "call_target2")
    _alias_if_absent_stamped("selected_exp", "expiry")
    _alias_if_absent_stamped("call_option_expiry", "expiry")
    _alias_if_absent_stamped("spread", "call_spread")
    _alias_if_absent_stamped("rec_strike", "call_strike")
    _alias_if_absent_stamped("rec_side", "call_option_right")
    if ms.get("dte_warn") is None and ms.get("dte") is not None:
        ms["dte_warn"] = f"{ms.get('dte')}DTE"

    if "option_chain_selection_proof" not in ms:
        replay_context = _json_obj(ms.get("replay_context_json"))
        proof = replay_context.get("option_chain_selection_proof")
        if proof is not None:
            ms["option_chain_selection_proof"] = proof
        for key in (
            "regime_primary",
            "regime_confidence",
            "zone",
            "vol_regime",
            "trade_type",
            "time_qualifier",
            "vwap",
            "vwap_side",
        ):
            if ms.get(key) is None and replay_context.get(key) is not None:
                ms[key] = replay_context.get(key)
                field_sources[key] = RECONSTRUCTED_LIVE_MS_SOURCE

    _infer_fusion_fields(ms)
    ms.setdefault("ticker", ticker)
    ms.setdefault("decision_generation_id", snapshot_id)
    ms.setdefault("_server_build_ts", ts_utc)
    ms.setdefault("decision_time_ms", int(ts_utc * 1000) if ts_utc is not None else None)
    ms.setdefault("stack_runtime", {"source": RECONSTRUCTED_LIVE_MS_SOURCE})
    ms.setdefault("stack_governance", {"source": RECONSTRUCTED_LIVE_MS_SOURCE})
    ms.setdefault("signal_chain", {"source": RECONSTRUCTED_LIVE_MS_SOURCE})
    for block in ("stack_runtime", "stack_governance", "signal_chain"):
        field_sources[block] = RECONSTRUCTED_LIVE_MS_SOURCE
    ms["live_ms_field_sources"] = field_sources
    ms["live_ms_reconstruction_source"] = RECONSTRUCTED_LIVE_MS_SOURCE
    return ms


def build_v2_advisory_snapshot(snapshot_row: Mapping[str, Any]) -> dict[str, Any]:
    """Run the current v2 adapter on a reconstructed historical snapshot row."""
    ms_dict = ms_dict_from_snapshot_row(snapshot_row)
    v2_decision = build_module_a_a1_decision(ms_dict)
    return {
        "snapshot_schema_version": ADVISORY_V2_SNAPSHOT_SCHEMA_VERSION,
        "adapter_version": ADVISORY_V2_ADAPTER_VERSION,
        "source": RECONSTRUCTED_LIVE_MS_SOURCE,
        "live_ms_field_sources": dict(ms_dict.get("live_ms_field_sources") or {}),
        "ticker": ms_dict.get("ticker"),
        "snapshot_id": ms_dict.get("snapshot_id"),
        "decision_ts_utc": ms_dict.get("ts_utc"),
        "v2_decision": v2_decision,
    }


def backfill_v2_advisory_decisions(
    db_path: Path,
    *,
    tol_sec: float = 0.0,
    limit: int | None = None,
) -> dict[str, Any]:
    """Populate advisory v2 decision JSON for trusted calibration rows."""
    conn = sqlite3.connect(str(db_path), timeout=60.0)
    conn.row_factory = sqlite3.Row
    configure_sqlite_connection(conn)
    ensure_calibration_schema(conn)
    enforce_calibration_decision_log_only_1m(conn)

    stats: dict[str, Any] = {
        "candidates": 0,
        "updated": 0,
        "skipped": 0,
        "tol_sec": tol_sec,
        "adapter_version": ADVISORY_V2_ADAPTER_VERSION,
    }
    rows = conn.execute(
        f"""
        SELECT id, ticker, decision_ts_utc
        FROM calibration_decision_log
        WHERE calibration_trust = 'trusted'
          AND canonical_timeframe = ?
          AND advisory_v2_decision_snapshot_json IS NULL
        ORDER BY id
        {"LIMIT ?" if limit is not None else ""}
        """,
        (CANONICAL_TIMEFRAME, int(limit)) if limit is not None else (CANONICAL_TIMEFRAME,),
    ).fetchall()
    stats["candidates"] = len(rows)
    now = time.time()

    for row in rows:
        rid = int(row["id"])
        snap, reason, _method = resolve_snapshot_for_backfill(
            conn,
            str(row["ticker"]),
            float(row["decision_ts_utc"]),
            tol_sec,
        )
        if snap is None:
            _mark_backfill_status(conn, rid, "skipped", reason, now)
            stats["skipped"] += 1
            stats[f"skipped_{reason}"] = int(stats.get(f"skipped_{reason}", 0)) + 1
            continue

        payload = build_v2_advisory_snapshot(snap)
        conn.execute(
            """
            UPDATE calibration_decision_log SET
              advisory_v2_decision_snapshot_json=?,
              advisory_v2_snapshot_schema_version=?,
              advisory_v2_adapter_version=?,
              advisory_v2_backfilled_ts_utc=?,
              advisory_v2_backfill_status='ok',
              advisory_v2_backfill_reason=NULL
            WHERE id=?
            """,
            (
                json.dumps(payload, default=str, sort_keys=True),
                ADVISORY_V2_SNAPSHOT_SCHEMA_VERSION,
                ADVISORY_V2_ADAPTER_VERSION,
                now,
                rid,
            ),
        )
        stats["updated"] += 1

    conn.commit()
    conn.close()
    return stats


def build_walk_forward_splits(
    *,
    start_ts: float,
    end_ts: float,
    train_span: float,
    calibration_span: float,
    holdout_span: float,
    step_span: float,
    embargo_span: float,
) -> list[WalkForwardSplit]:
    """Build purged walk-forward splits with an embargo before holdout."""
    splits: list[WalkForwardSplit] = []
    cursor = float(start_ts)
    while True:
        train_start = cursor
        train_end = train_start + train_span
        calibration_start = train_end
        calibration_end = calibration_start + calibration_span
        holdout_start = calibration_end + embargo_span
        holdout_end = holdout_start + holdout_span
        if holdout_end > end_ts:
            break
        splits.append(
            WalkForwardSplit(
                train_start=train_start,
                train_end=train_end,
                calibration_start=calibration_start,
                calibration_end=calibration_end,
                holdout_start=holdout_start,
                holdout_end=holdout_end,
            )
        )
        cursor += step_span
    return splits


def validate_purged_embargo_splits(splits: list[WalkForwardSplit], *, embargo_span: float) -> None:
    """Raise if any split overlaps or violates the required embargo."""
    for split in splits:
        if not (split.train_start < split.train_end <= split.calibration_start < split.calibration_end):
            raise ValueError("walk-forward train/calibration windows overlap or are malformed")
        if split.holdout_start < split.calibration_end + embargo_span:
            raise ValueError("walk-forward split violates embargo before holdout")
        if not split.holdout_start < split.holdout_end:
            raise ValueError("walk-forward holdout window is malformed")


def _mark_backfill_status(
    conn: sqlite3.Connection,
    row_id: int,
    status: str,
    reason: str | None,
    ts_utc: float,
) -> None:
    conn.execute(
        """
        UPDATE calibration_decision_log SET
          advisory_v2_backfilled_ts_utc=?,
          advisory_v2_backfill_status=?,
          advisory_v2_backfill_reason=?
        WHERE id=?
        """,
        (ts_utc, status, reason, row_id),
    )


def _alias_if_absent(ms: dict[str, Any], target: str, source: str) -> None:
    if ms.get(target) is None and ms.get(source) is not None:
        ms[target] = ms.get(source)


def _infer_fusion_fields(ms: dict[str, Any]) -> None:
    if "fusion_available" not in ms or ms.get("fusion_available") is None:
        ms["fusion_available"] = any(
            ms.get(key) is not None
            for key in ("fusion_dominant_prob", "fusion_prob_up", "fusion_prob_down", "fusion_prob_flat")
        )
    if ms.get("fusion_dominant_direction") is None:
        direction = _direction_from_triplet(ms.get("fusion_prob_up"), ms.get("fusion_prob_down"), ms.get("fusion_prob_flat"))
        if direction is not None:
            ms["fusion_dominant_direction"] = direction
    if ms.get("fusion_dominant_prob") is None:
        probs = [_float_or_none(ms.get(key)) for key in ("fusion_prob_up", "fusion_prob_down", "fusion_prob_flat")]
        vals = [p for p in probs if p is not None]
        if vals:
            ms["fusion_dominant_prob"] = max(vals)


def _direction_from_triplet(up: Any, down: Any, flat: Any) -> str | None:
    vals = {
        "up": _float_or_none(up),
        "down": _float_or_none(down),
        "flat": _float_or_none(flat),
    }
    present = {k: v for k, v in vals.items() if v is not None}
    if not present:
        return None
    return max(present.items(), key=lambda kv: kv[1])[0]


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


def _first_present(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value is not None:
            return value
    return None
