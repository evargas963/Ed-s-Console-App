# Institutional Standard V2 — Production ML for Trading Decisions (2026)

This document is a **synthesized institutional standard**: it consolidates three independent articulations of “institutional quality” for ML-driven trading decisions—(A) a narrative wishlist emphasizing risk and causality, (B) an eighteen-item control-plane framing emphasizing contracts and sanctity of active paths, (C) an eighteen-item checklist emphasizing symmetry, strict output validity, and explicit stack layers—**without** treating any single source as authoritative. Where sources align, the standard is strengthened. Where they diverge, this document **takes a position** and states why.

**Portability:** No reference to any particular codebase, repository layout, or vendor implementation. Any organization may adopt or reject clauses; the obligation here is internal consistency and defensibility in front of a risk committee.

**Reading pattern:** Most substantive sections use three layers—**Principle** (what “correct” means), **Invariant** (a rule that must never be violated without a governed exception), **Enforcement** (how violations surface: compile-time/schema gates, CI policy, runtime assertions, load-time checks, audit events, or human attestation with separation of duties). A consolidated **System Invariants** section lists every hard rule in one place for auditors and engineers.

---

## Table of contents

1. [Definition of institutional quality (V2)](#1-definition-of-institutional-quality-v2)
2. [System invariants](#2-system-invariants)
3. [Architecture declaration](#3-architecture-declaration)
4. [System validation standard (tuple health)](#4-system-validation-standard-tuple-health)
5. [Enforcement mechanisms (catalog)](#5-enforcement-mechanisms-catalog)
6. [Canonical contract layer](#6-canonical-contract-layer)
7. [Model stack symmetry](#7-model-stack-symmetry)
8. [Data and feature discipline](#8-data-and-feature-discipline)
9. [Horizon parity and economic labels](#9-horizon-parity-and-economic-labels)
10. [Stacking, meta, Monte Carlo, and fusion](#10-stacking-meta-monte-carlo-and-fusion)
11. [Output correctness and validity](#11-output-correctness-and-validity)
12. [Lifecycle governance and active path sanctity](#12-lifecycle-governance-and-active-path-sanctity)
13. [Observability, audit, and forensic replay](#13-observability-audit-and-forensic-replay)
14. [Operational discipline](#14-operational-discipline)
15. [Failure mode catalog and validation at boundaries](#15-failure-mode-catalog-and-validation-at-boundaries)
16. [External boundaries, security, and continuity](#16-external-boundaries-security-and-continuity)
17. [Synthesis notes: shared core, unique carries, disagreements](#17-synthesis-notes-shared-core-unique-carries-disagreements)
18. [Where this standard disagrees with common practice](#18-where-this-standard-disagrees-with-common-practice)
19. [Priorities and tier ordering](#19-priorities-and-tier-ordering)

---

## 1. Definition of institutional quality (V2)

**Principle.** *Institutional quality* means the organization can tell a risk committee, regulator, allocator, or internal capital committee—with evidence, not narrative—that every production decision is **traceable** to authorized data and approved model policy, **bounded** in failure behavior, **reversible** in change, and **verifiable** by automated checks plus independent challenge. “Institutional” is not a maturity label for ML; it is a **claims discipline**: every claim the system makes about its own state (healthy, degraded, authoritative) must be **checkable** against declared invariants.

**Invariant.** No production path may emit a trading-relevant score, probability, rank, or action recommendation without a **complete manifest chain** (data fingerprint → feature contract → label contract → model bundle hash → fusion/MC policy version → promotion record) resolvable from logs or batch replay artifacts.

**Enforcement.** Load-time and request-time **manifest completeness checks** block inference for tuples failing the chain; audit pipeline emits `MANIFEST_INCOMPLETE` as a **blocking** finding for any environment labeled production or production-shadow-with-action.

**Synthesis vs sources.** Source (A) emphasized narrative traceability and causal discipline; (B) emphasized **active path sanctity** and **validation at boundaries**; (C) emphasized **symmetry** and **strict output validity**. V2 treats those as **one standard**: traceability without symmetry is theater; symmetry without enforceable invariants is documentation.

---

## 2. System invariants

The following rules are **absolute** for any environment that claims institutional production quality. They apply regardless of section below; if any other text in this document appears to soften them, **this section wins** unless an explicit, time-bounded, risk-approved exception record exists.

| ID | Invariant |
|----|-----------|
| **I-01** | **No silent substitution.** If the configured architecture, horizon, fusion path, or required companion layer (e.g., calibration head) is unavailable, the system enters only a **declared** degraded mode; it never substitutes a different model class, horizon contract, or fusion policy without an auditable configuration change. |
| **I-02** | **Single promotion authority.** Exactly one governed mechanism may attach a model bundle to a live or trade-impacting shadow tier. No parallel writers (ad hoc sync, manual copy, “hotfix” bucket) to authoritative live pointers. |
| **I-03** | **Causal information ordering.** No feature or label may use information not knowable at the decision clock per published policy. |
| **I-04** | **Single clock policy per pipeline.** Every join, split, and label boundary uses timestamps interpreted under one documented clock hierarchy; mixing vendor receipt time and exchange time without explicit dual-field handling is forbidden. |
| **I-05** | **Train–serve feature identity.** Training and serving must consume the **same** feature contract version for a promoted bundle, or promotion is void. |
| **I-06** | **Artifact hash immutability.** Content-addressed hashes for weights, graphs, and manifests are recorded at promotion; production periodically verifies integrity. |
| **I-07** | **No orphan paths.** Any artifact reachable from a scheduler or developer workspace must either satisfy the canonical artifact contract **or** be quarantined (non-loadable) by automated policy. |
| **I-08** | **Output schema validity.** Every inference response validates against a versioned schema; semantic changes require schema version bump and consumer compatibility declaration. |
| **I-09** | **Secrets exclusion.** Secrets never appear in bundles, manifests, container images intended for inference, or structured logs. |
| **I-10** | **Reproducible training identity.** Each training run records immutable data snapshot identity and exact training code/materialization identity sufficient to **reconstruct** the build, not merely name a branch. |
| **I-11** | **Evaluation integrity.** Comparators (architecture A vs B) see identical examples, windows, and label definitions, or the comparison is void and cannot be cited for promotion. |
| **I-12** | **Pre-declared OOS.** Holdout and walk-forward embargo rules are fixed before primary metric consumption for a promotion cycle; post-hoc relabeling of OOS voids the cycle. |
| **I-13** | **Risk limits supersede model output.** Monte Carlo, fusion, and meta layers cannot override hard risk limits without a separate, explicit, human-governed policy object (not a weight tweak). |
| **I-14** | **Attributable change.** Every material change to data, features, labels, models, fusion, or serving defaults produces an auditable event with actor, rationale, and rollback pointer. |
| **I-15** | **Tuple health before trade impact.** No `(architecture, horizon, symbol)` tuple may influence capital unless it passes the **System validation standard** (Section 4) for its tier. |

**Enforcement (cross-cutting).** Invariants map to **policy-as-code** rules (CI), **load-time gates** (inference server), **runtime monitors** (continuous validation), and **periodic attestation** (internal audit / second line). A violation of I-01, I-02, I-05, I-07, or I-15 in production is **Severity-1**: immediate traffic isolation, automatic demotion to safe mode where configured, and mandatory incident record.

---

## 3. Architecture declaration

**Principle.** The system declares **which model architectures exist**, how they relate, what they **share** (contracts, data, evaluation harness), and what they **do not share** (weights, hyperparameters, failure surfaces), and **which governance tier** applies to each. Without this declaration, “multi-architecture” is an unbounded risk surface.

**Invariant.** Every architecture supported for trading-relevant inference appears in the **Architecture registry** with: role, peer group, parent/child edges, input contract ID, output contract ID, promotion tier eligibility, and SLO class (latency/memory).

**Enforcement.** CI rejects training or packaging jobs whose `architecture_id` is absent from the registry or whose contracts are not registered. Inference refuses loads for unknown `architecture_id`.

### 3.1 Supported roles (normative example—adapt names, not relationships)

This standard **assumes** a typical stack of **base learners**, optional **uncertainty heads**, **meta-learners**, **fusion policy**, and optional **Monte Carlo path**. Your naming may differ; relationships may not.

| Layer | Examples (illustrative) | Relationship to peers | Shared with peers | Not shared |
|-------|------------------------|------------------------|-------------------|------------|
| **Base learner** | Gradient-boosted trees, LSTM sequence model, Transformer sequence model | **Peer competitors** for the same *contract slot* (e.g., “primary directional scorer for horizon H”) | Canonical input tensor/tabular contract, label definition, evaluation harness, promotion evidence format | Parameters, optimizer state, architecture-specific code paths |
| **Optional calibrator / conformal wrapper** | Platt, isotonic, distribution-free adjustment | **Child attachment** to a specific base bundle hash | Reads base outputs; does not change feature contract | Calibration artifact hash |
| **Meta-learner** | Stacked linear, shallow GBM on base logits | **Parent–child:** children are **specific promoted base bundles** (by hash), not “whatever LSTM means today” | Anti-leakage rules, same clock policy, same manifest chain | Training data construction logic (must be separately reviewed) |
| **Fusion** | Fixed rules, Bayesian aggregator, learned combiner | **Policy layer** over **typed** inputs; not a peer to bases for the same slot unless explicitly designed as such | Versioned policy document; audit | Tunable parameters require policy version bump |
| **Monte Carlo** | Path generator over returns / features | **Optional parallel evaluator** feeding fusion or diagnostics only per configuration | Seed policy, assumption manifest | Stochastic stream state |

### 3.2 Peer competitor rule

**Position (disagreement with weak industry practice).** Treating tree, RNN-family, and attention-family models as incomparable “art projects” fails institutional bar. For any **contract slot**, peers must be **comparable at the boundary**: same economic label, same decision clock, same missing-data semantics, and same **output contract** (including uncertainty slots if the slot requires them). **Disagreement with a minimalist reading of source (C):** “Unified model architecture standard” must **not** mean homogenizing internals; it means **unifying the interface and evidence**, not forcing one algorithmic family.

### 3.3 Parent–child and shared-base rules

- **Meta** is never a root authority: it consumes **only** outputs from bundles whose hashes appear in its manifest. Replacing a child without updating meta is a **new** fusion graph, not a silent patch.
- **Shared-base** (e.g., shared embedding table across horizons) is permitted only if **versioned** and if **every** dependent horizon declares the dependency; implicit weight sharing across unrelated promotions is forbidden (violates I-02 / I-07).

### 3.4 Governance tier by layer

| Layer | Minimum promotion evidence | Independent challenge |
|-------|---------------------------|------------------------|
| Base | Economic + statistical eval, serving SLO proof, parity tests | Required for first introduction of architecture family |
| Calibrator | Calibration error bounds pre/post | Required if calibrator gates sizing |
| Meta | Same as base **plus** cross-model leakage review | **Stricter** than base (concentrates model risk)—disagrees with industry softness called out in source (A) |
| Fusion | Policy review, stress matrix, rollback | Required for any change affecting limits or sizing |
| MC | Assumption sign-off, seed/replay tests | Required if MC influences live fusion |

---

## 4. System validation standard (tuple health)

**Principle.** Health is not a vibe. For each **`(architecture, horizon, symbol)`** tuple (generalize `symbol` to instrument key as needed), the system defines **exactly** which checks must pass for the tuple to be **healthy** for a given **tier** (e.g., `LIVE`, `SHADOW_ACTION`, `SHADOW_OBSERVE`, `RESEARCH`).

**Invariant.** Tier `LIVE` **implies** all checks in the **LIVE column** pass at last evaluation window; partial pass is **not** healthy.

**Enforcement.** A **Tuple health service** (name immaterial) aggregates binary pass/fail signals; order routers and serving middleware query it. Failing tuples are excluded or drive explicit degraded policy per degradation matrix.

### 4.1 Mandatory checks by category

| Check ID | Description | RESEARCH | SHADOW_OBSERVE | SHADOW_ACTION | LIVE |
|----------|-------------|----------|----------------|---------------|------|
| **V-ART** | Artifact manifest complete, hashes verify | Advisory | Required | Required | Required |
| **V-PROM** | Promotion record exists for bundle pointer | N/A | Optional | Required | Required |
| **V-FEAT** | Feature contract version match train manifest | Best effort | Required | Required | Required |
| **V-LBL** | Label contract ID match manifest | Best effort | Required | Required | Required |
| **V-DATA** | Data freshness ≤ declared horizon SLA | Advisory | Required | Required | Required |
| **V-SLO** | p99 latency and memory within budget class | N/A | Required | Required | Required |
| **V-SCHEMA** | Output passes schema validator | Required | Required | Required | Required |
| **V-CAL** | If probabilities drive action: ECE (or chosen metric) within bounds | Optional | Required if used | Required | Required |
| **V-DRIFT** | Population and covariate drift indices below alert threshold | Optional | Alert-only | Required soft gate | Required hard gate or governed override |
| **V-FUS** | Fusion inputs pairwise schema-compatible | N/A | Required | Required | Required |
| **V-STACK** | If meta: child hashes ⊆ allowed set for this meta version | N/A | Required | Required | Required |
| **V-MC** | If MC on path: seed policy + assumption manifest present | N/A | Required if MC on | Required | Required |
| **V-REPLAY** | Sample replay within numerical tolerance | Optional | Periodic | Required periodic | Required periodic + on-demand |
| **V-LEAK** | Leakage test suite last run ≥ manifest `leak_suite_id` | Best effort | Required | Required | Required |

**Hard gate vs governed override.** For `LIVE`, **V-FEAT**, **V-LBL**, **V-ART**, **V-PROM**, **V-SCHEMA** allow **no** override. **V-DRIFT** may allow a **time-boxed** risk committeed override with automatic expiry; absence of expiry mechanism is non-compliant design.

### 4.2 Symbol-specific extensions

**Principle.** Liquidity, borrow, and session rules are symbol-real.

**Invariant.** If a symbol is **not** in the tradable universe for the tuple’s horizon per **universe version** at decision time, the tuple is **unhealthy for LIVE** regardless of model quality.

**Enforcement.** Universe membership is a **first-class** input to tuple health; backtest-only symbols cannot appear as healthy LIVE without explicit breach of I-15 (should block).

---

## 5. Enforcement mechanisms (catalog)

**Principle.** Philosophy without mechanism is not a standard. Every invariant must map to at least one **enforcement class**.

**Invariant.** Each rule in Sections 6–16 must appear in the **Enforcement registry** with columns: rule ID, enforcement class, owner, blast radius, default on failure (block / alert / isolate), and evidence artifact type.

| Class | Mechanism | Typical surface |
|-------|-----------|-----------------|
| **E1 — Schema & contract** | JSON/Protobuf/Arrow schema validators; feature store contract tests | CI + inference middleware |
| **E2 — Policy-as-code** | OPA/Rego, custom linters, manifest diff gates | CI on PR affecting features/models |
| **E3 — Load-time assertion** | Bundle loader verifies hashes, manifest fields, child references | Inference startup |
| **E4 — Request-time assertion** | Per-request clock skew, staleness, tuple health | Hot path (must be fast—cache health) |
| **E5 — Runtime monitor** | Drift, calibration, latency SLO breach detectors | Streaming + batch |
| **E6 — Audit event** | Append-only event log with tamper evidence | Central logging |
| **E7 — Human gate** | Four-eyes promotion, separation of duties | Workflow tool |
| **E8 — Chaos / game day** | Injected failures per catalog | Non-prod + scheduled prod drills |

**Position (addresses ChatGPT gap 1 vs source A).** Source (A) was strongest on **what** must be true but lighter on **how** violations surface. Source (B)’s “validation at boundaries” maps cleanly to **E3–E5**. This catalog **requires** explicit mapping; “we monitor that” without class fails review.

---

## 6. Canonical contract layer

**Principle.** Contracts—not meetings—are the source of truth for what crosses subsystem boundaries.

**Invariant.** The following **contract IDs** exist and are versioned: **Data snapshot**, **Feature set**, **Label definition**, **Horizon definition**, **Model bundle**, **Fusion policy**, **MC assumption set**, **Serving API schema**. A promotion references **exact** IDs, not ranges.

**Enforcement.** **E1/E2:** PRs touching contract-generating code must bump version or attach waiver with risk sign-off; manifests embed IDs; loaders reject unknown pairs `(contract_type, version)`.

**Unique carry from (B) “Canonical Contract Layer” and (C) “Canonical Artifact Contract”.** Both are included as **non-optional**; reasoning: without contract IDs, **I-14** attributable change is unprovable.

**Disagreement.** Some teams version only “the model.” **V2 position:** versioning **only** weights while eliding feature/label versions is **non-institutional**; it violates I-05 and invalidates promotion evidence.

---

## 7. Model stack symmetry

**Principle.** **Symmetry** means training-time geometry, data access patterns, and serving-time computation paths are **intentionally aligned** so that “works in notebook” cannot diverge from “works at the exchange clock.”

**Invariant.** For every promoted bundle, **training symmetry** and **serving symmetry** artifacts exist: a **parity report** (diff of feature graphs or hashed intermediate samples on fixed fixtures) signed in CI.

**Enforcement.** **E2:** No promotion artifact without parity report job ID. **E3:** Loader checks `parity_report_id` in manifest.

**Consolidation.** This merges (B) *Training Symmetry*, (C) *Architectural Symmetry* / *Model Training Consistency*, and (A) *train/serve skew as defect*. **Disagreement with narrow “architectural symmetry”** interpretations that only align layer shapes in neural nets: **tabular + sequence + transformer** must all honor the **same** clock, label, and missingness contracts even if tensor shapes differ.

**Horizon parity (embedded).** Each horizon’s label and feature alignment rules are identical in train and serve **for that horizon’s contract**; cross-horizon sharing is explicit in Architecture declaration, never implicit.

---

## 8. Data and feature discipline

**Principle.** Data is guilty until proven lineage-clean.

**Invariant.** Raw authoritative payloads are immutable-landed; derived sets declare upstream lineage; leakage tests are **blocking** on material changes (I-03, I-12 neighborhood).

**Enforcement.** **E2** on feature PRs; **E6** logs `LEAK_SUITE_RUN` with input commit and data snapshot; **V-LEAK** in tuple health.

**Unique carry from (A) not always explicit in (B)/(C):** **Primary vs diagnostic horizons** as a governance distinction—included because capital relevance must not be smuggled through “experimental” horizons without tier promotion.

---

## 9. Horizon parity and economic labels

**Principle.** Horizons are **contracts**, not string tags.

**Invariant.** Each horizon slug maps to: bar alignment, session calendar, overlap handling, economic interpretation, and **tier** (decision vs diagnostic).

**Enforcement.** Label service rejects training jobs with undefined slug; tuple health checks **V-LBL**.

**Disagreement.** Source (C) *Horizon Consistency* might be read as “all horizons must match.” **V2 position:** horizons may **differ by design**, but **conflict resolution** among live decision horizons must be **explicit policy**, not UI convention (aligns with A §5).

---

## 10. Stacking, meta, Monte Carlo, and fusion

**Principle.** Stacked layers **concentrate** model and policy risk; they receive **stricter**, not looser, treatment than bases.

**Invariant.** Meta, fusion, and MC each have manifests, hashes, promotion records, and schema-valid outputs. Meta cannot train on **future** base outputs relative to decision clock in ways that break causality; MC cannot run without **assumption manifest + seed policy** (I-13).

**Enforcement.** **E3/E5:** Fusion divergence monitors; MC timeout → declared branch per degradation matrix, never silent trim.

**First-class stacking (B + C + A).** Included. **Disagreement with “meta is lightweight”** (industry + echoed in A): meta promotion requires **additional** independent review vs a new base in the same slot.

**Monte Carlo standardization (C + A).** Seeds, path counts, variance reduction, and economic assumptions are versioned; replay tolerances published.

---

## 11. Output correctness and validity

**Principle.** Invalid outputs must **fail closed** into a declared safe mode for the tier.

**Invariant.** NaNs/Infs where forbidden, missing required uncertainty fields where required, out-of-range probabilities, and schema drift all **invalidate** the response for that tier.

**Enforcement.** **E1** schema validation; **E4** fast path checks; metrics `OUTPUT_INVALID_RATE` SLO.

**Strict output validity (C).** Adopted in full. **Disagreement with lenient practice** of returning “best effort” logits: **LIVE** may not return numerically unbounded “garbage then clamp in strategy”; clamping must be **explicit policy** logged per I-14.

---

## 12. Lifecycle governance and active path sanctity

**Principle.** Only **blessed** pointers participate in trade-impacting behavior.

**Invariant.** **Active path sanctity (B):** the live graph of `(data → features → models → fusion → serving)` is **exactly** the promoted graph; side paths may exist for research but cannot influence LIVE without passing promotion.

**Enforcement.** **E7** promotion workflow; **E6** `PROMOTION_EVENT`; **E3** refuses alternate paths; **I-02** scanning for rogue writers.

**Zero silent fallback (C) + no silent substitution (A).** Merged: **declared** degradation only.

**Governance and promotion control (C + A).** Binary promotion with from/to hashes, evidence pointers, rollback.

---

## 13. Observability, audit, and forensic replay

**Principle.** Observability is not dashboards; it is **provability**.

**Invariant.** Each decision log contains correlation ID, contract IDs, bundle hashes, fusion version, tuple health snapshot ID, and outcome routing.

**Enforcement.** **E6** append-only; distributed **tracing** (A + operational norm); **V-REPLAY** batch jobs reproduce outputs within tolerance.

**End-to-end observability (B).** Adopted as mandatory for non-trivial topologies.

---

## 14. Operational discipline

**Principle.** Operations are part of the model.

**Invariant.** SLOs exist per endpoint and model family; degradation matrix is tested; secrets never in artifacts; DR paths exist for authoritative stores.

**Enforcement.** **E5** SLO monitors; game days **E8**; secret scanning **E2**.

### 14.1 Testing framework (merged B + C + A)

| Layer | Minimum tests |
|-------|----------------|
| Unit | Schema, pure transforms, clock utilities |
| Contract | Train/serve parity fixtures, feature registry compatibility |
| Integration | Loader + inference + fusion dry-run on frozen snapshots |
| Statistical | Walk-forward / purged CV, OOS integrity, comparator fairness |
| Load | Latency/memory under peak; rate limit behavior |
| Chaos | Model load failure, partial feeds, fusion timeout per catalog |

**Test coverage layers (B) + Testing framework (C).** Unified here to avoid duplicate counting.

### 14.2 Reproducibility and versioning

**Principle.** Reproducibility is **risk control**, not academic optionalism (A).

**Invariant.** Training records immutable data snapshot ID + code materialization hash; inference records bundle hash.

**Enforcement.** **E2** blocks “successful” jobs with incomplete artifact set (A: no silent partial success).

### 14.3 Performance and profiling (unique carry from C)

**Reasoning for inclusion though less emphasized in A/B:** Without profiling evidence, latency and memory **SLO claims** are ungrounded; institutions that skip this confuse **functional** correctness with **operational** correctness.

**Invariant.** Every architecture in registry has a **profiled** baseline on reference hardware class before LIVE eligibility.

**Enforcement.** **V-SLO** gate includes pointer to profile job artifact.

### 14.4 Documentation as infrastructure (B)

**Principle.** A runbook untested is fiction.

**Invariant.** Runbooks for Severity-1 incidents are **exercise-tested** on a schedule; stale docs are tracked defects.

**Enforcement.** Game days include documentation drills; audit samples runbook version used during incident.

### 14.5 Change discipline (B)

Merged with I-14 and promotion; additionally: **feature flags** affecting inference defaults require same governance as model promotion if they change economic mapping.

---

## 15. Failure mode catalog and validation at boundaries

**Principle.** Enumerated failure beats heroic improvisation.

**Invariant.** The organization maintains a **Failure mode catalog** covering at minimum: data stall, symbology mismatch, partial corporate action, feature null spike, model load OOM, fusion input mismatch, MC timeout, clock skew, cache poisoning, secret expiry, promotion race, and **silent path drift** (detected via hash drift monitors).

**Enforcement.** Each catalog entry maps to: runbook, monitor, default degradation behavior, and **game day** frequency. This addresses **validation at boundaries (B)** and **operational validation (ChatGPT gap 4)** explicitly: **boundaries** are interfaces where contracts are checked; **operational validation** is the scheduled execution of catalog + tuple health + replay jobs with pass/fail stored as evidence.

**Disagreement.** Source (C) list alone can read as linear checklist; **V2 position:** without a **catalog**, “testing framework” degenerates to unit tests that never stress the true joint failure surface.

---

## 16. External boundaries, security, and continuity

**Principle.** Third parties and infrastructure are part of the threat model.

**Invariant.** Vendor feeds have SLA + reconciliation; blast radius limits on credentials; break-glass for prod writes is logged; backups and restore drills exist for artifact store and logs.

**Enforcement.** **E7/E8**; periodic restore proof; vendor divergence alarms.

**External boundaries (B).** Explicitly: anything outside the trust boundary (market data vendor, cloud control plane, counterparties) must have **declared** trust assumptions and monitoring—not implicit “AWS is safe.”

---

## 17. Synthesis notes: shared core, unique carries, disagreements

### 17.1 Shared core (appeared in two or more of A, B, C summaries—now unified)

| Theme | Sources | V2 home |
|-------|---------|---------|
| Canonical contracts / artifacts | B, C, A | §6, I-06/I-07 |
| Training / architectural symmetry | B, C, A | §7 |
| Horizon parity / consistency | B, C, A | §9 |
| Lifecycle / governance / promotion | B, C, A | §12 |
| Active path / no silent fallback | B, C, A | I-01, §12 |
| Validation at boundaries | B, gap-4 | §4–5, §15 |
| Output validity / correctness | B, C, A | §11 |
| Meta / stacking / fusion / MC first-class | B, C, A | §10 |
| Observability E2E | B, C, A | §13 |
| Reproducibility / versioning / lineage | B, C, A | §6, §14 |
| Testing layers / framework | B, C, A | §14 |
| No orphan paths | C, A | I-07, §6 |

### 17.2 Unique items judged worth carrying (single source)

| Item | Source | Reasoning |
|------|--------|-----------|
| **Failure mode catalog** | B | Without enumeration, joint failures and degradation behavior are unreviewable. |
| **Documentation as infrastructure** | B | Ops maturity is indistinguishable from model maturity at incident time. |
| **Change discipline** as explicit control | B | Separates “code merged” from “economic mapping changed.” |
| **External boundaries** explicit | B | Trading systems die at vendor and trust-boundary edges. |
| **Performance profiling gate** | C | Converts SLO claims into evidence; prevents post-hoc surprise. |
| **Strict schema enforcement / unified output standard** | C | Formalizes what A asked for in prose. |
| **Primary vs diagnostic horizons** | A | Prevents governance bypass via horizon proliferation. |
| **Tail/stress and calibration depth** | A | Institutional committees ask “what happens when correlations go to one?”—must be in standard. |
| **MRM / four-eyes / separation of duties depth** | A | Makes human enforcement real, not decorative. |

**Items not elevated to invariant status (judgment):** “Maximum number of architectures” caps—organization-specific; instead, **registry + tiered review** suffices.

### 17.3 Disagreements between sources (positions taken)

| Topic | Resolution | Reasoning |
|-------|------------|-----------|
| **Checklist vs narrative** | V2 is **spec-shaped** (invariants, tuple health, enforcement registry) while keeping **risk narrative** in §1 and §18 | Committees need narrative; engineers need falsifiable rules—ChatGPT gap 1 against A-style prose alone. |
| **Unified architecture internals** | **Reject** homogenizing model internals; **require** unified **contracts** | Preserves diversity of inductive bias without sacrificing comparability (disagrees with misreading of C). |
| **Meta strictness** | **Stricter than base** | Concentration of model risk (A + principled extension beyond C’s bare “meta requirement”). |
| **Shadow sufficiency** | Shadow **insufficient** without promotion criteria + drills (A) | B’s active path concept reinforces: shadow must not create shadow writers to live pointers. |

---

## 18. Where this standard disagrees with common practice

1. **“We’ll enforce culture.”** Culture is necessary; **institutional** quality requires **mechanized** gates (§5). Culture without mechanism fails silently.

2. **“Best backtest promotes.”** Backtests optimize stories; **tuple health**, **stress**, and **serving evidence** dominate (A, expanded in §4/§11/§15).

3. **“Microservices imply observability.”** Service sprawl without **contract IDs** and **tuple health** is still blind (disagrees with lazy industry equating logs with observability).

4. **“Agile promotion.”** Reversible, evidenced promotion beats frequency (A); **I-02** forbids convenience paths.

5. **“Research reproducibility optional.”** **I-10** rejects this outright.

---

## 19. Priorities and tier ordering

**Tier 0 — structural (must exist before “first dollar”)**  
System invariants I-01–I-15 as enforceable policy; Architecture registry; Enforcement registry; Tuple health for LIVE; Promotion workflow with four-eyes.

**Tier 1 — capital safety**  
Causal integrity, train/serve parity, manifest chain, no silent substitution, replayability, secrets hygiene.

**Tier 2 — statistical and economic honesty**  
OOS discipline, comparator integrity, economic costs in eval, calibration where probabilities matter, drift governance.

**Tier 3 — resilience and maturity**  
Failure catalog + game days, MC standardization, ensemble correlation monitoring, MRM cadence, profiling evidence.

**Deprioritized for defining “institutional”**  
Novelty of architecture count, leaderboard complexity without contract parity, tooling polish that does not touch risk surfaces.

---

## Document control

**Version:** 2.0 (synthesized standard)  
**Supersedes for operational specificity:** narrative wishlists that lack invariants, tuple health, architecture declaration, enforcement registry, and operational validation evidence—**regardless of authorship**.  
**Does not supersede:** law, regulation, or firm policy where stricter.

---

**END**
