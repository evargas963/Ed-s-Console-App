# Export a non-secret host inventory snapshot (gitignored host_manifest.json).
# Usage: .\scripts\export_host_manifest.ps1 [-OutFile host_manifest.json]

param(
    [string]$OutFile = "host_manifest.json"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

function Test-PathExists([string]$Rel) {
    $p = Join-Path $Root $Rel
    @{ path = $Rel; exists = (Test-Path -LiteralPath $p) }
}

function Get-DirStats([string]$Rel) {
    $p = Join-Path $Root $Rel
    if (-not (Test-Path -LiteralPath $p)) {
        return @{ path = $Rel; exists = $false; file_count = 0; size_bytes = 0 }
    }
    $files = Get-ChildItem -LiteralPath $p -Recurse -File -ErrorAction SilentlyContinue
    $size = ($files | Measure-Object -Property Length -Sum).Sum
    if ($null -eq $size) { $size = 0 }
    return @{
        path = $Rel
        exists = $true
        file_count = @($files).Count
        size_bytes = [long]$size
    }
}

$gitSha = ""
$gitBranch = ""
try {
    $gitSha = (git -C $Root rev-parse --short HEAD 2>$null)
    $gitBranch = (git -C $Root branch --show-current 2>$null)
} catch {}

$pythonVersion = ""
try {
    $pythonVersion = (python --version 2>&1 | Out-String).Trim()
} catch {}

$edEnvSet = @()
Get-ChildItem Env:ED_* -ErrorAction SilentlyContinue | ForEach-Object {
    $edEnvSet += $_.Name
}
$edEnvSet = $edEnvSet | Sort-Object -Unique

$schwabEnvSet = @()
Get-ChildItem Env:SCHWAB_* -ErrorAction SilentlyContinue | ForEach-Object {
    $schwabEnvSet += $_.Name
}
$schwabEnvSet = $schwabEnvSet | Sort-Object -Unique

$dbPath = $env:ED_CONSOLE_DB
if (-not $dbPath) {
    $dbPath = Join-Path $Root "data\ed_console.db"
}
$dbExists = Test-Path -LiteralPath $dbPath
$dbSize = 0
if ($dbExists) {
    $dbSize = (Get-Item -LiteralPath $dbPath).Length
}

$manifest = [ordered]@{
    generated_at_utc = (Get-Date).ToUniversalTime().ToString("o")
    repo_root = $Root
    git_branch = $gitBranch
    git_commit = $gitSha
    python = $pythonVersion
    ed_env_vars_set = $edEnvSet
    schwab_env_vars_set = $schwabEnvSet
    database = @{
        path = $dbPath
        exists = $dbExists
        size_bytes = [long]$dbSize
    }
    secrets_on_disk = @{
        dot_env = (Test-Path -LiteralPath (Join-Path $Root ".env"))
        schwab_token_json = (Test-Path -LiteralPath (Join-Path $Root "schwab_token.json"))
    }
    model_paths = @(
        (Get-DirStats "models/active"),
        (Get-DirStats "models/active_5c"),
        (Get-DirStats "models/active_15c"),
        (Get-DirStats "models/active_60c"),
        (Get-DirStats "models/parallel"),
        (Get-DirStats "models/cascade"),
        (Get-DirStats "models/arch_competition"),
        (Get-DirStats "models/cache")
    )
    claude_local = @{
        settings_local_json = (Test-PathExists ".claude/settings.local.json")
        scheduled_tasks_lock = (Test-PathExists ".claude/scheduled_tasks.lock")
    }
    notes = @(
        "This file is gitignored. Commit code/docs only; back up DB and secrets separately.",
        "See docs/host/BACKUP_AND_MIRROR.md"
    )
}

$json = $manifest | ConvertTo-Json -Depth 6
$outPath = Join-Path $Root $OutFile
Set-Content -LiteralPath $outPath -Value $json -Encoding utf8
Write-Host "Wrote $outPath"
