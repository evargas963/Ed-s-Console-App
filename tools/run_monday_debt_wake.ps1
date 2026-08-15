# EdMondayDebtWake launcher — Mondays ~08:25 CT (America/Chicago wall clock via Task Scheduler).
# Inventory: governance/host_scheduled_jobs.md + reports/monday_debt_alarm_setup.md
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
$Py = Join-Path $Repo ".venv\Scripts\python.exe"
$Tool = Join-Path $Repo "tools\monday_debt_wake.py"
if (-not (Test-Path $Py)) { throw "missing venv python: $Py" }
if (-not (Test-Path $Tool)) { throw "missing wake tool: $Tool" }
& $Py $Tool @args
exit $LASTEXITCODE
