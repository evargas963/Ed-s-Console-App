#Requires -Version 5.1
<#
.SYNOPSIS
  Run ml_scheduler --all-horizons --run-now for SPY/QQQ/IWM (anchor roster default).

.DESCRIPTION
  Host overnight training lane. Logs to logs/ml_all_horizons_<timestamp>.log.
  Optional -StartAt waits until local clock time (e.g. 16:00 for 4pm) before starting.

  Stop the live console before training to avoid snapshot_id races (see train_per_anchor_sequential.ps1).

.EXAMPLE
  pwsh tools/run_ml_all_horizons.ps1 -StartAt 16:00
.EXAMPLE
  pwsh tools/run_ml_all_horizons.ps1
#>
[CmdletBinding()]
param(
    [string] $StartAt = "",
    [switch] $NoAutoPromote
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$logDir = Join-Path $repoRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir ("ml_all_horizons_" + (Get-Date -Format "yyyy-MM-dd_HHmmss") + ".log")

function Write-Log([string]$Msg) {
    $line = (Get-Date -Format "yyyy-MM-dd HH:mm:ss") + " " + $Msg
    Write-Host $line
    Add-Content -Path $logFile -Value $line
}

if ($StartAt) {
    $parts = $StartAt -split ":"
    if ($parts.Count -lt 2) { throw "StartAt must be HH:mm (e.g. 16:00)" }
    $hour = [int]$parts[0]
    $minute = [int]$parts[1]
    $target = (Get-Date).Date.AddHours($hour).AddMinutes($minute)
    if ((Get-Date) -ge $target) {
        throw "StartAt $StartAt already passed today (local $($target.ToString('yyyy-MM-dd HH:mm:ss'))). Pick a future time or omit -StartAt."
    }
    $waitSec = [int](($target - (Get-Date)).TotalSeconds)
    Write-Log "Waiting until local $StartAt ($($target.ToString('yyyy-MM-dd HH:mm:ss'))) — ${waitSec}s ..."
    Start-Sleep -Seconds $waitSec
}

Write-Log "=== ml_scheduler --all-horizons --run-now (anchor roster default: SPY/QQQ/IWM) ==="
Write-Log "log=$logFile"
Write-Log "cwd=$repoRoot"

Remove-Item Env:ED_ML_SCHEDULER_TRAINING_EXPAND -ErrorAction SilentlyContinue
Remove-Item Env:ED_ML_SCHEDULER_TICKERS -ErrorAction SilentlyContinue
if (-not $NoAutoPromote) {
    $env:ED_SCHEDULER_AUTO_PROMOTE = "1"
}
$env:ED_TRAINING_SKIP_INLINE_NORMSYNC = "1"

Write-Log "env: ED_SCHEDULER_AUTO_PROMOTE=$($env:ED_SCHEDULER_AUTO_PROMOTE) ED_ML_SCHEDULER_TRAINING_EXPAND=(unset)"

$start = Get-Date
& python ml_scheduler.py --all-horizons --run-now 2>&1 | Tee-Object -FilePath $logFile -Append
$code = $LASTEXITCODE
$elapsedMin = [math]::Round(((Get-Date) - $start).TotalMinutes, 1)
Write-Log "=== finished exit=$code elapsed_min=$elapsedMin ==="
exit $code
