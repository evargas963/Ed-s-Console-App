# Governance system — EdWebConsole

> **Classification:** Operational Ledger | **Scope:** Governance map, truth sources, regeneration commands, maturity vocabulary.

**External reviewers:** start at [`REVIEWER_README.md`](REVIEWER_README.md) — evidence index, limitations, and one-command audit.

**Purpose:** Institutional-quality controls for trading decisions, releases, and platform governance.

## Truth sources (read in this order)

| Priority | Artifact | Authority |
|----------|----------|-----------|
| 0 | `docs/AGENT_OPERATING_CONTRACT.md` | **Agent preload** — session-start contract (Cursor + Claude) |
| 1 | `artifacts/SEVERITY_1_CONTROL_VALIDATION_REGISTER.json` | **Maturity truth** — supersedes matrix labels |
| 2 | `artifacts/UNIVERSAL_BYPASS_REGISTER.json` | Bypass paths per Severity-1 control |
| 3 | `artifacts/DECISION_PATH_REGISTRY.json` | Route universality proof gaps |
| 4 | `artifacts/governance_coverage_matrix.json` | **Inventory only** — not enforcement proof |

Do **not** treat matrix `ENFORCED` as institutional enforcement without validation register + adversarial evidence.

## Maturity levels (L0–L5)

| Level | Meaning |
|-------|---------|
| L0 | Not built |
| L1 | Documented / code exists without production proof |
| L2 | Checker or partial test |
| L3 | Commit/CI or runtime happy-path block |
| L4 | Bypass requires privilege + audit event |
| L5 | Four-eyes + immutable audit + adversarial survival |

**Promotion rule:** no upward move from implementation alone — see `artifacts/MATURITY_PROMOTION_RULES.json`.

## Regenerate artifacts

```bash
python tools/_build_institutional_audit_phase1.py
python tools/_build_institutional_audit_phase2.py
python tools/_build_institutional_audit_phase3.py   # after I-31/I-25 code lands
python tools/_build_governance_coverage_matrix.py
python tools/build_universal_repository_inventory.py
```

## Run governance tests

```bash
python tools/check_agent_preload_contract.py
python -m pytest tests/test_agent_preload_contract.py tests/test_governance_consolidation.py -q
python -m pytest tests/decision_reconstruction/ tests/release_object/ -q
python tools/enforce_all_rules.py --objective-audit
python tools/check_fix_everything_we_touch.py
```

## Institutional governance phases (3A–3D)

| Phase | Name | Status |
|-------|------|--------|
| **3A** | Agent preload contract + repo operating discipline | **LANDED** — `governance/docs/AGENT_OPERATING_CONTRACT.md`, `.cursor/rules/000–040`, `check_agent_preload_contract.py` |
| **3B** | Runtime enforcement: I-28 / I-29 / I-31 hardening | **LANDED** (working tree) — `trade_impacting_gate.py`, `tests/adversarial/`, R-005/R-010/R-017 partial |
| **3C** | Adversarial governance tests | **OPEN** — `tests/adversarial/` empty |
| **3D** | External self-protection: CI, branch protection, required reviews | **OPEN** — doc only |

## Phase 3 implementation (I-31 / I-25)

| Control | Code | API |
|---------|------|-----|
| I-31 Immutable Decision ID | `decision_record.py`, `live_decision_bundle.py` | `GET /api/decision/{decision_id}` |
| I-25 Release object | `release_object.py` | `GET /api/release/current`, `release_id` on `/api/build` |

Production decisions persist to `production_decision_records` in the console DB.

## Not institutionally enforced yet

- No control at **L5**
- `--no-verify` bypasses pre-commit
- Branch protection not proven in-repo — see `docs/BRANCH_PROTECTION_REQUIRED.md`
- Route universality **not proven** (R-005, R-010, R-017)
- Wrong-but-finite price quarantine not wired
- Adversarial bypass-detection suite mostly unimplemented

## Directory layout

```
governance/
  README.md                 ← this file
  artifacts/                ← generated evidence (regenerate commands above)
  docs/                     ← operator runbooks + AGENT_OPERATING_CONTRACT.md
  GOVERNANCE_MUTATION_AUDIT.md
  TRADE_IMPACTING_ROUTE_INVENTORY.md
tools/
  check_agent_preload_contract.py
  _build_institutional_audit_phase1.py
  _build_institutional_audit_phase2.py
  _build_institutional_audit_phase3.py
tests/
  test_agent_preload_contract.py
  test_governance_consolidation.py
  decision_reconstruction/  ← I-31
  release_object/           ← I-25
  adversarial/              ← bypass tests (expand here)
```
