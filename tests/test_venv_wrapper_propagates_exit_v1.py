"""RC-254: the venv wrapper must PROPAGATE its target's exit code.

Why this file exists. `tools/run_with_repo_venv.py` re-exec'd its target with os.execv. On
POSIX that replaces the process, so the target's status becomes the caller's. On Windows
there is no exec — CPython maps os.execv onto the CRT spawn family, so the parent returned
to its caller immediately with status 0 while the target ran detached and its exit code was
discarded.

Every pre-commit hook routed through that wrapper therefore reported "Passed" without the
gate's verdict ever reaching pre-commit: venv-parity, market-correctness, operating-process,
and institutional-correctness — the repo's ONE gate. It was invisible because a no-op gate
and a passing gate look identical from outside; the hook only printed on failure, so
"no output, Passed" read as health.

Every existing test drove the gate FUNCTIONS or invoked the module with `-m`. Nothing ran
the wrapper the way pre-commit runs it, so the seam between hook and gate was the one path
never exercised. These tests are that seam.
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WRAPPER = ROOT / "tools" / "run_with_repo_venv.py"


def _target(tmp_path: Path, code: int) -> Path:
    p = tmp_path / f"exit{code}.py"
    p.write_text(f"import sys\nprint('CHILD-RAN-{code}', flush=True)\nsys.exit({code})\n",
                 encoding="utf-8")
    return p


def test_nonzero_exit_reaches_the_caller(tmp_path: Path) -> None:
    """The property the wrapper exists to provide, and the one nothing asserted."""
    r = subprocess.run([sys.executable, str(WRAPPER), str(_target(tmp_path, 7))],
                       cwd=str(ROOT), capture_output=True, text=True)
    assert r.returncode == 7, (
        f"wrapper returned {r.returncode} for a target that exited 7 — a gate routed through "
        f"it cannot block anything"
    )


def test_the_target_actually_runs_and_its_output_is_not_lost(tmp_path: Path) -> None:
    """A detached child's stdout raced the caller and arrived after it had moved on, so
    captured output was empty. Waiting for the child is what makes the output usable."""
    r = subprocess.run([sys.executable, str(WRAPPER), str(_target(tmp_path, 0))],
                       cwd=str(ROOT), capture_output=True, text=True)
    assert r.returncode == 0
    assert "CHILD-RAN-0" in (r.stdout or ""), (
        "the target's output did not reach the caller — the wrapper did not wait for it"
    )


def test_success_still_reads_as_success(tmp_path: Path) -> None:
    """Negative control: the fix must not make everything fail."""
    r = subprocess.run([sys.executable, str(WRAPPER), str(_target(tmp_path, 0))],
                       cwd=str(ROOT), capture_output=True, text=True)
    assert r.returncode == 0, f"a clean target now reports {r.returncode}"


def test_no_exec_call_remains_on_the_hook_path() -> None:
    """os.execv is the defect itself, not a style question: on this platform it discards the
    exit status. It must not return to either file on the pre-commit path.

    AST, not text: the first draft of this test matched the string "os.exec" and failed on
    the docstring that EXPLAINS the defect — the same describe-it-and-trip-your-own-scanner
    class as RC-253. A call is a call node; prose about a call is not.
    """
    for rel in ("tools/run_with_repo_venv.py", "tools/precommit_institutional.py"):
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        calls = [
            n for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr.startswith("exec")
            and isinstance(n.func.value, ast.Name) and n.func.value.id == "os"
        ]
        assert not calls, (
            f"{rel} still hands off with os.exec* at line(s) "
            f"{[c.lineno for c in calls]} — on Windows that returns 0 to pre-commit "
            f"immediately and the real verdict is thrown away (RC-254)"
        )


def test_the_institutional_hook_carries_the_gates_verdict() -> None:
    """End-to-end at the real seam: the hook's exit code must BE its own verdict (RC-254).

    RC-406 relocated the whole-tree ADDED-VIOLATION delta to CI (hardening.yml, the authority
    before merge); the commit-path hook now reads the enforced-check ROSTER — base (origin/main)
    vs the staged index — and BLOCKS on a deletion/downgrade, the single most valuable thing to
    catch locally (RC-391). RC-254's property is unchanged: the verdict must reach pre-commit,
    not be swallowed. Proven here against the roster check, in BOTH directions, by driving the
    `_git_show` seam so no real index or trunk state is needed.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "precommit_exit", ROOT / "tools" / "precommit_institutional.py")
    seam = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seam)

    both_enforced = 'CHECKS = [("a", check_a, True), ("b", check_b, True)]'
    real_show, real_base = seam._git_show, seam._base_ref
    seam._base_ref = lambda: "origin/main"  # roster comparison needs no live trunk here

    # Intact roster: candidate keeps every enforced check the base carried -> verdict 0 reaches exit.
    seam._git_show = lambda spec: both_enforced
    try:
        assert seam.main() == 0, (
            "an intact roster must pass — the 0 verdict must reach pre-commit (RC-254)")
    finally:
        seam._git_show = real_show

    # A DOWNGRADED check on the staged-index side -> verdict 1 reaches the exit code.
    def _show(spec: str):
        # the staged index (':<path>') drops "b" to advisory; base/HEAD keep both enforced.
        return 'CHECKS = [("a", check_a, True), ("b", check_b, False)]' if spec.startswith(":") else both_enforced

    seam._git_show = _show
    try:
        assert seam.main() == 1, (
            "a deleted/downgraded enforced check must BLOCK — the 1 verdict must reach "
            "pre-commit (RC-254/RC-391)")
    finally:
        seam._git_show, seam._base_ref = real_show, real_base

    # …and the real, unmocked seam still runs end to end and returns an integer verdict.
    hook = subprocess.run([sys.executable, str(ROOT / "tools" / "precommit_institutional.py")],
                          cwd=str(ROOT), capture_output=True, text=True)
    assert isinstance(hook.returncode, int), "the real seam did not produce an exit code"
