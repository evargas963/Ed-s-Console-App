# Host scheduled jobs -- the inventory

Measured on the production host with `Get-ScheduledTask` on 2026-09-26: **no `Ed*` scheduled
tasks exist.** Nothing runs on a timer.

What runs, and who starts it:

| Process | Started by | Command |
|---|---|---|
| Console (`uvicorn server:app`, port 8000) | `start_ed_console.bat` | `.venv\Scripts\python.exe -m uvicorn server:app --host 0.0.0.0 --port 8000` |
| Capture daemon (the one Schwab stream, port 8800) | `start_ed_console.bat`, when :8800 is not already serving | `start_capture_daemon.bat` -> `.venv\Scripts\pythonw.exe -m app.market_data.schwab.streaming.capture` |

Standing rule: creating, changing or removing a host scheduled task updates this file in the
same change, measured from the host, not recalled.

Re-verify:

```bash
powershell -NoProfile -Command "Get-ScheduledTask | ? {$_.TaskName -like 'Ed*'} | % { $i = Get-ScheduledTaskInfo -TaskName $_.TaskName -ErrorAction SilentlyContinue; '{0}  state={1}  lastResult={2}' -f $_.TaskName, $_.State, $i.LastTaskResult }"
```
