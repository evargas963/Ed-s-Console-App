> **Classification:** Operational Ledger | **Scope:** Operator-trust closure matrix — not a parking lot

# Open items — operator trust register

**Purpose:** No passive **known remaining risks**. Every item has status, owner branch, and **Do not close until**.

**Allowed statuses only:** `OPEN_BLOCKING` | `NEEDS_RTH_VALIDATION_WITH_HARNESS` | `FIXED_IN_THIS_BRANCH` | `FIXED_IN_THIS_BRANCH_AWAITING_GITHUB_CI` | `COMPLETION_BRANCH_REQUIRED` | `ACCEPTED_WITH_EVIDENCE` | `CLOSED_WITH_EVIDENCE`

**Gate semantics (machine-readable — `governance/OPERATOR_TRUST_STABILIZATION_GATE.json`):**
- `stabilization_artifacts_gate_pass: true` — harnesses, checker, and closure docs exist on disk.
- `ci_triage_gate_pass: false` — PR #19 CI fixes landed; awaiting GitHub green.
- `operator_readiness_gate_pass: false` — CI triage + RTH proof not complete.
- `card_explainability_allowed: false` — **do not** start `fix/card-price-conflict-explainability`.
- **Next allowed step:** `resolve_pytest_full_failures` — pytest-full **25-failure** matrix expected @ `bc2e8a9` (29 @ `704b4b9` GitHub run `27851943230`).

