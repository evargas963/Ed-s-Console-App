"""
Phase 4 — controlled Option A distance backfill (stored magnitudes only).

Normalizes historical nearest_below_dist / nearest_above_dist to non-negative magnitudes
in every SQLite table that carries both columns (snapshots, snapshots_1m_normalized, …).

Requires: file backup before mutation, transaction-wrapped updates, ed_schema_flags audit.

Does NOT modify Issue 19 SQL, get_similar_setups, or tier thresholds.

CLI:
  python distance_option_a_backfill_v1.py --db data/ed_console.db
  python distance_option_a_backfill_v1.py --mark-writers-on --db data/ed_console.db
  python distance_option_a_backfill_v1.py --cleanup-phase2-verify --db data/ed_console.db
  python distance_option_a_backfill_v1.py --dry-run --db data/ed_console.db
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target  # noqa: E402
from calibration.paths import DEFAULT_DB  # noqa: E402

FLAG_KEY = "distance_magnitude_option_a_v1"
FLAG_NONE = "none"
FLAG_WRITERS_ON = "writers_on"
FLAG_IN_PROGRESS = "backfill_in_progress"
FLAG_COMPLETE = "backfill_complete"
VERIFICATION_TICKER = "PHASE2VERIFY"


def _repo_root() -> Path:
    return Path(__file__).resolve().parent


def ensure_schema_flags_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ed_schema_flags (
            flag_key    TEXT PRIMARY KEY,
            flag_value  TEXT NOT NULL,
            set_ts_utc  REAL
        )
        """
    )


def discover_distance_tables(conn: sqlite3.Connection) -> list[str]:
    """Tables that contain both nearest_above_dist and nearest_below_dist."""
    rows = conn.execute(
        """
        SELECT name FROM sqlite_master
        WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """
    ).fetchall()
    out: list[str] = []
    for (name,) in rows:
        cols = {
            r[1]
            for r in conn.execute(f"PRAGMA table_info({name})").fetchall()
        }
        if "nearest_above_dist" in cols and "nearest_below_dist" in cols:
            out.append(name)
    return out


def distance_column_stats(conn: sqlite3.Connection, table: str) -> dict[str, Any]:
    """Counts for one table; safe for empty tables."""
    t = table
    total = int(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])
    nad_neg = int(
        conn.execute(
            f"SELECT COUNT(*) FROM {t} WHERE nearest_above_dist < 0"
        ).fetchone()[0]
    )
    nbd_neg = int(
        conn.execute(
            f"SELECT COUNT(*) FROM {t} WHERE nearest_below_dist < 0"
        ).fetchone()[0]
    )
    nad_null = int(
        conn.execute(
            f"SELECT COUNT(*) FROM {t} WHERE nearest_above_dist IS NULL"
        ).fetchone()[0]
    )
    nbd_null = int(
        conn.execute(
            f"SELECT COUNT(*) FROM {t} WHERE nearest_below_dist IS NULL"
        ).fetchone()[0]
    )
    return {
        "table": t,
        "total_rows": total,
        "nearest_above_dist_lt_0": nad_neg,
        "nearest_below_dist_lt_0": nbd_neg,
        "nearest_above_dist_null": nad_null,
        "nearest_below_dist_null": nbd_null,
    }


def copy_db_file_backup(db_path: Path, *, label: str) -> Path:
    """Atomic best-effort backup: copy entire SQLite file to data/backups/."""
    db_path = db_path.resolve()
    if not db_path.is_file():
        raise FileNotFoundError(f"database not found: {db_path}")
    backup_root = db_path.parent / "backups"
    backup_root.mkdir(parents=True, exist_ok=True)
    ts = int(time.time())
    dest = backup_root / f"{db_path.stem}.{label}.{ts}.db"
    shutil.copy2(db_path, dest)
    log.info("Backup written: %s", dest)
    return dest


