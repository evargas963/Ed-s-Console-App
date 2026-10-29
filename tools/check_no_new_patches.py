"""No new or changed test patches the code it tests.

A pull request's test files (tests/**/*.py) are compared with the base unit by unit, each unit's
code read with its docstrings and comments set aside: every function, by name at any class depth
and carrying its classes' decorators, and each other statement (a function under an `if` among
them). A unit the PR adds or changes is refused when it patches: it names a patch tool
(`monkeypatch`, `MonkeyPatch`, `mocker`, unittest.mock's `patch` in any spelling or alias,
`getfixturevalue`), requests a fixture that does (in its file or any conftest.py; as a parameter or
through `pytest.mark.usefixtures`) or calls a helper that does. A test the PR adds or changes is
also refused when it would run under a patch: its file's patching autouse fixture, setup function
or other statement, or a conftest.py's patching autouse fixture or other statement in its directory
or one above. A patching test whose docstrings or comments alone change is not judged (operator
2026-10-28); a change to its code needs its patch removed.

    python tools/check_no_new_patches.py --base origin/main
Exit 0: nothing patches in what the PR adds or changes. Exit 1: refused, each function named.
Exit 2: the check itself failed (git unavailable, the base unknown).
"""
from __future__ import annotations

import argparse
import ast
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_end_to_end import _python_code  # noqa: E402

PATCH_FIXTURES = {"monkeypatch", "mocker"}
PATCH_ATTRS = {"patch", "MonkeyPatch", "getfixturevalue"}
SETUPS = {"setup_function", "setup_method", "setup_class", "setup_module", "setUp", "setUpClass", "setUpModule"}
_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef)


class ToolError(Exception):
    pass


def _git(root: Path, *args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8",
                              check=True).stdout
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        raise ToolError(f"git {' '.join(args)} failed: {e}") from e


def _source(root: Path, rev: str, path: str) -> str | None:
    r = subprocess.run(["git", "show", f"{rev}:{path}"], cwd=root, capture_output=True, text=True, encoding="utf-8")
    return r.stdout if r.returncode == 0 else None


def _dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_dotted(node.value)}.{node.attr}"
    return ""


def _units(src: str) -> tuple[dict[str, ast.FunctionDef], list[ast.stmt]]:
    """A module's functions by name (Class.method, at any class depth), each carrying its classes'
    decorators, and its other statements (docstrings aside), a function under an `if` among them."""
    funcs: dict[str, ast.FunctionDef] = {}
    rest: list[ast.stmt] = []

    def walk(body: list[ast.stmt], prefix: str, decorators: list[ast.expr]) -> None:
        for node in body:
            if isinstance(node, _DEFS):
                node.decorator_list = decorators + node.decorator_list
                funcs[prefix + node.name] = node
            elif isinstance(node, ast.ClassDef):
                walk(node.body, f"{prefix}{node.name}.", decorators + node.decorator_list)
            elif not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)):
                rest.append(node)
    walk(ast.parse(src).body, "", [])
    return funcs, rest


def _tools(src: str) -> set[str]:
    """The names that patch in a module: pytest's patching fixtures, and each name an import binds
    to a patch tool (`from unittest.mock import patch as p`)."""
    return PATCH_FIXTURES | {a.asname or a.name for n in ast.walk(ast.parse(src)) if isinstance(n, ast.ImportFrom)
                             for a in n.names if a.name in PATCH_ATTRS}


def _usefixtures(node: ast.AST) -> set[str]:
    """The fixture names `pytest.mark.usefixtures(...)` calls in `node` request."""
    return {a.value for n in ast.walk(node) if isinstance(n, ast.Call) and _dotted(n.func).endswith("mark.usefixtures")
            for a in n.args if isinstance(a, ast.Constant) and isinstance(a.value, str)}


def _patches(node: ast.AST, tools: set[str], fixtures: set[str], helpers: frozenset[str] = frozenset()) -> bool:
    """Whether `node` patches: it names a patch tool (`tools` as a name or parameter, PATCH_ATTRS as
    an attribute: `mock.patch`, `pytest.MonkeyPatch`, `request.getfixturevalue`), requests a
    patching fixture (as a parameter or a usefixtures name) or calls a patching helper."""
    requested = tools | fixtures
    return bool(_usefixtures(node) & requested) or any(
        (isinstance(n, ast.Name) and n.id in tools | helpers) or (isinstance(n, ast.arg) and n.arg in requested)
        or (isinstance(n, ast.Attribute) and n.attr in PATCH_ATTRS) for n in ast.walk(node))


def _short(name: str) -> str:
    """The name a fixture or helper is requested or called by: path::Class.name -> name."""
    return name.rsplit("::", 1)[-1].rsplit(".", 1)[-1]


