#!/usr/bin/env python3
"""Pass 2 — Persistence-layer consumer audit.

AST-walks persistence files (db.py, calibration/writer.py) to identify every
writer (function containing an INSERT INTO statement). For each writer, scans
the rest of the repo for production callers and read consumers (SELECT/FROM
references to written tables), and emits a deterministic JSON map.

The map is the source of truth for:
  - Pass 1b consumer mechanical lock (loads writer_fn -> read_consumers[])
  - Pass 2b CI staleness gate
  - Pass 5a model_accuracy hook recommendation (writer_candidates section)

Usage:
  python tools/audit_persistence_consumers.py                # write + diff
  python tools/audit_persistence_consumers.py --check        # exit 1 if stale
  python tools/audit_persistence_consumers.py --stdout       # print JSON

Determinism:
  Re-running against unchanged sources produces byte-identical JSON. The
  generated_at field is intentionally a stable string when --stable-time is
  passed; CI and the golden test use --stable-time.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parent.parent
MAP_PATH = ROOT / "governance" / "artifacts" / "persistence_consumer_map.json"

PERSISTENCE_FILES = (
    "db.py",
    "calibration/writer.py",
)

EXCLUDED_TREE_PARTS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        "node_modules",
        ".claude",
        "build",
        "dist",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "tests",
        "tools",
        "research",
        "arch_competition",
        "legacy",
    }
)

WRITER_CANDIDATE_NAME_RE = re.compile(
    r"^(?:log_|record_|track_|append_|insert_|update_|store_|persist_|"
    r"write_|save_|commit_|put_|register_|emit_|compute_|start_|end_)\w+$"
)

INSERT_TABLE_RE = re.compile(
    r"INSERT\s+(?:OR\s+(?:REPLACE|IGNORE|ABORT|FAIL|ROLLBACK)\s+)?INTO\s+([A-Za-z_][A-Za-z0-9_]*)",
    re.IGNORECASE,
)
FROM_TABLE_RE_TMPL = r"\bFROM\s+{tbl}\b"
JOIN_TABLE_RE_TMPL = r"\bJOIN\s+{tbl}\b"
UPDATE_TABLE_RE_TMPL = r"\bUPDATE\s+{tbl}\b"  # UPDATE x SET also reads

CALL_RE_TMPL = r"\b{fn}\s*\("


def _iter_repo_python_files(repo_root: Path) -> Iterable[Path]:
    for path in sorted(repo_root.rglob("*.py")):
        rel_parts = path.relative_to(repo_root).parts
        if any(part in EXCLUDED_TREE_PARTS for part in rel_parts):
            continue
        yield path


def _extract_string_constants(node: ast.AST) -> list[str]:
    out: list[str] = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            out.append(sub.value)
        elif isinstance(sub, ast.JoinedStr):
            for v in sub.values:
                if isinstance(v, ast.Constant) and isinstance(v.value, str):
                    out.append(v.value)
    return out


def _qualname_for(fn_node: ast.AST, class_stack: tuple[str, ...]) -> str:
    name = getattr(fn_node, "name", "<anon>")
    if class_stack:
        return ".".join(class_stack) + "." + name
    return name


def _walk_functions(tree: ast.AST):
    """Yield (FunctionDef, qualname, line) for module-level fns and class methods only.

    Nested function defs (closures inside another function body) are skipped —
    their INSERT statements belong to the enclosing public function.
    """
    def _walk(node: ast.AST, stack: tuple[str, ...], inside_fn: bool) -> Iterable[tuple[ast.AST, str, int]]:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                yield from _walk(child, stack + (child.name,), inside_fn=False)
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not inside_fn:
                    yield child, _qualname_for(child, stack), child.lineno
                # Recurse into body but mark "inside_fn" so nested defs are silent.
                yield from _walk(child, stack + (child.name,), inside_fn=True)
            else:
                yield from _walk(child, stack, inside_fn=inside_fn)

    yield from _walk(tree, (), inside_fn=False)


def _scan_persistence_file(rel: str) -> tuple[list[dict], list[dict]]:
    """Return (writers, writer_candidates) for one persistence file."""
    path = ROOT / rel
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=rel)

    writers: list[dict] = []
    candidates: list[dict] = []

    for fn_node, qualname, lineno in _walk_functions(tree):
        strings = _extract_string_constants(fn_node)
        tables_written: list[str] = []
        for s in strings:
            for m in INSERT_TABLE_RE.finditer(s):
                tbl = m.group(1)
                if tbl not in tables_written:
                    tables_written.append(tbl)

        if tables_written:
            writers.append(
                {
                    "writer_fn": qualname,
                    "file": rel,
                    "line": lineno,
                    "tables_written": sorted(tables_written),
                }
            )
        else:
            # writer-shaped name but no INSERT — candidate for future writer wiring
            short_name = qualname.rsplit(".", 1)[-1]
            if WRITER_CANDIDATE_NAME_RE.match(short_name):
                candidates.append(
                    {
                        "candidate_fn": qualname,
                        "file": rel,
                        "line": lineno,
                    }
                )

    return writers, candidates


def _has_non_def_call(text: str, pat: re.Pattern[str], name: str) -> bool:
    """True if any match of `pat` in `text` is NOT a function definition line.

    A call site looks like `self.log_level_cross(event)` or `EdDB.log_level_cross(...)`.
    A def line looks like `def log_level_cross(self, ...)`. Both contain
    `log_level_cross(`, so a naive regex would count the def as a caller.
    """
    def_re = re.compile(rf"\bdef\s+{re.escape(name)}\s*\(")
    for line in text.splitlines():
        if not pat.search(line):
            continue
        if def_re.search(line):
            continue
        return True
    return False


def _scan_repo_for_callers(fn_short_names: set[str]) -> dict[str, list[str]]:
    """For each short fn name, return sorted list of repo-relative files that call it.

    Persistence files (db.py, calibration/writer.py) ARE scanned — the helper
    pattern (`detect_and_log_level_crosses -> log_level_cross`) is a real
    indirection, not noise. Lines containing `def <fn_name>(` are filtered
    out so the writer's own definition doesn't count as a self-call.
    """
    patterns = {name: re.compile(CALL_RE_TMPL.format(fn=re.escape(name))) for name in fn_short_names}
    callers: dict[str, set[str]] = {name: set() for name in fn_short_names}

    for path in _iter_repo_python_files(ROOT):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        rel = str(path.relative_to(ROOT)).replace("\\", "/")
        for name, pat in patterns.items():
            if _has_non_def_call(text, pat, name):
                callers[name].add(rel)

    return {name: sorted(found) for name, found in callers.items()}


def _scan_repo_for_table_consumers(tables: set[str]) -> dict[str, list[str]]:
    """For each table, return sorted list of repo-relative files that SELECT/JOIN/UPDATE it.

    Persistence files ARE scanned — read helpers inside db.py
    (`get_recent_crosses`, `count_level_tests`) are legitimate consumers.
    """
    patterns = {
        tbl: [
            re.compile(FROM_TABLE_RE_TMPL.format(tbl=re.escape(tbl)), re.IGNORECASE),
            re.compile(JOIN_TABLE_RE_TMPL.format(tbl=re.escape(tbl)), re.IGNORECASE),
            re.compile(UPDATE_TABLE_RE_TMPL.format(tbl=re.escape(tbl)), re.IGNORECASE),
        ]
        for tbl in tables
    }
    consumers: dict[str, set[str]] = {tbl: set() for tbl in tables}

    for path in _iter_repo_python_files(ROOT):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        rel = str(path.relative_to(ROOT)).replace("\\", "/")
        for tbl, pats in patterns.items():
            if any(p.search(text) for p in pats):
                consumers[tbl].add(rel)

    return {tbl: sorted(found) for tbl, found in consumers.items()}


def _status_for(production_callers: list[str], read_consumers_by_table: dict[str, list[str]], tables: list[str]) -> str:
    has_caller = bool(production_callers)
    has_reader = any(read_consumers_by_table.get(t) for t in tables)
    if has_caller and has_reader:
        return "live"
    return "dormant"


def build_map(stable_time: bool = False) -> dict:
    all_writers: list[dict] = []
    all_candidates: list[dict] = []

    for rel in PERSISTENCE_FILES:
        writers, candidates = _scan_persistence_file(rel)
        all_writers.extend(writers)
        all_candidates.extend(candidates)

    short_writer_names = {w["writer_fn"].rsplit(".", 1)[-1] for w in all_writers}
    short_candidate_names = {c["candidate_fn"].rsplit(".", 1)[-1] for c in all_candidates}
    all_short_names = short_writer_names | short_candidate_names

    callers_by_name = _scan_repo_for_callers(all_short_names)

    all_tables = sorted({t for w in all_writers for t in w["tables_written"]})
    consumers_by_table = _scan_repo_for_table_consumers(set(all_tables))

    writers_out: list[dict] = []
    for w in all_writers:
        short = w["writer_fn"].rsplit(".", 1)[-1]
        prod_callers = callers_by_name.get(short, [])
        read_consumers = {t: consumers_by_table.get(t, []) for t in w["tables_written"]}
        writers_out.append(
            {
                "writer_fn": w["writer_fn"],
                "file": w["file"],
                "line": w["line"],
                "tables_written": w["tables_written"],
                "production_callers": prod_callers,
                "read_consumers": read_consumers,
                "status": _status_for(prod_callers, read_consumers, w["tables_written"]),
            }
        )

    candidates_out: list[dict] = []
    for c in all_candidates:
        short = c["candidate_fn"].rsplit(".", 1)[-1]
        prod_callers = callers_by_name.get(short, [])
        recommended_hook_file = prod_callers[0] if prod_callers else None
        candidates_out.append(
            {
                "candidate_fn": c["candidate_fn"],
                "file": c["file"],
                "line": c["line"],
                "production_callers": prod_callers,
                "recommended_hook_file": recommended_hook_file,
            }
        )

    writers_out.sort(key=lambda r: (r["file"], r["line"], r["writer_fn"]))
    candidates_out.sort(key=lambda r: (r["file"], r["line"], r["candidate_fn"]))

    return {
        "schema_version": 1,
        "generated_at": "stable" if stable_time else _wallclock_iso(),
        "persistence_files": list(PERSISTENCE_FILES),
        "writers": writers_out,
        "writer_candidates": candidates_out,
        "summary": {
            "writer_count": len(writers_out),
            "live_count": sum(1 for w in writers_out if w["status"] == "live"),
            "dormant_count": sum(1 for w in writers_out if w["status"] == "dormant"),
            "table_count": len(all_tables),
        },
    }


def _wallclock_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _serialize(map_obj: dict) -> str:
    return json.dumps(map_obj, indent=2, sort_keys=False) + "\n"


def _strip_generated_at(text: str) -> str:
    obj = json.loads(text)
    obj["generated_at"] = "stable"
    return _serialize(obj)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Persistence-layer consumer audit (Pass 2).")
    p.add_argument("--check", action="store_true", help="Exit 1 if on-disk map differs from regenerated map.")
    p.add_argument("--stdout", action="store_true", help="Print JSON to stdout instead of writing file.")
    p.add_argument("--stable-time", action="store_true", help="Use 'stable' as generated_at (for CI/tests).")
    args = p.parse_args(argv)

    new_map = build_map(stable_time=args.stable_time)
    new_text = _serialize(new_map)

    if args.stdout:
        sys.stdout.write(new_text)
        return 0

    if args.check:
        if not MAP_PATH.exists():
            sys.stderr.write(f"persistence_consumer_map.json missing at {MAP_PATH}\n")
            return 1
        on_disk = MAP_PATH.read_text(encoding="utf-8")
        # Compare with generated_at stripped on both sides
        if _strip_generated_at(on_disk) != _strip_generated_at(new_text):
            sys.stderr.write(
                "persistence_consumer_map.json is stale vs persistence sources.\n"
                "Run: python tools/audit_persistence_consumers.py\n"
            )
            return 1
        return 0

    MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
    MAP_PATH.write_text(new_text, encoding="utf-8")
    sys.stdout.write(f"wrote {MAP_PATH.relative_to(ROOT)} ({new_map['summary']})\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
