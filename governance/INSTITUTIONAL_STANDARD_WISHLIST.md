# Institutional Standard Wishlist — Production ML for Trading Decisions (2026)

This document states what **institutional quality** means for a production system that trains multiple architectures across horizons, stacks models, serves predictions under governance, and is accountable as real capital infrastructure—not a research codebase. It is **normative**: it describes the destination, not a migration plan. A reader should be able to hold any implementation against these expectations without knowing where this file originated.

**Definition used here:** *Institutional quality* means the organization can honestly tell a risk committee, regulator, allocator, or internal capital committee that (1) decisions are traceable to authorized data and approved models, (2) failure modes are bounded and monitored, (3) change is deliberate and reversible, and (4) no single engineer’s memory is load-bearing.

---

## Table of contents

1. [North star: what “correct” means](#1-north-star-what-correct-means)
2. [Decision integrity and causal discipline](#2-decision-integrity-and-causal-discipline)
3. [Data authority, lineage, and leakage boundaries](#3-data-authority-lineage-and-leakage-boundaries)
4. [Labeling, horizons, and economic meaning](#4-labeling-horizons-and-economic-meaning)
5. [Model zoo discipline: architectures and comparability](#5-model-zoo-discipline-architectures-and-comparability)
6. [Stacking, fusion, and ensemble governance](#6-stacking-fusion-and-ensemble-governance)
7. [Uncertainty, calibration, and tail behavior](#7-uncertainty-calibration-and-tail-behavior)
8. [Monte Carlo and simulation layers](#8-monte-carlo-and-simulation-layers)
9. [Training hygiene and reproducibility](#9-training-hygiene-and-reproducibility)
10. [Evaluation that matches production geometry](#10-evaluation-that-matches-production-geometry)
11. [Serving contracts, latency, and degradation](#11-serving-contracts-latency-and-degradation)
12. [Artifact lifecycle and promotion governance](#12-artifact-lifecycle-and-promotion-governance)
13. [Secrets, access, and blast radius](#13-secrets-access-and-blast-radius)
14. [Observability, audit trails, and forensic replay](#14-observability-audit-trails-and-forensic-replay)
15. [Incident response, rollback, and chaos expectations](#15-incident-response-rollback-and-chaos-expectations)
16. [Human process: roles, four-eyes, and challenge](#16-human-process-roles-four-eyes-and-challenge)
17. [Where this wishlist disagrees with common practice](#17-where-this-wishlist-disagrees-with-common-practice)
18. [Priorities: what matters most](#18-priorities-what-matters-most)

---

## 1. North star: what “correct” means

**Single coherent story per decision.** For every order or risk action attributed to the system, you can answer in one chain: *which data version, which feature contract, which label definition, which model bundle, which fusion policy, which uncertainty treatment, which governance approval, which timestamped artifact hashes* produced this output. If any link is “we think it was around then,” the system is not institutional.

**Production truth is not training truth.** Training metrics are supporting evidence; the standard of correctness is *behavior under production constraints* (latency, missing data, staleness, partial model availability, feed issues). A model that wins offline but cannot be served faithfully under those constraints is not a production winner.

**Governance is part of correctness.** “The best model” that bypassed promotion rules is not the best model—it is a liability. Institutional quality treats *who is allowed to change what touches capital* as seriously as *gradient descent*.

---

## 2. Decision integrity and causal discipline

**No silent substitution.** If a horizon, architecture, or fusion path is unavailable, the system must fail in a **declared** mode (explicit degraded policy), not quietly substitute a different stack. Silent fallback between heterogeneous stacks is unacceptable for institutional use; it destroys auditability and inflates false confidence.

**Causal ordering of information.** Features and labels must respect time: anything not knowable at decision time is forbidden. “Almost causal” is not causal. Institutional standard: **leakage tests are mandatory gates**, not best-effort notebooks—automated, versioned, and repeated on every material change to features, labels, or join logic.

**Single clock authority.** All timestamps that participate in joins, train/test splits, and evaluation windows must trace to a **defined** clock (exchange session, event time, receipt time) with explicit rules when they disagree. Mixing clocks across vendors without documentation is a common failure mode; the standard is one documented policy and enforcement in code.

**Deterministic replay.** Given frozen inputs (data cut, model bundle, config), batch replay of decisions should reproduce outputs within declared numerical tolerances. If replay cannot be bounded, the system is not forensically defensible.

---

## 3. Data authority, lineage, and leakage boundaries

**Authoritative sources with SLAs.** Market data, reference data, corporate actions, and vendor symbology each have a named owner, freshness SLO, and reconciliation expectations. Ad-hoc CSVs as silent upstreams fail the standard.

**Immutable raw landing.** Raw vendor payloads are stored immutably (or append-only with cryptographic integrity). All derived tables declare upstream lineage with schema version. “We cleaned it in pandas once” is not lineage.

**Feature registry as contract.** Every feature has: definition, owner, unit, transformation version, null semantics, staleness rules, and **eligibility** for each model family (tabular vs sequence vs cross-sectional). Breaking changes require version bumps and coordinated retraining policy—not silent column drift.

**Train/serve skew is a first-class defect.** Parity between training feature computation and serving feature computation must be **proven**, not assumed. Contract tests that fail closed when schemas diverge are the institutional baseline—not optional “data tests.”

---

## 4. Labeling, horizons, and economic meaning

**Labels are economic objects, not convenience columns.** Each label must map to a documented trade rule (entry, hold, exit, costs, borrow, capacity). If the label cannot be explained to a non-ML portfolio manager, it should not drive capital.

**Horizons are contracts.** Each horizon slug implies: prediction horizon, alignment to bars, session rules, and how overlapping labels are handled. Mixing horizons without explicit independence claims is a research pattern; production requires explicit statements of what is independent vs intentionally correlated.

**Primary vs diagnostic horizons.** Institutional systems separate **decision horizons** (few, heavily governed) from **diagnostic horizons** (many, never promoted to primary action without separate approval). Letting twelve horizons all influence the same lever without tiering is operational debt.

**Survivorship and universe bias.** Training and evaluation universes must match the tradable universe under realistic liquidity and borrow constraints. Backtests that assume full historical membership for today’s universe are misleading; institutional standard is explicit universe versioning tied to decision time membership rules.

---

## 5. Model zoo discipline: architectures and comparability

**Peer architectures need comparable contracts.** If two architectures compete for the same role, they must produce **comparable artifacts and inference contracts** (inputs, outputs, uncertainty fields, failure signals). “Different but we eyeball it” is not a standard.

**No orphan stacks.** Every trained candidate must be evaluable under the same governance rules: manifest completeness, lineage fields, and evaluation harness compatibility. A stack that trains but cannot be evaluated is incomplete work, not a hidden option.

**Capacity and compute realism.** Model families that cannot meet latency or memory budgets under peak load should be **disqualified** from production candidacy early, not discovered after promotion. Institutional quality includes *feasibility* as a gate, not only AUC.

**Version skew across horizons.** When multiple horizons are live, the system must declare how conflicts are resolved (hierarchy, veto rules, aggregation). Leaving resolution to implicit UI behavior fails the standard.

---

## 6. Stacking, fusion, and ensemble governance

**Meta-learners are models with the same obligations.** They require: training data lineage, anti-leakage discipline, calibration expectations, serving contracts, and promotion rules. Treating meta as “just a sklearn pickle” is sub-institutional.

**Fusion is policy, not trivia.** Bayesian fusion, rule engines, and learned combiners encode **risk preferences**. They must be versioned, reviewed, and tested with the same seriousness as base models. Changing fusion without a governance event is a material risk change.

**Monotonicity and guardrails where appropriate.** Where domain theory demands constraints (e.g., monotonicity in a credit-style signal), the standard is to **enforce** them in model or post-processing—not hope the network learned them.

**Ensemble diversity must be measured, not assumed.** Correlation of errors across models and horizons should be monitored in production. If everything moves together in stress, diversification is illusory.

---

## 7. Uncertainty, calibration, and tail behavior

**Calibration is not optional decoration.** For probability outputs that feed sizing or risk limits, **expected calibration error (ECE)** or equivalent metrics must sit inside declared bounds by segment (regime, volatility bucket, session). Systematic miscalibration is a pre-loss indicator.

**Separate aleatoric and epistemic narratives.** Production systems should expose what is “market randomness” vs “model ignorance” in a way risk can act on—even if the separation is imperfect. Hiding behind a single `confidence` scalar is weak.

**Tail and stress conditioning.** Institutional quality requires explicit behavior under gap moves, halts, thin books, and correlation spikes—**not** only average-day backtests. Stress evaluation belongs in the standard product, not a side project.

**Conformal or distribution-shift hooks where justified.** Industry disagrees on how far to go; this wishlist’s side: if you trade on probabilities, you need **explicit** drift handling policy (recalibration triggers, shadow mode, auto-downgrade), not ad-hoc “we retrain when someone complains.”

---

## 8. Monte Carlo and simulation layers

**MC paths are reproducible and bounded.** Seeds, path count, variance reduction choices, and termination criteria are logged and versioned. “Monte Carlo” without reproducibility is a random number generator attached to capital.

**Economic assumptions are explicit.** Path simulation must declare dividends, borrow, fees, slippage models, and correlation structure sources. Silent defaults are unacceptable.

**MC is not a substitute for risk limits.** If MC output can override hard limits without human policy, that is a design failure. Institutional use positions MC as **information**, limits as **hard law**.

---

## 9. Training hygiene and reproducibility

**Environment lock.** Training containers or images are pinned: OS, drivers, CUDA, Python, library hashes. “Works on my machine” fails institutional bar.

**Data snapshots for training runs.** Each training job references an immutable data fingerprint (content-addressed slice or vendor snapshot IDs). Retraining “on live DB” without snapshot discipline is common and wrong for audit.

**Code fingerprint in manifests.** Training artifacts carry a hash of the **exact** source list used to build the model—not “repo HEAD” ambiguously. If you cannot rebuild the training code identity, you cannot defend the model.

**No silent partial success.** Training pipelines that exit success with missing artifacts train organizational blind spots. Institutional standard: **contract-complete outputs** or **hard failure** with explicit remediation routing—not green dashboards with hollow directories.

---

## 10. Evaluation that matches production geometry

**Walk-forward with embargo discipline.** Standard is purged cross-validation or equivalent for any strategy with serial correlation; naive k-fold on time series is disqualifying for institutional claims.

**Transaction costs and capacity in the objective.** Evaluation that optimizes raw accuracy while ignoring friction is research-grade. Production-grade evaluation includes **economic** metrics under declared cost models.

**Comparator integrity.** When comparing architectures, they must see the **same** examples, time windows, and label definitions—or the comparison is void. “Fair fight” is a governance requirement.

**OOS is sacred and pre-declared.** Out-of-sample windows and holdout policies are fixed before peeking. Moving OOS after results is fraud-adjacent; systems must make tampering detectable (signed manifests, immutable eval logs).

---

## 11. Serving contracts, latency, and degradation

**SLOs per endpoint and per model family.** p50/p99 latency, error rate, and staleness budgets are defined and monitored. Trading systems without SLOs are hobby infrastructure.

**Graceful degradation matrix.** Declared behaviors when: one horizon is stale, one model fails load, fusion inputs disagree, MC times out, or vendor feed is partial. The matrix is documented and tested—not improvised at 9:29am.

**Schema versioning on the wire.** Inference APIs version their output schema; consumers declare compatibility. Silent new fields are better than silent semantic changes—but both need governance.

**Rate limits and abuse resistance.** Even internal services get protection from accidental storms (runaway batch jobs, broken clients). Institutional systems assume human error is guaranteed.

---

## 12. Artifact lifecycle and promotion governance

**Single promotion authority.** There is exactly one sanctioned path from candidate → live. Any alternate writer to production paths (sync jobs, “helpful” scripts, emergency hotfixes) is a **governance defect**, not convenience.

**Artifacts are content-addressed.** Hashes for weights, configs, and manifests are stored and compared on promotion and periodically in production (tamper detection).

**Binary promotion with audit.** Promotion events record: who, why, from-hash, to-hash, evaluation evidence pointers, rollback instructions. “Someone copied files” is not an audit trail.

**Rollback is a first-class product feature.** Demotion must be executable under stress within defined time, with deterministic behavior for in-flight requests.

**Retention and legal hold.** Model artifacts and logs have retention policies aligned with regulatory expectations; deletion is controlled, not accidental `rm`.

---

## 13. Secrets, access, and blast radius

**Least privilege everywhere.** Training workers cannot push to production artifact stores without break-glass roles. Break-glass is logged and reviewed.

**Secrets never in artifacts.** Keys, tokens, and connection strings never appear in model bundles, manifests, or logs. Scanning for secrets is continuous.

**Multi-tenant isolation.** If the platform serves multiple desks or clients, isolation is cryptographic and operational, not conventional wisdom.

---

## 14. Observability, audit trails, and forensic replay

**Per-decision audit record.** Each production decision log links: input snapshot IDs, model bundle IDs, fusion version, uncertainty outputs, and downstream action taken. Logs are append-only and tamper-evident.

**Metric coverage beyond accuracy.** Drift indices, calibration drift, latency, cache hit rates, feed gaps, and label population stability are first-class metrics—not “nice Grafana panels.”

**Tracing across services.** Distributed tracing with correlation IDs from ingest through model call to order router is the institutional baseline for any non-trivial topology.

---

## 15. Incident response, rollback, and chaos expectations

**Runbooks for predictable failures.** Data stall, model load failure, fusion divergence, fat-finger config—each has a runbook with severity, owner, and communication template.

**Game days.** Regular controlled failure injection for serving paths, not only Kubernetes. If you have never failed the model loader in prod-like conditions, you do not know your system.

**Post-incident blameless reviews with teeth.** Findings must translate into tracked remediations, not slide decks.

---

## 16. Human process: roles, four-eyes, and challenge

**Separation of duties.** The person who approves promotion is not the sole author of evaluation code for that cycle. Research, validation, and production ops are separable concerns with handoffs.

**Model Risk Management (MRM) analog.** Even without regulatory mandate, institutional quality adopts MRM patterns: inventory, tiering, materiality, periodic review, and independent challenge function.

**Documentation is executable.** Runbooks and contracts are tested like code; stale docs are treated as defects.

---

## 17. Where this wishlist disagrees with common practice

1. **“Move fast and promote often.”** Institutional quality prefers **slower, reversible promotion** with stronger evidence to **rare** catastrophic errors. Velocity without auditability is negative value at scale.

2. **“Let the best backtest win.”** Backtests optimize narrative. Production quality elevates **stress, capacity, causal discipline, and serving parity** above leaderboard chasing.

3. **“We’ll add governance later.”** Governance and observability are not Phase 2—they are **part of the product definition**. Retrofitting them after capital exposure is expensive and often dishonest.

4. **“Meta-learners are lightweight.”** They concentrate model risk; they deserve **harder** gates, not softer ones.

5. **“Shadow deployment is enough.”** Shadow mode is necessary but insufficient without **explicit** promotion criteria, drift triggers, and rollback drills.

6. **“Research reproducibility is optional.”** For trading capital, reproducibility is **risk control**, not academia cosplay.

---

## 18. Priorities: what matters most

**Tier 1 — non-negotiable**

- Causal integrity and leakage discipline  
- Single promotion authority and immutable audit for live models  
- Serving degradation matrix and SLOs  
- Data lineage and train/serve parity  
- Forensic replayability of decisions  

**Tier 2 — very high**

- Calibration and drift governance  
- Horizon and label economic meaning  
- Comparable contracts across competing architectures  
- OOS discipline and economic evaluation metrics  
- Secrets, access control, and blast radius  

**Tier 3 — high but secondary to Tier 1–2**

- MC reproducibility and assumption transparency  
- Advanced drift methods (conformal, etc.) where probabilities matter  
- Ensemble correlation monitoring  
- Chaos engineering and game days  
- MRM-style process maturity  

**Deprioritized relative to the above (still needed, but not defining “institutional”)**

- Novel architecture count  
- Raw leaderboard complexity  
- Bleeding-edge model types without serving proof  
- Internal tooling polish that does not touch risk surfaces  

---

## Closing stance

Institutional quality in 2026 is not “good ML engineering plus logging.” It is **a risk product** whose outputs are capital decisions: bounded, attributable, reversible, and boring under stress. The wishlist above is intentionally demanding. A system that meets most of Tier 1 and half of Tier 2 with honest gaps documented is already rare; a system that meets all of it with automated enforcement is genuinely institutional. Anything less should be marketed—and risk-managed—accordingly.
