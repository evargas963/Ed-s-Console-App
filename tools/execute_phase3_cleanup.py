"""Phase 3 execution: archive historical MDs, audit hooks/worktrees, record 3c/3d decisions."""
from __future__ import annotations

import ast
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "governance/archive/2026-Q2"
OUT = ROOT / "governance/consolidation/phase3"

ROOT_AUDITS = [
    "CALL_CARD_SEMANTICS_FIX_AUDIT.md",
    "CARD_STUCK_FIX_AUDIT.md",
    "FUSION_MC_AUDIT.md",
    "LSTM_INACTIVE_FIX_AUDIT.md",
    "MODEL_STATUS_HARDENING_AUDIT.md",
    "SCHWAB_AUTH_AUDIT.md",
    "SNAPSHOT_DATA_AUDIT.md",
]

ROOT_HISTORICAL = [
    "MIGRATION_1M_CANONICAL.md",
    "PIPELINE_QUALITY.md",
]

SUPERSEDED_SCHWAB = [
    "governance/SCHWAB_UNIVERSAL_COVERAGE_PROGRAM_V1.md",
    "governance/SCHWAB_UNIVERSAL_COVERAGE_PROGRAM_V2.md",
    "governance/SCHWAB_UNIVERSAL_COVERAGE_PROGRAM_V3.md",
    "governance/SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V2.md",
    "governance/SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V3.md",
]

LFS_HOOKS = ("pre-push", "post-checkout", "post-commit", "post-merge")


def _stub(rel_archive: str, *, active: str | None = None) -> str:
    lines = [
        f"> **Archived Phase 3b** — full text at [`{rel_archive}`]({rel_archive}).",
        "> **Classification:** Historical Record | **Scope:** Archived; not binding unless ACTIVE_PROGRAM cites.",
    ]
    if active:
        lines.append(f"> **Active authority:** `{active}`")
    lines.append("")
    lines.append(f"See [`{rel_archive}`]({rel_archive}).")
    lines.append("")
    return "\n".join(lines)


def _git_mv(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        raise SystemExit(f"dest exists: {dest}")
    subprocess.run(["git", "mv", str(src), str(dest)], cwd=ROOT, check=True)


def archive_moves() -> list[dict[str, str]]:
    moves: list[dict[str, str]] = []
    for name in ROOT_AUDITS:
        src = ROOT / name
        dest = ARCHIVE / "root_audits" / name
        rel_archive = dest.relative_to(ROOT).as_posix()
        _git_mv(src, dest)
        stub = ROOT / name
        stub.write_text(_stub(rel_archive), encoding="utf-8")
        moves.append({"from": name, "to": rel_archive, "stub": name})

    for name in ROOT_HISTORICAL:
        src = ROOT / name
        dest = ARCHIVE / "root_historical" / name
        rel_archive = dest.relative_to(ROOT).as_posix()
        _git_mv(src, dest)
        (ROOT / name).write_text(_stub(rel_archive), encoding="utf-8")
        moves.append({"from": name, "to": rel_archive, "stub": name})

    for rel in SUPERSEDED_SCHWAB:
        src = ROOT / rel
        if not src.is_file():
            continue
        dest = ARCHIVE / "superseded_schwab_coverage" / Path(rel).name
        rel_archive = dest.relative_to(ROOT).as_posix()
        _git_mv(src, dest)
        active = (
            "governance/SCHWAB_UNIVERSAL_COVERAGE_PROGRAM_V4.md"
            if "PROGRAM" in rel
            else "governance/SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv"
        )
        (ROOT / rel).write_text(_stub(rel_archive, active=active), encoding="utf-8")
        moves.append({"from": rel, "to": rel_archive, "stub": rel})
    return moves


def import_graph_audit() -> dict[str, object]:
    protected = json.loads(
        (ROOT / "governance/consolidation/phase0/do_not_rename_paths.json").read_text(
            encoding="utf-8"
        )
    )["anchor_set"]
    rows = []
    for rel in protected:
        if not rel.endswith(".py"):
            continue
        path = ROOT / rel
        if not path.is_file():
            rows.append({"path": rel, "exists": False, "imports": [], "imported_by": []})
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            rows.append({"path": rel, "exists": True, "parse_error": str(exc)})
            continue
        imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
        rows.append({"path": rel, "exists": True, "imports": sorted(imports)})
    return {"protected_modules": rows, "root_py_moves": "none — operator sign-off path; no safe moves without import-graph proof"}


def lfs_hooks_audit() -> dict[str, object]:
    hooks_dir = ROOT / ".git/hooks"
    rows = []
    for name in LFS_HOOKS:
        path = hooks_dir / name
        if not path.is_file():
            rows.append({"hook": name, "present": False})
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        rows.append(
            {
                "hook": name,
                "present": True,
                "is_lfs_shim": "git lfs" in text or "git-lfs" in text,
                "first_line": text.splitlines()[0] if text.splitlines() else "",
            }
        )
    return {"hooks": rows}


def worktree_audit() -> dict[str, object]:
    proc = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    entries: list[dict[str, str]] = []
    cur: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        if not line.strip():
            if cur:
                entries.append(cur)
                cur = {}
            continue
        key, _, val = line.partition(" ")
        cur[key] = val.strip()
    if cur:
        entries.append(cur)
    wt_bytes = 0
    wt_root = ROOT / ".claude/worktrees"
    if wt_root.is_dir():
        for p in wt_root.rglob("*"):
            if p.is_file():
                try:
                    wt_bytes += p.stat().st_size
                except OSError:
                    pass
    return {
        "worktrees": entries,
        "worktrees_bytes": wt_bytes,
        "prune_executed": False,
        "prune_note": (
            "All Claude worktrees show broad dirty state (likely line-ending drift). "
            "Operator must confirm no unique commits before `git worktree remove --force`."
        ),
    }


def duplicate_deletion_decisions() -> list[dict[str, str]]:
    return [
        {
            "item": "MODEL_RESTORE_LOG.md vs models/active/MODEL_RESTORE_LOG.md",
            "decision": "no_delete",
            "reason": "Different content groups in duplicate_md_report.json; both retained.",
        },
        {
            "item": "models/validation_runs/*/AUTHORITY_REPORT.md",
            "decision": "no_delete",
            "reason": "Per-run artifacts; same filename, different content.",
        },
    ]


def write_execution_log(moves: list[dict[str, str]]) -> None:
    log = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "phase": "3 execution",
        "operator_signoff": True,
        "3b_archives": moves,
        "3c_deletions": duplicate_deletion_decisions(),
        "3d_import_graph": import_graph_audit(),
        "3e_worktrees": worktree_audit(),
        "3f_lfs_hooks": lfs_hooks_audit(),
    }
    (OUT / "phase3_execution_log.json").write_text(
        json.dumps(log, indent=2) + "\n", encoding="utf-8"
    )
    readme = ARCHIVE / "README.md"
    if not readme.is_file():
        readme.write_text(
            "# Governance archive — 2026-Q2\n\nPhase 1c memory + Phase 3b historical/superseded moves.\n",
            encoding="utf-8",
        )


def main() -> None:
    moves = archive_moves()
    write_execution_log(moves)
    print(f"Phase 3b: archived {len(moves)} files; log at {OUT / 'phase3_execution_log.json'}")


if __name__ == "__main__":
    main()
