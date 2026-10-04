"""CLAUDE.md rule 8: a pull request that changes product code proves it with a test that fails on
the old code.

The PR's changed and added files under tests/ are laid over a checkout of the base, and the PR's
changed test files (tests/**/test_*.py) run there. At least one test must fail or error on the
base; a change whose every test already passed before proves nothing about that change. The
same tests passing on the PR is the full suite's job (the required pytest-full check).

Python tests only: every value the page shows is served (AGENTS.md rule 4), so a screen change
is proven through the route that serves it.

    python tools/check_fails_before.py --base origin/main
Exit 0: proven, or no product code changed. Exit 1: not proven, with the reason. Exit 2: the
check itself failed (git unavailable, the base unknown).
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_end_to_end import ToolError, _git, is_product  # noqa: E402


def changed(root: Path, base: str) -> list[str]:
    return [f for f in _git(root, "diff", "--name-only", "--diff-filter=AMR", f"{base}...HEAD").splitlines() if f]


def is_test(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return path.startswith("tests/") and name.startswith("test_") and name.endswith(".py")


def failures_on_base(root: Path, base: str, files: list[str], tests: list[str]) -> tuple[int, int]:
    """(tests run, tests failed or errored) of `tests` on the base with the PR's test files."""
    tmp = Path(tempfile.mkdtemp(prefix="fails-before-"))
    tree = tmp / "base"
    _git(root, "worktree", "add", "--detach", str(tree), base)
    try:
        for f in files:
            if f.startswith("tests/"):
                (tree / f).parent.mkdir(parents=True, exist_ok=True)
                (tree / f).write_bytes(subprocess.run(["git", "show", f"HEAD:{f}"], cwd=root,
                                                      capture_output=True, check=True).stdout)
        report = tmp / "report.xml"
        subprocess.run([sys.executable, "-m", "pytest", *tests, "-q", "-p", "no:cacheprovider",
                        f"--junitxml={report}"], cwd=tree, capture_output=True, env=os.environ.copy())
        if not report.exists():
            return 0, 0
        suites = ET.parse(report).getroot()
        run = failed = 0
        for s in suites.iter("testsuite"):
            run += int(s.get("tests", 0))
            failed += int(s.get("failures", 0)) + int(s.get("errors", 0))
        return run, failed
    finally:
        _git(root, "worktree", "remove", "--force", str(tree))
        shutil.rmtree(tmp, ignore_errors=True)


def violations(root: Path, base: str) -> list[str]:
    files = changed(root, base)
    product = [f for f in files if is_product(f)]
    if not product:
        return []
    tests = [f for f in files if is_test(f)]
    if not tests:
        return [f"product code changed ({', '.join(product)}) but no test under tests/ changed"]
    run, failed = failures_on_base(root, base, files, tests)
    if not failed:
        return [f"every changed test passes on the old code ({run} run: {', '.join(tests)}): "
                "none of them proves this change"]
    return []


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    a = ap.parse_args(argv)
    try:
        found = violations(Path.cwd(), a.base)
    except (ToolError, subprocess.CalledProcessError) as e:
        print(f"the check failed: {e}", file=sys.stderr)
        return 2
    for v in found:
        print(v)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
