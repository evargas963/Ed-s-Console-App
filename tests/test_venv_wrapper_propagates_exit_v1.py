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


def test_a_real_precommit_hook_through_the_wrapper_carries_its_verdict(tmp_path: Path) -> None:
    """End-to-end at the real seam: a hook routed through the wrapper must surface ITS exit
    code (RC-254). The `operating-process` hook is driven in both directions on a scratch
    repository: clean index==WT -> 0; a working-tree edit of an enforcement path -> 1."""
    import shutil

    repo = tmp_path / "r"
    (repo / "tools").mkdir(parents=True)
    shutil.copy(ROOT / "tools" / "operating_process_lock.py", repo / "tools" / "operating_process_lock.py")
    shutil.copy(ROOT / "tools" / "shell_parse.py", repo / "tools" / "shell_parse.py")
    (repo / "tools" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "tools" / "check_institutional_correctness.py").write_text("CHECKS = []\n", encoding="utf-8")
    (repo / "db.py").write_text("x = 1\n", encoding="utf-8")

    def g(*a: str) -> None:
        subprocess.run(["git", *a], cwd=str(repo), check=True, capture_output=True)
    g("init", "-q"); g("config", "user.email", "t@t"); g("config", "user.name", "t")
    g("add", "-A"); g("commit", "-qm", "seed")
    lock = repo / "tools" / "operating_process_lock.py"
    clean = subprocess.run([sys.executable, str(WRAPPER), str(lock), "--pre-commit"],
                           cwd=str(repo), capture_output=True, text=True)
    assert clean.returncode == 0, (clean.stdout, clean.stderr)
    (repo / "db.py").write_text("x = 2\n", encoding="utf-8")        # index != worktree
    dirty = subprocess.run([sys.executable, str(WRAPPER), str(lock), "--pre-commit"],
                           cwd=str(repo), capture_output=True, text=True)
    assert dirty.returncode == 1, (dirty.stdout, dirty.stderr)
