#!/usr/bin/env python3
"""
Complete fusion replay: populate fused_* over the maximum valid historical domain.

Per-horizon eligibility (for coverage stats): timeframe=1m, pred_move_prob_{hz}, outcome_move_{hz}.
Backfill attempts: LSTM causal gate (>=60 prior 1m rows) + union of per-horizon pred∧outcome
(same row set as expanded v1) + skip rows already fully fused (idempotent) unless --force.

No default row cap — use --limit only for debugging. Single-writer: run one instance at a time.

Resume: re-run the same command; completed rows (all fused_move_* non-null) are skipped.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
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

from tools.legacy.horizon_7.backfill_fusion_policy_columns_v1 import _incomplete_fused_sql
import logging

log = logging.getLogger(__name__)



def _sqlite_exec_retry(conn: sqlite3.Connection, sql: str, params: tuple, *, label: str = "") -> None:
    """Retry bounded for transient SQLITE_BUSY / locked under concurrent readers (e.g. EdDB)."""
    last: BaseException | None = None
    for attempt in range(80):
        try:
            conn.execute(sql, params)
            return
        except sqlite3.OperationalError as e:
            last = e
            msg = str(e).lower()
            if "locked" not in msg and "busy" not in msg:
                raise
            time.sleep(min(2.0, 0.02 * (1.5**min(attempt, 20))))
    raise last if last else RuntimeError(label or "sqlite retry exhausted")


def _classify_failure_complete(exc: BaseException, hint: str = "") -> str:
    from features.fusion_model_input import FusionModelInputError
    from features.lstm_sequence_input import LstmSequenceInputError, TransformerSequenceInputError
    from features.monte_carlo_stack_input import MonteCarloStackInputError
    from features.xgb_model_input import XgbInferenceInputError
    from ml_predict import ParallelRuntimeArtifactError

    s = f"{hint} {exc!r}".lower()
    if isinstance(exc, MonteCarloStackInputError):
        return "INSUFFICIENT_HISTORY"
    if isinstance(exc, (XgbInferenceInputError, LstmSequenceInputError, TransformerSequenceInputError, FusionModelInputError)):
        if "snapshot" in s or "60" in s or "sequence" in s or "history" in s:
            return "INSUFFICIENT_HISTORY"
        return "FEATURE_RECONSTRUCTION_FAILURE"
    if isinstance(exc, ParallelRuntimeArtifactError):
        return "MISSING_ARTIFACTS"
    if isinstance(exc, FileNotFoundError):
        return "MISSING_ARTIFACTS"
    if isinstance(exc, ValueError) and "inference" in s:
        return "FEATURE_RECONSTRUCTION_FAILURE"
    if "no such file" in s or ".pkl" in s or "artifact" in s:
        return "MISSING_ARTIFACTS"
    if isinstance(exc, (ImportError, OSError)) and "model" in s:
        return "MODEL_LOAD_FAILURE"
    return "OTHER"


def _max_eligible_per_horizon(conn: sqlite3.Connection) -> dict[str, Any]:
    tf = CANONICAL_TIMEFRAME
    out: dict[str, Any] = {"timeframe": tf, "per_horizon_pred_and_outcome_move": {}}
    for hz in ML_HORIZON_SLUGS:
        n = conn.execute(
            f"SELECT COUNT(*) FROM snapshots WHERE timeframe = ? "
            f"AND pred_move_prob_{hz} IS NOT NULL AND outcome_move_{hz} IS NOT NULL",
            (tf,),
        ).fetchone()[0]
        out["per_horizon_pred_and_outcome_move"][hz] = int(n)
    sub = (
        "(SELECT COUNT(*) FROM snapshots pr WHERE pr.ticker = snapshots.ticker "
        "AND pr.timeframe = ? AND pr.ts_utc < snapshots.ts_utc) >= ?"
    )
    out["per_horizon_pred_outcome_and_lstm_prior_ge_60"] = {}
    for hz in ML_HORIZON_SLUGS:
        n = conn.execute(
            f"SELECT COUNT(*) FROM snapshots WHERE timeframe = ? AND {sub} "
            f"AND pred_move_prob_{hz} IS NOT NULL AND outcome_move_{hz} IS NOT NULL",
            (tf, tf, STREAM_5M_LOOKBACK),
        ).fetchone()[0]
        out["per_horizon_pred_outcome_and_lstm_prior_ge_60"][hz] = int(n)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "ed_console.db")
    ap.add_argument(
        "--limit",
        type=int,
        default=None,
        help="DEBUG ONLY: max rows to process. Omit for full backfill.",
    )
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="Recompute even when all fused_move_* are set.")
    ap.add_argument(
        "--commit-every",
        type=int,
        default=1,
        help="Commit SQLite after every N rows (default 1 minimizes locked transaction duration).",
    )
    ap.add_argument(
        "--progress-every",
        type=int,
        default=10,
        help="Write progress JSON every N rows (lower = fresher resume checkpoints; fusion is slow).",
    )
    ap.add_argument("--report-only", action="store_true", help="Print MAX_ELIGIBLE_ROW_COUNTS_PER_HORIZON and exit.")
    ap.add_argument("--ticker", type=str, default=None)
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="backfill_fusion_policy_complete_v1", write_capable=not args.dry_run)

    tf = CANONICAL_TIMEFRAME
    prior_n = STREAM_5M_LOOKBACK
    lstm_sub = (
        "(SELECT COUNT(*) FROM snapshots pr WHERE pr.ticker = snapshots.ticker "
        "AND pr.timeframe = ? AND pr.ts_utc < snapshots.ts_utc) >= ?"
    )

    conn = sqlite3.connect(str(args.db.resolve()))
    conn.row_factory = sqlite3.Row
    configure_sqlite_connection(conn, busy_timeout_ms=120000)

    max_eligible = _max_eligible_per_horizon(conn)
    outp0 = ROOT / "data" / "fused_policy_max_eligible_per_horizon_v1.json"
    outp0.parent.mkdir(parents=True, exist_ok=True)
    outp0.write_text(json.dumps(max_eligible, indent=2), encoding="utf-8")
    print(json.dumps({"MAX_ELIGIBLE_ROW_COUNTS_PER_HORIZON": max_eligible}, indent=2))
    if args.report_only:
        conn.close()
        return 0

    where_parts = ["timeframe = ?", lstm_sub]
    params_tail: list[Any] = [tf, tf, prior_n]
    if args.ticker:
        where_parts.append("ticker = ?")
        params_tail.append(str(args.ticker).upper().strip())

    if not args.force:
        where_parts.append(_incomplete_fused_sql())

    comparable_any = "(" + " OR ".join(
        f"(pred_move_prob_{hz} IS NOT NULL AND outcome_move_{hz} IS NOT NULL)" for hz in ML_HORIZON_SLUGS
    ) + ")"
    where_parts.append(comparable_any)

    where_sql = " AND ".join(where_parts)
    q = (
        f"SELECT rowid AS _backfill_rowid_, snapshots.* FROM snapshots WHERE {where_sql} "
        f"ORDER BY ts_utc ASC, rowid ASC"
    )
    if args.limit is not None:
        q += f" LIMIT {int(args.limit)}"

    params = tuple(params_tail)

    expected_n = int(conn.execute(f"SELECT COUNT(*) FROM snapshots WHERE {where_sql}", params).fetchone()[0])
    if args.limit is not None:
        expected_n = min(expected_n, int(args.limit))
    summary: dict[str, Any] = {
        "tool": "backfill_fusion_policy_complete_v1",
        "db_path": str(args.db.resolve()),
        "dry_run": bool(args.dry_run),
        "limit_debug": args.limit,
        "expected_rows_in_query": int(expected_n),
        "lstm_prior_gate": prior_n,
        "started_ts_utc": time.time(),
        "rows_attempted": 0,
        "rows_wrote_any_fused": 0,
        "rows_skipped": 0,
        "per_horizon_fused_written_this_run": Counter(),
        "failure_categories": Counter(),
    }
    failures: list[dict[str, Any]] = []

    db = EdDB(str(args.db.resolve()))
    progress_path = ROOT / "data" / "fusion_backfill_complete_progress_v1.json"
    fail_path = ROOT / "data" / "fusion_backfill_complete_failures_v1.jsonl"

    # Materialize rows so no open SELECT cursor during stack replay + UPDATE (avoids sqlite locked).
    rows = conn.execute(q, params).fetchall()
    attempted = 0
    wrote = 0
    skipped = 0
    finished_normally = False

    try:
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
                cat = _classify_failure_complete(e, "signal_input")
                summary["failure_categories"][cat] += 1
                rec = {"rowid": rowid, "ticker": tkr, "stage": "signal_input", "category": cat, "detail": repr(e)}
                failures.append(rec)
                if not args.dry_run:
                    with open(fail_path, "a", encoding="utf-8") as f:
                        f.write(json.dumps(rec, default=str) + "\n")
                continue

            try:
                flat, hz_errs, _stack_integrity_v1 = compute_fusion_policy_flat_for_replay(inp, db)
            except Exception as e:
                skipped += 1
                cat = _classify_failure_complete(e, "stack")
                summary["failure_categories"][cat] += 1
                rec = {
                    "rowid": rowid,
                    "ticker": tkr,
                    "stage": "stack",
                    "category": cat,
                    "detail": repr(e),
                    "traceback": traceback.format_exc()[-6000:],
                }
                failures.append(rec)
                if not args.dry_run:
                    with open(fail_path, "a", encoding="utf-8") as f:
                        f.write(json.dumps(rec, default=str) + "\n")
                continue

            if hz_errs:
                for h in hz_errs:
                    summary["failure_categories"]["PER_HORIZON_STACK"] += 1

            if not flat:
                skipped += 1
                cat = "OTHER"
                rec = {"rowid": rowid, "ticker": tkr, "stage": "fusion", "category": cat, "detail": "empty flat", "horizon_errors": hz_errs}
                failures.append(rec)
                if not args.dry_run:
                    with open(fail_path, "a", encoding="utf-8") as f:
                        f.write(json.dumps(rec, default=str) + "\n")
                continue

            grade = fusion_replay_stack_grade_v1(flat)
            for hz in ML_HORIZON_SLUGS:
                if f"fused_move_prob_{hz}" in flat:
                    summary["per_horizon_fused_written_this_run"][hz] += 1

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
                    _sqlite_exec_retry(
                        conn,
                        f"UPDATE snapshots SET {sets}, {', '.join(extra_cols)} WHERE rowid = ?",
                        (*vals, *extra_vals, rowid),
                        label="update+fused+grade",
                    )
                else:
                    _sqlite_exec_retry(conn, f"UPDATE snapshots SET {sets} WHERE rowid = ?", (*vals, rowid), label="update+fused")

            if attempted % max(1, args.commit_every) == 0 and not args.dry_run:
                try:
                    conn.commit()
                except sqlite3.OperationalError:
                    time.sleep(0.2)
                    conn.commit()

            if attempted % max(1, args.progress_every) == 0 and not args.dry_run:
                summary["rows_wrote_any_fused"] = wrote
                summary["rows_skipped"] = skipped
                summary["per_horizon_fused_written_this_run"] = dict(summary["per_horizon_fused_written_this_run"])
                summary["failure_categories"] = dict(summary["failure_categories"])
                summary["last_rowid"] = rowid
                summary["last_ts_utc"] = rd.get("ts_utc")
                progress_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")

        finished_normally = True
    finally:
        if not args.dry_run:
            try:
                conn.commit()
            except sqlite3.OperationalError:
                time.sleep(0.2)
                conn.commit()

        summary["rows_wrote_any_fused"] = wrote
        summary["rows_skipped"] = skipped
        summary["finished_ts_utc"] = time.time()
        summary["per_horizon_fused_written_this_run"] = dict(summary["per_horizon_fused_written_this_run"])
        summary["failure_categories"] = dict(summary["failure_categories"])
        summary["failures_sample_n"] = len(failures)
        summary["interrupted_or_partial"] = not finished_normally or attempted < int(expected_n)

        out_sum = ROOT / "data" / "fusion_backfill_complete_summary_v1.json"
        out_sum.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
        if not args.dry_run:
            progress_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")

        fail_json = ROOT / "data" / "fusion_backfill_complete_failures_sample_v1.json"
        fail_json.write_text(
            json.dumps({"failures": failures[:5000], "truncated": len(failures) > 5000}, indent=2, default=str),
            encoding="utf-8",
        )

        try:
            conn.close()
        except Exception as e:
            log.debug("conn close: %s", e, exc_info=True)
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
