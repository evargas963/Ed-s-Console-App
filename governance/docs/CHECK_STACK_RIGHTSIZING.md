# Check stack right-sizing

**Scope:** Phase 3I — inventory, tier policy, duplication analysis, runtime budgets. No check removal in this phase.

Generated: `2026-06-16T19:47:59+00:00`

## Runtime budget targets (seconds)

| Path | Target | Measured / status |
|------|--------|-------------------|
| Pre-commit normal | 60s | under budget after Perf1 |
| Pre-commit governance | 180s | scoped path |
| Pre-push governance | 1200s | **OVER** — 1440s measured |

## Tier model

- **Tier 0** — upfront gate (`enforce_all_rules --upfront-gate`)
- **Tier 1** — pre-commit (staged + fast)
- **Tier 2** — pre-push (full static + consolidation pytest)
- **Tier 3** — CI objective-audit
- **Tier 4** — reviewer audit (`run_reviewer_audit.py`)

## Over budget (recorded, not silently accepted)

- **pre-push**: 1440s vs budget 1200s — governance-consolidation-tests pytest suite dominates (~26 min); ablation grid lock ~146s after PERF2-1 shared index

## Duplication analysis

- `prepush-fast-gate` ↔ `generated-artifacts-clean-check`: **candidate_for_merge** — Review before merge/remove — slowness alone is not removal grounds
- `prepush-fast-gate` ↔ `fix-everything-we-touch-full-static`: **candidate_for_merge** — Review before merge/remove — slowness alone is not removal grounds
- `prepush-fast-gate` ↔ `governance-consolidation-tests`: **candidate_for_merge** — Review before merge/remove — slowness alone is not removal grounds
- `generated-artifacts-clean-check` ↔ `fix-everything-we-touch-full-static`: **candidate_for_merge** — Review before merge/remove — slowness alone is not removal grounds
- `generated-artifacts-clean-check` ↔ `governance-consolidation-tests`: **candidate_for_merge** — Review before merge/remove — slowness alone is not removal grounds
- `fix-everything-we-touch-full-static` ↔ `governance-consolidation-tests`: **candidate_for_merge** — Review before merge/remove — slowness alone is not removal grounds
- `no-grep-subprocess` ↔ `no-deferral-language-msg`: **candidate_for_merge** — Review before merge/remove — slowness alone is not removal grounds
- `no-grep-subprocess` ↔ `no-deferral-language-files`: **candidate_for_merge** — Review before merge/remove — slowness alone is not removal grounds
- `no-grep-subprocess` ↔ `fix-everything-we-touch-msg`: **candidate_for_merge** — Review before merge/remove — slowness alone is not removal grounds
- `no-grep-subprocess` ↔ `fix-everything-we-touch`: **candidate_for_merge** — Review before merge/remove — slowness alone is not removal grounds
- `no-deferral-language-msg` ↔ `no-deferral-language-files`: **unintentional_duplicate** — Review before merge/remove — slowness alone is not removal grounds
- `no-deferral-language-msg` ↔ `fix-everything-we-touch-msg`: **candidate_for_merge** — Review before merge/remove — slowness alone is not removal grounds
- `no-deferral-language-msg` ↔ `fix-everything-we-touch`: **candidate_for_merge** — Review before merge/remove — slowness alone is not removal grounds
- `no-deferral-language-files` ↔ `fix-everything-we-touch-msg`: **candidate_for_merge** — Review before merge/remove — slowness alone is not removal grounds
- `no-deferral-language-files` ↔ `fix-everything-we-touch`: **candidate_for_merge** — Review before merge/remove — slowness alone is not removal grounds
- `fix-everything-we-touch-msg` ↔ `fix-everything-we-touch`: **unintentional_duplicate** — Review before merge/remove — slowness alone is not removal grounds

Regenerate: `python tools/build_check_stack_inventory.py`
