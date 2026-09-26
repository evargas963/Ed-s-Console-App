"""Backfill advisory v2 decision snapshots for calibration rows.

This uses additive columns on ``calibration_decision_log`` rather than a new
v2 table so existing calibration outcome joins keep their row identity.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from typing import Any

from v2_decision import SCHEMA_VERSION, V2_STATUS

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



@dataclass(frozen=True)
class WalkForwardSplit:
    train_start: float
    train_end: float
    calibration_start: float
    calibration_end: float
    holdout_start: float
    holdout_end: float








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








def validate_purged_embargo_splits(splits: list[WalkForwardSplit], *, embargo_span: float) -> None:
    """Raise if any split overlaps or violates the required embargo."""
    for split in splits:
        if not (split.train_start < split.train_end <= split.calibration_start < split.calibration_end):
            raise ValueError("walk-forward train/calibration windows overlap or are malformed")
        if split.holdout_start < split.calibration_end + embargo_span:
            raise ValueError("walk-forward split violates embargo before holdout")
        if not split.holdout_start < split.holdout_end:
            raise ValueError("walk-forward holdout window is malformed")














