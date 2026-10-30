"""AGENTS.md rule 1 and Before writing code: a pull request that changes product code proves it with
an end-to-end path test that fails on the old code, unless it only removes whole undecorated Python
functions or classes and the imports only they used (`deletes_only`), or only fixes what ruff rules
it newly selects find (`rule_fixes_only`): then the full suite and the browser tests, which the
same job runs, are the proof (AGENTS.md "Before writing code").

The PR's changed and added files under tests/ are laid over a checkout of the base, and the PR's
changed end-to-end path tests run there: pytest files (tests/test_data_path_*.py) with this
interpreter, Playwright specs (tests/e2e/*.spec.js) with the repository's installed Playwright,
against a console served from the base. At least one of them must fail or error on the base; a
change whose every test already passed before proves nothing about that change. The same tests
passing on the PR is the full suite's job (the required pytest-full check). A product file whose
code is the same once comments and docstrings are set aside, or whose change is exactly ruff's
safe fixes and ruff format (check_end_to_end.code_identical: .py, .js, .mjs), has nothing for a
test to fail on, and needs none; a deleted product file is a change.

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
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_end_to_end import (  # noqa: E402
    ToolError,
    _git,
    _python_code,
    behavior_change,
    deleted_product,
    pr_files,
)


def changed(root: Path, base: str) -> list[str]:
    return pr_files(root, base, "AMT")


def is_pytest(path: str) -> bool:
    """An end-to-end path test in pytest: tests/test_data_path_*.py (docs/DATA_FLOW.md §2)."""
    name = path.rsplit("/", 1)[-1]
    return (
        path.startswith("tests/")
        and "/" not in path[len("tests/") :]
        and name.startswith("test_data_path_")
        and name.endswith(".py")
    )


def is_spec(path: str) -> bool:
    return (
        path.startswith("tests/e2e/")
        and "/" not in path[len("tests/e2e/") :]
        and path.endswith(".spec.js")
    )


def is_test(path: str) -> bool:
    return is_pytest(path) or is_spec(path)


def pytest_on(tree: Path, tests: list[str], report: Path) -> tuple[int, list[str]]:
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            *tests,
            "-q",
            "-p",
            "no:cacheprovider",
            f"--junitxml={report}",
        ],
        cwd=tree,
        capture_output=True,
        env=os.environ.copy(),
    )
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
    env = {
        **os.environ,
        "PLAYWRIGHT_JSON_OUTPUT_NAME": str(report),
        "PATH": os.path.dirname(sys.executable) + os.pathsep + os.environ.get("PATH", ""),
    }
    subprocess.run(
        [
            "node",
            str(root / "node_modules" / "@playwright" / "test" / "cli.js"),
            "test",
            *specs,
            "--reporter=json",
        ],
        cwd=tree,
        capture_output=True,
        env=env,
    )
    if not report.exists():
        return 0, []
    run, failed = 0, []
    for suite in json.loads(report.read_text(encoding="utf-8")).get("suites", []):
        for spec in _specs(suite):
            run += 1
            if not spec["ok"]:
                failed.append(f"{spec['file']}::{spec['title']}")
    return run, failed


def failures_on_base(
    root: Path, base: str, files: list[str], tests: list[str]
) -> tuple[int, list[str]]:
    """(tests run, tests failed or errored) of `tests` on the base with the PR's test files."""
    tmp = Path(tempfile.mkdtemp(prefix=".fails-before-", dir=root))
    tree = tmp / "base"
    _git(root, "worktree", "add", "--detach", str(tree), base)
    try:
        for f in files:
            if f.startswith("tests/"):
                (tree / f).parent.mkdir(parents=True, exist_ok=True)
                (tree / f).write_bytes(
                    subprocess.run(
                        ["git", "show", f"HEAD:{f}"], cwd=root, capture_output=True, check=True
                    ).stdout
                )
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


_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def _units(tree: ast.Module) -> dict[str, ast.stmt]:
    """A module's top-level functions and classes, and its classes' methods (Class.method)."""
    out: dict[str, ast.stmt] = {}
    for node in tree.body:
        if isinstance(node, _DEFS):
            out[node.name] = node
            if isinstance(node, ast.ClassDef):
                out |= {f"{node.name}.{s.name}": s for s in node.body if isinstance(s, _DEFS)}
    return out


