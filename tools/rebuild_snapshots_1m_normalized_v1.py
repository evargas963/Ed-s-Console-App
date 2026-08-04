"""RC-207 — rebuild / quarantine tooling for corrupt snapshots_1m_normalized.

MEASURED (2026-08-03 quiet window FAIL):
  - Table rootpage 20 payload reads raise `database disk image is malformed`
  - COUNT(*) / MAX(ts_utc) via index still answer
  - DROP TABLE also raises malformed (cannot free in-place)
  - Source `snapshots` prior-net_gamma reads succeed

Live serve is quarantined off this table in ml_data_common.SERVE_SNAPSHOT_TABLE.
This tool:
  - dry-run: measure pre probes + disk headroom
  - --execute-clone: clone DB skipping the corrupt table, rematerialize, swap
    (needs free disk ≥ db_size + ~2GB; console writers MUST be stopped)

Usage:
  python -m tools.rebuild_snapshots_1m_normalized_v1
  python -m tools.rebuild_snapshots_1m_normalized_v1 --execute-clone
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
DEFAULT_DB = REPO / "data" / "ed_console.db"
OUT_DEFAULT = REPO / "data" / "ed_console_repaired.db"
QUAR_DEFAULT = REPO / "data" / "ed_console_pre_rc207_quarantine.db"
REPORT = REPO / "reports" / "rebuild_snapshots_1m_normalized_latest.json"
TABLE = "snapshots_1m_normalized"
INDEX = "idx_snap1m_ticker_tf_ts"


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=120.0)
    conn.execute("PRAGMA busy_timeout=120000")
    from db import configure_sqlite_connection

    configure_sqlite_connection(conn)
    return conn


def _probe_prior_net_gamma(conn: sqlite3.Connection, table: str) -> dict[str, Any]:
    from timeframe_config import CANONICAL_TIMEFRAME

    sql = (
        f"SELECT net_gamma FROM {table} "
        "WHERE ticker = ? AND timeframe = ? AND ts_utc < ? "
        "ORDER BY ts_utc DESC LIMIT 1"
    )
    t0 = time.perf_counter()
    try:
        row = conn.execute(sql, ("SPY", CANONICAL_TIMEFRAME, time.time())).fetchone()
        return {
            "ok": True,
            "err": None,
            "value": None if row is None else row[0],
            "elapsed_ms": round((time.perf_counter() - t0) * 1000, 2),
            "table": table,
        }
    except sqlite3.DatabaseError as e:
        return {
            "ok": False,
            "err": f"{type(e).__name__}: {e}",
            "value": None,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000, 2),
            "table": table,
        }


def measure(db_path: Path) -> dict[str, Any]:
    audit: dict[str, Any] = {
        "db_path": str(db_path),
        "mode": "measure",
        "started_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    usage = shutil.disk_usage(str(db_path.parent))
    audit["disk_free_gb"] = round(usage.free / 1e9, 2)
    audit["db_size_gb"] = round(db_path.stat().st_size / 1e9, 2) if db_path.is_file() else None
    audit["clone_headroom_ok"] = bool(
        audit["db_size_gb"] is not None
        and audit["disk_free_gb"] >= (audit["db_size_gb"] + 2.0)
    )
    conn = _connect(db_path)
    try:
        try:
            audit["normalized_count"] = int(
                conn.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0]
            )
        except Exception as e:
            audit["normalized_count_err"] = f"{type(e).__name__}: {e}"
        audit["normalized_prior_net_gamma"] = _probe_prior_net_gamma(conn, TABLE)
        audit["snapshots_prior_net_gamma"] = _probe_prior_net_gamma(conn, "snapshots")
        # DROP probe on a SAVEPOINT — expect malformed on corrupt live DB
        try:
            conn.execute("SAVEPOINT drop_probe")
            conn.execute(f"DROP TABLE IF EXISTS {TABLE}")
            audit["drop_table_ok"] = True
            conn.execute("ROLLBACK TO drop_probe")
        except sqlite3.DatabaseError as e:
            audit["drop_table_ok"] = False
            audit["drop_table_err"] = f"{type(e).__name__}: {e}"
            try:
                conn.execute("ROLLBACK TO drop_probe")
            except sqlite3.Error:
                pass
        conn.rollback()
    finally:
        conn.close()
    audit["ok"] = True  # measure always succeeds as a measurement
    audit["ended_at_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return audit


def execute_clone(
    db_path: Path,
    *,
    out_path: Path,
    quar_path: Path,
) -> dict[str, Any]:
    audit = measure(db_path)
    audit["mode"] = "execute_clone"
    audit["steps"] = []
    if not audit.get("clone_headroom_ok"):
        audit["ok"] = False
        audit["error"] = (
            f"insufficient free disk for clone "
            f"(free={audit.get('disk_free_gb')}GB db={audit.get('db_size_gb')}GB; need db+2GB)"
        )
        return audit
    if not audit.get("snapshots_prior_net_gamma", {}).get("ok"):
        audit["ok"] = False
        audit["error"] = "source snapshots unreadable — refuse clone"
        return audit

    if out_path.exists():
        out_path.unlink()

    src = _connect(db_path)
    try:
        t0 = time.perf_counter()
        src.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        audit["steps"].append(
            {"wal_checkpoint_ms": round((time.perf_counter() - t0) * 1000, 2)}
        )
        create_sql = src.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
            (TABLE,),
        ).fetchone()
        index_sqls = [
            r[0]
            for r in src.execute(
                "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name=? AND sql IS NOT NULL",
                (TABLE,),
            ).fetchall()
            if r[0]
        ]
        if not create_sql or not create_sql[0]:
            audit["ok"] = False
            audit["error"] = "missing create sql"
            return audit
        create_sql_text = create_sql[0]
        schema_path = REPO / "reports" / "_rc207_normalized_schema.sql"
        schema_path.write_text(
            create_sql_text + ";\n" + ";\n".join(index_sqls) + ";\n",
            encoding="utf-8",
        )
        audit["schema_path"] = str(schema_path)

        objs = src.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master "
            "WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' ORDER BY "
            "CASE type WHEN 'table' THEN 0 WHEN 'index' THEN 1 WHEN 'view' THEN 2 ELSE 3 END, name"
        ).fetchall()

        dst = sqlite3.connect(str(out_path), timeout=120.0)
        dst.execute("PRAGMA busy_timeout=120000")
        dst.execute("PRAGMA journal_mode=WAL")
        dst.execute("PRAGMA synchronous=NORMAL")
        tables_copied: list[dict[str, Any]] = []
        try:
            dst.execute(f"ATTACH DATABASE '{db_path.as_posix()}' AS srcdb")
            for typ, name, tbl_name, sql in objs:
                if name == TABLE or tbl_name == TABLE:
                    continue
                if typ == "table":
                    t0 = time.perf_counter()
                    dst.execute(sql)
                    dst.execute(f'INSERT INTO main."{name}" SELECT * FROM srcdb."{name}"')
                    dst.commit()
                    n = int(dst.execute(f'SELECT COUNT(*) FROM main."{name}"').fetchone()[0])
                    tables_copied.append(
                        {
                            "name": name,
                            "rows": n,
                            "ms": round((time.perf_counter() - t0) * 1000, 2),
                        }
                    )
                elif typ in ("index", "view", "trigger"):
                    try:
                        dst.execute(sql)
                    except sqlite3.Error as e:
                        audit.setdefault("nonfatal_schema_errs", []).append(
                            f"{typ} {name}: {e}"
                        )
            dst.commit()
            dst.execute(create_sql_text)
            for idx in index_sqls or [
                f"CREATE INDEX {INDEX} ON {TABLE}(ticker, timeframe, ts_utc)"
            ]:
                dst.execute(idx)
            dst.commit()
            dst.execute("DETACH DATABASE srcdb")
        finally:
            dst.close()
        audit["steps"].append({"tables_copied": len(tables_copied)})
        audit["tables_copied"] = tables_copied
    finally:
        src.close()

    from snapshot_normalizer import run_full_materialization

    t0 = time.perf_counter()
    mat = run_full_materialization(out_path)
    audit["materialize"] = {
        "success": bool(mat.get("success")),
        "normalized_rows": (mat.get("materialize") or {}).get("normalized_rows"),
        "errors": (mat.get("materialize") or {}).get("errors"),
        "validate_ok": (mat.get("validate") or {}).get("ok"),
        "ms": round((time.perf_counter() - t0) * 1000, 2),
    }

    con = _connect(out_path)
    try:
        audit["repaired_prior"] = _probe_prior_net_gamma(con, TABLE)
        audit["repaired_count"] = int(con.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0])
    finally:
        con.close()

    if not (
        audit.get("materialize", {}).get("success")
        and audit.get("repaired_prior", {}).get("ok")
        and audit.get("repaired_count", 0) > 0
    ):
        audit["ok"] = False
        audit["error"] = "repaired DB failed prove — live DB untouched"
        return audit

    if quar_path.exists():
        quar_path.unlink()
    os.replace(db_path, quar_path)
    for side in (str(db_path) + "-wal", str(db_path) + "-shm"):
        p = Path(side)
        if p.exists():
            os.replace(p, Path(str(quar_path) + p.name[len(str(db_path)) :]))
    os.replace(out_path, db_path)
    for side in (str(out_path) + "-wal", str(out_path) + "-shm"):
        p = Path(side)
        if p.exists():
            os.replace(p, Path(str(db_path) + p.name[len(str(out_path)) :]))

    con = _connect(db_path)
    try:
        audit["live_prior"] = _probe_prior_net_gamma(con, TABLE)
    finally:
        con.close()
    audit["quarantine"] = str(quar_path)
    audit["ok"] = bool(audit.get("live_prior", {}).get("ok"))
    audit["ended_at_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return audit


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--out", type=Path, default=OUT_DEFAULT)
    ap.add_argument("--quarantine", type=Path, default=QUAR_DEFAULT)
    ap.add_argument(
        "--execute-clone",
        action="store_true",
        help="Clone skipping corrupt table, rematerialize, swap (writers must be stopped)",
    )
    ap.add_argument("--report", type=Path, default=REPORT)
    args = ap.parse_args(argv)
    if args.execute_clone:
        audit = execute_clone(args.db, out_path=args.out, quar_path=args.quarantine)
    else:
        audit = measure(args.db)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                k: audit.get(k)
                for k in (
                    "ok",
                    "mode",
                    "error",
                    "disk_free_gb",
                    "clone_headroom_ok",
                    "normalized_prior_net_gamma",
                    "snapshots_prior_net_gamma",
                    "drop_table_ok",
                    "live_prior",
                    "materialize",
                )
                if k in audit or k in ("ok", "mode", "error")
            },
            indent=2,
        )
    )
    print(f"report={args.report}")
    if args.execute_clone:
        return 0 if audit.get("ok") else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
