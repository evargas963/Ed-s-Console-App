# Infrastructure Governance Phase Plan

## 1. Status and authority

**Status:** **LOCKED** — approved for implementation.  
**Version:** 1.0.1 LOCKED  

**Normative hierarchy for this phase plan:**

- `governance/INSTITUTIONAL_STANDARD_V3.md` (V3) — locked standard.  
- `governance/V3_LOCK_RECORD.md` — lock conditions and regression rules.  
- `governance/V3_CONFORMANCE_AUDIT.md` — evidenced non-conformance baseline.  
- Pre-INF audit artifacts (this plan’s operational inputs):  
  `governance/TRADE_IMPACTING_ROUTE_INVENTORY.md`,  
  `governance/PRODUCTION_CLAIMS_REGISTER.md`,  
  `governance/OPERATOR_DECISION_REGISTER.md` (sign-off context),  
  `governance/GOVERNANCE_EVENT_MODEL.md`,  
  `governance/EXISTING_ARTIFACT_TRANSITION_POLICY.md`,  
  and **`OPEN_ITEMS.md`** (repository root).  

**V3 is locked.** This phase plan was **LOCKED** at version **1.0** on **2026-05-01** following: (1) operator review and explicit written approval, (2) governance merge-gate PASS on **2026-05-01**, and (3) approved register and aligned upstream artifacts (per §18). **Version 1.0.1** (**2026-05-02**) is an **administrative amendment** only: §§1–2 mirror / upstream language and §18 checklist alignment with **`OPERATOR_DECISION_REGISTER.md`** (**O-16–O-19**) and merge gate **G1** scope (**§§6–14**, **including §10** governance-event decisions). **No** change to INF numeric thresholds, execution order, route/claim tables, or closure criteria in §§5–9 / §15. Subsequent changes require version bump and updated approval.

**Mandatory doctrine (non-negotiable):**  
*Design for institutional capability; execute against evidenced gaps; closure = enforceable + auditable + non-bypassable + proof + claim binding.*

**Mandatory current state statement:**

- V3 is locked.  
- Pre-INF audit is complete (routes, claims, events, artifacts).  
- Route Inventory, Claims Register, Governance Event Model, Existing Artifact Transition Policy, and Operator Decision Register are **source artifacts** for this plan.  
- **Binding operator decisions** are **controlled** by **`governance/OPERATOR_DECISION_REGISTER.md`** (register **upstream**), **approved 2026-05-01**. The **final operator decision set** embedded in **§§6–14** below (**including §10** governance-event decisions) **mirrors** that register and is **authoritative** for INF implementation and review.  
- This document is **LOCKED** at version **1.0.1** following operator approval, merge-gate **PASS** on **2026-05-01** (v1.0), and **administrative amendment** on **2026-05-02** (v1.0.1, per §18 changelog).  
- **INF implementation** is **not** complete until code, proof artifacts, and tests satisfy §15; until then, conformance rows for INF items remain **non-CONFORMS** per audit taxonomy (document lock ≠ INF closure).

---

## 2. Source artifacts and inputs

