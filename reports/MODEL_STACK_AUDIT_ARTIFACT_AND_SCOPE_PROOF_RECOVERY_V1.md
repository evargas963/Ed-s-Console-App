> **Classification:** Evidence Artifact | **Scope:** MODEL_STACK_AUDIT_ARTIFACT_AND_SCOPE_PROOF_RECOVERY_V1 session-evidence packet (read-only mission report)

# MODEL_STACK_AUDIT_ARTIFACT_AND_SCOPE_PROOF_RECOVERY_V1

**Mission type:** READ_ONLY  
**Base audit SHA:** e749e75345b19a291f9d14de6e78593c0feff4af  
**Investigation SHA:** 86466aeec5c18ae4b0d5ff30f3f5d77fa66c421b  
**Recovery HEAD:** 86466aeec5c18ae4b0d5ff30f3f5d77fa66c421b  
**Companion JSON:** 
eports/MODEL_STACK_AUDIT_ARTIFACT_AND_SCOPE_PROOF_RECOVERY_V1.json

---

## Phase 0 — Working-tree baseline (mission start)

`
git rev-parse HEAD
86466aeec5c18ae4b0d5ff30f3f5d77fa66c421b

git status --short
 M .cursor/rules/00-always.mdc
 M AGENTS.md
 M CLAUDE.md
 M governance/artifacts/CHECK_STACK_INVENTORY.json
 M governance/artifacts/survivor_edge_probe.json
 M governance/artifacts/survivor_inference_backtest.json
 M governance/artifacts/survivor_validation_run.json
 M governance/docs/AGENT_OPERATING_CONTRACT.md
 M governance/docs/CHECK_STACK_RIGHTSIZING.md
 M governance/mega1_traceable_inventory.py
 M reports/money_path/.gitkeep
 M server.py
 M tests/test_mega1_traceable_audit.py
 M tools/check_fix_everything_we_touch.py
?? governance/standard/
?? reports/MODEL_STACK_IMPLEMENTATION_AND_PREDICTIVE_VALIDITY_AUDIT_V1.md
?? reports/MODEL_STACK_SPECIFICATION_DEFECT_REPRODUCTION_AND_VALIDATION_DESIGN_V1.json
?? reports/MODEL_STACK_SPECIFICATION_DEFECT_REPRODUCTION_AND_VALIDATION_DESIGN_V1.md
?? reports/ui_transport/rth_guest_switch_validation_2026-07-09.json
?? reports/ui_transport/rth_guest_switch_validation_2026-07-09.md
?? reports/ui_transport/universal_card_fidelity_2026-07-09-after-hours-reproof-d2.json
?? reports/ui_transport/universal_card_fidelity_2026-07-09-after-hours-reproof-d2.md
?? tests/test_build_identity_process_drift_v1.py
?? tests/test_universal_institutional_standard.py
?? tools/check_universal_standard.py

git diff --name-status
M	.cursor/rules/00-always.mdc
M	AGENTS.md
M	CLAUDE.md
M	governance/artifacts/CHECK_STACK_INVENTORY.json
M	governance/docs/AGENT_OPERATING_CONTRACT.md
M	governance/docs/CHECK_STACK_RIGHTSIZING.md
M	governance/mega1_traceable_inventory.py
M	reports/money_path/.gitkeep
M	server.py
M	tests/test_mega1_traceable_audit.py
M	tools/check_fix_everything_we_touch.py

git diff --stat
 .cursor/rules/00-always.mdc                     |   2 +
 AGENTS.md                                       |   1 +
 CLAUDE.md                                       |   1 +
 governance/artifacts/CHECK_STACK_INVENTORY.json |  25 +++-
 governance/docs/AGENT_OPERATING_CONTRACT.md     |   1 +
 governance/docs/CHECK_STACK_RIGHTSIZING.md      |   2 +-
 governance/mega1_traceable_inventory.py         |   2 +
 reports/money_path/.gitkeep                     |   1 +
 server.py                                       | 162 +++++++++++++++++++++++-
 tests/test_mega1_traceable_audit.py             |   2 +-
 tools/check_fix_everything_we_touch.py          |  14 ++
 11 files changed, 206 insertions(+), 7 deletions(-)

git ls-files --others --exclude-standard
governance/standard/UNIVERSAL_INSTITUTIONAL_ENGINEERING_STANDARD_V1.md
governance/standard/universal_institutional_engineering_standard_v1.json
reports/MODEL_STACK_IMPLEMENTATION_AND_PREDICTIVE_VALIDITY_AUDIT_V1.md
reports/MODEL_STACK_SPECIFICATION_DEFECT_REPRODUCTION_AND_VALIDATION_DESIGN_V1.json
reports/MODEL_STACK_SPECIFICATION_DEFECT_REPRODUCTION_AND_VALIDATION_DESIGN_V1.md
reports/ui_transport/rth_guest_switch_validation_2026-07-09.json
reports/ui_transport/rth_guest_switch_validation_2026-07-09.md
reports/ui_transport/universal_card_fidelity_2026-07-09-after-hours-reproof-d2.json
reports/ui_transport/universal_card_fidelity_2026-07-09-after-hours-reproof-d2.md
tests/test_build_identity_process_drift_v1.py
tests/test_universal_institutional_standard.py
tools/check_universal_standard.py
`

