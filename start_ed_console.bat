@echo off
title Ed Console
cd /d "%~dp0"

REM The project's own Python, never whatever `python` the PATH finds; launch.py does the rest.
set "VENV_PY=%~dp0.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
    echo  ERROR: repo virtualenv interpreter not found at "%VENV_PY%".
    echo  Create it:  python -m venv .venv  then  .venv\Scripts\python -m pip install -r requirements.txt
    pause
    exit /b 1
)

"%VENV_PY%" launch.py
pause
