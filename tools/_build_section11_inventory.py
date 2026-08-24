"""Generate governance/section11_derivation_inventory.py — calibration + fusion."""
from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _section11_files() -> list[str]:
    out: list[str] = []
    for p in sorted((ROOT / "calibration").rglob("*.py")):
        if p.name == "__init__.py":
            continue
        out.append(p.relative_to(ROOT).as_posix().replace("\\", "/"))
    for p in sorted((ROOT / "arch_competition").glob("*.py")):
        if p.name == "__init__.py":
            continue
        out.append(p.relative_to(ROOT).as_posix().replace("\\", "/"))
    for name in ("governed_stack_contract.py", "bayesian_fusion.py"):
        out.append(name)
    return out


SECTION11_FILES = _section11_files()

OVERRIDES: dict[tuple[str, str], tuple[str, str, str]] = {
    ("bayesian_fusion.py", "fuse_probabilities"): (
        "model probs + priors",
        "KEEP_DERIVED",
        "Bayesian fusion of upstream model outputs; no Schwab ingest.",
    ),
    ("governed_stack_contract.py", "validate_governed_stack_bundle"): (
        "stack contract",
        "NONE",
        "Schema validation for governed stack payloads.",
    ),
    ("calibration/writer.py", "write_calibration_row"): (
        "calibration DB",
        "PASS_THROUGH",
        "Persists calibration audit rows to DB.",
    ),
    ("calibration/schema.py", "ensure_schema"): (
        "calibration schema",
        "NONE",
        "Calibration table schema DDL/migrations.",
    ),
}

_CALIB_KW = ("calibrat", "conformal", "isotonic", "outcome", "anchor", "audit", "repair")
_SCHEMA_KW = ("schema", "validate", "json", "sql", "pragma", "ddl")
_DATA_KW = ("snapshot", "feature", "spot", "outcome", "probability", "fusion", "signal")


def _fn_body(text: str, fn: ast.FunctionDef) -> str:
    end = fn.end_lineno or fn.lineno
    return "\n".join(text.splitlines()[fn.lineno - 1 : end])


def _walk(tree: ast.AST, text: str, class_stack: tuple[str, ...] = (), func_stack: tuple[str, ...] = ()):
    if isinstance(tree, ast.ClassDef):
        for child in tree.body:
            yield from _walk(child, text, class_stack + (tree.name,), func_stack)
    elif isinstance(tree, (ast.FunctionDef, ast.AsyncFunctionDef)):
        qual = ".".join(class_stack + func_stack + (tree.name,))
        yield qual, tree
        for child in tree.body:
            yield from _walk(child, text, class_stack, func_stack + (tree.name,))
    elif isinstance(tree, ast.Module):
        for child in tree.body:
            yield from _walk(child, text, class_stack, func_stack)


def classify(file: str, qual: str, fn: ast.FunctionDef, body: str) -> tuple[str, str, str]:
    key = (file, qual)
    if key in OVERRIDES:
        return OVERRIDES[key]

    body_l = body.lower()
    name_l = fn.name.lower()
    if file == "bayesian_fusion.py" or "fusion" in name_l:
        return (
            "fusion inputs",
            "KEEP_DERIVED",
            "Probability fusion; consumes model outputs only.",
        )
    if file == "governed_stack_contract.py":
        return ("stack contract", "NONE", "Governed stack contract validation.")
    if "arch_competition" in file:
        if any(k in body_l for k in _DATA_KW):
            return (
                "eval bundles / snapshots",
                "KEEP_DERIVED",
                "Arch competition metrics on persisted eval data.",
            )
        return ("—", "NONE", "Arch competition orchestration; no market-field derivation.")
    if any(k in name_l for k in ("main", "_main", "cli")):
        return ("—", "NONE", "CLI/script entrypoint.")
    if any(k in body_l or k in file for k in _SCHEMA_KW) and "repair" not in name_l:
        if "validate" in name_l or "schema" in name_l or "audit" in name_l:
            return ("—", "NONE", "Calibration schema/audit helper.")
    if any(k in body_l for k in _DATA_KW):
        return (
            "snapshots.* / outcomes",
            "KEEP_DERIVED",
            "Calibration on persisted snapshot/outcome data.",
        )
    if any(k in file or k in body_l for k in _CALIB_KW):
        return (
            "calibration artifacts",
            "KEEP_DERIVED",
            "Calibration pipeline step on stored data.",
        )
    return ("—", "NONE", "No Schwab market-field derivation in function body.")


def main() -> None:
    rows: list[tuple[str, int, str, str, str, str]] = []
    for rel in SECTION11_FILES:
        path = ROOT / rel
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        for qual, fn in _walk(tree, text):
            body = _fn_body(text, fn)
            leaf, disp, just = classify(rel, qual, fn, body)
            rows.append((rel, fn.lineno, qual, leaf, disp, just))

    header = '''"""
Section 11 Schwab-leaf derivation audit inventory (calibration + fusion).

One row per ``def`` (module, class method, nested helper).
Disposition: REPLACED | KEEP_DERIVED | PASS_THROUGH | NONE
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DerivationRecord:
    file: str
    line: str
    derivation: str
    schwab_leaf: str
    disposition: str
    justification: str


SECTION11_DERIVATION_INVENTORY: tuple[DerivationRecord, ...] = (
'''
    lines = [header]
    for file, line, func, leaf, disp, just in rows:
        j = just.replace('"', '\\"')
        lines.append(
            f'    DerivationRecord("{file}", "{line}", "{func}", "{leaf}", "{disp}", "{j}"),'
        )
    lines.append(")")
    lines.append("")
    lines.append("SECTION11_FILES = frozenset({")
    for f in SECTION11_FILES:
        lines.append(f'    "{f}",')
    lines.append("})")
    lines.append("")

    out = ROOT / "governance" / "section11_derivation_inventory.py"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {len(rows)} records to {out}")
    print("files:", len(SECTION11_FILES))
    print("dispositions:", dict(Counter(r[4] for r in rows)))


if __name__ == "__main__":
    main()
