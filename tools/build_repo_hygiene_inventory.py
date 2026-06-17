#!/usr/bin/env python3
"""Build repo hygiene inventory + backlog (Phase 3I — conservative classification only)."""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
OUT_INVENTORY = REPO / "governance" / "artifacts" / "REPO_HYGIENE_INVENTORY.json"
OUT_BACKLOG_JSON = REPO / "governance" / "artifacts" / "REPO_HYGIENE_BACKLOG.json"
OUT_BACKLOG_MD = REPO / "governance" / "docs" / "REPO_HYGIENE_BACKLOG.md"

SCHEMA_VERSION = 1

EXCLUDE_DIR_PARTS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        "node_modules",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".cursor",
        "build",
        "dist",
    }
)

EXCLUDE_PATH_PREFIXES = (
    "models/active",
    "models/active_",
    "backups/",
    "governance/archive/",
)

GENERATED_ARTIFACT_PREFIX = "governance/artifacts/"
HISTORICAL_PREFIX = "governance/archive/"

TRUTH_SOURCE_ARTIFACTS = frozenset(
    {
        "SEVERITY_1_CONTROL_VALIDATION_REGISTER.json",
        "EVIDENCE_INDEX.json",
        "CURRENT_LIMITATIONS.json",
        "REMOTE_ENFORCEMENT_EVIDENCE.json",
        "GOVERNANCE_ARTIFACT_MANIFEST.json",
        "DECISION_PATH_REGISTRY.json",
        "UNIVERSAL_BYPASS_REGISTER.json",
        "PERSISTENCE_CONSUMER_MAP.json",
        "REPO_HYGIENE_INVENTORY.json",
        "REPO_HYGIENE_BACKLOG.json",
        "CHECK_STACK_INVENTORY.json",
    }
)

BUILDER_COMMAND_HINTS: dict[str, str] = {
    "EVIDENCE_INDEX.json": "python tools/_build_evidence_index.py",
    "CURRENT_LIMITATIONS.json": "python tools/_build_current_limitations.py",
    "PERSISTENCE_CONSUMER_MAP.json": "python tools/audit_persistence_consumers.py",
    "PRECOMMIT_PERFORMANCE_AUDIT.json": "python tools/audit_precommit_performance.py",
    "FIX_EVERYTHING_WE_TOUCH_PROFILE.json": "python tools/check_fix_everything_we_touch.py --profile",
    "REPO_HYGIENE_INVENTORY.json": "python tools/build_repo_hygiene_inventory.py",
    "REPO_HYGIENE_BACKLOG.json": "python tools/build_repo_hygiene_inventory.py",
    "CHECK_STACK_INVENTORY.json": "python tools/build_check_stack_inventory.py",
}


def _rel(root: Path, p: Path) -> str:
    return p.resolve().relative_to(root.resolve()).as_posix()


def _excluded(rel: str) -> bool:
    parts = rel.split("/")
    if any(p in EXCLUDE_DIR_PARTS for p in parts):
        return True
    return any(rel.startswith(pref) for pref in EXCLUDE_PATH_PREFIXES)


def _iter_files(root: Path) -> list[str]:
    out: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dp = Path(dirpath)
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIR_PARTS]
        for fn in sorted(filenames):
            rel = _rel(root, dp / fn)
            if not _excluded(rel):
                out.append(rel)
    return out


def _collect_python_imports(root: Path, rel_paths: list[str]) -> dict[str, set[str]]:
    imports: dict[str, set[str]] = {}
    for rel in rel_paths:
        if not rel.endswith(".py"):
            continue
        path = root / rel
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError):
            imports[rel] = set()
            continue
        mods: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    mods.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods.add(node.module.split(".")[0])
        imports[rel] = mods
    return imports


