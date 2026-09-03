@echo off
title Ed Console
cd /d "%~dp0"

echo.
echo  ============================================
echo   Ed Console - Starting...
echo  ============================================
echo.

REM RC-497: deterministic interpreter. The desk launches ONLY through the repo
REM .venv Python. Bare PATH `python`/`pip` is forbidden here: in a spawned or
REM scheduled context (Start-Process, Task Scheduler) `python` resolves to a
REM different interpreter with no uvicorn, so the old launcher silently no-opped
REM (proven 2026-08-27). No launch-time `pip install` either -- installing into an
REM ambiguous environment at launch is the non-determinism we are removing.
set "VENV_PY=%~dp0.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
    echo  ERROR: repo virtualenv interpreter not found at "%VENV_PY%".
    echo  Create it:  python -m venv .venv  then  .venv\Scripts\python -m pip install -r requirements.txt
    pause
    exit /b 1
)

REM RC-513: is this checkout actually PROVISIONED, not just "does uvicorn import".
REM MEASURED 2026-09-03: the desk refused to launch with "SCHWAB_API_KEY /
REM SCHWAB_APP_SECRET missing after sanitize" while .env held both keys. dotenv was
REM missing, config._load_dotenv_if_present() swallows ImportError by design, and the
REM canonical load silently became a no-op -- a broken virtualenv wearing the face of
REM absent credentials. It stayed invisible because python_dotenv-1.2.2.dist-info was
REM still present with no dotenv/ package: importlib.metadata, pip and a full
REM requirements.txt audit all reported 22 of 22 SATISFIED. A second ghost,
REM python-dateutil, was breaking `import pandas` at the same time. The old probe here
REM asked only whether uvicorn imports, which both ghosts passed.
"%VENV_PY%" runtime_preflight.py
if errorlevel 1 (
    echo  LAUNCH BLOCKED: the repo virtualenv is not provisioned to run this app.
    echo  The report above names each distribution and the repair command.
    pause
    exit /b 1
)

echo  Starting server at http://localhost:8000
echo  Press Ctrl+C to stop.
echo  (CWD set to script dir - token path resolves from app dir)
echo  Ops panel /Run tasks/ click-to-run: ON  (localhost only unless ED_OPS_ALLOW_REMOTE=1)
echo  Opening Microsoft Edge to http://localhost:8000 in a few seconds...
echo.

set ED_OPS_RUNNER=1
set ED_CALIBRATION_LOG=1

REM Strip inherited CI/test contamination from parent shells (agent / pytest).
REM Proven 2026-08-29: launching with ED_CI_OFFLINE=1 left /api/health=200 while
REM analytics bg failed every ticker (Schwab CI offline RuntimeError). Clear first,
REM then fail-closed if live Schwab would still be blocked.
REM RC-512: this preflight is APP RUNTIME, not governance - it asks whether live Schwab
REM calls will work, which is a precondition of data collection. It moved from tools\ to
REM the app root with that ownership, so the launch path executes nothing out of the
REM governance tools directory.
REM RC-514: SANITIZE ALWAYS, NEVER VETO THE APPLICATION. The --bat-unsets/--sanitize pair
REM below is unchanged and still strips inherited CI/test contamination before uvicorn.
REM What changed is the consequence of a bad result. This used to `exit /b 1`, which made one
REM vendor's credentials decide whether Ed Console may exist. MEASURED 2026-09-03: a ghost
REM python-dotenv distribution made .env unloadable (RC-513) and the desk would not start,
REM while the API, UI, health and observability were all perfectly able to run.
REM docs/ARCHITECTURE.md section 4: Schwab unavailable degrades the CAPABILITY and fails
REM Schwab-dependent exposure closed; it does not kill the app. Fail-closed enforcement is
REM config.schwab_live_blocked_for() plus the two refusal sites in schwab_client -- not this
REM launcher, which only reports.
for /f "delims=" %%L in ('"%VENV_PY%" live_schwab_env.py --bat-unsets') do %%L
"%VENV_PY%" live_schwab_env.py --sanitize
if errorlevel 1 (
    echo.
    echo  ============================================================
    echo   SCHWAB CAPABILITY UNAVAILABLE - starting anyway.
    echo   API, UI, health and observability come up normally.
    echo   Live Schwab collection will NOT run, and Schwab-dependent
    echo   decisions fail closed. No fabricated or stale substitute.
    echo   Reasons are printed above; /api/health reports the state.
    echo  ============================================================
    echo.
)

REM RC-512 (operator mission 2026-09-03, DECOUPLE GOVERNANCE FROM APP RUNTIME): the
REM RC-350 ONE-APP LOCK call is no longer on the launch path. It asserted repository
REM state - branch==main, HEAD==origin/main zero-ahead AND zero-behind, no uncommitted
REM app file - and began with `git fetch origin main`, so desk availability depended on
REM git position and on reaching a remote. MEASURED 2026-09-03: the production checkout
REM was 9 commits behind origin/main and this line aborted the launcher, with no app
REM defect of any kind.
REM
REM The invariant is not lost and this was never its only enforcement: an agent is
REM PREVENTED from moving, committing to, or editing app code in the production checkout
REM by tools/process_lock_guard.py on every PreToolUse event. Repository lineage is an
REM agent/commit/merge concern and stays there; it does not decide whether the desk runs.
REM Operator-side lineage remains readable on demand:
REM     .venv\Scripts\python.exe tools\check_live_path_is_main.py

REM Stop any prior instance still bound to port 8000 (plain-line for /f - safe batch syntax)
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do taskkill /F /PID %%P 2>nul

REM RC-497 FAIL CLOSED: the stop above is best-effort (taskkill can fail on a
REM privileged/foreign-owned PID, or the socket can still be held). Give it a
REM moment, then PROVE port 8000 is actually free before launching. If anything
REM still answers on 8000, refuse rather than launch a second uvicorn into an
REM occupied port and hand the operator an ambiguous "which server am I on?"
timeout /t 1 /nobreak >nul
"%VENV_PY%" -c "import socket,sys; s=socket.socket(); s.settimeout(1); sys.exit(1 if s.connect_ex(('127.0.0.1',8000))==0 else 0)"
if errorlevel 1 (
    echo  LAUNCH BLOCKED: port 8000 is still occupied after the stop attempt.
    echo  Refusing to launch a second server into an occupied port. Stop the
    echo  process holding 8000, then relaunch.  ^(netstat -ano ^| findstr :8000^)
    pause
    exit /b 1
)

set "PF86=%ProgramFiles(x86)%"
set "EDGE_EXE=%PF86%\Microsoft\Edge\Application\msedge.exe"
if not exist "%EDGE_EXE%" set "EDGE_EXE=%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"

REM Original working pattern: delayed open in background subprocess (Edge only, not Chrome)
start "" cmd /c "timeout /t 2 /nobreak >nul & "%EDGE_EXE%" http://localhost:8000"

REM --timeout-graceful-shutdown: Ctrl+C must terminate even while browser tabs
REM hold SSE streams open (uvicorn's default waits forever for them to close).
"%VENV_PY%" -m uvicorn server:app --host 0.0.0.0 --port 8000 --timeout-graceful-shutdown 10

echo.
echo  Server stopped.
pause
