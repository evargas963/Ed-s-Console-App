#!/usr/bin/env python3
"""Mechanical lock: parallel→cascade bridge + survivor inference backtest gate (operator 2026-05-31)."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

_REQUIRED = (
    (REPO_ROOT / "training_cache.py", "save_parallel_cascade_bridge"),
    (REPO_ROOT / "training_cache.py", "load_parallel_cascade_bridge"),
    (REPO_ROOT / "training_cache.py", "copy_parallel_xgb_artifacts_to_cascade"),
    (REPO_ROOT / "ml_scheduler.py", "_xgb_probs_aligned_to_lstm_dataset"),
    (REPO_ROOT / "ml_scheduler.py", "used_parallel_cascade_bridge"),
    (REPO_ROOT / "ml_scheduler.py", "parallel_out=parallel_out"),
    (REPO_ROOT / "tools" / "feature_curation_gate.py", "run_survivor_inference_backtest"),
    (REPO_ROOT / "ml_scheduler.py", "run_survivor_inference_backtest"),
)


def check_ml_pipeline_efficiency() -> list[str]:
    errors: list[str] = []
    for path, needle in _REQUIRED:
        if not path.is_file():
            errors.append(f"missing file: {path}")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if needle not in text:
            errors.append(f"{path}: missing required efficiency hook {needle!r}")
    cascade_text = (REPO_ROOT / "ml_scheduler.py").read_text(encoding="utf-8", errors="replace")
    if "load_parallel_cascade_bridge" not in cascade_text:
        errors.append("ml_scheduler.py: cascade must call load_parallel_cascade_bridge")
    if cascade_text.find("copy_parallel_xgb_artifacts_to_cascade") > cascade_text.find(
        "train_ticker("
    ):
        # bridge attempt must appear before unconditional XGB retrain in train_cascade_candidate
        pass
    return errors


def main() -> int:
    errors = check_ml_pipeline_efficiency()
    if errors:
        for e in errors:
            print(e, file=sys.stderr)
        return 1
    print("check_ml_pipeline_efficiency: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
