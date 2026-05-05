# Framework: ED Institutional Decision Engine

**Document ID:** `governance/Framework-ED-Decision-Engine-v1.1.md`  
**Version:** 1.1  
**Status:** Canonical pilot and research-path governance for the replacement-core decision stack (non-production until separately promoted).

---

## Changelog

All notable changes to this framework document are listed here. This project follows principles aligned with [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

### [1.1 administrative correction] — 2026-05-04

#### Changed

- Corrected the contract-system wording and Appendix A authority references to point at the actual V3 invariant and glossary structure rather than stale B–H / guardrail / definition counts.
- This is a documentation authority-chain correction only. It does not change framework version `1.1`, prereg binding, label semantics, ATR policy, cost model family, instrument tier, or pilot runtime contract.

### [1.1] — 2026-05-01

#### Added

- **Step 0** (immediately after Purpose): locked items vs moving parts, change paths, and explicit **contracts primary, code projection** posture with appendix pointer to the contract system.
- **Bidirectional coupling** with frozen pre-registration: footer binds this document to `research/pilot_step3/prereg_v1.json` via `content_hash` and enumerates pilot-scope field IDs.
- **Runtime binding fields** in prereg (`framework_doc_id`, `framework_doc_version`) enforced by the pilot prereg loader (hard-fail on mismatch with this version).
- **ATR T−1 rationale** in Step 1.5 (trade-definition layer); Step 5.5 retains execution enforcement only.
- **Cost model versioning** as a reproducibility contract: `v1`, `v2_underlying`, `v2_options` (not a discretionary tuning surface within a locked run).
- **Instrument tiers and validation sequence**: SPY → QQQ → mega-cap → broader equities, with per-tier acknowledgment of spread, gap, and microstructure assumptions.
- **Meta-labeling** elevated to Step 1: primary layer = candidate trade outcomes; secondary layer = meta filter on candidates (implementation detail remains Step 16).
- **Pre-registration** framed explicitly as the anti–post-hoc rationalization spine for research claims.
- **DSR / multiplicity discipline** as non-negotiable before any “we found a cell” claim.
- **Appendix A**: Contract system reference appendix — normative contracts; code is a checked projection.

#### Changed

- Structural numbering: Step 0 inserted; former introductory material folded into Purpose + Step 0 + Step 1 where appropriate.

---

## Purpose

This framework defines how ED-style institutional research and pilot execution relate **contracts** (written specifications), **frozen pre-registration** (what was promised before seeing results), and **code** (what actually ran). It exists to prevent silent drift between intent, documentation, and artifacts.

---

## Step 0 — Locked items vs moving parts

### Contracts primary, code projection

The **contract system** (V3 invariants, controlled vocabulary, lifecycle semantics, and referenced contract artifacts; see **Appendix A**) is **primary**. Application code, SQL, and validators are **projections** of those contracts. If code and contract disagree, the run is **non-conformant** until reconciled; the contract is not “adjusted” to match convenience in a locked pilot.

### Locked items (require framework version bump)

Changes to locked items need a **new framework version** (e.g. 1.1 → 1.2) and a **changelog rationale** entry. Examples:

- Definition of the **primary label** for candidate trades (e.g. triple-barrier outcome semantics tied to pre-registered barriers).
- **ATR anchor policy** at the trade-definition layer (e.g. T−1 vs signal bar) when that choice affects barrier width identity.
- **Cost model family** identity (which cost schema is authoritative for a given instrument class), not merely numeric constants within an already-named model.
- **Instrument tier** promoted to authoritative production or research **tier-1** without completing the prior tier’s validation gate.

Each locked change must be reflected in this document’s changelog and, where the pilot prereg is in scope, accompanied by a **prereg amendment** only if the change is still “within version” for moving parts (see below); if the change is locked-scope, **bump framework version** first, then align prereg to the new framework version and recompute `content_hash`.

### Moving parts (revisable within the current framework version)

Moving parts may be updated via **pre-registration amendment** (same framework `framework_doc_version`), with an updated **`content_hash`** on `prereg_v1.json` and a short amendment note in the research log or pilot manifest. Examples:

- Numerical constants inside an already-named cost model **ID** (e.g. half-spread bp) that do not change classification rules pledged in prereg.
- Pilot **barrier grid** dimensions (stop/target multiples, vertical horizons) that remain within the pledged labeling family.
- Diagnostic thresholds that are explicitly **non-authoritative** for promotion.

### Change path summary

| Artifact | Locked change | Moving-part change |
|----------|----------------|---------------------|
| This framework | New version + changelog | N/A (moving parts live in prereg) |
| `prereg_v1.json` | Requires new framework version if change touches locked semantics | Amendment + new `content_hash` + loader verification |

---

## Step 1 — Problem framing, universe, and meta-labeling layers

### Primary layer: candidate trade outcomes

The **primary supervised target** is defined at the **candidate trade** level: event generation, direction/side rule, entry convention, barriers, and costs (post-label where pledged). Labels are **trade-outcome** labels, not bar-return proxies unless explicitly pre-registered as a non-authoritative diagnostic.

### Secondary layer: meta-labeling

**Meta-labeling** is a **second stage**: a filter or classifier over **candidates** (e.g. whether a realized primary-label outcome justifies taking the trade under a decision policy). It must not silently redefine the primary label. **OOF-only** training discipline for meta applies when meta is in scope (per prereg / future steps).

### Pre-registration as anti–post-hoc rationalization spine

Frozen **pre-registration** (see `research/pilot_step3/prereg_v1.json`) is the durable spine against **post-hoc rationalization**: what counts as an event, how labels are formed, and what is out of scope are fixed **before** inspecting results. Claims that contradict prereg without an explicit amendment are **void** for institutional purposes.

Implementation details for meta models remain in **Step 16** (not executed in the current pilot scaffold where noted in prereg).

---

## Step 1.5 — Trade path definition and ATR T−1 rationale

### Trade path

The trade path **must** be fully specified before labeling: session calendar, entry rule (e.g. next-bar open), side rule, CUSUM/sigma contract, triple-barrier parameters, same-bar policy, and force-flat rules. **Pilot:** see prereg sections `candidate_generator`, `entry`, `atr`, `session`, `same_bar`, `costs`.

### ATR T−1 — rationale (belongs with trade definition)

**Why T−1:** Barrier widths must not be scaled using volatility that **includes the signal bar’s own range**, which is **conditioned** by the same information set that fired the CUSUM event. Using **ATR at the close of bar T−1** (signal bar index minus one) aligns barrier distance with a **pre-signal** volatility state and reduces **selection-bias** contamination in barrier sizing. This is a **definition** choice documented alongside the trade path, not a post-label tweak.

**Enforcement** of the anchor in code paths is stated under **Step 5.5** (below).

---

## Step 2 — Data integrity and bars

RTH alignment, gaps, missing bars, and staging vs canonical tables are first-class. **No silent repair** where prereg forbids it. Pilot minimum history and integrity flags: prereg `data`.

---

## Step 2.5 — Candidate generation (events)

CUSUM parameters, SMA side rules, sigma contract, and session filters are **pre-registered**. Event counts and drop reasons are logged for audit.

---

## Step 3 — Labeling family

Triple-barrier labeling with declared same-bar conservative vs diagnostic reject policies. Pilot: prereg `barrier_grid`, `same_bar`, `return_units`.

---

## Step 4 — Costs

### Cost model versioning = reproducibility contract

Cost application is versioned by **stable model IDs**, not ad hoc tuning during a locked run:

| ID (conceptual) | Role |
|-----------------|------|
| `v1` | Baseline underlying cash/ETF spread+fee model; parameters frozen per prereg. |
| `v2_underlying` | Reserved naming for a future underlying cost schema revision (requires new ID + prereg/framework alignment). |
| `v2_options` | Reserved for options-specific cost and assignment semantics (not interchangeable with underlying v1). |

Changing **which** model ID applies is a **reproducibility** and **contract** change, not a knob to optimize after seeing the grid. Pilot: `costs.cost_model_id` and `must_not_change_classification`.

---

## Step 5 — Barrier hits and outcomes

WIN / LOSS / TIMEOUT (and FORCE_FLAT where defined) must map consistently to return units pledged in prereg.

---

## Step 5.5 — ATR anchor enforcement (execution)

- **Enforcement:** Barrier width uses the ATR series at **index `signal_bar_index - 1`**, not the signal bar, per prereg `atr` and labeling implementation.  
- **Rationale** for this anchor lives in **Step 1.5** (above); this step does not re-argue the “why.”

---

## Step 6 — Session and calendar constraints

Force-flat time and outcome class are pre-registered (`session`).

---

## Step 7 — Multiplicity, DSR, and “cell” claims

### Non-negotiable discipline

Before any institutional language of **“we found a cell”** (a barrier configuration that appears superior), the analysis must include **multiplicity correction** and **Deflated Sharpe Ratio (DSR)** (or a strictly equivalent pre-registered alternative) appropriate to the **number of trials** and **dependence structure** implied by the grid and overlapping labels.

Absent that discipline, results are **exploratory only** and must not be promoted.

---

## Step 8 — Instrument tiers and validation sequence

### Sequence

1. **SPY** — most liquid US cash-session proxy; tight spreads; minimal gap microstructure surprises for RTH 1m work.  
2. **QQQ** — technology-heavy ETF; still highly liquid; slightly different gap and correlation structure.  
3. **Mega-cap single names** — stock-specific gaps, halts, and borrow/shortability where relevant.  
4. **Broader equities** — tier-specific spread, gap, and microstructure heterogeneity; **no assumption** that SPY-level liquidity transfers.

### Acknowledgment

Each tier carries its own **spread**, **gap**, and **microstructure** assumptions. Moving a method down the sequence **without** re-validating those assumptions is **non-conformant** for production claims.

**Pilot:** prereg locks **`instrument.ticker`** (currently SPY); expansion requires new prereg and tier-appropriate cost and session contracts.

---

## Steps 9–15 — Evaluation, stability, and reporting

(Consolidated for v1.1 brevity; expand in future versions as the main stack gains scope.)

- Walk-forward, purge, embargo, and sample uniqueness: **pledged in framework**; pilot scaffold may mark specific items `NOT_IMPLEMENTED_IN_PILOT_V1` in prereg where honest.  
- Artifact manifests and run IDs remain mandatory for any research output cited internally.

---

## Step 16 — Meta-model implementation (when in scope)

Architecture, features, OOF training, and calibration for the **meta layer** live here. This step **does not** redefine Step 1 primary labels. **Pilot:** meta and full policy are explicitly out of scope per `pilot_scope` in prereg unless a future prereg version states otherwise.

---

## Appendix A — Contract system reference (normative)

| Source | Normative role |
|--------|----------------|
| `governance/INSTITUTIONAL_STANDARD_V3.md` §1.5 | Controlled vocabulary for governance and runtime terms. |
| `governance/INSTITUTIONAL_STANDARD_V3.md` §2 | Institutional invariants **I-01** through **I-20**. |
| `governance/INSTITUTIONAL_STANDARD_V3.md` §§3–16 | Architecture, validation, enforcement, lifecycle, output, observability, operational, and boundary standards. |
| `governance/G1_DIAGNOSIS.md` and addenda | Current model-lifecycle gap evidence and reconciliation queue. |
| `governance/V3_LOCK_RECORD.md` | V3 lock scope, amendment path, and deferred-item record. |
| `governance/G2_PLAN.md` | Alignment work in progress for artifact contracts, unless superseded by a later governed plan. |

The former B–H layer shorthand is non-authoritative in this v1.1 document. If a layered taxonomy is needed, it must be defined in a future governed standard/framework version rather than inferred from this appendix.

**Repository pointers:** `governance/INSTITUTIONAL_STANDARD_V3.md`, `governance/G1_DIAGNOSIS.md`, `governance/V3_LOCK_RECORD.md`, `governance/G2_PLAN.md` (alignment work in progress).

---

## Framework ↔ pre-registration coupling (footer)

**Frozen prereg file:** `research/pilot_step3/prereg_v1.json`  
**Prereg integrity hash (`content_hash`, SHA-256 of canonical JSON body excluding the `content_hash` key):**  
`fd2b1ab608e5bc5fabac62fe19c2cae0e792c7788c58133ee03e5c1fbd38b855`  

**Pilot scope field IDs** (keys under `pilot_scope` in prereg):  
`purpose`, `cusum_k_and_sma_fixed`, `output_authority`, `non_promotion`, `legacy_non_authority`

**Binding:** Runtime code that loads prereg **must** hard-fail when `content_hash` or `framework_doc_version` (and `framework_doc_id`) do not match the values committed for this framework release. Neither this document nor the prereg file is authoritative in isolation; **both** must agree.
