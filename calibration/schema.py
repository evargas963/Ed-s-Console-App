"""
SQLite schema for calibration_decision_log — analysis-ready decision cycles.

Joined to snapshots on (ticker, ts_utc) for outcome backfill (see calibration.backfill_outcomes).

Producer insert surface: ``calibration.writer.append_calibration_decision`` writes 38 columns.
DDL defines additional columns (outcomes, id, created_at) filled by backfill, not the writer.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

log = logging.getLogger(__name__)

# DEFAULT '1m' must stay aligned with timeframe_config.CANONICAL_TIMEFRAME.
# calibration_trust DEFAULT 'legacy' must stay aligned with calibration.trust.CALIBRATION_TRUST_LEGACY.
CALIBRATION_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS calibration_decision_log (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_ts_utc         REAL    NOT NULL,
    ticker                  TEXT    NOT NULL,
    canonical_timeframe     TEXT    NOT NULL DEFAULT '1m',
    session_label           TEXT,
    expiry                  TEXT,
    build_generation        TEXT,

    zone                    TEXT,
    vwap_side               TEXT,
    nearest_above_dist      REAL,
    nearest_below_dist      REAL,
    structural_json         TEXT,

    regime_primary          TEXT,
    regime_confidence       TEXT,
    vol_regime              TEXT,
    vix_bucket              TEXT,
    session_bucket          TEXT,
    regime_json             TEXT,

    model_outputs_json      TEXT,
    monte_carlo_json        TEXT,
    fusion_json             TEXT,
    canonical_json          TEXT,

    final_signal            TEXT,
    call_conviction         TEXT,
    entry_price             REAL,
    stop_price              REAL,
    target_price            REAL,
    target2_price           REAL,
    validation_summary      TEXT,
    wait_blocker_json       TEXT,
    multi_horizon_json      TEXT,

    outcome_1c              TEXT,
    outcome_5c              TEXT,
    outcome_15c             TEXT,
    outcome_60c             TEXT,
    outcome_1c_pts          REAL,
    outcome_5c_pts          REAL,
    outcome_15c_pts         REAL,
    outcome_60c_pts         REAL,
    outcomes_attached_ts_utc REAL,

    matched_snapshot_ts_utc REAL,
    outcome_join_method     TEXT,

    -- 'trusted' = inserted after quarantine (production writer); 'legacy' = pre-milestone / unreviewed
    calibration_trust       TEXT    NOT NULL DEFAULT 'legacy',

    raw_bundle_json         TEXT,

    advisory_v2_decision_snapshot_json TEXT,
    advisory_v2_snapshot_schema_version TEXT,
    advisory_v2_adapter_version TEXT,
    advisory_v2_backfilled_ts_utc REAL,
    advisory_v2_backfill_status TEXT,
    advisory_v2_backfill_reason TEXT,

    created_at              TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_calib_outcome_pending
    ON calibration_decision_log(ticker)
    WHERE outcome_5c IS NULL AND calibration_trust = 'trusted';
"""

# Developer-controlled column names only (ALTER TABLE ADD COLUMN {name} {decl}).
_CALIBRATION_OPTIONAL_COLUMNS: dict[str, str] = {
    "matched_snapshot_ts_utc": "REAL",
    "outcome_join_method": "TEXT",
    "calibration_trust": "TEXT NOT NULL DEFAULT 'legacy'",
    "advisory_v2_decision_snapshot_json": "TEXT",
    "advisory_v2_snapshot_schema_version": "TEXT",
    "advisory_v2_adapter_version": "TEXT",
    "advisory_v2_backfilled_ts_utc": "REAL",
    "advisory_v2_backfill_status": "TEXT",
    "advisory_v2_backfill_reason": "TEXT",
    # Track B (v2.1) provenance — distinguishes Pass 3 forward-rate live writes
    # from Track B historical INSERTs reconstructed from snapshot rows. Backfilled
    # rows carry decision_source='reconstructed_from_snapshot'; live writer rows
    # leave it NULL (default). Used by training-skew analysis to optionally
    # exclude reconstructed rows from model calibration.
    "decision_source": "TEXT",
    # execution_identity_v1 (PER_ROW_HISTORICAL_MODEL_ARTIFACT_IDENTITY_V1):
    # immutable decision-cycle linkage; enforced against
    # model_execution_identities + decision_persistence_ledger by triggers on
    # the production DB (see execution_identity.py). Legacy rows stay NULL.
    "decision_id": "TEXT",
    "execution_identity_sha256": "TEXT",
}


