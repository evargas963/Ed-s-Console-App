# Pre-push fast-fail policy

**Scope:** Pre-push tier — fail in seconds on dirty tree or stale generated artifacts before expensive hooks.

**Status:** Active policy | **Mechanical lock:** `tools/check_prepush_fast_gate.py` + `tools/check_governance_generated_artifacts_clean.py`

## Local vs remote responsibility split

**Local pre-push is a fast gate.** It catches dirty trees and stale generated artifacts in seconds to minutes — not full-repo static proof.

**Repo-wide full-static enforcement is performed by required CI `objective-audit`** (`python tools/enforce_all_rules.py --objective-audit` → `run_repo_wide_static_audit()`). This is **not coverage removal**; it is a local/remote responsibility split.

| Layer | Authority | What it runs |
|-------|-----------|--------------|
| **Local pre-commit** | Every commit | Staged `fix-everything-we-touch`, deferral/grep locks (lightweight string/AST/config) |
| **Local pre-push** | Fast guard before push | Dirty tree + generated-artifact freshness only (lightweight-only) |
| **Required CI `objective-audit`** | Branch protection on `main` | Full repo-wide static locks |
| **Required CI `pytest-full`** | Branch protection on `main` | Repo-wide governance consolidation pytest suite |

## Problem

Pre-push previously ran the ~296-test governance consolidation suite, spending 18–26 minutes before push. Phase 2B measured each candidate "lightweight" test file at **54–64s** (the test bodies do repo-wide / app-importing scans; pytest startup itself is only ~1.2s), so no pytest selection can satisfy the local budget. It also ran `fix-everything-we-touch --full-static` (~3–5 min) duplicating required CI coverage.

## Required pre-push order (lightweight-only — Phase 2B, 2026-06-26)

| # | Hook id | Purpose | Typical runtime |
|---|---------|---------|-----------------|
| 1 | `prepush-fast-gate` | Dirty working tree → fail in **<5s** | <1s |
| 2 | `generated-artifacts-clean-check` | Stale governance JSON → fail fast | <1–60s |

**Local pre-push budget:** hard ceiling **≤60s**, target **≤30s**. Measured lightweight pre-push ≈ a few seconds.

**Moved to required CI (2026-06-26):**
- `fix-everything-we-touch-full-static` → required CI `objective-audit` (repo-wide static).
- `governance-consolidation-tests` (repo-wide pytest suite, ~18–26 min) → required CI **`pytest-full`** (`.github/workflows/pytest.yml`, required + green on `main`). It is no longer a local hook.

## Non-mutating verification

| Check | Writes files? | Regenerate separately |
|-------|---------------|------------------------|
| `check_prepush_fast_gate.py` | No | N/A |
| `check_governance_generated_artifacts_clean.py` | **No** | See commands below |

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

- Full repo-wide static locks run on **required CI `objective-audit`** (not local pre-push)
- The repo-wide consolidation pytest suite runs on **required CI `pytest-full`** (required + green on `main`) — moved off local pre-push, not dropped
- Staged `fix-everything-we-touch` + deferral/grep locks (lightweight string/AST/config) still run on **every pre-commit**
- Lightweight-only pre-push adds **early failure**, not fewer checks — heavy coverage is required-CI-owned

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