### SHA-256 hashes (governs authorship)

See JSON phase0_baseline_start for full hash map:
- modified tracked files: 11
- untracked files: 12
- MODEL_STACK report artifacts: 2

MODEL_STACK report hashes at recovery start:
- MODEL_STACK_SPECIFICATION...V1.md: c48c19854e14e142c00ac1ca0940921a405bff691f0b3ab7517bb3176dc89a3a
- MODEL_STACK_SPECIFICATION...V1.json: 61fe1c004330d171abdfc9220c8eabc5421cf40954f7cb7dcfaf46baeaa4c35b

---

## Phase 1 — SHA reconciliation

| Check | Result |
|-------|--------|
| git merge-base --is-ancestor base → investigation | exit **0** (0 = ancestor PROVEN) |
| Commits between | **109** |
| Model-stack cone files changed | **9** |

Base SHA is an ancestor of investigation SHA: **PROVEN**.

Findings are **not uniformly applicable** across both SHAs without per-finding tags:
- MSD-001, MSD-003, MSD-004, MSD-005: **CONFIRMED_DEFECT at both SHAs** (line numbers drift only).
- MSD-002: **CONFIRMED_DEFECT at both**; investigation SHA adds $VXN/$RVX fetch in market_context.py (commit cfa274c) but **no consumer routing** — market_state.py still uses ix_level=mkt_ctx.vix for all tickers.
- **9** stack-path files changed between SHAs including server.py, market_context.py, ml_predict.py, market_state.py, signals.py.

BASE_TO_INVESTIGATION_SHA_APPLICABILITY = **NOT_PROVEN** as a blanket label.

---

## Phase 2 — Report completeness and consistency

| Check | Result |
|-------|--------|
| JSON parses | PROVEN |
| Runtime matrix rows | 256 / 256 expected — PROVEN |
| Defect IDs MD ↔ JSON | PROVEN (MSD-001..005) |
| Remediation lane cycles | none — PROVEN |
| All 15 matrices fully populated | NOT_PROVEN |

**Gaps (NOT_PROVEN completeness):**
- Matrix 3 feature_lineage is a string placeholder, not a populated feature x model x horizon grid
- Matrix 15 final_binary_status_table is a string pointer, not a duplicated table
- ACTIVE_STACK_ARCHITECTURE marked PROVEN without live numeric execution proof
- TRANSFORMER_PRODUCTION_CONTRIBUTION marked PROVEN — overbroad; sensitivity not shown
- Prior report cites investigation HEAD while base audit SHA is e749e75; not all findings uniformly tagged per SHA
- Matrices 5-12 are design stubs with APPROVED/NOT_PROVEN execution_status only — acceptable for design mission but not complete validation matrices

**Unsupported PROVEN in prior inal_binary_determinations:** ACTIVE_STACK_ARCHITECTURE, TRANSFORMER_PRODUCTION_CONTRIBUTION — code-path trace does not prove live effective contribution or sensitivity.

| Determination | Value |
|---------------|-------|
| REPORT_MARKDOWN_COMPLETENESS | NOT_PROVEN |
| REPORT_JSON_COMPLETENESS | NOT_PROVEN |
| REPORT_CROSS_FORMAT_CONSISTENCY | NOT_PROVEN |

---

## Phase 3 — Independent defect reproduction

