"""RC-529 — a measurement that did not run is not a measurement that came back clean.

THE CLASS (ported from #219's row 506, re-measured 2026-09-06 on ac3f78fb). A check shells out
to git, keeps only the child's STDOUT, and decides from that text. When the child exits
non-zero it usually prints nothing, so the check reads an empty string and takes the same
branch it takes for a genuinely clean result. Green and "never looked" become byte-identical.

MEASURED, running the real unmodified `tools/check_live_path_is_main.py` in a throwaway repo
on branch main, clean tree, with no resolvable `origin/main`:

    ahead  probe: rc=128 stdout=''
    behind probe: rc=128 stdout=''
    report stdout: ONE-APP LOCK: PASS - the running app is a provable build of origin/main.

Since RC-512 that file is an operator/agent-side REPORT, not a launch gate; a report that
says PASS for a lineage it could not measure is still a wrong answer. Verifying it also
surfaced a second defect in the same helper: `_git` returned `.stdout.strip()`, which removes
the leading status column of `git status --porcelain`, so the FIRST line's `ln[3:]` cut one
character off the filename — ' M static/app.js' arrived as 'tatic/app.js', which fails the
`startswith("static/")` test in `_is_app_code` and was dropped from check C entirely.

The same shape lived in the BLOCKING pre-commit secrets gate: `check_credential_leak._staged_text`
returned `p.stdout or ""` without reading the exit code, so an unreadable staged diff scanned
clean.

Every control here builds a REAL git repository and runs the REAL functions. Each fix also
carries a control that RESTORES the old behaviour and asserts the defect comes back, because a
test that only asserts the new behaviour cannot tell a working fix from a vacuous one.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.check_credential_leak as CL  # noqa: E402
import tools.check_live_path_is_main as CLP  # noqa: E402


def _git(cwd: Path, *a: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *a], cwd=str(cwd), capture_output=True, text=True, timeout=60)


def _repo(tmp_path: Path, name: str) -> Path:
    root = tmp_path / name
    root.mkdir(parents=True)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "a@b.c")
    _git(root, "config", "user.name", "t")
    (root / "server.py").write_text("X = 1\n", encoding="utf-8")
    _git(root, "add", "server.py")
    _git(root, "commit", "-qm", "base")
    return root


def _repo_with_origin(tmp_path: Path, name: str) -> Path:
    """A clone whose origin/main resolves and equals HEAD — the legitimately clean desk."""
    upstream = _repo(tmp_path, name + "_upstream")
    work = tmp_path / name
    subprocess.run(["git", "clone", "-q", str(upstream), str(work)],
                   capture_output=True, text=True, timeout=120)
    _git(work, "config", "user.email", "a@b.c")
    _git(work, "config", "user.name", "t")
    return work


# ── the proven fail-open ───────────────────────────────────────────────────────────────────
def test_an_unmeasurable_lineage_is_a_violation(tmp_path, monkeypatch):
    """origin/main unresolvable, clean tree, on main. The report must REFUSE, not certify."""
    root = _repo(tmp_path, "nolineage")
    monkeypatch.chdir(root)
    bad = CLP.violations()
    assert bad, "a checkout whose lineage cannot be measured was certified as clean"
    assert any("could NOT be measured" in b for b in bad), bad


def test_negative_control_the_old_code_path_was_fail_open_on_this_very_repo(tmp_path, monkeypatch):
    """THE control, and it has to reconstruct BOTH halves of the old code to be honest.

    Monkeypatching `_git` alone is not enough: the old fail-open needed the swallowing helper
    AND the old caller guard `if ahead and ahead != "0"`, where an empty string is falsy and
    therefore silently clean. So the old path is reproduced verbatim here and run against the
    same repository state the real report is asked about."""
    root = _repo(tmp_path, "nolineage_ctl")
    monkeypatch.chdir(root)

    def old_git(*args: str) -> str:
        return subprocess.run(["git", *args], capture_output=True, text=True,
                              encoding="utf-8", errors="replace").stdout.strip()

    old_out: list[str] = []
    ahead = old_git("rev-list", "--count", "origin/main..HEAD")
    if ahead and ahead != "0":
        old_out.append("ahead")
    behind = old_git("rev-list", "--count", "HEAD..origin/main")
    if behind and behind != "0":
        old_out.append("behind")
    porcelain = old_git("status", "--porcelain")
    if [ln for ln in porcelain.splitlines() if ln[3:] and CLP._is_app_code(ln[3:])]:
        old_out.append("dirty")

    assert old_out == [], (
        "the reconstructed old path no longer reproduces the fail-open, so this control is "
        f"not measuring what it claims: {old_out}")
    assert CLP.violations(), (
        "the real report does not refuse the state the old path waved through — the fix is "
        "not load-bearing")


def test_a_genuinely_clean_checkout_still_passes(tmp_path, monkeypatch):
    """Fail-closed must not mean fail-always: a real clone, HEAD == origin/main, clean tree."""
    work = _repo_with_origin(tmp_path, "clean")
    monkeypatch.chdir(work)
    assert CLP.violations() == [], CLP.violations()


def test_a_real_divergence_is_still_reported(tmp_path, monkeypatch):
    """And the check it exists for still fires when the lineage IS measurable and wrong."""
    work = _repo_with_origin(tmp_path, "ahead")
    (work / "server.py").write_text("X = 99\n", encoding="utf-8")
    _git(work, "add", "server.py")
    _git(work, "commit", "-qm", "private divergence")
    monkeypatch.chdir(work)
    bad = CLP.violations()
    assert any("NOT on origin/main" in b for b in bad), bad


# ── the porcelain truncation found while verifying ─────────────────────────────────────────
def test_the_first_dirty_file_keeps_its_whole_name(tmp_path, monkeypatch):
    """`static/app.js` as the ONLY dirty file. Under the old `.strip()` its path arrived as
    'tatic/app.js', missed `startswith("static/")`, and check C reported a clean tree."""
    work = _repo_with_origin(tmp_path, "porcelain")
    (work / "static").mkdir()
    (work / "static" / "app.js").write_text("var a = 1;\n", encoding="utf-8")
    _git(work, "add", "static/app.js")
    _git(work, "commit", "-qm", "add ui")
    _git(work, "push", "-q", "origin", "main")
    (work / "static" / "app.js").write_text("var a = 2;  // uncommitted\n", encoding="utf-8")
    monkeypatch.chdir(work)

    raw = _git(work, "status", "--porcelain").stdout
    assert raw.startswith(" M "), f"fixture assumption broken; porcelain was {raw!r}"

    bad = CLP.violations()
    assert any("static/app.js" in b for b in bad), (
        f"uncommitted UI code was not reported; violations={bad}")


def test_negative_control_the_old_strip_drops_the_first_filenames_leading_char(tmp_path):
    """Isolates the truncation itself, with no dependence on the report's wiring."""
    line = " M static/app.js"
    assert line[3:] == "static/app.js"
    assert line.strip()[3:] == "tatic/app.js"
    assert CLP._is_app_code("static/app.js") is True
    assert CLP._is_app_code("tatic/app.js") is False, (
        "the truncated path is still recognised as app code, so this control proves nothing")


