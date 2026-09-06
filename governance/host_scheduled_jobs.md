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
| `EdConsole Stream Capture` | Weekdays 08:25 ET, duration 0; same-task 1-min repetition for 12h (IgnoreNew; StopAtDurationEnd=false); ExecutionTimeLimit unlimited | `<REPO>\.venv\Scripts\pythonw.exe -m app.market_data.schwab.streaming.capture --symbols SPY,QQQ,IWM --duration-min 0` (WorkingDirectory=<REPO>) | DB-adjacent `stream_capture.lock` + heartbeat in `stream_capture.db` | 2026-09-04 — pythonw + -m app.market_data.schwab.streaming.capture; one owner; no watchdog |
| `EdWebConsole Daily Scoreboard` | Daily 15:35 ET | `powershell -NoProfile -ExecutionPolicy Bypass -File <REPO>\tools\run_daily_scoreboard.ps1` | per-script | 2026-08-04 — Last Result **3221225786** (was 0 on 2026-07-27) |
| ~~`EdMondayDebtWake`~~ | RETIRED | ~~`powershell.exe ... run_monday_debt_wake.ps1`~~ (repo script + `reports/_wake/` markers deleted 2026-08-25, audit round 2 — a one-shot 2026-08-03 alarm re-firing weekly against dead work orders) | `reports/_wake/` (deleted) | **2026-08-25 — DELETED from host by operator** (`schtasks /Delete /TN "EdMondayDebtWake" /F`); verified ABSENT via `Get-ScheduledTask`. Tombstone kept per this file's honest-record rule. |
| `EdRehabDailyScan` | Daily 18:30 | `powershell.exe -NoProfile -ExecutionPolicy Bypass -File "<REPO>\tools\run_rehab_daily.ps1"` (repo launcher, venv parity + non-zero exit surfaced inside it) | `reports/rehab_latest.md` + `reports/tqm_queue_latest.json` + `reports/advisory_debt_latest.json` | 2026-08-05 — registered by the PM; **PROVEN BY EXECUTION, not by registration**: triggered on demand, Last Result **0**, LastRunTime 04:53:24, and all three artifacts advanced 04:10 → 04:59 with the queue reading 3367/prior 3367/delta 0 across 5 items |
| `EdRthCompletenessCheck` | daily | `<REPO>\.venv\Scripts\pythonw.exe <REPO>\tools\rth_completeness_check_v1.py --db <REPO>\data\ed_console.db --backfill` (**pythonw**, not python — the tool now leaves a durable final record, so a windowless run loses no visibility; re-registration command below) | `reports/rth_validation/rth_completeness_latest.json` (durable final record, written on EVERY exit path; fail-closed exit 0/1/2, plus **3** if the record cannot be persisted — no silent success under pythonw) | 2026-08-28 — observability root-fixed (durable record + progress + `completion_path`); **operator to re-register with `pythonw` per the command below**. Prior `python.exe` form measured 2026-08-25 Ready; 2026-08-04 Last Result was **3221225786** |
| ~~`EdConsole Stream Capture Watchdog`~~ | RETIRED | ~~`<REPO>\tools\ensure_stream_capture.bat`~~ (custom poll that reported `started` after Popen without proving lock/heartbeat) | — | **2026-09-03 — DELETED from host**; `EdConsole Stream Capture` is the one owner |
| `EdConsoleLivenessWatch` | Every 5 min | `<REPO>\.venv\Scripts\pythonw.exe <REPO>\tools\console_liveness_check.py --db <REPO>\data\ed_console.db` (**pythonw**, not python — the console `python.exe` flashed a CMD window every 5 min; `_emit` guards its now-console-less `print`, the file log + non-zero exit are unchanged) | `reports/console_liveness_run.log` (scanned by `check_scheduled_producers_are_not_inert`) | 2026-08-25 — **REGISTERED + verified Ready**; first form used `python.exe` (visible window). Re-register with `pythonw` per the command below. Tool proven on-demand: OK outside the window, DEAD-PRODUCER alert inside it |

## 2026-08-28 — `EdRthCompletenessCheck` observability root-fix

The check printed `HOLES total_missing=…` as its first line and persisted nothing, so after the
scheduled window closed the operator had no durable way to see the run actually ENDED a pass
(`LastTaskResult=0` reached via successful backfill, or vendor reconciliation with zero real loss).
`tools/rth_completeness_check_v1.py` now writes ONE durable final record —
`reports/rth_validation/rth_completeness_latest.json` — on EVERY exit path, carrying `final_status`,
`completion_path` (INITIAL_COMPLETENESS / SUCCESSFUL_BACKFILL / VENDOR_RECONCILED_ZERO_LOSS /
LOST_DATA / HOLES_NO_BACKFILL / MEASUREMENT_FAILED / NO_SESSION), `grid_missing`, `lost_vs_vendor`,
`backfill_exit`, the ordered progress `steps`, and `exit_code`. Progress also streams to stderr so
`HOLES` reads as an intermediate step, never the verdict. Fail-closed exit codes: 0 = complete /
no-session; 1 = holes stand or real vendor loss; 2 = unmeasurable, never a pass (RC-57); **3 = the
verdict was reached but its durable record could not be persisted** — under pythonw (no console) a
0-verdict run whose artifact fails to write would otherwise be a silent success, so persistence
failure is itself a non-zero exit. No new checker/ledger/registry/governance file; the record is a
run report in the existing `reports/rth_validation/` location.

Because everything durable now lives in that artifact, the task runs windowless via **pythonw.exe**
(no CMD flash), the same fix EdConsoleLivenessWatch used. `/Change /TR` updates only the action, so
the operator's existing daily trigger is preserved:

