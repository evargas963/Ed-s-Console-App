> **Classification:** Operational Ledger | **Scope:** Operator-trust closure matrix — not a parking lot

# Open items — operator trust register

**Purpose:** No passive **known remaining risks**. Every item has status, owner branch, and **Do not close until**.

**Allowed statuses only:** `OPEN_BLOCKING` | `NEEDS_RTH_VALIDATION_WITH_HARNESS` | `FIXED_IN_THIS_BRANCH` | `COMPLETION_BRANCH_REQUIRED` | `ACCEPTED_WITH_EVIDENCE` | `CLOSED_WITH_EVIDENCE`

**Gate semantics (machine-readable — `governance/OPERATOR_TRUST_STABILIZATION_GATE.json`):**
- `stabilization_artifacts_gate_pass: true` — harnesses, checker, and closure docs exist on disk.
- `operator_readiness_gate_pass: false` — CI triage + RTH proof not complete.
- `card_explainability_allowed: false` — **do not** start `fix/card-price-conflict-explainability`.
- **Next allowed branch:** `audit/ci-nonblocking-failures-triage` (then operator RTH validation).

**Planned sequence:** Merge stabilization → `audit/ci-nonblocking-failures-triage` → operator RTH validation → `fix/card-price-conflict-explainability` (only when `card_explainability_allowed: true`)

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
| **Status** | `FIXED_IN_THIS_BRANCH` |
| **Source PR / report** | `audit/ci-nonblocking-failures-triage`; `reports/ci/ci_nonblocking_failure_triage_2026-06-18.md` |
| **Why it matters** | Only objective-audit trusted — repo health degraded |
| **Operator risk** | Regressions hide in red checks |
| **Evidence currently available** | Fixes landed: F401, schwab false-positive scope, pytest CI placeholders |
| **Evidence still needed** | GitHub `main` push: all three workflows green |
| **Fix now or harness now** | Fixes in `audit/ci-nonblocking-failures-triage` |
| **Owner branch** | `audit/ci-nonblocking-failures-triage` |
| **Blocking level** | High until CI green on GitHub |
| **Do not close until** | `hardening`, `pytest-full`, `schwab-csv-first` green on `main` CI |

---

### HARDENING_CI_FAILING_NON_BLOCKING

| Field | Value |
|-------|-------|
| **Status** | `FIXED_IN_THIS_BRANCH` |
| **Source PR / report** | CI triage 2026-06-19 — ruff F401 |
| **Why it matters** | Institutional locks may drift |
| **Operator risk** | Silent rule regression |
| **Evidence currently available** | `ruff check . --select F401,F821,E9` exit 0 locally |
| **Evidence still needed** | GitHub hardening workflow green |
| **Fix now or harness now** | F401 fixed repo-wide |
| **Owner branch** | `audit/ci-nonblocking-failures-triage` |
| **Blocking level** | Medium |
| **Do not close until** | `hardening` green on GitHub `main` |

---

### PYTEST_FULL_CI_FAILING_NON_BLOCKING

| Field | Value |
|-------|-------|
| **Status** | `FIXED_IN_THIS_BRANCH` |
| **Source PR / report** | CI triage 2026-06-19 — SCHWAB_API_KEY at webServer startup |
| **Why it matters** | Full suite catches cone gaps |
| **Operator risk** | Production-only test failures |
| **Evidence currently available** | `pytest.yml` CI placeholder env (not live credentials) |
| **Evidence still needed** | GitHub pytest-full workflow green |
| **Fix now or harness now** | CI env placeholders |
| **Owner branch** | `audit/ci-nonblocking-failures-triage` |
| **Blocking level** | Medium |
| **Do not close until** | `pytest-full` green on GitHub `main` |

---

### SCHWAB_CSV_FIRST_FAILING_OR_MIXED_NON_BLOCKING

| Field | Value |
|-------|-------|
| **Status** | `FIXED_IN_THIS_BRANCH` |
| **Source PR / report** | CI triage 2026-06-19 — diff-emission false positives |
| **Why it matters** | Schwab diff-emission gate for market fields |
| **Operator risk** | New market reads without register row |
| **Evidence currently available** | Scanner path exclusions + homonym tests |
| **Evidence still needed** | GitHub schwab-csv-first green on this PR |
| **Fix now or harness now** | `check_schwab_csv_first.py` precision fix |
| **Owner branch** | `audit/ci-nonblocking-failures-triage` |
| **Blocking level** | Medium |
| **Do not close until** | `schwab-csv-first` green on GitHub `main` |

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
