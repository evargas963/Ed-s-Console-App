# institutional-synthetic-ok: drive the Windows host-boundary contract against tmp
# paths and a synthetic ACL'd directory. The INSTALLED, Administrators-owned authority
# file is the real security boundary; this file is not that boundary.
"""RC-459 — the executable PM authority boundary works on the WINDOWS coding host.

Two classes are proven here:

  (1) REPOSITORY-SIDE (runs on every OS, incl. Linux CI): the reader/helper resolve an
      OS-appropriate, non-repo canonical path; fail closed when it is absent; keep
      pm=operator; and the Windows provisioner script carries the same trust anchor as
      the POSIX one AND assigns OWNERSHIP away from the AI.

  (2) HOST NEGATIVE CONTROLS (Windows only): with a directory ACL'd the way the
      installer ACLs the real one, the *current* (AI) account can READ but cannot
      write / overwrite / delete / rename / create-sibling.

WHY OWNERSHIP IS ASSERTED, NOT JUST A DENY ACE — measured 2026-08-23 on a real Windows
host: with the directory owned by the AI account, a deny ACE blocked write/delete/rename,
but `icacls <dir> /grant:r <ai>:(F)` SUCCEEDED because an OWNER always retains WRITE_DAC.
A deny ACE alone is therefore NOT a capability boundary; ownership by Administrators is.
test_windows_installer_moves_ownership_away_from_the_ai pins that requirement.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.pm_authority as PA  # noqa: E402
import tools.pm_authority_helper as PAH  # noqa: E402

WINDOWS = os.name == "nt"
PS1 = ROOT / "tools" / "install_pm_authority_host.ps1"


# ---------------------------------------------------------------------------
# (1) Repository-side contract — runs on every OS.
# ---------------------------------------------------------------------------

def test_canonical_path_is_os_appropriate_and_outside_the_repo():
    """The authority path is host-owned on BOTH platforms and never inside the checkout."""
    p = PA.CANONICAL_AUTHORITY_PATH
    assert not PA.path_is_inside_repo(p), f"authority path {p} resolved inside the repo"
    text = str(p).replace("\\", "/")
    if WINDOWS:
        assert "ed-console-authority" in text
        # ProgramData is the system-wide location an Administrator can own while the
        # AI account holds read-only; a per-user dir would be AI-owned (=> AI re-ACLable).
        assert "ProgramData" in text or text.lower().startswith("c:/programdata")
    else:
        assert text == "/var/lib/ed-console-authority/pm_mission.json"


def test_helper_and_reader_agree_on_the_canonical_destination():
    """The privileged helper never imports the reader, so its compiled-in constant
    must independently resolve to the SAME host path or writes would land elsewhere."""
    assert str(PAH.CANONICAL_AUTHORITY_PATH) == str(PA.CANONICAL_AUTHORITY_PATH)


def test_unprovisioned_host_fails_closed_not_open():
    """On a host with no boundary provisioned, the reader must DENY (never synthesize)."""
    loaded = PA.load_pm_authority()
    if loaded.ok:
        pytest.skip("this host has a provisioned authority file; absence case not applicable")
    assert loaded.violations
    assert PA.executable_mission() == {}


def test_windows_provisioner_exists_and_carries_the_same_trust_anchor():
    """The Windows installer must not be a weaker sibling of the POSIX one."""
    assert PS1.is_file(), "tools/install_pm_authority_host.ps1 must exist for the Windows host"
    src = PS1.read_text(encoding="utf-8")
    assert "ExpectedHelperSha256" in src, "must require an operator-supplied hash pin"
    assert "Get-FileHash" in src and "hash mismatch" in src, "must verify the helper hash"
    assert "ReviewCommit" in src and "rev-parse HEAD" in src, "must verify HEAD == reviewed commit"
    assert "diff --quiet HEAD" in src, "must refuse a dirty staging tree"
    assert "-I" in src and "PYTHONPATH" in src, "must smoke-test under isolated mode + hostile PYTHONPATH"
    assert "IsInRole" in src and "Administrator" in src, "must require an elevated operator"
    assert "post-install hash mismatch" in src, "must re-hash the INSTALLED file"


def test_windows_installer_moves_ownership_away_from_the_ai():
    """THE load-bearing Windows property (measured): ownership, not just a deny ACE.

    An owner always retains WRITE_DAC, so an AI-owned authority dir can be re-ACLed by
    the AI. The installer must SetOwner to Administrators and grant the AI read-only.
    """
    src = PS1.read_text(encoding="utf-8")
    assert "SetOwner" in src, "installer must assign OWNERSHIP away from the AI account"
    assert "S-1-5-32-544" in src, "owner must be BUILTIN\\Administrators (well-known SID)"
    assert "ReadAndExecute" in src, "the AI account must receive read-only access"
    assert "SetAccessRuleProtection" in src, "inheritance must be broken so a parent ACL cannot re-grant"
    # The AI must not be handed a writing right anywhere in the granted set.
    assert "FullControl', $inherit" not in src.replace('"', "'") or "aiSid" not in src.split("ReadAndExecute")[0][-400:], \
        "the AI account must never be granted FullControl"


def test_windows_installer_parses_under_windows_powershell():
    """RC-460 - MECHANICAL parse proof: hand the ACTUAL committed .ps1 to the REAL
    PowerShell parser and require zero errors. No string/regex inspection.

    WHY THIS EXISTS (host acceptance FAILED on 24965187), root cause BISECTED:
    the file shipped as UTF-8 with NO BOM and carried U+2014 em dashes inside
    DOUBLE-QUOTED STRING LITERALS in code (lines 65/81/87/99/102/114/136/161). Windows
    PowerShell 5.1 decodes a BOM-less .ps1 as ANSI/CP1252, so each `-` (U+2014, bytes
    E2 80 94) became three CP1252 characters ending in U+201D - a character PowerShell
    accepts as a DOUBLE-QUOTE STRING DELIMITER. That closed each string early and
    desynchronized the tokenizer, surfacing as "missing string terminator" at line 182
    and cascading "missing closing '}'" at 134 and 83.

    MEASURED bisect on the committed bytes: removing ONLY the U+2500 box-rules (which
    live in line comments) still FAILED; removing ONLY the U+2014 characters PARSED OK;
    prepending a UTF-8 BOM also PARSED OK - confirming the decode path, and confirming
    that non-ASCII inside a *comment* is harmless while non-ASCII inside a *string* is
    fatal. The installer is nonetheless kept pure ASCII (the conservative invariant, see
    test_windows_installer_bytes_are_encoding_agnostic) so no future edit has to reason
    about which position is safe.

    pwsh 7 defaults BOM-less files to UTF-8 and parsed the broken file clean, so
    verifying with pwsh certified a file Windows PowerShell could not run. This test
    therefore prefers powershell.exe.

    This test therefore prefers `powershell.exe` (Windows PowerShell, the host the
    operator actually runs) and additionally checks `pwsh` when present.
    """
    if not PS1.is_file():
        pytest.fail("tools/install_pm_authority_host.ps1 is missing")

    hosts = [h for h in ("powershell.exe", "pwsh") if shutil.which(h)]
    if not hosts:
        pytest.skip("no PowerShell host available to parse the installer")

    # Parse via the PowerShell AST parser and print structured errors. Read the script
    # path from an environment variable so no quoting/escaping of the path is involved.
    prog = (
        "$p = $env:ED_PS1_UNDER_TEST; "
        "$errors = $null; $tokens = $null; "
        "$null = [System.Management.Automation.Language.Parser]::ParseFile("
        "$p, [ref]$tokens, [ref]$errors); "
        "if ($errors -and $errors.Count -gt 0) { "
        "  foreach ($e in $errors) { "
        "    Write-Output (\"PARSE_ERROR line \" + $e.Extent.StartLineNumber + \": \" + $e.Message) } "
        "  exit 1 } "
        "else { Write-Output (\"PARSE_OK \" + $tokens.Count); exit 0 }"
    )

    env = dict(os.environ, ED_PS1_UNDER_TEST=str(PS1))
    for host in hosts:
        r = subprocess.run(
            [host, "-NoProfile", "-NonInteractive", "-Command", prog],
            capture_output=True, text=True, env=env, timeout=180,
        )
        combined = (r.stdout or "") + (r.stderr or "")
        assert "PARSE_ERROR" not in combined, (
            f"{host} FAILED to parse tools/install_pm_authority_host.ps1:\n{combined.strip()}"
        )
        assert r.returncode == 0 and "PARSE_OK" in combined, (
            f"{host} did not report a clean parse (rc={r.returncode}):\n{combined.strip()}"
        )


def test_windows_installer_bytes_are_encoding_agnostic():
    """RC-460 - the ROOT-CAUSE invariant, checkable on every OS (incl. Linux CI, which
    has no `powershell.exe` and whose `pwsh` cannot reproduce the 5.1 decode).

    A pure-ASCII .ps1 decodes IDENTICALLY as ASCII, UTF-8 and every ANSI codepage, so no
    host can mis-decode it into stray string delimiters. Any non-ASCII byte reintroduces
    the exact class that broke host acceptance on 24965187.
    """
    raw = PS1.read_bytes()
    non_ascii = sorted({b for b in raw if b > 127})
    assert not non_ascii, (
        "tools/install_pm_authority_host.ps1 contains non-ASCII bytes "
        f"{[hex(b) for b in non_ascii[:8]]}. Windows PowerShell 5.1 decodes a BOM-less "
        ".ps1 as ANSI/CP1252, which turns multi-byte UTF-8 into characters including "
        "U+201D that PowerShell treats as STRING DELIMITERS - the RC-460 parse failure. "
        "Keep the installer pure ASCII."
    )


def test_installer_refuses_when_the_ai_is_the_installing_principal():
    """A boundary the AI itself installs (as itself) is not a boundary."""
    src = PS1.read_text(encoding="utf-8")
    assert "SAME principal" in src, "installer must refuse when AiAccount == the running principal"


# ---------------------------------------------------------------------------
# (2) Windows host negative controls — the real OS behaviour.
# ---------------------------------------------------------------------------

pytestmark_windows = pytest.mark.skipif(not WINDOWS, reason="Windows host ACL controls")


def _icacls(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["icacls", *args], capture_output=True, text=True)


@pytestmark_windows
def test_windows_negative_controls_read_only_authority(tmp_path):
    """READ-ONLY GRANT (no deny ACE): the AI can READ executable authority but cannot
    write / overwrite / delete / rename / plant a sibling.

    MEASURED on a real Windows host 2026-08-23 — the shape matters:
      * grant `(RX)` only, NO deny ACE  -> read OK; write/delete/rename/plant all DENIED
      * ANY deny ACE containing `W`     -> ALSO denies READ, which would break the reader
    So the installer grants ReadAndExecute and adds NO deny rule; this test uses the
    same shape. The installer additionally moves OWNERSHIP to Administrators (asserted in
    test_windows_installer_moves_ownership_away_from_the_ai) — an unelevated test cannot
    do that, so ACCESS is proven here and OWNERSHIP is pinned by inspection.
    """
    who = subprocess.run(["whoami"], capture_output=True, text=True).stdout.strip()
    if not who:
        pytest.skip("cannot resolve current principal")

    authority_dir = tmp_path / "ed-console-authority"
    authority_dir.mkdir()
    authority = authority_dir / "pm_mission.json"
    authority.write_text(json.dumps({"pm": "operator", "status": "idle"}), encoding="utf-8")

    d = str(authority_dir)
    # Break inheritance and REMOVE inherited grants, then re-grant read-only across the
    # whole subtree. A dir-only grant leaves inherited Modify ACEs on an already-created
    # file (pytest tmp_path carries them), which would let the write through and make this
    # control vacuous.
    _icacls(d, "/inheritance:r")
    granted = _icacls(d, "/grant:r", f"{who}:(OI)(CI)(RX)", "/T", "/C")
    if granted.returncode != 0:
        pytest.skip(f"cannot apply test ACL on this host: {granted.stdout} {granted.stderr}")
    # Prove the ACL actually took: if this principal can still write, the host/sandbox
    # overrode it and the negative control would be meaningless.
    try:
        with authority.open("a", encoding="utf-8"):
            pass
    except (PermissionError, OSError):
        pass
    else:
        pytest.skip("host/sandbox ACL override: this principal retains write access")

    try:
        # READ still works — the AI must be able to READ executable authority.
        assert json.loads(authority.read_text(encoding="utf-8"))["pm"] == "operator"

        # Every mutation class must be denied by the OS.
        with pytest.raises(PermissionError):
            authority.write_text('{"pm": "claude"}', encoding="utf-8")
        with pytest.raises(PermissionError):
            with authority.open("a", encoding="utf-8") as fh:
                fh.write("x")
        with pytest.raises((PermissionError, OSError)):
            authority.unlink()
        with pytest.raises((PermissionError, OSError)):
            authority.rename(authority_dir / "evil.json")
        with pytest.raises((PermissionError, OSError)):
            (authority_dir / "planted.json").write_text("{}", encoding="utf-8")

        # The document survived every attack unchanged.
        assert json.loads(authority.read_text(encoding="utf-8")) == {
            "pm": "operator", "status": "idle"
        }

        # And the reader, pointed at it, still reports pm=operator (authorized READ path).
        import tools.pm_authority as _PA
        old = _PA.CANONICAL_AUTHORITY_PATH
        try:
            _PA.CANONICAL_AUTHORITY_PATH = authority
            loaded = _PA.load_pm_authority()
            assert loaded.ok and loaded.doc["pm"] == "operator"
        finally:
            _PA.CANONICAL_AUTHORITY_PATH = old
    finally:
        # Restore write access across the subtree, else pytest cannot remove its own
        # tmp_path and emits an rm_rf PermissionError warning (observed 2026-08-23).
        _icacls(d, "/inheritance:e")
        _icacls(d, "/grant", f"{who}:(OI)(CI)(F)", "/T", "/C")


@pytestmark_windows
def test_windows_operator_authorized_mutation_succeeds(tmp_path, monkeypatch):
    """POSITIVE control: an operator-authorized mutation through the privileged helper
    seam is ACCEPTED and lands, and pm=operator is preserved.

    (On the provisioned host this write runs as Administrator through the installed
    helper; here the same code path is exercised against a writable tmp destination.)
    """
    dest = tmp_path / "pm_mission.json"
    dest.write_text(json.dumps({"pm": "operator", "status": "idle"}), encoding="utf-8")
    monkeypatch.setattr(PAH, "CANONICAL_AUTHORITY_PATH", str(dest))

    rc = PAH.run(json.dumps({"pm": "operator", "status": "active", "mission_id": "win-1"}))
    assert rc == 0, "operator-authorized mutation must be ACCEPTED"
    doc = json.loads(dest.read_text(encoding="utf-8"))
    assert doc["pm"] == "operator" and doc["status"] == "active" and doc["mission_id"] == "win-1"

    # NEGATIVE control on the same seam: a pm steal is refused and does NOT land.
    rc_bad = PAH.run(json.dumps({"pm": "claude", "status": "active"}))
    assert rc_bad == 2
    assert json.loads(dest.read_text(encoding="utf-8"))["pm"] == "operator"
