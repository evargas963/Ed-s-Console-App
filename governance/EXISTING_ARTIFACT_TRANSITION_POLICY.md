> **Classification:** Policy Specification | **Scope:** Governance policy/contract `EXISTING_ARTIFACT_TRANSITION_POLICY.md`.

# Existing Artifact Transition Policy (Draft)

**Status:** DRAFT  
**Date:** 2026-05-01  

---

## 1. Current artifacts (summary)

| Artifact | What it proves today | INF-1 | INF-2 | INF-3 | INF-4 |
|-----------|---------------------|-------|-------|-------|-------|
| `models/active/{ticker}/` bundles | Training-side manifests / weights; runtime loading | No replay certificate | No clock health | No serving env fingerprint in bundle | No halt |
| `scheduler_run_manifest.json` (candidates) | Data + code fingerprints, artifact SHA (see `training_cache.py`) | Partial (train identity) | No | Partial (not serving env) | No |
| `models/arch_state.json` / training reports | Governance competition state | Partial | No | No | No |
| DB snapshots (`insert_snapshot` path) | Persisted Tier C outputs | No per-row replay | No skew proof | No env | No halt |
| Tier C `_state_cache` entries | Ephemeral API payloads | Same | Same | Same | Same |

---

## 2. Gaps (explicit)

- **INF-1:** No versioned replay harness artifact bound to each production release.  
- **INF-2:** No continuous clock-skew evidence attached to serving.  
- **INF-3:** No blessed **serving** environment fingerprint compared at startup.  
- **INF-4:** No independent halt store or enforced tri-level halt.

---

## 3. Policy recommendation

**Forward-only enforcement (default):**

1. New releases after INF closure must satisfy INF proof gates.  
2. **Pre-governance** artifacts remain usable **only** with **downgraded claims** (see `PRODUCTION_CLAIMS_REGISTER.md`).  
3. **Retroactive normalization** (replay all historical snapshots) is **out of scope** unless separately funded and specified.

**Marking:** Add `governance_era: pre_inf` vs `post_inf` in manifest or release notes when implementation exists.

---

## 4. Operator decisions

- Whether any **historical** marketing or UI strings must trigger **forced** replay backfill.  
- Retention years for JSONL/SQLite governance store.

---

**RESULT:** **PASS** (policy draft complete; implementation pending INF).
