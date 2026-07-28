# BRUTAL ADVERSARIAL AUDIT v2 — Claude "finished" again (2026-07-27 ~20:18 CT)

**Verdict: REJECT. NOT FINISHED.**

---

## Headline

Uncommitted WIP only. No new commit since `0a3d2c7a`. Lock-set still **33/35 OPEN: RC-12, RC-70**. Adjacent still OPEN: RC-31, RC-43, RC-58, RC-96, RC-97. Declaring finished in this state is false-completion.

---

## Still OPEN (exact)

| RC | Status | What Claude did | Verified? |
|---|---|---|---|
| RC-12 | OPEN | nothing this round | NO |
| RC-70 | OPEN | bat launcher drafted; task not rewired; row not closed | NO |
| RC-97 | OPEN | diagnosed PYTHONUTF8 trailing-space; check added; bat untracked | PARTIAL code, not end-to-end |
| RC-96 | OPEN | row created; AGENTS SOFT labels; loophole fix in check | PARTIAL — row still OPEN / IN PROGRESS |
| RC-31 | OPEN | untouched | NO |
| RC-43 | OPEN | still OPEN with FIX text saying CLOSED | LOG HYGIENE FAIL |
| RC-58 | OPEN | untouched this round | NO |

---

## What landed (credit, not discharge)

1. Correct root cause for scorecard: `set PYTHONUTF8=1 &&` → value `"1 "` → Python pre-init fatal.
2. `tools/run_terrain_scorecard.bat` — quoted `set "PYTHONUTF8=1"`, uses `.venv` python. **Untracked.**
3. `check_scheduled_producers_are_not_inert` ENFORCED — scans `reports/*_run.log` for fatals. **Uncommitted.**
4. AGENTS.md four grandfathered laws now marked `[SOFT …]`.
5. Grandfather SOFT loophole closed in `check_agents_laws_name_their_enforcer`.

---

## Adversarial findings (blocking)

### F1 — Scheduled task still broken (RC-70/97 not done)
`schtasks` **Task To Run** is still the inline `set PYTHONUTF8=1 && python ...` chain.  
**Last Result still 1.** Bat file is not pointed at by the task. Shipping a `.bat` without rewiring the host task is the same class as "built the tool, forgot the consumer."

### F2 — Fresh run still fails the consumer (UTC date bug)
Auditor ran the bat (exit 0). New `generated_utc=2026-07-28T01:19:43+00:00`.  
`/api/terrain/scorecard` still returned:
```json
{"stale": true, "age_trading_days": null, "stale_reason": "scorecard has not been regenerated"}
```
Cause: `scorecard_trading_day_age` uses `str(generated_utc)[:10]` (UTC calendar day). After ~19:00 CT the UTC date is **tomorrow** vs `now_et().date()`, so `gen > today` → `None` → treated as unusable/stale. A successful evening run is fail-closed as if never regenerated. **Producer can be green and coach still silent.**

### F3 — Scorecard content quality
Manual bat run scored **0 ticker-days** / 0 hit-rates for regime tables; wall-hold n=1/2. Launcher success ≠ useful coach measurement. Do not close RC-70 on exit code alone.

### F4 — Inert-log check still red (and should be until cleared)
`scheduled_producers_are_not_inert` → 1 violation (old fatals still in `scorecard_run.log`). Fine as a finding; not a finish.

### F5 — RC-96 still OPEN
Creating the missing row does not close the defect. Close only after proof + crosswalk, or keep OPEN honestly — do not say finished.

### F6 — Work not committed
Finish claim with dirty tree and untracked launcher is not a deliverable.

---

## Required before finish may be accepted

1. Point `\EdTerrainScorecard` at `tools\run_terrain_scorecard.bat` (or equivalent quoted launcher). Prove `Last Result = 0` from **the task**, not a manual agent run.
2. Fix `scorecard_trading_day_age` to use **ET trading date** of the stamp (not UTC `[:10]`), with a test for post-19:00 CT generation.
3. Clear/rotate `scorecard_run.log` after a proven good run; gate green.
4. Close RC-70/97 only with MEASURED: task result 0, JSON mtime, API `stale:false` with real figures, END-TO-END.
5. RC-12: measure or leave OPEN — do not ignore.
6. RC-96: close properly or stay OPEN; stop claiming finished.
7. RC-43: reconcile STATUS vs FIX.
8. Commit the real fix set.

**One-liner:** Progress on diagnosis and SOFT labeling; end-to-end scorecard still broken (task not rewired + UTC age bug); lock set still 2 open. **Reject finish.**