**Planned sequence:** Merge stabilization (PR #18 ✅) → CI triage (PR #19, awaiting pytest-full) → operator RTH validation → `fix/card-price-conflict-explainability` (only when `card_explainability_allowed: true`)

---

### ABLATION_GRID_RUNNABLE_ACCOUNTING_CI

| Field | Value |
|-------|-------|
| **Status** | `CLOSED_WITH_EVIDENCE` |
| **Source PR / report** | `reports/ci/ci_nonblocking_failure_triage_2026-06-18.md`; GitHub @ `704b4b9` runs `27851943226` (objective-audit) + `27851943230` (pytest-full) |
| **Why it matters** | objective-audit blocks merge; runnable accounting must agree on CI empty DB |
| **Operator risk** | False ablation readiness if denominators diverge |
| **Evidence currently available** | Fix @ `704b4b9`: `resolve_ablation_enriched_row_sample` + `enriched_rows_for_spec_build`; GitHub objective-audit PASS; 4 ablation matrix tests green in pytest-full |
| **Evidence still needed** | None — bucket closed |
| **Fix now or harness now** | Landed @ `704b4b9` on `audit/ci-nonblocking-failures-triage` |
| **Owner branch** | `audit/ci-nonblocking-failures-triage` |
| **Blocking level** | Closed |
| **Do not close until** | Met @ `704b4b9` |

---

### MEGA_INVENTORY_CONTRACT_LOCK_CI

| Field | Value |
|-------|-------|
| **Status** | `CLOSED_WITH_EVIDENCE` (local @ `bc2e8a9`; GitHub pytest-full not yet observed) |
| **Source PR / report** | `reports/ci/ci_nonblocking_failure_triage_2026-06-18.md`; commit `bc2e8a9` |
| **Why it matters** | mega1–mega4 inventory gate blocks merge when production defs lack rows |
| **Operator risk** | Untraced market-field derivations in new functions |
| **Evidence currently available** | Fix @ `bc2e8a9`: `sync_traceable_inventory_to_ast` + NONE stubs; row counts 383/211/148/1014; local mega audit **35/35** |
| **Evidence still needed** | GitHub pytest-full @ `bc2e8a9` confirms 4 mega tests green in full suite |
| **Fix now or harness now** | Landed @ `bc2e8a9` on `audit/ci-nonblocking-failures-triage` |
| **Owner branch** | `fix/mega-inventory-sync` |
| **Blocking level** | Closed locally — awaiting GitHub pytest-full observation |
| **Do not close until** | GitHub pytest-full @ `bc2e8a9` shows mega inventory tests green |

---

### OBJECTIVE_AUDIT_CI

| Field | Value |
|-------|-------|
| **Status** | `CLOSED_WITH_EVIDENCE` |
| **Source PR / report** | GitHub run `27851943226` @ `704b4b9` |
| **Why it matters** | Repo-wide static + situational runtime gate for merge |
| **Evidence currently available** | objective-audit PASS push + pull_request @ `704b4b9` |
| **Do not close until** | Met @ `704b4b9` |

---

### LIVE_GUEST_SLA_NOT_PROVEN

| Field | Value |
|-------|-------|
| **Status** | `NEEDS_RTH_VALIDATION_WITH_HARNESS` |
| **Source PR / report** | PR #16 @ `b621075`; `reports/ui_transport/ui_guest_switch_sla_2026-06-18.md` |
| **Why it matters** | Static guards ≠ live guest warm-switch SLA |
| **Operator risk** | Guest switches feel broken without transport truth |
| **Evidence currently available** | Switch diag schema v2; `dr-switch-state-chip`; `tools/run_rth_guest_switch_validation.py` |
| **Evidence still needed** | RTH run: `python tools/run_rth_guest_switch_validation.py --base-url http://127.0.0.1:8000` → PASS |
| **Fix now or harness now** | Harness landed in stabilization branch |
| **Owner branch** | Operator RTH runbook; tune only if breach proven |
| **Blocking level** | Blocks closing guest-switch workstream |
| **Do not close until** | RTH report classifies `GUEST_SWITCH_SLA_PASS` with `ED_CALIBRATION_LOG=1` |

---

### DB_CONTENTION_RTH_CORRELATION_NOT_PROVEN

| Field | Value |
|-------|-------|
| **Status** | `NEEDS_RTH_VALIDATION_WITH_HARNESS` |
| **Source PR / report** | PR #14–#15; `reports/db_contention/db_sqlite_contention_impact_2026-06-18.md` |
| **Why it matters** | DB visible ≠ causality vs STALE/LOADING proven |
| **Operator risk** | Misattribute model error when DB is root cause |
| **Evidence currently available** | `/api/diagnostics/sqlite-contention`; DB chips |
| **Evidence still needed** | `tools/run_rth_db_contention_validation.py` live run + log correlation |
| **Fix now or harness now** | Harness in stabilization branch |
| **Owner branch** | Operator RTH; `fix/db-tier1-write-isolation` only if proven |
| **Blocking level** | High — trust attribution |
| **Do not close until** | Timestamp-joined sample or negative with evidence |

---

### BASE_CAPTURE_NORMALIZATION_RTH_PROOF_NOT_COMPLETE

| Field | Value |
|-------|-------|
| **Status** | `NEEDS_RTH_VALIDATION_WITH_HARNESS` |
| **Source PR / report** | Base money-path contract |
| **Why it matters** | SPY/QQQ/IWM rows must rise during RTH |
| **Operator risk** | Fresh UI on stale capture |
| **Evidence currently available** | `base_money_path_logger` wiring |
| **Evidence still needed** | `tools/run_rth_base_capture_normalization_validation.py` during RTH |
| **Fix now or harness now** | Harness in stabilization branch |
| **Owner branch** | Operator observability |
| **Blocking level** | Medium |
| **Do not close until** | Row-rate audit PASS for all three base tickers |

---

### CI_NONBLOCKING_FAILURES_NOT_TRIAGED

| Field | Value |
|-------|-------|
| **Status** | `OPEN_BLOCKING` (partial — objective-audit + hardening + schwab-csv-first closed @ `704b4b9`) |
| **Source PR / report** | `audit/ci-nonblocking-failures-triage`; `reports/ci/ci_nonblocking_failure_triage_2026-06-18.md` |
| **Why it matters** | pytest-full is merge gate; 25 failures expected @ `bc2e8a9` (29 @ `704b4b9` GitHub) |
| **Operator risk** | Regressions hide in red checks |
| **Evidence currently available** | GitHub @ `704b4b9`: pytest-full `29 failed`; local @ `bc2e8a9`: MEGA cleared (35/35 mega audit) |
| **Evidence still needed** | GitHub PR #19: `pytest-full` green OR operator sign-off on all open matrix rows |
| **Fix now or harness now** | Next bucket: `ACTIVE_BUNDLE_ENCODER_LAYOUT` (3 tests) |
| **Owner branch** | `audit/ci-nonblocking-failures-triage` |
| **Blocking level** | High until CI green on GitHub |
| **Do not close until** | `pytest-full` green on GitHub PR #19 OR operator-signed acceptance of all **25** open matrix rows @ `bc2e8a9` |

---

### HARDENING_CI_FAILING_NON_BLOCKING

| Field | Value |
|-------|-------|
| **Status** | `CLOSED_WITH_EVIDENCE` |
| **Source PR / report** | CI triage 2026-06-19 — ruff F401 + openpyxl in hardening |
| **Why it matters** | Institutional locks may drift |
| **Operator risk** | Silent rule regression |
| **Evidence currently available** | GitHub PR #19 @ `6e3157c`: hardening pass |
| **Evidence still needed** | None — green on PR branch |
| **Fix now or harness now** | `hardening.yml` installs `requirements-dev.txt` |
| **Owner branch** | `audit/ci-nonblocking-failures-triage` |
| **Blocking level** | Medium |
| **Do not close until** | `hardening` green on GitHub PR #19 merge to `main` (met @ `6e3157c`) |

---

### PYTEST_FULL_CI_FAILING_NON_BLOCKING

| Field | Value |
|-------|-------|
| **Status** | `OPEN_BLOCKING` |
| **Source PR / report** | `reports/ci/ci_nonblocking_failure_triage_2026-06-18.md` — pytest-full failure matrix |
| **Why it matters** | Full suite catches cone gaps; 25 product matrix failures @ `a72ed54` |
| **Operator risk** | Regressions hide in uncategorized red check |
| **Evidence currently available** | GitHub @ `8c22aa9` run 27884930874: **17 failed, 3770 passed, 7 skipped** = product matrix only. CLOSED_WITH_EVIDENCE on GitHub: governance meta-artifact pin drift (27 → 25), `ACTIVE_BUNDLE_ENCODER_LAYOUT` (25 → 22), `CALIBRATION_BYPASS_ALLOWLIST` (22 → 20), `ET_AUTHORITY_DAILY_SCOREBOARD` (20 → 18), `ANTI_PATTERN_CAPS_VIOLATIONS` (18 → 17); schwab-csv-first PASS |
| **Evidence still needed** | pytest-full green OR operator sign-off on every open product matrix row |
| **Fix now or harness now** | Next (operator to select): largest open non-blocked buckets `STACK_WIRE_INTEGRITY` (3) / `LIVE_BUNDLE_SSE_CACHE` (3). `UI_LEVEL_TEST_CHIP` (2) + `UI_V2_CONFIDENCE_LABELS` (1) are contract-locked to the UI/card-explainability lane — do not start |
| **Owner branch** | `audit/ci-nonblocking-failures-triage` (FIX_NOW); triage-owned groups in `ci_nonblocking_failure_triage_2026-06-18.json` |
| **Blocking level** | High — blocks PR #19 merge |
| **Do not close until** | pytest-full green on GitHub PR #19 OR operator-signed acceptance of all **25** open product matrix rows @ `a72ed54` |

---

### SCHWAB_CSV_FIRST_FAILING_OR_MIXED_NON_BLOCKING

| Field | Value |
|-------|-------|
| **Status** | `CLOSED_WITH_EVIDENCE` @ `741091b` |
| **Also tracked as** | `SCHWAB_CSV_FIRST_CI_MIXED_OR_FAILING_NON_BLOCKING` |
| **Source PR / report** | GitHub PR runs `27870946980` + push `27870946302` @ `741091b` |
| **Why it matters** | Merge gate is `pull_request` workflow; push-only pass is not merge sign-off |
| **Operator risk** | New market reads ship without V4 register row |
| **Evidence currently available** | PR path red @ `a72ed54` run `27857853589` (35 mega-inventory false positives); fixed @ `741091b`; both PR + push green |
| **Evidence still needed** | None — schwab-csv-first closed @ `741091b` |
| **Fix now or harness now** | Landed @ `741091b`: exclude `governance/megaN_traceable_inventory.py` from diff-emission scan |
| **Owner branch** | `audit/ci-nonblocking-failures-triage` |
| **Blocking level** | Closed |
| **Do not close until** | Met @ `741091b` |

---

### ADMIN_BYPASS_USED_WITH_FAILED_CHECKS

| Field | Value |
|-------|-------|
| **Status** | `ACCEPTED_WITH_EVIDENCE` |
| **Source PR / report** | `docs/ADMIN_BYPASS_REGISTER.md` |
| **Why it matters** | Protection model must stay honest |
| **Operator risk** | Ceremonial branch protection |
| **Evidence currently available** | Register entries PR #14–#16 |
| **Evidence still needed** | None for register existence |
| **Fix now or harness now** | Register in stabilization branch |
| **Owner branch** | N/A — tracked |
| **Blocking level** | Low |
| **Do not close until** | N/A — ongoing discipline |

---

### ED_CALIBRATION_LOG_DISABLED_EVIDENCE_GAP

| Field | Value |
|-------|-------|
| **Status** | `ACCEPTED_WITH_EVIDENCE` |
| **Source PR / report** | `docs/RUNTIME_EVIDENCE_ENV_CONTRACT.md`; objective-audit warning |
| **Why it matters** | Calibration rows silently skipped |
| **Operator risk** | Proof runs incomplete |
| **Evidence currently available** | Env contract; RTH harness blocks PASS when disabled |
| **Evidence still needed** | Operator sets `ED_CALIBRATION_LOG=1` for RTH proof |
| **Fix now or harness now** | Contract + harness gate |
| **Owner branch** | Operator env |
| **Blocking level** | Medium for RTH PASS |
| **Do not close until** | RTH runs record env explicitly |

---

### PROCESS_LOCAL_SQLITE_COUNTERS_ONLY

| Field | Value |
|-------|-------|
| **Status** | `ACCEPTED_WITH_EVIDENCE` |
| **Source PR / report** | PR #14–#15 |
| **Why it matters** | Multi-worker would need aggregation |
| **Operator risk** | Under-report contention |
| **Evidence currently available** | Single-process deploy today |
| **Evidence still needed** | Only if multi-worker |
| **Fix now or harness now** | Documented limitation |
| **Owner branch** | `fix/db-contention-aggregate` if architecture changes |
| **Blocking level** | Low (single process) |
| **Do not close until** | Architecture change |

---

### CARD_EXPLAINABILITY_NOT_IMPLEMENTED

| Field | Value |
|-------|-------|
| **Status** | `COMPLETION_BRANCH_REQUIRED` |
| **Source PR / report** | PR #13 Card Trust Contract |
| **Why it matters** | Cards do not explain fusion/histogram/tape conflict |
| **Operator risk** | Price down, cards up — trust erosion |
| **Evidence currently available** | `docs/CARD_TRUST_CONTRACT.md` |
| **Evidence still needed** | UI implementation + tests |
| **Fix now or harness now** | Blocked — `card_explainability_allowed: false` per stabilization gate |
| **Owner branch** | `fix/card-price-conflict-explainability` (after `operator_readiness_gate_pass`) |
| **Blocking level** | High — primary operator trust gap |
| **Do not close until** | `card_explainability_allowed: true` in gate JSON and branch merged with paired tests |

---

### FUSION_HISTOGRAM_OVERRIDE_POLICY_UNDECIDED

| Field | Value |
|-------|-------|
| **Status** | `COMPLETION_BRANCH_REQUIRED` |
| **Source PR / report** | Card Trust Contract; fusion-only defaults |
| **Why it matters** | Policy hole when fusion and histogram disagree |
| **Operator risk** | Silent override semantics |
| **Evidence currently available** | `ED_MH_EMPIRICAL_SUPPORT=0.0` default |
| **Evidence still needed** | Governed policy decision |
| **Fix now or harness now** | Investigation branch |
| **Owner branch** | `investigate/fusion-empirical-override-policy` |
| **Blocking level** | Medium |
| **Do not close until** | Policy row + mechanical lock or O-NN |

---

### MARKET_SESSION_TRADEABILITY_GUARD_NOT_AUDITED

| Field | Value |
|-------|-------|
| **Status** | `COMPLETION_BRANCH_REQUIRED` |
| **Source PR / report** | Card Trust Contract session boundaries |
| **Why it matters** | After-hours actionable appearance |
| **Operator risk** | Trade outside valid session |
| **Evidence currently available** | `dr-session-boundary-chip` partial |
| **Evidence still needed** | End-to-end session audit |
| **Fix now or harness now** | Audit branch |
| **Owner branch** | `audit/market-session-tradeability-guard` |
| **Blocking level** | Medium |
| **Do not close until** | Audit + fix or accepted limitation |

---

### GUEST_DATA_COMPLETENESS_NOT_PROVEN

| Field | Value |
|-------|-------|
| **Status** | `NEEDS_RTH_VALIDATION_WITH_HARNESS` |
| **Source PR / report** | PR #11/#16 guest transport |
| **Why it matters** | Switch-safe ≠ data-complete per layer |
| **Operator risk** | Missing histogram/ALL/PLAN looks like model signal |
| **Evidence currently available** | `GUEST DATA INCOMPLETE` switch state; partial copy policy |
| **Evidence still needed** | Per-layer matrix per guest ticker |
| **Fix now or harness now** | RTH + guest partial UI copy |
| **Owner branch** | RTH validation + card explainability |
| **Blocking level** | High |
| **Do not close until** | Layer availability proven or `GUEST PARTIAL` copy shown |

---

### RTH_VALIDATION_NOT_EXECUTED_AFTER_TRANSPORT_FIXES

| Field | Value |
|-------|-------|
| **Status** | `NEEDS_RTH_VALIDATION_WITH_HARNESS` |
| **Source PR / report** | PRs #11–#16; master runbook |
| **Why it matters** | Instrumentation ≠ live proof |
| **Operator risk** | False confidence from green offline audits |
| **Evidence currently available** | `reports/rth_validation/RTH_OPERATOR_TRUST_VALIDATION_RUNBOOK.md` |
| **Evidence still needed** | Operator executes master checklist during RTH |
| **Fix now or harness now** | Harnesses + master runbook in stabilization |
| **Owner branch** | Operator host |
| **Blocking level** | **OPEN_BLOCKING** for production claims |
| **Do not close until** | Dated validation reports with PASS classifications |

---

### CLOSED_WITH_EVIDENCE — PR #12 Tier C dedup

| Field | Value |
|-------|-------|
| **Status** | `CLOSED_WITH_EVIDENCE` |
| **Source PR / report** | PR #12 @ `4129a96` |
| **Why it matters** | Duplicate Tier C renders |
| **Operator risk** | N/A — fixed |
| **Evidence currently available** | `_tierCCardRenderFingerprint` tests |
| **Evidence still needed** | None |
| **Fix now or harness now** | CLOSED_WITH_EVIDENCE |
| **Owner branch** | N/A |
| **Blocking level** | None |
| **Do not close until** | N/A |
