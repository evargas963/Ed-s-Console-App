# Database Inventory and Integrity

**Scope:** All SQLite database files under the EdWebConsole project tree, plus how code references them.  
**Scan method:** Recursive `*.db` discovery + `sqlite_master` / row counts (snapshot taken at audit time).

---

## 1. All DB files found

| # | Relative path | Size (bytes) | Last modified (UTC) | Notes |
|---|----------------|--------------|----------------------|--------|
| 1 | `data/ed_console.db` | 2,815,070,208 | 2026-04-11 | **Primary runtime DB** (`db.DB_PATH`) |
| 2 | `data/ed_console.db-wal` | ~10.65 GB | (sidecar) | Uncommitted WAL; active writes accumulate here until checkpoint |
| 3 | `data/ed_console.db-shm` | ~20 MB | (sidecar) | Shared-memory for WAL mode |
| 4 | `ed_console.db` (repo root) | **0** | 2026-03-08 | **Empty file** — not used by `db.py` (which uses `data/ed_console.db`) |
| 5 | `data/calibration_accumulation_validation.db` | 1,912,832 | 2026-04-11 | Harness / deterministic accumulation |
| 6 | `data/calibration_anchor_proof.db` | 548,864 | 2026-04-11 | Small anchor-proof dataset |
| 7–13 | `data/backups/ed_console.*.db` (7 files) | ~1.5–1.7 GB each | 2026-04-03 | **Point-in-time backups** of `ed_console` (older schema: no `calibration_decision_log`) |

**Total distinct `.db` files:** **11** (excluding WAL/SHM which are not separate logical DBs).

---

## 2. Row counts per DB (key tables)

| DB | `calibration_decision_log` | `snapshots` | `price_bars_1m` |
|----|----------------------------|-------------|-----------------|
| `data/ed_console.db` | 43 | 162,077 | 90,427 |
| `data/calibration_accumulation_validation.db` | 120 | 120 | 788 |
| `data/calibration_anchor_proof.db` | 30 | 30 | 30 |
| `data/backups/*.db` | *(table absent)* | 141k–142k range | 24k–48k range |

Backups predate the `calibration_decision_log` table migration on those copies.

---

## 3. Ticker coverage per DB

| DB | Distinct `snapshots.ticker` | Distinct `price_bars_1m.ticker` |
|----|-----------------------------|----------------------------------|
| `data/ed_console.db` | 26 | 26 |
| `data/calibration_accumulation_validation.db` | 4 (DIA, IWM, QQQ, SPY) | 4 |
| `data/calibration_anchor_proof.db` | 2 (QQQ, SPY) | 2 |
| Backups | 23–24 | 19–23 |

---

## 4. Time coverage per DB (`ts_utc` / bars)

| DB | `snapshots` min/max `ts_utc` | `price_bars_1m` bar range |
|----|------------------------------|----------------------------|
| `data/ed_console.db` | 1771914351.00 → 1775939460.02 | bar_start min 1771808400; bar_end max 1775939340 |
| `data/calibration_accumulation_validation.db` | 1712200000 → 1712211900 | synthetic harness window |
| `data/calibration_anchor_proof.db` | 1712100000 → 1712102900 | narrow proof window |
| Backups | ~1771914351 → ~1775237813 | older upper bound than current prod |

---

## 5. Code path mapping

### Canonical path (production)

| Symbol | Definition |
|--------|------------|
| `db.DB_DIR` | `Path(__file__).parent / "data"` |
| `db.DB_PATH` | `data/ed_console.db` |
| `calibration.paths.DEFAULT_DB` | `PROJECT_ROOT / "data" / "ed_console.db"` |

**Primary writer:** `EdDB` in `db.py` — opens `self.db_path` (default `DB_PATH`) for snapshots, bars, session log, calibration when logging enabled, etc.

**Calibration writer:** `calibration/writer.py` resolves DB via `DB_PATH` / `DEFAULT_DB` → same file.

**Environment override (ML / drift tooling):** `ED_CONSOLE_DB` — used e.g. in `ml_predict.py`, `ml_train.py`, `arch_competition/live_drift_monitoring.py` to point at a DB path; default remains project `data/ed_console.db` when unset.

### Alternate / test DB paths (not default production)

| Module / script | Path behavior |
|-----------------|---------------|
| `calibration/run_production_accumulation_validation.py` | **`db_mod.DB_PATH = OUT_DB`** for `data/calibration_accumulation_validation.db` during harness run |
| `calibration/edge_discovery.py` | Chooses among `ed_console.db` vs harness DB for analysis |
| `calibration/signal_layer_discrimination.py` | CLI arg or default harness DB |
| Tests | `:memory:` or `tmp_path / "*.db"` |
| `audit_snapshot_data.py`, `verify_snapshot_pipeline.py` | Explicit `data/ed_console.db` |

### Reads vs writes (summary)

- **Read/write (live):** `data/ed_console.db` via `EdDB` and direct `sqlite3.connect(DEFAULT_DB)` in tools/calibration.
- **Write (harness only):** `calibration_accumulation_validation.db` when accumulation script runs; `calibration_anchor_proof.db` when that builder runs.
- **Read-only copies:** `data/backups/*.db` — not referenced as live paths in core app code (manual restore / audit).

---

## 6. FINAL: Is data fragmented? **YES**

**Interpretation:**

- **Operational fragmentation:** Live state for the running system is intended to live in **one** file: `data/ed_console.db` (+ WAL/SHM). Harness and proof DBs hold **disjoint, smaller** datasets for validation — they are **not** a sharded production replica.
- **Historical fragmentation:** Multiple **full or partial** copies exist under `data/backups/` with **older** snapshot/bar counts and **no** `calibration_decision_log` — useful for rollback comparison, not for unified live queries across files.
- **Stray fragmentation:** A **zero-byte** `ed_console.db` at the **repository root** is misleading; the app does **not** use it (`db.py` points under `data/`).

---

## 7. TRUE production DB identified

**`data/ed_console.db`** (resolved as `db.DB_PATH` / `calibration.paths.DEFAULT_DB`).

It is the **largest** database, the **only** one with the full current `snapshots` + `price_bars_1m` + `calibration_decision_log` combination at current row counts, and the path **all** default server/calibration writers use. Other `.db` files are harnesses, proofs, backups, or empty stray files.

**Completeness note:** The on-disk SQLite file size does not include uncheckpointed WAL; logical “full” state = main file + `ed_console.db-wal` until checkpoint/merge.

---

## 8. Reproducibility

To re-list DB files (PowerShell):

```powershell
Get-ChildItem -Path . -Recurse -Filter "*.db" -File | Select-Object FullName, Length, LastWriteTimeUtc
```

To re-count tables for a path:

```python
import sqlite3
conn = sqlite3.connect(r"data\ed_console.db", timeout=60)
print(conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall())
```