# ── the blocking secrets gate ──────────────────────────────────────────────────────────────
def _staged_diff_fails(monkeypatch, rc: int = 128) -> None:
    def _boom(*a, **k):
        return subprocess.CompletedProcess(a[0] if a else [], rc, "", "fatal: index file corrupt")
    monkeypatch.setattr(CL.subprocess, "run", _boom)


def test_an_unreadable_staged_diff_is_not_a_clean_diff(tmp_path, monkeypatch, capsys):
    """A secrets gate that cannot read the diff must FAIL, never print PASS."""
    _staged_diff_fails(monkeypatch)
    with pytest.raises(CL.StagedDiffUnreadable):
        CL.find_credential_leaks()
    assert CL.main([]) == 1
    err = capsys.readouterr().err
    assert "could not be read" in err
    assert "PASS" not in err


def test_negative_control_returning_stdout_or_empty_restores_the_silent_pass(monkeypatch):
    """Restore `return p.stdout or ""` and the gate reports a clean diff it never read."""
    _staged_diff_fails(monkeypatch)

    def _old_staged_text() -> str:
        p = CL.subprocess.run(["git", "diff", "--cached"], capture_output=True, text=True)
        return p.stdout or ""

    monkeypatch.setattr(CL, "_staged_text", _old_staged_text)
    assert CL.find_credential_leaks() == [], (
        "the old stdout-only _staged_text no longer reproduces the silent pass")
    assert CL.main([]) == 0, "the old code path did not report a clean diff — control is vacuous"


def test_a_readable_diff_with_a_secret_still_fails(monkeypatch):
    """Fail-closed must not swamp the real detection the gate exists for."""
    diff = '+++ b/x.py\n+API_KEY = "abcdefghijklmnop"\n'  # credential-leak-fixture-ok
    assert CL.find_credential_leaks(diff), "a staged secret was not detected"
