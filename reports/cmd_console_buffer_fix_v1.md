# CMD console buffer fix v1

Date: 2026-08-02

## Goal
Raise Screen Buffer Height so the Ed Console scrolling cmd window can retain uvicorn warnings/tracebacks (operator could not scroll back).

## Live PIDs (confirmed this turn)
| Role | PID | Notes |
|------|-----|-------|
| cmd (`start_ed_console.bat`) | 21172 | scrolling window owner |
| conhost | 28728 | child of 21172 |
| uvicorn :8000 | 31344 | child of 21172; **not restarted** |
| Claude uvicorn :8777 | 21748 | **left alone** |

## Durable defaults (HKCU registry)
Set on `HKCU:\Console` and cmd-specific subkeys:
- `ScreenBufferSize` = `0x270F0078` (width **120**, height **9999**)
- `WindowSize` = `0x00320078` (width **120**, height **50** — window stays on-screen; buffer height enables scrollback)

Keys updated:
- `HKCU:\Console` (root defaults)
- `HKCU:\Console\%SystemRoot%_system32_cmd.exe`
- `HKCU:\Console\%SystemRoot%_SysWOW64_cmd.exe`
- `HKCU:\Console\%SystemRoot%_Sysnative_cmd.exe`
- `HKCU:\Console\C:_Windows_System32_cmd.exe`

Accidental junk keys from a path-split (`C:_WINDOWS`, `_system32_cmd.exe`) were removed.

## Live window (no restart)
Applied via brief `AttachConsole(21172)` + `CreateFile(CONOUT$)` + `SetConsoleScreenBufferSize` + `FreeConsole`.
- Before: **120 x 30**
- After: **120 x 9999** (window height unchanged ~30 lines)
- uvicorn PIDs were not killed or signaled.

## Next-launch (`start_ed_console.bat`)
After `cd /d "%~dp0"`:

```bat
mode con: cols=120 lines=9999 >nul 2>&1
```

So future launches get a tall buffer even if registry defaults differ.

## How to verify
1. Focus the Ed Console cmd window (title **Ed Console**, :8000).
2. Scroll the vertical scrollbar **up** — older lines (including prior warnings) should remain going forward; new output will accumulate in the tall buffer.
3. Optional: right-click title bar → **Properties** → **Layout** → Screen Buffer Height should show **9999**.
4. New launches via `start_ed_console.bat` pick up `mode con` automatically.

## Restart policy
No console/uvicorn restart was performed. Claude :8777 untouched.

## Live apply evidence

```json
{
  "before": "buf=120x30 winH=30 winW=120",
  "targetPid": 21172,
  "liveApplied": true,
  "after": "buf=120x9999 winH=30 winW=120"
}
```
