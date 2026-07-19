"""Quarantine writer for irrecoverable calibration rows — the ONLY write path for
`research_excluded` on `calibration_decision_log`.

Lives in `calibration/` deliberately. `calibration_decision_log` has a controlled write
surface enforced by `tests/test_calibration_bypass_closure.py`; this function previously
sat in `tools/operable_surface_gate.py`, which made a CLI tool an unaudited writer to the
production table (it ALTERed the schema and UPDATEd rows, defaulting to the production DB).
Moved 2026-07-19 so the gate tool stays read-only and every write to this table remains
inside the audited surface.

The gate tool imports this; behaviour is unchanged.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

#: Rows older than this with no joinable snapshot outcome are irrecoverable.
OLD_AGE_SEC = 70 * 60
QUARANTINE_REASON = "IRRECOVERABLE_NO_JOINABLE_SNAPSHOT_OUTCOME_V1"


def _has_col(conn: sqlite3.Connection, table: str, col: str) -> bool:
    return col in {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def operable_filter_sql(conn: sqlite3.Connection) -> str:
    """The ONE definition of 'this calibration row is operable for research'.

    `research_excluded` is created lazily by quarantine_old_unattached, so it is absent
    from any database that has never been quarantined — including every test fixture DB.
    Callers must therefore degrade to '1=1' rather than emit SQL referencing a column that
    may not exist. This predicate was copy-pasted into four places (the gate tool and the
    three research runners); the runners' unguarded copies raised
    `sqlite3.OperationalError: no such column: research_excluded` on fixture DBs. One
    definition, guarded, consumed everywhere.
    """
    if _has_col(conn, "calibration_decision_log", "research_excluded"):
        return "COALESCE(research_excluded,0)=0"
    return "1=1"


def quarantine_old_unattached(
    db_path: Path,
    *,
    now_utc: float | None = None,
    reason: str = QUARANTINE_REASON,
) -> dict[str, Any]:
    """Mark remaining old operable unattached rows research_excluded=1."""
    now = float(now_utc if now_utc is not None else time.time())
    old_cut = now - OLD_AGE_SEC
    conn = sqlite3.connect(str(db_path), timeout=60.0)
    conn.row_factory = sqlite3.Row
    try:
        from db import configure_sqlite_connection

        configure_sqlite_connection(conn)
    except Exception:
        # institutional-swallow-ok: sqlite pragma tuning is best-effort; the connection
        # works with defaults if configuration is unavailable.
        pass
    try:
        if not _has_col(conn, "calibration_decision_log", "research_excluded"):
            conn.execute(
                "ALTER TABLE calibration_decision_log "
                "ADD COLUMN research_excluded INTEGER NOT NULL DEFAULT 0"
            )
        if not _has_col(conn, "calibration_decision_log", "research_exclude_reason"):
            conn.execute(
                "ALTER TABLE calibration_decision_log "
                "ADD COLUMN research_exclude_reason TEXT"
            )
        cur = conn.execute(
            """
            UPDATE calibration_decision_log
            SET research_excluded=1,
                research_exclude_reason=?
            WHERE calibration_trust='trusted'
              AND COALESCE(research_excluded,0)=0
              AND decision_ts_utc < ?
              AND matched_snapshot_ts_utc IS NULL
            """,
            (reason, old_cut),
        )
        n = int(cur.rowcount)
        conn.commit()
        return {"quarantined": n, "reason": reason, "old_cut_utc": old_cut}
    finally:
        conn.close()
