"""Backfill advisory v2 decision snapshots for calibration rows.

This uses additive columns on ``calibration_decision_log`` rather than a new
v2 table so existing calibration outcome joins keep their row identity.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from calibration.backfill_outcomes import resolve_snapshot_for_backfill
from calibration.canonical_enforcement import enforce_calibration_decision_log_only_1m
from calibration.json_utils import parse_json_mapping
from calibration.schema import ensure_calibration_schema
from timeframe_config import CANONICAL_TIMEFRAME
from v2_decision import SCHEMA_VERSION, V2_STATUS, build_module_a_a1_decision

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
        # COH-I-L: stamp field_sources for the reconstructed dte_warn so replay readers can
        # tell this value came from snapshot reconstruction (not live live-tier-c).
        field_sources["dte_warn"] = RECONSTRUCTED_LIVE_MS_SOURCE

    if "option_chain_selection_proof" not in ms:
        replay_context = parse_json_mapping(
            ms.get("replay_context_json"),
            context="v2_advisory_backfill: replay_context_json",
        )
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
    if ts_utc is not None:
        ms.setdefault("ts_utc", ts_utc)
        from ml_data_common import market_session_from_ts_utc
        from app.domain.time_et import et_clock_from_ts_utc

        eh, em, _ = et_clock_from_ts_utc(ts_utc)
        ms["et_hour"] = eh
        ms["et_minute"] = em
        ms["market_session"] = market_session_from_ts_utc(ts_utc)
        field_sources["et_hour"] = RECONSTRUCTED_LIVE_MS_SOURCE
        field_sources["et_minute"] = RECONSTRUCTED_LIVE_MS_SOURCE
        field_sources["market_session"] = RECONSTRUCTED_LIVE_MS_SOURCE
    ms.setdefault("ticker", ticker)
    ms.setdefault("decision_generation_id", snapshot_id)
    ms.setdefault("_server_build_ts", ts_utc)
    ms.setdefault("decision_time_ms", int(ts_utc * 1000) if ts_utc is not None else None)
    for block in ("stack_runtime", "stack_governance", "signal_chain"):
        existing = ms.get(block)
        if existing is None:
            ms[block] = {"source": RECONSTRUCTED_LIVE_MS_SOURCE}
            field_sources[block] = RECONSTRUCTED_LIVE_MS_SOURCE
        elif isinstance(existing, dict) and existing.get("source") == RECONSTRUCTED_LIVE_MS_SOURCE:
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
        "decision_ts_utc": _float_or_none(
            _first_present(ms_dict, "ts_utc", "decision_ts_utc")
        ),
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
        "errored": 0,
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
        try:
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
        except Exception as e:
            err_reason = f"build_failed:{type(e).__name__}:{str(e)[:200]}"
            _mark_backfill_status(conn, rid, "error", err_reason, now)
            stats["errored"] += 1

    conn.commit()
    conn.close()
    return stats


# ───────────────────── Track B (v2.1) — historical INSERT backfill ─────────────────────
#
# Track B reconstructs calibration_decision_log rows that should have been
# written by the live writer but were never persisted (e.g., during the Apr 12
# – May 5 ED_CALIBRATION_LOG=off gap). It is a NEW INSERT path — distinct from
# backfill_v2_advisory_decisions above (which only UPDATEs rows that already
# exist).
#
# Provenance: every inserted row carries decision_source='reconstructed_from_snapshot'
# so training-skew analyses can optionally exclude reconstructed rows from
# calibration. The OPEN_ITEMS row is tagged [REAL-GATE: training-skew].
#
# Acceptance criteria (per v2.1 plan):
#   - Idempotent: second run inserts 0 (UNIQUE on (ticker, decision_ts_utc)
#     plus a pre-INSERT NOT EXISTS join).
#   - Returns {inserted, skipped, skipped_reason_counts: {reason: count, ...}}.

RECONSTRUCTED_DECISION_SOURCE = "reconstructed_from_snapshot"

# Columns copied verbatim from snapshot row -> calibration_decision_log (same name).
# Kept conservative — these are the analysis-critical fields. Other 38-col live
# writer fields stay NULL on backfilled rows; that's why decision_source exists.
_SNAPSHOT_TO_CALIBRATION_COPY_COLUMNS: tuple[str, ...] = (
    "session_bucket",
    "expiry",
    "zone",
    "vwap_side",
    "nearest_above_dist",
    "nearest_below_dist",
    "regime_primary",
    "regime_confidence",
    "vol_regime",
    "vix_bucket",
    "outcome_1c",
    "outcome_5c",
    "outcome_15c",
    "outcome_60c",
    "outcome_1c_pts",
    "outcome_5c_pts",
    "outcome_15c_pts",
    "outcome_60c_pts",
)


def backfill_calibration_decisions_insert_from_snapshots(
    db_path: Path,
    *,
    limit: int | None = None,
    now_ts: float | None = None,
) -> dict[str, Any]:
    """Track B (v2.1) — INSERT a calibration_decision_log row for every snapshot
    that has fusion + outcome populated but no existing calibration row.

    Distinct from backfill_v2_advisory_decisions (UPDATE path). Idempotent via
    NOT EXISTS join + UNIQUE (ticker, decision_ts_utc).

    Returns ``{inserted, skipped, skipped_reason_counts: {reason: count}}``.
    """
    now = float(now_ts if now_ts is not None else time.time())
    conn = sqlite3.connect(str(db_path), timeout=60.0)
    conn.row_factory = sqlite3.Row
    configure_sqlite_connection(conn)
    ensure_calibration_schema(conn)

    inserted = 0
    skipped = 0
    skipped_reason_counts: dict[str, int] = {}

    sql = """
        SELECT s.*
        FROM snapshots s
        WHERE s.timeframe = ?
          AND s.fusion_dominant_prob IS NOT NULL
          AND s.outcome_5c IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM calibration_decision_log c
              WHERE c.ticker = s.ticker
                AND c.decision_ts_utc = s.ts_utc
          )
        ORDER BY s.ts_utc
    """
    params: tuple[Any, ...] = (CANONICAL_TIMEFRAME,)
    if limit is not None:
        sql += " LIMIT ?"
        params = params + (int(limit),)

    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError as exc:
        # snapshots table missing or columns absent — surface as a single
        # "schema_unavailable" skip so callers see a structured failure.
        conn.close()
        return {
            "inserted": 0,
            "skipped": 0,
            "skipped_reason_counts": {f"schema_unavailable:{exc!s}": 1},
        }

    for row in rows:
        try:
            payload_dict = build_v2_advisory_snapshot(row)
            cols: dict[str, Any] = {
                "decision_ts_utc": float(row["ts_utc"]),
                "ticker": str(row["ticker"]),
                "canonical_timeframe": CANONICAL_TIMEFRAME,
                "calibration_trust": "legacy",
                "decision_source": RECONSTRUCTED_DECISION_SOURCE,
                "matched_snapshot_ts_utc": float(row["ts_utc"]),
                "outcome_join_method": RECONSTRUCTED_LIVE_MS_SOURCE,
                "advisory_v2_decision_snapshot_json": json.dumps(
                    payload_dict, default=str, sort_keys=True
                ),
                "advisory_v2_snapshot_schema_version": ADVISORY_V2_SNAPSHOT_SCHEMA_VERSION,
                "advisory_v2_adapter_version": ADVISORY_V2_ADAPTER_VERSION,
                "advisory_v2_backfilled_ts_utc": now,
                "advisory_v2_backfill_status": "ok",
            }
            for cn in _SNAPSHOT_TO_CALIBRATION_COPY_COLUMNS:
                try:
                    cols[cn] = row[cn]
                except (IndexError, KeyError):
                    cols[cn] = None
            placeholders = ", ".join("?" for _ in cols)
            column_list = ", ".join(cols.keys())
            cur = conn.execute(
                f"INSERT OR IGNORE INTO calibration_decision_log ({column_list}) "
                f"VALUES ({placeholders})",
                list(cols.values()),
            )
            if int(cur.rowcount) > 0:
                inserted += 1
            else:
                skipped += 1
                skipped_reason_counts["unique_conflict"] = (
                    skipped_reason_counts.get("unique_conflict", 0) + 1
                )
        except (sqlite3.Error, KeyError, TypeError, ValueError) as exc:
            skipped += 1
            reason = f"{type(exc).__name__}:{str(exc)[:80]}"
            skipped_reason_counts[reason] = skipped_reason_counts.get(reason, 0) + 1

    conn.commit()
    conn.close()
    return {
        "inserted": inserted,
        "skipped": skipped,
        "skipped_reason_counts": skipped_reason_counts,
    }


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


def _fusion_prob_triplet(ms: Mapping[str, Any]) -> tuple[float | None, float | None, float | None]:
    return (
        _float_or_none(ms.get("fusion_prob_up")),
        _float_or_none(ms.get("fusion_prob_down")),
        _float_or_none(ms.get("fusion_prob_flat")),
    )


def _fusion_triplet_complete(ms: Mapping[str, Any]) -> bool:
    return all(p is not None for p in _fusion_prob_triplet(ms))


def _infer_fusion_fields(ms: dict[str, Any]) -> None:
    up, down, flat = _fusion_prob_triplet(ms)
    if "fusion_available" not in ms or ms.get("fusion_available") is None:
        dominant_dir = ms.get("fusion_dominant_direction")
        dominant_prob = _float_or_none(ms.get("fusion_dominant_prob"))
        ms["fusion_available"] = _fusion_triplet_complete(ms) or (
            dominant_dir is not None and dominant_prob is not None
        )
    if ms.get("fusion_dominant_direction") is None and _fusion_triplet_complete(ms):
        direction = _direction_from_triplet(up, down, flat)
        if direction is not None:
            ms["fusion_dominant_direction"] = direction
    if ms.get("fusion_dominant_prob") is None and _fusion_triplet_complete(ms):
        ms["fusion_dominant_prob"] = max((up, down, flat))


def _direction_from_triplet(up: Any, down: Any, flat: Any) -> str | None:
    from app.domain.numeric_contract import direction_from_triplet

    return direction_from_triplet(up, down, flat)


def _float_or_none(value: Any) -> float | None:
    from app.domain.numeric_contract import float_finite_or_none

    return float_finite_or_none(value)


def _first_present(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value is not None:
            return value
    return None
