@echo off
title Ed Capture Daemon
cd /d "%~dp0"
REM Ed Console, one program: the ONE Schwab streaming connection, the recording, the console's
REM pages and every live price (:8000, the page's prices at /ws; stopped by a named event). Started
REM by launch.py (start_ed_console.cmd), which brings the checkout to origin/main first; it reads
REM its own .env (the Schwab credentials). Its output goes to logs\stream_capture.<date>.log and to
REM this window; an error before its modules load shows in this window (python). If it exits it is
REM restarted here after RESTART_WAIT_SEC, except when another daemon already owns the stream
REM (exit 3), this checkout may not run live (exit 2), or it was stopped cleanly on request (exit 5:
REM `python launch.py stop`, which also stops the console); then this window stays READ_WAIT_SEC,
REM so what it printed can be read, and closes. Stop the daemon with `python launch.py stop`;
REM closing this window ends it and its restarts.
set "RESTART_WAIT_SEC=5"
set "READ_WAIT_SEC=30"

:loop
echo  %date% %time%  capture daemon starting (output: logs\stream_capture.^<date^>.log)
"%~dp0.venv\Scripts\python.exe" -m app.market_data.schwab.streaming.capture_main
set "CODE=%errorlevel%"
echo  %date% %time%  capture daemon exited (code %CODE%)
if "%CODE%"=="3" (
    echo  Another capture daemon already owns the stream - not starting a second one.
    goto done
)
if "%CODE%"=="2" (
    echo  This checkout may not run a live daemon here - the reason is printed above.
    goto done
)
if "%CODE%"=="5" (
    echo  Stopped on request - not restarted.
    goto done
)
echo  Restarting in %RESTART_WAIT_SEC% s.
timeout /t %RESTART_WAIT_SEC% /nobreak >nul
goto loop

:done
timeout /t %READ_WAIT_SEC% /nobreak
