# Repo Rehab Program (standing — RC-220)

**PM:** Cursor. **Operator does not have to remind the PM to rehab the whole repo.**

**Primary charter (operator 2026-08-03):** **repo-wide multi-faucet** — **audit → find → fix end-to-end → no patches.**  
Not “one endpoint.” Not “leave the old producer as fallback.” Not CLOSED until the second path is dead on disk **and** proven on the live process (or honestly DISK_ONLY with restart owed).

Charter restated: piece-by-piece, fix-by-fix, **end-to-end** — dual paths die in-mission or the row stays PARTIAL/OPEN.

## Law

1. Rehab is the **default program**. The spine is **RH-F1 multi-faucet** across the whole continuum. Named missions (levels Phase 1, FORCES, DB) are **slices of that spine**, never a substitute for the program.
2. Every slice: **census → one authority → kill the second path (remove or hard-fail) → T1 tests → lock → prove LIVE (or DISK_ONLY + restart owed)**. No “delegate later” residue without an OPEN RC.
3. **No patches:** a fix that leaves the old producer callable as a silent second faucet is incomplete. Mark PARTIAL until the dead path is removed or hard-fails closed.
4. **Whole continuum:** backend, frontend, SQL, config, governance — same standard (mandate-to-mechanism). Spot, walls, volume, PDL, charm, levels — every named field can have a faucet debt.
5. **Queue authority:** `reports/rehab_latest.md` + multi-faucet census artifacts + this file. PM triages every session start. After a slice’s LIVE proof, PM opens the **next faucet P0** without waiting to be asked.
6. Daily scan (`tools/rehab_daily_scan.py` / Automation) is **recommend-only**; PM turns findings into missions.

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
| RH-F8 | Process | PM-first, sole writer, GO, no killed hooks |

## Active slice

See `governance/pm_mission.json` — **levels-tierb-session-collapse-v1** (RH-F1 census #2–5) armed behind quiet-window PASS (`log_progressed=true`). When idle after that slice LIVE/PARTIAL+restart-owed, PM’s next act is: open the next highest P1 from `reports/multi_faucet_census_latest.md` (clocks #7 or charm #6) — not wait for operator to invent work.

## Anti-patterns (PM must refuse)

- Soft “we’ll collapse producers later” without OPEN RC + date
- Second faucet kept as “fallback”
- UI polish while a measured dual-number lie remains on the same surface
- Claiming COMPLETE without END-TO-END reach on named victims
- Running a full `server.py` stem battery (1000+ tests) as the default per-turn proof when a scoped suite already binds the change

## Test tiers (efficiency — PM enforces)

| Tier | When | What |
|------|------|------|
| **T1 Mission** | Before any green claim / commit | Only tests that name the changed behavior (here: ~32 levels/market_context tests) |
| **T2 Adjacent** | If T1 green but import surface risky | One related file’s tests, not the whole stem |
| **T3 Stem / full** | Nightly Automation or pre-release only | `turn_self_audit` full stem / 1800+ — **not** every mission turn |
| **T4 Pre-commit** | Every commit | Institutional hooks already run — do not re-run T3 in chat “to be safe” |

**Rule:** red T3 failures that reproduce on pristine HEAD are **rehab backlog**, not blockers for an unrelated mission — unless they are in files this mission touched. PM owns filing them into the queue, not stalling every landing.

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
