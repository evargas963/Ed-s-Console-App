# One-shot SPY train status -> console (for operator + agent loop ticks).
$ErrorActionPreference = "SilentlyContinue"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot

function Out([string]$Msg, [string]$Color = "White") {
    Write-Host $Msg -ForegroundColor $Color
}

$sched = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match "ml_scheduler\.py" } | Select-Object -First 1)

Out ("=== SPY train status " + (Get-Date -Format "yyyy-MM-dd HH:mm:ss") + " ===") "Cyan"

if (-not $sched) {
    Out "ALERT: ml_scheduler not running" "Red"
    exit 1
}

$proc = Get-Process -Id $sched.ProcessId
$hz = "?"
if ($sched.CommandLine -match "--horizon\s+(\S+)") { $hz = $Matches[1] }
$surv = $env:ED_APPLY_ABLATION_SURVIVORS
$min = [math]::Round(((Get-Date) - $proc.StartTime).TotalMinutes, 1)
Out ("scheduler PID=" + $sched.ProcessId + " horizon=" + $hz + " runtime_min=" + $min +
    " WS_MB=" + [math]::Round($proc.WorkingSet64 / 1MB, 0) + " ED_APPLY_ABLATION_SURVIVORS=" + $surv) "Green"

$x5 = Get-Item "models\parallel\SPY\xgb_SPY_5c.pkl" -ErrorAction SilentlyContinue
if ($x5) {
    Out ("SPY parallel 5c xgb mtime=" + $x5.LastWriteTime.ToString("g")) "Yellow"
}

$latest = Get-ChildItem "models\parallel\SPY", "models\cascade\SPY" -File -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($latest) {
    Out ("latest artifact: " + $latest.Name + " @ " + $latest.LastWriteTime.ToString("g")) "Gray"
}

python -c @"
import json
from pathlib import Path
p = Path('models/training_report.jsonl')
for L in reversed(p.read_text(encoding='utf-8').splitlines()[-60:]):
    try:
        r = json.loads(L)
        if r.get('ticker') != 'SPY': continue
        if '2026-06-0' not in str(r.get('timestamp','')): continue
        print('  report', r.get('timestamp'), r.get('ml_horizon_suffix'), r.get('outcome'),
              'acc', r.get('eval_accuracy'), 'bal', r.get('balanced_accuracy'),
              'n_feat_check: see xgb meta')
    except Exception:
        pass
"@ 2>$null | ForEach-Object { Out $_ "White" }

foreach ($meta in @("models\parallel\SPY\xgb_SPY_1c_meta.json", "models\parallel\SPY\xgb_SPY_5c_meta.json")) {
    if (Test-Path $meta) {
        $m = Get-Content $meta -Raw | ConvertFrom-Json
        Out ("  " + (Split-Path $meta -Leaf) + " n_features=" + $m.n_features + " val_acc=" + $m.val_accuracy) "Gray"
    }
}

exit 0
