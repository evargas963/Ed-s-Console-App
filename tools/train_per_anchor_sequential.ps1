#Requires -Version 7
<#
.SYNOPSIS
  Per-anchor sequential PRODUCTION retrain + progressive activation (2026-06-03).

.DESCRIPTION
  Trains each ticker COMPLETELY (all models — XGB/LSTM/Transformer/meta — across all four governed
  horizons 1c/5c/15c/60c) on FULL history, auto-promotes the winners to models/active/, then calls
  the live console's loopback reload endpoint so THAT ticker's call cards go live BEFORE the next
  ticker starts training. Order: SPY -> QQQ -> IWM (default).

  Runtime lever (operator decision A, 2026-06-03): full history is preserved (no rolling-window
  cap, so the survivor-retrain env contract and the promotion floor are untouched); wall-clock is
  cut by EARLY STOPPING on the sequence models — training runs the 50/60-epoch CEILING but stops
  once the held-out val loss plateaus (patience, default 8), then restores the best epoch. No
  guessed epoch count. XGBoost is not epoch-based so it trains at full fidelity. (-LstmEpochs /
  -TransformerEpochs can lower the ceiling further if you want a hard cap; 0 = leave at 50/60.)

  Stop-on-failure: if a ticker's training/promotion fails, later tickers are NOT started (so SPY is
  proven done+promoted before QQQ begins, exactly as requested).

