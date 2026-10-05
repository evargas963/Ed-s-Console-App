"""TICKER-COVERAGE (operator 2026-10-04): every ticker is treated the same; a test of captured data
runs on more than one ticker's capture (the standard pair: SPY and TSLA).

A pull request's test files (tests/**/*.py) are compared unit by unit with the base. A test the PR
adds or changes, or whose helpers, fixtures or module constants (in its file, to any depth, or a
conftest.py fixture it requests) the PR changes, is judged. The captured fixtures it reads are the
fixture files (tests/fixtures/**/*.json) whose file name ends a string literal in the test or in
what it reaches. Each fixture's tickers come from the fixture itself: its provenance `symbols`,
else its top-level `ticker` / `symbol`, else the root (first word) of every `symbol`, `ticker` and
`key` string inside it. A test whose fixtures carry exactly one ticker is refused.

The one exception is a property only one capture has. The test carries
    @pytest.mark.one_capture("<fixture file>", <predicate>)
where <predicate> is a function of the same file that takes a fixture's parsed JSON and returns
whether it has the property. The check runs the predicate on every captured fixture and accepts the
exception only when exactly the named fixture has it. The predicate runs with the standard library
and the file's other plain functions only; a predicate that raises on any fixture refuses the test.

Limits: a fixture name built at run time (f-strings, joined pieces), a fixture read through a
helper module imported from another file, and a fixture with no ticker field and no symbol in it
are not seen.

    python tools/check_ticker_coverage.py --base origin/main
Exit 0: every judged test reads more than one ticker's capture, or none, or carries a proven
exception. Exit 1: refused, each test named with file:line. Exit 2: the check itself failed.
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

from check_no_new_patches import ToolError, _dotted, _git, _source
from check_real_market_data import FIXTURES, changed_names, is_fixture, python_units, references

TICKER_KEYS = ("symbol", "ticker", "key")


def fixture_tickers(data) -> set[str]:
    if isinstance(data, dict):
        prov = data.get("provenance")
        if isinstance(prov, dict) and prov.get("symbols"):
            return {str(s) for s in prov["symbols"]}
        top = {data[k] for k in ("ticker", "symbol") if isinstance(data.get(k), str)}
        if top:
            return top
    found: set[str] = set()

    def walk(o) -> None:
        if isinstance(o, dict):
            for k, v in o.items():
                if k in TICKER_KEYS and isinstance(v, str) and v.split():
                    found.add(v.split()[0])
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(data)
    return found


def captures(root: Path) -> dict[str, object]:
    """Every captured fixture, by file name, parsed."""
    files = sorted((root / FIXTURES).rglob("*.json"))
    if not files:
        raise ToolError(f"no captured fixtures under {FIXTURES}")
    return {f.name: json.loads(f.read_text(encoding="utf-8")) for f in files}


def _strings(node: ast.AST) -> set[str]:
    return {n.value.replace("\\", "/") for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)}


def _reached(units: dict[str, ast.AST], start: str) -> set[str]:
    seen, todo = {start}, [start]
    while todo:
        for ref in references(units[todo.pop()]):
            if ref in units and ref not in seen:
                seen.add(ref)
                todo.append(ref)
    return seen


def _marker(fn: ast.AST):
    for d in getattr(fn, "decorator_list", []):
        if isinstance(d, ast.Call) and _dotted(d.func).endswith("mark.one_capture"):
            return d
    return None


def _predicate(src: str, name: str):
    """The predicate `name` of `src`, defined with the file's standard-library imports and its other
    plain functions."""
    tree = ast.parse(src)
    keep = []
    for node in tree.body:
        if isinstance(node, ast.Import) and all(a.name.split(".")[0] in sys.stdlib_module_names for a in node.names):
            keep.append(node)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and (node.module or "").split(".")[0] in \
                sys.stdlib_module_names:
            keep.append(node)
        elif isinstance(node, ast.FunctionDef) and not node.decorator_list and not node.name.startswith("test"):
            keep.append(node)
    space: dict = {}
    exec(compile(ast.Module(body=keep, type_ignores=[]), "<predicate>", "exec"), space)
    return space.get(name)


def _exception(src: str, fn: ast.AST, caps: dict[str, object]) -> str | None:
    """None when the one_capture exception is proven, else why it is not."""
    m = _marker(fn)
    if len(m.args) != 2 or not isinstance(m.args[0], ast.Constant) or not isinstance(m.args[1], ast.Name):
        return 'one_capture takes ("<fixture file>", <predicate function>)'
    named, pname = Path(str(m.args[0].value)).name, m.args[1].id
    if named not in caps:
        return f"one_capture names {named}, which is not a captured fixture under {FIXTURES}"
    having, fname = [], "its definition"
    try:
        pred = _predicate(src, pname)
        if pred is None:
            return f"one_capture's predicate {pname} is not a plain function of this file"
        for fname, data in caps.items():
            if pred(data):
                having.append(fname)
    except Exception as e:  # noqa: BLE001 -- the predicate's failure is the refusal's reason
        return f"one_capture's predicate {pname} raised {type(e).__name__}: {e} on {fname}"
    if having != [named]:
        return f"one_capture's predicate {pname} holds for {len(having)} captured fixtures " \
               f"({', '.join(having[:5]) or 'none'}), not for {named} alone"
    return None


def _conftest_units(root: Path) -> dict[str, ast.AST]:
    out: dict[str, ast.AST] = {}
    for path in _git(root, "ls-tree", "-r", "--name-only", "HEAD", "tests").splitlines():
        if path.endswith("conftest.py") and (src := _source(root, "HEAD", path)):
            out |= {n: u for n, u in python_units(src).items() if is_fixture(u)}
    return out


def violations(root: Path, base: str) -> list[str]:
    paths = [f for f in _git(root, "diff", "--name-only", "--diff-filter=AMR", f"{base}...HEAD").splitlines()
             if f.startswith("tests/") and f.endswith(".py")]
    return judge(root, base, paths) if paths else []


def judge(root: Path, base: str, paths: list[str]) -> list[str]:
    caps = captures(root)
    tickers = {name: fixture_tickers(data) for name, data in caps.items()}
    shared = _conftest_units(root)
    out = []
    for path in paths:
        src = _source(root, "HEAD", path)
        if src is None:
            continue
        units = python_units(src)
        changed = changed_names(units, _source(root, base, path))
        for name, fn in units.items():
            if not (isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and name.split(".")[-1].startswith("test")):
                continue
            reach = _reached(units, name)
            if not reach & changed:
                continue
            texts = set().union(*(_strings(units[n]) for n in reach))
            for fx in references(fn) & set(shared):
                texts |= set().union(*(_strings(shared[n]) for n in _reached(shared, fx)))
            read = sorted(f for f in caps if any(t.endswith(f) for t in texts))
            seen = set().union(*(tickers[f] for f in read)) if read else set()
            if len(seen) != 1:
                continue
            if _marker(fn) is not None:
                why = _exception(src, fn, caps)
                if why is None:
                    continue
                out.append(f"{path}:{fn.lineno} {name}: {why}")
                continue
            out.append(f"{path}:{fn.lineno} {name}: reads captures of one ticker only ({next(iter(seen))}: "
                       f"{', '.join(read)}); run it on the SPY and TSLA captures, or prove a one_capture exception")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    a = ap.parse_args(argv)
    try:
        found = violations(Path.cwd(), a.base)
    except (ToolError, SyntaxError, ValueError) as e:
        print(f"the check failed: {e}", file=sys.stderr)
        return 2
    for v in found:
        print(v)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
