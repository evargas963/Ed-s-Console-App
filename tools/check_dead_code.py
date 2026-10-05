"""Cleanup: a change leaves no dead code behind.

vulture (minimum confidence 60) reads the repository's Python: the tracked files, and in the
working tree also the untracked files git would add. A finding the change creates, one the base
does not have, compared by (file, name, kind) and not by line, refuses the change: the code it
added that nothing uses, and the code that lost its last user to the change, in any file.
Findings the base already has are not judged; `--all` prints every finding for cleanup.

A finding is not dead code when one of these rules, computed from the code, says the name is used
from outside what vulture reads:
  - a framework calls it: a function registered by `@app.*`, `@router.*`, `@pytest.fixture` or
    `@pytest.hookimpl`; a test pytest collects by its naming rules ([tool.pytest.ini_options]
    python_files, python_functions, python_classes); a `pytest_*` hook in a conftest.py;
  - it overrides a library: a method or class attribute of a class whose base class is imported
    from outside the repository or is a builtin;
  - a library reads it: an attribute set on an object other than `self`/`cls`, or a method, whose
    name a class of a library module the file imports defines;
  - it is serialized: a field of a dataclass that `asdict`, `astuple` or `fields` reads whole
    (called in the class's own body, on the class, or on a name annotated with it);
  - its signature is set by its caller: a parameter of a lambda or of a function passed as a
    value, or a test parameter that requests a pytest fixture.

    python tools/check_dead_code.py --base origin/main [--head REV]
    python tools/check_dead_code.py --all
Without --head the working tree is judged. Exit 0: no new dead code (or --all printed). Exit 1:
refused, each finding named. Exit 2: the check itself failed (git or vulture unavailable, the base
unknown, a file that will not parse).
"""
from __future__ import annotations

import argparse
import ast
import builtins
import fnmatch
import importlib
import io
import subprocess
import sys
import tarfile
import tempfile
import tomllib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from vulture import Vulture

MIN_CONFIDENCE = 60
REGISTRATION_DECORATORS = ["@app.*", "@router.*", "@pytest.fixture", "@pytest.hookimpl"]
SERIALIZERS = {"asdict", "astuple", "fields"}
PYTEST_DEFAULTS = {"python_files": ["test_*.py", "*_test.py"], "python_functions": ["test"],
                   "python_classes": ["Test"]}


class ToolError(Exception):
    pass


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    name: str
    kind: str
    message: str

    @property
    def key(self) -> tuple[str, str, str]:
        return self.path, self.name, self.kind

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.message}"


def _git(root: Path, *args: str) -> bytes:
    try:
        return subprocess.run(["git", *args], cwd=root, capture_output=True, check=True).stdout
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        raise ToolError(f"git {' '.join(args)} failed: {e}") from e


def snapshot(root: Path, rev: str | None, dest: Path) -> tuple[Path, list[str]]:
    """(directory, Python files) of a revision extracted into `dest`, or of the working tree."""
    if rev is None:
        listed = _git(root, "ls-files", "--cached", "--others", "--exclude-standard", "--", "*.py")
        return root, [p for p in listed.decode().splitlines() if (root / p).is_file()]
    if b"pyproject.toml" in _git(root, "ls-tree", "--name-only", rev).splitlines():
        (dest / "pyproject.toml").write_bytes(_git(root, "show", f"{rev}:pyproject.toml"))
    with tarfile.open(fileobj=io.BytesIO(_git(root, "archive", rev, "--", "*.py"))) as tar:
        tar.extractall(dest, filter="data")
        return dest, sorted(m.name for m in tar.getmembers() if m.name.endswith(".py"))


def _dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_dotted(node.value)}.{node.attr}"
    return ""


def _pytest_config(top: Path) -> dict[str, list[str]]:
    p = top / "pyproject.toml"
    ini = tomllib.loads(p.read_text(encoding="utf-8")).get("tool", {}).get("pytest", {}).get(
        "ini_options", {}) if p.is_file() else {}
    return {k: (ini[k].split() if isinstance(ini.get(k), str) else ini.get(k) or v)
            for k, v in PYTEST_DEFAULTS.items()}


_LIBRARY_MEMBERS: dict[str, set[str]] = {}


