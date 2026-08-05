# Canonical launcher for the daily rehab + advisory TQM scan (RC-218 / RC-250 / RC-251).
#
# A host scheduled task or Cursor Automation should call THIS FILE, never an inline
# `schtasks /TR` command line. A launcher in the repo is reviewed, version-controlled and
# testable; an inline command lives only in the Task Scheduler UI, which is exactly how
# EdTerrainScorecard ran broken for weeks with nobody able to see why — see the defect history
# in governance/host_scheduled_jobs.md.
#
# Runs MEASURE (advisory checks) then TRIAGE (bounded queue), writing dated artifacts:
#   reports/rehab_latest.md            human view: findings, totals, hotspots, TQM queue
#   reports/tqm_queue_latest.json      machine queue — max 5 items, kill criteria, delta
#   reports/advisory_debt_latest.json  per-check tally + per-file hotspots
#
# Recommend-only: never edits product code, commits, or restarts servers.

$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
Set-Location $Repo

# venv parity: the repo interpreter, or say so loudly. A bare `python` is whatever happens to be
# on PATH — a defect class this repo has already paid for once.
$Py = Join-Path $Repo ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) {
    Write-Warning "repo venv python not found at $Py - falling back to PATH python (venv parity NOT guaranteed)"
    $Py = "python"
}

& $Py tools/rehab_daily_scan.py
$code = $LASTEXITCODE

# The scan is recommend-only, so a non-zero exit means the SCAN broke — not that debt exists.
# Surface it: a scheduled job that fails quietly reads exactly like a clean repo.
if ($code -ne 0) {
    Write-Error "rehab_daily_scan exited $code - the daily TQM measurement did not complete"
}
exit $code
