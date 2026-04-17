#!/usr/bin/env python3
"""
Historical fusion replay over broad 1m snapshot history: maximize valid fused_* coverage.

Unlike backfill_fusion_policy_columns_v1.py:
- No policy-readiness ticker filter (all tickers in DB).
- No legacy GOV_WHERE / simultaneous all-horizon outcome_move requirement.
- Still requires causal LSTM history: >= STREAM_5M_LOOKBACK prior 1m rows (stack integrity).

Writes fused_* + fusion_replay_stack_grade_v1 (FULL | PARTIAL | DEGRADED). Does not invent values.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import traceback
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from db import EdDB, configure_sqlite_connection
from features.fusion_replay_grade_v1 import fusion_replay_stack_grade_v1
from features.replay_signal_input_v1 import signal_input_from_snapshot_row_dict
from lstm_data import STREAM_5M_LOOKBACK
from ml_horizon import ML_HORIZON_SLUGS
from signals import compute_fusion_policy_flat_for_replay
from timeframe_config import CANONICAL_TIMEFRAME

from tools.backfill_fusion_policy_columns_v1 import _classify_failure, _incomplete_fused_sql


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "ed_console.db")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="Recompute even when all fused_move_* are set.")
    ap.add_argument("--commit-every", type=int, default=25)
    ap.add_argument("--ticker", type=str, default=None, help="Optional single ticker filter.")
    ap.add_argument(
        "--no-comparable-yield-filter",
        action="store_true",
        help="Backfill every LSTM-eligible 1m row even if no pred/outcome pair exists (max raw fused coverage; weaker for XGB vs fused eval).",
    )
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="backfill_fusion_policy_columns_expanded_v1", write_capable=not args.dry_run)

    tf = CANONICAL_TIMEFRAME
    prior_n = STREAM_5M_LOOKBACK
    lstm_sub = (
        f"(SELECT COUNT(*) FROM snapshots pr WHERE pr.ticker = snapshots.ticker "
        f"AND pr.timeframe = ? AND pr.ts_utc < snapshots.ts_utc) >= ?"
    )

    where_parts = [f"timeframe = ?", lstm_sub]
    params_tail: list[Any] = [tf, tf, prior_n]
    if args.ticker:
        where_parts.append("ticker = ?")
        params_tail.append(str(args.ticker).upper().strip())

    if not args.force:
        where_parts.append(_incomplete_fused_sql())

    comparable_any = "(" + " OR ".join(
        f"(pred_move_prob_{hz} IS NOT NULL AND outcome_move_{hz} IS NOT NULL)" for hz in ML_HORIZON_SLUGS
    ) + ")"
    if not args.no_comparable_yield_filter:
        where_parts.append(comparable_any)

    where_sql = " AND ".join(where_parts)

    q = (
        f"SELECT rowid AS _backfill_rowid_, snapshots.* FROM snapshots WHERE {where_sql} "
        f"ORDER BY ts_utc ASC"
    )
    if args.limit is not None:
        q += f" LIMIT {int(args.limit)} OFFSET {int(args.offset)}"

    summary: dict[str, Any] = {
        "tool": "backfill_fusion_policy_columns_expanded_v1",
        "db_path": str(args.db.resolve()),
        "dry_run": bool(args.dry_run),
        "lstm_prior_gate": prior_n,
        "comparable_yield_filter": not bool(args.no_comparable_yield_filter),
        "ticker_filter": args.ticker,
        "rows_attempted": 0,
        "rows_wrote_fused": 0,
        "rows_skipped": 0,
        "grade_counts": Counter(),
        "per_horizon_fused_written": Counter(),
        "failure_categories": Counter(),
    }
    failures: list[dict[str, Any]] = []

    conn = sqlite3.connect(str(args.db.resolve()))
    conn.row_factory = sqlite3.Row
    configure_sqlite_connection(conn)

    db = EdDB(str(args.db.resolve()))
    rows = conn.execute(q, tuple(params_tail)).fetchall()

    attempted = 0
    wrote = 0
    skipped = 0

    for row in rows:
        attempted += 1
        summary["rows_attempted"] = attempted
        rd = {k: row[k] for k in row.keys()}
        rowid = rd["_backfill_rowid_"]
        tkr = str(rd.get("ticker") or "")

        try:
            inp = signal_input_from_snapshot_row_dict(rd)
        except Exception as e:
            skipped += 1
            summary["failure_categories"][_classify_failure(e, "signal_input")] += 1
            failures.append({"rowid": rowid, "ticker": tkr, "stage": "signal_input", "detail": repr(e)})
            continue

        try:
            flat, hz_errs, _stack_integrity_v1 = compute_fusion_policy_flat_for_replay(inp, db)
        except Exception as e:
            skipped += 1
            summary["failure_categories"][_classify_failure(e, "stack")] += 1
            failures.append({"rowid": rowid, "ticker": tkr, "stage": "stack", "detail": repr(e)})
            continue

        if hz_errs:
            summary["failure_categories"]["PER_HORIZON_STACK"] += len(hz_errs)

        if not flat:
            skipped += 1
            failures.append({"rowid": rowid, "ticker": tkr, "stage": "fusion", "detail": "empty flat"})
            continue

        grade = fusion_replay_stack_grade_v1(flat)
        if grade:
            summary["grade_counts"][grade] += 1

        for hz in ML_HORIZON_SLUGS:
            if f"fused_move_prob_{hz}" in flat:
                summary["per_horizon_fused_written"][hz] += 1

        wrote += 1

        if not args.dry_run:
            keys = list(flat.keys())
            vals = [flat[k] for k in keys]
            sets = ", ".join(f"{k} = ?" for k in keys)
            extra_cols: list[str] = []
            extra_vals: list[Any] = []
            if grade is not None:
                extra_cols.append("fusion_replay_stack_grade_v1 = ?")
                extra_vals.append(grade)
            if extra_cols:
                conn.execute(
                    f"UPDATE snapshots SET {sets}, {', '.join(extra_cols)} WHERE rowid = ?",
                    (*vals, *extra_vals, rowid),
                )
            else:
                conn.execute(f"UPDATE snapshots SET {sets} WHERE rowid = ?", (*vals, rowid))

        if attempted % max(1, args.commit_every) == 0 and not args.dry_run:
            conn.commit()

    if not args.dry_run:
        conn.commit()

    summary["rows_wrote_fused"] = wrote
    summary["rows_skipped"] = skipped
    summary["grade_counts"] = dict(summary["grade_counts"])
    summary["per_horizon_fused_written"] = dict(summary["per_horizon_fused_written"])
    summary["failure_categories"] = dict(summary["failure_categories"])

    conn.close()

    out = ROOT / "data" / "fused_policy_backfill_expanded_summary_v1.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    failp = ROOT / "data" / "fused_policy_backfill_expanded_failures_v1.json"
    failp.write_text(json.dumps({"failures": failures[:8000], "truncated": len(failures) > 8000}, indent=2, default=str), encoding="utf-8")

    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
