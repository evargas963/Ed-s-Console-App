"""Generate governance/section12_derivation_inventory.py — liquidity playbook."""
from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SECTION12_FILES = sorted(
    [
        "liquidity_models.py",
        "liquidity_value_engine.py",
        "print_liquidity_value_snapshot.py",
        "run_liquidity_sample.py",
    ]
)

OVERRIDES: dict[tuple[str, str], tuple[str, str, str]] = {
    ("liquidity_models.py", "zone_class_for_type"): (
        "zone taxonomy",
        "NONE",
        "Maps ZoneType enum to display class; no market-field reads.",
    ),
    ("liquidity_models.py", "Zone.zone_class"): (
        "zone taxonomy",
        "NONE",
        "Property delegates to zone_class_for_type; no OHLC derivation.",
    ),
    ("liquidity_value_engine.py", "_resolve_bar_timestamp"): (
        "pricehistory.candles.datetime",
        "REPLACED",
        "Schwab pricehistory bars require datetime leaf; fail-closed when absent (§1 align).",
    ),
    ("liquidity_value_engine.py", "_schwab_pricehistory_bar_missing_datetime"): (
        "pricehistory.candles.datetime",
        "NONE",
        "Guard helper for missing Schwab datetime; covered by _resolve_bar_timestamp.",
    ),
    ("liquidity_value_engine.py", "merge_schwab_bars_with_live_overlay"): (
        "pricehistory.candles.* + live overlay",
        "KEEP_DERIVED",
        "Merges normalized Schwab history bars with live overlay by timestamp.",
    ),
    ("liquidity_value_engine.py", "_bars_to_list"): (
        "bars.open|high|low|close|volume",
        "KEEP_DERIVED",
        "Normalizes OHLCV bar dicts/DataFrame via _resolve_bar_timestamp.",
    ),
    ("liquidity_value_engine.py", "generate_liquidity_value_snapshot"): (
        "OHLCV bars",
        "KEEP_DERIVED",
        "Public snapshot entry; structural levels from normalized bars.",
    ),
    ("liquidity_value_engine.py", "generate_playbook_state"): (
        "OHLCV bars",
        "KEEP_DERIVED",
        "Full-session playbook from checkpoint snapshots on bars.",
    ),
    ("liquidity_value_engine.py", "playbook_state_to_dict"): (
        "SnapshotOutput",
        "NONE",
        "Serializes PlaybookState dataclass; no market derivation.",
    ),
    ("liquidity_value_engine.py", "summarize_snapshot"): (
        "SnapshotOutput",
        "NONE",
        "Human-readable summary of snapshot output.",
    ),
    ("print_liquidity_value_snapshot.py", "_fetch_bars_from_schwab"): (
        "pricehistory.candles.*",
        "PASS_THROUGH",
        "CLI fetches session bars via polling_adapter; engine consumes normalized bars.",
    ),
    ("print_liquidity_value_snapshot.py", "_snapshot_to_dict"): (
        "SnapshotOutput",
        "NONE",
        "JSON serialization helper for CLI output.",
    ),
    ("print_liquidity_value_snapshot.py", "main"): (
        "—",
        "NONE",
        "CLI entrypoint; delegates bar fetch then engine.",
    ),
    ("run_liquidity_sample.py", "main"): (
        "—",
        "NONE",
        "Sample harness CLI; delegates to print helper and engine.",
    ),
}

_BAR_KW = ("open", "high", "low", "close", "volume", "vwap", "atr", "orb", "bars")
_LEVEL_KW = ("level", "zone", "snapshot", "poc", "vah", "val", "cluster", "profile")


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

    if file == "liquidity_models.py":
        return ("—", "NONE", "Datamodel enum/dataclass module; no bar derivation.")

    if name_l in ("main", "_main") or name_l.startswith("cli_"):
        return ("—", "NONE", "CLI entrypoint.")

    if name_l.startswith("_positive_float") or name_l.startswith("_float_or_none"):
        return ("—", "NONE", "Numeric coercion helper.")

    if "schwab" in name_l and "missing" in name_l:
        return (
            "pricehistory.candles.datetime",
            "NONE",
            "Schwab bar guard helper.",
        )

    if name_l.startswith("build_") and "snapshot" in name_l:
        return (
            "OHLCV bars",
            "KEEP_DERIVED",
            "Structural snapshot builder from normalized session bars.",
        )

    if any(k in name_l for k in ("compute_", "get_", "cluster_", "merge_")):
        if any(k in body_l for k in _BAR_KW):
            return (
                "bars.open|high|low|close|volume",
                "KEEP_DERIVED",
                "Derives liquidity/structure levels from normalized OHLCV bars.",
            )

    if any(k in body_l for k in _BAR_KW) and any(k in name_l for k in _LEVEL_KW + ("bar", "rth", "cutoff")):
        return (
            "bars.open|high|low|close|volume",
            "KEEP_DERIVED",
            "Session level/zone math on normalized bars.",
        )

    if any(k in body_l for k in _BAR_KW):
        return (
            "bars.open|high|low|close|volume",
            "KEEP_DERIVED",
            "Bar-based liquidity/value derivation.",
        )

    return ("—", "NONE", "No Schwab market-field derivation in function body.")


def main() -> None:
    rows: list[tuple[str, int, str, str, str, str]] = []
    for rel in SECTION12_FILES:
        path = ROOT / rel
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        for qual, fn in _walk(tree, text):
            body = _fn_body(text, fn)
            leaf, disp, just = classify(rel, qual, fn, body)
            rows.append((rel, fn.lineno, qual, leaf, disp, just))

    header = '''"""
Section 12 Schwab-leaf derivation audit inventory (liquidity playbook).

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


SECTION12_DERIVATION_INVENTORY: tuple[DerivationRecord, ...] = (
'''
    lines = [header]
    for file, line, func, leaf, disp, just in rows:
        j = just.replace('"', '\\"')
        lines.append(
            f'    DerivationRecord("{file}", "{line}", "{func}", "{leaf}", "{disp}", "{j}"),'
        )
    lines.append(")")
    lines.append("")
    lines.append("SECTION12_FILES = frozenset({")
    for f in SECTION12_FILES:
        lines.append(f'    "{f}",')
    lines.append("})")
    lines.append("")

    out = ROOT / "governance" / "section12_derivation_inventory.py"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {len(rows)} records to {out}")
    print("dispositions:", dict(Counter(r[4] for r in rows)))


if __name__ == "__main__":
    main()