def _is_fixture(fn: ast.FunctionDef) -> tuple[bool, bool]:
    """(a pytest fixture, autouse)."""
    for d in fn.decorator_list:
        name = _dotted(d.func if isinstance(d, ast.Call) else d)
        if name in ("pytest.fixture", "fixture"):
            auto = isinstance(d, ast.Call) and any(
                k.arg == "autouse" and isinstance(k.value, ast.Constant) and k.value.value is True for k in d.keywords)
            return True, auto
    return False, False


def _patching(funcs: dict[str, ast.FunctionDef], tools: set[str], shared: set[str]) -> set[str]:
    """Names in `funcs` that patch, directly or through a fixture or helper that does (`shared`:
    patching fixtures from conftest.py), to a fixed point."""
    out: set[str] = set()
    while True:
        own = frozenset(_short(n) for n in out)
        more = {n for n, f in funcs.items() if n not in out and _patches(f, tools, shared | own, own)}
        if not more:
            return out
        out |= more


def _code(node: ast.AST) -> str | None:
    """A statement's code, decorators included, with its docstrings and comments set aside."""
    return _python_code(ast.unparse(node))


def _conftest_patching(root: Path, rev: str) -> tuple[set[str], list[tuple[str, str]]]:
    """The patching fixtures of every conftest.py, judged together (one may request another's), and
    what each patches under it as (its directory, what): an autouse fixture or code outside its
    functions."""
    funcs: dict[str, ast.FunctionDef] = {}
    rests: dict[str, list[ast.stmt]] = {}
    tools = set(PATCH_FIXTURES)
    for path in _git(root, "ls-tree", "-r", "--name-only", rev).splitlines():
        if path.rsplit("/", 1)[-1] == "conftest.py":
            src = _source(root, rev, path)
            if src:
                found, rests[path] = _units(src)
                funcs |= {f"{path}::{n}": f for n, f in found.items()}
                tools |= _tools(src)
    patching = _patching(funcs, tools, set())
    shared = {_short(n) for n in patching if _is_fixture(funcs[n])[0]}
    under = [(n.split("::")[0][:-len("conftest.py")], f"patching autouse fixture {_short(n)}")
             for n in sorted(patching) if _is_fixture(funcs[n]) == (True, True)]
    under += [(p[:-len("conftest.py")], "patch outside a function") for p, rest in rests.items()
              if any(_patches(s, tools, shared) for s in rest)]
    return shared, under


def violations(root: Path, base: str) -> list[str]:
    changed = [f for f in _git(root, "diff", "--name-only", "--diff-filter=AMR", f"{base}...HEAD").splitlines()
               if f.startswith("tests/") and f.endswith(".py")]
    if not changed:
        return []
    shared, conftest_under = _conftest_patching(root, "HEAD")
    out = []
    for path in changed:
        head = _source(root, "HEAD", path)
        if head is None:
            continue
        old = _source(root, base, path)
        old_funcs, old_rest = _units(old) if old else ({}, [])
        old_code = {n: _code(f) for n, f in old_funcs.items()}
        funcs, rest = _units(head)
        tools = _tools(head)
        patching = _patching(funcs, tools, shared)
        own = frozenset(_short(n) for n in patching)
        autouse = sorted(n for n in patching if _is_fixture(funcs[n]) == (True, True))
        setups = sorted(n for n in patching if _short(n) in SETUPS)
        under = [f"the file's patching autouse fixture {', '.join(autouse)}"] if autouse else []
        under += [f"the file's patching {', '.join(setups)}"] if setups else []
        under += [f"{d}conftest.py's {what}" for d, what in conftest_under
                  if path.startswith(d) and path != f"{d}conftest.py"]
        outside = [s for s in rest if _patches(s, tools, shared | own, own)]
        if outside:
            under.append("the file's patch outside a function")
            was = {_code(s) for s in old_rest}
            if any(_code(s) not in was for s in outside):
                out.append(f"{path} patches outside a function (a patch tool, or a pytestmark or test that patches)")
        for name, fn in funcs.items():
            if old_code.get(name) == _code(fn):
                continue                    # its code unchanged: docstrings and comments may change
            if name in patching:
                out.append(f"{path}::{name} patches (monkeypatch, mock.patch or a fixture that does)")
            elif under and name.split(".")[-1].startswith("test"):
                out.append(f"{path}::{name} runs under {'; '.join(under)}")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    a = ap.parse_args(argv)
    try:
        found = violations(Path.cwd(), a.base)
    except (ToolError, SyntaxError) as e:
        print(f"the check failed: {e}", file=sys.stderr)
        return 2
    for v in found:
        print(v)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
