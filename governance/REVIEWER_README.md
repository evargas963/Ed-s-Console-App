# Governance reviewer guide — EdWebConsole

> **Classification:** Operational Ledger | **Scope:** External reviewer entry point — evidence reproduction and honest limitations.

> **Audience:** External reviewers, auditors, and operators inspecting institutional governance.  
> **Scope detail:** What is proven locally, what is not, and how to reproduce every claim.

---

## What this governance system is

EdWebConsole uses a **layered governance model** for trading decisions:

1. **Agent preload (Phase 3A)** — session-start contract for Cursor/Claude  
2. **Runtime gates (Phase 3B)** — `trade_impacting_gate.py` quarantines bad market data and non-production routes  
3. **Route inventory + bypass register (Phase 3C)** — honest map of trade-impacting paths and open bypasses  
4. **External enforcement spec (Phase 3D)** — CI workflow `objective-audit`, CODEOWNERS, remote evidence model (**not API-verified on this machine**)  
5. **Live-path proof + bypass reduction (Phase 3E)** — live_path_simulation, R-004/R-031, mutation detection, env inventory  
6. **Reviewer index (Phase 3F)** — this document + evidence/limitations indexes  

**This is not L5 institutional enforcement.** No universal route enforcement is claimed.

---

## Maturity truth source (read first)

| Priority | File | Role |
|----------|------|------|
| 1 | `governance/artifacts/SEVERITY_1_CONTROL_VALIDATION_REGISTER.json` | Maturity truth — supersedes matrix labels |
| 2 | `governance/artifacts/EVIDENCE_INDEX.json` | Claim → evidence → code → test map |
| 3 | `governance/artifacts/CURRENT_LIMITATIONS.json` | Honest open gaps |
| 4 | `governance/artifacts/UNIVERSAL_BYPASS_REGISTER.json` | Bypass paths (69 still open) |
| 5 | `governance/artifacts/DECISION_PATH_REGISTRY.json` | Route enforcement state |

Do **not** treat green local CI as GitHub branch protection proof.

---

## Quick start — reviewer audit (one command)

```bash
python tools/run_reviewer_audit.py
```

This runs objective audit, adversarial tests, runtime proof, governance mutation tests, decision/reconstruction tests, agent preload, Phase 3D remote-evidence tests, and evidence-index checker tests. Exit 0 = **local** reviewer audit clean — **not** external GitHub verified.

---

## Run objective audit

```bash
python tools/enforce_all_rules.py --objective-audit
```

Expected: `AUDIT: CLEAN` (repo-wide static locks + situational runtime where cone fits).

---

## Run adversarial and proof tests

```bash
python -m pytest tests/adversarial/ -q
python -m pytest tests/runtime_proof/ -q
python -m pytest tests/governance_mutation/ -q
python -m pytest tests/decision_reconstruction/ tests/release_object/ tests/test_governance_consolidation.py -q
python -m pytest tests/test_agent_preload_contract.py -q
python -m pytest tests/test_remote_enforcement_evidence.py tests/test_branch_protection_proof.py tests/test_required_status_checks.py tests/test_no_verify_resistance.py tests/test_governance_self_protection.py -q
```

---

## Regenerate governance artifacts

| Artifact | Command |
|----------|---------|
| Evidence index | `python tools/_build_evidence_index.py` |
| Limitations index | `python tools/_build_current_limitations.py` |
| Phase 3E evidence | `python tools/_build_institutional_audit_phase3e.py` |
| Phase 3D evidence | `python tools/_build_institutional_audit_phase3d.py` (after `--fetch-github`) |
| Repo hygiene inventory | `python tools/build_repo_hygiene_inventory.py` |
| Check stack inventory | `python tools/build_check_stack_inventory.py` |
| Governance manifest | Included in phase3e builder |
| Remote enforcement | `python tools/verify_remote_enforcement.py --fetch-github` (requires authenticated `gh`) |

---

## Phases landed (honest status)

| Phase | Status | Key evidence |
|-------|--------|--------------|
| **3A** | LANDED | Agent preload contract + checker |
| **3B** | LANDED (partial) | Wrong-price quarantine, R-005 blocked, R-010/R-017 gated |
| **3C** | LANDED | Bypass register, decision path registry, production-like reconstruction |
| **3D** | LANDED (infra) | CI workflow `objective-audit`, remote evidence model — **verified=false** |
| **3D-Verification** | LANDED (infra) | `verify_remote_enforcement.py`, safeguards against fake verified |
| **3E** | LANDED | Live-path simulation, R-004 proof, R-031 classification, mutation detection |
| **3F** | LANDED | This README + evidence/limitations indexes |

