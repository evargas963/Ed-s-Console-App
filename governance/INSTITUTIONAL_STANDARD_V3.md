# Institutional Standard V3 — Production ML for Trading Decisions (2026)

This standard defines institutional quality for production ML trading decision systems. It is normative and portable: it does not assume any specific implementation stack. It is designed for systems that train multiple architectures across multiple horizons, use stacking/fusion/Monte Carlo layers, and serve outputs in production under governance.

Institutional quality means claims are enforceable. The system must prove that each production decision is attributable to governed artifacts, bounded by explicit failure policy, and auditable through deterministic replay or declared tolerance bounds.

This document uses a three-layer reading pattern in substantive sections:
- **Principle:** what correct means
- **Invariant:** hard rule that cannot be violated without governed exception
- **Enforcement:** how violations are surfaced in code/runtime/audit

This is **Version V3.1**. It supersedes:
- `governance/INSTITUTIONAL_STANDARD_WISHLIST.md` (V1)
- `governance/INSTITUTIONAL_STANDARD_V2.md` (V2)

Amendments follow this standard's own governance in Section 20.

---

## Changelog

### [V3.1] — 2026-05-04

Administrative refinement under Section 20's V3.X path; no invariant semantics or governance tier meanings changed.

- Added `Regime` as a controlled glossary term to reconcile existing divergence-band language with the V3 lock record.
- Added `Ticker` as the controlled instrument identifier and clarified `symbol` as legacy wording.
- Standardized lifecycle terminology on `PROMOTABLE_CANDIDATE`.
- Corrected §5.5 wording so degradation defaults must be published in the versioned failure-mode catalog or governing phase plan entry.

### [V3.0] — 2026-05-02

Initial locked V3 standard per `governance/V3_LOCK_RECORD.md`.

---

## Table of contents

1. Definition of institutional quality (V3)
1.5 Glossary
2. System invariants
3. Architecture declaration
3.5 Cross-architecture consistency monitoring
4. System validation standard (tuple health)
5. Enforcement mechanisms (catalog)
5.5 Degradation policy matrix
6. Canonical contract layer
7. Model stack symmetry
8. Data and feature discipline
8.1 Data revision and backfill policy
9. Horizon parity and economic labels
10. Stacking, meta, Monte Carlo, and fusion
11. Output correctness and validity
11.1 Output validity checklist
11.2 Time consistency and decision latency
12. Lifecycle governance and active path sanctity
12.1 Lifecycle tier vs operational tier
12.2 Human override logging
13. Observability, audit, and forensic replay
14. Operational discipline
14.6 Kill switch and halt authority
15. Failure mode catalog and validation at boundaries
16. External boundaries, security, and continuity
17. Synthesis notes (V3 updates)
18. Where this standard disagrees with common practice
19. Priorities and tier ordering
20. Standard governance
Document control

---

## 1. Definition of institutional quality (V3)

Institutional quality means the organization can present evidence to risk, control, and governance bodies that:
- every production decision is traceable to authorized data/contracts/artifacts;
- failure behavior is bounded and policy-driven, not improvised;
- changes are attributable, reversible, and governed;
- conformance status is explicit, binary where declared, and auditable.

The standard treats governance and runtime behavior as part of correctness, not process overhead.

---

## 1.5 Glossary

