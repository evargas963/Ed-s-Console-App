"""No new or changed test patches the code it tests.

A pull request's test files (tests/**/*.py) are compared with the base unit by unit, each unit's
code read with its docstrings and comments set aside: every function not inside another (by name,
at any class depth or under an `if` or `try`, carrying its classes' decorators) and every other
statement. The suite's runs, each recorded by tools/patch_record.py (one per system: a test ends
its run on Windows or on Linux, not always both), say what patched, however it was written. A test
the PR adds or changes is refused when it ran with a patch applied in any run (applied while it
ran, or still applied and reaching it, as the recorder judges), or when no run has a record of it
running to its end (skipped before or during its call, deselected, its file skipped), so what it
runs under is unknown. A unit the PR adds or changes is refused when a patch was applied from one
of its lines. A patching test whose docstrings or comments alone change is not judged, one a
standard tool's safe fix alone changes is not judged for its patches but must still run, and any
other change to its code needs its patch removed.

    ED_PATCH_RECORD=<dir> python -m pytest -p tools.patch_record
    python -m tools.check_no_new_patches --base origin/main --record <dir> [<dir> ...]
Exit 0: nothing patches in what the PR adds or changes. Exit 1: refused, each unit named.
Exit 2: the check itself failed (git unavailable, the base unknown, no record of the run).
"""

from __future__ import annotations

import argparse
import ast
import subprocess
import sys
from pathlib import Path

from tools.check_end_to_end import _python_code, tool_fixed, tools_fix_is_safe
from tools.patch_record import APPLIED, COLLECTED, RAN, read

_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef)
PATCHED = "it ran with a patch applied"
UNRUN = "it did not run, so what it runs under is unknown"
UNBOUND = "pytest collected it, but no code in its file binds the name, so what it is is unknown"


class ToolError(Exception):
    pass


def _git(root: Path, *args: str) -> bytes:
    try:
        return subprocess.run(
            ["git", "-c", "core.quotePath=false", *args], cwd=root, capture_output=True, check=True
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        raise ToolError(f"git {' '.join(args)} failed: {e}") from e


def _outside_defs(node: ast.AST) -> list[ast.AST]:
    """`node` and every node under it outside the functions and classes it holds."""
    out, todo = [], [node]
    while todo:
        n = todo.pop()
        out.append(n)
        todo += [c for c in ast.iter_child_nodes(n) if not isinstance(c, (*_DEFS, ast.ClassDef))]
    return out


def _units(src: bytes) -> tuple[dict[str, ast.stmt], list[ast.stmt]]:
    """A module's functions and class headers (name, bases, decorators) by name (Class.name at any
    class depth; one under an `if` or `try` by its own name), each carrying its classes'
    decorators, and its other statements, docstrings aside (a compound statement holds the
    functions under it)."""
    funcs: dict[str, ast.stmt] = {}
    rest: list[ast.stmt] = []

    def walk(body: list[ast.stmt], prefix: str, decorators: list[ast.expr], top: bool) -> None:
        for node in body:
            if isinstance(node, _DEFS):
                node.first = min([d.lineno for d in node.decorator_list] + [node.lineno])
                node.decorator_list = decorators + node.decorator_list
                funcs[prefix + node.name] = node
            elif isinstance(node, ast.ClassDef):
                header = ast.ClassDef(
                    name=node.name,
                    bases=node.bases,
                    keywords=node.keywords,
                    body=[ast.Pass()],
                    decorator_list=decorators + node.decorator_list,
                    type_params=node.type_params,
                )
                header.lineno, header.end_lineno = node.lineno, node.end_lineno
                header.first = min([d.lineno for d in node.decorator_list] + [node.lineno])
                funcs[prefix + node.name] = header
                walk(node.body, f"{prefix}{node.name}.", decorators + node.decorator_list, True)
            elif not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)):
                if top:
                    inner = _outside_defs(node)
                    node.binds = {
                        prefix + n.id
                        for n in inner
                        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)
                    } | {
                        prefix + (a.asname or a.name.split(".")[0])
                        for n in inner
                        if isinstance(n, (ast.Import, ast.ImportFrom))
                        for a in n.names
                    }
                    rest.append(node)
                for block in [getattr(node, f, []) for f in ("body", "orelse", "finalbody")] + [
                    h.body for h in getattr(node, "handlers", [])
                ]:
                    walk(block, prefix, decorators, False)

    walk(ast.parse(src).body, "", [], True)
    return funcs, rest


def _code(node: ast.AST) -> str | None:
    """A unit's code, decorators included, with its docstrings and comments set aside."""
    return _python_code(ast.unparse(node))


def _file_units(
    root: Path, base: str, path: str, was_path: str | None, tools_safe: bool
) -> list[tuple[str, ast.stmt, bool]]:
    """Every unit of `path` as (name, node, whether the PR adds or changes it); a statement is
    named "line N". `was_path` is the file's path on the base (a rename's old path; None when the
    PR adds the file). A unit as the repository's standard tools leave the base's (tool_fixed, when
    `tools_safe`) is not changed: a tool's safe fix adds no patch."""
    sources = [_git(root, "show", f"{base}:{was_path}")] if was_path else []
    if sources and tools_safe:
        fixed = tool_fixed(root, path, sources[0].decode("utf-8", "replace"))
        sources += [fixed] if fixed is not None else []
    was: set[tuple[str, str | None]] = set()
    was_statements: set[tuple[str | None, frozenset[str]]] = set()
    for source in sources:
        was_funcs, was_rest = _units(source)
        was |= {(n, _code(f)) for n, f in was_funcs.items()}
        was_statements |= {(_code(s), frozenset(s.binds)) for s in was_rest}
    funcs, rest = _units(_git(root, "show", f"HEAD:{path}"))
    return [(n, f, (n, _code(f)) not in was) for n, f in funcs.items()] + [
        (f"line {s.lineno}", s, (_code(s), frozenset(s.binds)) not in was_statements) for s in rest
    ]