def _binding(n: ast.Import | ast.ImportFrom, a: ast.alias) -> tuple:
    """One name an import binds, as (module, name, alias)."""
    return (
        None if isinstance(n, ast.Import) else "." * n.level + (n.module or ""),
        a.name,
        a.asname,
    )


def _imports(tree: ast.Module) -> dict[tuple, str]:
    """A module's top-level imports, each binding with the name it binds."""
    return {
        _binding(n, a): a.asname or a.name.split(".")[0]
        for n in tree.body
        if isinstance(n, (ast.Import, ast.ImportFrom))
        for a in n.names
    }


def _code_without(tree: ast.Module, units: set[str], bindings: set[tuple]) -> str | None:
    """`tree`'s code, in its order, with the named units and import bindings taken out as nodes."""
    body = []
    for n in tree.body:
        if isinstance(n, _DEFS) and n.name in units:
            continue
        if isinstance(n, ast.ClassDef):
            n.body = [
                s for s in n.body if not (isinstance(s, _DEFS) and f"{n.name}.{s.name}" in units)
            ] or [ast.Pass()]
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            n.names = [a for a in n.names if _binding(n, a) not in bindings]
            if not n.names:
                continue
        body.append(n)
    tree.body = body
    return _python_code(ast.unparse(tree))


def _removes_whole_units(was: str, now: str | None) -> bool:
    """Whether `now` is `was` with whole undecorated functions or classes removed, and the imports
    only they used, and nothing else: both compared as syntax trees in their order (comments and
    docstrings aside, every string as written). `now` None is the file deleted, which holds only
    imports, a docstring and undecorated functions and classes."""
    tree = ast.parse(was)
    if now is None:
        return not any(isinstance(n, _DEFS) and n.decorator_list for n in ast.walk(tree)) and all(
            isinstance(n, (ast.Import, ast.ImportFrom, *_DEFS))
            or (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))
            for n in tree.body
        )
    if _python_code(was) is None or _python_code(now) is None:  # one declares another encoding
        return False
    after = ast.parse(now)
    kept = _units(after)
    removed = {name: u for name, u in _units(tree).items() if name not in kept}
    if not removed or any(u.decorator_list for u in removed.values()):
        return False
    had, has = _imports(tree), _imports(after)
    dropped = had.keys() - has.keys()
    used = {n.id for n in ast.walk(after) if isinstance(n, ast.Name)}
    used_by_removed = {
        n.id for u in removed.values() for n in ast.walk(u) if isinstance(n, ast.Name)
    }
    if any(had[b] in used or had[b] not in used_by_removed for b in dropped):
        return False  # a dropped import still used, or one the removed code never used
    left = _code_without(tree, set(removed), dropped)
    return left is not None and left == _code_without(after, set(), set())


def deletes_only(root: Path, base: str, product: list[str]) -> bool:
    """Whether every changed product file is Python that loses whole undecorated functions or
    classes, and the imports only they used, and nothing else. Removing code
    nothing calls adds no value to check; what could break is a caller, which the full suite and
    the browser tests run. A line removed inside a function, a module-level call (`app.mount`), a
    decorated one (a route) or any page code is a change of behavior, and needs its end-to-end
    test."""
    if not all(f.endswith(".py") for f in product):
        return False
    fork = _git(root, "merge-base", base, "HEAD").strip()
    deleted = set(deleted_product(root, base))
    for f in product:
        try:
            was = _git(root, "show", f"{fork}:{f}")
            now = None if f in deleted else _git(root, "show", f"HEAD:{f}")
            if not _removes_whole_units(was, now):
                return False
        except (ToolError, SyntaxError):  # a new file, or one Python cannot read
            return False
    return True


