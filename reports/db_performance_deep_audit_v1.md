# DB + console performance deep audit v1

**Date:** 2026-07-31 (Friday RTH, America/New_York)  
**MISSION_CLASS:** Collect (DB/console latency & lock health)  
**STATUS:** PARTIAL — high-confidence code fixes in worktree; live process still on pre-fix SHA until operator restart  
**DECISION_PATH:** none (Decide WAIT; `decision_path_admissions` untouched)  
**OUT-OF-SCOPE:** Collect EOD residual PASS; combo-highlight; RC-165 Chart STALE wording (separate; noted only); terrain/storm1/LP-01 redesign; `BACKFILL_JOIN_TOL_SEC` widening

# chart-intent-ok: Collect/DB performance slice; Chart render Done not claimed  
# next-rth-ok: 2026-07-31 Friday (live session under audit)

---

## Admission (AGENTS.md)

| Field | Value |
|-------|--------|
| MISSION_CLASS | Collect |
| GAP | Live DB_DEGRADED + `/api/analytics/light` wall ≫ `_pipeline_ms` |
| SMALLEST_COMPLETE_CHANGE | Measure writers/WAL/light → ranked RC → safe lock-hold + pool isolation fixes + this report |
| MINIMUM_SUFFICIENT_EVIDENCE | Same-turn contention snapshot, pragmas/sizes, route timings, pytest |
| DECISION_PATH_EFFECT | none |
| WHY_NOW | Operator GO — freeze is live pain |
| TASK_ADMISSION | ADMITTED |

---

## 1) MEASURE (same-turn)

### Process / build

Reproduce:

```text
.venv\Scripts\python.exe -c "import json,urllib.request; print(json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/build', timeout=30)))"
```

**PROVEN (this turn):**
- `process_id`: **34440**
- `startup_git_sha`: `6c47b89bdcb4daa75842a1edcc43205d454a3191`
- `/api/health`: `logger_running=true`, `logger_tickers=40`, wall ~297 ms
- `/api/build` wall later re-probe: **4265.3 ms** (same process under load)

### DB file / WAL / pragmas (read-only URI connect — not the live EdDB connection)

Reproduce:

```text
.venv\Scripts\python.exe -c "from pathlib import Path; import sqlite3; db=Path('data/ed_console.db'); print(db.stat().st_size, Path(str(db)+'-wal').stat().st_size); c=sqlite3.connect(f'file:{db.as_posix()}?mode=ro', uri=True, timeout=5); print([(p,c.execute('PRAGMA '+p).fetchone()) for p in ['journal_mode','busy_timeout','synchronous','wal_autocheckpoint','cache_size','mmap_size']])"
```

**PROVEN (this turn):**
| Item | Value |
|------|--------|
| `ed_console.db` | **25,218,498,560** bytes (25.218 GB) |
| `ed_console.db-wal` | **181,131,712** bytes (181.1 MB) |
| `ed_console.db-shm` | 32,768 bytes |
| RO `journal_mode` | wal |
| RO `busy_timeout` | 5000 (RO probe does **not** call `configure_sqlite_connection`) |
| RO `cache_size` / `mmap_size` | -2000 / 0 (defaults on bare connect) |
| Live EdDB config (code + contention `config`) | `busy_timeout_ms=30000`, WAL, mmap 2 GiB, cache 128 MiB via `configure_sqlite_connection` |

**Why 25GB / 181MB WAL matters (ranked):**
1. **Does not explain** the measured freeze by itself: `sqlite_busy_retry_count=0` → waits are on the **Python** `_TIER1_SNAPSHOT_WRITE_LOCK`, not SQLITE_BUSY.
2. **Does matter** for write amplification and future checkpoint cost: 181 MB WAL with `wal_autocheckpoint=1000` pages and no in-process TRUNCATE loop (`tools/db_maintenance.py` is ops-only).
3. Large DB makes outcome-refresh SELECTs under the lock more expensive when they run — amplifying cause #1 below.
4. Mid-session `wal_checkpoint(TRUNCATE)`: **parked** (destructive risk during RTH). UNBLOCKED-BY: operator post-close or explicit GO.

### SQLite contention (live process)

Reproduce:

```text
.venv\Scripts\python.exe scratchpad\_db_perf_probe_v1.py
# or:
.venv\Scripts\python.exe -c "import json,urllib.request; print(json.dumps(json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/diagnostics/sqlite-contention', timeout=30)), indent=2)[:4000])"
```

**PROVEN — first snapshot this turn (~13:44–13:45 CT window):**
| Metric | Value |
|--------|--------|
| `sqlite_lock_wait_count` | **395** |
| `sqlite_lock_wait_total_ms` | **5,272,552.333** |
| `sqlite_lock_wait_max_ms` | **97,278.463** (~97.3 s) |
| `sqlite_busy_retry_count` | **0** |
| `sqlite_database_locked_count` | **0** |
| ops | `upsert_1m_bars`: **303**, `insert_snapshot`: **92** |
| hottest threads | `ed_bars_0/1/2`: 103 / 101 / 99 |

