"""Phase 1 — database coverage for snapshots / normalized (machine + human readable)."""
from __future__ import annotations

import csv
import io
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from db import (
    DB_PATH,
    get_snapshot_sql,
    sql_db_coverage_col_labeled,
    sql_db_coverage_col_nonnull,
    sql_db_coverage_gap_lag,
    sql_db_coverage_snap_tot,
)
from timeframe_config import CANONICAL_TIMEFRAME


@dataclass
class TickerCoverage:
    ticker: str
    timeframe: str
    snapshots_total: int
    normalized_total: int
    outcome_1c_nonnull: int
    outcome_5c_nonnull: int
    outcome_15c_nonnull: int
    outcome_60c_nonnull: int
    outcome_1c_labeled: int
    outcome_5c_labeled: int
    outcome_15c_labeled: int
    outcome_60c_labeled: int
    ts_min: Optional[float]
    ts_max: Optional[float]
    gap_hint: str


def _one(cur: sqlite3.Cursor, sql: str, params: tuple) -> int:
    return int(cur.execute(sql, params).fetchone()[0])


def db_coverage_report(
    tickers: list[str],
    db_path: Optional[Path] = None,
    timeframe: str = CANONICAL_TIMEFRAME,
) -> dict[str, Any]:
    path = Path(db_path or DB_PATH)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    has_norm = "snapshots_1m_normalized" in tables

    rows_out: list[TickerCoverage] = []
    for tkr in tickers:
        tkr = tkr.upper().strip()
        snap_tot = _one(
            cur, sql_db_coverage_snap_tot(), (tkr, timeframe)
        )
        if has_norm:
            norm_tot = _one(cur, "SELECT COUNT(*) FROM snapshots_1m_normalized WHERE ticker=?", (tkr,))
        else:
            norm_tot = -1

        def nn(col: str) -> int:
            return _one(
                cur,
                sql_db_coverage_col_nonnull(col),
                (tkr, timeframe),
            )

        def lab(col: str) -> int:
            return _one(
                cur,
                sql_db_coverage_col_labeled(col),
                (tkr, timeframe),
            )

        rts = cur.execute(
            get_snapshot_sql("verification/db_coverage.py:76"),
            (tkr, timeframe),
        ).fetchone()
        ts_min = rts["a"]
        ts_max = rts["b"]
        gap_hint = ""
        if snap_tot > 1 and ts_min and ts_max:
            try:
                gc = _one(
                    cur,
                    sql_db_coverage_gap_lag(),
                    (tkr, timeframe),
                )
                gap_hint = f"{gc} pairwise gap(s) with delta(ts_utc) > 120s (1m continuity heuristic)"
            except sqlite3.OperationalError:
                gap_hint = "gap detection skipped (SQLite without LAG/window support)"

        rows_out.append(
            TickerCoverage(
                ticker=tkr,
                timeframe=timeframe,
                snapshots_total=snap_tot,
                normalized_total=norm_tot,
                outcome_1c_nonnull=nn("outcome_1c"),
                outcome_5c_nonnull=nn("outcome_5c"),
                outcome_15c_nonnull=nn("outcome_15c"),
                outcome_60c_nonnull=nn("outcome_60c"),
                outcome_1c_labeled=lab("outcome_1c"),
                outcome_5c_labeled=lab("outcome_5c"),
                outcome_15c_labeled=lab("outcome_15c"),
                outcome_60c_labeled=lab("outcome_60c"),
                ts_min=float(ts_min) if ts_min is not None else None,
                ts_max=float(ts_max) if ts_max is not None else None,
                gap_hint=gap_hint,
            )
        )

    conn.close()

    machine = {
        "db_path": str(path),
        "timeframe": timeframe,
        "snapshots_1m_normalized_present": has_norm,
        "tickers": [r.__dict__ for r in rows_out],
    }

    human = io.StringIO()
    human.write(f"DB: {path} | timeframe={timeframe!r} | normalized_table={has_norm}\n\n")
    for r in rows_out:
        human.write(
            f"{r.ticker}: snapshots_total={r.snapshots_total} normalized_total={r.normalized_total}\n"
            f"  nonnull 1c/5c/15c/60c: {r.outcome_1c_nonnull}/{r.outcome_5c_nonnull}/"
            f"{r.outcome_15c_nonnull}/{r.outcome_60c_nonnull}\n"
            f"  labeled (u/d/f) 1c/5c/15c/60c: {r.outcome_1c_labeled}/{r.outcome_5c_labeled}/"
            f"{r.outcome_15c_labeled}/{r.outcome_60c_labeled}\n"
            f"  ts_utc span: {r.ts_min} .. {r.ts_max} (max = most recent)\n"
            f"  gaps: {r.gap_hint}\n\n"
        )

    # CSV table (machine-friendly table)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(rows_out[0].__dict__.keys()) if rows_out else [])
    if rows_out:
        w.writeheader()
        for r in rows_out:
            w.writerow(r.__dict__)

    return {
        "machine": machine,
        "human_summary": human.getvalue(),
        "csv": buf.getvalue(),
        "json": machine,
    }