def _changed_files(root: Path, base: str) -> dict[str, str | None]:
    """The PR's added, changed and renamed test files, each with its path on the base."""
    out = {}
    rows = _git(root, "diff", "--name-status", "-M", "--diff-filter=AMR", f"{base}...HEAD")
    for row in rows.decode("utf-8", "surrogateescape").splitlines():
        status, *paths = row.split("\t")
        if paths[-1].startswith("tests/") and paths[-1].endswith(".py"):
            out[paths[-1]] = None if status == "A" else paths[0]
    return out


def _named_as_test(path: str, name: str) -> bool:
    """Whether pytest's default names make `name` in `path` a test (test_*.py or *_test.py, a test*
    function in Test* classes): read only for a file pytest collected nothing from (skipped whole,
    ignored, or in a package that skipped)."""
    file, *classes, function = [path.rsplit("/", 1)[-1], *name.split(".")]
    return (
        (file.startswith("test_") or file.endswith("_test.py"))
        and function.startswith("test")
        and all(c.startswith("Test") for c in classes)
    )


def _innermost(units: dict, path: str, line: int) -> tuple[str, bool] | None:
    """The innermost unit of `path` holding `line`, as (name, changed); None outside every unit or
    for a file the PR does not change."""
    inside = [
        (u.end_lineno - getattr(u, "first", u.lineno), n, changed)
        for n, u, changed in units.get(path, [])
        if getattr(u, "first", u.lineno) <= line <= u.end_lineno
    ]
    return min(inside)[1:] if inside else None


def _resolve(units: dict, path: str, at: str | int) -> tuple[str, str] | None:
    """The changed file's unit a test identity names, as (path, name): a name pytest collected it
    under (a function's, or a statement's that binds it, `test_b = test_a`), or the innermost unit
    holding the line its code starts on."""
    if isinstance(at, int):
        inside = _innermost(units, path, at)
        return (path, inside[0]) if inside else None
    for n, u, _ in units.get(path, []):
        if n == at or at in getattr(u, "binds", ()):
            return path, n
    cls = at.rpartition(".")[0]
    return _resolve(units, path, cls) if cls else None  # a method the class inherits: its class


def _over(units: dict, path: str, name: str) -> set[tuple[str, str]]:
    """The units that put a test under what it runs with, besides its own code: the headers of the
    classes holding it (their bases and decorators) and a `pytestmark` over it, in its module or
    one of those classes."""
    parts = name.split(".")
    classes = {".".join(parts[:i]) for i in range(1, len(parts))}
    marks = {"pytestmark"} | {c + ".pytestmark" for c in classes}
    return {
        (path, n)
        for n, u, _ in units.get(path, [])
        if n in classes or marks & getattr(u, "binds", set())
    }


def violations(root: Path, base: str, *records: Path) -> list[str]:
    try:
        events = [e for record in records for e in read(record)]
    except FileNotFoundError as e:
        raise ToolError(str(e)) from e
    tools_safe = tools_fix_is_safe(root, base)
    changed_files = _changed_files(root, base)
    units = {
        path: _file_units(root, base, path, was, tools_safe) for path, was in changed_files.items()
    }
    touched = {
        path: _file_units(root, base, path, was, False) for path, was in changed_files.items()
    }
    reasons: dict[str, set[str]] = {}
    ran, collected, collected_files = set(), set(), set()
    for e in events:
        tests = {t for at in e.test or () if (t := _resolve(units, *at))}
        if tests and not any(changed for p, n in tests for m, _, changed in units[p] if m == n):
            tests |= {
                o for p, n in tests for o in _over(units, p, n)
            }  # unchanged code put under a changed mark
        if e.kind == RAN:
            ran |= tests
        if e.kind == COLLECTED:
            collected |= tests
            collected_files |= {path for path, _ in e.test}
            path, name = e.test[0]
            if path in units and not _resolve(units, path, name):
                reasons.setdefault(f"{path}::{name}", set()).add(UNBOUND)
        for path, name in tests:
            if (e.kind == APPLIED or e.sites) and any(
                n == name and changed for n, _, changed in units[path]
            ):
                reasons.setdefault(f"{path}::{name}", set()).add(PATCHED)
        if e.kind != APPLIED:
            continue
        for path, line in e.sites:
            inside = _innermost(units, path, line)
            if inside and inside[1]:
                reasons.setdefault(f"{path}::{inside[0]}", set()).add(f"line {line} applies one")
    for path, file_units in touched.items():
        for name, _, changed in file_units:
            is_test = (path, name) in collected or (
                path not in collected_files and _named_as_test(path, name)
            )
            if changed and is_test and (path, name) not in ran:
                reasons.setdefault(f"{path}::{name}", set()).add(UNRUN)
    return [f"{unit} patches: {', '.join(sorted(why))}" for unit, why in sorted(reasons.items())]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--record", required=True, type=Path, nargs="+")
    a = ap.parse_args(argv)
    try:
        found = violations(Path.cwd(), a.base, *a.record)
    except (ToolError, SyntaxError) as e:
        print(f"the check failed: {e}", file=sys.stderr)
        return 2
    for v in found:
        print(v)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
