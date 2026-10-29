"""No new or changed test patches the code it tests.

A pull request's test files (tests/**/*.py) are compared with the base unit by unit, each unit's
code read with its docstrings and comments set aside: every function not inside another (by name,
at any class depth or under an `if` or `try`, carrying its classes' decorators) and every other
statement. The suite's run, recorded by tools/patch_record.py, says what patched, however it was
written. A test the PR adds or changes is refused when it ran with a patch applied (applied while
it ran, or still applied and reaching it, as the recorder judges), or when the run has no record
of it running to its end (skipped before or during its call, deselected, its file skipped), so
what it runs under is unknown. A unit the
PR adds or changes is refused when a patch was applied from one of its lines. A patching test whose docstrings or comments alone change is not judged; a
change to its code needs its patch removed.

    ED_PATCH_RECORD=<dir> python -m pytest -p tools.patch_record
    python tools/check_no_new_patches.py --base origin/main --record <dir>
Exit 0: nothing patches in what the PR adds or changes. Exit 1: refused, each unit named.
Exit 2: the check itself failed (git unavailable, the base unknown, no record of the run).
"""
from __future__ import annotations

import argparse
import ast
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_end_to_end import _python_code  # noqa: E402
from patch_record import APPLIED, COLLECTED, RAN, read  # noqa: E402

_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef)
PATCHED = "it ran with a patch applied"
UNRUN = "it did not run, so what it runs under is unknown"


class ToolError(Exception):
    pass


def _git(root: Path, *args: str) -> bytes:
    try:
        return subprocess.run(["git", "-c", "core.quotePath=false", *args], cwd=root, capture_output=True,
                              check=True).stdout
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        raise ToolError(f"git {' '.join(args)} failed: {e}") from e


def _units(src: bytes) -> tuple[dict[str, ast.stmt], list[ast.stmt]]:
    """A module's functions by name (Class.name at any class depth; one under an `if` or `try` by
    its own name), each carrying its classes' decorators, and its other statements, docstrings
    aside (a compound statement holds the functions under it)."""
    funcs: dict[str, ast.stmt] = {}
    rest: list[ast.stmt] = []

    def walk(body: list[ast.stmt], prefix: str, decorators: list[ast.expr], top: bool) -> None:
        for node in body:
            if isinstance(node, _DEFS):
                node.first = min([d.lineno for d in node.decorator_list] + [node.lineno])
                node.decorator_list = decorators + node.decorator_list
                funcs[prefix + node.name] = node
            elif isinstance(node, ast.ClassDef):
                walk(node.body, f"{prefix}{node.name}.", decorators + node.decorator_list, True)
            elif not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)):
                if top:
                    rest.append(node)
                for block in [getattr(node, f, []) for f in ("body", "orelse", "finalbody")] + [
                        h.body for h in getattr(node, "handlers", [])]:
                    walk(block, prefix, decorators, False)
    walk(ast.parse(src).body, "", [], True)
    return funcs, rest


def _code(node: ast.AST) -> str | None:
    """A unit's code, decorators included, with its docstrings and comments set aside."""
    return _python_code(ast.unparse(node))


def _file_units(root: Path, base: str, path: str, was_path: str | None) -> list[tuple[str, ast.stmt, bool]]:
    """Every unit of `path` as (name, node, whether the PR adds or changes it); a statement is
    named "line N". `was_path` is the file's path on the base (a rename's old path; None when the
    PR adds the file)."""
    was_funcs, was_rest = _units(_git(root, "show", f"{base}:{was_path}")) if was_path else ({}, [])
    was = {n: _code(f) for n, f in was_funcs.items()}
    was_statements = {_code(s) for s in was_rest}
    funcs, rest = _units(_git(root, "show", f"HEAD:{path}"))
    return ([(n, f, was.get(n) != _code(f)) for n, f in funcs.items()]
            + [(f"line {s.lineno}", s, _code(s) not in was_statements) for s in rest])


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
    return ((file.startswith("test_") or file.endswith("_test.py")) and function.startswith("test")
            and all(c.startswith("Test") for c in classes))


def _innermost(units: dict, path: str, line: int) -> tuple[str, bool] | None:
    """The innermost unit of `path` holding `line`, as (name, changed); None outside every unit or
    for a file the PR does not change."""
    inside = [(u.end_lineno - getattr(u, "first", u.lineno), n, changed) for n, u, changed in units.get(path, [])
              if getattr(u, "first", u.lineno) <= line <= u.end_lineno]
    return min(inside)[1:] if inside else None


def _resolve(units: dict, path: str, at: str | int) -> tuple[str, str] | None:
    """The changed file's unit a test identity names, as (path, name): a name pytest collected it
    under, or the innermost unit holding the line its code starts on."""
    if isinstance(at, int):
        inside = _innermost(units, path, at)
        return (path, inside[0]) if inside else None
    return (path, at) if any(n == at for n, _, _ in units.get(path, [])) else None


def violations(root: Path, base: str, record: Path) -> list[str]:
    try:
        events = read(record)
    except FileNotFoundError as e:
        raise ToolError(str(e)) from e
    units = {path: _file_units(root, base, path, was) for path, was in _changed_files(root, base).items()}
    reasons: dict[str, set[str]] = {}
    ran, collected, collected_files = set(), set(), set()
    for e in events:
        tests = {t for at in e.test or () if (t := _resolve(units, *at))}
        if e.kind == RAN:
            ran |= tests
        if e.kind == COLLECTED:
            collected |= tests
            collected_files |= {path for path, _ in e.test}
        for path, name in tests:
            if (e.kind == APPLIED or e.sites) and any(n == name and changed for n, _, changed in units[path]):
                reasons.setdefault(f"{path}::{name}", set()).add(PATCHED)
        if e.kind != APPLIED:
            continue
        for path, line in e.sites:
            inside = _innermost(units, path, line)
            if inside and inside[1]:
                reasons.setdefault(f"{path}::{inside[0]}", set()).add(f"line {line} applies one")
    for path, file_units in units.items():
        for name, _, changed in file_units:
            is_test = (path, name) in collected or (path not in collected_files and _named_as_test(path, name))
            if changed and is_test and (path, name) not in ran:
                reasons.setdefault(f"{path}::{name}", set()).add(UNRUN)
    return [f"{unit} patches: {', '.join(sorted(why))}" for unit, why in sorted(reasons.items())]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--record", required=True, type=Path)
    a = ap.parse_args(argv)
    try:
        found = violations(Path.cwd(), a.base, a.record)
    except (ToolError, SyntaxError) as e:
        print(f"the check failed: {e}", file=sys.stderr)
        return 2
    for v in found:
        print(v)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
