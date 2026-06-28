> **Classification:** Operational Ledger | **Scope:** Phase 3F generated evidence index — claim traceability, not maturity proof.

# Governance evidence index

**Generated:** 2026-06-15  
**Purpose:** Map claims → artifacts → code → tests → reproduction commands.

| Claim | Verdict | Evidence | Code | Test | Reproduce |
|-------|---------|----------|------|------|-----------|
| Agent preload contract exists and is mechanically checked | `proven` | `governance/docs/AGENT_OPERATING_CONTRACT.md` | `tools/check_agent_preload_contract.py` | `tests/test_agent_preload_contract.py` | `python tools/check_agent_preload_contract.py` |
| Closed-loop Definition of Done for fixes exists | `proven` | `AGENTS.md (Definition of Done for Fixes)` | `tools/check_fix_everything_we_touch.py::check_definition_of_done_for_fixes_contract` | `tests/test_governance_consolidation.py::test_agents_closure_and_no_new_files_sections` | `python tools/enforce_all_rules.py --objective-audit` |
| Wrong-but-finite spot prices are quarantined (I-28) | `proven` | `governance/artifacts/INSTITUTIONAL_AUDIT_PHASE3B_EVIDENCE.json` | `trade_impacting_gate.py::assess_spot_price` | `tests/adversarial/test_wrong_price_quarantine.py` | `python -m pytest tests/adversarial/test_wrong_price_quarantine.py -q` |
| R-004 server._fetch_state production route is gated | `proven` | `governance/artifacts/INSTITUTIONAL_AUDIT_PHASE3E_EVIDENCE.json` | `server.py::_finalize_production_decision` | `tests/adversarial/test_r004_live_path_gate.py` | `python -m pytest tests/adversarial/test_r004_live_path_gate.py -q` |
| R-005 no_valid_expiry synthetic route blocked from production decision | `proven` | `governance/artifacts/DECISION_PATH_REGISTRY.json` | `trade_impacting_gate.py::SYNTHETIC_NON_PRODUCTION_ROUTES` | `tests/adversarial/test_route_universality.py` | `python -m pytest tests/adversarial/test_route_universality.py -q` |
| R-010 stale Tier C cache revalidated before serve | `proven` | `governance/artifacts/DECISION_PATH_REGISTRY.json` | `trade_impacting_gate.py::revalidate_cached_decision` | `tests/adversarial/test_stale_cache_revalidation.py` | `python -m pytest tests/adversarial/test_stale_cache_revalidation.py -q` |
| R-017 prediction override requires registry when env allows | `proven` | `governance/artifacts/DECISION_PATH_REGISTRY.json` | `override_registry.py` | `tests/adversarial/test_override_registry.py` | `python -m pytest tests/adversarial/test_override_registry.py -q` |
| R-031 verify_model_outputs classified diagnostic_only — no production decision | `proven` | `governance/artifacts/INSTITUTIONAL_AUDIT_PHASE3E_EVIDENCE.json` | `verify_model_outputs.py + trade_impacting_gate.py::resolve_fetch_state_decision_route` | `tests/adversarial/test_r031_cli_classification.py` | `python -m pytest tests/adversarial/test_r031_cli_classification.py -q` |
| Decision reconstruction works for live-path simulation (not live Schwab) (*live_path_simulation — no live Schwab wire traffic*) | `partially_proven` | `governance/artifacts/INSTITUTIONAL_AUDIT_PHASE3E_EVIDENCE.json` | `decision_record.py::live_path_simulation_emission` | `tests/runtime_proof/test_live_path_decision_reconstruction.py` | `python -m pytest tests/runtime_proof/test_live_path_decision_reconstruction.py -q` |
| Decision reconstruction works for production-like harness (*production_like_harness — post-pipeline ms_dict only*) | `partially_proven` | `governance/artifacts/INSTITUTIONAL_AUDIT_PHASE3C_EVIDENCE.json` | `decision_record.py::production_like_decision_emission` | `tests/adversarial/test_live_decision_record_reconstruction.py` | `python -m pytest tests/adversarial/test_live_decision_record_reconstruction.py -q` |
| Manual governance/decision artifact mutation is detectable (not prevented) | `detected_not_prevented` | `governance/artifacts/GOVERNANCE_ARTIFACT_MANIFEST.json` | `tools/governance_mutation_detection.py` | `tests/governance_mutation/test_manual_mutation_detection.py` | `python tools/_build_institutional_audit_phase3e.py` |
| High-impact ED_* env overrides inventoried and gated in production serving context | `proven` | `governance/artifacts/ENV_OVERRIDE_INVENTORY.json` | `tools/check_env_override_hardening.py` | `tests/runtime_proof/test_env_override_hardening.py` | `python tools/_build_institutional_audit_phase3e.py` |
| GitHub branch protection + required check objective-audit (*verified=false until GitHub API/CLI evidence*) | `required_not_proven` | `governance/artifacts/REMOTE_ENFORCEMENT_EVIDENCE.json` | `.github/workflows/objective-audit.yml + tools/verify_remote_enforcement.py` | `tests/test_remote_enforcement_evidence.py` | `python tools/verify_remote_enforcement.py --fetch-github` |
| No L5 institutional enforcement claim is made | `explicitly_rejected` | `governance/artifacts/SEVERITY_1_CONTROL_VALIDATION_REGISTER.json` | `governance/artifacts/MATURITY_PROMOTION_RULES.json` | `tests/test_reviewer_evidence_index.py::test_no_l5_claims_in_evidence_index` | `python tools/_build_evidence_index.py` |
| Universal route enforcement across all trade-impacting paths | `explicitly_rejected` | `governance/artifacts/DECISION_PATH_REGISTRY.json` | `trade_impacting_gate.py (partial priority routes only)` | `tests/adversarial/test_bypass_register_reconciliation.py` | `python tools/_build_institutional_audit_phase3c.py` |
| Live Schwab _fetch_state traffic emits reconstructable production decisions (*Requires live Schwab credentials and serving host*) | `unproven` | `governance/artifacts/CURRENT_LIMITATIONS.json` | `server.py::_fetch_state (requires Schwab credentials)` | `—` | `python tools/live_diag_compare.py SPY (operator host with Schwab auth)` |

## Verdict vocabulary

- **proven** — code + test evidence; reproducible
- **partially_proven** — honest limitation labeled
- **detected_not_prevented** — visibility only
- **required_not_proven** — spec/CI exists; external proof missing
- **unproven** — gap acknowledged
- **explicitly_rejected** — claim must not be made

Regenerate: `python tools/_build_evidence_index.py`

---

## D17 Path-A wave train — prose pointer only (2026-06-27)

**Not a maturity claim. Not a closure claim. JSON not regenerated.**

D17 strict non-money LINE_SCOPE NMD tracked slice identity rewrite (Policy A) wave train status is recorded in:

- `OPEN_ITEMS.md` — §D17 Path-A wave train (wave board + preserved NOT_CLOSED statuses)
- `governance/docs/D17_REGISTER_SLICE_INVENTORY_SUMMARY.md` — §Path-A wave train summary

**Pinned register truth (local read-only @ `77675a6`):** `governance/SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv` — rows 83,587; `unreviewed_count` 52,237; `closure_admissible` false. Build meta numeric `register_rows_written: 83587` is authoritative over stale `operator_note` prose.

**Preserved:** D17 full closure = **NOT_CLOSED**; Schwab V4 Register Closure = **NOT_CLOSED**; register repin = **NOT_APPROVED**.
