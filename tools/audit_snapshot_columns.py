#!/usr/bin/env python3
"""Per-column drop-safety audit for the snapshots wide tables (CORRECTNESS-CLOSEOUT #5(C)).

PURPOSE
-------
Produce a *definitive, enumerated* per-column ledger answering ONE question for
every column of ``snapshots`` and ``snapshots_1m_normalized``:

    Is this column safe to cull? (zero live writer AND zero reader AND not a
    training feature / active label / infra column AND not wired-pending-data)

This exists because "not a training feature" != "safe to delete" and even
"100% NULL" != "dead" (the sentiment columns are wired-pending-credentials).
A column is approved for cull ONLY when the trace proves no producer and no
consumer. The verdict is conservative: anything uncertain is KEEP / REVIEW,
never CULL.

METHODOLOGY (AST + introspection, never line-grep)
--------------------------------------------------
Writer set (producer):
  * ``SnapshotRow.__annotations__`` (AST-extracted from db.py) — the live
    snapshot-insert path drops any kwarg not in these annotations
    (server.py: "_dropped_snapshot_fields"), so this is authoritative for the
    insert path including the dynamic movement-head / fusion-policy kwargs.
  * ``horizon_outcomes.OUTCOME_BAR_SPECS`` + ``OUTCOME_MOVEMENT_V1_SPECS`` —
    the outcome/label columns ``fill_outcomes`` writes (active horizons only).

Protected roles (never cullable):
  * Feature cone — AST-extracted list literals from ml_train.py
    (DOLLAR/WALL/SCALE/TIME/CATEGORICALS) + lstm_data.py (FEATURES_5M/1M).
  * Active labels/outcomes — from the horizon specs above.
  * Infra — id / ticker / ts / timeframe / clock / spot / provenance columns.

Consumer set (reader):
  * AST-walk every non-excluded repo .py; for each column, record files where
    the column name appears as a string constant (word-boundary, to catch SQL
    SELECT lists) or as an attribute / dict-key. Producer + feature-definition
    files are recorded separately and do NOT count as consumers.

Legacy labels: 3c / 8c / 13c label-family columns (not in ML_HORIZON_SLUGS).

VERDICT
-------
  KEEP                     protected role (feature / active label / infra)
  KEEP_LIVE                has writer AND >=1 production consumer
  WIRED_PENDING_DATA       has writer AND ~100% NULL (sentiment class) — NOT cullable
  WRITTEN_NO_CONSUMER      has writer, no production consumer -> REVIEW (persisted for tooling/training)
  LEGACY_LABEL             3c/8c/13c label family -> REVIEW (confirm zero tooling consumer)
  REVIEW_POPULATED_ORPHAN  no prod writer/consumer but has data or tooling ref -> trace normalizer/tooling
  CULL_CANDIDATE           all-NULL AND zero writer AND zero consumer in ANY bucket AND not protected
  REVIEW                   production consumer ref but no traced writer

Usage:
  python tools/audit_snapshot_columns.py                 # write ledger + print summary
  python tools/audit_snapshot_columns.py --stdout        # print JSON only
  python tools/audit_snapshot_columns.py --db PATH       # override db path
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "ed_console.db"
LEDGER_PATH = ROOT / "governance" / "artifacts" / "snapshot_column_cull_ledger.json"
TABLES = ("snapshots", "snapshots_1m_normalized")

# Files that DEFINE / WRITE columns — references here are producer/schema, not consumers.
PRODUCER_DEFINITION_FILES = frozenset({
    "db.py", "snapshot_normalizer.py", "horizon_outcomes.py",
    "ml_train.py", "lstm_data.py", "normalized_training_sync.py",
})

# Never parsed (vendored / build / caches).
SCAN_SKIP_TREE_PARTS = frozenset({
    ".git", ".venv", "venv", "__pycache__", "node_modules", ".claude", "build",
    "dist", ".pytest_cache", ".mypy_cache", ".ruff_cache",
})
# Referenced here = a NON-production consumer (backfill/eval/test tooling). Recorded
# separately so "no production consumer" never over-claims "no consumer anywhere".
NON_PRODUCTION_TREE_PARTS = frozenset({
    "tests", "tools", "research", "arch_competition", "legacy", "models",
})

INFRA_COLS = frozenset({
    "snapshot_id", "id", "ticker", "timeframe", "ts_utc", "ts_et", "ts_iso",
    "et_hour", "et_minute", "spot", "created_at", "updated_at",
    "outcome_filled", "horizon_outcome_schema_version", "anchor_contract_version",
    "label_config_version", "feature_schema_version", "missingness_contract_version",
    "preprocessing_version", "snapshot_date", "ts_minute_utc",
})

LEGACY_HORIZONS = ("3c", "8c", "13c")
LEGACY_LABEL_RE = re.compile(r"_(3c|8c|13c)(_|$)|(^|_)(outcome|pred|fused|valid_dir|threshold_move)_.*(3c|8c|13c)")


# ──────────────────────────── DB facts ────────────────────────────
def db_columns_with_nulls(db_path: Path, table: str) -> tuple[int, dict[str, int]]:
    con = sqlite3.connect(f"file:{db_path}?mode=ro&immutable=1", uri=True)
    try:
        cur = con.cursor()
        cols = [r[1] for r in cur.execute(f'PRAGMA table_info("{table}")').fetchall()]
        if not cols:
            return 0, {}
        total = cur.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        sel = ", ".join(f'SUM(CASE WHEN "{c}" IS NULL THEN 1 ELSE 0 END)' for c in cols)
        row = cur.execute(f'SELECT {sel} FROM "{table}"').fetchone()
        return total, dict(zip(cols, row))
    finally:
        con.close()


# ──────────────────────── AST extraction ──────────────────────────
def _list_literal_names(tree: ast.AST, wanted: set[str]) -> set[str]:
    """Return union of str elements of top-level list-literal assignments whose
    target name is in `wanted`."""
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, (ast.List, ast.Tuple)):
            names = {t.id for t in node.targets if isinstance(t, ast.Name)}
            if names & wanted:
                for el in node.value.elts:
                    if isinstance(el, ast.Constant) and isinstance(el.value, str):
                        out.add(el.value)
    return out


def snapshotrow_annotations(db_text: str) -> set[str]:
    tree = ast.parse(db_text, filename="db.py")
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "SnapshotRow":
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    out.add(stmt.target.id)
    return out


def feature_cone() -> set[str]:
    cone: set[str] = set()
    mt = (ROOT / "ml_train.py").read_text(encoding="utf-8")
    cone |= _list_literal_names(
        ast.parse(mt, filename="ml_train.py"),
        {"DOLLAR_COLS", "WALL_DISTANCE_COLS", "SCALE_INVARIANT_COLS", "TIME_COLS", "CATEGORICALS"},
    )
    ld = (ROOT / "lstm_data.py").read_text(encoding="utf-8")
    cone |= _list_literal_names(
        ast.parse(ld, filename="lstm_data.py"),
        {"FEATURES_5M", "FEATURES_1M"},
    )
    return cone


# ──────────────────── label / outcome writer sets ─────────────────
def active_outcome_columns() -> set[str]:
    sys.path.insert(0, str(ROOT))
    from horizon_outcomes import OUTCOME_BAR_SPECS, OUTCOME_MOVEMENT_V1_SPECS
    out: set[str] = set()
    for odir, opts, _ in OUTCOME_BAR_SPECS:
        out.add(odir); out.add(opts)
    for dcol, mcol, vdcol, tmcol, legtcol, _, _slug in OUTCOME_MOVEMENT_V1_SPECS:
        out.update({dcol, mcol, vdcol, tmcol, legtcol})
    return out


# ──────────────────────── consumer scan ───────────────────────────
def _iter_repo_py():
    for p in sorted(ROOT.rglob("*.py")):
        parts = p.relative_to(ROOT).parts
        if any(part in SCAN_SKIP_TREE_PARTS for part in parts):
            continue
        yield p


def consumer_index(all_cols: set[str]) -> dict[str, dict[str, set[str]]]:
    """column -> {production, tooling, producer} sets of repo-relative files that
    reference it (string-const word match, attribute name, or dict-key constant).

    Single pass over every parseable repo .py; each referencing file is bucketed:
      producer   — schema/feature-definition/writer files (PRODUCER_DEFINITION_FILES)
      tooling    — tests/ tools/ legacy/ research/ arch_competition/ models/
      production — everything else (server/signals/calibration/features/...)
    """
    col_res = {c: re.compile(rf"\b{re.escape(c)}\b") for c in all_cols}
    refs: dict[str, dict[str, set[str]]] = {
        c: {"production": set(), "tooling": set(), "producer": set()} for c in all_cols
    }
    for path in _iter_repo_py():
        try:
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text, filename=str(path))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        rel = str(path.relative_to(ROOT)).replace("\\", "/")
        parts = path.relative_to(ROOT).parts
        if rel in PRODUCER_DEFINITION_FILES:
            bucket = "producer"
        elif any(part in NON_PRODUCTION_TREE_PARTS for part in parts):
            bucket = "tooling"
        else:
            bucket = "production"
        str_consts: list[str] = []
        attr_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                str_consts.append(node.value)
            elif isinstance(node, ast.Attribute):
                attr_names.add(node.attr)
        blob = "\n".join(str_consts)
        for c, rx in col_res.items():
            if c in attr_names or rx.search(blob):
                refs[c][bucket].add(rel)
    return refs


# ──────────────────────────── verdict ─────────────────────────────
def classify(col, null_pct, *, feature, active_lbl, infra, writer, prod_consumers, tooling_consumers, legacy):
    if col in feature:
        return "KEEP", "feature_cone"
    if col in active_lbl:
        return "KEEP", "active_label_outcome"
    if col in infra:
        return "KEEP", "infra"
    has_writer = col in writer
    has_prod = bool(prod_consumers)
    has_tool = bool(tooling_consumers)
    all_null = null_pct >= 100.0
    if has_writer and null_pct >= 99.0:
        return "WIRED_PENDING_DATA", "writer present; column ~100% NULL (upstream/credential gap)"
    if has_writer and has_prod:
        return "KEEP_LIVE", "writer + production consumer"
    if has_writer:
        return "WRITTEN_NO_CONSUMER", "writer present, no production consumer (persisted for tooling/training)"
    if legacy:
        return "LEGACY_LABEL", "3c/8c/13c label family (not in ML_HORIZON_SLUGS)"
    # no writer, not protected, not legacy
    if not has_prod and not has_tool and all_null:
        return "CULL_CANDIDATE", "all-NULL AND no writer AND no consumer anywhere AND not protected"
    if not has_prod:
        return "REVIEW_POPULATED_ORPHAN", "no traced production writer/consumer but has data or tooling ref — trace normalizer/tooling before action"
    return "REVIEW", "production consumer reference but no traced writer"


def build_ledger(db_path: Path) -> dict:
    feature = feature_cone()
    active_lbl = active_outcome_columns()
    writer = snapshotrow_annotations((ROOT / "db.py").read_text(encoding="utf-8")) | active_lbl

    all_cols: set[str] = set()
    table_facts: dict[str, dict] = {}
    for t in TABLES:
        total, nulls = db_columns_with_nulls(db_path, t)
        table_facts[t] = {"total": total, "nulls": nulls}
        all_cols |= set(nulls.keys())

    refs = consumer_index(all_cols)

    tables_out = {}
    for t in TABLES:
        total = table_facts[t]["total"]
        nulls = table_facts[t]["nulls"]
        rows = []
        for col in sorted(nulls.keys()):
            null_pct = (nulls[col] / total * 100.0) if total else 0.0
            cref = refs.get(col, {"production": set(), "tooling": set(), "producer": set()})
            prod_consumers = sorted(cref["production"])
            tooling_consumers = sorted(cref["tooling"])
            producer_refs = sorted(cref["producer"])
            legacy = bool(LEGACY_LABEL_RE.search(col))
            verdict, reason = classify(
                col, null_pct, feature=feature, active_lbl=active_lbl, infra=INFRA_COLS,
                writer=writer, prod_consumers=prod_consumers, tooling_consumers=tooling_consumers,
                legacy=legacy,
            )
            rows.append({
                "column": col,
                "null_pct": round(null_pct, 2),
                "writer": col in writer,
                "production_consumer_files": prod_consumers,
                "tooling_consumer_files": tooling_consumers,
                "producer_ref_files": producer_refs,
                "verdict": verdict,
                "reason": reason,
            })
        counts: dict[str, int] = {}
        for r in rows:
            counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
        tables_out[t] = {"total_rows": total, "n_columns": len(rows), "verdict_counts": counts, "columns": rows}

    return {
        "schema_version": 2,
        "db": str(db_path.relative_to(ROOT)) if db_path.is_relative_to(ROOT) else str(db_path),
        "consumer_scope_note": (
            "production_consumer_files = readers outside producer/test/tool/legacy trees. "
            "tooling_consumer_files = tests/tools/legacy/research/arch_competition/models readers "
            "(backfill/eval). CULL_CANDIDATE requires all-NULL AND zero writer AND zero consumer in "
            "ANY bucket. WRITTEN_NO_CONSUMER / REVIEW_* are NOT cull-approved — column-by-column "
            "producer+consumer confirmation (incl. tooling + UI dynamic serialization) required."
        ),
        "feature_cone_size": len(feature),
        "active_label_outcome_size": len(active_lbl),
        "snapshotrow_writer_size": len(writer),
        "tables": tables_out,
    }


def _print_summary(ledger: dict) -> None:
    for t, td in ledger["tables"].items():
        print(f"\n{'='*72}\n{t}  rows={td['total_rows']}  cols={td['n_columns']}")
        for v, n in sorted(td["verdict_counts"].items(), key=lambda x: -x[1]):
            print(f"  {n:4d}  {v}")
        def _bucket(v):
            return [r for r in td["columns"] if r["verdict"] == v]
        cull = _bucket("CULL_CANDIDATE")
        print(f"\n  CULL_CANDIDATE ({len(cull)}) — all-NULL, zero writer, zero consumer anywhere:")
        for r in cull:
            print(f"    {r['null_pct']:6.2f}%NULL  {r['column']}")
        wpd = _bucket("WIRED_PENDING_DATA")
        print(f"\n  WIRED_PENDING_DATA ({len(wpd)}) — writer present, ~100% NULL (NOT cullable):")
        for r in wpd:
            print(f"    {r['column']}")
        orphan = _bucket("REVIEW_POPULATED_ORPHAN")
        print(f"\n  REVIEW_POPULATED_ORPHAN ({len(orphan)}) — has data/tooling ref, no prod writer/consumer:")
        for r in orphan:
            print(f"    {r['null_pct']:6.2f}%NULL  {r['column']}  tooling={len(r['tooling_consumer_files'])}")
        wnc = _bucket("WRITTEN_NO_CONSUMER")
        print(f"\n  WRITTEN_NO_CONSUMER ({len(wnc)}) — REVIEW (writer, no production consumer):")
        for r in wnc:
            print(f"    {r['null_pct']:6.2f}%NULL  {r['column']}  tooling={len(r['tooling_consumer_files'])}")
        leg = _bucket("LEGACY_LABEL")
        print(f"\n  LEGACY_LABEL ({len(leg)}) — REVIEW (3c/8c/13c family):")
        for r in leg:
            print(f"    {r['column']}  prod={len(r['production_consumer_files'])} tooling={len(r['tooling_consumer_files'])}")


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # box/dash glyphs on Windows consoles
    except (AttributeError, ValueError):
        pass
    p = argparse.ArgumentParser(description="Per-column snapshot drop-safety audit (#5(C)).")
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--stdout", action="store_true")
    args = p.parse_args(argv)

    db_path = Path(args.db)
    if not db_path.exists():
        sys.stderr.write(f"db not found: {db_path}\n")
        return 1
    ledger = build_ledger(db_path)
    text = json.dumps(ledger, indent=2) + "\n"
    if args.stdout:
        sys.stdout.write(text)
        return 0
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    LEDGER_PATH.write_text(text, encoding="utf-8")
    sys.stdout.write(f"wrote {LEDGER_PATH.relative_to(ROOT)}\n")
    _print_summary(ledger)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
