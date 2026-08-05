# Host Scheduled Jobs — the single visible inventory

**Closes OPEN_ITEMS `FIND-SCHEDULED-JOBS-VISIBILITY`** (agent-registered Windows tasks ran outside
any app surface; the operator discovered them by accident). This file is the documented inventory
that item demanded: name, schedule, command, log path — measured from the live host with
`Get-ScheduledTask` / `Get-ScheduledTaskInfo` on 2026-07-27, not recalled.

**Standing rule (from the item, now the contract of this file):** creating, rewiring, or removing
a host scheduled task REQUIRES updating this inventory in the same change. A task that is not in
this file is an incident, not a convenience. Paths are written `<REPO>` = the repository root;
absolute operator-home paths never appear in tracked files (credential-leak hook, RC-89/RC-101).

| Task | Schedule | Command | Log | Last verified |
|---|---|---|---|---|
| `EdTerrainScorecard` | Weekdays 16:45 ET | `cmd /c "<REPO>\tools\run_terrain_scorecard.bat"` (quoted-set PYTHONUTF8, venv-parity enforced inside the bat) | `reports/scorecard_run.log` (gitignored; scanned by `check_scheduled_producers_are_not_inert`) | 2026-08-04 — Last Result **3221225786** (was 0 on 2026-07-27); see *Terminated-mid-run reading* below |
| `EdConsole Stream Capture` | Daily 08:25 ET, 405 min | `cmd /c cd /d <REPO> && python tools\run_stream_capture.py --symbols SPY,QQQ,IWM --duration-min 405` | `data/stream_capture.lock` owner + `reports/stream_capture_status.json` | 2026-08-04 — Last Result **3221225786** (was 0 on 2026-07-27) |
| `EdWebConsole Daily Scoreboard` | Daily 15:35 ET | `powershell -NoProfile -ExecutionPolicy Bypass -File <REPO>\tools\run_daily_scoreboard.ps1` | per-script | 2026-08-04 — Last Result **3221225786** (was 0 on 2026-07-27) |
| `EdMondayDebtWake` | weekly wake | (registered outside this inventory before the standing rule) | `reports/_wake/` | 2026-08-04 — Last Result **0** |
| `EdRthCompletenessCheck` | daily | (registered outside this inventory before the standing rule) | per-script | 2026-08-04 — Last Result **3221225786** |

### Terminated-mid-run reading (measured 2026-08-04, not diagnosed)

Three rows that read Last Result **0** on 2026-07-27 now read **3221225786** = `0xC000013A`
= `STATUS_CONTROL_C_EXIT` — the process was **terminated**, not failed on its own logic. The
common cause is the host sleeping or shutting down while the task was still running; the 08:25
capture legitimately runs 405 minutes and would be caught by any afternoon shutdown.

This is recorded as a MEASUREMENT, not a verdict. It is **not** the scheduled-but-inert defect
class (those tasks reported success while producing nothing — the inverse). Closing it needs a
run-log read per task, which belongs to its own row, not to the TQM change that measured it.
Left visible here rather than quietly refreshing the dates, because a table that still claimed
"Last Result 0" while this turn's `Get-ScheduledTaskInfo` said otherwise is the precise failure
this inventory exists to prevent.

## NOT SCHEDULED — the advisory-debt / TQM runner (RC-250 → RC-251, honest gap)

`tools/rehab_daily_scan.py` runs the full MEASURE + TRIAGE pass: it invokes
`-m tools.check_institutional_correctness --advisory`, refreshes
`reports/advisory_debt_latest.json` (per-check tally **and** per-file hotspots), builds the
bounded queue in `reports/tqm_queue_latest.json`, and raises a P1 finding when the report is
missing or older than 48 h. Proven same-turn 2026-08-04:
`advisory_total 3,360 across 7 checks; TQM queue 5 items (cap 5)`.

**There is no host task that calls it.** Measured 2026-08-04 with `Get-ScheduledTask`: the host
carries the five `Ed*` tasks in the table above and nothing for the rehab scan. So P1's bargain
(RC-246 moved 7 ADVISORY checks off pre-commit for 145 s/commit **on condition** they surface
daily) is still only half kept: the loop exists, the clock does not.

This section says NOT SCHEDULED deliberately. Writing the row as if it fired is the exact
scheduled-but-inert lie recorded below for `EdTerrainScorecard` — a table that claims coverage
is worse than one that admits a hole.

| Task | Schedule | Command | Log | State |
|---|---|---|---|---|
| `EdRehabDailyScan` | **not created** | `powershell -NoProfile -ExecutionPolicy Bypass -File <REPO>\tools\run_rehab_daily.ps1` | `reports/rehab_latest.md` + `reports/tqm_queue_latest.json` + `reports/advisory_debt_latest.json` | **ABSENT from the host** — registering a Windows task is an operator action; agents do not create host schedules |

Operator registration (one line, then this row moves to the table above with a verified date):

```powershell
schtasks /Create /TN "EdRehabDailyScan" /TR "powershell -NoProfile -ExecutionPolicy Bypass -File '<REPO>\tools\run_rehab_daily.ps1'" /SC DAILY /ST 18:30 /F
```

The command deliberately calls the **repo launcher**, not an inline interpreter path. The
launcher resolves the venv (with a loud warning if it is missing) and surfaces a non-zero exit as
an error, so a broken run is visible instead of silent. That is the lesson of the defect history
below: an inline `/TR` string lives only in the Task Scheduler UI, where it cannot be reviewed,
diffed, or tested. `test_rc251_launcher_is_the_canonical_entry_point` pins the launcher's two
load-bearing properties.

Until the task exists, advisory debt and the TQM queue are visible only when someone runs the
scan by hand — precisely the condition RC-250 was opened for.

## Known defect history this inventory exists to prevent

- `EdTerrainScorecard` ran an inline `set PYTHONUTF8=1 &&` for weeks — cmd assigned `"1 "` with a
  trailing space, Python died at PRE-INIT, and the task reported "scheduled" while producing
  nothing (RC-97: scheduled-but-inert is worse than unscheduled, because the ledger looks
  covered). It also called bare `python` (venv-parity violation) and fired at 15:30 ET — before
  the close — so no run could ever score a complete session. All three defects were invisible
  precisely because the task definition lived outside version control and outside any inventory.
- The launcher is now `tools/run_terrain_scorecard.bat`, in the repo, reviewed, with the quoting
  and parity checks inside it. `check_scheduled_producers_are_not_inert` (ENFORCED) fails the
  gate when any `reports/*_run.log` ends in a fatal — a silent producer plus a fail-closed
  consumer reads exactly like a quiet system, and only a log-scanning lock breaks that.

## Re-verify (the whole table, any time)

```bash
powershell -NoProfile -Command "Get-ScheduledTask | ? {$_.TaskName -like 'Ed*'} | % { $i = Get-ScheduledTaskInfo -TaskName $_.TaskName -ErrorAction SilentlyContinue; '{0}  state={1}  lastResult={2}' -f $_.TaskName, $_.State, $i.LastTaskResult }"
```