| Artifact | Path | Role |
|-----------|------|------|
| Institutional standard | `governance/INSTITUTIONAL_STANDARD_V3.md` | Invariants I-17, I-19, I-20; §14.6; degradation doctrine |
| Lock record | `governance/V3_LOCK_RECORD.md` | Binary conformance; no silent non-conformance; regression |
| Conformance audit | `governance/V3_CONFORMANCE_AUDIT.md` | INF-1–INF-4 gap evidence |
| Merge gate | `governance/GOVERNANCE_MERGE_GATE.md` | Binary PASS/FAIL before governance commit |
| Open items | `OPEN_ITEMS.md` (repo root) | Cross-workstream tracking; INF row pointers |
| Route inventory | `governance/TRADE_IMPACTING_ROUTE_INVENTORY.md` | Route IDs R-001–R-035; TI classification |
| Claims register | `governance/PRODUCTION_CLAIMS_REGISTER.md` | Claim IDs C-SRV-*, C-UI-*, C-GOV-*, C-OPS-*, C-LOG-01 |
| Operator decision register | `governance/OPERATOR_DECISION_REGISTER.md` | **Upstream authority** for binding numerics and policies in **§§6–14** (**including §10** governance-event decisions) |
| Governance event model | `governance/GOVERNANCE_EVENT_MODEL.md` | **ACTIVE**; aligns with §10; field semantics and storage bound by register **O-16–O-19** |
| Artifact transition | `governance/EXISTING_ARTIFACT_TRANSITION_POLICY.md` | Forward-only; aligns with §11 |
| Target state (strategic) | `governance/PHASE_PLAN_TARGET_STATE.md` | P0–P7 context only; **excluded from minimal governance commit** per register **O-14**; track in `OPEN_ITEMS.md` |
| Lock reviewer index (optional) | `governance/INFRASTRUCTURE_GOVERNANCE_LOCK_PACKAGE.md` | Non-normative index; disposition per register **O-15** |
| Mirrored operator decision set | **Sections 6–14 below** (**§10** governance-event binding decisions included) | Same thresholds, schemas, and policies as register **O-01–O-19** after sign-off; **`OPERATOR_DECISION_REGISTER.md`** is **upstream** |

**Missing inputs:** **None** — all listed files exist at paths above (`OPEN_ITEMS.md` at repository root), subject to **O-14** / **O-15** commit-scope rules.

---

## 3. Scope and non-scope

**In scope (this phase plan only):**

| INF | V3 anchor | Topic |
|-----|-----------|--------|
| INF-3 | I-20 | Dependency pinning / **environment fingerprint** |
| INF-2 | I-19 | Clock synchronization health |
| INF-1 | I-17 | Deterministic inference + replay |
| INF-4 | §14.6 | Kill switch / halt authority |

**Explicit non-scope:**

- **G2** cascade alignment.  
- **G3** promotion authority unification **except** where **G3-R1** (validator vs runtime bundle definition) is cited as **INF-1 prerequisite** — no G3 implementation work is owned here.  
- **G4** full tuple-health matrix / direct-write quarantine **except** minimal hooks (e.g. health flags) **required** by INF closure tests.  
- **G5** end-to-end model lifecycle proof.  
- Model **retraining**, **feature engineering**, performance tuning.  
- **UI redesign** except: **claim / synthetic / debug / MC advisory** labeling and API fields mandated herein.  
- **Order execution**, broker APIs, OMS — **out of repo**; execution boundary is fixed (§8 operator set).

---

## 4. Execution order

**Locked order:** **INF-3 → INF-2 → INF-1 → INF-4**

| Order | INF | Rationale (one line each) |
|-------|-----|---------------------------|
| 1 | INF-3 | Determinism and replay are meaningless if the serving environment can change without detection (I-20). |
| 2 | INF-2 | Replay, stale claims, and `decision_timestamp_utc` semantics require bounded clock skew (I-19). |
| 3 | INF-1 | Deterministic inference proof requires stable env (INF-3) and stable time identity (INF-2). |
| 4 | INF-4 | Halt must cover all **YES/CONDITIONAL** routes after route inventory and middleware boundaries are fixed. |

**Dependency (non-owned):** **G3-R1** must not block **drafting** this plan; it **blocks INF-1 closure** until one authoritative “complete bundle” definition exists for replay (per `OPEN_ITEMS.md` / audit).

---

## 5. Route and claim binding summary

### 5.1 Route ID → INF enforcement map

**Legend:** ✓ = required enforcement for that INF on the route; — = not primary for that route; **P** = partial (labeling / health only).

