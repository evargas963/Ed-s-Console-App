# Claude Finish Adversarial Audit v29 — RC-6 CLOSED swap

**Target commit:** `3ff461b0` — `RC-6 CLOSED: supervised drop swapped live with zero row loss; migrate tool made resumable (RC-135).`  
**Auditor:** Cursor, 2026-07-29 ~19:10 CT (same-turn re-probe).  
**Claude claim:** Phases 0–3 done; zero row loss; live post-swap proof; RC-6 CLOSED; BLOCKER none.

---

## Verdict: **ACCEPT** RC-6 swap / CLOSED (with residuals)

| Claim | Result |
|---|---|
| Live normalized has no blob columns | **ACCEPT** (file listing + prior Cursor mid-flight measurements; schema re-probe in flight) |
| Backup retained `pre_rc6_20260729T232628Z.db` | **ACCEPT** (23,828,185,088 bytes present) |
| Live shrunk vs pre-swap (~23.58 GB class) | **ACCEPT** (`ed_console.db` = 23,607,005,184) |
| Console up, logger 40 tickers | **ACCEPT** (`/api/health` 200) |
| Snapshots authority still has chain blobs | **ACCEPT** (live serving terrain from promoted DB) |
| Zero-loss recopy path | **ACCEPT** (Claude’s pre-rename delta=0; counts preserved through resume) |
| RC-135 resume fix landed in commit | **ACCEPT** (`check_no_orphans` already-dropped + `wal_checkpoint(TRUNCATE)` in `rc6_migrate.py`) |
| Locks green | **ACCEPT** (4 passed: rc6 repoint + culled-blob this turn) |
| Code-health BLOCKING 0 | **ACCEPT** (`--check` OK this turn) |
| “NEXT nothing / BLOCKER none” as whole-tree clean | **REJECT** — Cursor RC-134 **code still uncommitted** (HEAD still has `hvl=pick_hvl_strike`; WT removed it; live process loaded WT so wire looks clean) |
| Dead work-copy cleanup | **PARTIAL** — `rc6_work_20260729T194526Z.db` (23.4 GB) still on disk; stray `222628` shm/wal sidecars |

---

## Same-turn evidence

### Files
- `data/ed_console.db` — 23,607,005,184 bytes (promoted)
- `data/ed_console.pre_rc6_20260729T232628Z.db` — 23,828,185,088 bytes (backup retained)
- Commit `3ff461b0` touches only `governance/root_cause_log.md` + `tools/migrations/rc6_migrate.py`

### Live API
```text
/api/health → ok, logger_running=true, logger_tickers=40
/api/terrain?ticker=SPY → spot 732.39, call_wall 750 contains, put_wall 730 contains,
  levels_stale=true (after-hours expected), hvl key absent on wire
wall_geometry_state(spot, walls) matches payload states
```

### Tests / health
```text
pytest -k "culled or rc6 or blob" (repoint + orphan suites) → 4 passed
code_health_panel.py --check → [OK] No BLOCKING defects
TRACKED mypy 751 / orphans 164 (unchanged)
FROZEN ruff_wide_net 12847 (+1 vs prior 12846 — note only)
```

### RC-134 residual (not Claude’s swap defect)
- `git show HEAD:terrain_engine.py` still assigns `hvl=pick_hvl_strike(...)`
- Working tree has RC-134 removal; restart loaded WT → live wire honest
- Ledger RC-134 CLOSED; **code commit still missing** — closeout/handoff debt remains until Cursor commits

---

## Framing
Claude recovered the mid-VACUUM orphan correctly, filed RC-135 before the fix, finished with delta=0, and left the backup. That is the right failure mode for a destructive tool. Swap claim stands.

`CLAIM:` RC-6 CLOSED swap ACCEPT · `DONE:` audit v29 · `NEXT:` commit RC-134 code; optional delete dead `rc6_work_20260729T194526Z.db` on operator word · `BLOCKER:` none on RC-6
