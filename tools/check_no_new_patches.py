"""No new or changed test patches the code it tests.

A pull request's test files (tests/**/*.py) are compared function by function with the base, each
function's code read with its docstrings and comments set aside. A test, fixture or helper whose
code the PR adds or changes is refused when it patches: it takes or uses pytest's `monkeypatch`,
uses unittest.mock's patch (`patch(...)`, `mock.patch`, `patch.object`, `patch.dict`) or
pytest-mock's `mocker`, or requests a fixture that does (in its own file or a conftest.py), as a
parameter or through `pytest.mark.usefixtures`; a method carries its class's decorators. Code
outside the functions (a module's or a class's other statements) that the PR adds or changes is
refused when it patches (a patch call, or a pytestmark using a patching fixture). A test whose code
the PR adds or changes is also refused when it would run under a patch: an autouse fixture that
patches, in its file or in a conftest.py of its directory or one above, or its file's patch outside
a function. A patching test whose docstrings or comments alone change
is not judged (operator 2026-10-28); a change to its code needs its patch removed.

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

PATCH_CALLS = {"patch", "patch.object", "patch.dict", "patch.multiple", "mock.patch", "mock.patch.object",
               "mock.patch.dict", "unittest.mock.patch"}
PATCH_FIXTURES = {"monkeypatch", "mocker"}


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


def _functions(src: str) -> dict[str, ast.FunctionDef]:
    """Top-level functions and the methods of top-level classes, by name (Class.method); a method
    carries its class's decorators, which apply to it."""
    out = {}
    for node in ast.parse(src).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out[node.name] = node
        elif isinstance(node, ast.ClassDef):
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    sub.decorator_list = node.decorator_list + sub.decorator_list
                    out[f"{node.name}.{sub.name}"] = sub
    return out


def _usefixtures(node: ast.AST) -> set[str]:
    """The fixture names `pytest.mark.usefixtures(...)` calls in `node` request."""
    return {a.value for n in ast.walk(node) if isinstance(n, ast.Call) and _dotted(n.func).endswith("mark.usefixtures")
            for a in n.args if isinstance(a, ast.Constant) and isinstance(a.value, str)}


def _params(fn: ast.FunctionDef) -> set[str]:
    """The fixtures a function requests: its parameters and its decorators' usefixtures names."""
    return {a.arg for a in fn.args.args + fn.args.kwonlyargs} | set().union(*map(_usefixtures, fn.decorator_list))


def _patches_directly(fn: ast.FunctionDef) -> bool:
    if _params(fn) & PATCH_FIXTURES:
        return True
    for n in ast.walk(fn):
        if isinstance(n, ast.Name) and n.id in PATCH_FIXTURES:
            return True
        if isinstance(n, ast.Call) and _dotted(n.func) in PATCH_CALLS:
            return True
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n is not fn:
            if any(_dotted(d.func if isinstance(d, ast.Call) else d) in PATCH_CALLS for d in n.decorator_list):
                return True
    return any(_dotted(d.func if isinstance(d, ast.Call) else d) in PATCH_CALLS for d in fn.decorator_list)


def _is_fixture(fn: ast.FunctionDef) -> tuple[bool, bool]:
    """(a pytest fixture, autouse)."""
    for d in fn.decorator_list:
        name = _dotted(d.func if isinstance(d, ast.Call) else d)
        if name in ("pytest.fixture", "fixture"):
            auto = isinstance(d, ast.Call) and any(
                k.arg == "autouse" and isinstance(k.value, ast.Constant) and k.value.value is True for k in d.keywords)
            return True, auto
    return False, False


def _patching(funcs: dict[str, ast.FunctionDef], shared: set[str]) -> set[str]:
    """Names in `funcs` that patch, directly or through a fixture or helper that does (`shared`:
    patching fixtures from conftest.py), to a fixed point."""
    out = {n for n, f in funcs.items() if _patches_directly(f)}
    while True:
        more = {n for n, f in funcs.items() if n not in out and (
            _params(f) & (out | shared) or {x.id for x in ast.walk(f) if isinstance(x, ast.Name)} & out)}
        if not more:
            return out
        out |= more


def _code(fn: ast.FunctionDef) -> str | None:
    """A function's code, decorators included, with its docstrings and comments set aside."""
    return _python_code(ast.unparse(fn))


def _outside(tree: ast.Module) -> list[ast.stmt]:
    """A module's statements outside its functions: the module's and its classes' other
    statements."""
    out = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            out += [s for s in node.body if not isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef))]
        elif not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append(node)
    return out


def _outside_patches(tree: ast.Module, patching: set[str]) -> bool:
    """Whether a module's statements outside its functions patch: a patch call, or a pytestmark
    using `monkeypatch`, `mocker` or a patching fixture."""
    return any((isinstance(n, ast.Call) and _dotted(n.func) in PATCH_CALLS)
               or _usefixtures(n) & (patching | PATCH_FIXTURES)
               for s in _outside(tree) for n in ast.walk(s))


def _conftest_patching(root: Path, rev: str) -> tuple[set[str], list[tuple[str, str]]]:
    """The patching fixtures of every conftest.py, and the autouse ones as (its directory, name)."""
    shared: set[str] = set()
    autouse: list[tuple[str, str]] = []
    for path in _git(root, "ls-tree", "-r", "--name-only", rev).splitlines():
        if path.rsplit("/", 1)[-1] == "conftest.py":
            src = _source(root, rev, path)
            if src:
                funcs = _functions(src)
                fixtures = {n for n in _patching(funcs, set()) if _is_fixture(funcs[n])[0]}
                shared |= fixtures
                autouse += [(path[:-len("conftest.py")], n) for n in sorted(fixtures) if _is_fixture(funcs[n])[1]]
    return shared, autouse


def violations(root: Path, base: str) -> list[str]:
    changed = [f for f in _git(root, "diff", "--name-only", "--diff-filter=AMR", f"{base}...HEAD").splitlines()
               if f.startswith("tests/") and f.endswith(".py")]
    if not changed:
        return []
    shared, conftest_autouse = _conftest_patching(root, "HEAD")
    out = []
    for path in changed:
        head = _source(root, "HEAD", path)
        if head is None:
            continue
        old = _source(root, base, path)
        old_code = {n: _code(f) for n, f in _functions(old).items()} if old else {}
        funcs = _functions(head)
        patching = _patching(funcs, shared)
        autouse = sorted(n for n in patching if _is_fixture(funcs[n]) == (True, True))
        under = [f"the file's patching autouse fixture {', '.join(autouse)}"] if autouse else []
        under += [f"{d}conftest.py's patching autouse fixture {n}" for d, n in conftest_autouse
                  if path.startswith(d) and path != f"{d}conftest.py"]
        tree = ast.parse(head)
        if _outside_patches(tree, patching | shared):
            under.append("the file's patch outside a function")
            was = ast.Module(_outside(ast.parse(old)) if old else [], [])
            if _python_code(ast.unparse(was)) != _python_code(ast.unparse(ast.Module(_outside(tree), []))):
                out.append(f"{path} patches outside a function (a patch call or a pytestmark that patches)")
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
