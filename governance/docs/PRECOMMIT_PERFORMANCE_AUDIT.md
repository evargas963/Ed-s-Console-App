# Pre-commit performance audit

**Scope:** Institutional governance — pre-commit tiering, profiling, and cache policy (Phase 3F-Perf1). Does not weaken objective-audit or repo-wide locks on pre-push/CI.

Generated: `2026-07-12T05:00:39+00:00`
Mode: `declared_policy_only`

## Tier model

- **Tier 0 — Upfront gate (enforce_all_rules --upfront-gate before staging production paths)**
- **Tier 1 — Pre-commit (staged + fast locks)**
- **Tier 2 — Pre-push / explicit local audit**
- **Tier 3 — CI objective-audit + reviewer audit**
- **Tier 4 — Full training/qualification — never pre-push**

## Hooks

| Hook | Tier | Stages | Runtime (s) | Keep pre-commit | Location |
|------|------|--------|---------------|-----------------|----------|
| prepush-fast-gate | 2 | pre-push | — | False | prepush |
| generated-artifacts-clean-check | 2 | pre-push | — | False | prepush |
| prepush-parity-gate | 1 | pre-push | — | True | precommit |
| no-grep-subprocess | 1 | pre-commit | — | True | precommit |
| no-deferral-language-msg | 1 | commit-msg | — | True | precommit |
| no-deferral-language-files | 1 | pre-commit | — | True | precommit |
| fix-everything-we-touch-msg | 1 | commit-msg | — | True | precommit |
| fix-everything-we-touch | 1 | pre-commit | — | True | precommit |

## Phase 3K — governance pre-push optimization

- Pre-push bundle before: **1265.0s**
- Pre-push bundle after: **576.24s** (~54% vs before)
- `test_check_fix_everything_we_touch.py` after: **563.66s**
- Static profile after: **94.0s** (grid check still ~90s once per process)
- Target: **<600.0s**
- Static profile before: **103.0s** (dominant: `check_ablation_seven_model_four_horizon_grid` ~99.4s once)

