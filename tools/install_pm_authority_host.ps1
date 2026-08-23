<#
Host installation for executable PM authority on WINDOWS (Architecture A / RC-459).

COMMITTING THIS SCRIPT DOES NOT CREATE THE BOUNDARY. The boundary exists only after an
ELEVATED operator principal (NOT the assigned AI) runs this, and the HOST ACCEPTANCE
PROOF (reports/pm_authority_external_implementation.md) is measured on the exact SHA.

WHY OWNERSHIP, NOT JUST A DENY ACE (measured 2026-08-23 on a real Windows host):
  With the authority directory owned by the AI's own account, a DENY ACE blocked write,
  overwrite, delete, rename and create — but `icacls <dir> /grant:r <ai>:(F)` SUCCEEDED,
  because an object's OWNER always retains WRITE_DAC and can rewrite its own ACL. So a
  deny ACE alone is NOT a capability boundary on Windows. This installer therefore makes
  BUILTIN\Administrators the OWNER and grants the AI account ReadAndExecute only; the AI
  is a non-owner and cannot re-ACL, take ownership, write, delete, or rename.

Integrity model — identical anchor to the POSIX installer: this script REFUSES to run
unless the tree it runs from is Administrators/SYSTEM-owned (the AI's own checkout is
AI-owned, so running from it aborts), that tree's git HEAD equals ED_PM_REVIEW_COMMIT
(the exact commit the operator reviewed), and the working tree is clean. Root/Admin
therefore never executes an unverified installer from the AI-writable checkout.

