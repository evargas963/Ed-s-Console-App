"""Generate governance/section15_derivation_inventory.py — audit + verify + config + contracts."""
from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _section15_files() -> list[str]:
    names = sorted(p.name for p in ROOT.glob("audit_*.py"))
    names += sorted(p.name for p in ROOT.glob("verify_*.py"))
    names += sorted(p.name for p in ROOT.glob("ticker_*.py"))
    names += sorted(p.name for p in ROOT.glob("feature_contract_*.py"))
    names += [
        "inspect_trading_data.py",
        "config.py",
        "setup_readiness.py",
        "scheduler_user_tickers.py",
        "production_universe.py",
        "app/domain/instrument_identity.py",
        "timeframe_config.py",
        "model_contract.py",
        "horizon_outcomes.py",
        "movement_target_threshold.py",
        "institutional_behavior.py",
        "app/domain/canonical_distances.py",
        "tier3_design.py",
    ]
    return sorted(dict.fromkeys(names))


SECTION15_FILES = _section15_files()

OVERRIDES: dict[tuple[str, str], tuple[str, str, str]] = {
    ("config.py", "build_config"): ("env / paths", "NONE", "Loads app config from env/files."),
    ("model_contract.py", "validate_model_contract"): (
        "model contract",
        "NONE",
        "Schema validation for model I/O contract.",
    ),
    ("horizon_outcomes.py", "HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1"): (
        "outcome schema",
        "NONE",
        "Static outcome bar-anchor schema constant module-level (if fn).",
    ),
    ("feature_contract_validation.py", "validate_feature_contract"): (
        "feature contract",
        "NONE",
        "Feature contract validation against schema.",
    ),
    ("app/domain/canonical_distances.py", "canonical_distance_buckets_v1"): (
        "distance buckets",
        "NONE",
        "Static canonical distance bucket definitions.",
    ),
    ("verify_snapshot_pipeline.py", "verify_snapshot_pipeline"): (
        "snapshots.*",
        "KEEP_DERIVED",
        "End-to-end snapshot pipeline verification on stored rows.",
    ),
    ("audit_model_readiness.py", "audit_model_readiness"): (
        "artifacts / snapshots",
        "NONE",
        "Model readiness audit; no live Schwab ingest.",
    ),
}

_DATA_KW = ("snapshot", "feature", "model", "artifact", "row", "sql")


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

    if file == "config.py" or file == "app/domain/instrument_identity.py" or file == "scheduler_user_tickers.py":
        return ("—", "NONE", "Configuration/identity helper; no market-field derivation.")

    if "contract" in file or file in ("horizon_outcomes.py", "movement_target_threshold.py", "tier3_design.py"):
        if any(k in name_l for k in ("validate", "schema", "spec", "constant", "bucket", "threshold")):
            return ("contract schema", "NONE", "Static contract/schema definition or validation.")
        if any(k in body_l for k in _DATA_KW):
            return (
                "snapshots.* / contract",
                "NONE",
                "Contract module referencing snapshot fields without live ingest.",
            )
        return ("contract schema", "NONE", "Contract/design module; no Schwab derivation.")

    if file.startswith("audit_") or file.startswith("verify_"):
        if any(k in body_l for k in _DATA_KW):
            return (
                "snapshots.* / artifacts",
                "KEEP_DERIVED",
                "Audit/verify pass on persisted snapshots or artifacts.",
            )
        return ("—", "NONE", "Audit/verify helper; no live market ingest.")

    if file in ("inspect_trading_data.py", "setup_readiness.py"):
        if any(k in body_l for k in _DATA_KW):
            return (
                "snapshots.*",
                "KEEP_DERIVED",
                "Inspection/readiness on stored trading data.",
            )
        return ("—", "NONE", "Inspection/readiness utility.")

    if file.startswith("ticker_"):
        return ("ticker metadata", "NONE", "Ticker readiness/diagnostics; no Schwab API.")

    if file == "production_universe.py":
        return ("universe config", "NONE", "Production ticker universe list.")

    if file == "institutional_behavior.py" or file == "app/domain/canonical_distances.py":
        return ("design constants", "NONE", "Institutional behavior / distance design definitions.")

    return ("—", "NONE", "No Schwab market-field derivation in function body.")


def main() -> None:
    rows: list[tuple[str, int, str, str, str, str]] = []
    for rel in SECTION15_FILES:
        path = ROOT / rel
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        for qual, fn in _walk(tree, text):
            body = _fn_body(text, fn)
            leaf, disp, just = classify(rel, qual, fn, body)
            rows.append((rel, fn.lineno, qual, leaf, disp, just))

    header = '''"""
Section 15 Schwab-leaf derivation audit inventory (audit + verify + config + contracts).

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


SECTION15_DERIVATION_INVENTORY: tuple[DerivationRecord, ...] = (
'''
    lines = [header]
    for file, line, func, leaf, disp, just in rows:
        j = just.replace('"', '\\"')
        lines.append(
            f'    DerivationRecord("{file}", "{line}", "{func}", "{leaf}", "{disp}", "{j}"),'
        )
    lines.append(")")
    lines.append("")
    lines.append("SECTION15_FILES = frozenset({")
    for f in SECTION15_FILES:
        lines.append(f'    "{f}",')
    lines.append("})")
    lines.append("")

    out = ROOT / "governance" / "section15_derivation_inventory.py"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {len(rows)} records to {out}")
    print("files:", len(SECTION15_FILES))
    print("dispositions:", dict(Counter(r[4] for r in rows)))


if __name__ == "__main__":
    main()