| Route ID | TI (inventory) | INF-3 | INF-2 | INF-1 | INF-4 |
|----------|------------------|-------|-------|-------|-------|
| R-001 | YES | ✓ | ✓ | ✓ | ✓ |
| R-002 | YES | ✓ | ✓ | ✓ | ✓ |
| R-003 | CONDITIONAL | ✓ | ✓ | ✓ | ✓ |
| R-004 | YES | ✓ | ✓ | ✓ | ✓ |
| R-005 | NO (synthetic) | ✓ | P | — | ✓ |
| R-006 | YES (indirect) | ✓ | ✓ | ✓ | ✓ |
| R-007 | YES | ✓ | ✓ | ✓ | ✓ |
| R-008 | YES (indirect) | ✓ | ✓ | ✓ | ✓ |
| R-009 | YES (indirect) | ✓ | ✓ | ✓ | ✓ |
| R-010 | CONDITIONAL | ✓ | ✓ | ✓ | ✓ |
| R-011 | YES | ✓ | ✓ | ✓ | ✓ |
| R-012 | NO | P | P | — | ✓ |
| R-013 | NO | P | P | — | P |
| R-014 | CONDITIONAL | ✓ | ✓ | ✓ | ✓ |
| R-015 | CONDITIONAL | P | P | P | P |
| R-016 | CONDITIONAL | P | P | P | P |
| R-017 | CONDITIONAL | ✓ | P | ✓ | ✓ |
| R-018–R-026 | NO | P | P | — | P |
| R-027 | NO immediate | P | P | P | P |
| R-028 | CONDITIONAL | P | P | P | P |
| R-029–R-030 | NO | P | P | — | P |
| R-031 | YES | ✓ | ✓ | ✓ | ✓ |
| R-032 | YES | ✓ | ✓ | ✓ | ✓ |
| R-033 | YES stack / NO prod UI | ✓ | ✓ | ✓ | — |
| R-034 | future | P | P | P | P |
| R-035 | NO | — | — | — | — |

### 5.2 Explicit route coverage (operator mandates)

- **R-005 (`no_valid_expiry`):** Must emit **`synthetic_decision_bundle: true`**, **`decision_source: "no_valid_expiry"`**, **`the_call_authoritative: false`**; UI banner **“Synthetic — no chain decision”**; event **`SYNTHETIC_BUNDLE_SERVED`** when served to **non-localhost** client.  
- **Stale Tier C (R-010, R-014):** Claims tied to “fresh” or “live” decision must use **`analytics_stale`**, **`decision_generation_id`**, and post–INF-2 **clock health** fields; **C-SRV-03** / **C-UI-03** / **C-UI-17** bounded until INF-2 + claims work merged.  
- **`/api/debug/prediction` (R-011):** Subject to **§10 debug policy**; when disabled, **404** without body detail.  
- **Background logger (R-007):** Same INF envelope as R-004; proof artifacts must include **logger-attributed** samples where required.  
- **Calibration / profiler / verify (R-031–R-033):** Same stack semantics; **not** `ED_SERVING_PROCESS=1` path; fingerprint and halt policies apply **when** those processes load blessed weights — separate CI contract; **INF-3 proof** focuses on **serving process** per operator §12.

### 5.3 Claim ID → INF closure or downgrade

| Claim ID | Supported today | Required action |
|-----------|-----------------|-----------------|
| C-SRV-02 authoritative L1 | PARTIAL | Downgrade label or add **`claims_tier`** until INF-3 + INF-1 proof |
| C-SRV-03 full MarketState | PARTIAL | Clarify stale / pending shell; INF-2 clock health on Tier C |
| C-UI-01 LIVE / provenance | PARTIAL | Tooltip + **`claims_tier: pre_inf`** until proof |
| C-UI-05 LIVE_READY | PARTIAL | Disambiguate from halt; INF-4 UI copy |
| C-UI-06 Base models live | PARTIAL | INF-3 env + INF-1 replay scope |
| C-UI-07 authoritative ticker | NO | Rename client string or server doc — **UI/claim work** with INF |
| C-UI-08 _authoritative telemetry | PARTIAL | Document as client telemetry vocabulary or rename |
| C-UI-10 actionableNow | PARTIAL | “UI heuristic — not order router” + **`execution_boundary`** text |
| C-UI-11 active compliant | PARTIAL | G3-R1 alignment for wording; until then **`claims_tier`** |
| C-UI-12–15, C-UI-17–18, C-UI-20–21 | PARTIAL | INF-2 + INF-3 + **`claims_tier`** |
| C-UI-16 Deterministic FEED | NO | Rename to **fixed thresholds** (required UI change) |
| C-GOV-*, C-OPS-* | PARTIAL / YES | Governance panel claims remain **panel-scope** only |

