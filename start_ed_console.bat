@echo off
title Ed Console
cd /d "%~dp0"

echo.
echo  ============================================
echo   Ed Console - Starting...
echo  ============================================
echo.

REM The app runs only on the repo's .venv Python.
set "VENV_PY=%~dp0.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
    echo  ERROR: repo virtualenv interpreter not found at "%VENV_PY%".
    echo  Create it:  python -m venv .venv  then  .venv\Scripts\python -m pip install -r requirements.txt
    pause
    exit /b 1
)

REM Every required distribution imports in the .venv, or the launch stops with the repair command.
"%VENV_PY%" runtime_preflight.py
if errorlevel 1 (
    echo  LAUNCH BLOCKED: the repo virtualenv is not provisioned to run this app.
    echo  The report above names each distribution and the repair command.
    pause
    exit /b 1
)

REM The capture daemon (Schwab stream -> every live price, :8800) is its own process in its own
REM window (start_capture_daemon.bat: restarts it if it dies). Started here unless one is
REM already serving :8800. Closing THIS window does not stop it -- capture keeps running.
netstat -ano | findstr /R /C:":8800 .*LISTENING" >nul
if errorlevel 1 (
    start "Ed Capture Daemon" /min "%~dp0start_capture_daemon.bat"
    echo  Capture daemon: started in its own window ^("Ed Capture Daemon"^).
) else (
    echo  Capture daemon: already running ^(:8800 is serving^).
)
echo.
echo  Starting server at http://localhost:8000/
echo  Press Ctrl+C to stop.
echo  (CWD set to script dir - token path resolves from app dir)
echo.

REM Clear test settings inherited from the parent shell (ED_CI_OFFLINE and the like), then
REM report whether live Schwab calls will work; a bad result is reported and the app still starts.
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


REM Stop any prior instance on port 8000: only a process whose own command line names an Ed
REM Console server (uvicorn ... server:app) is stopped; anything else on the port is reported.
"%VENV_PY%" "%~dp0launcher_port_guard.py" 8000
if errorlevel 2 (
    echo  LAUNCH BLOCKED: could not determine whether port 8000 is free ^(see
    echo  warning above^). Refusing to guess and launch into a possibly-occupied
    echo  port. Check manually:  netstat -ano ^| findstr :8000
    pause
    exit /b 1
)
if errorlevel 1 (
    echo  LAUNCH BLOCKED: port 8000 is occupied by something that is not an Ed
    echo  Console server ^(see warning above^). Refusing to launch into it, and
    echo  refusing to kill a process this launcher does not recognize.
    pause
    exit /b 1
)

REM Report a developer-preview server on port 8322; informational, the launch goes on.
"%VENV_PY%" "%~dp0launcher_port_guard.py" 8322

set "PF86=%ProgramFiles(x86)%"
set "EDGE_EXE=%PF86%\Microsoft\Edge\Application\msedge.exe"
if not exist "%EDGE_EXE%" set "EDGE_EXE=%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"

REM Open Edge to the console once the server answers, in its own titled window so a failure to
REM come up stays on screen (wait_for_ready_then_open.py).
start "Ed Console - Browser Launch" "%VENV_PY%" "%~dp0wait_for_ready_then_open.py" http://localhost:8000/ "%EDGE_EXE%"

REM --timeout-graceful-shutdown: Ctrl+C must terminate even while browser tabs
REM hold SSE streams open (uvicorn's default waits forever for them to close).
"%VENV_PY%" -m uvicorn server:app --host 0.0.0.0 --port 8000 --timeout-graceful-shutdown 10

echo.
echo  Server stopped.
pause
