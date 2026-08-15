@echo off
setlocal
REM RC-70 / RC-97 daily terrain scorecard launcher.
REM
REM WHY THIS FILE EXISTS.
REM The scheduled task used an inline chain that set PYTHONUTF8 before calling python. In cmd,
REM everything between the equals sign and the command separator becomes the VALUE, so the
REM variable was set to "1 " with a trailing space. Python rejects that at PRE-INIT with
REM   Fatal Python error: preconfig_init_utf8_mode: invalid PYTHONUTF8 environment variable value
REM which happens before any Python code runs, so no in-script guard could ever reach it.
REM MEASURED 2026-07-27: the run log carried that fatal and the artifact was 119.4h stale while
REM the task still reported as scheduled. Scheduled-but-inert is worse than unscheduled: the
REM ledger looks covered.
REM
REM Quoted assignment cannot take a trailing space, and the quoting now lives in version control
REM rather than in a task definition nobody reviews.
REM
REM CMD HAZARDS THIS FILE DELIBERATELY AVOIDS, both self-inflicted on the first version:
REM   1. no command separators inside REM lines. cmd still parses them and runs the tail.
REM   2. plain ASCII only. A non-ASCII dash in a comment was split into a bogus token.
REM Symptom was: "-70 is not recognized" plus "was unexpected at this time", exit 255.

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

cd /d "%~dp0.."
if errorlevel 1 (
  echo [scorecard] FATAL cannot cd to repo root from %~dp0
  exit /b 2
)

REM venv parity: the institutional gate requires the repo interpreter, never a system python.
REM The old task action called bare "python", which was a parity violation in the one job that
REM produces coach data.
if not exist ".venv\Scripts\python.exe" (
  echo [scorecard] FATAL .venv\Scripts\python.exe missing, refusing to run on a system python
  exit /b 3
)

echo [scorecard] start %DATE% %TIME%
".venv\Scripts\python.exe" tools\terrain_backtest_report_v1.py
set "RC=%ERRORLEVEL%"
echo [scorecard] exit=%RC% %DATE% %TIME%
exit /b %RC%
