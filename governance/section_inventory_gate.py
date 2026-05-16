"""
Shared inventory coverage gate for section-by-section Schwab derivation audits.

Every module-level function in a section file must have >=1 inventory row
(derivation column equals function name).
"""

from __future__ import annotations

import ast
from pathlib import Path


def module_functions(repo_root: Path, rel: str) -> list[tuple[str, int, bool]]:
    tree = ast.parse((repo_root / rel).read_text(encoding="utf-8"))
    out: list[tuple[str, int, bool]] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            out.append((node.name, node.lineno, not node.name.startswith("_")))
    return out


def assert_inventory_covers_module_functions(
    repo_root: Path,
    section_files: frozenset[str],
    inventory: tuple,
    *,
    derivation_attr: str = "derivation",
    file_attr: str = "file",
) -> None:
    """Fail if any module-level def lacks an inventory row with matching derivation name."""
    by_file: dict[str, set[str]] = {f: set() for f in section_files}
    for row in inventory:
        fn = getattr(row, derivation_attr)
        fl = getattr(row, file_attr)
        if fl in by_file:
            by_file[fl].add(fn)

    errors: list[str] = []
    for rel in sorted(section_files):
        mod_fns = {name for name, _, _ in module_functions(repo_root, rel)}
        inv_fns = by_file.get(rel, set())
        missing = mod_fns - inv_fns
        extra = inv_fns - mod_fns
        pub = sum(1 for name, _, p in module_functions(repo_root, rel) if p)
        inv_count = len(inv_fns & mod_fns)
        if missing:
            errors.append(f"{rel}: missing {len(missing)} fn(s): {sorted(missing)[:8]}{'...' if len(missing)>8 else ''}")
        if inv_count < pub:
            errors.append(
                f"{rel}: inventory={inv_count} < public_functions={pub}"
            )
        if extra:
            errors.append(f"{rel}: stale inventory for: {sorted(extra)[:5]}")

    assert not errors, "Section inventory coverage gaps:\n" + "\n".join(errors)
