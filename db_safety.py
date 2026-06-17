"""
Production SQLite safeguards: authorizer-based DROP denial, static SQL validation,
timestamped backups + manifests, single-writer preflight, and row-count invariants.

**Canonical DB connections** (``db_authority.is_canonical_db_path``) install
``sqlite3.Connection.set_authorizer`` to deny DROP/DETACH unless
``ED_CONSOLE_DANGEROUS_SQL_UNRESTRICTED=1``. Disable the hook with ``ED_CONSOLE_SQL_EXECUTE_GUARD=0``.

``validate_sql_for_production_guard`` blocks additional patterns (DELETE without WHERE,
``VACUUM INTO``, etc.) for audited scripts — not wired on every ORM-style execute.

**Backups**
- ``historical_backfill_enrolled_1m_v1`` (non-dry, canonical): copies to
  ``backups/db/YYYYMMDD_HHMMSS_ed_console.db`` + ``*_manifest.json`` unless
  ``ED_CONSOLE_SKIP_AUTOMATIC_BACKUP=1``.
- ``EdDB._migrate_schema``: same, **only when** at least one ``NEW_COLUMNS`` entry is missing
  from ``PRAGMA table_info(snapshots)`` (avoids full copy on every process start).

**Row counts**: ``assert_critical_row_counts_no_drop`` after migration / backfill bar writes.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from db_authority import is_canonical_db_path, project_root

DANGEROUS_SQL_UNRESTRICTED_ENV = "ED_CONSOLE_DANGEROUS_SQL_UNRESTRICTED"
SKIP_AUTOMATIC_BACKUP_ENV = "ED_CONSOLE_SKIP_AUTOMATIC_BACKUP"
SQL_EXECUTE_GUARD_ENV = "ED_CONSOLE_SQL_EXECUTE_GUARD"


class UnsafeSqlError(sqlite3.DatabaseError):
    """Raised when a guarded connection attempts disallowed SQL on the production DB."""


def dangerous_sql_unrestricted() -> bool:
    return os.environ.get(DANGEROUS_SQL_UNRESTRICTED_ENV, "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def skip_automatic_backup() -> bool:
    return os.environ.get(SKIP_AUTOMATIC_BACKUP_ENV, "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def sql_execute_guard_enabled() -> bool:
    v = os.environ.get(SQL_EXECUTE_GUARD_ENV, "1").strip().lower()
    return v not in ("0", "false", "no", "off")


def default_backup_root() -> Path:
    return (project_root() / "backups" / "db").resolve()


def preflight_exclusive_sqlite_write(db_path: Path, *, timeout_s: float = 30.0) -> tuple[bool, str | None]:
    """Try BEGIN IMMEDIATE; wait up to ``timeout_s`` before declaring the DB locked.

    DB-INIT FIX: was 2.0s — 15x shorter than the 30s busy_timeout every real connection
    uses (db.py configure_sqlite_connection). At startup, when the live logger or a
    concurrent retrain holds the write lock for >2s, this returned (False, 'database is
    locked'), the migration preflight raised RuntimeError, and the logger-universe bootstrap
    fell back to CORE+JSON — silently dropping the operator's pinned/user-persisted tickers
    for that boot (surfaced only as the 'db load failed' warning). Aligning to 30s lets a
    transient writer clear instead of spuriously failing the load.
    """
    db_path = Path(db_path).resolve()
    try:
        conn = sqlite3.connect(str(db_path), timeout=float(timeout_s))
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("COMMIT")
        finally:
            conn.close()
        return True, None
    except sqlite3.OperationalError as e:
        return False, str(e)
    except Exception as e:
        return False, str(e)


def critical_table_row_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Best-effort row counts for integrity checks (tables may be absent during bootstrap)."""
    candidates = (
        "snapshots",
        "price_bars_1m",
        "logging_universe",
        "ml_predictions",
        "ml_prediction_runs",
        "model_registry",
    )
    out: dict[str, int] = {}
    for t in candidates:
        try:
            row = conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()
            out[t] = int(row[0] if row is not None else 0)
        except sqlite3.Error:
            continue
    return out


def assert_critical_row_counts_no_drop(before: dict[str, int], after: dict[str, int]) -> None:
    """Hard-fail if any tracked table loses rows (bootstrap growth allowed for new keys)."""
    for k, b in before.items():
        a = int(after.get(k, 0))
        if a < int(b):
            raise RuntimeError(
                f"db_safety: critical row count dropped for {k}: before={b} after={a} "
                "(aborting to prevent silent data loss)"
            )


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def backup_console_database(
    source_db: Path,
    *,
    operation_name: str,
    backup_root: Path | None = None,
) -> tuple[Path, Path, dict[str, Any]]:
    """
    Copy ``source_db`` to ``backups/db/YYYYMMDD_HHMMSS_ed_console.db`` and write manifest JSON.

    Returns ``(backup_db_path, manifest_path, manifest_dict)``.
    """
    src = Path(source_db).resolve()
    if not src.is_file():
        raise FileNotFoundError(f"backup_console_database: source missing: {src}")
    root = Path(backup_root).resolve() if backup_root is not None else default_backup_root()
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dest = root / f"{stamp}_ed_console.db"
    manifest_path = root / f"{stamp}_manifest.json"
    if dest.resolve() == src.resolve():
        raise ValueError("backup destination cannot equal source path")

    shutil.copy2(src, dest)
    size_b = dest.stat().st_size
    sha = _sha256_file(dest)
    manifest: dict[str, Any] = {
        "source_db_path": str(src),
        "backup_db_path": str(dest),
        "file_size_bytes": size_b,
        "sha256": sha,
        "operation_name": operation_name,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "unix_ts": time.time(),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return dest, manifest_path, manifest


def _split_sql_statements(sql: str) -> list[str]:
    parts = [p.strip() for p in sql.split(";")]
    return [p for p in parts if p]


_RE_DROP = re.compile(r"(?is)\bDROP\s+(TABLE|INDEX|VIEW|TRIGGER)\b")
_RE_TRUNCATE = re.compile(r"(?is)\bTRUNCATE\b")
_RE_VACUUM_INTO = re.compile(r"(?is)\bVACUUM\s+INTO\b")
_RE_ALTER_DROP = re.compile(r"(?is)\bALTER\s+TABLE\b.+\bDROP\b")
_RE_DELETE_FROM = re.compile(r"(?is)\bDELETE\s+FROM\b")
_RE_WHERE = re.compile(r"(?is)\bWHERE\b")


def validate_sql_for_production_guard(sql: str) -> None:
    """
    Block obviously destructive patterns unless ``ED_CONSOLE_DANGEROUS_SQL_UNRESTRICTED=1``.

    Heuristic (not a full SQL parser): ``DELETE`` must contain the keyword ``WHERE``.
    """
    if dangerous_sql_unrestricted():
        return
    raw = (sql or "").strip()
    if not raw:
        return
    for stmt in _split_sql_statements(raw):
        s = stmt.strip()
        if not s or s.startswith("--"):
            continue
        up = s.upper()
        if up.startswith("PRAGMA"):
            continue
        if up.startswith("BEGIN") or up.startswith("COMMIT") or up.startswith("ROLLBACK"):
            continue
        if up.startswith("SAVEPOINT") or up.startswith("RELEASE"):
            continue
        if _RE_DROP.search(s):
            raise UnsafeSqlError("blocked: DROP TABLE/INDEX/VIEW/TRIGGER (set ED_CONSOLE_DANGEROUS_SQL_UNRESTRICTED=1 to override)")
        if _RE_TRUNCATE.search(s):
            raise UnsafeSqlError("blocked: TRUNCATE")
        if _RE_VACUUM_INTO.search(s):
            raise UnsafeSqlError("blocked: VACUUM INTO overwrite path")
        if _RE_ALTER_DROP.search(s):
            raise UnsafeSqlError("blocked: ALTER TABLE ... DROP ...")
        if _RE_DELETE_FROM.search(s) and not _RE_WHERE.search(s):
            raise UnsafeSqlError("blocked: DELETE without WHERE clause")


def install_production_sql_authorizer(conn: sqlite3.Connection) -> None:
    """
    SQLite authorizer hook: deny structural DROP / DETACH on guarded connections.

    Note: ``DELETE`` / ``UPDATE`` without ``WHERE`` cannot be distinguished reliably here;
    use ``validate_sql_for_production_guard`` for audited scripts or preflight review.
    """

    def _auth(action: int, arg1: str | None, arg2: str | None, db_name: str | None, inner: str | None) -> int:
        if dangerous_sql_unrestricted():
            return sqlite3.SQLITE_OK
        deny = {
            getattr(sqlite3, "SQLITE_DROP_TABLE", 10),
            getattr(sqlite3, "SQLITE_DROP_INDEX", 11),
            getattr(sqlite3, "SQLITE_DROP_VIEW", 12),
            getattr(sqlite3, "SQLITE_DROP_TRIGGER", 13),
            getattr(sqlite3, "SQLITE_DETACH", 23),
        }
        if action in deny:
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    conn.set_authorizer(_auth)


def maybe_install_sql_guard_on_connection(conn: sqlite3.Connection, db_path: Path) -> None:
    """Install SQL authorizer on canonical production DB connections."""
    if not is_canonical_db_path(db_path):
        return
    if not sql_execute_guard_enabled():
        return
    if dangerous_sql_unrestricted():
        return
    install_production_sql_authorizer(conn)


def refuse_canonical_db_path_as_shutil_destination(dest: Path) -> None:
    """
    Block ``shutil.copy*(..., canonical_ed_console.db)`` style overwrites unless explicitly ack'd.

    Restores should use SQLite backup API or ops-approved flows, not silent file replace.
    """
    d = Path(dest).resolve()
    if not is_canonical_db_path(d):
        return
    if dangerous_sql_unrestricted():
        return
    raise ValueError(
        f"refusing shutil-style write to canonical production DB path {d!r}. "
        "Use backups under backups/db/ or set ED_CONSOLE_DANGEROUS_SQL_UNRESTRICTED=1 with explicit ops sign-off."
    )


def migration_backup_if_canonical(db_path: Path, *, operation_name: str) -> tuple[Path, Path, dict[str, Any]] | None:
    """Backup + manifest before schema work on the canonical file."""
    if not is_canonical_db_path(db_path):
        return None
    if skip_automatic_backup():
        return None
    ok, err = preflight_exclusive_sqlite_write(db_path)
    if not ok:
        raise RuntimeError(f"db_safety: cannot acquire exclusive write lock for backup: {err}")
    return backup_console_database(db_path, operation_name=operation_name)


def bulk_operation_backup_if_canonical(db_path: Path, *, operation_name: str) -> tuple[Path, Path, dict[str, Any]] | None:
    """Same as migration backup hook; used before large bar backfills."""
    return migration_backup_if_canonical(db_path, operation_name=operation_name)
