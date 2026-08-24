"""
Shared inventory coverage gate for section-by-section Schwab derivation audits.

Every ``def`` / ``async def`` in a section file (module, class method, nested helper)
must have an inventory row whose ``derivation`` equals the qualified name.

Active inventories use ``governance.traceable_derivation.TraceableDerivation``
(structured inputs + validated Schwab paths). Legacy categorical inventories live under
``governance/archive/legacy_categorical_inventories_v1/``.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FunctionRef:
    file: str
    qualified_name: str
    line: int
    scope: str  # module | class | nested
    parent: str | None


def _walk_functions(
    node: ast.AST,
    *,
    rel: str,
    class_stack: tuple[str, ...] = (),
    func_stack: tuple[str, ...] = (),
) -> list[FunctionRef]:
    out: list[FunctionRef] = []

    if isinstance(node, ast.ClassDef):
        for child in node.body:
            out.extend(
                _walk_functions(
                    child,
                    rel=rel,
                    class_stack=class_stack + (node.name,),
                    func_stack=func_stack,
                )
            )
        return out

    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        qual = ".".join(class_stack + func_stack + (node.name,))
        if func_stack:
            scope = "nested"
            parent = ".".join(class_stack + func_stack)
        elif class_stack:
            scope = "class"
            parent = ".".join(class_stack)
        else:
            scope = "module"
            parent = None
        out.append(
            FunctionRef(
                file=rel,
                qualified_name=qual,
                line=node.lineno,
                scope=scope,
                parent=parent,
            )
        )
        for child in node.body:
            out.extend(
                _walk_functions(
                    child,
                    rel=rel,
                    class_stack=class_stack,
                    func_stack=func_stack + (node.name,),
                )
            )
        return out

    if isinstance(node, ast.Module):
        for child in node.body:
            out.extend(_walk_functions(child, rel=rel))
    return out


def all_functions_in_file(repo_root: Path, rel: str) -> list[FunctionRef]:
    tree = ast.parse((repo_root / rel).read_text(encoding="utf-8"))
    return _walk_functions(tree, rel=rel)


def assert_inventory_covers_all_functions(
    repo_root: Path,
    section_files: frozenset[str],
    inventory: tuple,
    *,
    derivation_attr: str = "derivation",
    file_attr: str = "file",
    coverage_parent_attr: str = "coverage_parent",
) -> None:
    """
    Fail if any ``def`` in a section file lacks an inventory row.

  Optional ``coverage_parent`` on a record: nested helper covered by parent row
    (parent ``derivation`` must exist in the same file).
    """
    by_file: dict[str, set[str]] = {f: set() for f in section_files}
    covered_by_parent: dict[str, dict[str, str]] = {f: {} for f in section_files}

    for row in inventory:
        fn = getattr(row, derivation_attr)
        fl = getattr(row, file_attr)
        if fl not in by_file:
            continue
        by_file[fl].add(fn)
        parent = getattr(row, coverage_parent_attr, None)
        if parent:
            covered_by_parent[fl][fn] = parent

    errors: list[str] = []
    for rel in sorted(section_files):
        required = {fn.qualified_name for fn in all_functions_in_file(repo_root, rel)}
        inv_fns = by_file.get(rel, set())
        parent_map = covered_by_parent.get(rel, {})

        satisfied: set[str] = set()
        for qual, parent in parent_map.items():
            if qual in required and parent in inv_fns:
                satisfied.add(qual)

        missing = required - inv_fns - satisfied
        extra = inv_fns - required
        if missing:
            errors.append(
                f"{rel}: missing {len(missing)} def(s): "
                f"{sorted(missing)[:10]}{'...' if len(missing) > 10 else ''}"
            )
        if extra:
            errors.append(f"{rel}: stale inventory: {sorted(extra)[:8]}")

        by_scope: dict[str, int] = {}
        for fn in all_functions_in_file(repo_root, rel):
            by_scope[fn.scope] = by_scope.get(fn.scope, 0) + 1
        inv_in_file = len(inv_fns & required) + len(satisfied)
        if inv_in_file < len(required):
            errors.append(
                f"{rel}: inventoried {inv_in_file}/{len(required)} "
                f"(module={by_scope.get('module',0)} class={by_scope.get('class',0)} "
                f"nested={by_scope.get('nested',0)})"
            )

    assert not errors, "Section inventory coverage gaps:\n" + "\n".join(errors)


_NONE_STUB_JUSTIFICATION = (
    "No market-field derivation: No Schwab market-field derivation in function body."
)
_NESTED_STUB_JUSTIFICATION = (
    "No market-field derivation: Nested helper; parent row owns derivation semantics."
)


def _format_producer_refs(refs: tuple[str, ...]) -> str:
    if not refs:
        return "()"
    return "(" + ", ".join(f'"{r}"' for r in refs) + ",)"


def format_traceable_derivation_row(row_class_name: str, row: object) -> str:
    """Serialize one MegaNTraceableDerivation row for inventory modules."""
    leaf = "None" if row.schwab_leaf is None else repr(row.schwab_leaf)
    allow = "None" if row.allowlist_id is None else repr(row.allowlist_id)
    refs = _format_producer_refs(tuple(row.producer_refs))
    just = str(row.justification).replace("\\", "\\\\").replace('"', '\\"')
    return (
        f'    {row_class_name}("{row.file}", {row.line}, "{row.derivation}", '
        f'"{row.disposition}", {leaf}, {refs}, {allow}, "{just}"),'
    )


def sync_traceable_inventory_to_ast(
    repo_root: Path,
    section_files: frozenset[str],
    inventory: tuple,
    row_class: type,
) -> tuple:
    """Drop stale rows; append NONE stubs for every AST ``def`` missing from inventory."""
    required_by_key: dict[tuple[str, str], FunctionRef] = {}
    for rel in section_files:
        for fn in all_functions_in_file(repo_root, rel):
            required_by_key[(rel, fn.qualified_name)] = fn

    kept: dict[tuple[str, str], object] = {}
    for row in inventory:
        key = (row.file, row.derivation)
        if key in required_by_key:
            kept[key] = row

    for key, fn in required_by_key.items():
        if key in kept:
            continue
        justification = (
            _NESTED_STUB_JUSTIFICATION if fn.scope == "nested" else _NONE_STUB_JUSTIFICATION
        )
        kept[key] = row_class(key[0], fn.line, key[1], "NONE", None, (), None, justification)

    return tuple(sorted(kept.values(), key=lambda r: (r.file, r.line, r.derivation)))


def rewrite_mega_inventory_tuple(
    module_path: Path,
    *,
    inventory_attr: str,
    row_class_name: str,
    rows: tuple,
) -> None:
    """Replace the inventory tuple body in a governance/megaN_traceable_inventory.py file."""
    text = module_path.read_text(encoding="utf-8")
    marker = f"{inventory_attr}: tuple"
    start = text.index(marker)
    open_paren = text.index("(", start)
    close_paren = text.rindex("\n)\n")
    header = text[: open_paren + 1]
    footer = text[close_paren:]
    body_lines = [format_traceable_derivation_row(row_class_name, row) for row in rows]
    module_path.write_text(
        header + "\n" + "\n".join(body_lines) + footer,
        encoding="utf-8",
    )