.NOTES
  Run from the repo root in the operator's PowerShell (training is a >5 min host run).
  The live console must already be running (default http://127.0.0.1:8000) for cards to activate
  mid-run; if it is down, training + promotion still complete on disk and cards activate on the
  next server start (or a later manual reload). Set $env:ED_CONSOLE_RELOAD_TOKEN to match the
  server if the server has a reload token configured.

.EXAMPLE
  pwsh tools/train_per_anchor_sequential.ps1
.EXAMPLE
  pwsh tools/train_per_anchor_sequential.ps1 -Tickers SPY -LstmEpochs 20 -TransformerEpochs 24
#>
[CmdletBinding()]
param(
    [string[]] $Tickers           = @("SPY", "QQQ", "IWM"),
    [string[]] $Horizons          = @("1c", "5c", "15c", "60c"),
    [int]      $LstmEpochs        = 0,   # 0 = keep the 50-epoch ceiling; early-stop cuts runtime
    [int]      $TransformerEpochs = 0,   # 0 = keep the 60-epoch ceiling; early-stop cuts runtime
    [int]      $EarlyStopPatience = 8,   # stop after N epochs with no held-out val improvement
    [string]   $ServerUrl         = "http://127.0.0.1:8000",
    [switch]   $NoActivate        # train + promote only; skip the live reload call
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

# --- Full history: strip any rolling-window cap that might leak in from the shell/.env ---
foreach ($v in 'ED_TRAIN_ROLLING_RTH_SESSIONS_TABULAR', 'ED_TRAIN_ROLLING_RTH_SESSIONS_SEQUENCE',
                'ED_TRAIN_ROLLING_DAYS_TABULAR', 'ED_TRAIN_ROLLING_DAYS_SEQUENCE') {
    if (Test-Path "Env:$v") { Remove-Item "Env:$v" }
}

# --- Knobs applied to every child training process ---
$env:ED_SCHEDULER_AUTO_PROMOTE                = "1"   # train-success-live: write models/active/ on success
$env:ED_APPLY_ABLATION_SURVIVORS              = "1"   # O-56: train on the ablated data (per-model x horizon survivors). REQUIRED — full-feature is not a valid retrain target (AGENTS §Ablation).
$env:ED_TRAINING_SKIP_INLINE_NORMSYNC          = "1"   # ml_scheduler run_once syncs once; no per-load_data materialize (UNIQUE snapshot_id race with live server)
$env:ED_TRAIN_EARLY_STOP                      = "1"   # adaptive runtime lever (plateau -> stop, restore best)
$env:ED_TRAIN_EARLY_STOP_PATIENCE_LSTM        = "$EarlyStopPatience"
$env:ED_TRAIN_EARLY_STOP_PATIENCE_TRANSFORMER = "$EarlyStopPatience"
# Optional hard ceiling on epochs (0 = leave canonical 50/60; early-stop still applies underneath).
if ($LstmEpochs -gt 0)        { $env:ED_TRAIN_EPOCHS_LSTM = "$LstmEpochs" }        else { Remove-Item Env:ED_TRAIN_EPOCHS_LSTM -ErrorAction SilentlyContinue }
if ($TransformerEpochs -gt 0) { $env:ED_TRAIN_EPOCHS_TRANSFORMER = "$TransformerEpochs" } else { Remove-Item Env:ED_TRAIN_EPOCHS_TRANSFORMER -ErrorAction SilentlyContinue }

$reloadToken = $env:ED_CONSOLE_RELOAD_TOKEN
$reloadUrl   = "$ServerUrl/api/internal/reload_models"

$lstmCeil = if ($LstmEpochs -gt 0) { $LstmEpochs } else { "50(default)" }
$tfCeil = if ($TransformerEpochs -gt 0) { $TransformerEpochs } else { "60(default)" }
Write-Host "=== Per-anchor sequential PRODUCTION retrain ==="
Write-Host ("tickers={0}  horizons={1}  epoch_ceiling lstm/tf={2}/{3}  early_stop=ON(patience={4})  full_history=YES  auto_promote=ON" -f `
    ($Tickers -join ','), ($Horizons -join ','), $lstmCeil, $tfCeil, $EarlyStopPatience)
Write-Host "NOTE: stop the live console during this run if possible — concurrent normalized refresh causes snapshot_id UNIQUE failures."

# Fail-closed preflight: confirm pass + DB/readiness before multi-hour GPU burn.
Write-Host "=== O-56 survivor retrain preflight (confirm pass required) ==="
& python tools/feature_curation_gate.py --survivor-retrain-preflight --tickers ($Tickers -join ',')
if ($LASTEXITCODE -ne 0) {
    Write-Host "!!! Preflight FAILED — run: python tools/feature_curation_gate.py --ablation-confirm" -ForegroundColor Red
    exit $LASTEXITCODE
}
Write-Host "=== Pre-B incumbent score reconcile (all horizons) ==="
$tickerPy = ($Tickers | ForEach-Object { "'$($_.ToUpper())'" }) -join ', '
$reconcilePy = @"
from pathlib import Path
from arch_competition.promotion_execution import reconcile_pre_b_incumbent_scores
r = reconcile_pre_b_incumbent_scores(Path('models'), [$tickerPy], ['1c','5c','15c','60c'], dry_run=False)
print('reconcile reset_count', r.get('reset_count', 0))
"@
& python -c $reconcilePy
Write-Host ""

foreach ($t in $Tickers) {
    $start = Get-Date
    Write-Host ">>> [$t] training all models, all horizons ($($Horizons -join ',')) on full history ..."
    $env:ED_ML_SCHEDULER_TICKERS = $t

    & python ml_scheduler.py --run-now --all-horizons
    $code = $LASTEXITCODE
    $elapsed = [int]((Get-Date) - $start).TotalSeconds
    if ($code -ne 0) {
        Write-Host "!!! [$t] training FAILED (exit $code) after ${elapsed}s. STOPPING — later tickers not started." -ForegroundColor Red
        exit $code
    }
    Write-Host "<<< [$t] training + promotion done in ${elapsed}s (exit 0)."

    if ($NoActivate) {
        Write-Host "    [$t] activation skipped (-NoActivate); cards go live on next server start."
    }
    else {
        $reloads = @($Horizons | ForEach-Object { @{ ticker = $t; horizon = $_ } })
        $payload = @{ reloads = $reloads } | ConvertTo-Json -Depth 5
        $headers = @{ "Content-Type" = "application/json" }
        if ($reloadToken) { $headers["X-Reload-Token"] = $reloadToken }
        try {
            $resp = Invoke-RestMethod -Uri $reloadUrl -Method Post -Body $payload -Headers $headers -TimeoutSec 30
            Write-Host "    [$t] ACTIVATED — cards live. reload: $($resp | ConvertTo-Json -Compress -Depth 5)"
        }
        catch {
            Write-Host ("    [$t] activation POST failed: {0}. Training + promotion are SAFE on disk; cards activate on next server restart." -f $_.Exception.Message) -ForegroundColor Yellow
        }
    }
    Write-Host ""
}

Write-Host "=== Done. Trained + promoted + activated in order: $($Tickers -join ' -> ') ==="
