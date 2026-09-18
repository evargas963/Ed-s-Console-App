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


class CalibrationSchemaNotMigratedError(RuntimeError):
    """Raised when a database lacks `research_excluded`, so operability cannot be proven.

    No-fallback lock repair (2026-09-18, PR #254 point 4): a missing column used to
    silently degrade `operable_filter_sql` to `1=1` -- treating an UNKNOWN operability
    state as UNIVERSAL ELIGIBILITY, the exact "missing schema means everything passes"
    shape the mission prohibits. Root-cause trace: `research_excluded` is migrated
    unconditionally by `db.py`'s own startup path (`ensure_calibration_schema` runs
    inside `EdDB`'s migration sequence, calibration/schema.py:_CALIBRATION_OPTIONAL_COLUMNS),
    so any database ever opened through the canonical EdDB/db.py path already has this
    column by construction -- this branch is reachable only by (a) a bare connection that
    bypassed the canonical schema (a test-fixture bug, not a production state) or (b) a
    genuinely foreign/pre-migration database file (e.g. an old backup) whose rows have
    never been vetted for research-operability at all. Neither case may be silently
    treated as 'everything is operable' -- the caller must migrate the database (see
    `calibration.schema.ensure_calibration_schema`) or accept that operability is
    unproven for this connection.
    """


def _has_col(conn: sqlite3.Connection, table: str, col: str) -> bool:
    return col in {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def operable_filter_sql(conn: sqlite3.Connection) -> str:
    """The ONE definition of 'this calibration row is operable for research'.

    Raises `CalibrationSchemaNotMigratedError` if `research_excluded` is absent --
    every real production database has this column by the time db.py finishes its own
    startup migrations (see the error's docstring for the full trace); a database that
    still lacks it has never been vetted for research-operability, so returning `1=1`
    would silently assert "every row is clean" about data nobody has ever excluded
    anything from. This predicate was copy-pasted into four places (the gate tool and
    the three research runners); the runners' unguarded copies raised
    `sqlite3.OperationalError: no such column: research_excluded` on fixture DBs. One
    definition, guarded, consumed everywhere -- callers that want fixture convenience
    must call `calibration.schema.ensure_calibration_schema` on their connection first,
    not rely on this function to paper over an unmigrated schema.
    """
    if _has_col(conn, "calibration_decision_log", "research_excluded"):
        # Fallback lock (2026-09-17): the COALESCE here was provably-redundant defensive
        # code, not a real fallback -- this branch runs ONLY when the column already
        # exists, and the ONE writer that ever creates it (quarantine_old_unattached below)
        # always does so via "ALTER TABLE ... ADD COLUMN research_excluded INTEGER NOT NULL
        # DEFAULT 0", which SQLite backfills onto every pre-existing row and enforces going
        # forward -- NULL is structurally impossible once _has_col() is true.
        return "research_excluded=0"
    raise CalibrationSchemaNotMigratedError(
        "calibration_decision_log.research_excluded is absent -- this connection's "
        "database has never been migrated by calibration.schema.ensure_calibration_schema, "
        "so no row's research-operability has ever been established. Call "
        "ensure_calibration_schema(conn) (or ensure_calibration_schema_at_path(db_path)) "
        "before querying operability, or treat this database as un-vetted -- never assume "
        "every row is operable."
    )


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
              AND research_excluded=0
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
