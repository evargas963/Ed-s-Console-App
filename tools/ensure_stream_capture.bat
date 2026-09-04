@echo off
cd /d "%~dp0\.."
if exist "..\EdWebConsole\data\stream_capture.db" (
  set "STREAM_CAPTURE_DB_PATH=%~dp0..\..\EdWebConsole\data\stream_capture.db"
)
"%~dp0..\.venv\Scripts\pythonw.exe" "%~dp0ensure_stream_capture.py" %*
