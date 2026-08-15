# BRUTAL ADVERSARIAL AUDIT v3 — Claude "finished" again (2026-07-27 ~20:32 CT)

**Verdict: REJECT FINISH CLAIM. Partial mechanical progress on scorecard — governance not closed.**

---

## Headline

Saying "finished" while **7 RCs remain OPEN** (including lock-set RC-12 + RC-70) and the fix tree is **uncommitted** is false-completion.

Measured lock monitor: **33/35** still; open lock-set **RC-12, RC-70**.

---

## What actually improved (credit)

| Item | Evidence | Grade |
|---|---|---|
| Scorecard task rewired to bat | `Task To Run` → `tools\run_terrain_scorecard.bat`; Last Run 20:28; **Last Result = 0** | FIXED ( mechanized path ) |
| UTC→ET age bug | `scorecard_trading_day_age('2026-07-28T01:19:43+00:00')` → **0**; API `stale:false`, `age_trading_days:0` | FIXED (verified this turn) |
| Inert producer check | `scheduled_producers_are_not_inert` → **0** violations | PASS now |
| AGENTS SOFT labels | dirty tree | PARTIAL |

---

## Why finish is still rejected

1. **RC-70 / RC-97 still OPEN** — producer works; rows not closed with MEASURED END-TO-END / VIOLATION / TIGHTENED. Fix cells still stubs (`tools/terrain_backtest_report_v1.py`, `tools/run_terrain_scorecard.bat`).
2. **RC-96 still OPEN** — row exists; defect not closed.
3. **RC-12 still OPEN** — untouched; lock-set incomplete.
4. **RC-98 phantom** — `server.py` cites RC-98; **no `| RC-98 |` row** in root_cause_log (same class as the RC-96 audit finding).
5. **RC-43** still OPEN with FIX text saying CLOSED — hygiene fail.
6. **RC-31, RC-58** still OPEN.
7. **Nothing committed** — no commit after `0a3d2c7a`; finish without a landable commit is not a deliverable.
8. **Coach quality caveats** — API serves `wall_hold_trusted` with **call_n=1, put_n=2**. Launcher green ≠ statistically useful scorecard. Do not overclaim "coach fixed."

---

## Paste to Claude

```
REJECT FINISH.

You fixed the scorecard PRODUCER path (task→bat, Last Result 0) and the ET age bug
(API stale:false). That is real. It is NOT "finished."

STILL OPEN: RC-12, RC-31, RC-43, RC-58, RC-70, RC-96, RC-97
MISSING ROW: RC-98 (cited in server.py, absent from root_cause_log)
UNCOMMITTED: AGENTS.md, server.py, check_institutional_correctness.py, bat, RC log

REQUIRED BEFORE FINISH:
1. Close RC-70 + RC-97 with MEASURED proof (task Last Result 0, JSON mtime, API stale:false)
   + VIOLATION/TIGHTENED — or keep OPEN honestly.
2. Add RC-98 row OR stop citing RC-98.
3. Close or properly leave OPEN RC-96 with proof.
4. RC-12: measure SPY/QQQ confidence/span or leave OPEN — do not ignore in a finish claim.
5. Reconcile RC-43 STATUS vs FIX.
6. Commit the real fix set.
7. Do not say finished while lock-set open count > 0 unless operator scoped "scorecard-only."
```
