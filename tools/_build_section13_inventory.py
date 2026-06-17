"""Generate governance/section13_derivation_inventory.py — similarity engines."""
from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SECTION13_FILES = sorted(
    ["adaptive_similarity_engine.py"]
    + [p.name for p in ROOT.glob("similarity_*.py")]
)

OVERRIDES: dict[tuple[str, str], tuple[str, str, str]] = {
    ("adaptive_similarity_engine.py", "run_adaptive_shadow_v2"): (
        "snapshots.* / tier SQL pool",
        "KEEP_DERIVED",
        "Shadow v2 selection on Issue 19 tier-1 candidate rows from DB.",
    ),
    ("adaptive_similarity_engine.py", "run_weighted_selection"): (
        "snapshots.*",
        "KEEP_DERIVED",
        "Weighted similarity ranking on broad candidate pool.",
    ),
    ("adaptive_similarity_engine.py", "run_baseline_control"): (
        "snapshots.*",
        "KEEP_DERIVED",
        "Delegates to production get_similar_setups baseline.",
    ),
    ("adaptive_similarity_engine.py", "_fetch_candidate_rows"): (
        "snapshots.*",
        "PASS_THROUGH",
        "Loads candidate rows from DB for similarity scoring.",
    ),
    ("adaptive_similarity_engine.py", "_fetch_issue19_tier1_candidate_rows"): (
        "snapshots.*",
        "PASS_THROUGH",
        "Issue 19 tier-1 SQL candidate pool fetch.",
    ),
    ("similarity_audit.py", "query_context_for_similarity"): (
        "snapshots.*",
        "KEEP_DERIVED",
        "Builds anchor query context from snapshot feature columns.",
    ),
    ("similarity_audit.py", "baseline_feature_contract_v1"): (
        "feature contract",
        "NONE",
        "Static feature contract definition for similarity tiers.",
    ),
    ("similarity_audit.py", "build_similar_inspection_bundle"): (
        "trace + rows",
        "KEEP_DERIVED",
        "Inspection bundle from similarity trace and selected rows.",
    ),
}

_SIM_KW = ("similar", "tier", "anchor", "candidate", "score", "bucket", "constraint")
_DATA_KW = ("snapshot", "feature", "row", "sql", "horizon", "regime", "vwap", "zone")
_SCHEMA_KW = ("contract", "validate", "audit", "trace", "report", "inspect")


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

    if name_l in ("main", "_main") or name_l.startswith("cli_"):
        return ("—", "NONE", "CLI entrypoint.")

    if name_l.startswith("default_") or "weight_profiles" in name_l or name_l.endswith("_v1"):
        if "contract" in name_l or "profile" in name_l or "weights" in name_l:
            if not any(k in body_l for k in _DATA_KW):
                return ("—", "NONE", "Static config/contract helper.")

    if "contract" in name_l and "feature" in name_l:
        return ("feature contract", "NONE", "Feature contract schema definition.")

    if any(k in name_l for k in ("validate_", "widening_", "withheld_", "weakest_", "tier_stop")):
        return ("labeled counts / tiers", "NONE", "Tier viability audit counters.")

    if name_l.startswith("_fetch") or "sql" in body_l:
        return (
            "snapshots.*",
            "PASS_THROUGH",
            "DB fetch for similarity candidate rows.",
        )

    if any(k in name_l for k in ("run_", "score", "compare", "search", "universe", "survivorship")):
        if any(k in body_l for k in _DATA_KW):
            return (
                "snapshots.* / features",
                "KEEP_DERIVED",
                "Similarity analysis on persisted snapshot features.",
            )

    if any(k in body_l for k in _DATA_KW) and any(k in name_l + body_l for k in _SIM_KW):
        return (
            "snapshots.* / features",
            "KEEP_DERIVED",
            "Similarity scoring or filtering on snapshot-derived features.",
        )

    if any(k in body_l for k in _DATA_KW):
        return (
            "snapshots.*",
            "KEEP_DERIVED",
            "Operates on persisted snapshot/feature rows.",
        )

    if any(k in name_l for k in _SCHEMA_KW):
        return ("—", "NONE", "Similarity audit/trace helper; no live market ingest.")

    return ("—", "NONE", "No Schwab market-field derivation in function body.")


def main() -> None:
    rows: list[tuple[str, int, str, str, str, str]] = []
    for rel in SECTION13_FILES:
        path = ROOT / rel
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        for qual, fn in _walk(tree, text):
            body = _fn_body(text, fn)
            leaf, disp, just = classify(rel, qual, fn, body)
            rows.append((rel, fn.lineno, qual, leaf, disp, just))

    header = '''"""
Section 13 Schwab-leaf derivation audit inventory (similarity engines).

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


SECTION13_DERIVATION_INVENTORY: tuple[DerivationRecord, ...] = (
'''
    lines = [header]
    for file, line, func, leaf, disp, just in rows:
        j = just.replace('"', '\\"')
        lines.append(
            f'    DerivationRecord("{file}", "{line}", "{func}", "{leaf}", "{disp}", "{j}"),'
        )
    lines.append(")")
    lines.append("")
    lines.append("SECTION13_FILES = frozenset({")
    for f in SECTION13_FILES:
        lines.append(f'    "{f}",')
    lines.append("})")
    lines.append("")

    out = ROOT / "governance" / "section13_derivation_inventory.py"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {len(rows)} records to {out}")
    print("files:", len(SECTION13_FILES))
    print("dispositions:", dict(Counter(r[4] for r in rows)))


if __name__ == "__main__":
    main()
