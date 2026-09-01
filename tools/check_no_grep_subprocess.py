"""Guard: fail if tracked Python invokes grep/rg via subprocess.

TEST_SYSTEM_REHAB_V2 remediation: `main()` used to return 0 immediately when called
with no path arguments (`if not paths: return 0`), and .github/workflows/hardening.yml
invokes it with none -- so the "BLOCKING" CI step structurally could never fail,
independent of whether any staged/tracked file actually violated the rule. Fixed at
the root: no arguments now means "scan the canonical target population" (every
tracked .py file, the same git-index authority tools/anti_pattern_sweep.py::
iter_py_files already established for this repo -- RC-286/RC-307) rather than "scan
nothing". Passing explicit paths (the pre-commit staged-file usage) is unchanged."""
from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

BANNED = frozenset({"grep", "rg", "ripgrep", "awk", "sed"})


class SubprocessGrepVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.violations: list[tuple[int, str]] = []

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        name = None
        if isinstance(func, ast.Attribute) and func.attr in {"run", "call", "Popen"}:
            if isinstance(func.value, ast.Name) and func.value.id == "subprocess":
                name = "subprocess"
        elif isinstance(func, ast.Name) and func.id in {"system", "popen"}:
            name = func.id
        if name:
            # TEST_SYSTEM_REHAB_V2: the positional-args branch only matched a single
            # string constant (subprocess.run("grep foo")) and never a list/tuple
            # (subprocess.run(["grep", "foo"])) -- the far more common real-world
            # shape, and the exact form the gate's own required negative control
            # uses. A first positional list/tuple argument is now checked the same
            # way the keyword `args=[...]` form already was.
            for i, arg in enumerate(node.args):
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    self._check_string(arg.value, node.lineno)
                elif i == 0 and isinstance(arg, (ast.List, ast.Tuple)):
                    for elt in arg.elts:
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                            self._check_string(elt.value, node.lineno)
            for kw in node.keywords:
                if kw.arg in {"args", "cmd"} and isinstance(kw.value, ast.Constant):
                    if isinstance(kw.value.value, str):
                        self._check_string(kw.value.value, node.lineno)
                if kw.arg == "args" and isinstance(kw.value, (ast.List, ast.Tuple)):
                    for elt in kw.value.elts:
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                            self._check_string(elt.value, node.lineno)
        self.generic_visit(node)

    def _check_string(self, text: str, lineno: int) -> None:
        first = Path(text.split()[0]).name if text.split() else text
        if first in BANNED or any(f" {b} " in f" {text} " for b in BANNED):
            self.violations.append((lineno, text))


def check_file(path: Path) -> list[tuple[int, str]]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return []
    v = SubprocessGrepVisitor()
    v.visit(tree)
    return v.violations


def main(argv: list[str] | None = None) -> int:
    raw = argv if argv is not None else sys.argv[1:]
    if raw:
        paths = [Path(p) for p in raw]
    else:
        from tools.anti_pattern_sweep import iter_py_files
        paths = iter_py_files(production_only=False)
    failed = False
    for path in paths:
        if path.suffix != ".py" or not path.is_file():
            continue
        for lineno, expr in check_file(path):
            print(f"{path}:{lineno}: banned subprocess shell tool: {expr!r}")
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
