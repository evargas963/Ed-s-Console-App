#!/usr/bin/env python3
"""Mechanical lock: survivor pre-train gate order + parallel→cascade bridge (operator 2026-05-31)."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Binding gate order after ablation confirm v2 (exercising path: run_survivor_stack_refit_backtest).
SURVIVOR_PRETRAIN_GATE_ORDER: tuple[str, ...] = (
    "run_survivor_stack_refit_backtest",
    "run_survivor_edge_probe",
    "run_survivor_validation_run",
)

_REQUIRED_BRIDGE = (
    (REPO_ROOT / "training_cache.py", "save_parallel_cascade_bridge"),
    (REPO_ROOT / "training_cache.py", "load_parallel_cascade_bridge"),
    (REPO_ROOT / "training_cache.py", "copy_parallel_xgb_artifacts_to_cascade"),
    (REPO_ROOT / "ml_scheduler.py", "_xgb_probs_aligned_to_lstm_dataset"),
    (REPO_ROOT / "ml_scheduler.py", "used_parallel_cascade_bridge"),
    (REPO_ROOT / "ml_scheduler.py", "parallel_out=parallel_out"),
    (REPO_ROOT / "tools" / "feature_curation_gate.py", "run_survivor_stack_refit_backtest"),
    (REPO_ROOT / "ml_scheduler.py", "run_survivor_stack_refit_backtest"),
)

_REQUIRED_GATE_SURFACE = (
    (REPO_ROOT / "tools" / "feature_curation_gate.py", "--survivor-stack-refit-backtest"),
    (REPO_ROOT / "tools" / "feature_curation_gate.py", "log_loss_delta"),
    (REPO_ROOT / "tools" / "feature_curation_gate.py", "survivor_better"),
    (REPO_ROOT / "tools" / "run_survivor_retrain_gate.ps1", "--survivor-stack-refit-backtest"),
    (REPO_ROOT / "tools" / "run_survivor_retrain_gate.ps1", "--survivor-edge-probe"),
    (REPO_ROOT / "tools" / "run_survivor_retrain_gate.ps1", "--survivor-validation-run"),
    (REPO_ROOT / "ml_scheduler.py", "run_survivor_stack_refit_backtest"),
    (REPO_ROOT / "tools" / "feature_curation_gate.py", "run_survivor_stack_refit_backtest"),
    (REPO_ROOT / "tools" / "build_feature_assignment_matrix_v2.py", "resolve_expanded_schwab_ablation_universe"),
    (REPO_ROOT / "tools" / "build_feature_assignment_matrix_v2.py", "MIN_ABLATION_EXPANSION_FACTOR"),
    (REPO_ROOT / "arch_competition" / "stack_bundle_eval_v1.py", "void_compound_ablation_survivors"),
    (REPO_ROOT / "arch_competition" / "stack_bundle_eval_v1.py", "compound_survivors_voided"),
)


def _call_order_ok(text: str, symbols: tuple[str, ...]) -> bool:
    pos = -1
    for sym in symbols:
        idx = text.find(sym)
        if idx < 0 or idx <= pos:
            return False
        pos = idx
    return True


def _scheduler_survivor_gate_slice(text: str) -> str:
    start = text.find("_backtest = run_survivor_stack_refit_backtest")
    end = text.find("survivor_validation_run passed:")
    if start < 0 or end < 0:
        return ""
    return text[start:end]


def check_ml_pipeline_efficiency() -> list[str]:
    errors: list[str] = []
    for path, needle in _REQUIRED_BRIDGE + _REQUIRED_GATE_SURFACE:
        if not path.is_file():
            errors.append(f"missing file: {path}")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if needle not in text:
            errors.append(f"{path}: missing required efficiency hook {needle!r}")

    sched_path = REPO_ROOT / "ml_scheduler.py"
    if sched_path.is_file():
        sched_text = sched_path.read_text(encoding="utf-8", errors="replace")
        if "load_parallel_cascade_bridge" not in sched_text:
            errors.append("ml_scheduler.py: cascade must call load_parallel_cascade_bridge")
        gate_slice = _scheduler_survivor_gate_slice(sched_text)
        if not gate_slice:
            errors.append("ml_scheduler.py: missing survivor pre-train gate block")
        elif not _call_order_ok(
            gate_slice,
            ("run_survivor_stack_refit_backtest", "run_survivor_edge_probe", "run_survivor_validation_run"),
        ):
            errors.append(
                "ml_scheduler.py: survivor pre-train gates must run in order "
                f"{SURVIVOR_PRETRAIN_GATE_ORDER} (stack refit backtest before edge probe before validation)"
            )

    gate_path = REPO_ROOT / "tools" / "run_survivor_retrain_gate.ps1"
    if gate_path.is_file():
        ps1 = gate_path.read_text(encoding="utf-8", errors="replace")
        train_idx = ps1.find('$schedArgs = @("ml_scheduler.py"')
        if train_idx < 0:
            errors.append("run_survivor_retrain_gate.ps1: missing ml_scheduler train invocation")
        else:
            for sym in (
                "--survivor-stack-refit-backtest",
                "--survivor-edge-probe",
                "--survivor-validation-run",
            ):
                sym_idx = ps1.find(sym)
                if sym_idx < 0 or sym_idx > train_idx:
                    errors.append(
                        f"run_survivor_retrain_gate.ps1: {sym} must appear before ml_scheduler train"
                    )

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
