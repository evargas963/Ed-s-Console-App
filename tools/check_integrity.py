"""AGENTS.md rule 15: what a change may not take from its tests.

Run from the base by `.github/workflows/locks.yml`; the head is read as data, none of its code runs.

Test integrity, every pull request:
   - an assertion of a test that survives is not lost. A test is its function name in Python and
     its title in a Playwright spec, across every changed test file, so a moved test is the same
     test and a rewritten one may restate its assertions. An assertion gone with its test, or
     with a function it calls that this change deleted, is not judged, nor a test renamed or
     disabled with its assertions kept: a test renamed and one deleted beside a new one read the
     same to a machine;
   - no test is another test again: the same code, arguments and decorators, in a file whose
     other top-level code (its imports, constants, fixtures and helpers; its docstring aside) is
     the same (every test file at the head);
   - no line added to code skips a test or leaves a deferred-work marker.

    python tools/check_integrity.py --base <rev>

Exit 0: clean. Exit 1: each violation on its own line. Exit 2: the check itself failed.
"""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from pathlib import Path

CODE_SUFFIXES = (".py", ".js", ".mjs", ".html", ".yml")
PYTHON_TESTS = re.compile(r"^tests/.*\.py$")
JS_TESTS = re.compile(r"^tests/e2e/.*\.spec\.js$")
MARKERS = re.compile(
    r"pytest\.mark\.skip|skipif|\bskip\(|unittest\.skip|importorskip|xfail"
    r"|\b(?:test|describe|it)\.(?:skip|fixme|fail)\b|\bx(?:it|describe)\b|\bTODO\b|\bFIXME\b"
)
CALLED = re.compile(r"(\w+)\(")
JS_TEST = re.compile(r"""\btest(?:\.\w+)?\(\s*(['"`])(.*?)(?<!\\)\1""", re.S)
JS_EXPECT = re.compile(r"\bexpect(?:\.\w+)?\([^;]*;")
#: the head's own attributes and drivers do not decide what the diff shows
DIFF = ("diff", "-U0", "--text", "--no-ext-diff", "--no-textconv")


class ToolError(Exception):
    def __init__(self, what: str, why: Exception) -> None:
        super().__init__(f"{what} failed: {why}")


def _git(root: Path, *args: str) -> str:
    try:
        done = subprocess.run(
            ["git", "-c", "core.quotePath=false", *args], cwd=root, check=True, capture_output=True
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        raise ToolError(" ".join(args), e) from e
    # bytes: text mode would break a line at a bare CR, and --text prints a binary file's bytes
    return done.stdout.decode("utf-8", "replace")


def changed(root: Path, base: str) -> list[str]:
    out = _git(root, "diff", "--name-only", "-z", "--no-renames", f"{base}...HEAD")
    return [name for name in out.split("\0") if name]


def _at(root: Path, rev: str, path: str) -> str | None:
    """`path` at `rev`, or None where it does not exist."""
    held = _git(root, "ls-tree", "--name-only", rev, "--", path)
    return _git(root, "show", f"{rev}:{path}") if held else None


def _test_functions(source: str):
    """Each test function of a Python test file, as its syntax tree reads it."""
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith(
            "test"
        ):
            yield node


def python_assertions(source: str) -> dict[str, set[str]]:
    """{test name: its assertions, as the syntax tree reads them}."""
    found: dict[str, set[str]] = {}
    for node in _test_functions(source):
        held = found.setdefault(node.name, set())
        for inner in ast.walk(node):
            if isinstance(inner, ast.Assert):
                held.add(ast.unparse(inner.test))
            elif (
                isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Attribute)
                and inner.func.attr.startswith("assert")
            ):
                held.add(ast.unparse(inner))
    return found


def js_assertions(source: str) -> dict[str, set[str]]:
    """{test title: its expect statements, spacing aside}. Best effort: a test runs to the next."""
    tests = list(JS_TEST.finditer(source))
    found: dict[str, set[str]] = {}
    for i, test in enumerate(tests):
        end = tests[i + 1].start() if i + 1 < len(tests) else len(source)
        held = found.setdefault(test.group(2), set())
        held.update(
            " ".join(m.group().split()) for m in JS_EXPECT.finditer(source, test.end(), end)
        )
    return found