---

## 6. INF-3 — Dependency pinning / environment fingerprint (I-20)

**Invariant:** V3 **I-20** — serving runtime dependencies pinned; drift is governance event; manifest-validated.

**Operator decisions (exact):**  
Fingerprint fields (see register **O-05**): `python_version` (first line of `sys.version`), `platform` = `sys.platform`, `implementation` = `platform.python_implementation()`, `deps_sha256` = SHA-256 of UTF-8 of **sorted line-by-line** `pip freeze` stdout, `repo_git_commit` = 40-char `git rev-parse HEAD` or **`unknown`**, `cuda_visible_devices` = exact env or `""`, `torch_cuda_version` = `torch.version.cuda` or `null`. **`cwd_sha256` is not used** — excluded as operational noise (consensus P-02 / N-02). Canonical JSON **keys sorted**, UTF-8, SHA-256 → **`env_fingerprint_sha256`**. **No equivalence classes** — any field change changes hash.

**Serving path (exact):** Single OS process: **`uvicorn server:app`**, `cwd` = repo root, **`ED_SERVING_PROCESS=1`** required in production. **All** FastAPI routes on that app **except** `GET /favicon.ico`, `GET /guide/*`, `GET /`, static non-API mounts. **Excluded:** `calibration/`, `tests/`, `tools/`, `ml_scheduler.py` CLI, `verify_*.py`. Fingerprint **at process start only** in that process.

**Enforcement points:**

1. **Process startup:** compute `env_fingerprint_sha256`; compare to blessed value for active governance era; emit **`INFRA_DRIFT`** on mismatch.  
2. **Route entry:** middleware on all **YES/CONDITIONAL** Route IDs (per inventory) re-validates or reads cached startup result — no **unauthenticated** bypass.  
3. **Proof artifact:** written `environment_fingerprint.json` + startup validation log row in **`governance_events`**.

**Failure behavior:** Default **BLOCK** trade-impacting outputs (YES/CONDITIONAL routes) on mismatch or missing blessed fingerprint. **`INFRA_DRIFT`** event mandatory. Response is **BLOCK** with structured error body (implementation may use HTTP 503 where appropriate for serving process).

**Proof artifacts:** `environment_fingerprint.json` (canonical), startup log, **`governance_events`** rows.

**Negative tests (required):**

| Test name | Expected |
|-----------|----------|
| `test_inf3_deps_hash_mismatch_blocks_ti` | TI route returns block / 503 with no normal prediction body |
| `test_inf3_missing_fingerprint_blocks_ti` | Same |
| `test_inf3_serving_without_ed_serving_process` | Production serving process fails startup or refuses `claims_tier` governance assertion when `ED_SERVING_PROCESS≠1` |

**Closure criteria (binary):**

- [ ] Blessed `env_fingerprint_sha256` stored and versioned.  
- [ ] Startup compare implemented and tested.  
- [ ] Mismatch path tested; **`INFRA_DRIFT`** emitted.  
- [ ] **`claims_tier`** / artifact linkage documented for Tier C.

---

## 7. INF-2 — Clock synchronization health (I-19)

**Invariant:** V3 **I-19** — producer-consumer skew bounded and monitored.

**Operator decisions (exact):**

- **Primary clock:** `decision_timestamp_utc` = UTC from **`time.time()`** at instant **`stamp_decision_bundle()`** runs in `live_decision_bundle.py`.  
- **Secondary:** (1) Schwab L1 **quoteTime** / last trade time when present; (2) SQLite **`CURRENT_TIMESTAMP`** UTC at **`insert_snapshot`** commit; (3) last completed **1m bar** datetime used in stack.  
- **Fallback:** If quote time missing → use **primary only** for quote-skew pairs; **never** invent synthetic quote time.  
- **Arbitration:** Features/labels use bar/candle **≤** primary `decision_timestamp_utc`. Skew compares **primary vs quote** and **primary vs DB write** only. UI age = **primary − quote_time** when both exist.

**Threshold table (seconds, float):**

