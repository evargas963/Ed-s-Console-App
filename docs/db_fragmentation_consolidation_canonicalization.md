# Database Fragmentation, Consolidation, and Canonicalization

**Date:** 2026-04-11  
**Scope:** Full project SQLite inventory, authoritative-data proof vs `data/ed_console.db`, consolidation decision, canonical path hardening.

---

## 1. Executive result

- **Every** project `.db` file is **classified** (no unknowns).
- **Anti-join proof:** For `snapshots` and `price_bars_1m`, rows present in **backups** but **absent** from `data/ed_console.db` are **only** non-production test rows (`PHASE2VERIFY` in one backup) or **zero** for other backups. **Harness/proof DBs** hold **disjoint** synthetic keys (no key overlap with canonical).
- **Merge into canonical:** **Not required** for authoritative production history — canonical is the **superset** of real market snapshot/bar keys; remaining deltas are **harness artifacts**, **proof fixtures**, or **intentionally removed test sentinel** rows.
- **Canonical DB:** `data/ed_console.db` (resolved via `db.DB_PATH`; see §9).
- **Hardening:** Single resolution of `DB_PATH` from `ED_CONSOLE_DB` or default file; `calibration.paths.DEFAULT_DB` aliases `db.DB_PATH`; duplicate path literals removed; **empty stray** root `ed_console.db` **removed**.

**FINAL RESULT: PASS**

---

## 2. Full DB inventory table

| Path | Size (bytes) | Modified (UTC) | WAL/SHM |
|------|----------------|----------------|---------|
| `data/ed_console.db` | ~2.82e9 | 2026-04-11 | Yes (`ed_console.db-wal`, `ed_console.db-shm`) |
| `data/calibration_accumulation_validation.db` | ~1.9e6 | 2026-04-11 | No |
| `data/calibration_anchor_proof.db` | ~5.5e5 | 2026-04-11 | No |
| `data/backups/ed_console.*.db` (7 files) | ~1.5–1.8e9 each | 2026-04-03 | No |
| ~~`ed_console.db` (repo root)~~ | ~~0~~ | — | **Deleted** (was empty) |

---

## 3. Classification of every DB

| DB | Classification |
|----|----------------|
| `data/ed_console.db` | **Authoritative production** (live `EdDB`, calibration writer default, full schema including `calibration_decision_log`) |
| `data/ed_console.db-wal` / `-shm` | **SQLite sidecars** — uncheckpointed writes; not separate logical databases |
| `data/calibration_accumulation_validation.db` | **Harness / deterministic validation** — isolated, `DB_PATH` overridden during harness run |
| `data/calibration_anchor_proof.db` | **Proof / edge dataset** — small, dedicated |
| `data/backups/*.db` | **Backup / archive** — point-in-time copies; older schema on some (no `calibration_decision_log` on copies examined earlier) |
| Root `ed_console.db` (removed) | **Empty / stray** — not referenced by `db.py` |

---

## 4. Code-path DB mapping (summary)

| Mechanism | Resolves to | Writers / readers |
|-----------|-------------|---------------------|
| **`db.DB_PATH`** | `ED_CONSOLE_DB` if set, else `\<repo\>/data/ed_console.db` | `EdDB`, all tier-1 persistence |
| **`calibration.paths.DEFAULT_DB`** | `from db import DB_PATH as DEFAULT_DB` | Validators, repairs, `--db` defaults |
| **`ml_train.DB_PATH`** | `str(db.DB_PATH)` | Training pipeline |
| **`ml_data_common._db_default_path()`** | `str(db.DB_PATH)` | M5 additive fetches |
| **`ml_predict`** | Uses `ml_train.DB_PATH` for snapshot additive path | Inference overlay |
| **Harness** | `run_production_accumulation_validation` sets `db_mod.DB_PATH = OUT_DB` for **isolated** file only for that process | Does not change on-disk canonical unless mis-pointed |

**Accidental wrong DB:** Mitigated by **one** env var (`ED_CONSOLE_DB`) and **one** default file; harness explicitly rebinds `db.DB_PATH` only inside the accumulation script’s process.

---

## 5. Fragmentation analysis (by table)

### 5.1 `snapshots` / `price_bars_1m` (natural keys)