def cleanup_verification_ticker_rows(
    conn: sqlite3.Connection,
    *,
    ticker: str = VERIFICATION_TICKER,
) -> dict[str, Any]:
    """Delete only Phase 2 verification rows; per-table counts logged."""
    ticker_u = (ticker or "").upper().strip()
    tables = discover_distance_tables(conn)
    detail: dict[str, int] = {}
    total = 0
    for tbl in tables:
        cur = conn.execute(
            f"DELETE FROM {tbl} WHERE UPPER(ticker) = ?",
            (ticker_u,),
        )
        n = cur.rowcount if cur.rowcount is not None else 0
        detail[tbl] = n
        total += n
    log.info(
        "cleanup_verification_ticker_rows ticker=%r total_deleted=%s detail=%s",
        ticker_u,
        total,
        detail,
    )
    return {"ticker": ticker_u, "total_deleted": total, "per_table": detail}


def _validate_non_negative_distances(conn: sqlite3.Connection, tables: list[str]) -> None:
    for t in tables:
        bad_a = conn.execute(
            f"SELECT COUNT(*) FROM {t} WHERE nearest_above_dist < 0"
        ).fetchone()[0]
        bad_b = conn.execute(
            f"SELECT COUNT(*) FROM {t} WHERE nearest_below_dist < 0"
        ).fetchone()[0]
        if int(bad_a) > 0 or int(bad_b) > 0:
            raise RuntimeError(
                f"invariant failed after backfill: {t} nad_neg={bad_a} nbd_neg={bad_b}"
            )


def tier1_pool_coverage_report(db_path: Path) -> dict[str, Any]:
    """Re-run Adaptive Shadow v1 tier-1 pool report on default survivorship anchors."""
    from adaptive_shadow_v2_calibration import load_survivorship_anchors_v1
    from adaptive_shadow_v2_calibration import report_tier1_pool_coverage_v1
    from db import EdDB

    db = EdDB(db_path)
    anchors = load_survivorship_anchors_v1()
    return report_tier1_pool_coverage_v1(db, anchors)


def issue19_tier_sanity(db_path: Path) -> dict[str, Any]:
    """Sample Issue-19-style tier-1 fetch: pool non-empty for anchors after backfill."""
    from adaptive_similarity_engine import _fetch_issue19_tier1_candidate_rows
    from adaptive_shadow_v2_calibration import load_survivorship_anchors_v1
    from db import EdDB

    db = EdDB(db_path)
    anchors = load_survivorship_anchors_v1()
    samples: list[dict[str, Any]] = []
    for a in anchors[:5]:
        rows = _fetch_issue19_tier1_candidate_rows(
            db,
            ticker=a["ticker"],
            timeframe=a["timeframe"],
            zone=a["zone"],
            vwap_side=a["vwap_side"],
            nearest_above_dist=a.get("nearest_above_dist"),
            nearest_below_dist=a.get("nearest_below_dist"),
            as_of_ts_utc=None,
            structural_pool_cap=8000,
        )
        samples.append(
            {
                "anchor_id": a.get("anchor_id"),
                "tier1_row_count": len(rows),
            }
        )
    nonempty = sum(1 for s in samples if s["tier1_row_count"] > 0)
    return {
        "schema": "issue19_tier1_sanity_v1",
        "anchors_sampled": len(samples),
        "nonempty_tier1_in_sample": nonempty,
        "samples": samples,
        "note": (
            "Uses unchanged Issue 19 tier-1 SQL via _fetch_issue19_tier1_candidate_rows; "
            "after ABS backfill, stored BETWEEN on non-negative buckets aligns with rows."
        ),
    }