def _rule_codes(root: Path, config: Path, path: str, text: str) -> set[str] | None:
    """The ruff rules `text` (as `path`) breaks under `config`; None when ruff cannot say."""
    try:
        run = subprocess.run(
            [sys.executable, "-m", "ruff", "check", "--config", str(config)]
            + ["--output-format", "json", "--exit-zero", "--stdin-filename", path, "-"],
            input=text.encode("utf-8"),
            capture_output=True,
            cwd=root,
            timeout=120,
        )
        return {r["code"] for r in json.loads(run.stdout)} if run.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def _enabled_rules(root: Path, config: Path) -> set[str] | None:
    """The rule codes ruff's resolved settings for `config` list as enabled
    (`linter.rules.enabled`); None when ruff cannot say."""
    try:
        run = subprocess.run(
            [sys.executable, "-m", "ruff", "check", "--show-settings", "--config", str(config)]
            + ["pyproject.toml"],
            capture_output=True,
            cwd=root,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    lines = run.stdout.decode("utf-8", "replace").splitlines()
    if run.returncode != 0 or "linter.rules.enabled = [" not in lines:
        return None
    block = lines[lines.index("linter.rules.enabled = [") + 1 :]
    if "]" not in block:
        return None
    return {
        code
        for line in block[: block.index("]")]
        for code in re.findall(r"\(([A-Z]+[0-9]+)\)", line)
    }


def rule_fixes_only(root: Path, base: str, product: list[str]) -> bool:
    """Whether every changed product file is Python whose base version breaks a ruff rule the
    PR's pyproject.toml newly enables (one ruff lists as enabled under it and not under the base's)
    and whose PR version breaks none: a change made for a rule now selected, behaviour unchanged,
    which the full suite and the browser tests prove, as a deletion is. A changed setting of a rule
    already on is not a new rule. That the diff is only the rule's fix, and no other change rides
    with it, no check can tell: the reviewers read it. A deleted file, page code, or a file that
    broke no new rule is not one."""
    deleted = set(deleted_product(root, base))
    if not all(f.endswith(".py") and f not in deleted for f in product):
        return False
    fork = _git(root, "merge-base", base, "HEAD").strip()
    try:
        _git(root, "diff", "--quiet", "HEAD", "--", "pyproject.toml")  # the tree's is the commit's
        old_config = _git(root, "show", f"{fork}:pyproject.toml")
    except ToolError:
        return False
    with tempfile.TemporaryDirectory() as tmp:
        was_config = Path(tmp) / "pyproject.toml"
        was_config.write_bytes(old_config.encode("utf-8"))
        now_on, was_on = (
            _enabled_rules(root, root / "pyproject.toml"),
            _enabled_rules(root, was_config),
        )
    if now_on is None or was_on is None or not now_on - was_on:
        return False
    for f in product:
        try:
            was, now = _git(root, "show", f"{fork}:{f}"), _git(root, "show", f"HEAD:{f}")
        except ToolError:
            return False
        found = _rule_codes(root, root / "pyproject.toml", f, was)
        if found is None or not found & (now_on - was_on):
            return False
        if _rule_codes(root, root / "pyproject.toml", f, now) != set():
            return False
    return True


def violations(root: Path, base: str) -> list[str]:
    files = changed(root, base)
    product = [f for f in files if behavior_change(root, base, f)] + deleted_product(root, base)
    if not product:
        return []
    if deletes_only(root, base, product):
        print(
            f"proven: {', '.join(product)} only lose whole undecorated functions or classes "
            "and their imports; "
            "the full suite and "
            "the browser tests are the proof"
        )
        return []
    if rule_fixes_only(root, base, product):
        print(
            f"proven: {', '.join(product)} change only for ruff rules the PR newly selects; "
            "the full suite and the browser tests are the proof"
        )
        return []
    tests = [f for f in files if is_test(f)]
    if not tests:
        return [
            f"product code changed ({', '.join(product)}) but no end-to-end path test "
            "(tests/test_data_path_*.py or tests/e2e/*.spec.js) changed"
        ]
    run, failed = failures_on_base(root, base, files, tests)
    if not failed:
        return [
            f"every changed test passes on the old code ({run} run: {', '.join(tests)}): "
            "none of them proves this change"
        ]
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
