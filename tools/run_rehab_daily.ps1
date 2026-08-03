# Local fallback for daily rehab scan (RC-218). Prefer Cursor Automation when available.
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
Set-Location $Repo
$Py = Join-Path $Repo ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { $Py = "python" }
& $Py tools/rehab_daily_scan.py
exit $LASTEXITCODE
