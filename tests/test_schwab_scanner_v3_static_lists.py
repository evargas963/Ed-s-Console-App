"""
Deliverable 14 — V3-A static analysis: no hand-curated market-token literals at module level.

Heuristic: in `tools/schwab_universal_coverage_scanner_v3/*.py`, flag module-level
collections of string literals containing known market-token examples, or
module-level string constants that are themselves market tokens.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_PKG = Path(__file__).resolve().parent.parent / "tools" / "schwab_universal_coverage_scanner_v3"

# Probe tokens — must not appear as module-level curated literals in scanner source.
_MARKET_PROBE = frozenset(
    {
        "bid",
        "ask",
        "theta",
        "delta",
        "volume",
        "volatility",
        "openinterest",
    }
)


def _str_literals_in_node(node: ast.AST) -> set[str]:
    out: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            out.add(sub.value.lower())
    return out


def _check_module(tree: ast.Module, path: Path) -> None:
    for stmt in tree.body:
        if not isinstance(stmt, ast.Assign):
            continue
        for t in stmt.targets:
            if not isinstance(t, ast.Name):
                continue
            # Allow structural builtins filter in python_scanner (not market tokens).
            if t.id == "_PY_CORE_CALLABLES":
                continue
            val = stmt.value
            if isinstance(val, (ast.Set, ast.List, ast.Tuple)):
                lits = _str_literals_in_node(val)
                bad = lits & _MARKET_PROBE
                assert not bad, f"{path}: module-level {t.id} contains market-like literals {bad}"
            if isinstance(val, ast.Constant) and isinstance(val.value, str):
                if val.value.lower() in _MARKET_PROBE:
                    assert False, f"{path}: module-level {t.id} = market-like string literal"


@pytest.mark.parametrize(
    "pyfile",
    sorted(_PKG.glob("*.py")),
    ids=lambda p: p.name,
)
def test_v3_package_no_module_level_market_literal_collections(pyfile: Path) -> None:
    if pyfile.name == "__init__.py":
        return
    src = pyfile.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(pyfile))
    _check_module(tree, pyfile)
