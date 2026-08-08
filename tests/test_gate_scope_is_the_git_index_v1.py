"""RC-286 — a gate's idea of "repo-wide" must be the git index, in EVERY gate.

RC-274 found the silent-zero gate walking `scratchpad/` — a directory `.gitignore:202`
excludes and which holds 0 tracked files — and fixed it by DEFINITION rather than by adding
a skip entry: repo-wide became `git ls-files`, which cannot drift. That repair was applied
to the one gate then failing. `tools/anti_pattern_sweep.py`, one directory away, kept its
`ROOT.rglob("*.py")` plus a hand-maintained `SKIP_DIR_PARTS`, and has been failing on
throwaway audit scripts ever since.

THE PATTERN THIS FILE EXISTS TO STOP. Three times in two days I have fixed the instance in
front of me and not swept the class: RC-283 (a cleanup tool that reached one table of
three), RC-284 (a harness that typed one outcome), and this. A root cause gets written, a
mechanism gets designed, and its second instance stays broken because nothing asked where
else the shape lives. So the last test here asks that question mechanically.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.anti_pattern_sweep import iter_py_files  # noqa: E402


def _tracked() -> set[str]:
    out = subprocess.run(["git", "ls-files", "-z", "--", "*.py"],
                         cwd=REPO, capture_output=True, text=True, check=True).stdout
    return {p for p in out.split("\0") if p}


def test_untracked_scratch_is_out_of_scope():
    """The defect: gitignored scratch judged as production code."""
    rels = {p.relative_to(REPO).as_posix() for p in iter_py_files(production_only=True)}
    assert not [r for r in rels if r.startswith("scratchpad/")], (
        "untracked scratch is back inside a repo-wide product gate")


def test_the_scope_is_exactly_what_git_tracks():
    """Not a subset that happens to exclude scratch — the index itself."""
    rels = {p.relative_to(REPO).as_posix() for p in iter_py_files(production_only=False)}
    assert rels <= _tracked(), (
        f"the scanner reaches files git does not track: {sorted(rels - _tracked())[:5]}")


def test_the_scan_did_not_collapse():
    """A gate that passes because it stopped looking is worse than one that fails."""
    rels = {p.relative_to(REPO).as_posix() for p in iter_py_files(production_only=True)}
    assert len(rels) > 200, f"production scope collapsed to {len(rels)} files"
    for must in ("server.py", "math_levels.py", "lstm_data.py", "terrain_engine.py",
                 "desk_store.py", "db.py"):
        assert must in rels, f"{must} fell out of the production scan"


def test_tools_and_tests_stay_out_of_the_production_scan():
    rels = {p.relative_to(REPO).as_posix() for p in iter_py_files(production_only=True)}
    assert not [r for r in rels if r.startswith(("tools/", "tests/"))]


def _filesystem_enumerating_scanners() -> list[str]:
    """Every TRACKED module under tools/ or tests/ that builds its own file list from disk.

    RC-307 widened this. It read `(REPO / "tools").glob("*.py")` — the directory the RC-286
    instance happened to live in — so the same shape inside `tests/` went uncounted, and
    `tests/test_coh_sa2_et_authority.py` spent that time failing on 93 untracked scratch
    scripts. A sweep that inherits its instance's neighbourhood cannot find the class, which
    is the exact failure RC-286's docstring names. The scope is now the git index, which is
    also the answer this whole file is about.
    """
    tracked = subprocess.run(
        ["git", "ls-files", "-z", "--", "tools/*.py", "tests/*.py"],
        cwd=REPO, capture_output=True, text=True, check=True).stdout
    found: list[str] = []
    for rel in sorted(p for p in tracked.split("\0") if p):
        path = REPO / rel
        if not path.exists():
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "rglob"):
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and str(arg.value).endswith(".py"):
                        found.append(f"{rel}:{node.lineno}")
    return found


def test_the_two_repo_wide_product_gates_use_the_index():
    """The gates that make repo-wide CLAIMS about product code must not guess the scope.

    Narrowed deliberately, and the narrowing is the honest part. The class sweep below
    found 20 further sites; asserting all of them here would ship a permanently-red test,
    and exempting all of them would be the allowlist habit this session keeps removing.
    So this pins what is actually fixed, and the remainder is MEASURED, not waved away.
    """
    for rel in ("tools/anti_pattern_sweep.py",):
        src = (REPO / rel).read_text(encoding="utf-8", errors="replace")
        assert "git ls-files" in src, f"{rel} no longer scopes to the git index"
        assert 'ROOT.rglob("*.py")' not in src, f"{rel} enumerates the filesystem again"
    gate = (REPO / "tests" / "test_ohlcv_schwab_first.py").read_text(
        encoding="utf-8", errors="replace")
    assert "git ls-files" in gate, "the silent-zero gate lost its index scope (RC-274)"


def test_the_remaining_filesystem_scanners_are_measured_not_forgotten():
    """RC-286's class sweep — the question I failed to ask three times running.

    A scanner that builds its own file list re-decides what "the repository" means, and
    every such list is correct exactly once. This does not fail the build for the ones
    still outstanding, because I have not read them and do not know which genuinely need
    the filesystem — `check_credential_leak` legitimately asks about UNTRACKED files, a
    question the index cannot answer. What it does is refuse to let the count drift out of
    sight: the number is asserted, so the next person to add one has to come here.
    """
    found = _filesystem_enumerating_scanners()
    assert len(found) == 48, (
        f"the filesystem-enumerating scanner count moved from the 48 measured under RC-307 "
        f"to {len(found)}. If you FIXED some, lower this number and say so in the row. If "
        f"you ADDED one, use `git ls-files` instead — this is the RC-274 -> RC-286 loop.\n"
        + "\n".join(found))
    # RC-307: the number moved from 21 to 48 because the SCOPE moved, not because 27
    # scanners appeared. RC-286 counted `(REPO / "tools").glob("*.py")` and the same shape
    # lives 27 more times under tests/ — where it had already turned
    # tests/test_coh_sa2_et_authority.py red on untracked scratch. Both directories are
    # counted from the git index now, so neither can hide the other's drift.
    by_dir = {rel.split("/")[0] for rel in found}
    assert by_dir <= {"tools", "tests"}, f"the sweep reached outside its scope: {by_dir}"
    assert "tests/test_coh_sa2_et_authority.py" not in {f.split(":")[0] for f in found}, (
        "the ET-authority scanner is walking the filesystem again (RC-307)")
    assert "tools/anti_pattern_sweep.py" not in {f.split(':')[0] for f in found}, (
        "the gate RC-286 repaired is enumerating the filesystem again")
