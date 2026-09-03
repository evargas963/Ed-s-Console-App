"""RC-382 — the line-ending lock, driven against real git repositories.

The three occurrences this lock exists to refuse, each reproduced below as a planted
control rather than described:

  1. RC-372         a text-mode restore flipped the real AGENTS.md LF->CRLF every run.
  2. settings.json  an 8-line addition committed as 78 insertions / 71 deletions.
  3. RC-381 slice 1 a 15-line declaration pass committed as 2428 / 2427.

Cases 1 and 2/3 are different shapes and are refused by different clauses: a PURE EOL
REFLOW carries no content change at all, while an EOL STYLE FLIP hides a genuine edit
inside a whole-file reflow. Both must fail; a legitimate edit that preserves the
terminator must pass, or the lock would simply block work.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


TOOL = REPO / "tools" / "check_eol_style_invariant.py"


@pytest.fixture()
def repo(tmp_path):
    """A real git repo with one LF file and one CRLF file already committed."""
    root = tmp_path / "eolrepo"
    root.mkdir()

    def git(*args, check=True):
        r = subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True)
        if check and r.returncode != 0:
            raise AssertionError(f"git {args}: {r.stderr}")
        return r

    git("init", "-b", "main")
    git("config", "user.email", "t@t.t")
    git("config", "user.name", "t")
    # core.autocrlf=false so the blob is exactly what we write — the same setting the
    # real repo runs, and the condition under which occurrence 3 still happened.
    git("config", "core.autocrlf", "false")
    (root / "lf_file.py").write_bytes(b"a = 1\nb = 2\nc = 3\n")
    (root / "crlf_file.py").write_bytes(b"x = 1\r\ny = 2\r\nz = 3\r\n")
    git("add", "-A")
    git("commit", "-m", "seed")
    return root, git


def run_tool(root: Path, *extra: str) -> tuple[int, str]:
    r = subprocess.run(
        [sys.executable, str(TOOL), *extra], cwd=str(root),
        capture_output=True, text=True, check=False,
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def _patch_tool_repo(root: Path):
    """The tool resolves REPO from its own location; run it with cwd inside the scratch
    repo and point it there via git's own discovery by copying it in."""
    dest = root / "tools"
    dest.mkdir(exist_ok=True)
    (dest / "check_eol_style_invariant.py").write_bytes(TOOL.read_bytes())
    return dest / "check_eol_style_invariant.py"