def _library_members(module: str) -> set[str]:
    """Every attribute name of every class the library module defines or imports."""
    if module not in _LIBRARY_MEMBERS:
        try:
            mod = importlib.import_module(module)
        except ImportError:
            mod = None
        _LIBRARY_MEMBERS[module] = {a for obj in vars(mod).values() if isinstance(obj, type)
                                    for a in dir(obj)} if mod else set()
    return _LIBRARY_MEMBERS[module]


class Repo:
    """The Python files of one tree: their sources, module names, pytest config and fixtures."""

    def __init__(self, top: Path, files: list[str]) -> None:
        self.top, self.files = top, files
        self.modules = {Path(f).parts[0].removesuffix(".py") for f in files} | {Path(f).stem for f in files}
        self.pytest_config = _pytest_config(top)
        self._fixtures: set[str] | None = None

    def source(self, path: str) -> str:
        return (self.top / path).read_text(encoding="utf-8", errors="replace")

    @property
    def fixtures(self) -> set[str]:
        """Names of the functions decorated as pytest fixtures."""
        if self._fixtures is None:
            self._fixtures = {
                fn.name for f in self.files if "fixture" in (src := self.source(f))
                for fn in ast.walk(ast.parse(src)) if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
                and any(_dotted(d.func if isinstance(d, ast.Call) else d) in ("pytest.fixture", "fixture")
                        for d in fn.decorator_list)}
        return self._fixtures


