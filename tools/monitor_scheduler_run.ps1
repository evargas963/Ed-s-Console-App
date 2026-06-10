# Monitor ml_scheduler - prints every tick to THIS console + log file (do not kill train).
param(
    [int]$IntervalSec = 600,
    [int]$SchedulerPid = 0
)

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot
$LogDir = Join-Path $RepoRoot "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogFile = Join-Path $LogDir ("scheduler_monitor_" + (Get-Date -Format "yyyy-MM-dd_HHmmss") + ".log")

function Write-Log([string]$Msg, [string]$Level = "INFO") {
    $line = (Get-Date -Format "yyyy-MM-dd HH:mm:ss") + " " + $Msg
    switch ($Level) {
        "ALERT" { Write-Host $line -ForegroundColor Red }
        "OK"    { Write-Host $line -ForegroundColor Green }
        default { Write-Host $line }
    }
    Add-Content -Path $LogFile -Value $line
}

function Get-SchedulerInfo() {
    $cim = $null
    if ($SchedulerPid -gt 0) {
        $cim = Get-CimInstance Win32_Process -Filter ("ProcessId=" + $SchedulerPid) -ErrorAction SilentlyContinue
    }
    if (-not $cim) {
        $cim = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
            Where-Object { $_.CommandLine -match "ml_scheduler\.py.*--run-now" } | Select-Object -First 1)
    }
    if (-not $cim) { return $null }
    $proc = Get-Process -Id $cim.ProcessId -ErrorAction SilentlyContinue
    if (-not $proc) { return $null }
    $hz = "?"
    if ($cim.CommandLine -match "--horizon\s+(\S+)") { $hz = $Matches[1] }
    elseif ($cim.CommandLine -match "--all-horizons") { $hz = "all" }
    return @{
        Proc = $proc
        CommandLine = $cim.CommandLine
        Horizon = $hz
    }
}

function Get-SpyTrainingQuality() {
    $report = Join-Path $RepoRoot "models\training_report.jsonl"
    if (-not (Test-Path $report)) { return @() }
    $lines = @()
    try {
        $tail = Get-Content -Path $report -Tail 40 -ErrorAction Stop
        foreach ($L in $tail) {
            try {
                $r = $L | ConvertFrom-Json
                if ($r.ticker -ne "SPY") { continue }
                $lines += ("  SPY " + $r.ml_horizon_suffix + " " + $r.outcome +
                    " acc=" + $r.eval_accuracy + " bal=" + $r.balanced_accuracy +
                    " ll=" + $r.eval_log_loss + " rows=" + $r.rows_used + " @ " + $r.timestamp)
            } catch { }
        }
    } catch { }
    return $lines | Select-Object -Last 4
}

function Get-SpyHorizonArtifactHint([string]$Hz) {
    if ($Hz -eq "?" -or $Hz -eq "all") { return $null }
    $latest = Get-ChildItem -Path @(
        (Join-Path $RepoRoot "models\parallel\SPY"),
        (Join-Path $RepoRoot "models\cascade\SPY")
    ) -File -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match ("_" + [regex]::Escape($Hz) + "(\.|_)") } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if ($latest) {
        return "  latest " + $Hz + " artifact: " + $latest.Name + " @ " + $latest.LastWriteTime.ToString("g")
    }
    return $null
}

Write-Log "=== scheduler monitor (console + log) interval=${IntervalSec}s pid_hint=$SchedulerPid ===" "OK"
Write-Log "Run this script in a visible PowerShell window (foreground) to see ticks on screen." "INFO"

while ($true) {
    Write-Host ""
    $info = Get-SchedulerInfo
    if (-not $info) {
        Write-Log "ALERT: ml_scheduler not running" "ALERT"
        break
    }
    $sched = $info.Proc
    $min = [math]::Round(((Get-Date) - $sched.StartTime).TotalMinutes, 1)
    $cpu = [math]::Round($sched.CPU, 0)
    $ws = [math]::Round($sched.WorkingSet64 / 1MB, 0)
    Write-Log ("OK scheduler PID=" + $sched.Id + " horizon=" + $info.Horizon +
        " runtime_min=" + $min + " CPU=" + $cpu + "s WS_MB=" + $ws) "OK"

    $blockers = @()
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" | ForEach-Object {
        $cmd = $_.CommandLine
        if (-not $cmd) { return }
        if ($cmd -match "uvicorn") { $blockers += ("uvicorn PID=" + $_.ProcessId) }
        if ($cmd -match "schwab-mcp") { $blockers += ("schwab-mcp PID=" + $_.ProcessId) }
        if ($cmd -match "_train_parallel|_train_cascade" -and $cmd -notmatch "ml_scheduler") {
            $blockers += ("adhoc-train PID=" + $_.ProcessId)
        }
        if ($cmd -match "feature_curation_gate\.py.*--ablation") {
            $blockers += ("ablation PID=" + $_.ProcessId)
        }
    }
    if ($blockers.Count -gt 0) {
        Write-Log ("ALERT blockers: " + ($blockers -join "; ")) "ALERT"
    } else {
        Write-Log "OK no uvicorn schwab-mcp adhoc-train ablation" "OK"
    }

    $x5 = Get-Item "models\parallel\SPY\xgb_SPY_5c.pkl" -ErrorAction SilentlyContinue
    if ($x5) {
        Write-Log ("SPY parallel 5c xgb mtime=" + $x5.LastWriteTime.ToString("g") + " (exclude check)") "INFO"
    }

    $hint = Get-SpyHorizonArtifactHint $info.Horizon
    if ($hint) { Write-Log $hint.TrimStart() "INFO" }

    $quality = Get-SpyTrainingQuality
    if ($quality.Count -gt 0) {
        Write-Log "quality (training_report.jsonl tail):" "INFO"
        foreach ($q in $quality) { Write-Host $q }
    }

    Write-Log ("next tick in " + $IntervalSec + "s ...") "INFO"
    Start-Sleep -Seconds $IntervalSec
}

Write-Log "=== monitor exit ===" "INFO"
