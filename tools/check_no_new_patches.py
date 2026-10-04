"""TEST-PATCHES (operator 2026-10-04): no new or changed test patches the code it tests.

A pull request's test files (tests/**/*.py) are compared function by function with the base. A
test, fixture or helper the PR adds or changes is refused when it patches: it takes or uses
pytest's `monkeypatch`, uses unittest.mock's patch (`patch(...)`, `mock.patch`, `patch.object`,
`patch.dict`) or pytest-mock's `mocker`, or requests a fixture that does (in its own file or a
conftest.py). A test the PR adds or changes is also refused when its file has an autouse fixture
that patches: it would run under that patch. A function the PR leaves unchanged is not judged.

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
    """Top-level functions and the methods of top-level classes, by name (Class.method)."""
    out = {}
    for node in ast.parse(src).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out[node.name] = node
        elif isinstance(node, ast.ClassDef):
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    out[f"{node.name}.{sub.name}"] = sub
    return out


def _params(fn: ast.FunctionDef) -> set[str]:
    return {a.arg for a in fn.args.args + fn.args.kwonlyargs}


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


def _conftest_patching(root: Path, rev: str) -> set[str]:
    out: set[str] = set()
    for path in _git(root, "ls-tree", "-r", "--name-only", rev, "tests").splitlines():
        if path.endswith("conftest.py"):
            src = _source(root, rev, path)
            if src:
                funcs = _functions(src)
                out |= {n for n in _patching(funcs, set()) if _is_fixture(funcs[n])[0]}
    return out


def violations(root: Path, base: str) -> list[str]:
    changed = [f for f in _git(root, "diff", "--name-only", "--diff-filter=AMR", f"{base}...HEAD").splitlines()
               if f.startswith("tests/") and f.endswith(".py")]
    if not changed:
        return []
    shared = _conftest_patching(root, "HEAD")
    out = []
    for path in changed:
        head = _source(root, "HEAD", path)
        if head is None:
            continue
        old = _source(root, base, path)
        old_funcs = {n: ast.dump(f) for n, f in _functions(old).items()} if old else {}
        funcs = _functions(head)
        patching = _patching(funcs, shared)
        autouse = sorted(n for n in patching if _is_fixture(funcs[n]) == (True, True))
        for name, fn in funcs.items():
            if old_funcs.get(name) == ast.dump(fn):
                continue                                  # unchanged by this PR: not judged
            if name in patching:
                out.append(f"{path}::{name} patches (monkeypatch, mock.patch or a fixture that does)")
            elif autouse and name.split(".")[-1].startswith("test"):
                out.append(f"{path}::{name} runs under the file's patching autouse fixture {', '.join(autouse)}")
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
