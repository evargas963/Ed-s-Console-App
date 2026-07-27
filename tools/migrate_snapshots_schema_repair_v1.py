#!/usr/bin/env python3
"""Repair drifted snapshots identity schema.

Default mode is dry-run. Use --apply for production writes.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from calibration.paths import DEFAULT_DB  # noqa: E402
from snapshot_normalizer import materialize_normalized_table, validate_normalization  # noqa: E402


REQUIRED_INDEXES = {
    "idx_snap_ticker_tf_ts": "CREATE INDEX IF NOT EXISTS idx_snap_ticker_tf_ts ON snapshots(ticker, timeframe, ts_utc)",
    "idx_snap_outcome_unfilled": (
        "CREATE INDEX IF NOT EXISTS idx_snap_outcome_unfilled "
        "ON snapshots(ticker, timeframe, outcome_filled) WHERE outcome_filled = 0"
    ),
    "idx_snap_ts": "CREATE INDEX IF NOT EXISTS idx_snap_ts ON snapshots(ts_utc)",
}

_CANONICAL_SNAPSHOTS_COLUMNS: list[dict[str, Any]] | None = None


def run(db_path: Path, *, apply: bool = False, backup_root: Path | None = None) -> dict[str, Any]:
    db_path = Path(db_path).resolve()
    backup_root = Path(backup_root or ROOT / "backups" / "db").resolve()
    audit: dict[str, Any] = {
        "schema": "migrate_snapshots_schema_repair_v1",
        "db_path": str(db_path),
        "apply": bool(apply),
        "status": None,
        "errors": [],
    }
    if not db_path.is_file():
        return _fail(audit, "db_missing", f"DB path does not exist: {db_path}")

    with _connect(db_path) as conn:
        audit["pre_integrity_check"] = _integrity_check(conn)
        if audit["pre_integrity_check"] != "ok":
            return _fail(audit, "integrity_check_failed_pre", "PRAGMA integrity_check failed before migration")

        snapshots_probe = _snapshot_schema_probe(conn, "snapshots")
        audit["snapshots_schema_before"] = snapshots_probe
        audit["counts_before"] = _counts(conn)
        audit["id_assignment_preview"] = _id_assignment_preview(conn)
        audit["collision_count"] = _collision_count(conn)
        audit["indexes_before"] = _index_sql(conn, "snapshots")

        target_cols = _merged_target_columns(conn)
        target_normalized_cols = _normalized_target_columns(target_cols)
        audit["target_column_count"] = len(target_cols)
        audit["target_extra_live_columns"] = [
            c["name"] for c in target_cols if c["source"] == "live_extra"
        ]

        if (
            audit["counts_before"]["snapshots_null_snapshot_id"] == 0
            and _table_matches_columns(conn, "snapshots", target_cols)
            and _table_matches_columns(conn, "snapshots_1m_normalized", target_normalized_cols)
        ):
            audit["idempotence"] = "already_repaired"
            audit["status"] = "noop_already_repaired"
            return _success(audit)

        refusal = _preflight_refusal(audit)
        if refusal:
            return _fail(audit, refusal[0], refusal[1])

        if not apply:
            audit["status"] = "dry_run"
            audit["would_apply"] = True
            return _success(audit)

    backup_path = _backup_database(db_path, backup_root)
    audit["backup_path"] = str(backup_path)

    try:
        with _connect(db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                _migrate_snapshots(conn, audit)
                _rebuild_normalized_schema(conn)
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
    except Exception as e:
        return _fail(audit, "migration_apply_failed", str(e))

    normalized_result: dict[str, Any] | None = None
    normalized_validation: dict[str, Any] | None = None
    try:
        normalized_result = materialize_normalized_table(db_path, tickers=None, clear_first=False)
        normalized_validation = validate_normalization(db_path)
    except Exception as e:
        return _fail(audit, "normalized_rebuild_failed", str(e))
    audit["normalized_rebuild"] = normalized_result
    audit["normalized_validation"] = normalized_validation
    if normalized_result.get("errors"):
        return _fail(audit, "normalized_materialize_errors", str(normalized_result.get("errors")))
    if not normalized_validation.get("ok"):
        return _fail(audit, "normalized_validation_failed", str(normalized_validation.get("errors")))

    with _connect(db_path) as conn:
        audit["post_integrity_check"] = _integrity_check(conn)
        audit["counts_after"] = _counts(conn)
        audit["snapshots_schema_after"] = _snapshot_schema_probe(conn, "snapshots")
        audit["normalized_schema_after"] = _snapshot_schema_probe(conn, "snapshots_1m_normalized")
        audit["indexes_after"] = _index_sql(conn, "snapshots")
        if audit["post_integrity_check"] != "ok":
            return _fail(audit, "integrity_check_failed_post", "PRAGMA integrity_check failed after migration")
        _assert_post_conditions(conn, audit)

    audit["status"] = "applied"
    return _success(audit)


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        from db import configure_sqlite_connection

        configure_sqlite_connection(conn)
    except Exception:
        conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _integrity_check(conn: sqlite3.Connection) -> str:
    row = conn.execute("PRAGMA integrity_check").fetchone()
    return str(row[0] if row else "")


def _table_info(conn: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
    return conn.execute(f"PRAGMA table_info({table})").fetchall()


def _column_dict(row: sqlite3.Row | dict[str, Any], *, source: str) -> dict[str, Any]:
    return {
        "cid": int(row["cid"]) if "cid" in row.keys() else 0,
        "name": str(row["name"]),
        "type": str(row["type"] or ""),
        "notnull": int(row["notnull"] or 0),
        "dflt_value": row["dflt_value"],
        "pk": int(row["pk"] or 0),
        "source": source,
    }


def _canonical_snapshots_columns() -> list[dict[str, Any]]:
    """Build canonical snapshots schema by running db.py schema init on a temp DB."""
    global _CANONICAL_SNAPSHOTS_COLUMNS
    if _CANONICAL_SNAPSHOTS_COLUMNS is not None:
        return [dict(c) for c in _CANONICAL_SNAPSHOTS_COLUMNS]

    temp_root = Path(tempfile.gettempdir()) / "ed_console_schema_repair"
    temp_root.mkdir(exist_ok=True)
    temp_db = temp_root / f"canonical_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')}.db"
    from db import EdDB

    EdDB(temp_db, allow_noncanonical=True)
    conn = sqlite3.connect(str(temp_db))
    conn.row_factory = sqlite3.Row
    try:
        cols = [_column_dict(r, source="db_py") for r in _table_info(conn, "snapshots")]
        _CANONICAL_SNAPSHOTS_COLUMNS = [dict(c) for c in cols]
        return cols
    finally:
        conn.close()
        for suffix in ("", "-wal", "-shm"):
            try:
                temp_db.with_name(temp_db.name + suffix).unlink(missing_ok=True)
            except PermissionError:
                pass


def _merged_target_columns(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    canonical = _canonical_snapshots_columns()
    live = [_column_dict(r, source="live") for r in _table_info(conn, "snapshots")]
    _live_by_name = {c["name"]: c for c in live}
    canonical_names = {c["name"] for c in canonical}
    merged = [dict(c) for c in canonical]
    merged.extend({**c, "source": "live_extra"} for c in live if c["name"] not in canonical_names)
    return merged


def _normalized_target_columns(snapshot_cols: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cols = [dict(c) for c in snapshot_cols]
    if "normalized_from_subminute" not in {c["name"] for c in cols}:
        cols.append(
            {
                "cid": len(cols),
                "name": "normalized_from_subminute",
                "type": "INTEGER",
                "notnull": 1,
                "dflt_value": "0",
                "pk": 0,
                "source": "migration",
            }
        )
    return cols


def _table_matches_columns(
    conn: sqlite3.Connection, table: str, expected_cols: list[dict[str, Any]]
) -> bool:
    actual = [_column_dict(r, source="actual") for r in _table_info(conn, table)]
    if len(actual) != len(expected_cols):
        return False
    for a, e in zip(actual, expected_cols):
        if a["name"] != e["name"]:
            return False
        if _norm_decl_type(a["type"]) != _norm_decl_type(e["type"]):
            return False
        if int(a["pk"]) != int(e["pk"]):
            return False
        if int(a["notnull"]) != int(e["notnull"]):
            return False
        if _norm_default(a["dflt_value"]) != _norm_default(e["dflt_value"]):
            return False
    return True


def _norm_decl_type(value: Any) -> str:
    return " ".join(str(value or "").upper().split())


def _norm_default(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text.startswith("(") and text.endswith(")"):
        text = text[1:-1].strip()
    return " ".join(text.split())


def _snapshot_schema_probe(conn: sqlite3.Connection, table: str) -> dict[str, Any]:
    cols = _table_info(conn, table)
    first = cols[0] if cols else None
    sql_row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name = ?",
        (table,),
    ).fetchone()
    first_type = str(first["type"] or "").upper() if first else ""
    first_pk = int(first["pk"] or 0) if first else 0
    return {
        "table": table,
        "exists": bool(cols),
        "first_column": first["name"] if first else None,
        "first_type": first_type,
        "first_pk": first_pk,
        "sqlite_master_sql": sql_row["sql"] if sql_row else None,
        "is_repaired": bool(first and first["name"] == "snapshot_id" and first_type == "INTEGER" and first_pk == 1),
    }


def _counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {
        "snapshots": int(conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]),
        "snapshots_null_snapshot_id": int(
            conn.execute("SELECT COUNT(*) FROM snapshots WHERE snapshot_id IS NULL").fetchone()[0]
        ),
        "snapshots_distinct_snapshot_id": int(
            conn.execute("SELECT COUNT(DISTINCT snapshot_id) FROM snapshots WHERE snapshot_id IS NOT NULL").fetchone()[0]
        ),
        "normalized": int(
            conn.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='snapshots_1m_normalized'"
            ).fetchone()[0]
            and conn.execute("SELECT COUNT(*) FROM snapshots_1m_normalized").fetchone()[0]
        ),
    }


def _id_assignment_preview(conn: sqlite3.Connection) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT
            COALESCE(MAX(snapshot_id), 0) AS max_snapshot_id,
            COUNT(*) AS total,
            SUM(CASE WHEN snapshot_id IS NULL THEN 1 ELSE 0 END) AS null_count
        FROM snapshots
        """
    ).fetchone()
    max_id = int(row["max_snapshot_id"] or 0)
    null_count = int(row["null_count"] or 0)
    return {
        "max_existing_snapshot_id": max_id,
        "null_count": null_count,
        "first_new_snapshot_id": max_id + 1 if null_count else None,
        "last_new_snapshot_id": max_id + null_count if null_count else None,
        "total_rows": int(row["total"] or 0),
    }