| Pair | Warning | Breach |
|------|---------|--------|
| primary vs quote | > 0.25 | > 1.5 |
| primary vs DB write | > 0.5 | > 3.0 |

**Hysteresis:** Warning after **2** consecutive warning-band samples; breach after **2** consecutive breach-band samples; clear warning after **5** consecutive samples below **80%** of warning threshold; clear breach after **3** consecutive below breach threshold **or** operator **`CLOCK_SKEW_BREACH`** resolution after **10-minute** automated cooldown.

**Required event:** **`CLOCK_SKEW_BREACH`** (and INFO-level warning event if distinct implementation adds one — minimum **`CLOCK_SKEW_BREACH`** on breach).

**Failure behavior:** **Warning** → degrade + visible machine-readable flag on Tier C. **Breach** → **BLOCK** authoritative decision outputs (conservative default); **`CLOCK_SKEW_BREACH`**. Missing required quote time when **`live_on=True`** and chain succeeded → **breach** class.

**Proof artifacts:** skew sample file or `governance_events` stream; clock health report JSON; breach/warning CI logs.

**Negative tests (required):**

| Test name | Expected |
|-----------|----------|
| `test_inf2_quote_skew_warning` | Warning state after hysteresis |
| `test_inf2_quote_skew_breach` | BLOCK + event |
| `test_inf2_db_skew_breach` | BLOCK + event |
| `test_inf2_missing_quote_time_live_on` | Breach path |

**Closure criteria (binary):**

- [ ] Primary stamp aligned with `stamp_decision_bundle` contract.  
- [ ] Both pairs monitored with table thresholds + hysteresis.  
- [ ] UI/API bound when skew unhealthy.  
- [ ] **`CLOCK_SKEW_BREACH`** tested.

---

## 8. INF-1 — Deterministic inference (I-17)

**Invariant:** V3 **I-17**.

**Operator decisions (exact):**

- **N = 7** replays.  
- **Discrete:** exact match.  
- **Float:** **`max_abs_diff`**, **`1e-5`** per probability in **[0,1]**.  
- **Scope:** `call.signal`, `call.conviction`, `call.validation_passed`, `call.execution_mode`, **`call.r_units`** rounded **4** decimals then exact; `dominant_dir` exact; `dominant_prob` rounded **6** decimals then `max_abs_diff 1e-5`; **primary** horizon triples **1c, 5c, 15c, 60c** only — `prob_up`, `prob_down`, `prob_flat` where present (register **O-10**). Horizons **3c, 8c, 13c** are **diagnostic only** for authoritative replay parity (same register row).  
- **Excluded from parity:** fields containing **`mc_`**, **`monte`**, diagnostic fields, **`analytics_age`**, **`server_ts`**, **`decision_generation_id`**.  
- **Replay harness:** same blessed artifact hashes; **frozen `decision_timestamp_utc` injection** for harness only.

**Monte Carlo (binding):** MC **must not** alter authoritative replay-scoped fields listed above. Tier C exposes MC only as **`mc_advisory`**: `{ "advisory": true, "non_binding": true, "schema_version": 1, ... }` or **`null`**. **INF-1 cannot close** until proof shows MC does not affect authoritative fields.

**Failure behavior:** Mismatch → **`REPLAY_FAILURE`**; block promotion / governed claims per route policy in implementation spec.

**Proof artifacts:** `replay_report.json`, tolerance diff output, harness command documented.

**Negative tests (required):**

| Test name | Expected |
|-----------|----------|
| `test_inf1_discrete_mismatch_fails` | REPLAY_FAILURE |
| `test_inf1_prob_tolerance_breach_fails` | REPLAY_FAILURE |
| `test_inf1_mc_cannot_mutate_authoritative` | Mutation attempt fails CI |
| `test_inf1_generation_timestamp_ignored` | Parity ignores excluded fields |

**Closure criteria (binary):**

- [ ] All scoped fields in replay diff.  
- [ ] Exclusions documented in harness.  
- [ ] **7** passes green on golden fixture.  
- [ ] **`REPLAY_FAILURE`** path tested.  
- [ ] MC non-mutation proof attached.

