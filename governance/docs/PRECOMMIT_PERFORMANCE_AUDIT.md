# Pre-commit performance audit

**Scope:** Institutional governance — pre-commit tiering, profiling, and cache policy (Phase 3F-Perf1). Does not weaken objective-audit or repo-wide locks on pre-push/CI.

Generated: `2026-06-16T05:49:43+00:00`
Mode: `declared_policy_only`

## Commit time targets (2026-06-16)

| Path | Target | Measured after optimization |
|------|--------|------------------------------|
| Normal staged code/doc (`market_state.py` only) | under 60s | **~2s** (scoped + cache) |
| Governance-critical staged | under 3 min | full repo-wide (~3.5 min profile) |
| Pre-push `--full-static` + consolidation | under 10 min | explicit Tier 2 |
| `--profile` / objective-audit | explicit only | ~3.5 min repo-wide static |

**Before:** pre-commit ran all 46 repo-wide locks every commit (~8–9 min) + pytest consolidation (~10–20 min) = **~15–20 min**.

**After:** pre-commit runs staged locks + conditional/cached repo-wide; consolidation + full static on **pre-push**.

Profile artifact: `governance/artifacts/FIX_EVERYTHING_WE_TOUCH_PROFILE.json` (`python tools/check_fix_everything_we_touch.py --profile`).

Local cache: `.cursor/cache/fix_everything_we_touch_cache.json` (gitignored; populated by pre-push `--full-static`).


- **Tier 0 — Upfront gate (enforce_all_rules --upfront-gate before staging production paths)**
- **Tier 1 — Pre-commit (staged + fast locks)**
- **Tier 2 — Pre-push / explicit local audit**
- **Tier 3 — CI objective-audit + reviewer audit**

## Hooks

| Hook | Tier | Stages | Runtime (s) | Keep pre-commit | Location |
|------|------|--------|---------------|-----------------|----------|
| governance-consolidation-tests | 2 | pre-push | — | False | prepush |
| fix-everything-we-touch-full-static | 2 | pre-push | — | False | prepush |
| no-grep-subprocess | 1 | pre-commit | — | True | precommit |
| no-deferral-language-msg | 1 | commit-msg | — | True | precommit |
| no-deferral-language-files | 1 | pre-commit | — | True | precommit |
| fix-everything-we-touch-msg | 1 | commit-msg | — | True | precommit |
| fix-everything-we-touch | 1 | pre-commit | — | True | precommit |
