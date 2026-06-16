# Pre-push fast-fail policy

**Scope:** Pre-push tier — fail in seconds on dirty tree or stale generated artifacts before expensive hooks.

**Status:** Active policy | **Mechanical lock:** `tools/check_prepush_fast_gate.py` + `tools/check_governance_generated_artifacts_clean.py`

## Problem

Pre-push previously ran the ~296-test governance consolidation suite **first**, spending 20–50 minutes before failing on a dirty tree or stale generated artifact.

## Required pre-push order

| # | Hook id | Purpose | Typical runtime |
|---|---------|---------|-----------------|
| 1 | `prepush-fast-gate` | Dirty working tree → fail in **<5s** | <1s |
| 2 | `generated-artifacts-clean-check` | Stale governance JSON → fail **before pytest** | 5–60s |
| 3 | `fix-everything-we-touch-full-static` | Full repo-wide static locks | ~3–5 min |
| 4 | `governance-consolidation-tests` | Pytest consolidation (check-only) | ~10–25 min |

The consolidation suite **must not start** until hooks 1–3 pass.

## Non-mutating verification

| Check | Writes files? | Regenerate separately |
|-------|---------------|------------------------|
| `check_prepush_fast_gate.py` | No | N/A |
| `check_governance_generated_artifacts_clean.py` | **No** | See commands below |
| `fix-everything-we-touch --full-static` | Cache only (`.cursor/cache/`, gitignored) | N/A |
| `governance-consolidation-tests` | No (pytest) | N/A |

### Explicit regeneration (never run during pre-push verify)

```bash
python tools/audit_persistence_consumers.py
python tools/build_repo_hygiene_inventory.py
python tools/build_check_stack_inventory.py
python tools/audit_precommit_performance.py --write
```

## Dirty tree definition

Pre-push fails when **any** of:

- Staged or unstaged changes to tracked files vs `HEAD`
- Untracked files not covered by `.gitignore`

Commit or stash before push. Gitignored runtime artifacts (models, logs, backups) do not block push.

## Governance not weakened

- Full static locks still run on pre-push (hook 3)
- Consolidation pytest still runs on pre-push (hook 4)
- CI / `enforce_all_rules.py --objective-audit` unchanged in strength
- Fast gates add **early failure**, not fewer checks

## Mtime-gated deep checks (fast pre-push)

Expensive rebuild/compare runs **only when** the artifact is missing or a listed source file is newer than the artifact:

| Artifact | Source probe |
|----------|----------------|
| `persistence_consumer_map.json` | `db.py`, `calibration/writer.py`, `audit_persistence_consumers.py` |
| `CHECK_STACK_INVENTORY.json` | `build_check_stack_inventory.py`, `.pre-commit-config.yaml` |
| `PRECOMMIT_PERFORMANCE_AUDIT.json` | `audit_precommit_performance.py`, `.pre-commit-config.yaml` |
| `REPO_HYGIENE_*` | `build_repo_hygiene_inventory.py` | **Not on default pre-push** — full-repo walk; use explicit regen or `ED_PREPUSH_DEEP_ARTIFACT_CHECK=1` |

Force all deep compares (explicit operator/CI — not pre-push default):

```bash
ED_PREPUSH_DEEP_ARTIFACT_CHECK=1 python tools/check_governance_generated_artifacts_clean.py
```

## Artifacts

| Artifact | Command |
|----------|---------|
| Audit | `governance/artifacts/PREPUSH_FAST_FAIL_AUDIT.json` |
| Fast gate | `python tools/check_prepush_fast_gate.py` |
| Generated clean | `python tools/check_governance_generated_artifacts_clean.py` |
| Policy-only (objective audit) | `python tools/check_prepush_fast_gate.py --policy-only` |
