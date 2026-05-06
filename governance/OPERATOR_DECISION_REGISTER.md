# Operator Decision Register

**Status:** **APPROVED** — operator sign-off recorded below.  
**Document date:** 2026-05-02  
**Approval effective:** 2026-05-02  
**Control model:** **Single-Operator Control Model** unless the operator documents a change.

---

## Register authority and global rules

**Authority:** This register is the authoritative record for the binding operator decisions listed below. Any external consensus notes are non-authoritative unless their decisions are explicitly approved and recorded here.

| Rule | Statement |
|------|-----------|
| **R-08** | Any value **not** in this register is **non-authoritative** for committed or authoritative artifacts. |
| **R-09** | Any value proposed by **any** system is **invalid** until **explicitly approved and recorded** in this register. |

**Register upstream:** `PHASE_PLAN_INFRASTRUCTURE.md` mirrors this register for all binding INF operator decisions, including §§6–14 and governance-event decisions in §10. No plan text may assert binding numerics or policies **before** they appear here.

---

## Binding operator decisions (INF governance)

*Provenance: **Owner** = program operator; **Date** = approval date; **Source** as listed.*

| ID | Topic | Decision (binding) | Owner | Date | Source |
|----|--------|-------------------|-------|------|--------|
| **O-01** | Replay N | **7** | Program operator | 2026-05-01 | Consensus + phase plan |
| **O-02** | Float tolerance | **`max_abs_diff` = `1e-5`** per probability in **[0, 1]** | Program operator | 2026-05-01 | Phase plan §8 |
| **O-03** | Skew thresholds (seconds) | **primary vs quote:** warning **> 0.25**, breach **> 1.5**; **primary vs DB write:** warning **> 0.5**, breach **> 3.0** | Program operator | 2026-05-01 | Phase plan §7 |
| **O-04** | Hysteresis | Warning after **2** consecutive warning-band samples; breach after **2** consecutive breach-band; clear warning after **5** consecutive samples below **80%** of warning threshold; clear breach after **3** consecutive below breach threshold **or** operator `CLOCK_SKEW_BREACH` resolution after **10-minute** automated cooldown | Program operator | 2026-05-01 | Phase plan §7 |
| **O-05** | INF-3 fingerprint fields | **`python_version`**, **`platform`** (`sys.platform`), **`implementation`**, **`deps_sha256`** (SHA-256 of UTF-8 sorted line-by-line `pip freeze` stdout), **`repo_git_commit`** (40-char `git rev-parse HEAD` or **`unknown`**), **`cuda_visible_devices`** (exact env or `""`), **`torch_cuda_version`** (`torch.version.cuda` or `null`). **`cwd_sha256` excluded** — operational noise; not in schema. Canonical JSON keys sorted → UTF-8 → SHA-256 → **`env_fingerprint_sha256`**. No equivalence classes. | Program operator | 2026-05-01 | Consensus P-02 / N-02 |
| **O-06** | Serving path (INF-3) | Single OS process: **`uvicorn server:app`**, `cwd` = repo root, **`ED_SERVING_PROCESS=1`** in production; fingerprint at process start only; exclusions per phase plan §6 | Program operator | 2026-05-01 | Phase plan §6 |
| **O-07** | Halt storage | SQLite **`DB_PATH`**, table **`infra_halt`** with columns per phase plan §9 | Program operator | 2026-05-01 | Phase plan §9 |
| **O-08** | Halt release | **Dual identifier:** `release_operator_id` **case-insensitively ≠** `halt_actor`; both non-empty; payload includes `halt_event_id`, `halt_actor`, `release_operator_id`, `timestamp_utc`, **`reason` ≥ 10 characters**; **`HALT_RELEASE`** event; row **`active = 0`**. **Documented limitation:** under Single-Operator Control Model this is **not** cryptographic dual control—two distinct strings only. **No time delay** on release under current control model; **may revisit** if control model changes (e.g. two-person ops). | Program operator | 2026-05-01 | Consensus P-01 / N-03 |
| **O-09** | G3-R1 and INF-1 closure | **External gate** per `OPEN_ITEMS.md`. **No waiver** path for INF-1 closure; G3-R1 must be **resolved** before INF-1 is CLOSED. | Program operator | 2026-05-01 | Consensus N-01 |
| **O-10** | INF-1 replay scope (horizons) | **Primary (authoritative parity):** **1c, 5c, 15c, 60c** — `prob_up`, `prob_down`, `prob_flat` where present for those horizons. **Secondary (diagnostic only, out of authoritative replay parity):** **3c, 8c, 13c** (confirmed present in model rule keys / stack). | Program operator | 2026-05-01 | Consensus P-03; 3c/8c/13c verified in `models/active/*/xgb_*_meta.json` patterns |
| **O-11** | MC on trade path | **Advisory-only**; `mc_advisory` object or null; must not mutate authoritative replay fields | Program operator | 2026-05-01 | Prior register + phase plan §8 |
| **O-12** | Separate production claim binding doc | **Not required** — `PRODUCTION_CLAIMS_REGISTER.md` + phase plan §5.3 / §12 suffice | Program operator | 2026-05-01 | Consensus N-05 |
| **O-13** | Synthetic / debug defaults | Synthetic bundle and debug policy per phase plan §5.2, §10, §12 until amended | Program operator | 2026-05-01 | Phase plan |
| **O-14** | `PHASE_PLAN_TARGET_STATE.md` | **Excluded** from minimal governance commit bundle; **tracked** for separate review (strategic P0–P7; not execution order). Do not leave untracked without disposition. | Program operator | 2026-05-01 | Consensus P-04 |
| **O-15** | `INFRASTRUCTURE_GOVERNANCE_LOCK_PACKAGE.md` | **Deferred** — reviewer index at lock time; **not** normative vs V3 or phase plan. Include in **optional** lock-review bundle when operator promotes plan to LOCKED; not required for first merge-gate PASS if G4 lists files explicitly. | Program operator | 2026-05-01 | Consensus N-04 |
| **O-16** | Governance event storage | Governance events are stored in SQLite table **`governance_events`** at **`DB_PATH`**. This intentionally uses the same SQLite database authority as the application data under the current Single-Operator Control Model. This accepts the coupling between application storage and governance-event storage for the current implementation. Separation into a dedicated audit store is deferred and requires a future register decision before any multi-operator or external-audit deployment. Application behavior is **INSERT-only** for **`governance_events`**; no **UPDATE** or **DELETE** from application code. **INSERT** authority is limited to the serving process (`uvicorn server:app` with **`ED_SERVING_PROCESS=1`**) unless a future register decision explicitly authorizes a tool/script writer. Any deviation from this storage or writer model requires a prior update to this register. | Program operator | 2026-05-01 | Phase plan §10; `GOVERNANCE_EVENT_MODEL.md`; Single-Operator Control Model |
| **O-17** | Required governance event types | Authoritative, required for implementation: **`REPLAY_FAILURE`**, **`CLOCK_SKEW_BREACH`**, **`INFRA_DRIFT`**, **`HALT_ACTIVATION`**, **`HALT_RELEASE`**, **`VALIDATION_FAILURE`**, **`SYNTHETIC_BUNDLE_SERVED`**. No additional event types are binding unless added via a future register decision. | Program operator | 2026-05-01 | `PHASE_PLAN_INFRASTRUCTURE.md` §10; `GOVERNANCE_EVENT_MODEL.md`; register **O-13** (synthetic / debug defaults) |
| **O-18** | Optional governance event extensions | Event types listed as extensions in `GOVERNANCE_EVENT_MODEL.md`, including but not limited to **`REGRESSION_CONFORMS`**, **`CLAIM_BOUNDARY_CHANGE`**, **`CLAIM_WITHDRAWN`**, and **`GOVERNANCE_OVERRIDE_APPLIED`**, are **non-authoritative** and **optional**. They must not be treated as required, binding, or production-authoritative unless explicitly promoted by a future register entry. | Program operator | 2026-05-01 | `GOVERNANCE_EVENT_MODEL.md`; R-08 / R-09 authority rules |
| **O-19** | Governance event retention | Governance event retention duration, archival behavior, and deletion policy are **deferred** and **non-authoritative** at this stage. A future register entry must define retention duration and archival/deletion policy before the first implementation PR that adds **INSERT** calls to **`governance_events`** for production serving. | Program operator | 2026-05-01 | Gap identified during INF governance alignment |
| **O-20** | `a2_quote_staleness_threshold_ms` | **2000** — Maximum quote age (`decision_time_ms - quoteTimeInLong`) before A2 must emit `WAIT` for stale quote. Applies to Pilot 1B Module A/A2 SPY/QQQ 0DTE. Policy object identity: `a2_quote_staleness_threshold_ms_v1`; effective from 2026-05-05 until amended; rollback pointer: no prior bound value; replay impact: future changes may require replay segmentation once A2 staleness gates affect replay labels. Revisit if WAIT-rate-from-staleness exceeds 5% in normal conditions or execution quality degrades during volatile windows. | Program operator | 2026-05-05 | `governance/PILOT_1B_A2_0DTE_CONTRACT.md` L165; v2.0 §15 policy object framework; registered in existing row format pending future policy-object schema migration |
| **O-21** | `a2_spread_hard_threshold` | **$0.10 absolute OR 10% of mid, whichever is tighter** — A2 must emit `WAIT` when bid/ask spread on selected contract exceeds threshold. Applies to Pilot 1B Module A/A2 SPY/QQQ 0DTE. Policy object identity: `a2_spread_hard_threshold_v1`; effective from 2026-05-05 until amended; rollback pointer: no prior bound value; replay impact: future changes may require replay segmentation once A2 spread gates affect replay labels. Excludes deep-OTM strikes by design. Revisit if soft-gate spread reports cluster around threshold or trade quality degrades. | Program operator | 2026-05-05 | `governance/PILOT_1B_A2_0DTE_CONTRACT.md` L166; v2.0 §15 policy object framework; registered in existing row format pending future policy-object schema migration |
| **O-22** | `a1_calibration_health_max_ece` | **warning > 0.05; degraded > 0.08** — Holdout expected calibration error thresholds for A1 calibration health. Applies to Pilot 1B Module A/A1 SPY/QQQ advisory calibration. Policy object identity: `a1_calibration_health_max_ece_v1`; effective from 2026-05-05 until amended; rollback pointer: no prior bound value. Revisit if holdout reliability curves show persistent over-gating or under-gating around threshold. | Program operator | 2026-05-05 | `governance/PILOT_1B_CALIBRATION_CONTRACT.md` §Calibration Health Gates; v2.0 §15 policy object framework |
| **O-23** | `a1_conformal_min_empirical_coverage` | **nominal 0.90; degraded < 0.85** — Holdout empirical coverage thresholds for A1 conformal probability bands. Applies to Pilot 1B Module A/A1 SPY/QQQ advisory calibration. Policy object identity: `a1_conformal_min_empirical_coverage_v1`; effective from 2026-05-05 until amended; rollback pointer: no prior bound value. Revisit if conformal bands are consistently too wide to be useful or miss nominal coverage in stable regimes. | Program operator | 2026-05-05 | `governance/PILOT_1B_CALIBRATION_CONTRACT.md` §Calibration Health Gates; v2.0 §15 policy object framework |
| **O-24** | `a1_calibration_aggregate_holdout_min_samples` | **500** — Minimum aggregate holdout sample count before A1 calibration metrics may be treated as sufficient for Pilot 1B advisory calibration. Policy object identity: `a1_calibration_aggregate_holdout_min_samples_v1`; effective from 2026-05-05 until amended; rollback pointer: no prior bound value. Revisit if walk-forward windows routinely fail due to sample scarcity or isotonic reliability remains unstable above this floor. | Program operator | 2026-05-05 | `governance/PILOT_1B_CALIBRATION_CONTRACT.md` §Per-Regime Stratification and §Calibration Health Gates sample-floor table; v2.0 §15 policy object framework |
| **O-25** | `a1_calibration_per_regime_min_samples` | **50** — Minimum per-regime-cell sample count before stratified A1 calibration metrics may emit reliability rates, ECE, or Brier conclusions. Applies to deterministic rule-based calibration regime buckets. Policy object identity: `a1_calibration_per_regime_min_samples_v1`; effective from 2026-05-05 until amended; rollback pointer: no prior bound value. Revisit if regime cells are too sparse for stable monitoring or too coarse to catch degradation. | Program operator | 2026-05-05 | `governance/PILOT_1B_CALIBRATION_CONTRACT.md` §Per-Regime Stratification and §Calibration Health Gates sample-floor table; v2.0 §15 policy object framework |
| **O-26** | `a1_calibration_per_reliability_bin_min_samples` | **30** — Minimum per-reliability-bin sample count before A1 reliability table bins may emit observed hit-rate conclusions. Policy object identity: `a1_calibration_per_reliability_bin_min_samples_v1`; effective from 2026-05-05 until amended; rollback pointer: no prior bound value. Revisit if reliability bins remain noisy above this floor or too many bins are withheld in normal backfill windows. | Program operator | 2026-05-05 | `governance/PILOT_1B_CALIBRATION_CONTRACT.md` §Per-Regime Stratification and §Calibration Health Gates sample-floor table; v2.0 §15 policy object framework |
| **O-27** | `a1_calibration_max_consecutive_failed_refits` | **3** — Maximum consecutive scheduled A1 calibration refit failures before `calibration_health` must become `degraded` regardless of last successful run ECE. Applies to Pilot 1B Module A/A1 SPY/QQQ advisory calibration. Policy object identity: `a1_calibration_max_consecutive_failed_refits_v1`; effective from 2026-05-05 until amended; rollback pointer: no prior bound value. Revisit if weekly refit cadence changes or failed-refit clusters are mostly caused by known data outages. | Program operator | 2026-05-05 | `governance/PILOT_1B_CALIBRATION_CONTRACT.md` §Calibration Health Gates failed-refit behavior; v2.0 §15 policy object framework |

---

## Legacy audit rows (pre-consensus wording)

The following were **UNKNOWN** in the pre-2026-05-01 audit. Where **O-** IDs above cover them, those **O-** rows are authoritative.

| Decision (historical label) | Superseded by |
|----------------------------|----------------|
| Primary clock authority | O-03 / O-04 context + phase plan §7 |
| Skew thresholds | **O-03** |
| Replay N | **O-01** |
| Determinism metric | **O-02** + phase plan §8 discrete scope |
| Serving path enumeration | **O-06** |
| Environment fingerprint fields | **O-05** |
| Halt store | **O-07** |
| Halt release control | **O-08** |
| MC on trade path | **O-11** |
| Synthetic / debug / log audit | **O-13**; log vocabulary still **pending** dedicated pass unless closed elsewhere |

---

## Operator sign-off

By signing below, the operator attests that the **Decision** column for **O-01 through O-19** is accurate or has been corrected in-line, that **R-08** and **R-09** are accepted, and that **`GOVERNANCE_MERGE_GATE.md`** may be run for the next governance commit.

**Printed name:** Program operator  

**Signature:** *(electronic approval — Cursor session / directive)*  

**Date:** 2026-05-02  

---

*End of register.*
