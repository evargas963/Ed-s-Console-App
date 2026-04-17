@echo off
title Ed Console
cd /d "%~dp0"

echo.
echo  ============================================
echo   Ed Console — Starting...
echo  ============================================
echo.

:: Check Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo  ERROR: Python not found. Make sure Python is installed and on your PATH.
    pause
    exit /b 1
)

:: Check uvicorn is available
python -m uvicorn --version >nul 2>&1
if errorlevel 1 (
    echo  Installing uvicorn...
    pip install uvicorn[standard] fastapi
)

echo  Starting server at http://localhost:8000
echo  Press Ctrl+C to stop.
echo  (CWD set to script dir — token path resolves from app dir)
echo  Ops panel /Run tasks/ click-to-run: ON  (localhost only unless ED_OPS_ALLOW_REMOTE=1)
echo.

:: Enable /ops "Run tasks" buttons (whitelisted scripts only). Still localhost-only by default.
set ED_OPS_RUNNER=1

:: Open browser after a short delay (runs in background)
start "" cmd /c "timeout /t 2 >nul && start http://localhost:8000"

:: Start the server
python -m uvicorn server:app --host 0.0.0.0 --port 8000

echo.
echo  Server stopped.
pause
