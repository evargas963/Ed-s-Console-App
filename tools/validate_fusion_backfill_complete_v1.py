#!/usr/bin/env python3
"""Post-run coverage + sufficiency for complete fusion backfill (Task 7–8)."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from db import configure_sqlite_connection
from lstm_data import STREAM_5M_LOOKBACK
from ml_horizon import ML_HORIZON_SLUGS
from timeframe_config import CANONICAL_TIMEFRAME

from tools.legacy.horizon_7.backfill_fusion_policy_columns_v1 import _incomplete_fused_sql

MIN_COMPARABLE = 500


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "ed_console.db")
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="validate_fusion_backfill_complete_v1", write_capable=False)

    tf = CANONICAL_TIMEFRAME
    conn = sqlite3.connect(str(args.db.resolve()))
    configure_sqlite_connection(conn)

    summary_path = ROOT / "data" / "fusion_backfill_complete_summary_v1.json"
    backfill_meta: dict = {}
    if summary_path.is_file():
        try:
            backfill_meta = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass

    per: dict = {}
    for hz in ML_HORIZON_SLUGS:
        elig = conn.execute(
            f"SELECT COUNT(*) FROM snapshots WHERE timeframe = ? "
            f"AND pred_move_prob_{hz} IS NOT NULL AND outcome_move_{hz} IS NOT NULL",
            (tf,),
        ).fetchone()[0]
        fused_nn = conn.execute(
            f"SELECT COUNT(*) FROM snapshots WHERE timeframe = ? AND fused_move_prob_{hz} IS NOT NULL",
            (tf,),
        ).fetchone()[0]
        comp = conn.execute(
            f"SELECT COUNT(*) FROM snapshots WHERE timeframe = ? "
            f"AND pred_move_prob_{hz} IS NOT NULL AND fused_move_prob_{hz} IS NOT NULL "
            f"AND outcome_move_{hz} IS NOT NULL",
            (tf,),
        ).fetchone()[0]
        nt = conn.execute(
            f"SELECT COUNT(DISTINCT ticker) FROM snapshots WHERE timeframe = ? "
            f"AND pred_move_prob_{hz} IS NOT NULL AND fused_move_prob_{hz} IS NOT NULL "
            f"AND outcome_move_{hz} IS NOT NULL",
            (tf,),
        ).fetchone()[0]
        rng = conn.execute(
            f"SELECT MIN(ts_utc), MAX(ts_utc) FROM snapshots WHERE timeframe = ? "
            f"AND pred_move_prob_{hz} IS NOT NULL AND fused_move_prob_{hz} IS NOT NULL "
            f"AND outcome_move_{hz} IS NOT NULL",
            (tf,),
        ).fetchone()
        rate = (100.0 * fused_nn / elig) if elig else 0.0
        suff = "PASS" if comp >= MIN_COMPARABLE else "FAIL"
        per[hz] = {
            "eligible_rows_pred_outcome_1m": int(elig),
            "fused_move_non_null_rows": int(fused_nn),
            "comparable_rows": int(comp),
            "distinct_tickers_comparable": int(nt),
            "ts_utc_min": rng[0],
            "ts_utc_max": rng[1],
            "fused_coverage_vs_eligible_pct": round(rate, 4),
            "comparable_sufficiency_ge_500": suff,
        }

    min_comp = min(per[h]["comparable_rows"] for h in ML_HORIZON_SLUGS)

    prior = STREAM_5M_LOOKBACK
    lstm_sub = (
        f"(SELECT COUNT(*) FROM snapshots pr WHERE pr.ticker = snapshots.ticker "
        f"AND pr.timeframe = ? AND pr.ts_utc < snapshots.ts_utc) >= ?"
    )
    comp_any = "(" + " OR ".join(
        f"(pred_move_prob_{hz} IS NOT NULL AND outcome_move_{hz} IS NOT NULL)" for hz in ML_HORIZON_SLUGS
    ) + ")"
    rem_q = (
        f"SELECT COUNT(*) FROM snapshots WHERE timeframe = ? AND {lstm_sub} AND {_incomplete_fused_sql()} AND {comp_any}"
    )
    remaining_incomplete = int(conn.execute(rem_q, (tf, tf, prior)).fetchone()[0])

    full_run = False
    if backfill_meta and backfill_meta.get("expected_rows_in_query"):
        exp = int(backfill_meta["expected_rows_in_query"])
        att = backfill_meta.get("rows_attempted")
        interrupted = bool(backfill_meta.get("interrupted_or_partial"))
        full_run = (
            backfill_meta.get("limit_debug") is None
            and att is not None
            and int(att) == exp
            and exp > 0
            and not interrupted
        )

    verdict = "PASS"
    if not full_run:
        verdict = "FAIL"
    if min_comp < MIN_COMPARABLE:
        verdict = "FAIL"
    if remaining_incomplete > 0:
        verdict = "FAIL"

    out = {
        "db_path": str(args.db.resolve()),
        "backfill_summary_path": str(summary_path),
        "BACKFILL_PROGRESS_SUMMARY": backfill_meta,
        "FINAL_COVERAGE_BY_HORIZON": per,
        "COMPARABLE_ROW_COUNTS": {hz: per[hz]["comparable_rows"] for hz in ML_HORIZON_SLUGS},
        "SUFFICIENCY_STATUS": {
            "min_comparable_across_horizons": min_comp,
            "required_min_comparable": MIN_COMPARABLE,
            "per_horizon_pass_ge_500": {hz: per[hz]["comparable_rows"] >= MIN_COMPARABLE for hz in ML_HORIZON_SLUGS},
        },
        "full_eligible_backfill_completed_verified": full_run,
        "FULL_DATASET_RUN_WITHOUT_LIMIT": bool(backfill_meta.get("limit_debug") is None) if backfill_meta else False,
        "ATTEMPTED_EQUALS_EXPECTED": full_run,
        "remaining_incomplete_backfill_queue_rows": remaining_incomplete,
        "FINAL_VERDICT": verdict,
    }

    outp = ROOT / "data" / "fusion_backfill_complete_validation_v1.json"
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(json.dumps(out, indent=2, default=str))
    conn.close()
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