Usage — the operator MATERIALIZES THE REVIEWED COMMIT FROM THE REMOTE INTO AN
ADMIN-OWNED STAGING TREE FIRST, then runs THIS script from there (never from the AI
checkout), in an ELEVATED PowerShell:

  $C = '<operator-reviewed PR #181 HEAD commit SHA>'
  git clone <remote-url> C:\ProgramData\ed-console-staging
  git -C C:\ProgramData\ed-console-staging checkout --detach $C
  # pin derived from the REVIEWED commit in admin-owned staging, never the live checkout:
  $PIN = (Get-FileHash C:\ProgramData\ed-console-staging\tools\pm_authority_helper.py -Algorithm SHA256).Hash.ToLower()
  C:\ProgramData\ed-console-staging\tools\install_pm_authority_host.ps1 `
      -ExpectedHelperSha256 $PIN -ReviewCommit $C -AiAccount '<DOMAIN\ai-user>' -Confirm 'ed-console-authority-host'
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ExpectedHelperSha256,
    [Parameter(Mandatory = $true)][string]$ReviewCommit,
    [Parameter(Mandatory = $true)][string]$AiAccount,
    [Parameter(Mandatory = $true)][string]$Confirm
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Fail([string]$msg) { Write-Error "install_pm_authority_host.ps1: $msg"; exit 1 }

$CONFIRM_REQUIRED = 'ed-console-authority-host'
$AUTHORITY_DIR    = Join-Path $env:ProgramData 'ed-console-authority'
$AUTHORITY_FILE   = Join-Path $AUTHORITY_DIR 'pm_mission.json'
$HELPER_DIR       = Join-Path $env:ProgramData 'ed-console-authority-bin'
$HELPER_INSTALL   = Join-Path $HELPER_DIR 'ed_pm_authority_write.py'

if ($Confirm -ne $CONFIRM_REQUIRED) { Fail "set -Confirm $CONFIRM_REQUIRED to proceed (the AI cannot casually lock the host)" }

# --- must be elevated: only an Administrator can assign ownership away from the AI ---
$principal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Fail 'must run ELEVATED (Administrator). A non-elevated run cannot move ownership away from the AI account, and ownership is the boundary.'
}

# --- the AI account must resolve, and must NOT be the identity running this installer ---
try { $aiSid = (New-Object Security.Principal.NTAccount($AiAccount)).Translate([Security.Principal.SecurityIdentifier]) }
catch { Fail "AiAccount '$AiAccount' does not resolve to a Windows principal" }
if ($aiSid -eq $principal.Identity.User) {
    Fail "AiAccount '$AiAccount' is the SAME principal running this installer — a boundary the AI holds is not a boundary. Run as the operator/Administrator, not as the AI account."
}

$SCRIPT_DIR = Split-Path -Parent $PSCommandPath
$REPO_ROOT  = Split-Path -Parent $SCRIPT_DIR
$HELPER_SRC = Join-Path $REPO_ROOT 'tools\pm_authority_helper.py'
$TEMPLATE   = Join-Path $REPO_ROOT 'governance\pm_mission.json'

# ── BOOTSTRAP TRUST ANCHOR ────────────────────────────────────────────────────────
# (1) The tree this script runs from must be Administrators/SYSTEM-owned and must not be
#     writable by the AI account. The AI's own checkout is AI-owned, so it REFUSES here.
$trustedOwners = @('BUILTIN\Administrators', 'NT AUTHORITY\SYSTEM')
foreach ($p in @($SCRIPT_DIR, $REPO_ROOT, $PSCommandPath, $HELPER_SRC)) {
    if (-not (Test-Path -LiteralPath $p)) { Fail "missing $p" }
    $acl = Get-Acl -LiteralPath $p
    if ($trustedOwners -notcontains $acl.Owner) {
        Fail "refusing: '$p' is owned by '$($acl.Owner)', not Administrators/SYSTEM — run from an ADMIN-OWNED staging checkout of the reviewed commit, never the AI-writable checkout"
    }
    foreach ($ace in $acl.Access) {
        if ($ace.AccessControlType -ne 'Allow') { continue }
        if ($ace.IdentityReference.Translate([Security.Principal.SecurityIdentifier]) -ne $aiSid) { continue }
        if ($ace.FileSystemRights.ToString() -match 'Write|Modify|FullControl|Delete|ChangePermissions|TakeOwnership') {
            Fail "refusing: '$p' is writable by the AI account '$AiAccount' ($($ace.FileSystemRights)) — staging must not be AI-writable"
        }
    }
}

# (2) The staging content must be EXACTLY the operator-reviewed commit. A commit SHA is
#     content-addressed, so the AI cannot change what ReviewCommit contains, and it cannot
#     write the admin-owned staging. This binds installer AND helper to the reviewed version.
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Fail 'git required to verify the reviewed commit' }
$head = (& git -C $REPO_ROOT rev-parse HEAD 2>$null)
if ($LASTEXITCODE -ne 0 -or -not $head) { Fail 'cannot read staging git HEAD' }
if ($head.Trim() -ne $ReviewCommit.Trim()) {
    Fail "refusing: staging HEAD ('$($head.Trim())') != operator-reviewed ReviewCommit ('$($ReviewCommit.Trim())') — materialize the exact reviewed commit from the remote"
}
& git -C $REPO_ROOT diff --quiet HEAD --
if ($LASTEXITCODE -ne 0) { Fail "refusing: staging working tree is dirty vs $ReviewCommit — the on-disk files do not match the reviewed commit" }

# --- (0) FREEZE the source ONCE to an admin-owned scratch copy (TOCTOU close) -------
$SCRATCH = Join-Path ([IO.Path]::GetTempPath()) ("ed-pm-" + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $SCRATCH -Force | Out-Null
try {
    $FROZEN = Join-Path $SCRATCH 'ed_pm_authority_write.py'
    Copy-Item -LiteralPath $HELPER_SRC -Destination $FROZEN -Force

    # --- (1) INTEGRITY GATE against the operator-reviewed pin (hash the FROZEN copy) --
    $actual = (Get-FileHash -LiteralPath $FROZEN -Algorithm SHA256).Hash.ToLower()
    if ($actual -ne $ExpectedHelperSha256.Trim().ToLower()) {
        Fail "helper source hash mismatch — refusing.`n  expected: $($ExpectedHelperSha256.Trim().ToLower())`n  actual:   $actual`n  The staging tree does not match the operator-reviewed helper. Do NOT install."
    }

    # --- (2) SELF-CONTAINMENT SMOKE TEST on the FROZEN copy ---------------------------
    # Isolated mode (-I) with a hostile PYTHONPATH shadow of a stdlib name. A self-contained
    # helper prints its stdin-only refusal (rc 2, "PM_AUTHORITY"); anything else aborts.
    $py = (Get-Command python.exe -ErrorAction SilentlyContinue)
    if (-not $py) { Fail 'python.exe not found on PATH (required to smoke-test the helper)' }
    $hostile = Join-Path $SCRATCH 'hostile'
    New-Item -ItemType Directory -Path $hostile -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $hostile 'json.py') -Value 'raise SystemExit("PYTHONPATH shadow executed")' -Encoding utf8
    $errFile = Join-Path $SCRATCH 'smoke.err'
    $prevPP = $env:PYTHONPATH
    $env:PYTHONPATH = $hostile
    try {
        $p = Start-Process -FilePath $py.Source -ArgumentList @('-I', $FROZEN) -NoNewWindow -Wait -PassThru `
             -RedirectStandardInput 'NUL' -RedirectStandardError $errFile -RedirectStandardOutput 'NUL'
        $smokeRc = $p.ExitCode
    } finally { $env:PYTHONPATH = $prevPP }
    $smokeErr = if (Test-Path $errFile) { Get-Content $errFile -Raw } else { '' }
    if ($smokeRc -ne 2 -or $smokeErr -notmatch 'PM_AUTHORITY') {
        Write-Output "--- smoke stderr ---"; Write-Output $smokeErr
        Fail "self-containment smoke test failed (rc=$smokeRc) — helper is not repo-independent; refusing to install"
    }
    if ($smokeErr -match 'shadow executed') { Fail 'hostile PYTHONPATH was executed — refusing to install' }

    # --- (3) authority dir + file: Administrators-OWNED, AI read-only ------------------
    foreach ($d in @($AUTHORITY_DIR, $HELPER_DIR)) {
        if (-not (Test-Path -LiteralPath $d)) { New-Item -ItemType Directory -Path $d -Force | Out-Null }
    }
    if (-not (Test-Path -LiteralPath $AUTHORITY_FILE)) {
        # Seed MINIMALLY: pm=operator + idle. Do NOT import scope_paths/remaining/status from
        # the AI-writable template — only confirm the operator intent pm=operator is present.
        if (Test-Path -LiteralPath $TEMPLATE) {
            $tpl = Get-Content -LiteralPath $TEMPLATE -Raw | ConvertFrom-Json
            if (-not $tpl.pm -or $tpl.pm -ne 'operator') { Fail 'template is not a valid pm=operator document' }
        }
        Set-Content -LiteralPath $AUTHORITY_FILE -Value "{`n  `"pm`": `"operator`",`n  `"status`": `"idle`"`n}" -Encoding utf8
    }

    # --- (4) install the FROZEN, hash-verified, smoke-tested helper -------------------
    Copy-Item -LiteralPath $FROZEN -Destination $HELPER_INSTALL -Force

    # --- (4b) RE-HASH the installed file: it must equal the frozen/verified copy ------
    $installedSha = (Get-FileHash -LiteralPath $HELPER_INSTALL -Algorithm SHA256).Hash.ToLower()
    if ($installedSha -ne $actual) {
        Remove-Item -LiteralPath $HELPER_INSTALL -Force -ErrorAction SilentlyContinue
        Fail "post-install hash mismatch (installed=$installedSha != verified=$actual) — removed; refusing"
    }

    # --- (5) THE BOUNDARY: Administrators OWNS; AI account gets ReadAndExecute only ----
    # Ownership is the load-bearing part (see header): a non-owner cannot rewrite the ACL,
    # take ownership, write, delete or rename. Inheritance is broken so a permissive parent
    # ACL cannot re-grant the AI.
    $admins = New-Object Security.Principal.SecurityIdentifier('S-1-5-32-544')  # BUILTIN\Administrators
    $system = New-Object Security.Principal.SecurityIdentifier('S-1-5-18')      # NT AUTHORITY\SYSTEM
    foreach ($target in @($AUTHORITY_DIR, $AUTHORITY_FILE, $HELPER_DIR, $HELPER_INSTALL)) {
        $acl = Get-Acl -LiteralPath $target
        $acl.SetOwner($admins)                 # OWNERSHIP AWAY FROM THE AI
        $acl.SetAccessRuleProtection($true, $false)   # break inheritance, drop inherited ACEs
        foreach ($ace in @($acl.Access)) { [void]$acl.RemoveAccessRule($ace) }
        $isDir  = (Get-Item -LiteralPath $target) -is [IO.DirectoryInfo]
        $inherit = if ($isDir) { 'ContainerInherit,ObjectInherit' } else { 'None' }
        foreach ($sid in @($admins, $system)) {
            [void]$acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule(
                $sid, 'FullControl', $inherit, 'None', 'Allow')))
        }
        [void]$acl.AddAccessRule((New-Object Security.AccessControl.FileSystemAccessRule(
            $aiSid, 'ReadAndExecute', $inherit, 'None', 'Allow')))
        Set-Acl -LiteralPath $target -AclObject $acl
    }

    Write-Output "installed $AUTHORITY_FILE and $HELPER_INSTALL"
    Write-Output "owner: BUILTIN\Administrators; $AiAccount has ReadAndExecute only"
    Write-Output "helper pin verified (frozen + installed): $actual"
    Write-Output "BOUNDARY IS NOT PROVEN until the HOST ACCEPTANCE PROOF is measured on this SHA."
    Write-Output "REMAINING UNAVOIDABLE OPERATOR STEP: ensure $AiAccount is NOT an Administrator"
    Write-Output "and that every AI execution channel runs as $AiAccount (not elevated)."
}
finally {
    Remove-Item -LiteralPath $SCRATCH -Recurse -Force -ErrorAction SilentlyContinue
}
exit 0