**G3-R1:** INF-1 **CLOSED** requires **G3-R1** resolved per `OPEN_ITEMS.md` (validator vs runtime bundle definition) — **external gate**; no closure until resolved.

---

## 9. INF-4 — Kill switch and halt authority (§14.6)

**Invariant:** V3 **§14.6**.

**Operator decisions (exact):**

**Storage:** SQLite at **`DB_PATH`** (same as `db.py` **EdDB**). Table **`infra_halt`**:  
`id INTEGER PRIMARY KEY`, `scope_type TEXT`, `scope_key TEXT`, `active INTEGER`, `reason TEXT`, `actor TEXT`, `created_utc TEXT`, `halt_event_id TEXT UNIQUE`. One active row per **`scope_type`+`scope_key`** or global **`scope_type='SYSTEM'`**.

**Enforcement layers (order):**

1. First executable line inside **`_fetch_state`** after ticker normalize.  
2. First line inside **`build_market_state`** before **`compute_signals`**.  
3. **FastAPI middleware** before routes for any Route ID with TI **YES** or **CONDITIONAL** in `TRADE_IMPACTING_ROUTE_INVENTORY.md`.

**Failure behavior:**

- Store unreadable → **BLOCK** all YES/CONDITIONAL TI routes; body includes **`{"halt":"store_unreachable"}`**.  
- Active halt → **BLOCK** same; body includes **`{"status":"halted","trade_impacting":false}`** (plus required scope fields as implementation adds without contradicting keys).

**Halt release:** **Dual identifier** — `release_operator_id` **case-insensitively ≠** `halt_actor`; both non-empty; payload includes `halt_event_id`, `halt_actor`, `release_operator_id`, `timestamp_utc`, **`reason` ≥ 10 chars**; **`HALT_RELEASE`** event; row **`active=0`**. **No time delay** under **Single-Operator Control Model** (register **O-08**); revisit if control model changes. **Limitation:** two strings ≠ two-person dual control; document in ops runbooks.

**Proof artifacts:** `HALT_ACTIVATION` + `HALT_RELEASE` events; route-block transcript (HTTP + logger path).

**Negative tests (required):**

| Test name | Expected |
|-----------|----------|
| `test_inf4_system_halt_blocks_tier_c` | 503 / halted body |
| `test_inf4_tuple_halt_blocks_route` | Applicable route blocked |
| `test_inf4_store_unreachable_blocks` | `store_unreachable` |
| `test_inf4_release_same_operator_fails` | Release rejected |
| `test_inf4_debug_without_triple_gate_404` | Debug 404 |

**Closure criteria (binary):**

- [ ] Middleware + `_fetch_state` + `build_market_state` checks present.  
- [ ] Release path + events tested.  
- [ ] Route inventory **YES/CONDITIONAL** coverage verified in CI list.

---

## 10. Governance event model integration

**Event types (locked):**  
`REPLAY_FAILURE`, `CLOCK_SKEW_BREACH`, `INFRA_DRIFT`, `HALT_ACTIVATION`, `HALT_RELEASE`, `VALIDATION_FAILURE`, `SYNTHETIC_BUNDLE_SERVED`.

**Required fields (locked):**  
`event_id` (UUID4), `event_type`, `invariant` or **`N/A`**, `severity` (**`SEVERITY_1`** | **`INFO`**), `scope` JSON, `actor`, `timestamp_utc` RFC3339 **Z**, `artifact_identity` JSON or `{}`, `environment_fingerprint` string or `""`, `details` length ≥ 1, `resolution_status` **`OPEN`** | **`RESOLVED`**.

**Storage (single choice):** SQLite table **`governance_events`** at **`DB_PATH`**, **INSERT-only** from application — **no UPDATE, no DELETE** in app code.

**INF → event mapping:**

| INF | Events |
|-----|--------|
| INF-1 | `REPLAY_FAILURE`, `VALIDATION_FAILURE` (bundle/schema) |
| INF-2 | `CLOCK_SKEW_BREACH` |
| INF-3 | `INFRA_DRIFT` |
| INF-4 | `HALT_ACTIVATION`, `HALT_RELEASE` |
| Synthetic policy | `SYNTHETIC_BUNDLE_SERVED` (once per synthetic response to **non-localhost** client) |

