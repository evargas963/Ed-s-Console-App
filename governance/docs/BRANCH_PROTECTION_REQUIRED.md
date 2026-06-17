# Branch protection — required external controls (Phase 3D)

**Classification:** Institutional Audit Phase 3D | **Scope:** External branch protection requirement and honest verification states | **Status:** REQUIRED — **operator_action_required** until GitHub API confirms protection on `main`

## Honest limit

This repository can document and CI-specify external controls. It **cannot** prove GitHub branch protection is enabled without authenticated GitHub API evidence (`GITHUB_TOKEN` / `gh auth login`).

Machine-readable state: `governance/artifacts/BRANCH_PROTECTION_PROOF.json`

| Field | Current acceptable value |
|-------|-------------------------|
| `branch_protection.required` | `true` |
| `branch_protection.verified` | `false` |
| `branch_protection.verification_state` | `unverified` |
| `external_enforcement_proven` | `false` |
| `operator_action_required` | `true` (until API fetch proves protection) |

## Verified Objective Audit check name (GitHub Actions API — public)

From run **27662986304** @ commit **b084e71** on `feature/institutional-key-levels`:

| Source | Value |
|--------|--------|
| Workflow display name | `Objective Audit` |
| Workflow file | `.github/workflows/objective-audit.yml` |
| **Required status check name (branch protection)** | **`objective-audit`** |
| Job id | `objective-audit` |
| Check run conclusion | `success` |

Use **`objective-audit`** exactly when configuring branch protection — not the workflow display name.

Regenerate inspection:

```bash
python tools/verify_remote_enforcement.py --fetch-github --run-id 27662986304
```

## Expected GitHub settings (operator must configure on host)

| Setting | Required | In-repo proof |
|---------|----------|---------------|
| Branch protection / ruleset on `main` | Yes | API fetch only |
| Required pull request reviews | ≥1 independent | API fetch only |
| Required status check: **`objective-audit`** | Yes | Workflow + Actions run inspection |
| Require branches up to date | Yes (recommended) | API fetch only |
| Block force-push to `main` | Yes | API fetch only |
| Block branch deletion | Yes | API fetch only |
| CODEOWNERS on governance paths | Yes | `.github/CODEOWNERS` |

## Operator UI — GitHub.com (when CLI/token unavailable)

1. **Repository** → **Settings** → **Branches** (classic protection) **or** **Rules** → **Rulesets**
2. Target branch: **`main`**
3. Enable **Require a pull request before merging** (≥1 approval if using CODEOWNERS)
4. Enable **Require status checks to pass before merging**
5. Search and select check: **`objective-audit`** (exact spelling)
6. Enable **Require branches to be up to date before merging**
7. Disable **Allow force pushes** and **Allow deletions**
8. Save rule

Then verify from a machine with credentials:

```bash
export GITHUB_TOKEN=<PAT with repo admin>
python tools/verify_remote_enforcement.py --fetch-github
python tools/check_branch_protection_proof.py
```

Or configure via API:

```bash
export GITHUB_TOKEN=<PAT>
python tools/verify_remote_enforcement.py --configure-main-protection
```

## Acceptable claim until verified

- **GitHub Objective Audit passed** on feature branch (CI run evidence).
- **Objective Audit check name verified:** `objective-audit`.
- **Protected `main` merge path:** `operator_action_required` until GitHub API shows `objective-audit` required on `main`.
- **Local `--no-verify`** remains possible; protected merge is the external gate.

Do **not** claim universal enforcement, L5 institutional enforcement, or “all bypasses closed.”

## Phase 3D-Verification (after operator configures GitHub)

```bash
# Preferred — GitHub CLI or REST token:
python tools/verify_remote_enforcement.py --fetch-github

# Or manual attestation (verified stays false):
python tools/verify_remote_enforcement.py --write-template
python tools/verify_remote_enforcement.py --attestation governance/artifacts/REMOTE_ENFORCEMENT_OPERATOR_ATTESTATION.json

python tools/_build_institutional_audit_phase3d.py
```

Canonical evidence store: `governance/artifacts/REMOTE_ENFORCEMENT_EVIDENCE.json`

**Do not set `verified: true` in artifacts by hand.** Only `--fetch-github` / `--configure-main-protection` with API-class evidence may set `branch_protection.verified=true`.