- **Tuple:** `(architecture, horizon, ticker)` decision unit.
- **Ticker:** canonical instrument identifier used by current system contracts. Legacy text may use `symbol`; within V3, `ticker` is the controlled term.
- **Lifecycle tier:** governance state of an artifact (`TRAINED`, `EVALUATABLE`, `PROMOTABLE_CANDIDATE`, `ACTIVE_SERVING`).
- **Operational tier:** traffic exposure state (`RESEARCH`, `SHADOW_OBSERVE`, `SHADOW_ACTION`, `LIVE`).
- **Contract slot:** named boundary role where peer architectures compete under identical boundary contracts.
- **Manifest chain:** linked identifiers from data snapshot through serving artifact pointer and promotion record.
- **Parity report:** evidence artifact proving train/serve feature and transform identity under fixed fixtures.
- **Blessed pointer:** governed authoritative pointer to active-serving artifact(s).
- **Governed override:** time-boxed, auditable exception approved by authorized governance authority.
- **Time-box:** explicit maximum duration after which override auto-expires.
- **Four-eyes:** minimum two distinct authorized reviewers for material production changes.
- **MRM:** model risk management discipline (inventory, tiering, challenge, periodic review).
- **Peer competitor:** architecture in the same contract slot evaluated and monitored against peers.
- **Child attachment:** dependent artifact (e.g., calibrator/meta child list) attached to specific parent hashes.
- **Shared base:** shared lower-level artifact used by multiple horizons/architectures with explicit dependency declaration.
- **Policy object:** declarative, versioned, signed artifact defining risk policy parameters.
- **Blast radius:** maximum intended impact scope of a failure/change.
- **Tuple health:** pass/fail status for tuple against validation matrix for operational tier.
- **Decomposition trace:** decision-level record of component outputs/transforms/composition order/final output.
- **Regime:** pre-declared, versioned market-state classification used for evaluation, calibration, monitoring, thresholding, or model conditioning. A regime definition declares its input features, clock/availability policy, class boundaries or model artifact, training window if learned, and whether it is advisory, gating, or trade-impacting.
- **Expected divergence band:** declared acceptable divergence range per class `(ticker, horizon, regime)`.
- **Freshness SLA:** maximum allowed age of input data at decision point.
- **Decision TTL:** maximum age after emit for decision to remain actionable.
- **Halt authority:** controlled ability to stop inference globally/by architecture/by tuple.
- **Conformance audit:** structured assessment of current system against V3 invariants/sections.
- **Severity-1:** highest incident class requiring immediate isolation/containment and governance event.
- **No silent non-conformance:** unknown or undeclared deviation from invariant enforcement is forbidden.
- **Degradation mode signal:** explicit machine-readable flag that declared degraded policy is active.
- **Environment fingerprint:** pinned runtime dependency signature for serving path.
- **Active path sanctity:** only blessed pointers may influence trade-impacting behavior.

---

## 2. System invariants

These invariants are absolute for institutional claims.

| ID | Invariant |
|---|---|
| **I-01** | **No silent substitution OR silent degradation.** If configured architecture, horizon, fusion path, or required companion layer is unavailable, system may only enter declared degraded mode; it may not silently substitute alternatives, nor continue serving with reduced quality (skipped layers, fallback values, suppressed components) without emitting declared degraded mode signal. |
| **I-02** | **Single promotion authority.** Exactly one governed mechanism may move artifacts to authoritative active-serving pointers. |
| **I-03** | **Causal information ordering.** Features/labels may not include information unavailable at decision clock. |
| **I-04** | **Single clock policy.** Joins/splits/labels follow documented clock hierarchy. |
| **I-05** | **Train-serve feature identity.** Promoted bundles must use identical feature contract versions in train and serve. |
| **I-06** | **Artifact hash immutability.** Weights/config/manifests are content-addressed and periodically integrity-checked. |
| **I-07** | **No orphan paths.** Reachable artifacts must satisfy canonical contract or be quarantined non-loadable. |
| **I-08** | **Output schema validity.** Inference outputs must satisfy versioned schema; semantic changes require version bump. |
| **I-09** | **Secrets exclusion.** No secrets in bundles/manifests/images/logs. |
| **I-10** | **Reproducible training identity.** Training captures immutable data snapshot and exact code/materialization identity. |
| **I-11** | **Evaluation integrity.** Comparator evaluations require identical windows/examples/labels. |
| **I-12** | **Pre-declared OOS discipline.** Holdout/embargo policy fixed before metric consumption for promotion cycle. |
| **I-13** | **Risk limits supersede model output.** MC/fusion/meta cannot override hard risk limits except via explicit governed policy object. A policy object is a declarative configuration artifact, versioned, signed by an authorized policy owner, that specifies risk parameters. Tunable runtime parameters, weight values, threshold sliders, or dashboard inputs do not constitute policy objects. Policy object changes follow change discipline equivalent to model promotion. |
| **I-14** | **Attributable change.** Material changes emit auditable event with actor, rationale, and rollback pointer. |
| **I-15** | **Tuple health before trade impact.** No tuple may influence capital unless required validation checks pass for its operational tier. |
| **I-16** | **Decision-level explainability.** Every production decision has decomposition trace: component outputs, transforms, composition order, final output. Where additive attribution is mathematically valid, reconstruction within tolerance is enforceable; where not valid, trace must still record outputs and composition logic without false additive claim. |
| **I-17** | **Deterministic inference.** Identical inputs + identical artifact hashes produce identical outputs, except declared bounded nondeterminism with published tolerance per architecture/layer. |
| **I-18** | **Capacity bounded.** Concurrent behavior is bounded; no unbounded queues/starvation. Backpressure/rate limits and fairness policy are explicit; low-priority paths may not be starved in ways that bias trade path behavior. |
| **I-19** | **Clock synchronization health.** Producer-consumer clock skew is bounded and continuously monitored beyond policy definition in I-04. |
| **I-20** | **Dependency pinning in serving path.** Serving runtime dependency set is pinned and recorded in manifest; drift is governance event, not silent change. |