---

## 11. Existing artifact transition

**Policy:** **Forward-only** (operator set).

- Label **`governance_era: pre_inf`** in **`models/arch_state.json`** root.  
- Candidate **`scheduler_run_manifest.json`** gains **`governance_era: pre_inf`** on next train.  
- Historical DB snapshots **unchanged**.  
- Tier C API adds **`claims_tier: "pre_inf"`** until first post-INF proof bundle exists **per ticker**.  
- **No** mandatory DB backfill of old rows.

---

## 12. Claim downgrade / bounding requirements

Per **`PRODUCTION_CLAIMS_REGISTER.md`:**

- **Unsupported / PARTIAL** claims must carry **`claims_tier: pre_inf`** or explicit downgraded copy until INF proof closes.  
- **LIVE / authoritative / provenance compliant / deterministic** (UI) — align with **C-UI-01**, **C-UI-07–08**, **C-UI-16** remediation text in §5.3.  
- **Trade signal / confidence** — **C-UI-04**, **C-UI-10** must show non-order-router disclaimer where shown.  
- **Synthetic (R-005):** **`synthetic_decision_bundle`**, **`decision_source`**, **`the_call_authoritative: false`** + banner.  
- **MC:** UI **“Advisory / Non-binding”**; API **`mc_advisory`** schema.  
- **Debug:** §10 operator policy; **never** presented as governed production without triple gate.

---

## 13. Proof artifacts

| INF | Proof artifact | Path (proposed) | Regeneration | Reviewer | Pass/fail rule |
|-----|----------------|------------------|--------------|----------|----------------|
| INF-3 | Fingerprint JSON + startup log | `governance/proof/inf3/env_fingerprint.json` + `startup_validation.log` | Restart serving process with pinned env | Governance lead | Hash match; no startup without PASS row |
| INF-2 | Skew samples + health report | `governance/proof/inf2/skew_samples.jsonl` + `clock_health_report.json` | 24h capture job | Governance lead | No breach in window; hysteresis UT pass |
| INF-1 | Replay report | `governance/proof/inf1/replay_report.json` | `make replay-inf1` (to be defined in Makefile) | Governance lead | 7/7 passes; MC non-mutation |
| INF-4 | Halt transcript | `governance/proof/inf4/halt_drill_transcript.json` | Manual drill script | Two IDs distinct | All YES routes blocked; release works |

---

## 14. Negative test matrix

| Test name | INF | Route / claim | Expected failure | Closure role |
|-----------|-----|----------------|------------------|--------------|
| `test_inf3_deps_hash_mismatch_blocks_ti` | INF-3 | R-010 | Block / 503 | INF-3 |
| `test_inf3_missing_fingerprint_blocks_ti` | INF-3 | R-004 | Block | INF-3 |
| `test_inf2_quote_skew_breach` | INF-2 | R-004 | BLOCK + `CLOCK_SKEW_BREACH` | INF-2 |
| `test_inf2_missing_quote_time_live_on` | INF-2 | R-004 | Breach class | INF-2 |
| `test_inf1_discrete_mismatch` | INF-1 | harness | `REPLAY_FAILURE` | INF-1 |
| `test_inf1_mc_no_authoritative_mutation` | INF-1 | R-002/R-004 | CI fail if mutation | INF-1 |
| `test_inf4_halt_blocks_tier_c` | INF-4 | R-010 | halted JSON | INF-4 |
| `test_inf4_release_same_operator` | INF-4 | API | Reject | INF-4 |
| `test_debug_charm_404_without_gate` | INF-4 / policy | R-022 | 404 | Debug policy |
| `test_synthetic_fields_present_r005` | claims | R-005 | Missing field fails | Synthetic policy |

---

## 15. Closure criteria

**Binary per INF — no “mostly done”:**

