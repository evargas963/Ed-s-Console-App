@echo off
title Ed Capture Daemon
cd /d "%~dp0"
REM Ed Console, one program: the ONE Schwab streaming connection, the recording, the console's
REM pages and every live price (:8000, the page's prices at /ws; stopped by a named event). Started
REM by launch.py (start_ed_console.cmd), which brings the checkout to origin/main first; it reads
REM its own .env (the Schwab credentials). Its output goes to logs\stream_capture.<date>.log and to
REM this window; an error before its modules load shows in this window (python). `launch.py
REM window` runs it, and again after it ends on an error; never after a stop (`python launch.py
REM stop`, which reaches it between two runs too), Ctrl+C, another program holding the stream or
REM a checkout that may not run live. Then this window stays READ_WAIT_SEC, so what it printed
REM can be read, and closes. Closing this window ends the program without its clean stop.
set "READ_WAIT_SEC=30"
set "VENV_PY=%~dp0.venv\Scripts\python.exe"

REM One block, read whole before it runs: a merge that rewrites this file while it runs changes
REM nothing it does. The project's own Python, never whatever `python` the PATH finds.
if exist "%VENV_PY%" (
    "%VENV_PY%" launch.py window
    timeout /t %READ_WAIT_SEC% /nobreak
    exit /b
) else (
    echo  ERROR: repo virtualenv interpreter not found at "%VENV_PY%".
    timeout /t %READ_WAIT_SEC% /nobreak
    exit /b 1
)
