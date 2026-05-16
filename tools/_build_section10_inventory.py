"""Generate governance/section10_derivation_inventory.py — ML training + predict modules."""
from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SECTION10_FILES = sorted(
    [
        "ml_data_common.py",
        "ml_horizon.py",
        "ml_predict.py",
        "ml_train.py",
        "ml_scheduler.py",
        "lstm_model.py",
        "lstm_data.py",
        "xgboost_model.py",
        "transformer_train.py",
        "transformer_model.py",
        "train_all.py",
        "train_compare.py",
        "training_cache.py",
        "training_provenance.py",
        "training_cache_policy.py",
        "normalized_training_sync.py",
        "smoke_predict_active.py",
    ]
)

OVERRIDES: dict[tuple[str, str], tuple[str, str, str]] = {
    ("ml_data_common.py", "load_training_rows"): (
        "snapshots.* / normalized table",
        "PASS_THROUGH",
        "Training rows from DB snapshots; no live Schwab ingest.",
    ),
    ("lstm_data.py", "fetch_snapshot_sequence"): (
        "snapshots.*",
        "PASS_THROUGH",
        "LSTM sequence from persisted snapshot rows.",
    ),
    ("lstm_data.py", "merge_stream_5m_into_sequence"): (
        "snapshots.*",
        "KEEP_DERIVED",
        "Merges stream 5m rows into training sequence.",
    ),
    ("ml_predict.py", "predict_active_models"): (
        "InferenceSnapshotV1 / features",
        "KEEP_DERIVED",
        "Inference entry; consumes canonical features only.",
    ),
    ("ml_train.py", "train_model_for_horizon"): (
        "training rows",
        "KEEP_DERIVED",
        "Trains model from persisted feature rows.",
    ),
    ("train_all.py", "main"): (
        "—",
        "NONE",
        "CLI orchestration for batch training.",
    ),
    ("smoke_predict_active.py", "main"): (
        "active models",
        "KEEP_DERIVED",
        "Smoke test predict path on active artifacts.",
    ),
}

_TRAIN_KW = ("train", "fit", "epoch", "batch", "optimizer", "loss")
_PREDICT_KW = ("predict", "infer", "forward", "softmax", "prob")
_DATA_KW = (
    "snapshot",
    "feature",
    "sequence",
    "candle",
    "datetime",
    "row",
    "column",
    "tensor",
    "horizon",
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
    if name_l in ("main", "_main") or name_l.startswith("cli_"):
        return ("—", "NONE", "CLI entrypoint; no market-field derivation.")
    if "cache" in name_l or "provenance" in name_l or "manifest" in name_l:
        return ("—", "NONE", "Training cache/provenance metadata; no market derivation.")
    if "scheduler" in file or "horizon_slug" in body_l:
        if any(k in name_l for k in ("reset", "set_", "slug", "token")):
            return ("—", "NONE", "Horizon slug / scheduler bookkeeping.")
    if any(k in name_l for k in _TRAIN_KW) or "train_" in file:
        if any(k in body_l for k in _DATA_KW):
            return (
                "snapshots.* / training features",
                "KEEP_DERIVED",
                "Training path on persisted snapshot/feature rows.",
            )
    if any(k in name_l for k in _PREDICT_KW):
        return (
            "model features / InferenceSnapshotV1",
            "KEEP_DERIVED",
            "Inference on canonical features; no Schwab wire ingest.",
        )
    if any(k in body_l for k in _DATA_KW):
        return (
            "snapshots.* / feature columns",
            "KEEP_DERIVED",
            "ML data prep from upstream canonical inputs.",
        )
    if "model" in name_l and "load" in name_l:
        return ("artifact files", "NONE", "Loads trained model artifact from disk.")
    return ("—", "NONE", "No Schwab market-field derivation in function body.")


def main() -> None:
    rows: list[tuple[str, int, str, str, str, str]] = []
    for rel in SECTION10_FILES:
        text = (ROOT / rel).read_text(encoding="utf-8")
        tree = ast.parse(text)
        for qual, fn in _walk(tree, text):
            body = _fn_body(text, fn)
            leaf, disp, just = classify(rel, qual, fn, body)
            rows.append((rel, fn.lineno, qual, leaf, disp, just))

    header = '''"""
Section 10 Schwab-leaf derivation audit inventory (ML training + predict).

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


SECTION10_DERIVATION_INVENTORY: tuple[DerivationRecord, ...] = (
'''
    lines = [header]
    for file, line, func, leaf, disp, just in rows:
        j = just.replace('"', '\\"')
        lines.append(
            f'    DerivationRecord("{file}", "{line}", "{func}", "{leaf}", "{disp}", "{j}"),'
        )
    lines.append(")")
    lines.append("")
    lines.append("SECTION10_FILES = frozenset({")
    for f in SECTION10_FILES:
        lines.append(f'    "{f}",')
    lines.append("})")
    lines.append("")

    out = ROOT / "governance" / "section10_derivation_inventory.py"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {len(rows)} records to {out}")
    print("dispositions:", dict(Counter(r[4] for r in rows)))


if __name__ == "__main__":
    main()