**PROVEN — re-probe after ~10 minutes (scratchpad probe):**
| Metric | Value |
|--------|--------|
| waits | **467** |
| max_ms | **138,924.745** (~138.9 s) |
| busy | **0** |
| ops | upsert **346**, insert_snapshot **121** |

Recent event samples (same process): `upsert_1m_bars` waits of 1.7s–21.4s on `ed_bars_*`; `insert_snapshot` waits ~9.0s on ThreadPoolExecutor / `ed_sse_fetch_timeout_*`.

**Interpretation (PROVEN from metrics + code):** lock_wait is time waiting to acquire `_TIER1_SNAPSHOT_WRITE_LOCK` (db.py), not SQLite busy. Zero busy retries means the bottleneck is **serialized long holds** of that process lock, dominated by `upsert_1m_bars`.

### Writers (code + coded frequency)

| Writer | Interval / gate | Serialized by | Cite |
|--------|-----------------|---------------|------|
| `upsert_1m_bars` | bars loop 30s, 3 workers | tier-1 lock | server.py bars loop; db.py |
| `insert_snapshot` | base capture ~60s; viewer ≤1/min/ticker | tier-1 lock | server.py |
| `persist_chain_accrual` | floors 60s/300s on terrain workers×2 | SQLite WAL only (not tier-1) | option_chain_morning_full.py |
| `fill_outcomes` | dedicated executor max_workers=1 | SQLite WAL only | db.py / server.py |
| Calibration / confluence ticks | opportunistic | SQLite WAL only | various |

### `/api/analytics/light` wall ≫ `_pipeline_ms`

**PROVEN from code:**
- `_pipeline_ms` is set only inside `build_l1_context` (planes/context_light.py) — pure L1 assembly.
- HTTP handler (pre-fix) ran `_touch_tracked_ticker_view` + L1 build on **`ed_route_offload` (8 workers)** shared with Tier C JSON and streaming resubscribe (≤30s).
- Fast-quote uses **`ed_quote_hot`** — intentionally isolated; explains intermittent “price OK / cards freeze”.

**PROVEN live timings (scratchpad probe, old code still running):**
| Route | wall_ms | notes |
|-------|---------|-------|
| `/api/analytics/light?ticker=SPY` | **891.2** | `pipeline_ms=45.187`; `_route_await_executor_ms` absent (old code) |
| `/api/fast-quote?ticker=SPY` | **2338.2** | |
| `/api/terrain?ticker=SPY` | **2807.7** | |
| contention endpoint | **1381.4** | |

Earlier organic reports of median ~9s / spikes ~33s for light remain **directionally consistent** with shared-pool queue under burst; this turn’s single light sample was 0.89s — intermittent, not a disproof.

Reproduce light wall vs pipeline:

```text
.venv\Scripts\python.exe scratchpad\_db_perf_probe_v1.py
```

After restart, expect `_route_await_executor_ms` and `_route_total_ms` on the light JSON.

---

## 2) ROOT CAUSE TREE (5-why, evidence-tagged)

### Primary freeze path (UI overlay / DB_DEGRADED / cards lag)

1. Operator sees **DB DEGRADED** / cards lag / intermittent freeze.  
2. `/api/diagnostics/sqlite-contention` shows climbing **lock_wait** with max tens–hundreds of seconds, ops=`upsert_1m_bars`+`insert_snapshot`.  
3. `busy_retry=0` → not SQLITE_BUSY; waits are on **`_TIER1_SNAPSHOT_WRITE_LOCK.acquire()`**.  
4. Three `ed_bars_*` workers call `upsert_1m_bars` every ~30s; each hold includes SELECT filter + executemany + (pre-fix) **governed outcome refresh** on the same connection under the lock; live path also **unconditionally rewrote the ~180s overlap window** every cycle even when OHLC/volume were identical → refresh work every cycle.  
5. **ROOT:** tier-1 process lock held across redundant overlap rewrites + governed outcome refresh, so snapshot/UI writers queue for seconds–minutes behind bar workers.

### Why analytics/light wall ≫ pipeline_ms

1. Client sees multi-second light / SSE starvation while `_pipeline_ms` ~12–45 ms.  
2. `_pipeline_ms` only times L1 dict assembly.  
3. Pre-fix handler awaited `run_in_executor(ed_route_offload)` which also runs Tier C serve + streaming touch (≤30s).  
4. Same task also did `logging_universe` UPDATE before L1 (SQLite write under contention).  
5. **ROOT:** L1 HTTP shared a contended route pool and bundled a DB touch into the awaited path; instrumentation hid queue/DB wait outside `_pipeline_ms`.

### WAL 181 MB

- Amplifies I/O cost; **not** the primary measured freeze mechanism this turn (`busy_retry=0`).  
- Checkpoint ops parked mid-RTH.

### Ranked causes

