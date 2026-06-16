# Governance Self-Protection Audit

**Classification:** Institutional Audit Phase 1 | **Date:** 2026-06-15  
**Method:** Read `.github/CODEOWNERS`, `.pre-commit-config.yaml`, `.github/workflows/hardening.yml`, `tools/check_governance_coverage_matrix.py`, git mechanics — not matrix inheritance.

## Executive verdict

Governance is **not self-protecting at institutional grade**. CODEOWNERS assigns review ownership, but **in-repo evidence does not prove branch protection, required reviews, or signed commits**. Weakening governance is **detectable only via git history** (post-hoc), not blocked at privilege boundary.

## Who can modify governance?

| Surface | CODEOWNERS | Proven block in repo? | Audit event? |
|---------|------------|----------------------|--------------|
| `AGENTS.md` | @evargas963 | No — file in repo | Git commit only |
| `governance/artifacts/*.json` | @evargas963 (via `/governance/`) | No | Git commit only |
| `tools/check_fix_everything_we_touch.py` | Not listed individually | No | Git commit only |
| `.pre-commit-config.yaml` | @evargas963 | No — can commit with `--no-verify` | None |
| `.github/workflows/*` | @evargas963 | No — merge without PR if allowed | CI log if PR used |
| `governance_coverage_matrix.json` | @evargas963 | `check_governance_coverage_matrix()` validates schema only | None |

## Who can disable governance?

| Action | Detection | Block | Audit |
|--------|-----------|-------|-------|
| `git commit --no-verify` | None at commit time | None | None |
| Remove hook from `.pre-commit-config.yaml` | Next CI run on PR | Only if PR + required check | Git diff |
| Lower matrix maturity in JSON | Checker allows if schema valid | None if L4+ not required yet | Git diff |
| Delete checker function | Other static locks may fail | `--no-verify` bypasses | Git diff |
| Set `ED_*` to change runtime law | None | None | None |
| Disable branch protection (GitHub settings) | Not in repo | N/A | GitHub audit log (if enabled) |

## Who can bypass governance?

See `governance/artifacts/GOVERNANCE_ATTACK_TREE.json`. Universal bypass: **`--no-verify`** (trivial, no audit event).

## What evidence is generated?

| Event | Evidence today | Institutional grade? |
|-------|----------------|---------------------|
| Pre-commit fail | stderr to developer | No persistence |
| CI fail | GitHub Actions log | PR-only |
| Promotion | `models/training_report.jsonl` | Partial |
| Override | None append-only | No |
| Governance change | Git commit | Mutable, rewriteable |

## Required upgrades (Phase 0 governance-of-governance)

1. GitHub branch protection: required reviews + required checks (`hardening.yml`, `pytest.yml`) — **verify on host**
2. CODEOWNERS must cover `tools/check_fix_everything_we_touch.py` explicitly
3. Matrix v2: forbid maturity > L2 without `bypass_detection_test` reference
4. Immutable governance event log (or signed tags on governance releases)
5. CI job that diffs governance files without corresponding validation register update → fail

**Git history alone is not institutional protection.**
