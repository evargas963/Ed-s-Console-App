# Governance-critical files (Phase 3D)

**Scope:** Institutional Audit Phase 3D — governance-critical path enumeration and CODEOWNERS coverage model.

Files listed here require CODEOWNERS coverage and should require independent review when branch protection is verified on GitHub.

## Canonical list

- `AGENTS.md`, `CLAUDE.md`
- `.cursor/rules/**` (agent preload surfaces)
- `.github/workflows/**`, `.github/CODEOWNERS`
- `tools/check_*.py`, `tools/enforce_all_rules.py`, `tools/_build_institutional_audit_*.py`
- `governance/**`
- `tests/adversarial/**`, `tests/decision_reconstruction/**`, `tests/release_object/**`
- `tests/test_governance_consolidation.py`, `tests/test_agent_preload_contract.py`
- `trade_impacting_gate.py`, `live_decision_bundle.py`, `decision_record.py`, `override_registry.py`
- `server.py`, `signals.py`

## Enforcement

| Layer | What it proves |
|-------|----------------|
| CODEOWNERS | Ownership model present — **not** review enforcement by itself |
| `tools/check_governance_critical_files.py` | Paths exist + CODEOWNERS prefix coverage |
| Branch protection + required reviews | External enforcement — **unverified until GitHub proof** |

## Artifact

`governance/artifacts/GOVERNANCE_CRITICAL_FILES.json`

Checker: `python tools/check_governance_critical_files.py`
