# Pre-commit performance audit

Generated: `2026-06-16T04:28:55+00:00`
Mode: `declared_policy_only`

## Tier model

- **Tier 0 — Upfront gate (enforce_all_rules --upfront-gate before staging production paths)**
- **Tier 1 — Pre-commit (staged + fast locks)**
- **Tier 2 — Pre-push / explicit local audit**
- **Tier 3 — CI objective-audit + reviewer audit**

## Hooks

| Hook | Tier | Stages | Runtime (s) | Keep pre-commit | Location |
|------|------|--------|---------------|-----------------|----------|
| governance-consolidation-tests | 2 | pre-push | — | False | prepush |
| no-grep-subprocess | 1 | pre-commit | — | True | precommit |
| no-deferral-language-msg | 1 | commit-msg | — | True | precommit |
| no-deferral-language-files | 1 | pre-commit | — | True | precommit |
| fix-everything-we-touch-msg | 1 | commit-msg | — | True | precommit |
| fix-everything-we-touch | 1 | pre-commit | — | True | precommit |
