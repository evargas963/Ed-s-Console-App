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

REM launch.py ends with 10 after it fast-forwarded the checkout: it is run again, on the new code.
:launch
"%VENV_PY%" launch.py
if "%errorlevel%"=="10" goto launch
pause