def _collect_text_references(root: Path, rel_paths: list[str]) -> set[str]:
    refs: set[str] = set()
    exts = {".py", ".md", ".yaml", ".yml", ".json", ".toml", ".html", ".js", ".sh", ".ps1"}
    pat = re.compile(r"[\w./\\-]+\.(?:py|md|json|yaml|yml|html|js|sh|ps1)")
    for rel in rel_paths:
        if Path(rel).suffix.lower() not in exts:
            continue
        try:
            text = (root / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in pat.findall(text):
            refs.add(m.replace("\\", "/"))
            refs.add(Path(m.replace("\\", "/")).name)
    return refs


def _build_importer_index(py_imports: dict[str, set[str]], rel_paths: list[str]) -> dict[str, set[str]]:
    stem_to_file: dict[str, str] = {}
    for rel in rel_paths:
        if rel.endswith(".py"):
            stem_to_file[Path(rel).stem] = rel
    imported_by: dict[str, set[str]] = defaultdict(set)
    for importer, mods in py_imports.items():
        for mod in mods:
            if mod in stem_to_file:
                imported_by[stem_to_file[mod]].add(importer)
    return imported_by


def _duplicate_checker_paths(rel_paths: list[str]) -> set[str]:
    basenames: Counter[str] = Counter()
    dup_paths: set[str] = set()
    for rel in rel_paths:
        if rel.startswith("tools/") and rel.endswith(".py"):
            bn = Path(rel).name
            basenames[bn] += 1
    for rel in rel_paths:
        if rel.startswith("tools/") and rel.endswith(".py"):
            if basenames[Path(rel).name] > 1:
                dup_paths.add(rel)
    return dup_paths


def _classify_file(
    rel: str,
    *,
    imported_by: dict[str, set[str]],
    text_refs: set[str],
    dup_checker_paths: set[str],
) -> tuple[str, list[str]]:
    signals: list[str] = []
    name = Path(rel).name

    if rel.startswith("tests/"):
        if rel.endswith(".py") and name.startswith("test_"):
            module_guess = name[5:]
            if rel not in imported_by and module_guess not in "".join(text_refs):
                signals.append("test_module_weakly_linked")
                return "orphan_candidate", signals
        return "active_test", signals

    if rel.startswith(HISTORICAL_PREFIX):
        return "historical_artifact", signals

    if rel.startswith(GENERATED_ARTIFACT_PREFIX):
        if name in TRUTH_SOURCE_ARTIFACTS:
            signals.append("truth_source_evidence")
        elif name.endswith(".json") and name not in BUILDER_COMMAND_HINTS:
            signals.append("generated_without_pinned_builder")
        return "generated_artifact", signals

    if rel.startswith("governance/"):
        if "DEPRECATED" in name.upper():
            return "deprecated_candidate", signals
        return "active_governance", signals

    if rel.endswith(".py"):
        importers = imported_by.get(rel) or set()
        ref_hit = rel in text_refs or name in text_refs
        if rel in dup_checker_paths:
            signals.append("duplicate_checker_basename")
            return "duplicate_candidate", signals
        if "deprecated" in name.lower() or "/legacy/" in rel:
            signals.append("deprecated_name")
            return "deprecated_candidate", signals
        if not importers and not ref_hit:
            if rel.startswith("tools/") or rel.count("/") == 0:
                signals.append("zero_python_importers")
                return "dead_code_candidate", signals
            return "orphan_candidate", signals
        return "active_runtime", signals

    if rel.endswith((".md", ".html", ".js", ".css")):
        if rel in text_refs or name in text_refs:
            return "active_governance" if rel.startswith("governance/") else "active_runtime", signals
        if rel.startswith(("static/", "templates/")):
            return "active_runtime", signals
        signals.append("weak_doc_reference")
        return "manual_review_required", signals

    if rel.endswith((".json", ".csv", ".xlsx")) and not rel.startswith(GENERATED_ARTIFACT_PREFIX):
        return "manual_review_required", signals

    return "manual_review_required", signals


def build_inventory(root: Path | None = None) -> dict[str, Any]:
    root = (root or REPO).resolve()
    rel_paths = _iter_files(root)
    py_imports = _collect_python_imports(root, rel_paths)
    imported_by = _build_importer_index(py_imports, rel_paths)
    text_refs = _collect_text_references(root, rel_paths)
    dup_paths = _duplicate_checker_paths(rel_paths)

    entries: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()

    for rel in sorted(rel_paths):
        category, signals = _classify_file(
            rel,
            imported_by=imported_by,
            text_refs=text_refs,
            dup_checker_paths=dup_paths,
        )
        counts[category] += 1
        regen = None
        if rel.startswith(GENERATED_ARTIFACT_PREFIX) and Path(rel).name in BUILDER_COMMAND_HINTS:
            regen = BUILDER_COMMAND_HINTS[Path(rel).name]
        entries.append(
            {
                "path": rel,
                "category": category,
                "signals": signals,
                "importer_count": len(imported_by.get(rel, ())),
                "regenerate_command": regen,
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "phase": "3I-RepoHygiene",
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "policy": "governance/docs/REPO_HYGIENE_POLICY.md",
        "summary": {
            "file_count": len(entries),
            "by_category": dict(sorted(counts.items())),
            "safe_to_remove_count": counts.get("safe_to_remove", 0),
            "manual_review_count": counts.get("manual_review_required", 0),
            "candidate_count": sum(
                counts.get(c, 0)
                for c in (
                    "orphan_candidate",
                    "dead_code_candidate",
                    "duplicate_candidate",
                    "deprecated_candidate",
                )
            ),
        },
        "entries": entries,
    }


def build_backlog(inventory: dict[str, Any]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    candidate_categories = {
        "orphan_candidate",
        "dead_code_candidate",
        "duplicate_candidate",
        "deprecated_candidate",
    }
    for row in inventory.get("entries") or []:
        cat = str(row.get("category") or "")
        if cat not in candidate_categories:
            continue
        path = str(row.get("path") or "")
        risk = "high" if path.startswith(("tools/", "governance/artifacts/")) else "medium"
        items.append(
            {
                "candidate": path,
                "category": cat,
                "reason": "; ".join(row.get("signals") or []) or cat,
                "risk": risk,
                "owner_action": "manual_review_required",
                "safe_next_step": "Read cone end-to-end; classify keep/remove/defer in backlog",
                "tests_needed": "paired pytest or checker proof before removal",
                "status": "open",
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "phase": "3I-RepoHygiene",
        "generated_at_utc": inventory.get("generated_at_utc"),
        "actionable_only": True,
        "actionable_categories": sorted(candidate_categories),
        "item_count": len(items),
        "open_count": sum(1 for i in items if i.get("status") == "open"),
        "items": items,
    }


def _render_backlog_md(backlog: dict[str, Any]) -> str:
    lines = [
        "# Repo hygiene backlog",
        "",
        "**Scope:** Phase 3I progressive cleanup — candidates only; no mass deletion.",
        "",
        f"Generated: `{backlog.get('generated_at_utc')}` | Open items: **{backlog.get('open_count')}**",
        "",
        "Regenerate: `python tools/build_repo_hygiene_inventory.py`",
        "",
        "| Candidate | Category | Risk | Status | Reason |",
        "|-----------|----------|------|--------|--------|",
    ]
    for row in (backlog.get("items") or [])[:200]:
        lines.append(
            f"| `{row.get('candidate')}` | {row.get('category')} | {row.get('risk')} | "
            f"{row.get('status')} | {str(row.get('reason') or '')[:80]} |"
        )
    if len(backlog.get("items") or []) > 200:
        lines.append("")
        lines.append(f"_… and {len(backlog['items']) - 200} more rows in JSON._")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Build repo hygiene inventory + backlog.")
    p.add_argument("--stdout", action="store_true", help="Print inventory JSON to stdout.")
    args = p.parse_args(argv)

    inv = build_inventory()
    backlog = build_backlog(inv)

    if args.stdout:
        print(json.dumps(inv, indent=2))
        return 0

    OUT_INVENTORY.parent.mkdir(parents=True, exist_ok=True)
    OUT_INVENTORY.write_text(json.dumps(inv, indent=2) + "\n", encoding="utf-8")
    OUT_BACKLOG_JSON.write_text(json.dumps(backlog, indent=2) + "\n", encoding="utf-8")
    OUT_BACKLOG_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_BACKLOG_MD.write_text(_render_backlog_md(backlog), encoding="utf-8")
    print(
        f"wrote {OUT_INVENTORY.relative_to(REPO)} "
        f"({inv['summary']['file_count']} files; "
        f"{inv['summary']['candidate_count']} candidates)"
    )
    print(f"wrote {OUT_BACKLOG_JSON.relative_to(REPO)} ({backlog['item_count']} backlog rows)")
    print(f"wrote {OUT_BACKLOG_MD.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
