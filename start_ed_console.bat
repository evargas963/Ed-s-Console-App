@echo off
title Ed Console
cd /d "%~dp0"

echo.
echo  ============================================
echo   Ed Console - Starting...
echo  ============================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo  ERROR: Python not found. Make sure Python is installed and on your PATH.
    pause
    exit /b 1
)

python -m uvicorn --version >nul 2>&1
if errorlevel 1 (
    echo  Installing uvicorn...
    pip install "uvicorn[standard]" fastapi
)

echo  Starting server at http://localhost:8000
echo  Press Ctrl+C to stop.
echo  (CWD set to script dir - token path resolves from app dir)
echo  Ops panel /Run tasks/ click-to-run: ON  (localhost only unless ED_OPS_ALLOW_REMOTE=1)
echo  Opening Microsoft Edge to http://localhost:8000 in a few seconds...
echo.

set ED_OPS_RUNNER=1
set ED_CALIBRATION_LOG=1

REM RC-350 ONE-APP LOCK (operator yes 2026-08-14): the desk may only run a committed,
REM non-divergent build of origin/main. Emergency bypass: set ED_LIVE_PATH_UNLOCKED=1.
python tools\check_live_path_is_main.py
if errorlevel 1 (
    echo  LAUNCH BLOCKED: the desk is not running origin/main. See RC-350.
    pause
    exit /b 1
)

REM Stop any prior instance still bound to port 8000 (plain-line for /f — safe batch syntax)
for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do taskkill /F /PID %%P 2>nul

set "PF86=%ProgramFiles(x86)%"
set "EDGE_EXE=%PF86%\Microsoft\Edge\Application\msedge.exe"
if not exist "%EDGE_EXE%" set "EDGE_EXE=%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"

REM Original working pattern: delayed open in background subprocess (Edge only, not Chrome)
start "" cmd /c "timeout /t 2 /nobreak >nul & "%EDGE_EXE%" http://localhost:8000"

REM --timeout-graceful-shutdown: Ctrl+C must terminate even while browser tabs
REM hold SSE streams open (uvicorn's default waits forever for them to close).
python -m uvicorn server:app --host 0.0.0.0 --port 8000 --timeout-graceful-shutdown 10

echo.
echo  Server stopped.
pause
