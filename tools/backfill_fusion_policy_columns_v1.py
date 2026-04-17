#!/usr/bin/env python3
"""
Replay governed stack (XGB + LSTM + Transformer → MC → Fusion) on historical snapshot rows
and persist fused_* policy columns. No synthetic values; failures leave NULL + logged reasons.
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
from features.replay_signal_input_v1 import signal_input_from_snapshot_row_dict
from lstm_data import STREAM_5M_LOOKBACK
from ml_horizon import ML_HORIZON_SLUGS
from signals import compute_fusion_policy_flat_for_replay
from timeframe_config import CANONICAL_TIMEFRAME

# Base outcome contract (schema + legacy directional outcomes + bars anchor).
_GO_BASE = """
timeframe = '1m'
AND COALESCE(horizon_outcome_schema_version, 3) = 3
AND outcome_1c IS NOT NULL AND outcome_1c_pts IS NOT NULL
AND outcome_3c IS NOT NULL AND outcome_3c_pts IS NOT NULL
AND outcome_5c IS NOT NULL AND outcome_5c_pts IS NOT NULL
AND outcome_8c IS NOT NULL AND outcome_8c_pts IS NOT NULL
AND outcome_13c IS NOT NULL AND outcome_13c_pts IS NOT NULL
AND outcome_15c IS NOT NULL AND outcome_15c_pts IS NOT NULL
AND outcome_60c IS NOT NULL AND outcome_60c_pts IS NOT NULL
AND EXISTS (SELECT 1 FROM price_bars_1m p WHERE p.ticker = snapshots.ticker AND p.bar_end_ts_utc <= snapshots.ts_utc)
AND (
  SELECT COUNT(*) FROM snapshots pr
  WHERE pr.ticker = snapshots.ticker AND pr.timeframe = ?
  AND pr.ts_utc < snapshots.ts_utc
) >= ?
"""

# Movement-target labels on all governed horizons — matches audit `policy_ticker_domain` / Phase 8 substrate.
_MOVEMENT_ALL = " AND ".join(f"outcome_move_{hz} IS NOT NULL" for hz in ML_HORIZON_SLUGS)

# Full governed predicate for apples-to-apples fused vs pred_move_prob_* comparison.
GOV_WHERE = f"""
{_GO_BASE.strip()}
AND {_MOVEMENT_ALL}
""".strip()

def _classify_failure(exc: BaseException, hint: str = "") -> str:
    from features.fusion_model_input import FusionModelInputError
    from features.lstm_sequence_input import LstmSequenceInputError, TransformerSequenceInputError
    from features.monte_carlo_stack_input import MonteCarloStackInputError
    from features.xgb_model_input import XgbInferenceInputError
    from ml_predict import ParallelRuntimeArtifactError

    s = f"{hint} {exc!r}".lower()
    if isinstance(exc, MonteCarloStackInputError):
        return "HISTORICAL_CONTEXT_INSUFFICIENT"
    if isinstance(
        exc,
        (XgbInferenceInputError, LstmSequenceInputError, TransformerSequenceInputError, FusionModelInputError),
    ):
        return "FEATURE_RECONSTRUCTION_FAILURE"
    if isinstance(exc, ParallelRuntimeArtifactError):
        return "MISSING_ARTIFACTS"
    if isinstance(exc, FileNotFoundError):
        return "MISSING_ARTIFACTS"
    if isinstance(exc, ValueError) and "inference" in s:
        return "FEATURE_RECONSTRUCTION_FAILURE"
    if "no such file" in s or ".pkl" in s or "artifact" in s:
        return "MISSING_ARTIFACTS"
    if "sequence" in s or "bar" in s or "history" in s:
        return "HISTORICAL_CONTEXT_INSUFFICIENT"
    if isinstance(exc, (ImportError, OSError)) and "model" in s:
        return "MODEL_LOAD_FAILURE"
    return "OTHER"


def _policy_tickers(root: Path) -> list[str]:
    p = root / "data" / "ticker_readiness_matrix_v1.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    return sorted(
        r["ticker"]
        for r in data["tickers"]
        if r.get("final_readiness_verdict") == "READY_GLOBAL_STANDARD" and r.get("policy_status") == "POLICY_ELIGIBLE"
    )


def _incomplete_fused_sql() -> str:
    parts = [f"fused_move_prob_{hz} IS NULL" for hz in ML_HORIZON_SLUGS]
    return "(" + " OR ".join(parts) + ")"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "ed_console.db")
    ap.add_argument("--limit", type=int, default=None, help="Max rows to process (debug).")
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true", help="Compute but do not write SQLite.")
    ap.add_argument("--force", action="store_true", help="Also process rows that already have all fused_move_* set.")
    ap.add_argument("--commit-every", type=int, default=20)
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="backfill_fusion_policy_columns_v1", write_capable=not args.dry_run)

    allowed = _policy_tickers(ROOT)
    ph = ",".join(["?"] * len(allowed))

    where_extra = "" if args.force else f" AND {_incomplete_fused_sql()} "
    q = (
        f"SELECT rowid AS _backfill_rowid_, snapshots.* FROM snapshots WHERE ticker IN ({ph}) AND {GOV_WHERE} "
        f"{where_extra} ORDER BY ts_utc ASC"
    )
    if args.limit is not None:
        q += f" LIMIT {int(args.limit)} OFFSET {int(args.offset)}"

    summary: dict[str, Any] = {
        "tool": "backfill_fusion_policy_columns_v1",
        "db_path": str(args.db.resolve()),
        "dry_run": bool(args.dry_run),
        "prior_snapshot_gate": STREAM_5M_LOOKBACK,
        "prior_snapshot_gate_timeframe": CANONICAL_TIMEFRAME,
        "movement_outcome_all_horizons_required": True,
        "policy_tickers_n": len(allowed),
        "rows_attempted": 0,
        "rows_backfilled_ok": 0,
        "rows_skipped": 0,
        "rows_partial": 0,
        "failure_categories": Counter(),
        "per_ticker_attempted": Counter(),
        "per_ticker_backfilled": Counter(),
        "per_horizon_success": Counter(),
        "pred_fused_intersection_sample": {},
    }
    failures: list[dict[str, Any]] = []

    conn = sqlite3.connect(str(args.db.resolve()))
    conn.row_factory = sqlite3.Row
    configure_sqlite_connection(conn)

    cur = conn.execute(q, tuple(allowed) + (CANONICAL_TIMEFRAME, STREAM_5M_LOOKBACK))
    rows = cur.fetchall()

    db = EdDB(str(args.db.resolve())) if not args.dry_run else EdDB(str(args.db.resolve()))

    attempted = 0
    ok_full = 0
    partial = 0
    skipped = 0

    pred_cols = [f"pred_move_prob_{hz}" for hz in ML_HORIZON_SLUGS]
    fused_cols = [f"fused_move_prob_{hz}" for hz in ML_HORIZON_SLUGS]

    for row in rows:
        attempted += 1
        summary["rows_attempted"] = attempted
        rd = {k: row[k] for k in row.keys()}
        rowid = rd["_backfill_rowid_"]
        tkr = str(rd.get("ticker") or "")
        summary["per_ticker_attempted"][tkr] += 1

        try:
            inp = signal_input_from_snapshot_row_dict(rd)
        except Exception as e:
            skipped += 1
            cat = _classify_failure(e, "signal_input")
            summary["failure_categories"][cat] += 1
            failures.append(
                {
                    "rowid": rowid,
                    "ticker": tkr,
                    "ts_utc": rd.get("ts_utc"),
                    "stage": "signal_input",
                    "category": cat,
                    "detail": repr(e),
                }
            )
            continue

        try:
            flat, hz_errs, _stack_integrity_v1 = compute_fusion_policy_flat_for_replay(inp, db)
        except Exception as e:
            skipped += 1
            cat = _classify_failure(e, "stack")
            summary["failure_categories"][cat] += 1
            failures.append(
                {
                    "rowid": rowid,
                    "ticker": tkr,
                    "ts_utc": rd.get("ts_utc"),
                    "stage": "full_stack",
                    "category": cat,
                    "detail": repr(e),
                    "traceback": traceback.format_exc()[-4000:],
                }
            )
            continue

        if hz_errs:
            summary["failure_categories"]["PER_HORIZON_STACK"] += len(hz_errs)
        for hz in ML_HORIZON_SLUGS:
            if f"fused_move_prob_{hz}" in flat:
                summary["per_horizon_success"][hz] += 1

        if len(flat) == 0:
            skipped += 1
            failures.append(
                {
                    "rowid": rowid,
                    "ticker": tkr,
                    "ts_utc": rd.get("ts_utc"),
                    "stage": "fusion",
                    "category": "OTHER",
                    "detail": "no fused columns produced (all horizons failed)",
                    "horizon_errors": hz_errs,
                }
            )
            continue

        if len(hz_errs) > 0:
            partial += 1
        else:
            ok_full += 1
        summary["per_ticker_backfilled"][tkr] += 1

        if not args.dry_run and flat:
            keys = list(flat.keys())
            vals = [flat[k] for k in keys]
            sets = ", ".join(f"{k} = ?" for k in keys)
            conn.execute(f"UPDATE snapshots SET {sets} WHERE rowid = ?", (*vals, rowid))

        if attempted % max(1, args.commit_every) == 0 and not args.dry_run:
            conn.commit()

    if not args.dry_run:
        conn.commit()

    summary["rows_backfilled_ok"] = ok_full + partial
    summary["rows_skipped"] = skipped
    summary["rows_partial"] = partial
    summary["failure_categories"] = dict(summary["failure_categories"])
    summary["per_ticker_attempted"] = dict(summary["per_ticker_attempted"])
    summary["per_ticker_backfilled"] = dict(summary["per_ticker_backfilled"])
    summary["per_horizon_success"] = dict(summary["per_horizon_success"])

    # Intersection: rows where pred_move and fused_move both non-null (governed query subset)
    inter_q = (
        f"SELECT COUNT(*) AS n FROM snapshots WHERE ticker IN ({ph}) AND {GOV_WHERE} "
        f"AND pred_move_prob_5c IS NOT NULL AND fused_move_prob_5c IS NOT NULL"
    )
    summary["pred_fused_intersection_sample"] = {
        "governed_rows_pred5c_and_fused5c_nonnull": conn.execute(
            inter_q, tuple(allowed) + (CANONICAL_TIMEFRAME, STREAM_5M_LOOKBACK)
        ).fetchone()["n"],
    }

    conn.close()

    out_sum = ROOT / "data" / "fused_policy_backfill_summary_v1.json"
    out_fail = ROOT / "data" / "fused_policy_backfill_failures_v1.json"
    out_sum.parent.mkdir(parents=True, exist_ok=True)
    out_sum.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    out_fail.write_text(json.dumps({"failures": failures[:5000], "truncated": len(failures) > 5000}, indent=2, default=str), encoding="utf-8")

    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
