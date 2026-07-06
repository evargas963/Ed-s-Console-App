#!/usr/bin/env python3
"""
D2 dual-label full-matrix runner (research-only; operator approval
D2_FULL_DUAL_LABEL_MATRIX_RUNNER_AND_SCRATCH_NORMALIZED_CARRY, 2026-07-06).

Runs (or emits PowerShell commands for) the production-pipeline training matrix
over the SCRATCH research DB, one cell per (ticker x horizon x label x family),
with hard isolation guards:

  * --db is REQUIRED and must NOT be the production DB (path containing
    data/ed_console.db is refused).
  * --out is REQUIRED and must live under data/research/ ; any path touching
    models/ (incl. models/parallel, models/cascade, models/active*) is refused.
  * Promotion is disabled for the process (ED_SCHEDULER_AUTO_PROMOTE=0) and no
    promotion code path is imported.
  * label must be explicit per cell: fixed -> outcome_{hz}, tb -> outcome_tb_{hz}.

Family support (this approval's scope — no production training files changed):
  * xgb: FULL production tabular path — ml_train.load_data(label_column=...)
    over the scratch snapshots_1m_normalized, then an in-memory column swap
    (df[outcome_{hz}] = df[outcome_tb_{hz}] for TB cells) feeds the UNCHANGED
    production ml_train.train_ticker (engineer_features, sanity gates, eval),
    writing artifacts only into the cell's out_dir.
  * lstm / transformer: BLOCKED_PENDING_LABEL_THREADING_APPROVAL — their
    dataset builders read the DB internally and derive the label from the
    horizon slug; threading label_column requires additive changes to
    production training files, which is outside this approval. Cells are
    recorded as blocked in the manifest and excluded from emitted commands.

Schwab CSV authority checked: yes
CSV row(s): NO_SCHWAB_EQUIVALENT — research training orchestration over the
  scratch DB; no production market field read, derivation, emission, or
  actionability logic changed.
Derived-field disposition: none required (research-only outputs).
All consumers checked: yes — reads scratch DB only; writes only under
  data/research/.
SCHWAB_CSV_CHECKED
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SUPPORTED_FAMILIES = ("xgb",)
BLOCKED_FAMILIES = ("lstm", "transformer")
FORBIDDEN_OUT_MARKERS = ("models",)  # any path segment 'models' = production model tree


class MatrixGuardError(SystemExit):
    pass


def guard_paths(db: Path, out: Path) -> None:
    """Hard isolation guards — refuse production DB and any model-tree output."""
    db_res = db.resolve()
    if db_res.name == "ed_console.db" or "ed_console.db" in str(db_res).lower():
        raise MatrixGuardError(
            f"REFUSED: --db points at the production DB ({db_res}); the matrix "
            "runs only against the scratch research DB."
        )
    out_res = out.resolve()
    parts = {p.lower() for p in out_res.parts}
    if any(m in parts for m in FORBIDDEN_OUT_MARKERS):
        raise MatrixGuardError(
            f"REFUSED: --out {out_res} touches a production model tree path "
            "(models/, models/parallel, models/cascade, models/active*)."
        )
    research_root = (ROOT / "data" / "research").resolve()
    if research_root not in out_res.parents and out_res != research_root:
        raise MatrixGuardError(
            f"REFUSED: --out {out_res} must live under {research_root}."
        )


def label_column_for(label: str, hz: str) -> str:
    if label == "fixed":
        return f"outcome_{hz}"
    if label == "tb":
        return f"outcome_tb_{hz}"
    raise MatrixGuardError(f"unknown label family {label!r} (use fixed|tb)")


def run_xgb_cell(db: Path, out: Path, ticker: str, hz: str, label: str) -> dict:
    """One xgb cell through the UNCHANGED production tabular path."""
    from ml_train import load_data, train_ticker

    label_col = label_column_for(label, hz)
    fixed_col = f"outcome_{hz}"
    t0 = time.time()
    df = load_data(
        db_path=str(db), ticker=ticker, ml_horizon_slug=hz, label_column=label_col
    )
    if df is None or len(df) == 0:
        return {"status": "no_rows", "label_column": label_col}
    swapped = False
    if label == "tb":
        # In-memory swap: production train_ticker derives its target column name
        # from the horizon slug; the TB labels take that seat for this research
        # run only. The scratch DB and production labels are untouched.
        df = df.copy()
        df[fixed_col] = df[label_col]
        swapped = True
    cell_dir = out / f"{ticker}_{hz}_{label}_xgb"
    cell_dir.mkdir(parents=True, exist_ok=True)
    res = train_ticker(ticker, df, model_dir=cell_dir, ml_horizon_slug=hz)
    return {
        "status": "ok",
        "label_column": label_col,
        "column_swap_applied": swapped,
        "rows": int(len(df)),
        "out_dir": str(cell_dir),
        "elapsed_s": round(time.time() - t0, 1),
        "train_result_keys": sorted(res.keys()) if isinstance(res, dict) else None,
        "eval": {
            k: res.get(k)
            for k in ("eval_accuracy", "eval_log_loss", "eval_rows", "train_rows", "status")
            if isinstance(res, dict) and k in res
        },
    }


def emit_powershell_matrix(db: Path, out: Path, tickers, horizons, labels) -> list[str]:
    cmds = []
    for tkr in tickers:
        for hz in horizons:
            for lab in labels:
                cmds.append(
                    "python tools/research/d2_run_dual_label_matrix.py "
                    f"--db {db} --out {out} --tickers {tkr} --horizons {hz} "
                    f"--labels {lab} --families xgb --run"
                )
    return cmds


def main() -> int:
    ap = argparse.ArgumentParser(description="D2 dual-label full-matrix runner")
    ap.add_argument("--db", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--tickers", nargs="+", default=["SPY", "QQQ", "IWM"])
    ap.add_argument("--horizons", nargs="+", default=["5c", "15c"])
    ap.add_argument("--labels", nargs="+", default=["fixed", "tb"])
    ap.add_argument("--families", nargs="+", default=["xgb", "lstm", "transformer"])
    ap.add_argument("--run", action="store_true",
                    help="Execute cells now (retrain-class; default emits commands only)")
    args = ap.parse_args()

    guard_paths(args.db, args.out)
    if not args.db.is_file():
        raise MatrixGuardError(f"scratch DB not found: {args.db}")
    # Promotion disabled for anything imported below (auto-promote reads env).
    os.environ["ED_SCHEDULER_AUTO_PROMOTE"] = "0"

    args.out.mkdir(parents=True, exist_ok=True)
    manifest: dict = {
        "schema": "d2_dual_label_matrix_v1",
        "db": str(args.db),
        "out": str(args.out),
        "promotion_disabled": True,
        "cells": {},
        "blocked_families": {
            fam: "BLOCKED_PENDING_LABEL_THREADING_APPROVAL"
            for fam in args.families if fam in BLOCKED_FAMILIES
        },
    }
    run_families = [f for f in args.families if f in SUPPORTED_FAMILIES]

    if not args.run:
        cmds = emit_powershell_matrix(args.db, args.out, args.tickers, args.horizons, args.labels)
        cmd_file = args.out / "d2_matrix_commands.ps1"
        cmd_file.write_text("\r\n".join(cmds) + "\r\n", encoding="utf-8")
        manifest["emitted_commands"] = len(cmds)
        manifest["command_file"] = str(cmd_file)
        (args.out / "d2_matrix_manifest.json").write_text(
            json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")
        print(json.dumps(manifest, indent=1, sort_keys=True))
        return 0

    for tkr in args.tickers:
        for hz in args.horizons:
            for lab in args.labels:
                for fam in run_families:
                    key = f"{tkr}_{hz}_{lab}_{fam}"
                    try:
                        manifest["cells"][key] = run_xgb_cell(args.db, args.out, tkr, hz, lab)
                    except SystemExit:
                        raise
                    except Exception as e:  # research runner: record + continue
                        manifest["cells"][key] = {"status": "error", "error": str(e)[:300]}
    (args.out / "d2_matrix_manifest.json").write_text(
        json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps(manifest, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