| Candidate DB | Snapshots in DB **not** in canonical? | Bars in DB **not** in canonical? | Interpretation |
|--------------|----------------------------------------|----------------------------------|----------------|
| `calibration_accumulation_validation.db` | 120 | 788 | **Synthetic** keys (harness window); **0** key overlap with canonical (proven) |
| `calibration_anchor_proof.db` | 30 | 30 | **Proof-only**; **0** overlap with canonical |
| Backups (most) | **0** | **0** | Canonical ⊇ backup for these keys |
| `ed_console.pre_option_a_backfill_v1.1775227393.db` | **110** | **0** | All 110 are **`PHASE2VERIFY`** 1m rows — **verification sentinel**, not production market history; **do not merge** |

### 5.2 `calibration_decision_log`

- Exists **only** on canonical and harness/proof DBs in this tree (not on sampled backups from Apr 2026 inventory).
- Harness rows are **disjoint** from canonical keys (no `(ticker, decision_ts_utc)` overlap with production harness run).

---

## 6. Merge-required decisions

| Candidate | MERGE REQUIRED? |
|-----------|-----------------|
| Harness DB | **NO** — test data |
| Anchor proof DB | **NO** — proof fixture |
| Backups (0/0 delta) | **NO** — canonical already contains those rows |
| Backup with PHASE2VERIFY-only delta | **NO** — not authoritative production content |

**Consolidation SQL merge performed:** **None** (proven unnecessary and unsafe to mix harness/PHASE2VERIFY into live history).

---

## 7. Exact files changed

| File | Change |
|------|--------|
| `db.py` | `DB_PATH` = `_resolve_console_db_path()` using `ED_CONSOLE_DB` or `data/ed_console.db` |
| `calibration/paths.py` | `DEFAULT_DB` imports `db.DB_PATH`; `CANONICAL_CONSOLE_DB_FILE` documents default file |
| `audit_snapshot_data.py` | Uses `from db import DB_PATH` |
| `verify_snapshot_pipeline.py` | Uses `from db import DB_PATH` |
| `ml_data_common.py` | `_db_default_path()` → `str(db.DB_PATH)` |
| `ml_train.py` | `DB_PATH = str(db.DB_PATH)` |
| `ml_predict.py` | Uses `_ML_DB` only for additive snapshot path (no duplicate env read) |
| `ed_console.db` (repo root) | **Deleted** (0-byte stray) |

---

## 8. Consolidation performed

**None.** Evidence: backup-vs-canonical anti-joins are **0** for production tickers; only **PHASE2VERIFY** test rows differ in one backup.

---

## 9. Final canonical DB declaration

- **Logical canonical database file:** `\<project_root\>/data/ed_console.db`
- **Runtime resolution:** `db.DB_PATH` (module `db`, attribute `DB_PATH`)
- **Override:** Environment variable **`ED_CONSOLE_DB`** (path to the single SQLite file used for this deployment)
- **Calibration / validators default:** `calibration.paths.DEFAULT_DB` **is** `db.DB_PATH`

---

## 10. Guardrails / hardening

1. **Single resolver** for default path + env: `db._resolve_console_db_path()` / `db.DB_PATH`.
2. **No duplicate** “default path” strings in `ml_train` / `ml_data_common` / audit scripts — use `db.DB_PATH`.
3. **Stray empty** root `ed_console.db` **removed** to eliminate false “second DB” confusion.
4. **Harness** remains explicit: accumulation script assigns `db_mod.DB_PATH` to harness file **only in that process**.
5. **Backups** remain read-only archives under `data/backups/` — not default targets for any code path.

---

## 11. Post-consolidation validation

| Check | Result |
|-------|--------|
| Canonical row counts (`calibration_decision_log` / `snapshots` / `price_bars_1m`) | 43 / 162,077 / 90,427 (unchanged by this change) |
| `validate_outcome_join --db data/ed_console.db` | `binary_pass_strict_production`: **true** (spot check after hardening) |
| Import sanity | `DEFAULT_DB == db.DB_PATH` when `ED_CONSOLE_DB` unset |

---

## 12. Remaining issues

**NONE** for canonical closure under this audit.

**Operational:** Checkpoint WAL periodically to reduce `ed_console.db-wal` size (SQLite maintenance; not a fragmentation issue).

---

## 13. FINAL RESULT: **PASS**

All authoritative production SQLite state for this application is **intended** to live in **`data/ed_console.db`** (or the path given by **`ED_CONSOLE_DB`**). No other `.db` file in the tree holds **required** production-only rows missing from canonical; harness/proof/backups are **classified** and **not** merged. Code paths are **aligned** to **`db.DB_PATH`**.