**Cross-cutting enforcement.** Invariants map to policy-as-code, load-time gates, runtime assertions/monitors, and auditable events. Violations of **I-01, I-02, I-05, I-07, I-15, I-17, I-19, or I-20** in production are **Severity-1**.

---

## 3. Architecture declaration

### Principle
Architectures are declared as governed entities with explicit relationships and boundary contracts.

### Invariant
Every trade-impacting architecture exists in architecture registry with role, peer group, parent/child links, contract IDs, and SLO class.

### Enforcement
Unknown architecture IDs or contract mismatches are rejected at build/load.

### 3.1 Layer relationships
- Base learners are peer competitors in contract slots.
- Calibrators/meta layers are child attachments to explicit parent hashes.
- Fusion is policy layer over typed inputs.
- Monte Carlo is explicit layer with assumption manifest and seed policy.

### 3.2 Shared/not shared
- Shared: boundary contracts, governance evidence format, clock/label policies.
- Not shared: weights, optimizer state, architecture-specific internals unless declared shared-base dependency.

### 3.3 Governance tier by layer
- Meta/fusion/MC carry equal or stricter governance versus base due to concentration risk.

### 3.5 Cross-architecture consistency monitoring

#### Principle
Peer competitors running concurrently remain operationally observable for divergence, not only evaluated offline.

#### Invariant
For each tuple class where two or more peer architectures are deployed, outputs are logged side-by-side. Divergence metrics (KL divergence, directional disagreement rate, prediction range delta) are computed/stored. Expected divergence bands are declared per `(ticker, horizon, regime)` class. Breaches create auditable events.

#### Enforcement
E5 runtime monitor, divergence dashboard, threshold policy per class. Breach response is tier-configurable (alert-only or block-action).

---

## 4. System validation standard (tuple health)

### Principle
Tuple health is explicit and tier-specific.

### Invariant
`LIVE` requires all mandatory `LIVE` checks pass. Partial pass is non-healthy.

### Enforcement
Tuple health service provides pass/fail to inference middleware and action gates.

### 4.1 Validation matrix

