import json
from collections import Counter
from pathlib import Path

r = json.loads(Path("governance/artifacts/feature_ablation_report_leaf.json").read_text())
cells = r.get("whole_stack_feature_cells") or []
acc = r.get("ablation_accounting") or {}
prog = r.get("run_progress") or {}
meta = r.get("run_meta") or {}

print("=== RUN META ===")
for k in (
    "started_at",
    "completed_at",
    "status",
    "ed_ablation_scoring_pass",
    "whole_stack_runnable_ok",
    "whole_stack_runnable_terminal",
):
    print(f"  {k}: {meta.get(k)}")

print("\n=== PROGRESS ===")
print(json.dumps(prog, indent=2))

print("\n=== ACCOUNTING ===")
print("  runnable_target:", acc.get("runnable_target"), "| report:", r.get("whole_stack_runnable_cell_target"))
print("  runnable_by_model:", acc.get("runnable_by_model"))

runnable = [c for c in cells if c.get("runnable")]
ok = [c for c in runnable if c.get("status") == "ok"]
print("\n=== CELLS ===")
print("  on disk:", len(cells), "| runnable ok:", len(ok))
print("  ok by model:", dict(Counter(c.get("model_family") for c in ok)))
print("  ok zero permute:", sum(1 for c in ok if int(c.get("columns_permuted_count") or 0) == 0))
print("  knockout_resolution:", dict(Counter(c.get("knockout_resolution") for c in cells if c.get("knockout_resolution"))))

print("\n=== LAST 8 CELLS ===")
for c in cells[-8:]:
    print(
        f"  {c.get('model_family')}/{c.get('horizon_slug')}/{c.get('group_id')} "
        f"st={c.get('status')} perm={c.get('columns_permuted_count')} "
        f"delta={c.get('log_loss_delta')} res={c.get('knockout_resolution')}"
    )

ei = r.get("experiment_integrity") or {}
print("\n=== INTEGRITY ===")
print("  verdict:", ei.get("verdict"))
rc = ei.get("run_completion") or {}
print("  completion:", rc)
