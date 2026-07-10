> **Classification:** Generated Rendering | **Scope:** Universal engineering standard (derived; canonical source is the JSON artifact).

<!-- GENERATED FILE — DO NOT EDIT. Derived from governance/standard/universal_institutional_engineering_standard_v1.json by tools/check_universal_standard.py --render. Drift fails governance. -->

# UNIVERSAL_INSTITUTIONAL_ENGINEERING_STANDARD_V1 (v1.0.0)

**Answers:** HOW MUST ALL WORK BE DONE AND PROVEN?
**Does not answer:** WHAT SHOULD WE WORK ON NEXT?

**Applicability:** Every Ed Console repository task: data, database, calculations, features, models, signals, risk, execution, APIs, transport, UI, infrastructure, testing, governance, documentation, refactoring, and production operations.

## Primary objective (UIES-OBJ)

Every task must materially advance Ed Console toward institutional-grade standards comparable in rigor, reliability, transparency, and operator trust to systems used by professional trading firms, institutional market-data and analytics platforms, Bloomberg Terminal-class operator systems, Reuters/LSEG Workspace-class financial platforms, regulated production financial software, and serious quantitative research environments. The objective is not to accumulate green tests, close small checklist items, or make the application look more complete. The objective is to build a system whose: market data is trustworthy; calculations are correct; database history is temporally valid; features are free from look-ahead contamination; models are empirically justified; confidence values mean what the UI says they mean; signals have measured outcome validity; risk and sizing are controlled; live behavior matches tested and backtested behavior; failures are visible and fail closed; operator surfaces are truthful; runtime identity and evidence are reproducible; and real-money decisions can be reconstructed and audited.

## Universal principles

### UIES-P01 — material_institutional_advancement

Every task must identify the concrete institutional capability it improves (e.g., data truth, temporal integrity, calculation correctness, empirical validity, calibration, risk control, execution realism, production reliability, observability, explainability, reproducibility, operator trust, regression prevention). A task may be small when it removes a foundational blocker. A task may not be accepted merely because it is easy, cosmetic, or produces green tests.

### UIES-P02 — root_cause_correction

Every defect must be traced to the earliest defensible root cause. Where applicable, analysis follows: SOURCE -> INGESTION -> STORAGE -> TIMESTAMPING -> NORMALIZATION -> FEATURE/CALCULATION -> MODEL -> FUSION/POLICY -> DECISION -> API -> TRANSPORT -> UI -> OPERATOR ACTION -> OUTCOME. Do not patch downstream symptoms while upstream truth remains defective.

### UIES-P03 — universal_design

Fixes must be universal by construction across the supported dimensions relevant to the task, including as applicable: tickers, horizons, sessions, roster sizes, data states, missing/stale conditions, deployment modes, process lifecycles, concurrency, and runtime environments. Representative examples do not by themselves prove universality.

### UIES-P04 — truthful_semantics

Names, labels, payloads, displays, metrics, probabilities, statuses, and evidence must mean exactly what they claim. Do not: relabel an incorrect quantity; fabricate unavailable values; convert unknown states into false or clean states; present stale data as current; present diagnostics as process identity; or imply proof that has not been obtained.

### UIES-P05 — empirical_and_mathematical_validity

Trade-determinative calculations, models, probabilities, confidence values, signal logic, thresholds, and policies must be supported by: defined semantics, traceable inputs, valid mathematics, appropriate holdout or out-of-sample evidence, outcome validation, and explicit failure behavior. Passing code tests does not prove trading validity.

### UIES-P06 — fail_closed_behavior

When required truth, provenance, freshness, capacity, calibration, validation, or safety conditions are unavailable, the system must fail closed where money-path behavior is affected. Failure must be explicit, observable, attributable, and testable.

### UIES-P07 — mechanical_regression_prevention

Every material fix must add or strengthen an appropriate mechanical lock: deterministic tests, schema validation, invariant checks, static analysis, runtime assertions, contract tests, mutation detection, CI enforcement, or governed artifact validation. A prose statement alone is not a mechanical lock.

### UIES-P08 — complete_proof

Acceptance must be based on the evidence appropriate to the task: code-path evidence, deterministic tests, adversarial tests, runtime proof, data proof, browser/transport proof, model or statistical validation, exact diff scope, remote CI, and committed-SHA identity. The absence of an observed failure is not proof.

