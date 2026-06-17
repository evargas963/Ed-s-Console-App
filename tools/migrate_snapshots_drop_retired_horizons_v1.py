#!/usr/bin/env python3
"""Drop retired 3c/8c/13c snapshot columns via explicit-DDL rebuild (dry-run default)."""

from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from calibration.paths import DEFAULT_DB, PROJECT_ROOT  # noqa: E402

log = logging.getLogger(__name__)

SCHEMA = "migrate_snapshots_drop_retired_horizons_v1"
FLAG_KEY = "snapshots_drop_retired_horizons_v1"

_RETIRED_HORIZONS: tuple[str, ...] = ("3c", "8c", "13c")


def _build_retired_columns() -> tuple[str, ...]:
    """All snapshot columns tied to retired 3c/8c/13c product horizons (69 total)."""
    cols: list[str] = []
    for hz in _RETIRED_HORIZONS:
        cols.extend(
            (
                f"pred_{hz}_up_prob",
                f"pred_{hz}_down_prob",
                f"pred_{hz}_flat_prob",
                f"outcome_{hz}",
                f"outcome_{hz}_pts",
                f"outcome_dir_{hz}",
                f"outcome_move_{hz}",
                f"valid_dir_{hz}",
                f"threshold_move_{hz}",
                f"outcome_move_thr_pts_{hz}",
                f"pred_{hz}_dir_up_prob",
                f"pred_{hz}_dir_down_prob",
                f"pred_{hz}_move_prob",
                f"pred_{hz}_no_move_prob",
                f"pred_dir_up_prob_{hz}",
                f"pred_dir_down_prob_{hz}",
                f"pred_move_prob_{hz}",
                f"pred_no_move_prob_{hz}",
                f"fused_move_prob_{hz}",
                f"fused_dir_up_prob_{hz}",
                f"fused_confidence_{hz}",
                f"fused_contributing_models_{hz}",
                f"fused_stack_status_{hz}",
            )
        )
    return tuple(cols)


RETIRED_COLUMNS: tuple[str, ...] = _build_retired_columns()
assert len(RETIRED_COLUMNS) == 69, f"expected 69 retired columns, got {len(RETIRED_COLUMNS)}"
assert len(RETIRED_COLUMNS) == len(set(RETIRED_COLUMNS)), "duplicate retired column slug"
RETIRED_SET = frozenset(RETIRED_COLUMNS)

AUDIT_EXPECTED_KEYS = frozenset(
    {
        "db_path",
        "mode",
        "sqlite_version",
        "columns_before",
        "columns_after",
        "columns_dropped",
        "row_count_before",
        "row_count_after",
        "integrity_check",
        "flag_state",
        "ddl_column_delta",
        "already_applied",
        "audit_ts_utc",
    }
)