class Module:
    """One file's syntax tree and what the rules ask of it."""

    def __init__(self, path: str, src: str, repo: Repo) -> None:
        self.path, self.tree, self.repo = path, ast.parse(src), repo
        self.is_test_file = Path(path).name == "conftest.py" or any(
            fnmatch.fnmatch(Path(path).name, g) for g in repo.pytest_config["python_files"])
        self.imported: dict[str, str] = {}
        self.modules: list[str] = []
        for n in ast.walk(self.tree):
            if isinstance(n, ast.Import):
                for a in n.names:
                    self.imported[a.asname or a.name.split(".")[0]] = a.name
                    self.modules.append(a.name)
            elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
                for a in n.names:
                    self.imported[a.asname or a.name] = n.module
                self.modules.append(n.module)
        self.classes = {n.name: n for n in ast.walk(self.tree) if isinstance(n, ast.ClassDef)}

    def is_library(self, module: str) -> bool:
        return module.split(".")[0] not in self.repo.modules

    def libraries(self) -> list[str]:
        return [m for m in dict.fromkeys(self.modules) if self.is_library(m)]

    def class_at(self, line: int, name: str) -> ast.ClassDef | None:
        """The class whose own body defines `name` at `line`."""
        for cls in self.classes.values():
            for s in cls.body:
                first = min([s.lineno] + [d.lineno for d in getattr(s, "decorator_list", [])])
                if first <= line <= s.end_lineno and name in _stmt_names(s):
                    return cls
        return None

    def has_library_base(self, cls: ast.ClassDef, seen: frozenset[str] = frozenset()) -> bool:
        for base in cls.bases:
            root = _dotted(base).split(".")[0]
            if root in self.imported:
                if self.is_library(self.imported[root]):
                    return True
            elif root in self.classes and root not in seen:
                if self.has_library_base(self.classes[root], seen | {cls.name}):
                    return True
            elif root != "object" and isinstance(getattr(builtins, root, None), type):
                return True
        return False

    def is_serialized(self, cls: ast.ClassDef) -> bool:
        if not any(_dotted(d.func if isinstance(d, ast.Call) else d).split(".")[-1] == "dataclass"
                   for d in cls.decorator_list):
            return False
        annotated = {a.arg for n in ast.walk(self.tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                     for a in n.args.args + n.args.kwonlyargs if a.annotation is not None
                     and _dotted(a.annotation) == cls.name}
        inside = {id(n) for n in ast.walk(cls)}
        for n in ast.walk(self.tree):
            if isinstance(n, ast.Call) and _dotted(n.func).split(".")[-1] in SERIALIZERS and n.args:
                arg = _dotted(n.args[0])
                if id(n) in inside or arg == cls.name or arg in annotated:
                    return True
        return False

    def parameter_owner(self, line: int, name: str) -> ast.AST | None:
        for n in ast.walk(self.tree):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                a = n.args
                for arg in a.posonlyargs + a.args + a.kwonlyargs + [x for x in (a.vararg, a.kwarg) if x]:
                    if arg.arg == name and arg.lineno == line:
                        return n
        return None

    def passed_as_value(self, fn_name: str) -> bool:
        called = {id(n.func) for n in ast.walk(self.tree) if isinstance(n, ast.Call)}
        return any(isinstance(n, ast.Name) and n.id == fn_name and isinstance(n.ctx, ast.Load)
                   and id(n) not in called for n in ast.walk(self.tree))

    def foreign_attribute_store(self, line: int, name: str) -> bool:
        return any(isinstance(n, ast.Attribute) and n.attr == name and isinstance(n.ctx, ast.Store)
                   and n.lineno <= line <= n.end_lineno
                   and not (isinstance(n.value, ast.Name) and n.value.id in ("self", "cls"))
                   for n in ast.walk(self.tree))


def _stmt_names(s: ast.stmt) -> set[str]:
    if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {s.name}
    targets = s.targets if isinstance(s, ast.Assign) else [s.target] if isinstance(s, ast.AnnAssign) else []
    return {n.id for t in targets for n in ast.walk(t) if isinstance(n, ast.Name)}


def used_from_outside(f: Finding, m: Module) -> bool:
    """True when a rule of the module docstring says the name is used from outside vulture's view."""
    cfg = m.repo.pytest_config
    if f.kind in ("function", "method") and m.is_test_file:
        if Path(f.path).name == "conftest.py" and f.name.startswith("pytest_"):
            return True
        if any(f.name.startswith(p) or fnmatch.fnmatch(f.name, p) for p in cfg["python_functions"]):
            return True
    if f.kind == "class" and m.is_test_file and any(
            f.name.startswith(p) or fnmatch.fnmatch(f.name, p) for p in cfg["python_classes"]):
        return True
    cls = m.class_at(f.line, f.name)
    if cls is not None and f.kind in ("method", "variable", "property") and m.has_library_base(cls):
        return True
    if (f.kind == "attribute" and m.foreign_attribute_store(f.line, f.name)) or f.kind == "method":
        if any(f.name in _library_members(lib) for lib in m.libraries()):
            return True
    if cls is not None and f.kind == "variable" and m.is_serialized(cls):
        return True
    if f.kind == "variable":
        owner = m.parameter_owner(f.line, f.name)
        if isinstance(owner, ast.Lambda):
            return True
        if owner is not None and m.passed_as_value(owner.name):
            return True
        if owner is not None and m.is_test_file and f.name in m.repo.fixtures:
            return True
    return False


def findings(top: Path, files: list[str]) -> list[Finding]:
    """vulture's findings in `files` (paths relative to `top`) that no rule clears."""
    v = Vulture(ignore_decorators=REGISTRATION_DECORATORS)
    v.scavenge([str(top / f) for f in files])
    if v.exit_code:
        raise ToolError(f"vulture could not read every file (exit {v.exit_code})")
    repo = Repo(top, files)
    modules: dict[str, Module] = {}
    out = []
    for item in v.get_unused_code(min_confidence=MIN_CONFIDENCE):
        path = Path(item.filename).resolve().relative_to(top.resolve()).as_posix()
        f = Finding(path, item.first_lineno, item.name, item.typ, f"{item.message} ({item.confidence}% confidence)")
        if path not in modules:
            modules[path] = Module(path, repo.source(path), repo)
        if not used_from_outside(f, modules[path]):
            out.append(f)
    return out


def findings_at(root: Path, rev: str | None) -> list[Finding]:
    """The findings of a revision of the repository at `root`, or of its working tree."""
    with tempfile.TemporaryDirectory() as tmp:
        top, files = snapshot(root, rev, Path(tmp))
        return findings(top, files)


def new_findings(root: Path, base: str, head: str | None = None) -> list[Finding]:
    before = Counter(f.key for f in findings_at(root, base))
    after = findings_at(root, head)
    grown = {k for k, n in Counter(f.key for f in after).items() if n > before[k]}
    return [f for f in after if f.key in grown]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base")
    ap.add_argument("--head", default=None, help="a revision; the working tree when omitted")
    ap.add_argument("--all", action="store_true", help="print every finding in the working tree")
    a = ap.parse_args(argv)
    if not a.all and not a.base:
        ap.error("--base is required unless --all")
    try:
        found = findings_at(Path.cwd(), None) if a.all else new_findings(Path.cwd(), a.base, a.head)
    except (ToolError, SyntaxError) as e:
        print(f"the check failed: {e}", file=sys.stderr)
        return 2
    for f in found:
        print(f)
    return 1 if found and not a.all else 0


if __name__ == "__main__":
    sys.exit(main())
