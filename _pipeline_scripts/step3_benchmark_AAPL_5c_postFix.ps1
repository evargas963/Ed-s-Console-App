$RepoPath  = "C:\Users\evarg\Documents\Trading\EdWebConsole"
$LogDir    = "$RepoPath\benchmark_logs"
$Stamp     = (Get-Date).ToString("yyyy-MM-dd_HHmmss")
$LogFile   = "$LogDir\benchmark_AAPL_5c_postfix_$Stamp.log"
$ErrFile   = "$LogDir\benchmark_AAPL_5c_postfix_$Stamp.err"
$Ticker    = "AAPL"
$Horizon   = "5c"

Write-Host "=== PRE-FLIGHT ===" -ForegroundColor Cyan
if (-not (Test-Path $RepoPath)) { Write-Host "FAIL: repo missing" -ForegroundColor Red; exit 1 }
Set-Location $RepoPath
$PyVersion = python --version 2>&1
if ($LASTEXITCODE -ne 0) { Write-Host "FAIL: python missing" -ForegroundColor Red; exit 1 }
Write-Host "  Python: $PyVersion"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

if ($env:ED_XGB_STRICT_ACTIVE_ONLY) {
    Write-Host "  NOTE: ED_XGB_STRICT_ACTIVE_ONLY is set in shell to '$env:ED_XGB_STRICT_ACTIVE_ONLY'. Removing for this test." -ForegroundColor Yellow
    Remove-Item Env:\ED_XGB_STRICT_ACTIVE_ONLY -ErrorAction SilentlyContinue
}
Write-Host "  ED_XGB_STRICT_ACTIVE_ONLY: not set in shell (relying on code-level scope fix)"

$PreActive = Get-ChildItem -Path "$RepoPath\models\active\$Ticker" -ErrorAction SilentlyContinue
$PreActiveHash = if ($PreActive) {
    ($PreActive | ForEach-Object { "$($_.Name):$((Get-FileHash $_.FullName -Algorithm SHA256).Hash)" }) -join "`n"
} else { "" }
Write-Host "  active/$Ticker pre-state: $(if($PreActive){$PreActive.Count}else{0}) files"

Write-Host ""
Write-Host "=== TRAINING ===" -ForegroundColor Cyan
$env:ED_ML_SCHEDULER_TICKERS = $Ticker
Write-Host "  ED_ML_SCHEDULER_TICKERS = $env:ED_ML_SCHEDULER_TICKERS"
Write-Host "  Start: $(Get-Date -Format 'HH:mm:ss')"
$T0 = Get-Date
python ml_scheduler.py --run-now --horizon $Horizon 1>$LogFile 2>$ErrFile
$ExitCode = $LASTEXITCODE
$Elapsed = (Get-Date) - $T0
Remove-Item Env:\ED_ML_SCHEDULER_TICKERS
Write-Host "  End:   $(Get-Date -Format 'HH:mm:ss')"
Write-Host "  Elapsed: $($Elapsed.TotalMinutes.ToString('F2')) min"
Write-Host "  Exit:    $ExitCode"

Write-Host ""
Write-Host "=== POST-TRAINING ===" -ForegroundColor Cyan
$PostActive = Get-ChildItem -Path "$RepoPath\models\active\$Ticker" -ErrorAction SilentlyContinue
$PostActiveHash = if ($PostActive) {
    ($PostActive | ForEach-Object { "$($_.Name):$((Get-FileHash $_.FullName -Algorithm SHA256).Hash)" }) -join "`n"
} else { "" }
$tickerLabel = $Ticker
if ($PreActiveHash -ne $PostActiveHash) {
    Write-Host "  FAIL: active/$tickerLabel was modified" -ForegroundColor Red
} else {
    Write-Host "  active/${tickerLabel}: unchanged (good)"
}

$ParallelDir = "$RepoPath\models\parallel\$Ticker"
$CascadeDir  = "$RepoPath\models\cascade\$Ticker"
Write-Host "  parallel/$Ticker contents:"
if (Test-Path $ParallelDir) {
    Get-ChildItem $ParallelDir | ForEach-Object { Write-Host "    $($_.Name) ($([math]::Round($_.Length/1KB,2)) KB)" }
} else { Write-Host "    (directory not found)" }
Write-Host "  cascade/$Ticker contents:"
if (Test-Path $CascadeDir) {
    Get-ChildItem $CascadeDir | ForEach-Object { Write-Host "    $($_.Name) ($([math]::Round($_.Length/1KB,2)) KB)" }
} else { Write-Host "    (directory not found)" }

Write-Host ""
Write-Host "=== KEY ARTIFACTS CHECK ===" -ForegroundColor Cyan
$KeyFiles = @(
    "$ParallelDir\meta_AAPL_5c.pkl",
    "$ParallelDir\evaluation_manifest.json",
    "$ParallelDir\promotion_decision.json",
    "$CascadeDir\meta_AAPL_5c.pkl",
    "$CascadeDir\xgb_AAPL_5c.pkl",
    "$CascadeDir\evaluation_manifest.json",
    "$CascadeDir\promotion_decision.json"
)
$AllPresent = $true
foreach ($f in $KeyFiles) {
    if (Test-Path $f) {
        $sz = [math]::Round((Get-Item $f).Length/1KB, 2)
        Write-Host "  PRESENT  $f ($sz KB)"
    } else {
        Write-Host "  MISSING  $f" -ForegroundColor Yellow
        $AllPresent = $false
    }
}

Write-Host ""
Write-Host "=== SUMMARY ===" -ForegroundColor Cyan
Write-Host "  Wall-clock: $($Elapsed.TotalMinutes.ToString('F2')) min"
Write-Host "  Exit code:  $ExitCode"
Write-Host "  All artifacts present: $AllPresent"
Write-Host "  Logs: $LogFile"
Write-Host "        $ErrFile"
Write-Host ""
if ($AllPresent -and $ExitCode -eq 0) {
    Write-Host "  RESULT: code fix works - ready for full pipeline test" -ForegroundColor Green
} else {
    Write-Host "  RESULT: fix incomplete - do NOT proceed; report to Claude" -ForegroundColor Red
}
Write-Host ""
Write-Host "PASTE THIS OUTPUT TO CLAUDE."
