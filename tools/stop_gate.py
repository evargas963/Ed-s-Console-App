"""Stop hook: a turn ends only when ruff and the touched test files pass.

Reads the hook's JSON on stdin. When `stop_hook_active` is true (this hook already kept the turn going
once), it lets the turn end, so it cannot loop. The touched files: the working tree's changes and
untracked files, and what the branch changed since it left origin/main. Ruff (the commit hook's
selection) runs on the touched .py files; pytest on the touched test files. A failure goes to stderr
with exit 2: the turn goes on.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SELECT = "F401,F821,E9"
OFFLINE = {"ED_CI_OFFLINE": "1", "SCHWAB_API_KEY": "ci-not-live-placeholder",
           "SCHWAB_APP_SECRET": "ci-not-live-placeholder"}


def _git(*args: str) -> list[str]:
    out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [line for line in out.splitlines() if line.strip()]


def touched_python() -> list[str]:
    """The .py files this worktree changed: uncommitted, untracked, and on the branch since origin/main."""
    names = set(_git("diff", "--name-only", "origin/main...HEAD"))
    names |= {line[3:].split(" -> ")[-1] for line in _git("status", "--porcelain", "--untracked-files=all")}
    return sorted(n for n in names if n.endswith(".py") and (ROOT / n).is_file())


def tests_for(touched: list[str]) -> list[str]:
    """The touched test files; the full suite is the before-done skill's and CI's."""
    return sorted(p for p in touched if p.startswith("tests/") and Path(p).name.startswith("test_"))


def failures(touched: list[str]) -> list[str]:
    """Each failing check's output: ruff on the touched files, then their tests."""
    py = [sys.executable, "-m"]
    out = []
    ruff = subprocess.run(py + ["ruff", "check", *touched, "--select", SELECT], cwd=ROOT,
                          capture_output=True, text=True)
    if ruff.returncode != 0:
        out.append(f"ruff ({SELECT}):\n{ruff.stdout}{ruff.stderr}")
    tests = tests_for(touched)
    if tests:
        run = subprocess.run(py + ["pytest", "-q", "-p", "no:cacheprovider", "-n", "8", "--dist", "loadfile",
                                   *tests], cwd=ROOT, capture_output=True, text=True,
                             env={**os.environ, **OFFLINE})
        if run.returncode != 0:
            out.append(f"pytest on {len(tests)} test files:\n" + "\n".join(run.stdout.splitlines()[-40:]))
    return out


def main() -> int:
    if json.load(sys.stdin).get("stop_hook_active") is True:
        return 0
    touched = touched_python()
    if not touched:
        return 0
    failed = failures(touched)
    if not failed:
        return 0
    sys.stderr.write("The turn goes on: ruff and the touched test files must pass.\n\n" + "\n\n".join(failed))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
