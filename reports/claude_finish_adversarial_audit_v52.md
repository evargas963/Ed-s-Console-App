# Claude Finish Adversarial Audit v52 — RC-166 DB freeze worktree (2026-07-31)

**Auditor:** Cursor (adversarial), 2026-07-31 ~14:00 CT  
**Target claims (agent 2da31cbb):** Deep DB audit → freeze = Python tier-1 write-lock queue (`upsert_1m_bars` dominates; `SQLITE_BUSY=0`; waits ≤~139s); light wall ≫ `_pipeline_ms` = shared pool / untimed wait; RC-166 PARTIAL worktree (incremental bars, post-unlock outcome refresh, `ed_l1_light` + fire-and-forget last-seen + route timing); 9 tests green; needs restart; Collect residual PARTIAL; Decide untouched.  
**Scope:** verify only. **No commit. No console restart.**

**Admission:** MISSION_CLASS=Collect (adversarial honesty) · GAP=confirm RC-166 code/tests/RC stamp vs live · SMALLEST_COMPLETE_CHANGE=this file · MINIMUM_SUFFICIENT_EVIDENCE=report+diff+pytest+live `/api/build`+contention · DECISION_PATH_EFFECT=none · WHY_NOW=restart GO pending · TASK_ADMISSION=audit only.

# chart-intent-ok: latency/DB path audit; Chart render Done not claimed  
# next-rth-ok: 2026-07-31 Friday

---

## Verdict: **ACCEPT worktree / PARTIAL** (not live-fixed; not FAIL)

Investigator claims match the worktree. RC-166 correctly stays **PARTIAL**. Do **not** claim speedup until post-restart probe.

| # | Claim | Same-turn evidence | Result |
|---|---|---|---|
| 1 | Freeze = Python `_TIER1_SNAPSHOT_WRITE_LOCK` queue; busy=0; upsert-dominated; max ~139s | Live `/api/diagnostics/sqlite-contention`: `sqlite_busy_retry_count=0`, `sqlite_lock_wait_max_ms=138924.745`, `sqlite_lock_wait_count=548` (↑ from report 467), ops `upsert_1m_bars` + `insert_snapshot`. Code: lock_wait meters acquire of tier-1 lock | **PASS** |
| 2 | Live path no longer force-rewrites ~180s overlap; only MISSING/CHANGED | `git diff db.py`: cutoff/`LIVE_BARS_REUPSERT_OVERLAP_SEC` branch removed from `_needs_write`; equality on OHLC/volume. Tests cover identical reseed→0, mutation→1, gap fill | **PASS** |
| 3 | Governed refresh after tier-1 release | Refresh moved after `_tier1_snapshot_write`; separate `_connect()`. `test_governed_refresh_runs_after_tier1_lock_release` + mutation outcome test | **PASS** |
| 4 | `ed_l1_light` pool; F&F last-seen; `_route_await_executor_ms` / `_route_total_ms` | `server.py`: `_get_l1_light_executor` (4 workers); light awaits that pool only; touch via `submit` on route_offload; timing fields on JSON | **PASS** |
| 5 | 9 tests green | Same-turn: `.venv\Scripts\python.exe -m pytest …` → **`9 passed` in 98.63s** | **PASS** |
| 6 | RC-166 PARTIAL not false CLOSED; BLOCKER/UNBLOCKED-BY; VISIBLE_SURFACE | Row status **PARTIAL**. Fix cell: UNBLOCKED-BY operator restart + re-probe; `VISIBLE_SURFACE: none new` (latency path, not new DOM — legal). Collect EOD residual not Done; Decide WAIT | **PASS** |
| 7 | Live still pre-fix SHA; no speedup claim | `/api/build`: `process_id=34440`, `startup_git_sha=6c47b89bdcb4…`; HEAD same SHA with **dirty** worktree. Contention still climbing — fix **not loaded** | **PASS** (pre-fix confirmed) |

---

## Drift-audit (this turn)

- **Intent:** shorten tier-1 hold + isolate L1; not Collect Done / Decide.
- **Presence vs capability:** worktree present; live process still `6c47b89` → **not operative**.
- **Silent-swallow:** post-unlock refresh `except Exception: log.exception` + `fill_outcomes` repair — honest lag, not silent success.
- **Fail-closed:** identical reseed returns 0 writes (no fake refresh); mutation still writes.
- **Test path:** real upsert + lock-free assertion during refresh + AST of light handler — not proxy-only.
- **Doc drift (minor):** `upsert_1m_bars` docstring still says refresh “in the same connection” (stale vs RC-166). `LIVE_BARS_REUPSERT_OVERLAP_SEC` is now unused constant.
- **Verdict:** **CLEAN for worktree unit proof; NOT MET for live DB fixed.**

---

## Residual risks (ranked)

1. **Live not restarted** — still max wait ~139s cumulative; queue continues (`wait_count` 548).  
2. **Post-unlock label race** — brief BAR_ANCHOR_V1 lag / concurrent WAL writers until refresh or `fill_outcomes` (accepted trade).  
3. **Float OHLC/volume equality** — SQLite REAL vs Python float: miss a true change (under-write) or spurious rewrite (lock pressure returns). Covered for deliberate mutations; wire noise **[UNVERIFIED]**.  
4. **`source`-only change skipped** — `_needs_write` ignores `source` field.  
5. **Fire-and-forget last-seen** — under route_offload saturation, touch can lag/fail (debug log); enrollment aging, not freeze.  
6. **`ed_l1_light` (4)** — can still queue on cold/force L1 recompute; isolated from Tier C only.  
7. **WAL ~181MB / 25GB DB** — parked; not primary (busy=0) but still I/O amplifier.

---

## Safe to restart?

**Yes — operator-approved mid-session restart is the stated UNBLOCKED-BY** (also picks up RC-165 STALE wording). Not auditor-forced. Restart loads dirty worktree; no live speedup claimed until probes pass.

**Post-restart probe:**
1. `/api/build` new `process_id` + identity reflects loaded code (dirty OK if intentional).  
2. Light JSON has `_route_await_executor_ms` / `_route_total_ms`; wall tracks await.  
3. Contention **recent** window decays (lifetime max may reset on new process).  
4. After 5–10 min bars: recent `upsert_1m_bars` waits ≪ pre-fix tens-of-seconds samples — **measure**.  
5. Terrain STALE sentence uses DELIVERED-cycle wording (RC-165).

---

## STATUS

`CLAIM:` ACCEPT worktree / PARTIAL — RC-166 code+9 tests match claims; live still `6c47b89` pid=34440 busy=0 wait_max=138924.745 count=548 · `DONE:` v52 audit · `NEXT:` operator restart + `_db_perf_probe_v1.py` · `BLOCKER:` restart consent (no speedup until measured)
