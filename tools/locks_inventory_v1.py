#!/usr/bin/env python3
"""Machine inventory of concurrency + governance locks (reports/locks_inventory_v1.json)."""
from __future__ import annotations

import ast
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SKIP_PARTS = {".venv", "node_modules", "__pycache__", ".git", ".claude", "EdWebConsole-Claude"}

LOCK_CALLS = {
    "threading.Lock": "mutex",
    "threading.RLock": "reentrant_mutex",
    "threading.Condition": "condition",
    "threading.Event": "event",
    "threading.Semaphore": "semaphore",
    "asyncio.Lock": "asyncio_mutex",
    "asyncio.Semaphore": "asyncio_semaphore",
}


def _skip(p: Path) -> bool:
    return any(part in SKIP_PARTS for part in p.parts)


def _assign_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _call_qualname(node: ast.Call) -> str | None:
    f = node.func
    if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name):
        return f"{f.value.id}.{f.attr}"
    if isinstance(f, ast.Name):
        return f.id
    return None


def scan_concurrency(root: Path) -> list[dict]:
    out: list[dict] = []
    for path in sorted(root.rglob("*.py")):
        if _skip(path):
            continue
        try:
            src = path.read_text(encoding="utf-8", errors="ignore")
            tree = ast.parse(src, filename=str(path))
        except (OSError, SyntaxError):
            continue
        rel = str(path.relative_to(root)).replace("\\", "/")
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
                continue
            q = _call_qualname(node.value)
            if q not in LOCK_CALLS and not (
                isinstance(node.value.func, ast.Name)
                and node.value.func.id in {"Lock", "RLock", "Condition", "Event", "Semaphore"}
            ):
                # also capture threading.Lock() via from-import aliases poorly; keep simple
                if q is None:
                    continue
                if q not in LOCK_CALLS:
                    continue
            kind = LOCK_CALLS.get(q or "", "unknown")
            for t in node.targets:
                name = _assign_name(t)
                if not name:
                    continue
                out.append(
                    {
                        "path": rel,
                        "line": getattr(node, "lineno", 0),
                        "symbol": name,
                        "construction": q,
                        "kind": kind,
                        "surface": "test" if "/tests/" in f"/{rel}" or rel.startswith("tests/") else "production",
                    }
                )
    return out


def parse_institutional_checks(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="ignore")
    rows = re.findall(
        r'\(\s*"([^"]+)"\s*,\s*(check_[A-Za-z0-9_]+)\s*,\s*(True|False)\s*\)',
        text,
    )
    enforced = [{"id": n, "fn": fn} for n, fn, f in rows if f == "True"]
    advisory = [{"id": n, "fn": fn} for n, fn, f in rows if f == "False"]
    ratchet = re.findall(
        r'_RATCHET_BLOCKS_ON_RISE\s*=\s*\{([^}]+)\}', text, re.S
    )
    ratchet_ids = re.findall(r'"([^"]+)"', ratchet[0]) if ratchet else []
    return {
        "enforced": enforced,
        "advisory": advisory,
        "ratchet_blocks_on_rise": ratchet_ids,
        "counts": {"enforced": len(enforced), "advisory": len(advisory), "total": len(rows)},
    }


def parse_precommit(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8", errors="ignore")
    # local hook ids
    ids = re.findall(r"^\s*-\s*id:\s*([^\s]+)\s*$", text, re.M)
    return [{"id": i, "config": str(path.relative_to(REPO)).replace("\\", "/")} for i in ids]


def main() -> int:
    conc = scan_concurrency(REPO)
    prod = [c for c in conc if c["surface"] == "production"]
    tests = [c for c in conc if c["surface"] == "test"]
    inst = parse_institutional_checks(REPO / "tools" / "check_institutional_correctness.py")
    hooks = parse_precommit(REPO / ".pre-commit-config.yaml")
    cursor_rules = sorted(
        str(p.relative_to(REPO)).replace("\\", "/")
        for p in (REPO / ".cursor" / "rules").glob("*.mdc")
    ) if (REPO / ".cursor" / "rules").is_dir() else []

    file_locks = [
        {
            "path": "tools/run_stream_capture.py",
            "symbol": "OWNER_LOCK",
            "kind": "pid_file_excl",
            "target": "data/stream_capture.lock",
        },
        {
            "path": "tools/feature_curation_gate.py",
            "symbol": "ABLATION_LOCK_PATH",
            "kind": "pid_file",
            "target": "governance/artifacts/feature_ablation.run.lock",
        },
        {
            "path": "tools/check_git_index_lock.py",
            "symbol": "index.lock clearer",
            "kind": "stale_git_index_lock",
            "target": ".git/index.lock",
            "stale_sec": 60,
        },
    ]

    report = {
        "schema_version": 1,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "repo": str(REPO),
        "concurrency": {
            "production_count": len(prod),
            "test_count": len(tests),
            "production": prod,
            "test": tests,
        },
        "file_ownership_locks": file_locks,
        "institutional_checks": inst,
        "precommit_hooks": hooks,
        "cursor_rules": cursor_rules,
        "decision_path_admissions": {
            "path": "governance/decision_path_admissions.json",
            "note": "empty admissions = fail-closed WAIT for TRADE influence",
        },
        "related_reports": [
            "reports/locks_violation_audit_v1.json",
        ],
    }
    out = REPO / "reports" / "locks_inventory_v1.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"WROTE {out} production_locks={len(prod)} enforced={inst['counts']['enforced']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
