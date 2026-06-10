#!/usr/bin/env python3
"""Mechanical parity lock: ablation confirm ≈ train ≈ serve transform order (O-56)."""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# confirm must not use the chicken-egg production mask flag
_FORBIDDEN_CONFIRM = (
    (REPO_ROOT / "tools" / "feature_curation_gate.py", "use_production_survivor_mask"),
)

# production/serve paths must apply post-normalize channel zero
_REQUIRED_SERVE = (
    (REPO_ROOT / "ml_predict.py", "zero_ablated_sequence_channels_for_model"),
    (REPO_ROOT / "ml_predict.py", "_transformer_apply_ablation_channel_zero"),
    (REPO_ROOT / "transformer_train.py", "zero_ablated_sequence_channels_for_model"),
    (REPO_ROOT / "lstm_model.py", "zero_ablated_sequence_channels_for_model"),
    (REPO_ROOT / "arch_competition" / "stack_bundle_eval_v1.py", "null_snapshot_dict_for_drop_groups"),
    (REPO_ROOT / "arch_competition" / "stack_bundle_eval_v1.py", "drop_ablated_xgb_engineered_columns"),
    (REPO_ROOT / "arch_competition" / "stack_bundle_eval_v1.py", "void_compound_ablation_survivors"),
    (REPO_ROOT / "arch_competition" / "stack_bundle_eval_v1.py", "compound_survivors_voided"),
    (REPO_ROOT / "tools" / "build_feature_assignment_matrix_v2.py", "build_schwab_ablation_field_registry"),
    (REPO_ROOT / "governed_stack_contract.py", "FULL_STACK_MODEL_LAYERS"),
    (REPO_ROOT / "lstm_data.py", "confirm_drop_group_ids"),
)

# scheduler wires edge probe + incumbent reset on scheduled tickers
_REQUIRED_SCHEDULER = (
    (REPO_ROOT / "ml_scheduler.py", "run_survivor_edge_probe"),
    (REPO_ROOT / "ml_scheduler.py", "ensure_survivor_retrain_incumbent_reset_at_run_start"),
    (REPO_ROOT / "ml_scheduler.py", "run_survivor_stack_refit_backtest"),
    (REPO_ROOT / "ml_scheduler.py", "load_parallel_cascade_bridge"),
)

# parallel→cascade single-pass bridge
_REQUIRED_BRIDGE = (
    (REPO_ROOT / "training_cache.py", "PARALLEL_CASCADE_BRIDGE_NPZ_NAME"),
    (REPO_ROOT / "ml_scheduler.py", "_xgb_probs_aligned_to_lstm_dataset"),
    (REPO_ROOT / "ml_scheduler.py", "save_parallel_cascade_bridge"),
)


# confirm pass must be single-instance + refuse wiping partial v2 without resume
_REQUIRED_CONFIRM_DURABILITY = (
    (REPO_ROOT / "tools" / "feature_curation_gate.py", "guard_ablation_confirm_fresh_start"),
    (REPO_ROOT / "tools" / "feature_curation_gate.py", "acquire_ablation_run_lock(run_kind=\"confirm\")"),
    (REPO_ROOT / "tools" / "feature_curation_gate.py", "PER_MODEL_CONFIRM_CELL_TARGET"),
    (REPO_ROOT / "tools" / "feature_curation_gate.py", "confirm_resume_recommended"),
    (REPO_ROOT / "tools" / "feature_curation_gate.py", "--ablation-confirm-force-restart"),
)


def check_ablation_pipeline_parity() -> list[str]:
    errors: list[str] = []
    for path, needle in _FORBIDDEN_CONFIRM:
        if not path.is_file():
            errors.append(f"missing file: {path}")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if needle in text:
            errors.append(
                f"{path}: forbidden confirm pattern {needle!r} — use drop_group_ids + manifest"
            )
    for path, needle in (
        _REQUIRED_SERVE + _REQUIRED_SCHEDULER + _REQUIRED_BRIDGE + _REQUIRED_CONFIRM_DURABILITY
    ):
        if not path.is_file():
            errors.append(f"missing file: {path}")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if needle not in text:
            errors.append(f"{path}: missing required parity hook {needle!r}")
    return errors


def main() -> int:
    errors = check_ablation_pipeline_parity()
    if errors:
        for e in errors:
            print(e, file=sys.stderr)
        return 1
    print("check_ablation_pipeline_parity: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
