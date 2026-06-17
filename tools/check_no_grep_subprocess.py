"""Pre-commit guard: fail if staged Python invokes grep/rg via subprocess."""
from __future__ import annotations

import ast
import sys
from pathlib import Path

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
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    self._check_string(arg.value, node.lineno)
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
    paths = [Path(p) for p in (argv if argv is not None else sys.argv[1:])]
    if not paths:
        return 0
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