def run_distance_option_a_backfill_v1(
    db_path: Path,
    *,
    dry_run: bool = False,
    force: bool = False,
    skip_backup: bool = False,
) -> dict[str, Any]:
    """
    Transaction-wrapped backfill. Sets ed_schema_flags.distance_magnitude_option_a_v1.

    NO-GO (raises) if backup fails (unless dry_run). Refuses when flag is backfill_complete
    unless force=True.
    """
    db_path = db_path.resolve()
    audit: dict[str, Any] = {
        "schema": "distance_option_a_backfill_v1",
        "db_path": str(db_path),
        "dry_run": dry_run,
        "force": force,
    }

    conn = sqlite3.connect(str(db_path), timeout=60)
    conn.row_factory = sqlite3.Row
    try:
        ensure_schema_flags_table(conn)
        row = conn.execute(
            "SELECT flag_value FROM ed_schema_flags WHERE flag_key = ?",
            (FLAG_KEY,),
        ).fetchone()
        current = str(row[0]) if row and row[0] is not None else None
        audit["flag_before"] = current or FLAG_NONE

        if current == FLAG_COMPLETE and not force and not dry_run:
            raise RuntimeError(
                f"NO-GO: {FLAG_KEY} is {FLAG_COMPLETE}. Pass force=True to re-run (remediation only)."
            )

        tables = discover_distance_tables(conn)
        audit["tables_discovered"] = tables
        pre: dict[str, Any] = {t: distance_column_stats(conn, t) for t in tables}
        audit["pre_backfill"] = pre

        if dry_run:
            audit["status"] = "dry_run_complete"
            return audit

        backup_path: Optional[Path] = None
        if not skip_backup:
            backup_path = copy_db_file_backup(
                db_path, label="pre_option_a_backfill_v1"
            )
        audit["backup_path"] = str(backup_path) if backup_path else None

        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                """
                INSERT INTO ed_schema_flags (flag_key, flag_value, set_ts_utc)
                VALUES (?, ?, ?)
                ON CONFLICT(flag_key) DO UPDATE SET
                    flag_value = excluded.flag_value,
                    set_ts_utc = excluded.set_ts_utc
                """,
                (FLAG_KEY, FLAG_IN_PROGRESS, time.time()),
            )

            changes_by_table: dict[str, dict[str, int]] = {}
            for t in tables:
                nbd_before = int(
                    conn.execute(
                        f"SELECT COUNT(*) FROM {t} WHERE nearest_below_dist < 0"
                    ).fetchone()[0]
                )
                nad_before = int(
                    conn.execute(
                        f"SELECT COUNT(*) FROM {t} WHERE nearest_above_dist < 0"
                    ).fetchone()[0]
                )
                conn.execute(
                    f"""
                    UPDATE {t}
                    SET nearest_below_dist = ABS(nearest_below_dist)
                    WHERE nearest_below_dist IS NOT NULL AND nearest_below_dist < 0
                    """
                )
                if nad_before > 0:
                    conn.execute(
                        f"""
                        UPDATE {t}
                        SET nearest_above_dist = ABS(nearest_above_dist)
                        WHERE nearest_above_dist IS NOT NULL AND nearest_above_dist < 0
                        """
                    )

                nbd_neg_after = int(
                    conn.execute(
                        f"SELECT COUNT(*) FROM {t} WHERE nearest_below_dist < 0"
                    ).fetchone()[0]
                )
                nad_neg_after = int(
                    conn.execute(
                        f"SELECT COUNT(*) FROM {t} WHERE nearest_above_dist < 0"
                    ).fetchone()[0]
                )
                changes_by_table[t] = {
                    "rows_nearest_below_negative_before": nbd_before,
                    "rows_nearest_above_negative_before": nad_before,
                    "rows_nearest_below_negative_after": nbd_neg_after,
                    "rows_nearest_above_negative_after": nad_neg_after,
                    "nearest_below_rows_fixed": max(0, nbd_before - nbd_neg_after),
                    "nearest_above_rows_fixed": max(0, nad_before - nad_neg_after),
                }

            _validate_non_negative_distances(conn, tables)

            post = {t: distance_column_stats(conn, t) for t in tables}
            audit["post_backfill"] = post
            audit["rows_changed_detail"] = changes_by_table

            conn.execute(
                """
                INSERT INTO ed_schema_flags (flag_key, flag_value, set_ts_utc)
                VALUES (?, ?, ?)
                ON CONFLICT(flag_key) DO UPDATE SET
                    flag_value = excluded.flag_value,
                    set_ts_utc = excluded.set_ts_utc
                """,
                (FLAG_KEY, FLAG_COMPLETE, time.time()),
            )
            conn.commit()
            audit["status"] = "backfill_complete"
            audit["flag_after"] = FLAG_COMPLETE
        except Exception:
            conn.rollback()
            restore = (
                current
                if current and current != FLAG_IN_PROGRESS
                else FLAG_NONE
            )
            conn.execute(
                """
                INSERT INTO ed_schema_flags (flag_key, flag_value, set_ts_utc)
                VALUES (?, ?, ?)
                ON CONFLICT(flag_key) DO UPDATE SET
                    flag_value = excluded.flag_value,
                    set_ts_utc = excluded.set_ts_utc
                """,
                (FLAG_KEY, restore, time.time()),
            )
            conn.commit()
            raise
    finally:
        conn.close()

    audit_path = _repo_root() / "data" / "distance_option_a_backfill_v1_last_audit.json"
    try:
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        audit_path.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
        audit["audit_json_written"] = str(audit_path)
    except OSError as e:
        audit["audit_json_error"] = str(e)

    return audit