```powershell
schtasks /Change /TN "EdRthCompletenessCheck" /TR "'<REPO>\.venv\Scripts\pythonw.exe' '<REPO>\tools\rth_completeness_check_v1.py' --db '<REPO>\data\ed_console.db' --backfill"
```

After re-registering, the operator reads the run's outcome from the durable artifact (and the task's
own `Last Result`), not from a transient console line.

## RESOLVED 2026-08-25 — console + producer liveness watch (RC-481 / RC-479)

`tools/console_liveness_check.py` reads the production DB read-only and, during a trading
day inside 09:30-close+15min ET, ALERTs (non-zero exit + a line in
`reports/console_liveness_run.log`) when EITHER the console is down/stalled (newest
`snapshots.ts_utc` older than 10 min) OR the model producer is dead (collection live but
`mc_paths` NULL across the last 15 min — the RC-479 signature, distinguished from designed
abstention). Validated on demand 2026-08-25: against the live DB it returns the DEAD
PRODUCER alert, matching the measured mc_* outage. This is stronger than the `/api/health`
ping (whose `logger_running` flag is True even when every fetch fails), because it measures
COLLECTION, not process existence — no in-process change, no heartbeat table, no framework.

| Task | Schedule | Command | Log | State |
|---|---|---|---|---|
| `EdConsoleLivenessWatch` | Every 5 min | `<REPO>\.venv\Scripts\python.exe <REPO>\tools\console_liveness_check.py --db <REPO>\data\ed_console.db` | `reports/console_liveness_run.log` (scanned by `check_scheduled_producers_are_not_inert`) | **REGISTERED 2026-08-25** by the operator (`schtasks /Create ... /SC MINUTE /MO 5 /F`); now Ready — see the live table above. Row kept as the registration record. |

Operator registration — uses **pythonw.exe** (the windowless interpreter) so the 5-minute run does
NOT flash a CMD window. `/Create /F` overwrites the existing python.exe registration in place:

```powershell
schtasks /Create /TN "EdConsoleLivenessWatch" /TR "'<REPO>\.venv\Scripts\pythonw.exe' '<REPO>\tools\console_liveness_check.py' --db '<REPO>\data\ed_console.db'" /SC MINUTE /MO 5 /F
```

Same-day visibility comes from the task's own non-zero `Last Result` (the re-verify one-liner
at the bottom of this file) and the fatal line in the run log; the existing
`check_scheduled_producers_are_not_inert` gate is the commit-time backstop.

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

## RESOLVED 2026-08-05 — the advisory-debt / TQM runner is now scheduled AND proven to run

The section below is kept as written, with this heading correcting it, because the honest
record of a gap is worth more than a tidy file. `EdRehabDailyScan` now exists (see the table
above), calls the repo launcher rather than an inline command, and — the part that matters —
was **executed on demand and observed to complete**: Last Result 0 and all three artifacts
advanced. Registration alone would have proven nothing; that is the `EdTerrainScorecard`
lesson recorded at the bottom of this file, where a task reported "scheduled" for weeks while
producing nothing.

### The gap as it stood, 2026-08-04 (historical)

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


## 2026-09-04 — windowless capture owner

The one stream task now launches ``pythonw.exe -m app.market_data.schwab.streaming.capture``. ``pythonw`` is the same windowless interpreter already used by ``EdRthCompletenessCheck`` and ``EdConsoleLivenessWatch``. No BAT, no second task, no watchdog. ``IgnoreNew`` still refuses a second StreamClient. After merge, retarget WorkingDirectory to the production checkout.

## 2026-09-03 — native host lifecycle is the one stream process owner

One Windows task, `EdConsole Stream Capture`, owns the duration-0 daemon. `ExecutionTimeLimit` is unlimited so the 72-hour default cannot kill it. `MultipleInstancesPolicy` is IgnoreNew — a second start does not open a second StreamClient. The weekday 08:25 trigger repeats every 1 minute for 12 hours and does not stop the running process when that window ends: if the process is alive the repeat is ignored; if it has died the same task starts it again. `RestartOnFailure` is kept for fail-to-launch only — Task Scheduler does not treat a started process's later exit as a task-start failure. The daemon still refuses a second owner via the DB-adjacent lock, and still recycles a half-open socket internally during a capturable session. The 1-minute custom watchdog (`ensure_stream_capture.py` / `.bat` / `stream_watchdog.py`) is deleted: it reported `started` after `Popen` without proving lock, survival, or a fresh heartbeat. No second task or supervisor is registered.

## 2026-08-30 — `EdConsole Stream Capture` becomes the SOLE Schwab streaming authority

The command line, schedule, and lock/log paths are UNCHANGED — no task edit was made. What changed
is inside `tools/run_stream_capture.py`: it is now also the sole source for the live UI's book/L1
feed. `order_flow_streaming.py` used to open a SECOND, independent `schwab.streaming.StreamClient`
at server startup — proven still-open by `tools/check_single_stream_authority.py`'s repo-wide
census before this fix (2 production constructors; census now enforces exactly 1). That module now
reads this daemon's `stream_capture.db` read-only; the daemon additionally captures NASDAQ_BOOK /
NYSE_BOOK for whichever ONE symbol the server signals as the active UI ticker
(`data/stream_active_ticker.json`, polled ~1s), and stores native-fidelity quote content
(`stream_quotes_raw.native_json`) alongside the existing flattened columns. No new host
configuration is required — the server and this task already run on the same host and share
`data/`.

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
