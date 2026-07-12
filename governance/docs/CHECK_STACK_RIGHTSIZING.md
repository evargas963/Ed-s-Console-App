# Check stack right-sizing

**Scope:** Phase 3I — inventory, tier policy, duplication analysis, runtime budgets. No check removal in this phase.

Generated: `2026-07-12T01:36:32+00:00`

## Runtime budget targets (seconds)

| Path | Target | Measured / status |
|------|--------|-------------------|
| Pre-commit normal | 60s | under budget after Perf1 |
| Pre-commit governance | 180s | scoped path |
| Pre-push local (lightweight) | 60s hard / 30s target | ~5s measured — **under budget** (Phase 2B) |

## Tier model

- **Tier 0** — upfront gate (`enforce_all_rules --upfront-gate`)
- **Tier 1** — pre-commit (staged + fast lightweight string/AST/config checks)
- **Tier 2** — pre-push (lightweight fast gates only: prepush-fast-gate + generated-artifacts-clean-check)
- **Tier 3** — required CI: objective-audit (repo-wide static) + pytest-full (repo-wide consolidation suite) + hardening + schwab-csv-first
- **Tier 4** — reviewer audit (`run_reviewer_audit.py`)

## Over budget (recorded, not silently accepted)

- **pre-push**: 1440s vs budget 60s — governance consolidation pytest suite (~18-26 min; each candidate file 54-64s, repo-wide/app-importing test bodies) exceeds the local lightweight pre-push budget (60s) — moved to required CI 'pytest-full' (.github/workflows/pytest.yml). It is no longer a local pre-push hook; current lightweight local pre-push measures ~5s.

## Duplication analysis

- `prepush-fast-gate` ↔ `generated-artifacts-clean-check`: **candidate_for_merge** — Review before merge/remove — slowness alone is not removal grounds
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
- `fix-everything-we-touch-full-static` ↔ `governance-consolidation-tests`: **candidate_for_merge** — Review before merge/remove — slowness alone is not removal grounds

Regenerate: `python tools/build_check_stack_inventory.py`
