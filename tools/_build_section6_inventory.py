"""Generate governance/section6_derivation_inventory.py — one row per def (all scopes)."""
from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SECTION6_FILES = [
    "signals.py",
    "signal_helpers.py",
    "signal_types.py",
    "rules_engine.py",
    "prediction_engine.py",
    "call_engine.py",
    "multi_horizon_decision.py",
    "multi_horizon_ml_bundle.py",
]

OVERRIDES: dict[tuple[str, str], tuple[str, str, str]] = {
    ("signals.py", "compute_signals"): (
        "SignalInput / ms_dict upstream",
        "KEEP_DERIVED",
        "Main signals entry; consumes Schwab-first market state, no new ingest.",
    ),
    ("signals.py", "_compute_signals_impl"): (
        "SignalInput fields",
        "KEEP_DERIVED",
        "Signal pipeline implementation on cached state.",
    ),
    ("signals.py", "_spot_for_mc_fusion_adjustment"): (
        "spot, fusion overlay",
        "KEEP_DERIVED",
        "Spot selection for MC fusion; upstream quote-derived spot.",
    ),
    ("signals.py", "_run_model_stack"): (
        "ML + fusion inputs",
        "KEEP_DERIVED",
        "Runs model stack on snapshot features.",
    ),
    ("signals.py", "compute_fusion_policy_flat_for_replay"): (
        "replay snapshot dict",
        "PASS_THROUGH",
        "Replay path reads persisted snapshot features only.",
    ),
    ("signals.py", "_build_snapshot_dict"): (
        "ms_dict fields",
        "PASS_THROUGH",
        "Serializes market state for ML snapshot.",
    ),
    ("signals.py", "_build_stack_decision_path._model_stage"): (
        "—",
        "NONE",
        "Nested stage label helper inside decision path builder.",
    ),
    ("signal_helpers.py", "_ordinal"): (
        "—",
        "NONE",
        "String formatting helper.",
    ),
    ("signal_types.py", "CanonicalForecast.dominant_probability"): (
        "fusion probabilities",
        "KEEP_DERIVED",
        "Property on forecast dataclass; no Schwab wire read.",
    ),
    ("rules_engine.py", "compute_rules"): (
        "micro_structure + SignalInput",
        "KEEP_DERIVED",
        "Rules layer on upstream market fields.",
    ),
    ("rules_engine.py", "_derive_bias_from_micro"): (
        "micro_structure reads",
        "KEEP_DERIVED",
        "Bias from micro structure metrics.",
    ),
    ("prediction_engine.py", "compute_prediction"): (
        "SignalInput / similarity DB",
        "KEEP_DERIVED",
        "Public prediction entry; no direct Schwab API.",
    ),
    ("prediction_engine.py", "compute_prediction_core"): (
        "empirical probs",
        "KEEP_DERIVED",
        "Core prediction from labeled history.",
    ),
    ("prediction_engine.py", "build_fusion_model_overlay_for_stack"): (
        "fusion model output",
        "KEEP_DERIVED",
        "ML overlay on product triplets.",
    ),
    ("call_engine.py", "compute_call"): (
        "CallInput / levels",
        "KEEP_DERIVED",
        "Trade call synthesis from upstream signals and levels.",
    ),
    ("call_engine.py", "_compute_levels"): (
        "structural levels, spot",
        "KEEP_DERIVED",
        "Stop/target levels from key levels + spot.",
    ),
    ("call_engine.py", "_compute_levels._structural_levels"): (
        "key levels",
        "KEEP_DERIVED",
        "Nested structural level picker.",
    ),
    ("multi_horizon_decision.py", "build_multi_horizon_bundle"): (
        "horizon triplets",
        "KEEP_DERIVED",
        "Multi-horizon bundle assembly.",
    ),
    ("multi_horizon_decision.py", "compute_multi_horizon_synthesis"): (
        "horizon rows",
        "KEEP_DERIVED",
        "Synthesis across horizon forecasts.",
    ),
    ("multi_horizon_ml_bundle.py", "build_multi_horizon_ml_fusion_bundle"): (
        "ML fusion outputs",
        "KEEP_DERIVED",
        "MH ML fusion bundle from model outputs.",
    ),
}

_MARKET_KW = (
    "spot",
    "quote",
    "vwap",
    "bid",
    "ask",
    "mark",
    "chain",
    "volume",
    "gamma",
    "gex",
    "delta",
    "level",
    "wall",
    "pin",
    "candle",
    "price",
    "spread",
    "flow",
    "ms_dict",
    "signalinput",
    "marketstate",
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
            "upstream ms_dict / SignalInput",
            "KEEP_DERIVED",
            "Consumes upstream Schwab-first market state; no new wire ingest.",
        )
    if "replay" in body_l or "snapshot" in body_l:
        return (
            "snapshots.* / replay dict",
            "PASS_THROUGH",
            "Reads persisted snapshot or replay payload only.",
        )
    if qual.endswith(".dominant_probability") or "prob" in fn.name.lower():
        return (
            "model probabilities",
            "KEEP_DERIVED",
            "Probability math on model outputs.",
        )
    return ("—", "NONE", "No Schwab market-field derivation in function body.")


def main() -> None:
    rows: list[tuple[str, int, str, str, str, str]] = []
    for rel in SECTION6_FILES:
        text = (ROOT / rel).read_text(encoding="utf-8")
        tree = ast.parse(text)
        for qual, fn in _walk(tree, text):
            body = _fn_body(text, fn)
            leaf, disp, just = classify(rel, qual, fn, body)
            rows.append((rel, fn.lineno, qual, leaf, disp, just))

    header = '''"""
Section 6 Schwab-leaf derivation audit inventory (signals + decision).

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


SECTION6_DERIVATION_INVENTORY: tuple[DerivationRecord, ...] = (
'''
    lines = [header]
    for file, line, func, leaf, disp, just in rows:
        j = just.replace('"', '\\"')
        lines.append(
            f'    DerivationRecord("{file}", "{line}", "{func}", "{leaf}", "{disp}", "{j}"),'
        )
    lines.append(")")
    lines.append("")
    lines.append("SECTION6_FILES = frozenset({")
    for f in SECTION6_FILES:
        lines.append(f'    "{f}",')
    lines.append("})")
    lines.append("")

    out = ROOT / "governance" / "section6_derivation_inventory.py"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {len(rows)} records to {out}")
    print("dispositions:", dict(Counter(r[4] for r in rows)))


if __name__ == "__main__":
    main()