| Rank | Cause | Impact | Tag |
|------|-------|--------|-----|
| 1 | Overlap-window unconditional rewrite + governed refresh under tier-1 lock | Multi-second–100s+ lock waits; DB_DEGRADED | **PROVEN** |
| 2 | L1 light on shared `ed_route_offload` + awaited SQLite touch | wall ≫ pipeline; intermittent freeze while quote-hot OK | **PROVEN** (code) + **partial live** (intermittent) |
| 3 | 3 concurrent bar workers × ~40 tickers × 30s | Queue depth on tier-1 | **PROVEN** structure; magnitude from contention metrics |
| 4 | Large WAL / no live checkpoint | Write amplification; future checkpoint stalls | **PROVEN** size; causal share of freeze **[UNVERIFIED]** |
| 5 | Accrual JSON writes outside tier-1 / bare connect | Competing WAL writer | Structure **PROVEN**; share **[UNVERIFIED]** given busy=0 |
| 6 | 25 GB DB cold reads | General slowness | RC-50 already tunes mmap/cache on EdDB connections; residual **[UNVERIFIED]** |

---

## 3) FIXES SHIPPED (worktree)

### A) `db.py` — shorten tier-1 hold (RC-166)

1. Live incremental filter: write only **MISSING or CHANGED** bars (removed unconditional overlap rewrite).  
2. Governed outcome refresh moved to a **post-unlock** connection; failures log and rely on `fill_outcomes` repair.  

### B) `server.py` — isolate L1 light (RC-166)

1. New `ed_l1_light` pool (`L1_LIGHT_EXECUTOR_MAX_WORKERS=4`).  
2. `/api/analytics/light` awaits that pool only; `logging_universe` touch is **fire-and-forget** on route_offload.  
3. Route timing fields: `_route_await_executor_ms`, `_route_total_ms` + log line `analytics_light_route_done`.

### Tests (same-turn)

```text
.venv\Scripts\python.exe -m pytest tests/test_db_perf_rc166_v1.py tests/test_db_sqlite_tier1_retry.py::test_live_bar_upsert_is_incremental_bulk_path_full tests/test_db_sqlite_tier1_retry.py::test_live_bar_upsert_writes_mutated_overlap_bar tests/test_db_sqlite_tier1_retry.py::test_live_bar_upsert_covers_downtime_gap tests/test_governed_outcome_refresh_after_bar_mutation_v1.py -q --tb=short
```

**PROVEN:** `9 passed` in 139.12s.

### Not done (parked)

| Item | Why parked |
|------|------------|
| Live `wal_checkpoint(TRUNCATE)` | Mid-RTH destructive risk |
| Accrual `configure_sqlite_connection` | busy_retry=0; lower confidence vs #1 |
| Reduce `BARS_WORKERS` | Would slow Collect; not needed if holds shrink |
| Terrain / storm1 / LP-01 redesign | Explicitly forbidden |
| Claim live latency fixed | Process still on `6c47b89`; needs restart + re-measure |

---

## 4) UNBLOCKED-BY (live proof)

Operator-approved **console restart** onto this worktree (also picks up RC-165 staleness honesty).

Post-restart acceptance probes (do not claim CLOSED without these):

```text
.venv\Scripts\python.exe scratchpad\_db_perf_probe_v1.py
```

Expect:
1. Light JSON includes `_route_await_executor_ms` / `_route_total_ms`; wall should track await (not mysterious multi-second gap vs pipeline alone).  
2. `/api/diagnostics/sqlite-contention` **recent** waits decay (120s window → OK) — cumulative lifetime max may still show the old peak until process restart clears counters.  
3. After ~5–10 minutes of bars: recent `upsert_1m_bars` lock waits should be ≪ pre-fix tens-of-seconds samples **[measure, do not assume]**.  
4. Terrain STALE sentence (RC-165) uses delivered-cycle wording.

**Expected speedup:**  
- Tier-1 queue: **[UNVERIFIED]** until post-restart; structurally should drop from “rewrite ~4 bars + outcome refresh every cycle” to “0 writes on identical reseed / refresh only on mutation”.  
- Light wall: **[UNVERIFIED]** until post-restart; pool isolation removes Tier C/stream head-of-line blocking by construction.

---

## 5) Drift-audit (self)

- Intent: make DB/console fast; do not claim Collect Done / Decide influence.  
- AST: `get_analytics_light` awaits `_get_l1_light_executor` only (test).  
- Presence vs capability: live process still old SHA — fix not operative until restart.  
- Silent-swallow: post-unlock refresh failures logged; fill_outcomes remains repair.  
- Fail-closed: bar write still returns count; labels may lag briefly (honest).  
- Test path: drives real upsert + lock acquire during refresh + AST of light handler.  
- EXPLAIN: no ad-hoc multi-GB join added.  
- Verdict: **CLEAN for worktree unit proof; NOT MET for live DB fixed.**

---

## STATUS

`CLAIM:` measured live contention (max wait 97s→139s, busy=0, upsert-dominated) + light pool/instrumentation gap; shipped RC-166 worktree fixes + 9 green tests · `DONE:` audit report + RC-166 PARTIAL · `NEXT:` operator restart + post-restart probe · `BLOCKER:` live process still `6c47b89` (restart GO)