| Check ID | Description | RESEARCH | SHADOW_OBSERVE | SHADOW_ACTION | LIVE |
|---|---|---|---|---|---|
| V-ART | Manifest complete/hash verified | Advisory | Required | Required | Required |
| V-PROM | Promotion record exists | N/A | Optional | Required | Required |
| V-FEAT | Train/serve feature contract match | Best effort | Required | Required | Required |
| V-LBL | Label contract match | Best effort | Required | Required | Required |
| V-DATA-FRESH | Data freshness within SLA | Advisory | Required | Required | Required |
| V-DATA-TTL | Decision TTL not expired | Advisory | Advisory | Required | Required |
| V-SLO | Latency/memory within class | N/A | Required | Required | Required |
| V-SCHEMA | Output schema valid | Required | Required | Required | Required |
| V-CAL | Calibration bounds if probabilities actioned | Optional | Required if used | Required | Required |
| V-DRIFT | Drift within policy threshold | Optional | Alert-only | Required soft gate | Required hard gate or governed override |
| V-FUS | Fusion input compatibility | N/A | Required | Required | Required |
| V-STACK | Meta child hash allowlist satisfied | N/A | Required | Required | Required |
| V-MC | MC assumption + seed policy present if used | N/A | Required if used | Required | Required |
| V-REPLAY | Replay/tolerance check | Optional | Periodic | Required periodic | Required periodic + on-demand |
| V-LEAK | Leakage suite freshness and pass | Best effort | Required | Required | Required |
| V-HALT | Halt status not active for tuple/scope | Advisory | Advisory | Required | Required |

**V-DRIFT override note (M-3).** Default time-box is 24h. Renewal requires risk committee re-review (not automatic) with drift trend analysis evidence. Expired overrides auto-revert to hard gate. Policy registry defines organizational absolute ceiling that cannot be exceeded without highest-tier governance.

**Freshness vs TTL note.** V-DATA-FRESH checks input recency; V-DATA-TTL checks actionability window post emit. They are distinct and independently enforced.

---

## 5. Enforcement mechanisms (catalog)

### Principle
Every invariant must map to explicit enforcement mechanism(s).

### Invariant
No rule exists without enforcement owner, failure mode, and evidence artifact type.

### Enforcement classes
- E1: Schema/contract validation
- E2: Policy-as-code gates
- E3: Load-time assertions
- E4: Request-time assertions
- E5: Runtime monitors
- E6: Append-only audit events
- E7: Human gate controls
- E8: Chaos/game-day validation

### 5.5 Degradation policy matrix

#### Principle
Every named failure mode maps to named response.

#### Invariant
Each failure mode catalog entry declares response (`BLOCK`, `RESTRICT`, `DEGRADE`, `CONTINUE`) plus maximum allowed duration before mandatory escalation. Default responses must be published in the versioned failure-mode catalog or its governing phase plan entry. Runtime override requires governed exception.

#### Enforcement
E5 monitors classify failure mode; E2 policy rules apply matrix response; matrix is versioned with failure mode catalog and audited with incident records.

---

## 6. Canonical contract layer

### Principle
Boundary contracts are first-class governed artifacts.

### Invariant
Data, feature, label, horizon, bundle, fusion, MC assumption, and API schema contracts are versioned and referenced by exact IDs in promotion evidence.

### Enforcement
Unknown or mismatched contract IDs fail CI/load/promotion gates.

---

## 7. Model stack symmetry

### Principle
Train/serve geometry is symmetric at boundary semantics.

### Invariant
Promoted artifacts include parity report evidence.

### Enforcement
Missing or stale parity report blocks promotion/load.

---

## 8. Data and feature discipline

### Principle
Lineage and leakage control are mandatory.

### Invariant
Immutable/raw authority + derived lineage + blocking leakage checks on material changes.

### Enforcement
Policy-as-code on feature/data changes, leakage suite evidence in tuple health.

### 8.1 Data revision and backfill policy

#### Principle
Historical revisions are governance events that can stale prior model claims.

#### Invariant
Revision emits event. Artifacts trained on revised snapshot are auto-marked `POTENTIALLY_STALE`. Continued LIVE serving past declared window requires governed exception with rationale.

#### Enforcement
E2 on data revision workflows, E5 staleness monitor, V-DATA checks include snapshot currency status.

### 8.2 Options key levels (derived dealer structure)

#### Principle
Charted key levels are derived from Schwab chain leaves (`delta`, `gamma`, `openInterest`, `strikePrice`, `multiplier`, `putCall`, `volatility`, `vega`, `daysToExpiration`, `expirationDate`). GEX$, DEX$, pin, HVL, max pain, flip, and inflection have no Schwab primitive; they must use one canonical derivation in `math_exposure_core` / `math_levels` and Schwab Field Precedence (`fb1e84c`).

