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
| `EdTerrainScorecard` | Weekdays 16:45 ET | `cmd /c "<REPO>\tools\run_terrain_scorecard.bat"` (quoted-set PYTHONUTF8, venv-parity enforced inside the bat) | `reports/scorecard_run.log` (gitignored; scanned by `check_scheduled_producers_are_not_inert`) | 2026-07-27 — Last Result **0**, artifact mtime advanced, API `stale:false` (RC-70/RC-97) |
| `EdConsole Stream Capture` | Daily 08:25 ET, 405 min | `cmd /c cd /d <REPO> && python tools\run_stream_capture.py --symbols SPY,QQQ,IWM --duration-min 405` | `data/stream_capture.lock` owner + `reports/stream_capture_status.json` | 2026-07-27 — Last Result **0** |
| `EdWebConsole Daily Scoreboard` | Daily 15:35 ET | `powershell -NoProfile -ExecutionPolicy Bypass -File <REPO>\tools\run_daily_scoreboard.ps1` | per-script | 2026-07-27 — Last Result **0** |

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