def run(
    db_path: Path,
    *,
    apply: bool = False,
    backup_root: Path | None = None,
    audit_root: Path | None = None,
) -> dict[str, Any]:
    db_path = Path(db_path).resolve()
    mode = "apply" if apply else "dry_run"
    sqlite_version = ".".join(str(x) for x in sqlite3.sqlite_version_info)
    log.info(
        "snapshots_drop_retired_horizons_v1: sqlite_version=%s mode=%s db=%s",
        sqlite_version,
        mode,
        db_path,
    )
    if sqlite3.sqlite_version_info < (3, 35, 0):
        log.warning(
            "SQLite %s < 3.35.0 — rebuild path required (DROP COLUMN not used regardless)",
            sqlite_version,
        )

    audit: dict[str, Any] = {
        "schema": SCHEMA,
        "db_path": str(db_path),
        "mode": mode,
        "sqlite_version": sqlite_version,
        "columns_before": [],
        "columns_after": [],
        "columns_dropped": [],
        "row_count_before": 0,
        "row_count_after": 0,
        "integrity_check": None,
        "flag_state": {
            "flag_key": FLAG_KEY,
            "present_before": False,
            "present_after": False,
        },
        "ddl_column_delta": 0,
        "already_applied": False,
        "audit_ts_utc": datetime.now(timezone.utc).isoformat(),
        "success": False,
        "status": None,
        "errors": [],
    }

    if not db_path.is_file():
        return _fail(audit, "db_missing", f"DB path does not exist: {db_path}")

    audit_path = _write_audit_skeleton(audit, audit_root=audit_root)

    with _connect(db_path) as conn:
        _ensure_ed_schema_flags(conn)
        flag_before = _flag_value(conn)
        audit["flag_state"]["present_before"] = flag_before is not None
        audit["integrity_check"] = _integrity_check(conn)

        if not _table_exists(conn, "snapshots"):
            return _fail(audit, "snapshots_missing", "snapshots table does not exist", audit_path)

        cols_before = _column_names(conn, "snapshots")
        audit["columns_before"] = cols_before
        retired_present = [c for c in RETIRED_COLUMNS if c in cols_before]
        audit["columns_dropped"] = retired_present
        row_before = _snapshot_row_count(conn)
        audit["row_count_before"] = row_before

        if flag_before is not None:
            audit["already_applied"] = True
            audit["columns_after"] = cols_before
            audit["row_count_after"] = row_before
            audit["ddl_column_delta"] = 0
            audit["flag_state"]["present_after"] = True
            audit["status"] = "already_applied"
            audit["success"] = True
            _finalize_audit(audit, audit_path)
            return audit

        if not retired_present:
            audit["columns_after"] = cols_before
            audit["row_count_after"] = row_before
            audit["ddl_column_delta"] = 0
            audit["status"] = "noop_no_retired_columns"
            audit["success"] = True
            _finalize_audit(audit, audit_path)
            return audit

        cols_after_projected = [c for c in cols_before if c not in RETIRED_SET]
        audit["columns_after"] = cols_after_projected
        audit["ddl_column_delta"] = len(cols_after_projected) - len(cols_before)
        audit["row_count_after"] = row_before

        if not apply:
            audit["status"] = "dry_run"
            audit["success"] = True
            audit["would_apply"] = True
            _finalize_audit(audit, audit_path)
            return audit

    from db_safety import (
        assert_critical_row_counts_no_drop,
        backup_console_database,
        critical_table_row_counts,
        preflight_exclusive_sqlite_write,
        skip_automatic_backup,
    )

    ok, err = preflight_exclusive_sqlite_write(db_path)
    if not ok:
        return _fail(audit, "preflight_write_lock_failed", err or "exclusive write preflight failed", audit_path)

    with _connect(db_path) as _pre:
        counts_before = critical_table_row_counts(_pre)
    backup_meta: dict[str, Any] | None = None
    if not skip_automatic_backup():
        _backup_root = Path(backup_root).resolve() if backup_root is not None else None
        _backup_db, _manifest_path, manifest = backup_console_database(
            db_path,
            operation_name=SCHEMA,
            backup_root=_backup_root,
        )
        audit["backup_db_path"] = str(_backup_db)
        audit["backup_manifest_path"] = str(_manifest_path)
        backup_meta = manifest

    indexes_before: dict[str, str] = {}
    try:
        with _connect(db_path) as conn:
            indexes_before = _index_sql(conn, "snapshots")
            conn.execute("BEGIN IMMEDIATE")
            try:
                _rebuild_snapshots_drop_retired(conn)
                _set_flag(conn, FLAG_KEY)
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
    except Exception as e:
        return _fail(audit, "migration_apply_failed", str(e), audit_path)

    with _connect(db_path) as _post_count:
        counts_after = critical_table_row_counts(_post_count)
    try:
        assert_critical_row_counts_no_drop(counts_before, counts_after)
    except RuntimeError as e:
        return _fail(audit, "row_count_invariant_failed", str(e), audit_path)

    with _connect(db_path) as conn:
        audit["integrity_check"] = _integrity_check(conn)
        if audit["integrity_check"] != "ok":
            return _fail(audit, "integrity_check_failed_post", "PRAGMA integrity_check failed after migration", audit_path)
        cols_after = _column_names(conn, "snapshots")
        audit["columns_after"] = cols_after
        audit["row_count_after"] = _snapshot_row_count(conn)
        flag_after = _flag_value(conn)
        audit["flag_state"]["present_after"] = flag_after is not None
        audit["ddl_column_delta"] = len(cols_after) - len(audit["columns_before"])
        still_present = [c for c in RETIRED_COLUMNS if c in cols_after]
        if still_present:
            return _fail(
                audit,
                "retired_columns_remain",
                f"columns still present after apply: {still_present}",
                audit_path,
            )
        for sql in indexes_before.values():
            conn.execute(sql)

    audit["status"] = "applied"
    audit["success"] = True
    if backup_meta is not None:
        audit["backup_operation"] = backup_meta.get("operation_name")
    _finalize_audit(audit, audit_path)
    return audit


def _rebuild_snapshots_drop_retired(conn: sqlite3.Connection) -> None:
    live_cols = [_column_dict(r) for r in _table_info(conn, "snapshots")]
    kept = [c for c in live_cols if c["name"] not in RETIRED_SET]
    if len(kept) == len(live_cols):
        return
    kept_names = [c["name"] for c in kept]
    conn.execute("DROP TABLE IF EXISTS snapshots_new")
    conn.execute(_create_table_sql("snapshots_new", kept))
    insert_cols = ", ".join(_quote_ident(n) for n in kept_names)
    select_cols = insert_cols
    row_count = int(conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0])
    conn.execute(
        f"INSERT INTO snapshots_new ({insert_cols}) SELECT {select_cols} FROM snapshots"
    )
    new_count = int(conn.execute("SELECT COUNT(*) FROM snapshots_new").fetchone()[0])
    if new_count != row_count:
        raise RuntimeError(f"snapshots rebuild row parity failed: before={row_count} after={new_count}")
    conn.execute("DROP TABLE snapshots")
    conn.execute("ALTER TABLE snapshots_new RENAME TO snapshots")


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=60.0)
    conn.row_factory = sqlite3.Row
    try:
        from db import configure_sqlite_connection

        configure_sqlite_connection(conn)
    except Exception:
        conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _table_info(conn: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
    return conn.execute(f"PRAGMA table_info({table})").fetchall()


def _column_names(conn: sqlite3.Connection, table: str) -> list[str]:
    return [str(r["name"]) for r in _table_info(conn, table)]


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def _snapshot_row_count(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0])


