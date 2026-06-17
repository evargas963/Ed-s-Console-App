"""Generate governance/section9_derivation_inventory.py — one row per def in features/*.py."""
from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SECTION9_FILES = sorted(
    f"features/{p.name}"
    for p in (ROOT / "features").glob("*.py")
    if p.name != "__init__.py"
)

OVERRIDES: dict[tuple[str, str], tuple[str, str, str]] = {
    (
        "features/mvp_source_coercion.py",
        "strict_float_from_raw",
    ): (
        "canonical feature fields",
        "KEEP_DERIVED",
        "Fail-closed numeric coercion; no silent default to 0.",
    ),
    (
        "features/mvp_source_coercion.py",
        "coerce_mvp_features_from_source",
    ): (
        "snapshot/ms_dict source keys",
        "KEEP_DERIVED",
        "Maps upstream market fields to MVP canonical schema.",
    ),
    (
        "features/inference_snapshot.py",
        "build_inference_snapshot_v1",
    ): (
        "ms_dict / DB row",
        "KEEP_DERIVED",
        "Canonical inference row from upstream market state.",
    ),
    (
        "features/fusion_model_input.py",
        "build_fusion_model_input",
    ): (
        "InferenceSnapshotV1",
        "KEEP_DERIVED",
        "Fusion tensor from canonical snapshot features.",
    ),
    (
        "features/lstm_sequence_input.py",
        "build_lstm_sequence_input",
    ): (
        "DB snapshots sequence",
        "PASS_THROUGH",
        "LSTM window from persisted snapshot rows.",
    ),
    (
        "features/shared_sequence_context.py",
        "build_shared_sequence_context",
    ): (
        "snapshots DB",
        "PASS_THROUGH",
        "Shared LSTM/Transformer sequence fetch from DB.",
    ),
    (
        "features/live_feature_adapter.py",
        "build_live_feature_row",
    ): (
        "live ms_dict",
        "KEEP_DERIVED",
        "Live feature row from current market state dict.",
    ),
    (
        "features/db_feature_adapter.py",
        "load_features_from_db",
    ): (
        "snapshots.*",
        "PASS_THROUGH",
        "Loads feature columns from snapshots table.",
    ),
}

_SCHEMA_KW = ("schema", "contract", "parity", "integrity", "allowed_", "validate")
_MARKET_KW = (
    "spot",
    "vwap",
    "gamma",
    "gex",
    "iv",
    "vol",
    "quote",
    "chain",
    "snapshot",
    "ms_dict",
    "canonical",
    "feature",
    "liquidity",
)


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
    if any(k in body_l or k in name_l for k in _SCHEMA_KW):
        return ("—", "NONE", "Schema/contract validation; no market-field derivation.")
    if "build_" in name_l or "load_" in name_l or "coerce" in name_l:
        return (
            "snapshots.* / InferenceSnapshotV1",
            "KEEP_DERIVED",
            "Feature builder from upstream or persisted canonical inputs.",
        )
    if any(kw in body_l for kw in _MARKET_KW):
        return (
            "canonical feature fields",
            "KEEP_DERIVED",
            "Feature-layer transform on upstream Schwab-first inputs.",
        )
    return ("—", "NONE", "No Schwab market-field derivation in function body.")


def main() -> None:
    rows: list[tuple[str, int, str, str, str, str]] = []
    for rel in SECTION9_FILES:
        text = (ROOT / rel).read_text(encoding="utf-8")
        tree = ast.parse(text)
        for qual, fn in _walk(tree, text):
            body = _fn_body(text, fn)
            leaf, disp, just = classify(rel, qual, fn, body)
            rows.append((rel, fn.lineno, qual, leaf, disp, just))

    header = '''"""
Section 9 Schwab-leaf derivation audit inventory (features / ML inputs).

One row per ``def`` in ``features/*.py`` (module, class method, nested helper).
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


SECTION9_DERIVATION_INVENTORY: tuple[DerivationRecord, ...] = (
'''
    lines = [header]
    for file, line, func, leaf, disp, just in rows:
        j = just.replace('"', '\\"')
        lines.append(
            f'    DerivationRecord("{file}", "{line}", "{func}", "{leaf}", "{disp}", "{j}"),'
        )
    lines.append(")")
    lines.append("")
    lines.append("SECTION9_FILES = frozenset({")
    for f in SECTION9_FILES:
        lines.append(f'    "{f}",')
    lines.append("})")
    lines.append("")

    out = ROOT / "governance" / "section9_derivation_inventory.py"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {len(rows)} records to {out}")
    print("dispositions:", dict(Counter(r[4] for r in rows)))


if __name__ == "__main__":
    main()
