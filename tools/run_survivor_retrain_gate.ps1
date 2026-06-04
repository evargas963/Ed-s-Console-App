# 3:30 PM CT — FULL TRAIN (operator contract)
#   SPY + QQQ + IWM | parallel + cascade | all horizons (1c/5c/15c/60c) | survivor mask | auto-promote
#   Command: ml_scheduler.py --run-now --force-retrain --bypass-cache --all-horizons
#
# Usage:
#   .\tools\run_survivor_retrain_gate.ps1
#   .\tools\run_survivor_retrain_gate.ps1 -NoWait
#   .\tools\run_survivor_retrain_gate.ps1 -StartTimeCT "15:30"

param(
    [string]$StartTimeCT = "15:30",
    [switch]$NoWait,
    [switch]$SkipSpyParallel5c,
    [switch]$BypassCache
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot

$LogDir = Join-Path $RepoRoot "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Stamp = Get-Date -Format "yyyy-MM-dd_HHmmss"
$LogFile = Join-Path $LogDir "survivor_retrain_gate_$Stamp.log"
$ErrFile = Join-Path $LogDir "survivor_retrain_gate_$Stamp.err"

function Write-Log([string]$Msg) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Msg"
    Write-Host $line
    Add-Content -Path $LogFile -Value $line
}

function Stop-CompetingMlJobs {
    Write-Log "pipeline-status + stop competing ablation/train (not ml_scheduler)..."
    $statusJson = python tools/feature_curation_gate.py --pipeline-status 2>&1 | Out-String
    Add-Content -Path $LogFile -Value $statusJson
    $status = $statusJson | ConvertFrom-Json

    if ($status.ablation.ablation_process_live -and $status.ablation.lock_pid) {
        $pidA = [int]$status.ablation.lock_pid
        Write-Log "stopping ablation pid=$pidA"
        Stop-Process -Id $pidA -Force -ErrorAction SilentlyContinue
    }
    Get-CimInstance Win32_Process -Filter "name='python.exe'" | ForEach-Object {
        $cmd = $_.CommandLine
        if ($cmd -match "feature_curation_gate\.py.*--ablation") {
            Write-Log "stopping ablation pid=$($_.ProcessId)"
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }
        if ($cmd -match "_train_parallel|_train_cascade" -and $cmd -notmatch "ml_scheduler\.py") {
            Write-Log "stopping ad-hoc train pid=$($_.ProcessId) (3:30 uses ml_scheduler only)"
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }
    }
    Remove-Item "governance\artifacts\feature_ablation.run.lock" -ErrorAction SilentlyContinue
}

Write-Log "=== FULL TRAIN gate repo=$RepoRoot ==="
Write-Log "contract: SPY,QQQ,IWM | parallel+cascade | all horizons | survivors | auto-promote"