def _migrate_calibration_unique_ticker_decision_ts(conn: sqlite3.Connection) -> None:
    """
    One row per (ticker, decision_ts_utc): dedupe legacy duplicates, then enforce UNIQUE.

    Dedupe keeps MIN(id) per (ticker, decision_ts_utc) — oldest row wins; newer duplicates
    are deleted (destructive). Emits a warning when any rows are removed.

    DELETE and CREATE UNIQUE INDEX run in one BEGIN IMMEDIATE transaction.

    Idempotent: skips if uq_calib_ticker_decision_ts_utc already exists.
    """
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name='uq_calib_ticker_decision_ts_utc'"
    ).fetchone()
    if row:
        return
    try:
        conn.execute("DROP INDEX IF EXISTS idx_calib_ticker_ts")
    except sqlite3.Error as e:
        log.warning(
            "calibration schema: DROP INDEX idx_calib_ticker_ts failed (continuing): %s",
            e,
        )
    conn.execute("BEGIN IMMEDIATE")
    try:
        cur = conn.execute(
            """
            DELETE FROM calibration_decision_log
            WHERE id NOT IN (
                SELECT MIN(id) FROM calibration_decision_log GROUP BY ticker, decision_ts_utc
            )
            """
        )
        n_deleted = int(cur.rowcount)
        if n_deleted > 0:
            log.warning(
                "calibration schema: removed %d duplicate calibration_decision_log row(s) "
                "(kept oldest id per ticker, decision_ts_utc)",
                n_deleted,
            )
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_calib_ticker_decision_ts_utc
            ON calibration_decision_log(ticker, decision_ts_utc)
            """
        )
        conn.commit()
    except sqlite3.Error:
        conn.rollback()
        raise


def _migrate_calibration_decision_log_columns(conn: sqlite3.Connection) -> None:
    cur = conn.execute("PRAGMA table_info(calibration_decision_log)")
    cols = {row[1] for row in cur.fetchall()}
    for name, decl in _CALIBRATION_OPTIONAL_COLUMNS.items():
        if name not in cols:
            conn.execute(f"ALTER TABLE calibration_decision_log ADD COLUMN {name} {decl}")
    conn.commit()


def _migrate_calibration_pending_index(conn: sqlite3.Connection) -> None:
    """
    Prefer partial index covering trusted pending rows only (backfill + studies).

    DROP then CREATE allows evolving the partial-index WHERE clause on upgrade; brief
    scan window during migration is acceptable (startup-only path).
    """
    cur = conn.execute("PRAGMA table_info(calibration_decision_log)")
    cols = {row[1] for row in cur.fetchall()}
    if "calibration_trust" not in cols:
        return
    conn.execute("DROP INDEX IF EXISTS idx_calib_outcome_pending")
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_calib_outcome_pending
            ON calibration_decision_log(ticker)
            WHERE outcome_5c IS NULL AND calibration_trust = 'trusted'
        """
    )
    conn.commit()


def ensure_calibration_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(CALIBRATION_TABLE_SQL)
    conn.commit()
    _migrate_calibration_decision_log_columns(conn)
    _migrate_calibration_unique_ticker_decision_ts(conn)
    _migrate_calibration_pending_index(conn)


def ensure_calibration_schema_at_path(db_path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    ensure_calibration_schema(conn)
    return conn
