"""
FIND-CAL-TS item-6: rewrite stored ET clock columns from authoritative ts_utc.

Targets snapshots (and snapshots_1m_normalized when present) for rows with
ts_utc < COH_I_A_ET_BACKFILL_CEILING_TS_UTC. calibration_decision_log has no
et_hour / ts_et columns — join snapshots on decision_ts_utc for session context.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from ml_data_common import market_session_from_ts_utc
from app.domain.time_et import (
    COH_I_A_ET_BACKFILL_CEILING_TS_UTC,
    build_ts_et_from_ts_utc,
    et_clock_from_ts_utc,
)

SCHEMA = "backfill_et_clock_from_ts_utc_v1"
BACKFILL_TABLES: tuple[str, ...] = ("snapshots", "snapshots_1m_normalized")
ET_CLOCK_COLUMNS: tuple[str, ...] = ("et_hour", "et_minute", "market_session", "ts_et")
PK_COLUMN = "snapshot_id"


@dataclass(frozen=True)
class DerivedEtClock:
    et_hour: int
    et_minute: int
    market_session: str
    ts_et: str


def derive_et_clock_from_ts_utc(ts_utc: float) -> DerivedEtClock:
    h, m, _ = et_clock_from_ts_utc(ts_utc)
    return DerivedEtClock(
        et_hour=h,
        et_minute=m,
        market_session=market_session_from_ts_utc(ts_utc),
        ts_et=build_ts_et_from_ts_utc(ts_utc),
    )


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    return row is not None


def _table_column_set(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(r[1]) for r in rows}


def table_ready_for_backfill(conn: sqlite3.Connection, table: str) -> bool:
    if not _table_exists(conn, table):
        return False
    cols = _table_column_set(conn, table)
    need = {PK_COLUMN, "ts_utc", *ET_CLOCK_COLUMNS}
    return need.issubset(cols)


def row_differs_from_derived(
    ts_utc: float,
    et_hour: Any,
    et_minute: Any,
    market_session: Any,
    ts_et: Any,
) -> bool:
    """True when any stored ET clock field differs from ts_utc-derived authority."""
    d = derive_et_clock_from_ts_utc(ts_utc)
    try:
        if int(et_hour) != d.et_hour or int(et_minute) != d.et_minute:
            return True
    except (TypeError, ValueError):
        return True
    stored_ms = "" if market_session is None else str(market_session)
    if stored_ms != d.market_session:
        return True
    stored_ts_et = "" if ts_et is None else str(ts_et)
    if stored_ts_et != d.ts_et:
        return True
    return False


def count_candidates(
    conn: sqlite3.Connection,
    table: str,
    *,
    ceiling_ts_utc: float,
) -> int:
    row = conn.execute(
        f"""
        SELECT COUNT(*) FROM {table}
        WHERE ts_utc IS NOT NULL AND ts_utc < ?
        """,
        (float(ceiling_ts_utc),),
    ).fetchone()
    return int(row[0]) if row else 0


def count_mismatched(
    conn: sqlite3.Connection,
    table: str,
    *,
    ceiling_ts_utc: float,
    max_rows: int | None = None,
) -> int:
    limit_sql = f" LIMIT {int(max_rows)}" if max_rows is not None and max_rows > 0 else ""
    rows = conn.execute(
        f"""
        SELECT ts_utc, et_hour, et_minute, market_session, ts_et
        FROM {table}
        WHERE ts_utc IS NOT NULL AND ts_utc < ?
        ORDER BY {PK_COLUMN} ASC
        {limit_sql}
        """,
        (float(ceiling_ts_utc),),
    ).fetchall()
    n = 0
    for r in rows:
        if row_differs_from_derived(r[0], r[1], r[2], r[3], r[4]):
            n += 1
            if max_rows is not None and n >= max_rows:
                break
    return n


def _fetch_batch(
    conn: sqlite3.Connection,
    table: str,
    *,
    ceiling_ts_utc: float,
    after_snapshot_id: int,
    batch_size: int,
) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    return list(
        conn.execute(
            f"""
            SELECT {PK_COLUMN}, ts_utc, et_hour, et_minute, market_session, ts_et
            FROM {table}
            WHERE ts_utc IS NOT NULL
              AND ts_utc < ?
              AND {PK_COLUMN} > ?
            ORDER BY {PK_COLUMN} ASC
            LIMIT ?
            """,
            (float(ceiling_ts_utc), int(after_snapshot_id), int(batch_size)),
        ).fetchall()
    )


def backfill_table(
    conn: sqlite3.Connection,
    table: str,
    *,
    ceiling_ts_utc: float = COH_I_A_ET_BACKFILL_CEILING_TS_UTC,
    apply: bool = False,
    max_rows: int | None = None,
    batch_size: int = 500,
    manage_transaction: bool = True,
) -> dict[str, Any]:
    """
  Rewrite ET clock columns for pre-ceiling rows.

  max_rows caps would_update / updated (not merely scanned rows).
  When apply=True and manage_transaction=True, wraps the table pass in BEGIN/COMMIT
  and ROLLBACK on any error.
    """
    conn.row_factory = sqlite3.Row
    if not table_ready_for_backfill(conn, table):
        return {
            "table": table,
            "skipped": True,
            "reason": "missing_table_or_columns",
            "scanned": 0,
            "would_update": 0,
            "updated": 0,
        }

    scanned = 0
    would_update = 0
    updated = 0
    after_id = 0
    update_budget = max_rows
    txn_open = False

    if apply and manage_transaction:
        conn.execute("BEGIN")
        txn_open = True

    try:
        while True:
            if update_budget is not None and update_budget <= 0:
                break
            take = batch_size
            if update_budget is not None:
                take = min(take, update_budget)
            rows = _fetch_batch(
                conn,
                table,
                ceiling_ts_utc=ceiling_ts_utc,
                after_snapshot_id=after_id,
                batch_size=take,
            )
            if not rows:
                break

            for r in rows:
                sid = int(r[PK_COLUMN])
                after_id = sid
                ts_utc = float(r["ts_utc"])
                scanned += 1
                if not row_differs_from_derived(
                    ts_utc, r["et_hour"], r["et_minute"], r["market_session"], r["ts_et"]
                ):
                    continue
                if update_budget is not None and update_budget <= 0:
                    break
                would_update += 1
                d = derive_et_clock_from_ts_utc(ts_utc)
                if apply:
                    conn.execute(
                        f"""
                        UPDATE {table}
                        SET et_hour=?, et_minute=?, market_session=?, ts_et=?
                        WHERE {PK_COLUMN}=?
                        """,
                        (d.et_hour, d.et_minute, d.market_session, d.ts_et, sid),
                    )
                    updated += 1
                if update_budget is not None:
                    update_budget -= 1

            if update_budget is not None and update_budget <= 0:
                break

        if apply and txn_open:
            conn.commit()
            txn_open = False
    except Exception:
        if apply and txn_open:
            conn.rollback()
        raise

    return {
        "table": table,
        "skipped": False,
        "scanned": scanned,
        "would_update": would_update,
        "updated": updated if apply else 0,
    }


def run_backfill(
    db_path: str,
    *,
    apply: bool = False,
    ceiling_ts_utc: float = COH_I_A_ET_BACKFILL_CEILING_TS_UTC,
    max_rows: int | None = None,
    tables: tuple[str, ...] = BACKFILL_TABLES,
) -> dict[str, Any]:
    conn = sqlite3.connect(str(db_path), timeout=120)
    try:
        per_table: list[dict[str, Any]] = []
        remaining_budget = max_rows
        for table in tables:
            if remaining_budget is not None and remaining_budget <= 0:
                per_table.append(
                    {
                        "table": table,
                        "skipped": True,
                        "reason": "max_rows_budget_exhausted",
                        "scanned": 0,
                        "would_update": 0,
                        "updated": 0,
                    }
                )
                continue
            stats = backfill_table(
                conn,
                table,
                ceiling_ts_utc=ceiling_ts_utc,
                apply=apply,
                max_rows=remaining_budget,
                manage_transaction=False,
            )
            per_table.append(stats)
            if remaining_budget is not None:
                used = int(stats.get("would_update") or 0) if not apply else int(stats.get("updated") or 0)
                remaining_budget = max(0, remaining_budget - used)

        if apply:
            conn.commit()

        return {
            "schema": SCHEMA,
            "db_path": str(db_path),
            "mode": "commit" if apply else "dry_run",
            "ceiling_ts_utc": float(ceiling_ts_utc),
            "tables": per_table,
            "calibration_decision_log": "skipped_no_et_clock_columns",
        }
    except Exception:
        if apply:
            conn.rollback()
        raise
    finally:
        conn.close()


def sample_post_backfill_check(
    conn: sqlite3.Connection,
    table: str,
    *,
    ceiling_ts_utc: float,
    sample_size: int = 20,
) -> dict[str, Any]:
    """Random sample: stored ET clock fields must match derive_et_clock_from_ts_utc(ts_utc)."""
    if not table_ready_for_backfill(conn, table):
        return {"table": table, "ok": True, "checked": 0, "mismatches": []}

    rows = conn.execute(
        f"""
        SELECT {PK_COLUMN}, ts_utc, et_hour, et_minute, market_session, ts_et
        FROM {table}
        WHERE ts_utc IS NOT NULL AND ts_utc < ?
        ORDER BY RANDOM()
        LIMIT ?
        """,
        (float(ceiling_ts_utc), int(sample_size)),
    ).fetchall()

    mismatches: list[dict[str, Any]] = []
    for r in rows:
        sid = int(r[0])
        ts_utc = float(r[1])
        if row_differs_from_derived(ts_utc, r[2], r[3], r[4], r[5]):
            d = derive_et_clock_from_ts_utc(ts_utc)
            mismatches.append(
                {
                    PK_COLUMN: sid,
                    "ts_utc": ts_utc,
                    "stored": {
                        "et_hour": r[2],
                        "et_minute": r[3],
                        "market_session": r[4],
                        "ts_et": r[5],
                    },
                    "derived": {
                        "et_hour": d.et_hour,
                        "et_minute": d.et_minute,
                        "market_session": d.market_session,
                        "ts_et": d.ts_et,
                    },
                }
            )

    return {
        "table": table,
        "ok": len(mismatches) == 0,
        "checked": len(rows),
        "mismatches": mismatches,
    }