---

## What is proven locally

See `governance/artifacts/EVIDENCE_INDEX.json` — claims with verdict `proven` or `partially_proven` include code path, test path, and regeneration command.

Highlights:

- Wrong-price quarantine (I-28)  
- R-004 gated via `server._finalize_production_decision`  
- R-005 synthetic route blocked  
- R-010 stale cache revalidation  
- R-017 override registry  
- R-031 CLI classified non-production  
- Decision reconstruction (production-like + live_path_simulation — **not live Schwab**)  
- Env override inventory (18 flags, 6 high-risk)  
- Manual mutation **detection** (not prevention)  

---

## What is NOT proven (required reading)

See `governance/CURRENT_LIMITATIONS.md` and `governance/artifacts/CURRENT_LIMITATIONS.json`:

| Gap | Honest label |
|-----|--------------|
| Live Schwab traffic proof | `unproven` |
| R-012 route | `unproven` |
| GitHub branch protection | `required_not_proven` |
| Required status check on GitHub | `required_not_proven` |
| `git --no-verify` | `external_required` |
| Manual DB/filesystem mutation | `detected_not_prevented` |
| Universal enforcement | `explicitly_rejected` |
| L5 institutional enforcement | `explicitly_rejected` |

---

## Claims explicitly rejected

Do **not** accept without API/GitHub evidence:

- `verified=true` from docs or CI file existence alone  
- Branch protection satisfied from CODEOWNERS alone  
- `--no-verify` mitigated because pre-commit exists locally  
- L5 or universal enforcement from clean objective audit  
- Live Schwab proof from `live_path_simulation` or `production_like_harness`  
- Manual attestation as API verification  

---

## GitHub external enforcement (operator track)

1. Push workflow to GitHub  
2. Run `objective-audit` once on `main`  
3. Configure branch protection: required check **`objective-audit`**, PR review ≥1, no force push  
4. On authenticated machine: `python tools/verify_remote_enforcement.py --fetch-github`  

Until step 4 succeeds with API evidence, `branch_protection_verified` remains **false**.

---

## D17 wave train + pinned register pointers (2026-06-27)

**D17 wave-train status** lives in:

- `OPEN_ITEMS.md` — §D17 Path-A wave train (Waves 1–6 **CLOSED_WITH_EVIDENCE** board)
- `governance/docs/D17_REGISTER_SLICE_INVENTORY_SUMMARY.md` — §Path-A wave train summary

**Pinned register truth** (local read-only; waves did **not** repin):

- `governance/SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv` — rows, `unreviewed_count`, `closure_admissible`, content SHA @ tip
- `governance/artifacts/schwab_v4_register_build_meta.json` — numeric `register_rows_written` is authoritative; `operator_note` row-count prose may be stale

**Preserved (do not conflate wave completion with program closure):**

| Status | Value |
|--------|-------|
| D17 full closure | **NOT_CLOSED** |
| Schwab V4 Register Closure | **NOT_CLOSED** |
| Register repin | **NOT_APPROVED** |
| Production semantic-key merge | **NOT_APPROVED** |

---

## Directory map for reviewers

```
governance/
  REVIEWER_README.md          ← you are here
  CURRENT_LIMITATIONS.md      ← honest gaps (generated)
  README.md                   ← operational ledger (may lag phases — trust EVIDENCE_INDEX)
  artifacts/
    EVIDENCE_INDEX.json       ← claim map
    CURRENT_LIMITATIONS.json
    REMOTE_ENFORCEMENT_EVIDENCE.json
    INSTITUTIONAL_AUDIT_PHASE3E_EVIDENCE.json
    UNIVERSAL_BYPASS_REGISTER.json
    DECISION_PATH_REGISTRY.json
tools/
  run_reviewer_audit.py       ← one-shot reviewer verification
  _build_evidence_index.py
  _build_current_limitations.py
  enforce_all_rules.py --objective-audit
tests/
  adversarial/                ← gate proofs
  runtime_proof/              ← live-path simulation
  governance_mutation/        ← mutation detection
```

---

## Contact / repo

Remote: `https://github.com/evargas963/Ed-s-Console-App.git`  
Required CI check name (do not rename): **`objective-audit`**
