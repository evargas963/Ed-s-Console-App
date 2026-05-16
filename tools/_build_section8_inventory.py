"""Generate governance/section8_derivation_inventory.py — one row per def (all scopes)."""
from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SECTION8_FILES = [
    "monte_carlo.py",
    "mc_fusion_adjustment.py",
    "volatility_regime.py",
    "regime_engine.py",
]

OVERRIDES: dict[tuple[str, str], tuple[str, str, str]] = {
    ("monte_carlo.py", "simulate"): (
        "iv,realized_vol,atr,spot (upstream)",
        "KEEP_DERIVED",
        "MC paths from upstream vol/spot; no Schwab wire ingest.",
    ),
    ("monte_carlo.py", "_blend_sigma"): (
        "iv,realized_vol,atr,spot",
        "KEEP_DERIVED",
        "Sigma blend; inputs from Schwab-first chain/candles upstream.",
    ),
    ("monte_carlo.py", "_compute_drift"): (
        "regime, confidence",
        "KEEP_DERIVED",
        "Drift from regime + model confidence; not a Schwab leaf.",
    ),
    ("monte_carlo.py", "MonteCarloOutput.mc_feature_dict"): (
        "derived MC features",
        "KEEP_DERIVED",
        "MC feature dict for fusion; not quote fields.",
    ),
    ("mc_fusion_adjustment.py", "apply_mc_adjustment"): (
        "fusion triplets + MC features",
        "KEEP_DERIVED",
        "Blends MC path features into fusion probabilities.",
    ),
    ("mc_fusion_adjustment.py", "fuse_payload_apply_mc_adjustment"): (
        "fusion payload",
        "KEEP_DERIVED",
        "Applies MC adjustment on fusion payload object.",
    ),
    ("mc_fusion_adjustment.py", "normalize_mc"): (
        "MC output dict",
        "KEEP_DERIVED",
        "Normalizes MC output relative to spot.",
    ),
    ("volatility_regime.py", "classify_volatility_regime"): (
        "SignalInput vol fields",
        "KEEP_DERIVED",
        "Vol policy from rv/iv/atr/vix upstream fields.",
    ),
    ("regime_engine.py", "classify_regime"): (
        "SignalInput + RulesCard",
        "KEEP_DERIVED",
        "8-family regime from upstream levels/greeks/zone.",
    ),
}

_MARKET_KW = (
    "spot",
    "iv",
    "realized_vol",
    "atr",
    "vix",
    "vol",
    "sigma",
    "quote",
    "signalinput",
    "regime",
    "gamma",
    "gex",
    "vwap",
    "chain",
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
            "upstream SignalInput / vol leaves",
            "KEEP_DERIVED",
            "MC/regime metric from upstream Schwab-first inputs.",
        )
    if "triplet" in fn.name or "blend" in fn.name or "argmax" in fn.name:
        return (
            "probability math",
            "NONE",
            "Pure probability blending helper.",
        )
    if qual.endswith("._fallback") or fn.name == "_fallback":
        return ("—", "NONE", "MC fallback error payload.")
    if fn.name == "_f" or fn.name.startswith("_score_"):
        return ("—", "NONE", "Scoring/helper; no new market-field derivation.")
    return ("—", "NONE", "No Schwab market-field derivation in function body.")


def main() -> None:
    rows: list[tuple[str, int, str, str, str, str]] = []
    for rel in SECTION8_FILES:
        text = (ROOT / rel).read_text(encoding="utf-8")
        tree = ast.parse(text)
        for qual, fn in _walk(tree, text):
            body = _fn_body(text, fn)
            leaf, disp, just = classify(rel, qual, fn, body)
            rows.append((rel, fn.lineno, qual, leaf, disp, just))

    header = '''"""
Section 8 Schwab-leaf derivation audit inventory (MC + regime + volatility).

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


SECTION8_DERIVATION_INVENTORY: tuple[DerivationRecord, ...] = (
'''
    lines = [header]
    for file, line, func, leaf, disp, just in rows:
        j = just.replace('"', '\\"')
        lines.append(
            f'    DerivationRecord("{file}", "{line}", "{func}", "{leaf}", "{disp}", "{j}"),'
        )
    lines.append(")")
    lines.append("")
    lines.append("SECTION8_FILES = frozenset({")
    for f in SECTION8_FILES:
        lines.append(f'    "{f}",')
    lines.append("})")
    lines.append("")

    out = ROOT / "governance" / "section8_derivation_inventory.py"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {len(rows)} records to {out}")
    print("dispositions:", dict(Counter(r[4] for r in rows)))


if __name__ == "__main__":
    main()