#### Invariant
- Dollar GEX per 1%: `gamma × openInterest × multiplier × spot² × 0.01` aggregated per strike; net = call − put.
- UI key levels use **full chain** strikes that passed OI and Greek validity gates at bucket build; no silent raw-γ fallback when spot/dollar GEX is unavailable (`kl_institutional_ready=false`).
- Section 8 dealer aggregates and `kl_net_gex` use the same full-chain `aggregate_net_gex` helper.

#### Canonical levels
| Level | Definition |
| --- | --- |
| Gamma pin | `argmax_strike \|net_gex_1pct\|` |
| HVL | `argmax_strike (\|call_gex_1pct\| + \|put_gex_1pct\|)` |
| Max pain | `argmin_settlement Σ_K [ call_oi_mult·max(S−K,0) + put_oi_mult·max(K−S,0) ]` on strike grid |
| Gamma flip | zero-cross per-strike `net_gex_1pct`, else `net_gamma`, else cumulative GEX |
| Gamma inflection | `argmin \|net_gex_1pct\|` (else raw net_gamma) |
| Delta inflection | `argmin \|net_dex_dollars\|` (else raw net_delta) |
| Gamma walls | `argmax \|call_gex_1pct\|`, `argmax \|put_gex_1pct\|` |
| Net GEX | `Σ net_gex_1pct` full chain |
| Charm drift target | `pick_gamma_pin_strike` (not a separate charm-internal pin) |

#### Enforcement
`tests/test_institutional_key_levels.py`, `tests/test_math_levels_hvl_max_pain.py`; payload fields `kl_*`, `kl_institutional_ready`, `kl_metrics_dollarized`.

---

## 9. Horizon parity and economic labels

### Principle
Horizons are economic contracts, not labels.

### Invariant
Each horizon defines alignment/session/overlap/economic meaning and decision-vs-diagnostic tier.

### Enforcement
Undefined horizon contracts block training/promotion.

---

## 10. Stacking, meta, Monte Carlo, and fusion

### Principle
Stack layers are first-class risk-bearing components.

### Invariant
Meta/fusion/MC carry manifests, hash lineage, and governance equal or stricter than bases.

### Enforcement
Child hash allowlists, policy review, replay checks, and incident-linked monitoring.

---

## 11. Output correctness and validity

### Principle
Invalid outputs fail closed or enter declared degraded policy.

### Invariant
Output validity is explicit and testable.

### Enforcement
Schema + runtime assertions + output validity metrics.

### 11.1 Output validity checklist

1. Multiclass probabilities sum to 1.0 within tolerance epsilon.
2. Binary calibrated score in `[0, 1]` (no sum-to-one requirement).
3. No NaN values.
4. No Inf values.
5. No negative probabilities where forbidden.
6. All declared classes present.
7. No constant-vector outputs indicative of failed training/path.
8. Output distribution within declared architecture range.
9. Output schema version matches serving contract.

### 11.2 Time consistency and decision latency

#### Principle
Decision validity is time-bound and explicit.

#### Invariant
Schema includes `data_as_of_timestamp` and `decision_emit_timestamp`. Freshness SLA and decision TTL are distinct; both must pass. Expired decisions are not actionable.

#### Enforcement
Schema validation + consumer middleware delta checks + tuple-health data checks.

---

## 12. Lifecycle governance and active path sanctity

### Principle
Only blessed pointers influence trade-impacting behavior.

### Invariant
Active serving path is exactly the promoted governed path.

### Enforcement
Single promotion authority, pointer integrity checks, and audit events.

### 12.1 Lifecycle tier vs operational tier

Lifecycle tier (`TRAINED`, `EVALUATABLE`, `PROMOTABLE_CANDIDATE`, `ACTIVE_SERVING`) and operational tier (`RESEARCH`, `SHADOW_OBSERVE`, `SHADOW_ACTION`, `LIVE`) are independent axes. Artifacts may be `ACTIVE_SERVING` in lifecycle while operating at `SHADOW_OBSERVE` operationally. Lifecycle promotion does not auto-advance operational tier.

