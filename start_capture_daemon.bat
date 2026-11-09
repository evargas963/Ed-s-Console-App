@echo off
title Ed Capture Daemon
cd /d "%~dp0"
REM Ed Console, one program: the ONE Schwab streaming connection, the recording, the console's pages
REM and every live price (:8000, the page's prices at /ws; /control: launch.py stop). Started by launch.py
REM (start_ed_console.bat), which brings the
REM checkout to origin/main first; it reads its own .env (the Schwab credentials). Its output goes
REM to logs\stream_capture.<date>.log and to this window; an error before its modules load shows in this window (python). If it exits it is restarted here after 5 s -- except when
REM another daemon already owns the stream (exit 3), this checkout may not run live (exit 2), or it
REM was stopped cleanly on request (exit 5: `python launch.py stop`, which also stops the console).
REM Stop the daemon with `python launch.py stop`; closing this window ends it and its restarts.
:loop
echo  %date% %time%  capture daemon starting (output: logs\stream_capture.^<date^>.log)
"%~dp0.venv\Scripts\python.exe" -m app.market_data.schwab.streaming.capture_main
set "CODE=%errorlevel%"
if "%CODE%"=="3" (
    echo  Another capture daemon already owns the stream - not starting a second one.
    goto done
)
if "%CODE%"=="2" (
    echo  This checkout may not run a live daemon here - the reason is printed above.
    goto done
)
if "%CODE%"=="5" (
    echo  %date% %time%  capture daemon stopped on request - not restarted.
    goto done
)
echo  %date% %time%  capture daemon exited (code %CODE%) - restarting in 5 s
timeout /t 5 /nobreak >nul
goto loop
:done
timeout /t 30
