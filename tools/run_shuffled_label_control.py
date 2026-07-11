#!/usr/bin/env python3
"""Governed production shuffled-label control (ML-PIPE-V2 Phase 6 interface).

THE documented operator interface for production negative-control runs:

  python tools/run_shuffled_label_control.py --ticker SPY --horizon 5c \\
      --seed 20260711 --dry-run          # validate plan (no copy, no training)
  python tools/run_shuffled_label_control.py --ticker SPY --horizon 5c \\
      --seed 20260711                    # full control run (operator host; hours)

Mechanism (production paths preserved byte-identically):
1. Walk-forward split via the SAME authority the scheduler uses
   (training_cache.split_sessions_walk_forward over RTH session days).
2. Control DB = sqlite backup copy of the source DB; then ONLY the target
   label column (outcome_<hz>) on TRAIN-window rows of the selected ticker is
   permuted (seeded, multiset-preserving — class balance identical).
3. Training runs the UNCHANGED production trainer (ml_scheduler._train_parallel)
   against the control DB; evaluation runs the UNCHANGED evaluator
   (_evaluate_parallel_on_full_rth) against the ORIGINAL DB (true labels).
4. Machine-readable evidence JSON with pinned identity (seed, ticker, horizon,
   HEAD SHA, split, label histograms, tolerance verdict).

Preregistered tolerance: shuffled balanced accuracy must be <= chance + 0.06
(one-sided upper; same contract as tests/test_shuffled_label_control_v1.py).
"""
from __future__ import annotations

import argparse
import json
import random
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

CHANCE = 1.0 / 3.0


def _snapshot_table() -> str:
    """Canonical 1m training table authority (same source the trainers read)."""
    from timeframe_config import SNAPSHOT_TABLE_1M

    return SNAPSHOT_TABLE_1M
SHUFFLED_BALANCED_ACC_UPPER_TOLERANCE = 0.06  # preregistered; do not tune post-hoc
DEFAULT_SEED = 20260711


def _head_sha() -> str:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, timeout=20
        )
        return r.stdout.strip()
    except Exception:
        return "UNKNOWN"


def label_histogram(db_path: str, ticker: str, label_col: str, days: set[str]) -> dict[str, int]:
    con = sqlite3.connect(db_path)
    try:
        rows = con.execute(
            f"SELECT {label_col}, COUNT(*) FROM {_snapshot_table()} "
            f"WHERE ticker = ? AND timeframe = '1m' AND {label_col} IS NOT NULL "
            f"AND substr(ts_et, 1, 10) IN ({','.join('?' * len(days))}) "
            f"GROUP BY {label_col}",
            (ticker.upper(), *sorted(days)),
        ).fetchall()
    finally:
        con.close()
    return {str(k): int(v) for k, v in rows}


def build_control_db(
    *,
    source_db: str,
    control_db: str,
    ticker: str,
    label_col: str,
    train_days: set[str],
    seed: int,
) -> dict:
    """Copy source → control (sqlite backup API), then permute ONLY the label
    column on train-window rows of the ticker. Returns the permutation record."""
    src = sqlite3.connect(source_db)
    dst = sqlite3.connect(control_db)
    try:
        src.backup(dst)
    finally:
        src.close()
    try:
        day_params = sorted(train_days)
        rows = dst.execute(
            f"SELECT snapshot_id, {label_col} FROM {_snapshot_table()} "
            f"WHERE ticker = ? AND timeframe = '1m' AND {label_col} IS NOT NULL "
            f"AND substr(ts_et, 1, 10) IN ({','.join('?' * len(day_params))}) "
            f"ORDER BY snapshot_id",
            (ticker.upper(), *day_params),
        ).fetchall()
        ids = [r[0] for r in rows]
        labels = [r[1] for r in rows]
        rng = random.Random(int(seed))
        permuted = list(labels)
        rng.shuffle(permuted)
        dst.executemany(
            f"UPDATE {_snapshot_table()} SET {label_col} = ? WHERE snapshot_id = ?",
            list(zip(permuted, ids)),
        )
        dst.commit()
        moved = sum(1 for a, b in zip(labels, permuted) if a != b)
        return {
            "rows_in_train_window": len(ids),
            "rows_with_label_moved": moved,
            "label_multiset_preserved": sorted(map(str, labels)) == sorted(map(str, permuted)),
            "seed": int(seed),
        }
    finally:
        dst.close()


