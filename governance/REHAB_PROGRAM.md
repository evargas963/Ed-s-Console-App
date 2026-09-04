# Repo Rehab Program (operator-invoked — RC-220)

**Directed by the operator in chat** (2026-08-24 teardown: no standing PM/auditor roles — any agent the operator assigns performs the rehab behaviors below that session).

**Scope of this file:** the distinct multi-faucet rehab PROCEDURE (operator charter 2026-08-03: repo-wide multi-faucet, audit → find → fix end-to-end → no patches). The general engineering law it applies — correct the whole connected path, no patch or fallback or second faucet, one computation authority, tests conform to the architecture, PASS only by direct proof — lives ONLY in `AGENTS.md` (Institutional end-to-end execution law) and is not restated here.

## Procedure

1. When the operator directs a session at rehab, **RH-F1 multi-faucet** is the spine of that work, across the whole continuum. Named missions (levels Phase 1, FORCES, DB) are **slices of that spine**, never a substitute for the program.
2. Every slice: **census → one authority → kill the second path (remove, never demote to fallback) → T1 tests → lock → prove LIVE (or DISK_ONLY + restart owed)**. A slice is not CLOSED until the second path is dead on disk **and** proven on the live process, or the row honestly says DISK_ONLY with the restart owed. Every field in the continuum — spot, walls, volume, PDL, charm, levels — can carry a faucet debt, on the backend, frontend, SQL, config or governance layer alike.
3. **Queue sources:** `reports/rehab_latest.md` + multi-faucet census artifacts + this file — RECORDS for the operator's triage; the operator opens each slice in chat; nothing self-opens.
4. **The ONE rehab measurement owner** is the daily scan, `tools/rehab_daily_scan.py` (host launcher `tools/run_rehab_daily.ps1`, inventory `governance/host_scheduled_jobs.md`). It is **recommend-only**; the operator turns findings into work. There is no second rehab measurement surface: the unscheduled self-measuring plan script that once sat beside it had no caller and was deleted (RC-516, 2026-09-04).

## Collect operable surface (RH-F5 procedure)

- **Authority for a "clean" Collect claim:** `python -m tools.operable_surface_gate --db data/ed_console.db` (committed). Re-run in the same turn before any clean/verified Collect claim.
- **Scope:** operable = `calibration_trust='trusted' AND COALESCE(research_excluded,0)=0`, **all tickers**. A sentinel-only (SPY/QQQ/IWM) clean result is `SENTINEL_SURFACE_CLEAN` only — never `OPERABLE_SURFACE_CLEAN` (AGENTS.md, UNIVERSAL ticker scope).
- **Do not widen** production `BACKFILL_JOIN_TOL_SEC` (29). The historical one-shot tol=59 repair was explicit ops, not a production default.
- **Recurring ops:** `python -m tools.run_operable_surface_ops` (backfill 29 + gate). Without it, young unattached rows age past 70m and regenerate old_missing.

## Standing facets (hunt these forever)

| ID | Facet | Done means |
|----|-------|------------|
| RH-F1 | **Multi-faucet / multi-clock (PRIMARY)** | Repo-wide census; one compute+serve authority per named level/field; second path **gone** (not demoted to quiet fallback); LIVE agreement proven |
| RH-F2 | Stale beside live | Age/fail-closed on every operator-facing number |
| RH-F3 | Empty/lie HTTP | No 200 with blank critical payload without error |
| RH-F4 | Ghost / half-wipe UI | Chart/console/exposure surfaces coherent; no orphan DOM |
| RH-F5 | Collect fidelity | Window law LIVE; operable surface; contention managed |
| RH-F6 | Decide hygiene | Admissions empty → WAIT; no unadmitted TRADE influence |
| RH-F7 | Static quality | BLOCKING 0; TRACKED not regressing unexplained |
| RH-F8 | Process | measure before claim, no killed hooks |

## Active slice

The operator names the active slice in chat (the pm_mission.json coordination file was removed 2026-08-24). Candidate-slice record for the operator's triage: `reports/multi_faucet_census_latest.md`.

## Rehab-specific anti-patterns (refuse these; the general ones are AGENTS.md laws 3–5, 10 and 12)

- UI polish while a measured dual-number lie remains on the same surface
- Running a full `server.py` stem battery (1000+ tests) as the default per-turn proof when a scoped suite already binds the change

## Test tiers (efficiency)

| Tier | When | What |
|------|------|------|
| **T1 Mission** | Before any green claim / commit | Only tests that name the changed behavior (here: ~32 levels/market_context tests) |
| **T2 Adjacent** | If T1 green but import surface risky | One related file’s tests, not the whole stem |
| **T3 Stem / full** | Nightly Automation or pre-release only | `turn_self_audit` full stem / 1800+ — **not** every mission turn |
| **T4 Pre-commit** | Every commit | Institutional hooks already run — do not re-run T3 in chat “to be safe” |

**Rule:** red T3 failures that reproduce on pristine HEAD are **rehab backlog**, not blockers for an unrelated mission — unless they are in files this mission touched. File them into the queue rather than stalling every landing.

## LIVE closeout / post-restart DONE bar

After any ed_server restart that is meant to clear WARN / malfunction debt or prove LIVE:

1. Operator restarts via `start_ed_console.bat` (uvicorn). Do not claim LIVE from a stale PID.
2. Root FileHandler must append plain lines (INFO+) for **all loggers** to `logs/ed_server.log`
   (`install_ed_server_file_sink` in `server.py` boot, flush-after-emit). Console-only WARNs are not enough.
3. **Required gate (5 min):**  
   `python -m tools.ed_server_warn_quiet_window`  
   Exit 0 / `verdict=PASS` only if, during the window:
   - zero failure signals: level ≥ WARNING (WARNING / ERROR / CRITICAL) for **any** logger
     (`db`, `ed_server`, uvicorn, …), including `[WARN]` / `[ERR ]` / `[CRIT]` markers and
     stdlib ` WARNING:` / ` ERROR:` / ` CRITICAL:` lines; **and**
   - zero `Traceback (most recent call last):` headers; **and**
   - the log file **progressed** (grew). Stale/dead sink → `MEASUREMENT_INVALID` (non-zero exit), never PASS.
   INFO/DEBUG lines never fail the gate. Optional artifact:
   `reports/ed_server_warn_quiet_window_latest.json`.  
   Smoke: `python -m tools.ed_server_warn_quiet_window --seconds 5`.
4. Without this PASS, do **not** claim post-restart DONE / “quiet console”.
5. **VOID:** any prior quiet-window PASS while `logs/ed_server.log` did not grow (e.g. stayed ~482 bytes
   with console-only `WARNING:db:...`) is **invalid** — re-run after restart with the root FileHandler live.
6. **fill_outcomes SLA:** `sqlite_bg_write_slow` at 5s+/10s+ remains WARNING (any-WARN FAIL). Live path
   caps work via `FILL_OUTCOMES_LIVE_BATCH_LIMIT` (newest-first) + prefetched cols (no N+1 SELECTs).
   Do not demote multi-second runs to INFO to pass the quiet window.