All five defects **CONFIRMED_DEFECT** at base and investigation committed SHAs (read-only git show).

| ID | Producer | Consumer | Money-path |
|----|----------|----------|------------|
| MSD-001 | market_state.py vix_direction=None; no vix_vs_prev on SignalInput | olatility_regime.py inp.vix_vs_prev | CONDITIONAL |
| MSD-002 | mkt_ctx.vix shared; base: VIX only; inv: VXN/RVX fetch-only | SignalInput, ML, vol_regime | PROVEN possible |
| MSD-003 | ml_predict.py hardcoded isotonic maps (base ~L1694, inv L1806) | 5c stack_probs | PROVEN for SPY 5c |
| MSD-004 | 5c _weighted_average_partial (base ~L1846, inv L1958) | stack_probs → MC | PROVEN |
| MSD-005 | _net_vanna = None (base L1209, inv L1212) | SignalInput.net_vanna | NOT_PROVEN |

---

## Phase 4 — Transformer claim decomposition

| Claim | Status |
|-------|--------|
| TRANSFORMER_STATIC_REACHABILITY | PROVEN |
| TRANSFORMER_RUNTIME_INVOCATION | PROVEN |
| TRANSFORMER_ARTIFACT_SELECTION | PROVEN |
| TRANSFORMER_NON_FALLBACK_OUTPUT | NOT_PROVEN |
| TRANSFORMER_FUSION_INCLUSION | NOT_PROVEN |
| TRANSFORMER_FINAL_OUTPUT_SENSITIVITY | NOT_PROVEN |
| TRANSFORMER_PREDICTIVE_INCREMENT | NOT_PROVEN |
| TRANSFORMER_ECONOMIC_INCREMENT | NOT_PROVEN |

---

## Phase 5 — Prior-mission scope assessment

- Pre-mission baseline artifact: **not found**
- Agent transcript records the MODEL_STACK_SPECIFICATION mission but **not** a hash snapshot before first report write
- Recovery-start dirty tree: **11** modified tracked, **12** untracked (includes server.py modified before this recovery mission)

| Determination | Value |
|---------------|-------|
| PREVIOUS_MISSION_AUTHORIZED_FILE_COMPLIANCE | NOT_PROVEN |
| PREVIOUS_MISSION_SCOPE_VIOLATION | NOT_PROVEN |
| PREVIOUS_MISSION_CLOSURE | NOT_CLOSED |

Prior mission use of SCOPE_VIOLATION = NOT_APPLICABLE was **not authorized** by its mission text.

---

## Phase 6 — Bounded decision board (max 5)

| Lane | Class | Objective |
|------|-------|-----------|
| R1 | SPECIFICATION | Native vs macro volatility semantics before consumer wiring |
| R2 | DEFECT_FIX | MSD-001 SignalInput vix parity |
| R3 | DEFECT_FIX | MSD-003/MSD-004 5c stack_probs + isotonic governance |
| R4 | VALIDATION_INFRASTRUCTURE | Purged interval-overlap harness |
| R5 | MODEL_RESEARCH | Transformer final-output sensitivity stop/go test |

---

## Final binary determinations

`
REPORT_MARKDOWN_COMPLETENESS = NOT_PROVEN
REPORT_JSON_COMPLETENESS = NOT_PROVEN
REPORT_CROSS_FORMAT_CONSISTENCY = NOT_PROVEN
BASE_TO_INVESTIGATION_SHA_APPLICABILITY = NOT_PROVEN
MSD_001 = CONFIRMED_DEFECT
MSD_002 = CONFIRMED_DEFECT
MSD_003 = CONFIRMED_DEFECT
MSD_004 = CONFIRMED_DEFECT
MSD_005 = CONFIRMED_DEFECT
TRANSFORMER_STATIC_REACHABILITY = PROVEN
TRANSFORMER_FINAL_OUTPUT_SENSITIVITY = NOT_PROVEN
PREVIOUS_MISSION_AUTHORIZED_FILE_COMPLIANCE = NOT_PROVEN
PREVIOUS_MISSION_CLOSURE = NOT_CLOSED
IMPLEMENTATION_READY = NOT_APPROVED
MODEL_STACK_REAL_MONEY_APPROVAL = NOT_APPROVED
`

---

## End-of-mission proof

Recorded in JSON phase0_baseline_end after writing recovery artifacts only.
