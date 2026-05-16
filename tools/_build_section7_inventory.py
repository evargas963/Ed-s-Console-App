"""Generate governance/section7_derivation_inventory.py — one row per def (all scopes)."""
from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SECTION7_FILES = sorted(
    f"v2_decision/{p.name}"
    for p in (ROOT / "v2_decision").glob("*.py")
    if p.name != "__init__.py"
) + ["lifecycle_rule_core.py"]

OVERRIDES: dict[tuple[str, str], tuple[str, str, str]] = {
    (
        "v2_decision/a2_price_precedence.py",
        "resolve_a2_contract_mid",
    ): (
        "chains.*.mark,bid,ask,last",
        "KEEP_DERIVED",
        "OP-006 contract mid ladder: mark → last → bid/ask/2 when mark+last absent.",
    ),
    (
        "v2_decision/a2_price_precedence.py",
        "contract_spread_pts_from_bid_ask",
    ): (
        "chains.*.bid,ask",
        "PASS_THROUGH",
        "Contract spread points from Schwab bid/ask leaves only.",
    ),
    (
        "v2_decision/a2_price_precedence.py",
        "resolve_a2_underlying_spread_pts",
    ): (
        "ms_dict spread_pts",
        "PASS_THROUGH",
        "Underlying spread from upstream quote path; not contract spread.",
    ),
    (
        "v2_decision/a2_option_expression.py",
        "build_a2_option_expression",
    ): (
        "chain_row, ms_dict",
        "KEEP_DERIVED",
        "A2 OE build from Schwab-first chain row + market state.",
    ),
    (
        "v2_decision/a2_option_expression.py",
        "_quote_staleness_ms",
    ): (
        "quotes quoteTime",
        "KEEP_DERIVED",
        "Quote staleness from Schwab time fields.",
    ),
    (
        "v2_decision/a2_lifecycle_sidecar.py",
        "build_a2_lifecycle_sidecar",
    ): (
        "ms_dict, chain",
        "KEEP_DERIVED",
        "Lifecycle sidecar from upstream market state.",
    ),
    (
        "lifecycle_rule_core.py",
        "derive_stop_distance_pct",
    ): (
        "spot, structural levels",
        "KEEP_DERIVED",
        "Stop distance from spot and key levels.",
    ),
    (
        "lifecycle_rule_core.py",
        "derive_target_levels",
    ): (
        "structural levels",
        "KEEP_DERIVED",
        "Target level selection from key levels geometry.",
    ),
}

_MARKET_KW = (
    "quote",
    "schwab",
    "bid",
    "ask",
    "mark",
    "spot",
    "chain",
    "ms_dict",
    "spread",
    "price",
    "volume",
    "datetime",
    "contract",
    "underlying",
    "strike",
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
    if any(kw in body_l for kw in _MARKET_KW):
        return (
            "upstream ms_dict / chains.*",
            "KEEP_DERIVED",
            "V2 lifecycle reads upstream Schwab-first state; no new wire ingest.",
        )
    if "artifact" in body_l or "conformal" in body_l or "isotonic" in body_l or "calibrat" in body_l:
        return (
            "calibration artifacts",
            "NONE",
            "Calibration/artifact plumbing; no live market-field derivation.",
        )
    if "replay" in body_l or "label" in fn.name.lower():
        return (
            "replay labels",
            "PASS_THROUGH",
            "Replay/offline label path; persisted inputs only.",
        )
    return ("—", "NONE", "No Schwab market-field derivation in function body.")


def main() -> None:
    rows: list[tuple[str, int, str, str, str, str]] = []
    for rel in SECTION7_FILES:
        text = (ROOT / rel).read_text(encoding="utf-8")
        tree = ast.parse(text)
        for qual, fn in _walk(tree, text):
            body = _fn_body(text, fn)
            leaf, disp, just = classify(rel, qual, fn, body)
            rows.append((rel, fn.lineno, qual, leaf, disp, just))

    header = '''"""
Section 7 Schwab-leaf derivation audit inventory (V2 decision + A2 lifecycle).

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


SECTION7_DERIVATION_INVENTORY: tuple[DerivationRecord, ...] = (
'''
    lines = [header]
    for file, line, func, leaf, disp, just in rows:
        j = just.replace('"', '\\"')
        lines.append(
            f'    DerivationRecord("{file}", "{line}", "{func}", "{leaf}", "{disp}", "{j}"),'
        )
    lines.append(")")
    lines.append("")
    lines.append("SECTION7_FILES = frozenset({")
    for f in SECTION7_FILES:
        lines.append(f'    "{f}",')
    lines.append("})")
    lines.append("")

    out = ROOT / "governance" / "section7_derivation_inventory.py"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {len(rows)} records to {out}")
    print("dispositions:", dict(Counter(r[4] for r in rows)))


if __name__ == "__main__":
    main()
