# Repo Rehab Program (operator-invoked — RC-220)

**Directed by the operator in chat** (2026-08-24 teardown: no standing PM/auditor roles — any agent the operator assigns performs the rehab behaviors below that session).

**Primary charter (operator 2026-08-03):** **repo-wide multi-faucet** — **audit → find → fix end-to-end → no patches.**  
Not “one endpoint.” Not “leave the old producer as fallback.” Not CLOSED until the second path is dead on disk **and** proven on the live process (or honestly DISK_ONLY with restart owed).

Charter restated: piece-by-piece, fix-by-fix, **end-to-end** — dual paths die in-mission or the row stays PARTIAL/OPEN.

## Law

1. When the operator directs a session at rehab, **RH-F1 multi-faucet** is the spine of that work, across the whole continuum. Named missions (levels Phase 1, FORCES, DB) are **slices of that spine**, never a substitute for the program.
2. Every slice: **census → one authority → kill the second path (remove or hard-fail) → T1 tests → lock → prove LIVE (or DISK_ONLY + restart owed)**. No “delegate later” residue without an OPEN RC.
3. **No patches:** a fix that leaves the old producer callable as a silent second faucet is incomplete. Mark PARTIAL until the dead path is removed or hard-fails closed.
4. **Whole continuum:** backend, frontend, SQL, config, governance — same standard. Spot, walls, volume, PDL, charm, levels — every named field can have a faucet debt.
5. **Queue sources:** `reports/rehab_latest.md` + multi-faucet census artifacts + this file — RECORDS for the operator's triage; the operator opens each slice in chat; nothing self-opens.
6. Daily scan (`tools/rehab_daily_scan.py` / Automation) is **recommend-only**; the operator turns findings into work.

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

## Anti-patterns (refuse these)

- Soft “we’ll collapse producers later” without OPEN RC + date
- Second faucet kept as “fallback”
- UI polish while a measured dual-number lie remains on the same surface
- Claiming COMPLETE without END-TO-END reach on named victims
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

## Daily ACT + RE-MEASURE pass (moved from the retired reports-side agent brief, 2026-09-05, RC-520)

MEASURE and TRIAGE are automated by `tools/rehab_daily_scan.py`; this is the other half of the loop (RC-246 → RC-250 → RC-251). The backlog total is **not a work order**: a repo-wide autofix would touch the money path with no behavioural test per change, which is how a "cleanup" becomes an incident. Debt falls in increments that can each be proven safe.

**Inputs (read all three; do not re-run the world):** `reports/rehab_latest.md` (human view), `reports/tqm_queue_latest.json` (the machine queue — **the only work list**), `reports/advisory_debt_latest.json` (per-check tally + per-file hotspots).

1. **TRIAGE — accept or kill each item, out loud.** Work **only** `top_items` (max 5). Every item ships with `kill_criteria`; killing an item is a legitimate outcome — say why in one line.
2. **ACT — smallest safe change, one item at a time.** Preferred: `ruff --fix` scoped to the single file, then that file's own test module. Types: annotate the one function the error names; do not restructure call sites. Length/complexity: extract *one* cohesive block with a behavioural test pinning before == after on real inputs (RC-19: a split to save seven lines added five circular imports; SHAPE metrics track but never block). Orphan keys: delete at the producer **and** prove no consumer reads it end-to-end — a static orphan can be a live field via dynamic access. **Never:** drive-by refactors, opportunistic renames, touching anything the item did not name, or touching `data/ed_console.db` (+ `-wal`/`-shm`) / `data/ed_console_claude.db`.
3. **RE-MEASURE — same harness, same turn.** `python tools/rehab_daily_scan.py`, then record **before → after** for `advisory_total` and `delta` in the report and in the RC row. If the number did not move, say so; if it rose, find out why.
4. **LEDGER — the row opens before the fix (`tools/mission_latch.py`) and closes only with the measured delta and the reproduce command.** If the host clock is still missing, the schedule half stays **PARTIAL**.

**Boundaries:** advisory checks never return to the blocking commit path (RC-246; a control asserts it); no mass rewrites; no database deletion or "disk cleanup" as quality work; RC-166 / RC-227 / RC-243 close only on a live mid-RTH `sqlite-contention` reading; no product rename unless the operator says so.

**Empty or stale queue:** an empty queue with a non-zero total means hotspots were dropped between the gate and the scan (that bug shipped once); check `hotspots` in `advisory_debt_latest.json`, then in the queue JSON. A stale report (>48 h) carries a P1 `rehab.advisory_report_stale` finding — fix the schedule before working the list.
