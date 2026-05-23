"""Phase 3: repo cleanup artifacts (baseline delta, duplicates, py audit, worktrees)."""
from __future__ import annotations

import ast
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "governance/consolidation/phase3"
PHASE0 = ROOT / "governance/consolidation/phase0/baseline_snapshot.json"
DO_NOT_RENAME = ROOT / "governance/consolidation/phase0/do_not_rename_paths.json"

SKIP_DIR_NAMES = frozenset(
    {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", "backups"}
)


def _count_root_py() -> int:
    return len([p for p in ROOT.glob("*.py") if p.is_file()])


def _worktree_bytes() -> int | None:
    wt = ROOT / ".claude" / "worktrees"
    if not wt.is_dir():
        return 0
    total = 0
    for p in wt.rglob("*"):
        if p.is_file():
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return total


def _md_duplicates() -> list[dict[str, object]]:
    by_name: dict[str, list[str]] = {}
    for path in ROOT.rglob("*.md"):
        rel = path.relative_to(ROOT)
        if any(part in SKIP_DIR_NAMES for part in rel.parts):
            continue
        if ".claude" in rel.parts and "worktrees" in rel.parts:
            continue
        by_name.setdefault(path.name, []).append(rel.as_posix())
    out = []
    for name, paths in sorted(by_name.items()):
        if len(paths) < 2:
            continue
        hashes = {}
        for rel in paths:
            h = hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()
            hashes.setdefault(h, []).append(rel)
        out.append({"filename": name, "paths": paths, "content_groups": list(hashes.values())})
    return out


def _import_graph_for(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return []
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return sorted(set(imports))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    baseline = json.loads(PHASE0.read_text(encoding="utf-8"))
    root_py = _count_root_py()
    wt_bytes = _worktree_bytes()
    delta = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "phase0_root_py": baseline.get("root_py_count"),
        "current_root_py": root_py,
        "root_py_delta": root_py - int(baseline.get("root_py_count", root_py)),
        "phase0_worktrees_bytes": baseline.get("worktrees_bytes"),
        "current_worktrees_bytes": wt_bytes,
        "five_percent_reduction_met": root_py <= int(baseline.get("root_py_count", root_py)) * 0.95,
        "operator_signoff_required": root_py > int(baseline.get("root_py_count", root_py)) * 0.95,
        "note": (
            "Phase 3 gate allows >=5% root .py reduction OR operator sign-off with rationale. "
            "No root .py deletions in this slice — sign-off path documented."
        ),
    }
    (OUT / "baseline_delta.json").write_text(json.dumps(delta, indent=2) + "\n", encoding="utf-8")

    dups = _md_duplicates()
    (OUT / "duplicate_md_report.json").write_text(
        json.dumps({"duplicates": dups}, indent=2) + "\n",
        encoding="utf-8",
    )

    anchors = json.loads(DO_NOT_RENAME.read_text(encoding="utf-8"))["anchor_set"]
    py_rows = []
    for rel in anchors:
        if not rel.endswith(".py"):
            continue
        path = ROOT / rel
        if not path.is_file():
            py_rows.append({"path": rel, "exists": False, "imports": []})
            continue
        py_rows.append({"path": rel, "exists": True, "imports": _import_graph_for(path)})
    (OUT / "protected_py_audit.json").write_text(
        json.dumps({"protected_modules": py_rows}, indent=2) + "\n",
        encoding="utf-8",
    )

    notes = f"""> **Classification:** Operator Runbook | **Scope:** Phase 3 worktree cleanup operator guidance.

# Phase 3 worktree cleanup notes

Generated: {datetime.now(timezone.utc).isoformat()}

## Baseline (Phase 0 @ `{baseline.get("git_commit")}`)

- Worktrees disk: ~{baseline.get("worktrees_bytes", 0) / (1024**3):.2f} GB under `.claude/worktrees/`

## Current

- Worktrees disk: ~{(wt_bytes or 0) / (1024**3):.2f} GB

## Operator actions (not automated in consolidation)

1. List worktrees: `git worktree list`
2. Remove stale worktrees after confirming no unpushed commits: `git worktree remove <path>`
3. AGENTS.md excludes `**/.claude/worktrees/**` from repo hygiene sweeps — do not treat as product code.

## Duplicate MD review

See `duplicate_md_report.json` — e.g. `MODEL_RESTORE_LOG.md` at repo root vs `models/active/`.
Operator decides per-item delete/merge in Phase 3c; no deletions in this artifact-only slice.
"""
    (OUT / "worktree_cleanup_notes.md").write_text(notes, encoding="utf-8")
    print(f"wrote Phase 3 artifacts to {OUT}")


if __name__ == "__main__":
    main()