def _assertions(root: Path, rev: str, names: list[str]) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for name in names:
        source = _at(root, rev, name)
        if source is None:
            continue
        reader = js_assertions if JS_TESTS.match(name) else python_assertions
        try:
            read = reader(source)
        except SyntaxError as e:
            raise ToolError(f"{rev}:{name}", e) from e
        for test, held in read.items():
            found.setdefault(test, set()).update(held)
    return found


def _definitions(root: Path, rev: str, names: list[str]) -> set[str]:
    found: set[str] = set()
    for name in names:
        source = _at(root, rev, name)
        if source is None:
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError as e:
            raise ToolError(f"{rev}:{name}", e) from e
        found.update(
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        )
    return found


def lost_assertions(root: Path, base: str, files: list[str]) -> list[str]:
    tests = [f for f in files if PYTHON_TESTS.match(f) or JS_TESTS.match(f)]
    product = [f for f in files if f.endswith(".py") and not f.startswith("tests/")]
    deleted = _definitions(root, base, product) - _definitions(root, "HEAD", product)
    before = _assertions(root, base, tests)
    after = _assertions(root, "HEAD", tests)
    out = []
    for test in sorted(before.keys() & after.keys()):
        lost = [
            a
            for a in sorted(before[test] - after[test])
            if not deleted.intersection(CALLED.findall(a))
        ]
        # an assertion corrected or strengthened is one for one; only a net loss is a loss
        if len(lost) > len(after[test] - before[test]):
            out.extend(f"{test}: assertion lost: {a}" for a in lost)
    return out


def added_markers(root: Path, base: str) -> list[str]:
    out = []
    path, in_hunk = "", False
    for line in _git(root, *DIFF, "--no-renames", f"{base}...HEAD").split("\n"):
        if line.startswith("diff --git "):
            in_hunk = False
        elif line.startswith("@@ "):
            in_hunk = True
        elif not in_hunk and line.startswith("+++ "):
            path = line.removeprefix("+++ b/").removesuffix("\t").strip('"')
        elif in_hunk and line.startswith("+") and path.endswith(CODE_SUFFIXES):
            if MARKERS.search(line):
                out.append(f"{path}: skip or deferred-work marker added: {line[1:].strip()[:90]}")
    return out


def duplicate_tests(root: Path) -> list[str]:
    """Return each Python test of the head that is another one again.

    The same code, arguments and decorators once its name and docstring are set aside, in a file
    importing the same names, over every test file.
    """
    seen: dict[str, list[str]] = {}
    for name in _git(root, "ls-tree", "-r", "-z", "--name-only", "HEAD").split("\0"):
        if not PYTHON_TESTS.match(name):
            continue
        source = _git(root, "show", f"HEAD:{name}")
        # the same body tests different code or data when the file's other top-level code differs:
        # its imports, constants, fixtures and helpers; not its tests, not its docstring
        tree = ast.parse(source)
        top = tree.body[1:] if ast.get_docstring(tree) else tree.body
        imports = "".join(
            ast.dump(n)
            for n in top
            if not (
                isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name.startswith("test")
            )
        )
        for node in _test_functions(source):
            body = node.body[1:] if ast.get_docstring(node) else node.body
            key = imports + ast.dump(ast.Module(body=body, type_ignores=[]))
            key += "".join(ast.dump(part) for part in (node.args, *node.decorator_list))
            seen.setdefault(key, []).append(f"{name}::{node.name}")
    return [f"a test duplicated: {', '.join(same)}" for same in seen.values() if len(same) > 1]


def violations(root: Path, base: str) -> list[str]:
    files = changed(root, base)
    return [
        *lost_assertions(root, base, files),
        *duplicate_tests(root),
        *added_markers(root, base),
    ]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", required=True)
    a = ap.parse_args(argv)
    try:
        found = violations(Path.cwd(), a.base)
    except (ToolError, OSError, SyntaxError) as e:  # a test file that does not parse: exit 2
        print(f"the check failed: {e}", file=sys.stderr)
        return 2
    sys.stdout.reconfigure(encoding="utf-8")
    for v in found:
        print(v)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
