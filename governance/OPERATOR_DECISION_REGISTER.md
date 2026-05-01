# Operator Decision Register

**Status:** **APPROVED** — operator sign-off recorded below.  
**Document date:** 2026-05-01  
**Approval effective:** 2026-05-01  
**Control model:** **Single-Operator Control Model** unless the operator documents a change.

---

## Master consensus and global rules

**Normative cross-system consensus:** *Master Governance Consensus Document* (tightened pass, 2026-05-01) — operator sign-off on that master doc **or** this register satisfies **governance process** acknowledgment.

| Rule | Statement |
|------|-----------|
| **R-08** | Any value **not** in this register is **non-authoritative** for committed or authoritative artifacts. |
| **R-09** | Any value proposed by **any** system is **invalid** until **explicitly approved and recorded** in this register. |

**Register upstream:** `PHASE_PLAN_INFRASTRUCTURE.md` §6–§14 **mirrors** this register. No plan text may assert binding numerics or policies **before** they appear here.

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

By signing below, the operator attests that the **Decision** column for **O-01 through O-15** is accurate or has been corrected in-line, that **R-08** and **R-09** are accepted, and that **`GOVERNANCE_MERGE_GATE.md`** may be run for the next governance commit.

**Printed name:** Program operator  

**Signature:** *(electronic approval — Cursor session / directive)*  

**Date:** 2026-05-01  

---

*End of register.*