### 12.2 Human override logging

#### Principle
Human interventions are first-class governed events.

#### Invariant
Every human action affecting production state logs actor, timestamp, action, prior state, new state, reason, and ticket/case reference.

#### Enforcement
E6 append-only override events; E7 gates require event emission; override events included in incident response.

---

## 13. Observability, audit, and forensic replay

### Principle
Observability means provability, not dashboard volume.

### Invariant
Each decision has correlation IDs, contract IDs, hashes, tuple health snapshot, and route outcome.

### Enforcement
Append-only logs, distributed tracing, replay checks with tolerance evidence.

---

## 14. Operational discipline

### Principle
Operational controls are part of model correctness.

### Invariant
SLOs, runbooks, drills, secret controls, and change discipline are mandatory.

### Enforcement
Monitors, game days, and governance workflows.

### 14.6 Kill switch and halt authority

#### Principle
System supports immediate external halt without code deploy.

#### Invariant
Halt authority exists at:
- system-wide
- per architecture
- per tuple `(architecture, horizon, ticker)`

Activation emits auditable event. Reactivation requires separate authority from deactivation. Halt status checked at inference middleware and downstream action gate.

#### Enforcement
External control plane, tuple health `V-HALT`, independent action-gate halt check, append-only halt audit events.

---

## 15. Failure mode catalog and validation at boundaries

### Principle
Enumerated failure modes and boundary checks prevent improvisation under stress.

### Invariant
Catalog entries map to monitors, degradation responses, runbooks, and escalation bounds.

### Enforcement
Boundary validation in CI/load/runtime plus scheduled drills.

---

## 16. External boundaries, security, and continuity

### Principle
Vendor/trust boundaries are explicit risk surfaces.

### Invariant
External dependencies have SLA/reconciliation controls, least privilege, and continuity plans.

### Enforcement
Security controls, restore drills, and boundary incident monitoring.

---

## 17. Synthesis notes (V3 updates)

- Shared core from V2 remains intact.
- Unique carries from prior critiques retained.
- V3 adds: decomposition trace constraints without universal additive assumption; drift override default-with-governed-cap; explicit freshness vs TTL split; deterministic inference; capacity fairness; clock sync health; dependency pinning.

---

## 18. Where this standard disagrees with common practice

1. Fast promotion without reversible evidence is rejected.
2. Backtest leaderboard alone is rejected as promotion basis.
3. Governance-later approach is rejected; governance is product definition.
4. Shadow-only confidence without explicit kill/degradation controls is rejected.
5. Reproducibility as optional is rejected.

---

## 19. Priorities and tier ordering

### Tier 0 — Foundation (cannot be deferred)
Required before any production capital exposure, defined as any decision the system makes that an external trading system or human acts on. Internal research, paper trading, and shadow-observe are not capital exposure.

### Tier 1 — Capital safety
Causal integrity, promotion authority, tuple health, no silent substitution/degradation, deterministic replay discipline.

### Tier 2 — Statistical and governance quality
Calibration/drift governance, comparator integrity, economic evaluation fidelity, contract rigor.

### Tier 3 — Resilience maturity
Advanced stress behaviors, expanded MRM cadence, extended operational hardening.

---

## 20. Standard governance

The standard versions itself.

- Changes require proposed amendment, supporting evidence, review authority, version bump, migration window, and deprecation policy for backward-incompatible changes.
- **V3.X**: refinements that do not change invariant semantics.
- **V4.0**: changes that alter invariant semantics or governance tier meaning.
- Invariant amendments require highest-tier governance review (risk committee or equivalent authority).
- Standard amendments emit auditable events and are versioned with rigor equivalent to model promotion.

---

## Document control

- **Version:** V3.1
- **Supersedes:** V1 (`governance/INSTITUTIONAL_STANDARD_WISHLIST.md`), V2 (`governance/INSTITUTIONAL_STANDARD_V2.md`)
- **Effective:** on lock per `governance/V3_LOCK_RECORD.md`