def build_plan(*, db_path: str, ticker: str, hz: str, seed: int) -> dict:
    from ml_horizon import outcome_column
    from training_cache import db_distinct_rth_et_dates_for_ticker, split_sessions_walk_forward

    label_col = outcome_column(hz)
    days = db_distinct_rth_et_dates_for_ticker(db_path, ticker.upper(), label_column=label_col)
    if len(days) < 10:
        return {"ok": False, "error": f"need >= 10 RTH sessions, have {len(days)}"}
    train_days, val_days = split_sessions_walk_forward(days)
    hist = label_histogram(db_path, ticker, label_col, set(train_days))
    return {
        "ok": True,
        "interface": "tools/run_shuffled_label_control.py",
        "ticker": ticker.upper(),
        "horizon": hz,
        "label_column": label_col,
        "seed": int(seed),
        "head_sha": _head_sha(),
        "train_sessions": len(train_days),
        "val_sessions": len(val_days),
        "train_day_range": [train_days[0], train_days[-1]] if train_days else [],
        "val_days": list(val_days),
        "train_label_histogram": hist,
        "preregistered_tolerance": {
            "chance": CHANCE,
            "shuffled_balanced_acc_upper": CHANCE + SHUFFLED_BALANCED_ACC_UPPER_TOLERANCE,
            "rule": "shuffled balanced accuracy must be <= chance + 0.06 (one-sided)",
        },
        "production_paths": {
            "trainer": "ml_scheduler._train_parallel (unchanged)",
            "evaluator": "ml_scheduler._evaluate_parallel_on_full_rth vs ORIGINAL db (true labels)",
            "only_difference": f"{_snapshot_table()}.{label_col} permuted on train-window {ticker.upper()} rows in the control DB copy",
        },
    }


def run_control(
    *,
    db_path: str,
    ticker: str,
    hz: str,
    seed: int,
    work_dir: str,
    evidence_path: str,
) -> dict:
    from ml_horizon import outcome_column
    from ml_scheduler import _evaluate_parallel_on_full_rth, _train_parallel
    from training_cache import db_distinct_rth_et_dates_for_ticker, split_sessions_walk_forward

    plan = build_plan(db_path=db_path, ticker=ticker, hz=hz, seed=seed)
    if not plan.get("ok"):
        return plan
    label_col = outcome_column(hz)
    days = db_distinct_rth_et_dates_for_ticker(db_path, ticker.upper(), label_column=label_col)
    train_days, val_days = split_sessions_walk_forward(days)

    wd = Path(work_dir)
    wd.mkdir(parents=True, exist_ok=True)
    control_db = str(wd / f"control_{ticker.upper()}_{hz}_seed{seed}.db")
    perm = build_control_db(
        source_db=db_path,
        control_db=control_db,
        ticker=ticker,
        label_col=label_col,
        train_days=set(train_days),
        seed=seed,
    )
    model_dir = wd / f"models_{ticker.upper()}_{hz}_seed{seed}"
    _train_parallel(
        ticker.upper(),
        control_db,
        out_dir=model_dir,
        allowed_et_dates=set(train_days),
        bypass_cache=True,
        ml_horizon_slug=hz,
    )
    acc, bal, n, ll, realized = _evaluate_parallel_on_full_rth(
        db_path,
        ticker.upper(),
        model_dir,
        allowed_et_dates=set(val_days),
        target_column=label_col,
    )
    upper = CHANCE + SHUFFLED_BALANCED_ACC_UPPER_TOLERANCE
    evidence = {
        **plan,
        "permutation": perm,
        "control_db": control_db,
        "model_dir": str(model_dir),
        "results": {
            "accuracy": acc,
            "balanced_accuracy": bal,
            "n_rows_scored": n,
            "log_loss": ll,
            "execution_economics_measurable": (realized or {}).get("execution_economics_measurable"),
        },
        "verdict": {
            "collapsed_to_chance": bool(bal <= upper),
            "retained_edge_requires_leakage_investigation": bool(bal > upper),
        },
        "completed_at_epoch": time.time(),
    }
    Path(evidence_path).write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")
    return evidence


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--horizon", required=True, help="1c | 5c | 15c | 60c")
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--db", default=str(REPO_ROOT / "data" / "ed_console.db"))
    ap.add_argument("--work-dir", default=str(REPO_ROOT / "models" / "shuffled_label_control"))
    ap.add_argument("--evidence", default=None, help="evidence JSON output path")
    ap.add_argument("--dry-run", action="store_true", help="validate plan only (no copy/training)")
    args = ap.parse_args()

    from ml_horizon import normalize_ml_horizon_slug

    hz = normalize_ml_horizon_slug(args.horizon)
    if args.dry_run:
        plan = build_plan(db_path=args.db, ticker=args.ticker, hz=hz, seed=args.seed)
        print(json.dumps(plan, indent=2, sort_keys=True))
        return 0 if plan.get("ok") else 1
    evidence_path = args.evidence or str(
        Path(args.work_dir) / f"evidence_{args.ticker.upper()}_{hz}_seed{args.seed}.json"
    )
    out = run_control(
        db_path=args.db,
        ticker=args.ticker,
        hz=hz,
        seed=args.seed,
        work_dir=args.work_dir,
        evidence_path=evidence_path,
    )
    print(json.dumps({k: out[k] for k in out if k not in ("val_days",)}, indent=2, sort_keys=True, default=str))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
