"""AGENTS.md Before writing code: a pull request that changes product code proves it with a test that fails on
the old code.

The PR's changed and added files under tests/ are laid over a checkout of the base, and the PR's
changed test files run there: pytest files (tests/**/test_*.py) with this interpreter, Playwright
specs (tests/e2e/*.spec.js) with the repository's installed Playwright, against a console served
from the base. At least one test must fail or error on the base; a change whose every test
already passed before proves nothing about that change. The same tests passing on the PR is the
full suite's job (the required pytest-full check). A run that gives no result (no test ran, e.g. a
conftest that cannot load on the base) proves nothing and is refused. A PR that adds no line to any
product file and changes no test or only deletes whole tests has nothing to fail before: it passes
here, and names the existing tests that cover it under "End-to-end test:" (tools/check_end_to_end.py).
"Only deletes whole tests": no line added under tests/ (`git diff --numstat`), and every changed file
under tests/ is a pytest file (tests/**/test_*.py) that is deleted, or that equals, as parsed code,
its base with whole top-level definitions removed (tests, helpers, fixtures, imports, constants) that
no name, attribute, parameter or string left in the file names (a fixture's `name=` counts as a name
it defines), none an autouse fixture, setup_module, teardown_module, setup_function,
teardown_function, a pytest* name or a * import. Any other change under tests/ (conftest.py, a
helper module or fixture data changed or deleted, a line removed inside a test, helper or fixture
that stays) keeps the rule above. A test module that cannot import on the base counts as failing
there (a test of new code cannot import the old code).

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
from check_end_to_end import ToolError, _git, is_product, numstat  # noqa: E402


def changed(root: Path, base: str) -> list[str]:
    return [f for f in _git(root, "diff", "--name-only", "--diff-filter=AMR", f"{base}...HEAD").splitlines() if f]


#: the module-level functions pytest calls by name, with no test naming them
XUNIT = frozenset({"setup_module", "teardown_module", "setup_function", "teardown_function"})


def _keyword(node: ast.stmt, arg: str) -> list[ast.expr]:
    """The values of keyword `arg` in the decorator calls of `node` (`autouse=`, a fixture's `name=`)."""
    decorators = getattr(node, "decorator_list", [])
    return [k.value for d in decorators if isinstance(d, ast.Call) for k in d.keywords if k.arg == arg]


def _defined(node: ast.stmt) -> set[str]:
    """The names a top-level statement defines (a fixture's `name=` too); empty for one that does
    anything else (a call, an if)."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {node.name} | {v.value for v in _keyword(node, "name")
                              if isinstance(v, ast.Constant) and isinstance(v.value, str)}
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return {(a.asname or a.name).split(".")[0] for a in node.names}
    targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
    return {t.id for t in targets} if targets and all(isinstance(t, ast.Name) for t in targets) else set()


def _referenced(tree: ast.Module) -> set[str]:
    """Every name, attribute, parameter and string in a module: each way a test can reach a definition."""
    found = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Name):
            found.add(n.id)
        elif isinstance(n, ast.Attribute):
            found.add(n.attr)
        elif isinstance(n, ast.arg):
            found.add(n.arg)
        elif isinstance(n, ast.Constant) and isinstance(n.value, str):
            found.add(n.value)
    return found


def _removable(node: ast.stmt, kept: set[str]) -> bool:
    """A top-level definition (a test, a helper, a fixture, an import, a constant) that no name, attribute,
    parameter or string left in the file names, and that is not an autouse fixture, a `XUNIT` function,
    a pytest* name or a * import."""
    names = _defined(node)
    if not names or "*" in names or names & XUNIT or any(n.startswith("pytest") for n in names):
        return False
    return not _keyword(node, "autouse") and not names & kept


def _show(root: Path, rev: str, path: str) -> str | None:
    shown = subprocess.run(["git", "show", f"{rev}:{path}"], cwd=root, capture_output=True,
                           text=True, encoding="utf-8")
    return shown.stdout if shown.returncode == 0 else None


def only_deletes_whole_tests(root: Path, base: str, path: str) -> bool:
    """`path`, under tests/, is a pytest file that is deleted, or that is its base module with only whole
    top-level statements removed, each one `_removable` (compared as parsed code: comments aside).
    Any other file under tests/ (conftest.py, a helper module, fixture data) is never only a deletion."""
    now = _show(root, "HEAD", path)
    if now is None:
        return is_pytest(path)
    before = _show(root, _git(root, "merge-base", base, "HEAD").strip(), path)
    if not is_pytest(path) or before is None:
        return False
    new_tree = ast.parse(now)
    new, kept = [ast.dump(n) for n in new_tree.body], _referenced(new_tree)
    i = 0
    for node in ast.parse(before).body:
        if i < len(new) and ast.dump(node) == new[i]:
            i += 1
        elif not _removable(node, kept):
            return False
    return i == len(new)


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
    product = [f for f in files if is_product(f)]
    if not product:
        return []
    added = numstat(root, base)
    in_tests = [f for f in added if f.startswith("tests/")]
    if not any(n for f, n in added.items() if is_product(f) or f in in_tests) \
            and all(only_deletes_whole_tests(root, base, f) for f in in_tests):
        print(f"product code only removed ({', '.join(sorted(f for f in added if is_product(f)))}) and every changed "
              "test file only lost whole definitions nothing left in it names: nothing to fail before; the "
              "existing tests its End-to-end test: names are checked by check_end_to_end.py")
        return []
    tests = [f for f in files if is_test(f)]
    if not tests:
        return [f"product code changed ({', '.join(product)}) but no test under tests/ changed"]
    run, failed = failures_on_base(root, base, files, tests)
    if not run:
        return [f"no changed test ran on the old code ({', '.join(tests)}): the run gave no result, so "
                "nothing proves this change"]
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