| INF | CLOSED only if |
|-----|------------------|
| INF-3 | All §6 checkboxes + proof row + CI negatives + `INFRA_DRIFT` live |
| INF-2 | All §7 checkboxes + proof + `CLOCK_SKEW_BREACH` live |
| INF-1 | All §8 checkboxes + **G3-R1** resolved per `OPEN_ITEMS.md` (**external gate; no waiver**) + MC proof |
| INF-4 | All §9 checkboxes + drill transcript |

If any proof missing → row stays **`DOES_NOT_CONFORM_TRACKED`** or **`DOES_NOT_CONFORM_NEW_GAP`** per audit taxonomy — **never `CONFORMS`**.

---

## 16. Deferred items / explicit non-goals

- External halt plane / separate control host **deferred** (v2).  
- SBOM / container image digest **deferred**.  
- Exhaustive every-string HTML pass (**claims v2**) optional unless new claim discovered.  
- **G2–G5** model lifecycle **separate workstreams**.  
- **OMS** controls **out of repo**.  
- Full **tuple-health** rebuild **G4/G5** except minimal hooks listed in §3.

---

## 17. Lock-maintenance and closure-evidence checklist

Unchecked items below track **evidence** toward INF **implementation closure**; they do **not** contradict this document’s **v1.0.1 LOCKED** status. Pre-lock items (e.g. merge gate) may already be satisfied — retain for audit trail.

- [ ] **`GOVERNANCE_MERGE_GATE.md`** run → **PASS** (all G1–G7).  
- [ ] All **§2** source files still present at merge time.  
- [ ] **Route IDs** R-001–R-035 mapped in §5.  
- [ ] **Claim IDs** mapped in §5.3.  
- [ ] **Operator decisions** in **§§6–14** (**including §10** governance-event decisions) match **`OPERATOR_DECISION_REGISTER.md`** verbatim (diff review).  
- [ ] **No new** operator decisions introduced in prose without amendment.  
- [ ] **Proof paths** created or adjusted with reviewer names filled.  
- [ ] **Negative tests** from §14 in CI.  
- [ ] **Closure** §15 all **checked**.  
- [ ] **Deferred** §16 acknowledged in `OPEN_ITEMS.md` if scope bleeds.

---

## 18. Document control

| Field | Value |
|--------|--------|
| **Document** | `governance/PHASE_PLAN_INFRASTRUCTURE.md` |
| **Version** | **1.0.1 LOCKED** |
| **Status** | **LOCKED** — approved for implementation |
| **Supersedes** | Draft 0.1; aligns register-upstream + G3-R1 closure + fingerprint without `cwd_sha256` |
| **Depends on** | §2 artifact list; **`OPERATOR_DECISION_REGISTER.md`** approved **2026-05-01** (updated **2026-05-02** for **O-16–O-19** / sign-off refresh); **`GOVERNANCE_MERGE_GATE.md`** **PASS** **2026-05-01**; **2026-05-02** merge gate run history (see **`GOVERNANCE_MERGE_GATE.md`**) references bundle commit **72ac0667b9acf81d3ff957e0dcc11b034900a068** |
| **Lock target** | ACHIEVED — v1.0 promoted **2026-05-01**; v1.0.1 administrative amendment **2026-05-02** (§18) |
| **1.0.1 operator approval** | Program operator — **2026-05-02** — attests the **2026-05-02** changelog entry is accurate; amendment is **administrative alignment only** (no INF technical threshold or execution-order change). |

### Changelog

- 2026-05-01 — Promoted Draft 0.2 to 1.0 LOCKED after operator approval and merge-gate PASS.
- 2026-05-02 — **1.0.1** — Administrative alignment: §1 binding-decision bullet; §2 source-artifact rows (mirror / upstream for **§§6–14**, **including §10**; register **O-01–O-19**); §17 checklist operator-decision row; §18 document control. **No** change to INF numeric thresholds, execution order, or closure criteria in §§5–9 / §15.
- 2026-05-02 — **1.0.1** (follow-up) — §18 **Depends on** clarified for merge gate run history; cross-reference to bundle commit **72ac0667b9acf81d3ff957e0dcc11b034900a068**.

---

*End of document — Version 1.0.1 LOCKED.*
