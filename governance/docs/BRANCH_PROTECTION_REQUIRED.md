# Branch protection — required external controls (Phase 3D)

**Classification:** Institutional Audit Phase 3D | **Scope:** External branch protection requirement and honest verification states | **Status:** REQUIRED, NOT VERIFIED in-repo

## Honest limit

This repository can document and CI-specify external controls. It **cannot** prove GitHub branch protection is enabled without authenticated GitHub API evidence or operator attestation recorded outside fabricated in-repo claims.

Machine-readable state: `governance/artifacts/BRANCH_PROTECTION_PROOF.json`

| Field | Current acceptable value |
|-------|-------------------------|
| `branch_protection.required` | `true` |
| `branch_protection.verified` | `false` |
| `branch_protection.verification_state` | `unverified` |
| `external_enforcement_proven` | `false` |

## Expected GitHub settings (operator must verify on host)

| Setting | Required | In-repo proof |
|---------|----------|---------------|
| Branch protection on `main` | Yes | Doc + artifact only |
| Required pull request reviews | ≥1 independent | **Not proven locally** |
| Required status check: `objective-audit` | Yes | `.github/workflows/objective-audit.yml` |
| CODEOWNERS on governance paths | Yes | `.github/CODEOWNERS` |
| Block force-push to `main` | Yes | **Not verified from repo** |

## Acceptable claim until verified

**Branch protection required but not yet verified.**

Do not claim external enforcement proven until `BRANCH_PROTECTION_PROOF.json` carries `github_api_evidence` from a real API response or operator attestation with date and repository URL.

## Phase 3D-Verification (after operator configures GitHub)

```bash
# Preferred — GitHub CLI with auth:
python tools/verify_remote_enforcement.py --fetch-github

# Or manual attestation (verified stays false):
python tools/verify_remote_enforcement.py --write-template
# edit governance/artifacts/REMOTE_ENFORCEMENT_OPERATOR_ATTESTATION.template.json → save as REMOTE_ENFORCEMENT_OPERATOR_ATTESTATION.json
python tools/verify_remote_enforcement.py --attestation governance/artifacts/REMOTE_ENFORCEMENT_OPERATOR_ATTESTATION.json

python tools/_build_institutional_audit_phase3d.py
```

Canonical evidence store: `governance/artifacts/REMOTE_ENFORCEMENT_EVIDENCE.json`

**Do not set `verified: true` in artifacts by hand.** Only `verify_remote_enforcement.py --fetch-github` (or exported ruleset ingest) may set API-class verification.

## Operator verification checklist

1. GitHub → Settings → Branches → protection rule for `main`
2. Enable required status check **`objective-audit`** (job name from workflow)
3. Enable required pull request reviews (≥1)
4. Confirm `--no-verify` local commits still fail merge without passing CI
5. Record verification in ops log — not as fabricated `verified: true` without evidence
