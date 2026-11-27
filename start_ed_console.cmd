@echo off
title Ed Console
cd /d "%~dp0"

REM The project's own Python, never whatever `python` the PATH finds; launch.py does the rest.
set "VENV_PY=%~dp0.venv\Scripts\python.exe"

REM launch.py starts Ed Console (one program, in the "Ed Capture Daemon" window), opens the browser
REM once its pages answer and ends with 0, and this window closes; it stays open on an error, so its
REM message can be read. One block, read whole before it runs: a start that fast-forwards the
REM checkout may rewrite this file, and nothing after it is read.
if exist "%VENV_PY%" (
    "%VENV_PY%" launch.py || pause
    exit /b
) else (
    echo  ERROR: repo virtualenv interpreter not found at "%VENV_PY%".
    echo  Create it:  python -m venv .venv
    echo  then:       .venv\Scripts\python -m pip install -r requirements.txt
    pause
    exit /b 1
)
