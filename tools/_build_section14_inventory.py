"""Generate governance/section14_derivation_inventory.py — DB + backfill + repair."""
from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _section14_files() -> list[str]:
    names = sorted(p.name for p in ROOT.glob("db*.py"))
    names += sorted(p.name for p in ROOT.glob("backfill_*.py"))
    names += sorted(p.name for p in ROOT.glob("bar_rehydration_*.py"))
    names += [
        "clean_db.py",
        "eval_metrics_store.py",
        "pin_neutral_outcome_repair_v1.py",
        "distance_option_a_backfill_v1.py",
        "patch_active_artifact_provenance.py",
        "replay_bundle_coverage.py",
        "realized_contract_eval.py",
    ]
    return sorted(dict.fromkeys(names))


SECTION14_FILES = _section14_files()

OVERRIDES: dict[tuple[str, str], tuple[str, str, str]] = {
    ("db.py", "configure_sqlite_connection"): ("SQLite", "NONE", "Connection pragmas; no market-field derivation."),
    ("db.py", "get_db"): ("SQLite", "PASS_THROUGH", "DB accessor singleton."),
    ("db.py", "get_snapshot_sql"): ("SQL templates", "NONE", "Named snapshot SQL template registry."),
    ("db.py", "_apply_bar_based_outcome_updates"): (
        "snapshots.* / bars",
        "KEEP_DERIVED",
        "Updates snapshot outcome columns from bar mutations.",
    ),
    ("db.py", "market_session"): ("clock ET", "NONE", "Session label from ET hour/minute."),
    ("db.py", "build_ts_et"): ("clock ET", "NONE", "ET timestamp string from datetime."),
    ("clean_db.py", "main"): ("—", "NONE", "CLI DB cleanup utility."),
    ("eval_metrics_store.py", "ensure_eval_metrics_schema"): (
        "eval_metrics schema",
        "NONE",
        "Eval metrics table DDL.",
    ),
    ("backfill_snapshot_derived.py", "backfill_snapshot_derived_columns"): (
        "snapshots.*",
        "KEEP_DERIVED",
        "Backfills derived snapshot columns from stored rows.",
    ),
    ("backfill_flow_imbalance.py", "backfill_flow_imbalance"): (
        "snapshots.*",
        "KEEP_DERIVED",
        "Backfills flow imbalance columns on snapshots.",
    ),
    ("bar_rehydration_issue19_v1.py", "rehydrate_bars_for_issue19"): (
        "snapshots.* / bars",
        "KEEP_DERIVED",
        "Rehydrates bar linkage for Issue 19 snapshots.",
    ),
    ("realized_contract_eval.py", "evaluate_realized_contract_trades_for_rows"): (
        "option chain replay",
        "KEEP_DERIVED",
        "Contract PnL eval from replay rows; no live Schwab ingest.",
    ),
}

_DB_UTIL = ("connect", "pragma", "migrate", "schema", "ensure_", "configure_")
_DATA_KW = (
    "snapshot",
    "outcome",
    "bar",
    "backfill",
    "repair",
    "rehydrat",
    "flow",
    "imbalance",
    "contract",
    "chain",
    "replay",
)
_MARKET_KW = ("bid", "ask", "quote", "datetime", "open", "high", "low", "close", "volume")


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

    if file == "clean_db.py":
        return ("—", "NONE", "DB cleanup utility.")

    if name_l.startswith("sql_") or name_l == "get_snapshot_sql":
        return ("SQL templates", "NONE", "SQL string builder; no runtime market derivation.")

    if any(name_l.startswith(p) for p in _DB_UTIL) or name_l in ("now_utc", "now_et", "utc_ts", "_resolve_console_db_path"):
        return ("SQLite / paths", "NONE", "DB infrastructure helper.")

    if "similarity_" in name_l and "viable" in name_l or name_l == "similarity_labeled_counts":
        return ("labeled counts", "NONE", "Similarity tier viability counters.")

    if file.startswith("backfill_") or "backfill" in name_l or file.endswith("_backfill_v1.py"):
        return (
            "snapshots.*",
            "KEEP_DERIVED",
            "Backfill/repair pass on persisted snapshot or bar rows.",
        )

    if "repair" in file or "repair" in name_l or "rehydrat" in name_l:
        return (
            "snapshots.* / outcomes",
            "KEEP_DERIVED",
            "Repair/rehydration on stored DB rows.",
        )

    if file == "db.py" and qual.startswith("EdDB."):
        if any(k in body_l for k in _MARKET_KW) and any(k in body_l for k in _DATA_KW):
            return (
                "snapshots.*",
                "PASS_THROUGH",
                "EdDB method reads/writes snapshot rows.",
            )
        if "insert" in name_l or "update" in name_l or "fetch" in name_l or "load" in name_l:
            return (
                "snapshots.*",
                "PASS_THROUGH",
                "EdDB persistence accessor.",
            )
        return ("SQLite", "NONE", "EdDB helper without market-field derivation.")

    if any(k in body_l for k in _DATA_KW):
        if any(k in body_l for k in _MARKET_KW):
            return (
                "snapshots.*",
                "KEEP_DERIVED",
                "Derives or updates stored market fields from DB rows.",
            )
        return (
            "snapshots.*",
            "PASS_THROUGH",
            "Reads or writes persisted snapshot/outcome rows.",
        )

    if "eval_metrics" in file or "coverage" in file or "provenance" in file:
        return ("audit counters", "NONE", "Metrics/coverage audit; no live Schwab ingest.")

    return ("—", "NONE", "No Schwab market-field derivation in function body.")


def main() -> None:
    rows: list[tuple[str, int, str, str, str, str]] = []
    for rel in SECTION14_FILES:
        path = ROOT / rel
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        for qual, fn in _walk(tree, text):
            body = _fn_body(text, fn)
            leaf, disp, just = classify(rel, qual, fn, body)
            rows.append((rel, fn.lineno, qual, leaf, disp, just))

    header = '''"""
Section 14 Schwab-leaf derivation audit inventory (DB + backfill + repair).

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


SECTION14_DERIVATION_INVENTORY: tuple[DerivationRecord, ...] = (
'''
    lines = [header]
    for file, line, func, leaf, disp, just in rows:
        j = just.replace('"', '\\"')
        lines.append(
            f'    DerivationRecord("{file}", "{line}", "{func}", "{leaf}", "{disp}", "{j}"),'
        )
    lines.append(")")
    lines.append("")
    lines.append("SECTION14_FILES = frozenset({")
    for f in SECTION14_FILES:
        lines.append(f'    "{f}",')
    lines.append("})")
    lines.append("")

    out = ROOT / "governance" / "section14_derivation_inventory.py"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {len(rows)} records to {out}")
    print("files:", len(SECTION14_FILES))
    print("dispositions:", dict(Counter(r[4] for r in rows)))


if __name__ == "__main__":
    main()
