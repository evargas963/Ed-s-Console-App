@echo off
title Ed Capture Daemon
cd /d "%~dp0"
REM The capture daemon: holds the ONE Schwab streaming connection and serves every live price
REM (ws :8800 browsers, :8799 console). Started by launch.py (start_ed_console.bat), which brings the
REM checkout to origin/main first; it reads its own .env (the Schwab credentials). Its output,
REM and its errors from before its project modules load, go to logs\stream_capture.<date>.log (pythonw). If it exits it is restarted here after 5 s -- except when
REM another daemon already owns the stream (exit 3), this checkout may not run live (exit 2), or it
REM was stopped cleanly on request (exit 5: `python launch.py stop`, which also stops the console).
REM Close this window to stop the daemon's restarts (then end the pythonw process if running).
:loop
echo  %date% %time%  capture daemon starting (output: logs\stream_capture.^<date^>.log)
"%~dp0.venv\Scripts\pythonw.exe" -m app.market_data.schwab.streaming.capture
set "CODE=%errorlevel%"
if "%CODE%"=="3" (
    echo  Another capture daemon already owns the stream - not starting a second one.
    goto done
)
if "%CODE%"=="2" (
    echo  This checkout may not run a live daemon here - see logs or run it in a terminal.
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