def mark_writers_on(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path.resolve()), timeout=30)
    try:
        ensure_schema_flags_table(conn)
        conn.execute(
            """
            INSERT INTO ed_schema_flags (flag_key, flag_value, set_ts_utc)
            VALUES (?, ?, ?)
            ON CONFLICT(flag_key) DO UPDATE SET
                flag_value = excluded.flag_value,
                set_ts_utc = excluded.set_ts_utc
            """,
            (FLAG_KEY, FLAG_WRITERS_ON, time.time()),
        )
        conn.commit()
    finally:
        conn.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(description="Option A distance backfill (Phase 4)")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--force", action="store_true", help="allow re-run when already complete")
    p.add_argument(
        "--skip-backup",
        action="store_true",
        help="unsafe: skip file copy (testing only)",
    )
    p.add_argument(
        "--mark-writers-on",
        action="store_true",
        help=f"set {FLAG_KEY}={FLAG_WRITERS_ON} and exit",
    )
    p.add_argument(
        "--cleanup-phase2-verify",
        action="store_true",
        help=f"delete rows with ticker={VERIFICATION_TICKER!r} only",
    )
    p.add_argument("--report-only", action="store_true", help="pre counts + tier1 + sanity only")
    register_allow_noncanonical_flag(p)
    args = p.parse_args()
    require_canonical_db_target(args, tool_name="distance_option_a_backfill_v1", write_capable=True)

    if args.mark_writers_on:
        mark_writers_on(args.db)
        print(json.dumps({"marked": FLAG_WRITERS_ON, "db": str(args.db.resolve())}))
        return

    conn = sqlite3.connect(str(args.db.resolve()), timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        ensure_schema_flags_table(conn)
        if args.cleanup_phase2_verify:
            out = cleanup_verification_ticker_rows(conn, ticker=VERIFICATION_TICKER)
            conn.commit()
            print(json.dumps(out, indent=2))
            return

        if args.report_only:
            tables = discover_distance_tables(conn)
            pre = {t: distance_column_stats(conn, t) for t in tables}
            flag = conn.execute(
                "SELECT flag_value FROM ed_schema_flags WHERE flag_key = ?",
                (FLAG_KEY,),
            ).fetchone()
            print(
                json.dumps(
                    {
                        "flag": str(flag[0]) if flag else None,
                        "pre": pre,
                        "tier1_coverage": tier1_pool_coverage_report(args.db),
                        "issue19_sanity": issue19_tier_sanity(args.db),
                    },
                    indent=2,
                )
            )
            return
    finally:
        conn.close()

    out = run_distance_option_a_backfill_v1(
        args.db,
        dry_run=args.dry_run,
        force=args.force,
        skip_backup=args.skip_backup,
    )
    if not args.dry_run and out.get("status") == "backfill_complete":
        out["tier1_coverage_after"] = tier1_pool_coverage_report(args.db)
        out["issue19_sanity_after"] = issue19_tier_sanity(args.db)
        cov = out["tier1_coverage_after"]
        at = cov["anchors_total"]
        ne = cov["nonempty_tier1_pool_count"]
        out["majority_nonempty_tier1_pools"] = (
            (ne * 2 >= at) if at else False
        )
        mean_sz = cov.get("mean_pool_size", 0.0)
        out["mean_pool_size"] = mean_sz
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