### UIES-P09 — honest_binary_status

Use explicit statuses: `PROVEN` / `NOT_PROVEN`; `APPROVED` / `NOT_APPROVED`; `PASS` / `FAIL`; `CLOSED_WITH_EVIDENCE` / `NOT_CLOSED`; `AUTHORIZED` / `NOT_AUTHORIZED`. Do not use ambiguous closure language.

### UIES-P10 — controlled_change_scope

Each task must identify its mission-owned scope. No unrelated ride-along changes are permitted. Implementation, commit, push, and merge authorization remain separate decisions unless explicitly combined by policy.

### UIES-P11 — engineering_autonomy_within_the_standard

The standard governs outcomes, truth, scope, universality, evidence, and acceptance. It must not over-prescribe ordinary implementation details such as helper names, class names, line count, test fixture style, internal decomposition, or one specific algorithm when multiple approaches satisfy the standard. The standard prevents drift without causing continuous approval churn.

### UIES-P12 — explicit_exceptions

Any exception to the universal standard must be explicit, narrowly scoped, justified, approved, time-bounded or review-bounded where appropriate, recorded, and mechanically detectable. Silent exceptions are prohibited.

## Required task declarations

- `STANDARD_VERSION`
- `INSTITUTIONAL_CAPABILITY_ADVANCED`
- `ROOT_CAUSE_TARGET`
- `MONEY_PATH_IMPACT`
- `UNIVERSALITY_DIMENSIONS`
- `TRUTH_SEMANTICS`
- `FAIL_CLOSED_REQUIREMENT`
- `MECHANICAL_REGRESSION_LOCK`
- `REQUIRED_PROOF`
- `MISSION_OWNED_SCOPE`
- `EXCEPTIONS`
- `BINARY_ACCEPTANCE_CRITERIA`

- Trigger: Any governed artifact block that declares STANDARD_VERSION invokes full task-contract validation.
- Priority exclusion: These declarations describe the standard of execution. They must not dictate which task should be selected next. Priority lives in queue files, mission packets, operator decisions, and evidence artifacts - never in this standard.

## Closure contract (UIES-CLOSURE)

1. What institutional weakness existed?
2. What root cause created it?
3. What concrete capability was improved?
4. Which universal dimensions were covered?
5. What semantics are now truthful?
6. What failure behavior was proven?
7. What tests and runtime/data evidence support the result?
8. What mechanical lock prevents regression?
9. What remains not proven?
10. What exact code identity and diff were tested?
11. What is the binary status?

A task may not close unless its evidence packet answers every applicable question. The closure checker must reject unsupported closure. The FULL_FIXES_ONLY_V2 evidence gate remains the mechanical closure vocabulary; this contract defines what its evidence must answer.

## Prohibited practices

- accumulating green tests as a goal in itself
- cosmetic completion of checklist items
- downstream symptom patches over defective upstream truth
- representative-only proof presented as universality — such evidence must be classified REPRESENTATIVE_ONLY_NOT_PROVEN
- relabeling incorrect quantities
- fabricating unavailable values
- converting unknown states into clean states
- presenting stale data as current
- presenting diagnostics as process identity
- prose-only regression prevention
- ambiguous closure language in governed status fields
- silent exceptions
- unrelated ride-along changes
- embedding current priority, active lanes, SHAs, PIDs, or CI state into this standard

## Exceptions

Silent exceptions are prohibited. An exception line missing any required field is invalid.
- Format: `UIES_EXCEPTION_APPROVED: scope=<narrow-scope> justification=<why> approved_by=<operator-ref> bound=<time-or-review-bound>`

## Domain profiles

- **INSTITUTIONAL_STANDARD_V3** (governance/INSTITUTIONAL_STANDARD_V3.md): Domain profile under this universal standard; it does not define a competing repository-wide objective.
- **SCHWAB_UNIVERSAL_COVERAGE_PROGRAM_V4** (governance/SCHWAB_UNIVERSAL_COVERAGE_PROGRAM_V4.md): Domain program under this universal standard; market-field disposition law is unchanged by this artifact.

## Enforcement

- Checker: `tools/check_universal_standard.py`
- Invoked from: tools/check_fix_everything_we_touch.py::_REPO_WIDE_STATIC_CHECK_FUNCS (enforce-all + objective-audit + CI hardening/objective gates)
- Tests: `tests/test_universal_institutional_standard.py`
