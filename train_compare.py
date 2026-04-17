#!/usr/bin/env python3
"""
train_compare.py — Parallel vs Cascade using the same training + eval entry points as ml_scheduler.

Training: ml_scheduler._train_parallel / _train_cascade (identical to nightly run_once).
Sessions: training_cache.db_distinct_rth_et_dates_for_ticker (same ordered RTH ET dates as rolling windows).
Data slices: ml_train.load_data(..., allowed_et_dates=...) — same SQL as production.
Evaluation: ml_scheduler._evaluate_parallel_on_full_rth / _evaluate_cascade_on_full_rth with the same
            allowed_et_dates set so both architectures are scored on identical rows.
Promotion tie-break: same rule as run_once (accuracy, then balanced_accuracy).
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Set

SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR))

from db import DB_PATH
from ml_horizon import DEFAULT_ML_HORIZON_SLUG, normalize_ml_horizon_slug, outcome_column
COMPARE_DIR = SCRIPT_DIR / "models" / "compare_temp"
COMPARE_PARALLEL = COMPARE_DIR / "parallel_SPY"
COMPARE_CASCADE = COMPARE_DIR / "cascade_SPY"
REPORT_PATH = SCRIPT_DIR / "models" / "comparison_report.txt"

TICKER = "SPY"


def _safe_stdout_ctx():
    _real = sys.stdout

    class _Writable:
        def write(self, s):
            try:
                _real.write(s)
            except UnicodeEncodeError:
                _real.write(s.encode("ascii", errors="replace").decode("ascii"))

        def flush(self):
            _real.flush()

    return _Writable()


def _compute_baseline(val_df, label_col: str):
    rules_map = {"long": "up", "short": "down", "wait": "flat"}
    valid = val_df[label_col].notna() & val_df["rules_signal"].notna()
    df = val_df[valid].copy()
    if len(df) == 0:
        return 0.0
    pred = df["rules_signal"].str.lower().map(rules_map).fillna("flat")
    actual = df[label_col].str.lower()
    return float((pred == actual).mean())


def _rel_artifacts(root: Path, basenames: list[str]) -> dict:
    rel = {}
    for n in basenames:
        p = root / n
        if p.is_file():
            try:
                rel[n] = str(p.relative_to(SCRIPT_DIR))
            except ValueError:
                rel[n] = str(p.resolve())
    return rel


def validate_eval_slice_parity(
    n_val_tabular: int,
    n_parallel: int,
    n_cascade: int,
    val_days: Set[str],
) -> None:
    """Hard checks: ml_train.load_data(val) row count matches evaluators; both arches same n_rows."""
    if n_parallel != n_cascade:
        raise RuntimeError(
            f"eval slice mismatch: parallel n_rows={n_parallel} cascade n_rows={n_cascade} "
            f"val_days={sorted(val_days)}"
        )
    if n_val_tabular != n_parallel:
        raise RuntimeError(
            f"val tabular/eval mismatch: load_data val rows={n_val_tabular} "
            f"!= _evaluate_*_on_full_rth n_rows={n_parallel}"
        )


def main():
    ap = argparse.ArgumentParser(
        description="Train/compare parallel vs cascade using the same entry points as ml_scheduler.",
    )
    ap.add_argument(
        "--horizon",
        default=DEFAULT_ML_HORIZON_SLUG,
        help="ML horizon slug (1c, 5c, 15c, 60c); selects outcome_* label and artifacts.",
    )
    cli = ap.parse_args()
    hz = normalize_ml_horizon_slug(cli.horizon)

    print("=" * 70)
    print("TRAIN_COMPARE — Parallel vs Cascade (ml_scheduler._train_* + _evaluate_*_on_full_rth)")
    print("=" * 70)
    print(f"DB: {DB_PATH}")
    print(f"ML horizon: {hz}  label: {outcome_column(hz)}")
    print(f"Temp: {COMPARE_PARALLEL} / {COMPARE_CASCADE}")
    print()

    if not DB_PATH.exists():
        print(f"ERROR: Database not found: {DB_PATH}")
        sys.exit(1)

    from training_cache import (
        db_distinct_rth_et_dates_for_ticker,
        compare_tabular_data_fingerprint_from_df,
        compute_training_code_fingerprint,
        compute_scheduler_cache_key,
        compute_feature_cache_key,
        compute_artifact_sha256_map,
        parallel_artifact_basenames,
        cascade_artifact_basenames,
        build_manifest,
        save_compare_aggregate_manifest,
    )
    from training_cache_policy import (
        MANIFEST_SCHEMA_VERSION,
        ROLLING_WINDOW_RTH_SESSIONS_TABULAR,
        ROLLING_WINDOW_RTH_SESSIONS_SEQUENCE,
    )
    from ml_train import load_data
    from ml_scheduler import (
        _train_parallel,
        _train_cascade,
        _evaluate_parallel_on_full_rth,
        _evaluate_cascade_on_full_rth,
    )
    from datetime import datetime, timezone

    label_col = outcome_column(hz)

    days = db_distinct_rth_et_dates_for_ticker(str(DB_PATH), TICKER, label_column=label_col)
    if len(days) < 10:
        print(f"ERROR: Need at least 10 RTH sessions in DB (have {len(days)})")
        sys.exit(1)

    n_val = min(3, max(1, len(days) - 10))
    n_train = len(days) - n_val
    train_days = days[:n_train]
    val_days = days[-n_val:]
    train_days_set: Set[str] = set(train_days)
    val_days_set: Set[str] = set(val_days)

    print(f"Train sessions ({len(train_days)}): {train_days[:3]}…{train_days[-1]}")
    print(f"Val sessions ({len(val_days)}):   {val_days}")

    train_df = load_data(
        str(DB_PATH), ticker=TICKER, allowed_et_dates=train_days_set, ml_horizon_slug=hz
    )
    val_df = load_data(
        str(DB_PATH), ticker=TICKER, allowed_et_dates=val_days_set, ml_horizon_slug=hz
    )
    print(f"Train rows: {len(train_df):,}  Val rows: {len(val_df):,}")
    if len(val_df) == 0:
        print("ERROR: No validation data")
        sys.exit(1)

    baseline_acc = _compute_baseline(val_df, label_col)
    print(f"\nBaseline (rules_signal vs {label_col} on val): {baseline_acc:.1%}")

    code_fp = compute_training_code_fingerprint()
    data_fp_cmp = compare_tabular_data_fingerprint_from_df(train_df, TICKER)
    fk_cmp = compute_feature_cache_key(TICKER, data_fp_cmp, code_fp, target_column=label_col)
    parallel_key_cmp = compute_scheduler_cache_key(
        TICKER, "parallel", data_fp_cmp, code_fp, target_column=label_col
    )
    cascade_key_cmp = compute_scheduler_cache_key(
        TICKER, "cascade", data_fp_cmp, code_fp, target_column=label_col
    )
    run_iso = datetime.now(timezone.utc).isoformat()

    if COMPARE_DIR.exists():
        shutil.rmtree(COMPARE_DIR, ignore_errors=True)
    COMPARE_PARALLEL.mkdir(parents=True)
    COMPARE_CASCADE.mkdir(parents=True)

    _so = sys.stdout
    try:
        sys.stdout = _safe_stdout_ctx()
        print("\n--- Architecture A (Parallel) — ml_scheduler._train_parallel ---")
        par_ret = _train_parallel(
            TICKER,
            str(DB_PATH),
            out_dir=COMPARE_PARALLEL,
            allowed_et_dates=train_days_set,
            bypass_cache=True,
            data_fp=data_fp_cmp,
            code_fp=code_fp,
            scheduler_cache_key=parallel_key_cmp,
            feature_cache_key=fk_cmp,
            prior_manifest=None,
            ml_horizon_slug=hz,
        )
        print("\n--- Architecture B (Cascade) — ml_scheduler._train_cascade ---")
        cas_ret = _train_cascade(
            TICKER,
            str(DB_PATH),
            out_dir=COMPARE_CASCADE,
            allowed_et_dates=train_days_set,
            bypass_cache=True,
            data_fp=data_fp_cmp,
            code_fp=code_fp,
            scheduler_cache_key=cascade_key_cmp,
            feature_cache_key=fk_cmp,
            prior_manifest=None,
            ml_horizon_slug=hz,
        )
    finally:
        sys.stdout = _so

    parallel_acc, parallel_bal, n_ev_p, par_ll, par_real = _evaluate_parallel_on_full_rth(
        str(DB_PATH), TICKER, COMPARE_PARALLEL, allowed_et_dates=val_days_set, target_column=label_col
    )
    cascade_acc, cascade_bal, n_ev_c, cas_ll, cas_real = _evaluate_cascade_on_full_rth(
        str(DB_PATH), TICKER, COMPARE_CASCADE, allowed_et_dates=val_days_set, target_column=label_col
    )

    validate_eval_slice_parity(len(val_df), n_ev_p, n_ev_c, val_days_set)
    print(
        f"\n[validation] slice parity OK: load_data(val)={len(val_df)} rows; "
        f"parallel eval={n_ev_p}; cascade eval={n_ev_c}; val ET dates={sorted(val_days_set)}"
    )

    par_names = parallel_artifact_basenames(TICKER, horizon_suffix=hz)
    cas_names = cascade_artifact_basenames(TICKER, horizon_suffix=hz)
    par_sha = compute_artifact_sha256_map(COMPARE_PARALLEL, par_names)
    cas_sha = compute_artifact_sha256_map(COMPARE_CASCADE, cas_names)

    parallel_manifest = build_manifest(
        ticker=TICKER,
        architecture="parallel",
        scheduler_cache_key=parallel_key_cmp,
        feature_cache_key=fk_cmp,
        data_fp=data_fp_cmp,
        trained_at=run_iso,
        artifact_rel_paths=_rel_artifacts(COMPARE_PARALLEL, par_names),
        artifact_sha256=par_sha,
        training_code_fingerprint=code_fp,
        evaluation={
            "realized_contract_eval_ref": "realized_contract_eval.py",
            "eval_accuracy": round(float(parallel_acc), 6),
            "balanced_accuracy": round(float(parallel_bal), 6),
            "n_rows": int(n_ev_p),
            **({"eval_log_loss": round(float(par_ll), 6)} if par_ll is not None else {}),
            "realized_contract_metrics": par_real,
        },
        promotion_decision=None,
        skipped_train=False,
        skipped_eval=False,
        used_feature_cache=bool(par_ret.get("used_feature_cache", False)),
        used_cascade_tensor_cache=bool(par_ret.get("used_cascade_tensor_cache", False)),
        rolling_window_days_tabular=ROLLING_WINDOW_RTH_SESSIONS_TABULAR,
        rolling_window_days_sequence=ROLLING_WINDOW_RTH_SESSIONS_SEQUENCE,
        rolling_rth_sessions_tabular=ROLLING_WINDOW_RTH_SESSIONS_TABULAR,
        rolling_rth_sessions_sequence=ROLLING_WINDOW_RTH_SESSIONS_SEQUENCE,
        consecutive_scheduler_skips=0,
        skip_reason=None,
        retrain_reason="train_compare_ephemeral",
        cache_miss_reason="compare_script_always_trains",
        warm_resume=par_ret.get("warm_resume") or {},
        ml_horizon_suffix=hz,
    )

    cascade_manifest = build_manifest(
        ticker=TICKER,
        architecture="cascade",
        scheduler_cache_key=cascade_key_cmp,
        feature_cache_key=fk_cmp,
        data_fp=data_fp_cmp,
        trained_at=run_iso,
        artifact_rel_paths=_rel_artifacts(COMPARE_CASCADE, cas_names),
        artifact_sha256=cas_sha,
        training_code_fingerprint=code_fp,
        evaluation={
            "realized_contract_eval_ref": "realized_contract_eval.py",
            "eval_accuracy": round(float(cascade_acc), 6),
            "balanced_accuracy": round(float(cascade_bal), 6),
            "n_rows": int(n_ev_c),
            **({"eval_log_loss": round(float(cas_ll), 6)} if cas_ll is not None else {}),
            "realized_contract_metrics": cas_real,
        },
        promotion_decision=None,
        skipped_train=False,
        skipped_eval=False,
        used_feature_cache=bool(cas_ret.get("used_feature_cache", False)),
        used_cascade_tensor_cache=bool(cas_ret.get("used_cascade_tensor_cache", False)),
        rolling_window_days_tabular=ROLLING_WINDOW_RTH_SESSIONS_TABULAR,
        rolling_window_days_sequence=ROLLING_WINDOW_RTH_SESSIONS_SEQUENCE,
        rolling_rth_sessions_tabular=ROLLING_WINDOW_RTH_SESSIONS_TABULAR,
        rolling_rth_sessions_sequence=ROLLING_WINDOW_RTH_SESSIONS_SEQUENCE,
        consecutive_scheduler_skips=0,
        skip_reason=None,
        retrain_reason="train_compare_ephemeral",
        cache_miss_reason="compare_script_always_trains",
        warm_resume=cas_ret.get("warm_resume") or {},
        ml_horizon_suffix=hz,
    )

    save_compare_aggregate_manifest(
        {
            "aggregate_schema_version": MANIFEST_SCHEMA_VERSION,
            "training_code_fingerprint": code_fp,
            "note": "train_compare: _train_parallel/_train_cascade + shared val slice via _evaluate_*_on_full_rth",
            "parallel": parallel_manifest,
            "cascade": cascade_manifest,
        }
    )

    _par_avg = par_real.get("eval_pnl_realized_contract") if isinstance(par_real, dict) else None
    _cas_avg = cas_real.get("eval_pnl_realized_contract") if isinstance(cas_real, dict) else None
    _pnl_tie_p = (
        (float("-inf") if _par_avg is None else float(_par_avg))
        >= (float("-inf") if _cas_avg is None else float(_cas_avg))
    )
    if par_ll is not None and cas_ll is not None:
        parallel_wins = par_ll < cas_ll - 1e-9 or (
            abs(par_ll - cas_ll) <= 1e-9
            and (
                parallel_acc > cascade_acc
                or (
                    parallel_acc == cascade_acc
                    and (
                        parallel_bal > cascade_bal
                        or (parallel_bal == cascade_bal and _pnl_tie_p)
                    )
                )
            )
        )
    else:
        parallel_wins = parallel_acc > cascade_acc or (
            parallel_acc == cascade_acc and parallel_bal >= cascade_bal
        )
    winner = "PARALLEL" if parallel_wins else "CASCADE"

    shutil.rmtree(COMPARE_DIR, ignore_errors=True)

    report = f"""TRAIN_COMPARE REPORT
===================
Session split: db_distinct_rth_et_dates_for_ticker (chronological train / val)
Training: ml_scheduler._train_* with allowed_et_dates=train sessions (same code path as run_once)
Eval: ml_scheduler._evaluate_*_on_full_rth with allowed_et_dates=val sessions (identical rows for both arches)

BASELINE:   accuracy={baseline_acc*100:.1f}%
PARALLEL:   accuracy={parallel_acc*100:.1f}%  balanced_acc={parallel_bal*100:.1f}%  log_loss={par_ll if par_ll is not None else '—'}  pnl_realized_avg={_par_avg if _par_avg is not None else '—'}  n_val_rows={n_ev_p}
CASCADE:    accuracy={cascade_acc*100:.1f}%  balanced_acc={cascade_bal*100:.1f}%  log_loss={cas_ll if cas_ll is not None else '—'}  pnl_realized_avg={_cas_avg if _cas_avg is not None else '—'}  n_val_rows={n_ev_c}
WINNER (scheduler: lower log_loss primary; else acc/bal/realized contract PnL avg): {winner}
"""
    print("\n" + report)
    (SCRIPT_DIR / "models").mkdir(exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"Saved: {REPORT_PATH}")


if __name__ == "__main__":
    main()