def _integrity_check(conn: sqlite3.Connection) -> str:
    row = conn.execute("PRAGMA integrity_check").fetchone()
    return str(row[0] if row else "")


def _ensure_ed_schema_flags(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ed_schema_flags (
            flag_key TEXT PRIMARY KEY,
            flag_value TEXT NOT NULL,
            set_ts_utc REAL NOT NULL
        )
        """
    )


def _flag_value(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT flag_value FROM ed_schema_flags WHERE flag_key = ?",
        (FLAG_KEY,),
    ).fetchone()
    return str(row[0]) if row is not None else None


def _set_flag(conn: sqlite3.Connection, flag_key: str) -> None:
    conn.execute(
        """
        INSERT INTO ed_schema_flags (flag_key, flag_value, set_ts_utc)
        VALUES (?, ?, ?)
        ON CONFLICT(flag_key) DO UPDATE SET flag_value=excluded.flag_value, set_ts_utc=excluded.set_ts_utc
        """,
        (flag_key, "1", time.time()),
    )


def _column_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "name": str(row["name"]),
        "type": str(row["type"] or "TEXT"),
        "notnull": int(row["notnull"] or 0),
        "dflt_value": row["dflt_value"],
        "pk": int(row["pk"] or 0),
    }


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _column_definition(col: dict[str, Any]) -> str:
    name = str(col["name"])
    if name == "snapshot_id" and int(col["pk"] or 0) == 1:
        return "snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT"
    ctype = str(col["type"] or "TEXT").strip() or "TEXT"
    parts = [_quote_ident(name), ctype]
    if int(col["notnull"] or 0):
        parts.append("NOT NULL")
    default = col["dflt_value"]
    if default is not None:
        default_sql = str(default)
        if "(" in default_sql and not default_sql.strip().startswith("("):
            default_sql = f"({default_sql})"
        parts.extend(["DEFAULT", default_sql])
    return " ".join(parts)


def _create_table_sql(table: str, cols: list[dict[str, Any]]) -> str:
    defs = [_column_definition(c) for c in cols]
    return f"CREATE TABLE {_quote_ident(table)} (\n    " + ",\n    ".join(defs) + "\n)"


def _index_sql(conn: sqlite3.Connection, table: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in conn.execute(f"PRAGMA index_list({table})").fetchall():
        name = str(row["name"])
        if name.startswith("sqlite_autoindex"):
            continue
        sql_row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND name = ?",
            (name,),
        ).fetchone()
        if sql_row and sql_row["sql"]:
            out[name] = str(sql_row["sql"])
    return out


def _write_audit_skeleton(audit: dict[str, Any], *, audit_root: Path | None) -> Path:
    root = Path(audit_root).resolve() if audit_root is not None else (PROJECT_ROOT / "governance" / "audits")
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = root / f"snapshots_schema_drop_retired_horizons_v1_{stamp}.json"
    audit["audit_path"] = str(path)
    return path


def _finalize_audit(audit: dict[str, Any], audit_path: Path) -> None:
    audit_path.write_text(json.dumps(audit, indent=2, default=str), encoding="utf-8")


def _fail(
    audit: dict[str, Any],
    status: str,
    message: str,
    audit_path: Path | None = None,
) -> dict[str, Any]:
    audit["success"] = False
    audit["status"] = status
    audit.setdefault("errors", []).append(message)
    if audit_path is not None:
        _finalize_audit(audit, audit_path)
    return audit


def main(argv: list[str] | None = None) -> int:
    from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target

    ap = argparse.ArgumentParser(
        description="Drop retired 3c/8c/13c columns from snapshots (rebuild dance). Default: dry-run."
    )
    ap.add_argument("--db", type=Path, default=DEFAULT_DB, help="SQLite database path")
    ap.add_argument("--apply", action="store_true", help="Mutate DB (backup + rebuild + flag)")
    ap.add_argument("--backup-root", type=Path, default=None, help="Override backups/db root")
    ap.add_argument("--audit-root", type=Path, default=None, help="Override governance/audits output dir")
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args(argv)
    require_canonical_db_target(
        args,
        tool_name=SCHEMA,
        write_capable=bool(args.apply),
    )
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    out = run(
        args.db,
        apply=bool(args.apply),
        backup_root=args.backup_root,
        audit_root=args.audit_root,
    )
    print(json.dumps(out, indent=2, default=str))
    return 0 if out.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
