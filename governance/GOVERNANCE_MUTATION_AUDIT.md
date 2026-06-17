# Governance Mutation Audit

**Classification:** Institutional Audit Phase 2 | **Date:** 2026-06-15
**Machine source:** `governance/artifacts/GOVERNANCE_MUTATION_AUDIT.json`

## Verdict

- **Institutional answer required:** No — same actor must not author, approve, and deploy governance
- **Current answer:** Yes — single actor can change, commit (--no-verify), and deploy
- **In-repo branch protection proof:** False

## Surfaces

| Surface | Detection | Audit | Same actor author+approve? |
|---------|-----------|-------|----------------------------|
| AGENTS.md | git diff post-hoc | mutable | True |
| governance/artifacts/governance_coverage_matrix.json | pre-commit schema check | mutable | True |
| tools/check_fix_everything_we_touch.py | git diff; other checkers may fail | mutable | True |
| .pre-commit-config.yaml | none at commit if --no-verify | none | True |
| .github/workflows/* | CI on PR only | mutable | True |
| tools/_build_institutional_audit_phase*.py | paired pytest on artifact shape | mutable | True |

## Required upgrades

- GitHub branch protection + required reviews (verify on host)
- CODEOWNERS on tools/check_fix_everything_we_touch.py
- CI fail when governance files change without validation register regen
- Immutable governance event log or signed governance release tags
- Block --no-verify on protected branches via server-side hooks
