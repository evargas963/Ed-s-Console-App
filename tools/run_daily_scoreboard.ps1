# End-of-day signal scoreboard (registered as Windows scheduled task "EdWebConsole Daily Scoreboard").
# Attaches outcomes to today's calibration decisions, scores per-horizon fusion predictions,
# writes reports/daily_scoreboard/scoreboard_<date>.{json,html}, and opens the HTML report.
#
# Register (one-time, already done by agent on 2026-06-09; rerun if the task is ever deleted):
#   schtasks /Create /TN "EdWebConsole Daily Scoreboard" /SC WEEKLY /D MON,TUE,WED,THU,FRI `
#     /ST 15:35 /TR "powershell -NoProfile -ExecutionPolicy Bypass -File C:\Users\evarg\Documents\Trading\EdWebConsole\tools\run_daily_scoreboard.ps1" /F

$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

$logDir = Join-Path $repo "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir ("daily_scoreboard_{0}.log" -f (Get-Date -Format "yyyy-MM-dd"))

"=== daily scoreboard run $(Get-Date -Format o) ===" | Out-File -Append -FilePath $log
python -m calibration.daily_scoreboard --open *>> $log
"exit=$LASTEXITCODE" | Out-File -Append -FilePath $log
exit $LASTEXITCODE
