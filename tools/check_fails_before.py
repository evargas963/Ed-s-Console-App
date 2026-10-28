"""AGENTS.md, Before writing code: a pull request that changes product code proves it with a test that
fails on the old code.

The PR's changed and added files under tests/ are laid over a checkout of the base, and the PR's
changed test files run there: pytest files (tests/**/test_*.py) with this interpreter, Playwright
specs (tests/e2e/*.spec.js) with the repository's installed Playwright, against a console served
from the base. At least one test must fail or error on the base; a change whose every test
already passed before proves nothing about that change. The same tests passing on the PR is the
full suite's job (the required pytest-full check). A product file whose code is the same once
comments and docstrings are set aside (check_end_to_end.code_identical: .py, .js, .mjs) has nothing
for a test to fail on, and needs none; a deleted product file is a change. Nor does a Python file the
PR changes only by removing whole top-level functions, classes and assignments (with the imports
they leave unused), when no tracked file still spells a name they bound, as a whole word: the
no-callers proof. Nothing can call what no file names; a test of code nothing calls could not fail.

The base checkout sits inside the repository so that Node finds the repository's node_modules
from it, and runs on the same Python as this check (first on PATH for the spec's console).

    python tools/check_fails_before.py --base origin/main
Exit 0: proven, or no product code changed. Exit 1: not proven, with the reason. Exit 2: the
check itself failed (git unavailable, the base unknown).
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_end_to_end import (  # noqa: E402
    ToolError, _git, behavior_change, deleted_product, pr_files, pr_source, python_tree)


def changed(root: Path, base: str) -> list[str]:
    return pr_files(root, base, "AMT")


def _bound(stmt: ast.stmt) -> "list[str] | None":
    """The names a top-level definition or assignment binds; [] for an import (what a removed import
    bound, a later use would fail to import or ruff's F821 refuses); None for any other statement."""
    if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return [stmt.name]
    if isinstance(stmt, ast.Assign) and all(isinstance(t, ast.Name) for t in stmt.targets):
        return [t.id for t in stmt.targets]
    if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
        return [stmt.target.id]
    if isinstance(stmt, (ast.Import, ast.ImportFrom)):
        return []
    return None


def removed_names(root: Path, base: str, path: str) -> "list[str] | None":
    """The names the PR's change to the Python file `path` removes, when removing whole top-level
    definitions, assignments and imports is all it does (docstrings and comments set aside); None for
    any other change, a file the PR adds or deletes, or one either version of which cannot be read."""
    if not path.endswith(".py"):
        return None
    try:
        old = _git(root, "show", f"{_git(root, 'merge-base', base, 'HEAD').strip()}:{path}")
        new = pr_source(root, path)
    except ToolError:
        return None
    before, after = python_tree(old), python_tree(new)
    if before is None or after is None:
        return None
    kept = [ast.dump(s) for s in after.body]
    names, at = [], 0
    for stmt in before.body:
        if at < len(kept) and ast.dump(stmt) == kept[at]:
            at += 1
            continue
        bound = _bound(stmt)
        if bound is None:
            return None
        names += bound
    return names if at == len(kept) and names else None


def still_named(root: Path, names: list[str]) -> list[str]:
    """Those of `names` a file tracked at the PR's head spells, as a whole word."""
    out = []
    for name in names:
        r = subprocess.run(["git", "grep", "-q", "-w", "-F", "-e", name, "HEAD", "--"], cwd=root,
                           capture_output=True)
        if r.returncode not in (0, 1):
            raise ToolError(f"git grep {name} failed: {r.stderr.decode(errors='replace').strip()}")
        if r.returncode == 0:
            out.append(name)
    return out


def is_pytest(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return path.startswith("tests/") and name.startswith("test_") and name.endswith(".py")


def is_spec(path: str) -> bool:
    return path.startswith("tests/e2e/") and "/" not in path[len("tests/e2e/"):] and path.endswith(".spec.js")


def is_test(path: str) -> bool:
    return is_pytest(path) or is_spec(path)


def pytest_on(tree: Path, tests: list[str], report: Path) -> tuple[int, list[str]]:
    subprocess.run([sys.executable, "-m", "pytest", *tests, "-q", "-p", "no:cacheprovider",
                    f"--junitxml={report}"], cwd=tree, capture_output=True, env=os.environ.copy())
    if not report.exists():
        return 0, []
    run, failed = 0, []
    for case in ET.parse(report).getroot().iter("testcase"):
        run += 1
        if case.find("failure") is not None or case.find("error") is not None:
            failed.append(f"{case.get('classname')}::{case.get('name')}")
    return run, failed


def _specs(suite: dict) -> list[dict]:
    return suite.get("specs", []) + [s for child in suite.get("suites", []) for s in _specs(child)]


def playwright_on(root: Path, tree: Path, specs: list[str], report: Path) -> tuple[int, list[str]]:
    env = {**os.environ, "PLAYWRIGHT_JSON_OUTPUT_NAME": str(report),
           "PATH": os.path.dirname(sys.executable) + os.pathsep + os.environ.get("PATH", "")}
    subprocess.run(["node", str(root / "node_modules" / "@playwright" / "test" / "cli.js"), "test",
                    *specs, "--reporter=json"], cwd=tree, capture_output=True, env=env)
    if not report.exists():
        return 0, []
    run, failed = 0, []
    for suite in json.loads(report.read_text(encoding="utf-8")).get("suites", []):
        for spec in _specs(suite):
            run += 1
            if not spec["ok"]:
                failed.append(f"{spec['file']}::{spec['title']}")
    return run, failed


def failures_on_base(root: Path, base: str, files: list[str], tests: list[str]) -> tuple[int, list[str]]:
    """(tests run, tests failed or errored) of `tests` on the base with the PR's test files."""
    tmp = Path(tempfile.mkdtemp(prefix=".fails-before-", dir=root))
    tree = tmp / "base"
    _git(root, "worktree", "add", "--detach", str(tree), base)
    try:
        for f in files:
            if f.startswith("tests/"):
                (tree / f).parent.mkdir(parents=True, exist_ok=True)
                (tree / f).write_bytes(subprocess.run(["git", "show", f"HEAD:{f}"], cwd=root,
                                                      capture_output=True, check=True).stdout)
        run, failed = 0, []
        pytests = [t for t in tests if is_pytest(t)]
        if pytests:
            n, f = pytest_on(tree, pytests, tmp / "report.xml")
            run, failed = run + n, failed + f
        specs = [t for t in tests if is_spec(t)]
        if specs:
            n, f = playwright_on(root, tree, specs, tmp / "report.json")
            run, failed = run + n, failed + f
        return run, failed
    finally:
        _git(root, "worktree", "remove", "--force", str(tree))
        shutil.rmtree(tmp, ignore_errors=True)


def violations(root: Path, base: str) -> list[str]:
    files = changed(root, base)
    product = [f for f in files if behavior_change(root, base, f)] + deleted_product(root, base)
    uncalled = {}
    for f in product:
        names = removed_names(root, base, f)
        if names is not None and not still_named(root, names):
            uncalled[f] = names
    for f, names in uncalled.items():
        print(f"proven: {f} only removes {', '.join(names)}, which no tracked file names")
    product = [f for f in product if f not in uncalled]
    if not product:
        return []
    tests = [f for f in files if is_test(f)]
    if not tests:
        return [f"product code changed ({', '.join(product)}) but no test under tests/ changed"]
    run, failed = failures_on_base(root, base, files, tests)
    if not failed:
        return [f"every changed test passes on the old code ({run} run: {', '.join(tests)}): "
                "none of them proves this change"]
    print(f"proven: {len(failed)} of {run} changed tests fail on the old code: {'; '.join(failed)}")
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