if (-not $NoWait) {
    $tz = [System.TimeZoneInfo]::FindSystemTimeZoneById("Central Standard Time")
    $nowCt = [System.TimeZoneInfo]::ConvertTimeFromUtc([DateTime]::UtcNow, $tz)
    $parts = $StartTimeCT.Split(":")
    if ($parts.Count -lt 2) { throw "StartTimeCT must be HH:mm (got $StartTimeCT)" }
    $targetCt = Get-Date -Year $nowCt.Year -Month $nowCt.Month -Day $nowCt.Day `
        -Hour ([int]$parts[0]) -Minute ([int]$parts[1]) -Second 0
    if ($nowCt -lt $targetCt) {
        $waitSec = [math]::Max(1, [int](($targetCt - $nowCt).TotalSeconds))
        Write-Log "waiting until $StartTimeCT CT ($waitSec s) — now=$($nowCt.ToString('HH:mm:ss')) CT"
        Start-Sleep -Seconds $waitSec
    } else {
        Write-Log "start time $StartTimeCT CT passed — launching now ($($nowCt.ToString('HH:mm:ss')) CT)"
    }
}

Stop-CompetingMlJobs

$env:ED_APPLY_ABLATION_SURVIVORS = "1"
$env:ED_ML_SCHEDULER_TICKERS = "SPY,QQQ,IWM"
$env:ED_SCHEDULER_AUTO_PROMOTE = "1"
$env:ED_SCHEDULER_AUTO_PROMOTE_CORE_ONLY = "1"
Remove-Item Env:\ED_TRAIN_ROLLING_RTH_SESSIONS_TABULAR -ErrorAction SilentlyContinue
Remove-Item Env:\ED_TRAIN_ROLLING_RTH_SESSIONS_SEQUENCE -ErrorAction SilentlyContinue
Remove-Item Env:\ED_TRAIN_ROLLING_DAYS_TABULAR -ErrorAction SilentlyContinue
Remove-Item Env:\ED_TRAIN_ROLLING_DAYS_SEQUENCE -ErrorAction SilentlyContinue
Remove-Item Env:\ED_ABLATION_SCORED_EVAL -ErrorAction SilentlyContinue
Remove-Item Env:\ED_DISABLE_AUTO_PROMOTE -ErrorAction SilentlyContinue

Write-Log "gate env check..."
python tools/feature_curation_gate.py --survivor-retrain-gate-env-check 2>&1 | Tee-Object -FilePath $LogFile -Append
if ($LASTEXITCODE -ne 0) { exit 1 }

Write-Log "survivor retrain preflight..."
python tools/feature_curation_gate.py --survivor-retrain-preflight --tickers SPY,QQQ,IWM 2>&1 | Tee-Object -FilePath $LogFile -Append
if ($LASTEXITCODE -ne 0) { exit 2 }

Write-Log "survivor inference backtest (models/active — no retrain)..."
python tools/feature_curation_gate.py --survivor-inference-backtest --tickers SPY,QQQ,IWM 2>&1 | Tee-Object -FilePath $LogFile -Append
if ($LASTEXITCODE -ne 0) { exit 3 }

Write-Log "survivor edge probe..."
python tools/feature_curation_gate.py --survivor-edge-probe --tickers SPY,QQQ,IWM 2>&1 | Tee-Object -FilePath $LogFile -Append
if ($LASTEXITCODE -ne 0) { exit 4 }

Write-Log "survivor validation run..."
python tools/feature_curation_gate.py --survivor-validation-run --tickers SPY,QQQ,IWM 2>&1 | Tee-Object -FilePath $LogFile -Append
if ($LASTEXITCODE -ne 0) { exit 5 }

$schedArgs = @("ml_scheduler.py", "--run-now", "--force-retrain")
if ($BypassCache) { $schedArgs += "--bypass-cache" }

if ($SkipSpyParallel5c) {
    Write-Log "=== split train: SkipSpyParallel5c (QQQ/IWM all hz; SPY 1c/15c/60c; SPY cascade 5c only) ==="
    $env:ED_ML_SCHEDULER_TICKERS = "QQQ,IWM"
    Write-Log "phase 1: QQQ,IWM --all-horizons"
    $T0 = Get-Date
    & python @schedArgs --all-horizons *>> $LogFile
    $Exit = $LASTEXITCODE
    Write-Log "phase 1 exit=$Exit elapsed_min=$([math]::Round(((Get-Date) - $T0).TotalMinutes, 1))"
    if ($Exit -ne 0) { exit $Exit }

    $env:ED_ML_SCHEDULER_TICKERS = "SPY"
    foreach ($hz in @("1c", "15c", "60c")) {
        Write-Log "phase 2: SPY horizon=$hz"
        $T0 = Get-Date
        python @schedArgs --horizon $hz 1>>$LogFile 2>>$ErrFile
        $Exit = $LASTEXITCODE
        Write-Log "phase 2 SPY $hz exit=$Exit elapsed_min=$([math]::Round(((Get-Date) - $T0).TotalMinutes, 1))"
        if ($Exit -ne 0) { exit $Exit }
    }

    Write-Log "phase 3: SPY 5c cascade only (parallel skipped)"
    Remove-Item Env:\ED_ML_SCHEDULER_SKIP_PARALLEL_TRAIN -ErrorAction SilentlyContinue
    $env:ED_ML_SCHEDULER_SKIP_PARALLEL_TRAIN = "1"
    $T0 = Get-Date
    python @schedArgs --horizon 5c 1>>$LogFile 2>>$ErrFile
    $Exit = $LASTEXITCODE
    Remove-Item Env:\ED_ML_SCHEDULER_SKIP_PARALLEL_TRAIN -ErrorAction SilentlyContinue
    Write-Log "phase 3 exit=$Exit elapsed_min=$([math]::Round(((Get-Date) - $T0).TotalMinutes, 1))"
    if ($Exit -ne 0) { exit $Exit }
} else {
    Write-Log "=== ml_scheduler --all-horizons (parallel+cascade, force-retrain$(if ($BypassCache) { ', bypass-cache' })) ==="
    $env:ED_ML_SCHEDULER_TICKERS = "SPY,QQQ,IWM"
    $T0 = Get-Date
    & python @schedArgs --all-horizons *>> $LogFile
    $Exit = $LASTEXITCODE
    Write-Log "scheduler exit=$Exit elapsed_min=$([math]::Round(((Get-Date) - $T0).TotalMinutes, 1))"
    if ($Exit -ne 0) { exit $Exit }
}

python verify_active_models.py 2>&1 | Tee-Object -FilePath $LogFile -Append
Write-Log "=== done - restart server with ED_APPLY_ABLATION_SURVIVORS=1 ==="
exit 0