def _collision_count(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*)
        FROM snapshots s
        WHERE s.snapshot_id IS NULL
          AND EXISTS (
              SELECT 1 FROM snapshots existing
              WHERE existing.snapshot_id = s.rowid
          )
        """
    ).fetchone()
    return int(row[0] or 0)


def _index_sql(conn: sqlite3.Connection, table: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in conn.execute(f"PRAGMA index_list({table})").fetchall():
        name = row["name"]
        if str(name).startswith("sqlite_autoindex"):
            continue
        sql_row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND name = ?",
            (name,),
        ).fetchone()
        if sql_row and sql_row["sql"]:
            out[str(name)] = str(sql_row["sql"])
    return out


def _preflight_refusal(audit: dict[str, Any]) -> tuple[str, str] | None:
    counts = audit["counts_before"]
    preview = audit["id_assignment_preview"]
    if counts["snapshots"] <= 0:
        return "source_empty", "snapshots table is empty"
    if counts["snapshots_distinct_snapshot_id"] != counts["snapshots"] - counts["snapshots_null_snapshot_id"]:
        return "duplicate_existing_snapshot_id", "Existing non-null snapshot_id values are not unique"
    if preview["total_rows"] != counts["snapshots"]:
        return "count_probe_mismatch", "ID preview total does not match source count"
    if audit["snapshots_schema_before"]["is_repaired"] and counts["snapshots_null_snapshot_id"] > 0:
        return "repaired_schema_has_null_ids", "source table is repaired but still has NULL snapshot_id rows"
    return None


def _backup_database(db_path: Path, backup_root: Path) -> Path:
    backup_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_path = backup_root / f"{stamp}_pre_schema_repair_v1_ed_console.db"
    src = sqlite3.connect(str(db_path))
    try:
        dst = sqlite3.connect(str(backup_path))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    return backup_path


def _column_definition(col: dict[str, Any], *, normalized: bool = False) -> str:
    name = str(col["name"])
    if name == "snapshot_id":
        return "snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT"
    ctype = str(col["type"] or "TEXT").strip() or "TEXT"
    if normalized and name == "normalized_from_subminute":
        return "normalized_from_subminute INTEGER NOT NULL DEFAULT 0"
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


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _create_table_sql(table: str, cols: list[dict[str, Any]], *, normalized: bool = False) -> str:
    defs = [_column_definition(c, normalized=normalized) for c in cols]
    if normalized and "normalized_from_subminute" not in {str(c["name"]) for c in cols}:
        defs.append("normalized_from_subminute INTEGER NOT NULL DEFAULT 0")
    return f"CREATE TABLE {_quote_ident(table)} (\n    " + ",\n    ".join(defs) + "\n)"


def _migrate_snapshots(conn: sqlite3.Connection, audit: dict[str, Any]) -> None:
    live_cols = [_column_dict(r, source="live") for r in _table_info(conn, "snapshots")]
    cols = _merged_target_columns(conn)
    if not cols:
        raise RuntimeError("snapshots table missing")
    live_col_names = [str(c["name"]) for c in live_cols]
    target_col_names = [str(c["name"]) for c in cols]
    if "snapshot_id" not in live_col_names:
        raise RuntimeError("snapshots.snapshot_id column missing")

    preview = _id_assignment_preview(conn)
    max_id = int(preview["max_existing_snapshot_id"])
    null_rows = conn.execute(
        """
        SELECT rowid AS old_rowid,
               (? + ROW_NUMBER() OVER (ORDER BY rowid)) AS repaired_snapshot_id
        FROM snapshots
        WHERE snapshot_id IS NULL
        ORDER BY rowid
        """,
        (max_id,),
    ).fetchall()
    null_id_by_rowid = {int(r["old_rowid"]): int(r["repaired_snapshot_id"]) for r in null_rows}
    audit["assigned_null_snapshot_ids"] = {
        "count": len(null_id_by_rowid),
        "first": min(null_id_by_rowid.values()) if null_id_by_rowid else None,
        "last": max(null_id_by_rowid.values()) if null_id_by_rowid else None,
    }

    conn.execute("DROP TABLE IF EXISTS snapshots_new")
    conn.execute(_create_table_sql("snapshots_new", cols))
    insert_names = [name for name in target_col_names if name in live_col_names]
    insert_cols = ", ".join(_quote_ident(c) for c in insert_names)
    placeholders = ", ".join("?" for _ in insert_names)
    insert_sql = f"INSERT INTO snapshots_new ({insert_cols}) VALUES ({placeholders})"
    select_cols = ", ".join(_quote_ident(c) for c in live_col_names)
    source_rows = conn.execute(f"SELECT rowid AS _old_rowid, {select_cols} FROM snapshots ORDER BY rowid").fetchall()
    payloads = []
    for row in source_rows:
        values = []
        for name in insert_names:
            if name == "snapshot_id" and row[name] is None:
                values.append(null_id_by_rowid[int(row["_old_rowid"])])
            else:
                values.append(row[name])
        payloads.append(tuple(values))
    conn.executemany(insert_sql, payloads)

    _assert_target_invariants(conn, "snapshots_new", expected_count=len(source_rows))
    conn.execute("DROP TABLE snapshots")
    conn.execute("ALTER TABLE snapshots_new RENAME TO snapshots")
    for sql in REQUIRED_INDEXES.values():
        conn.execute(sql)
    for name, sql in audit.get("indexes_before", {}).items():
        if name not in REQUIRED_INDEXES:
            conn.execute(sql)
    conn.execute("ANALYZE snapshots")


def _rebuild_normalized_schema(conn: sqlite3.Connection) -> None:
    snap_cols = [_column_dict(r, source="snapshots") for r in _table_info(conn, "snapshots")]
    conn.execute("DROP TABLE IF EXISTS snapshots_1m_normalized")
    conn.execute(
        _create_table_sql(
            "snapshots_1m_normalized",
            _normalized_target_columns(snap_cols),
            normalized=True,
        )
    )


def _assert_target_invariants(conn: sqlite3.Connection, table: str, *, expected_count: int) -> None:
    count = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    if count != expected_count:
        raise RuntimeError(f"{table} count parity failed: expected={expected_count} actual={count}")
    null_count = int(conn.execute(f"SELECT COUNT(*) FROM {table} WHERE snapshot_id IS NULL").fetchone()[0])
    if null_count:
        raise RuntimeError(f"{table} has NULL snapshot_id rows: {null_count}")
    distinct_count = int(conn.execute(f"SELECT COUNT(DISTINCT snapshot_id) FROM {table}").fetchone()[0])
    if distinct_count != count:
        raise RuntimeError(f"{table} snapshot_id uniqueness failed: distinct={distinct_count} count={count}")


def _assert_post_conditions(conn: sqlite3.Connection, audit: dict[str, Any]) -> None:
    counts = audit["counts_after"]
    if counts["snapshots_null_snapshot_id"] != 0:
        raise RuntimeError("post migration snapshots still has NULL snapshot_id")
    if counts["snapshots_distinct_snapshot_id"] != counts["snapshots"]:
        raise RuntimeError("post migration snapshots snapshot_id is not unique")
    if not audit["snapshots_schema_after"]["is_repaired"]:
        raise RuntimeError("post migration snapshots schema is not repaired")
    if not audit["normalized_schema_after"]["is_repaired"]:
        raise RuntimeError("post migration normalized schema is not repaired")


def _success(audit: dict[str, Any]) -> dict[str, Any]:
    audit["success"] = True
    return audit


def _fail(audit: dict[str, Any], status: str, message: str) -> dict[str, Any]:
    audit["success"] = False
    audit["status"] = status
    audit.setdefault("errors", []).append(message)
    return audit


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Repair snapshots schema drift. Defaults to dry-run.")
    ap.add_argument("--db-path", type=Path, default=DEFAULT_DB)
    ap.add_argument("--backup-root", type=Path, default=None)
    ap.add_argument("--apply", action="store_true", help="Actually mutate the DB; default is dry-run.")
    args = ap.parse_args(argv)
    out = run(args.db_path, apply=bool(args.apply), backup_root=args.backup_root)
    print(json.dumps(out, indent=2, default=str))
    return 0 if out.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