def run_in(root: Path, *extra: str) -> tuple[int, str]:
    tool = _patch_tool_repo(root)
    r = subprocess.run(
        [sys.executable, str(tool), *extra], cwd=str(root),
        capture_output=True, text=True, check=False,
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def test_clean_repo_passes(repo):
    root, _git = repo
    rc, out = run_in(root, "--measure")
    assert rc == 0 and "[PASS]" in out, out


def test_pure_eol_reflow_is_refused(repo):
    """Occurrence 1 (RC-372): content identical, every terminator flipped."""
    root, _git = repo
    p = root / "lf_file.py"
    p.write_bytes(p.read_bytes().replace(b"\n", b"\r\n"))
    rc, out = run_in(root, "--measure")
    assert "PURE EOL REFLOW" in out, out
    assert "lf -> crlf" in out, out


def test_eol_style_flip_hiding_a_real_edit_is_refused(repo):
    """Occurrences 2 and 3: a genuine change PLUS a whole-file reflow."""
    root, _git = repo
    p = root / "lf_file.py"
    body = p.read_bytes().replace(b"b = 2\n", b"b = 22  # real edit\n")
    p.write_bytes(body.replace(b"\n", b"\r\n"))
    rc, out = run_in(root, "--measure")
    assert "EOL STYLE FLIP" in out, out


def test_a_real_edit_preserving_the_terminator_passes(repo):
    """The lock must not block ordinary work — this is the shape every edit should have."""
    root, _git = repo
    p = root / "lf_file.py"
    p.write_bytes(p.read_bytes().replace(b"b = 2\n", b"b = 22  # real edit\n"))
    rc, out = run_in(root, "--measure")
    assert rc == 0 and "[PASS]" in out, out


def test_crlf_file_edited_as_crlf_passes_and_flipped_to_lf_fails(repo):
    """Symmetric: the invariant is 'do not change the style', not 'prefer LF'."""
    root, _git = repo
    p = root / "crlf_file.py"
    p.write_bytes(p.read_bytes().replace(b"y = 2\r\n", b"y = 22  # real edit\r\n"))
    rc, out = run_in(root, "--measure")
    assert rc == 0 and "[PASS]" in out, out

    p.write_bytes(p.read_bytes().replace(b"\r\n", b"\n"))
    rc2, out2 = run_in(root, "--measure")
    assert ("EOL STYLE FLIP" in out2) or ("PURE EOL REFLOW" in out2), out2
    assert "crlf -> lf" in out2, out2


def test_staged_mode_blocks_with_nonzero_exit(repo):
    """--measure reports; the pre-commit path must actually FAIL."""
    root, git = repo
    p = root / "lf_file.py"
    p.write_bytes(p.read_bytes().replace(b"\n", b"\r\n"))
    git("add", "-A")
    rc, out = run_in(root)
    assert rc == 1, f"staged reflow must block the commit, got rc={rc}: {out}"
    assert "PURE EOL REFLOW" in out, out


def test_a_new_file_has_no_prior_style_to_violate(repo):
    root, git = repo
    (root / "brand_new.py").write_bytes(b"q = 1\r\nr = 2\r\n")
    git("add", "-A")
    rc, out = run_in(root)
    assert rc == 0, f"a newly added file cannot flip a style it never had: {out}"


def test_binary_files_are_exempt(repo):
    root, git = repo
    blob = root / "thing.bin"
    blob.write_bytes(bytes([0, 1, 2, 3]) + b"\n" * 5)
    git("add", "-A")
    git("commit", "-m", "add binary")
    blob.write_bytes(bytes([0, 1, 2, 3]) + b"\r\n" * 5)
    rc, out = run_in(root, "--measure")
    assert rc == 0 and "[PASS]" in out, out


def test_a_pinned_path_may_differ_on_disk_without_being_a_violation(repo):
    """RC-383: `text eol=lf` means git normalises into the blob, so worktree CRLF is the
    CONFIGURED state, not a flip. .claude/settings.json lives exactly here."""
    root, git = repo
    (root / ".gitattributes").write_bytes(b"pinned.json text eol=lf\n")
    (root / "pinned.json").write_bytes(b'{\n  "a": 1\n}\n')
    git("add", "-A")
    git("commit", "-m", "pin a path")

    # An external tool rewrites it with platform terminators - exactly what the harness
    # does to settings.json. Nothing about the committed form has changed.
    (root / "pinned.json").write_bytes(b'{\r\n  "a": 1\r\n}\r\n')
    rc, out = run_in(root, "--measure")
    assert rc == 0 and "[PASS]" in out, f"a pinned path was reported as a flip: {out}"


def test_a_pinned_path_with_a_real_content_change_is_still_silent(repo):
    """The case the pre-RC-383 implementation only survived by accident.

    Before the fix, pinned paths escaped only because `git diff --name-only` filters
    normalised files out of the changed list. Give the file a REAL content change and it
    reappears in that list, and the raw byte comparison then fires on a correctly
    configured file. This test fails against the pre-fix code.
    """
    root, git = repo
    (root / ".gitattributes").write_bytes(b"pinned.json text eol=lf\n")
    (root / "pinned.json").write_bytes(b'{\n  "a": 1\n}\n')
    git("add", "-A")
    git("commit", "-m", "pin a path")

    # UNSTAGED and CRLF on disk. This is the discriminating case: staged mode reads the
    # index, which git has already normalised, so the defect cannot show there. Only the
    # worktree comparison sees raw CRLF against an LF blob.
    (root / "pinned.json").write_bytes(b'{\r\n  "a": 2,\r\n  "b": 3\r\n}\r\n')
    rc, out = run_in(root, "--measure")
    assert "EOL STYLE FLIP" not in out, (
        f"a real edit to a PINNED path was reported as a terminator flip — the check is "
        f"judging disk bytes where git judges normalised bytes (RC-383): {out}")
    assert "[PASS]" in out, out


def test_the_live_repo_is_currently_clean():
    """Negative control on the real tree: the lock must not be born failing."""
    rc = subprocess.run(
        [sys.executable, str(TOOL), "--measure"], cwd=str(REPO),
        capture_output=True, text=True, check=False,
    )
    assert "[PASS]" in rc.stdout, rc.stdout + rc.stderr
