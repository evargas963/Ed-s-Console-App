@echo off
title Ed Capture Daemon
cd /d "%~dp0"
REM The capture daemon: holds the ONE Schwab streaming connection and serves every live price
REM (ws :8800 browsers, :8799 console). Started by start_ed_console.bat. Its output goes to
REM logs\stream_capture.log (pythonw). If it exits it is restarted here after 5 s, the wait
REM doubling (to 300 s) after each run shorter than a minute, logged -- except when another
REM daemon already owns the stream (exit 3) or this checkout may not run live (exit 2).
REM Close this window to stop the daemon's restarts (then end the pythonw process if running).
set "WAIT=5"
:loop
echo  %date% %time%  capture daemon starting (output: logs\stream_capture.log)
for /f %%s in ('powershell -NoProfile -Command "[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()"') do set "STARTED=%%s"
"%~dp0.venv\Scripts\pythonw.exe" -m app.market_data.schwab.streaming.capture
set "CODE=%errorlevel%"
for /f %%s in ('powershell -NoProfile -Command "[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()"') do set "ENDED=%%s"
set /a RAN=ENDED-STARTED
if "%CODE%"=="3" (
    echo  Another capture daemon already owns the stream - not starting a second one.
    goto done
)
if "%CODE%"=="2" (
    echo  This checkout may not run a live daemon here - see logs or run it in a terminal.
    goto done
)
if %RAN% GEQ 60 set "WAIT=5"
echo  %date% %time%  capture daemon exited (code %CODE%) after %RAN% s - restarting in %WAIT% s
echo %date% %time% start_capture_daemon.bat: the daemon exited (code %CODE%) after %RAN% s; restarting in %WAIT% s>> "%~dp0logs\stream_capture.log"
timeout /t %WAIT% /nobreak >nul
if %RAN% LSS 60 set /a WAIT=WAIT*2
if %WAIT% GTR 300 set "WAIT=300"
goto loop
:done
timeout /t 30
