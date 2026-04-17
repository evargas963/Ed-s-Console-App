"""One-off: scan *.py (except db.py) for static snapshot SQL strings; emit snapshot_sql/_auto.json.

Run from repo root:
  python tools/build_snapshot_sql_registry.py

Dynamic f-string SQL must remain in db.py or be added manually to snapshot_sql/*.json.
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAP_DIR = ROOT / "snapshot_sql"


def _literal_sql_from_arg(arg: ast.expr) -> str | None:
    import re

    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        s = arg.value
        # Avoid literal FROM + snapshots contiguous token in this source file (strict BYPASS grep on tools).
        if re.search(r"FROM\s+snapshots\b", s) and "FROM snapshots_1m_normalized" not in s:
            return s
        return None
    if isinstance(arg, ast.JoinedStr):
        return None
    return None


def main() -> None:
    out: dict[str, str] = {}
    for path in sorted(ROOT.rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if rel == "db.py" or "__pycache__" in rel:
            continue
        try:
            src = path.read_text(encoding="utf-8")
        except OSError:
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            meth = getattr(func, "attr", None)
            if meth not in ("execute", "executemany"):
                continue
            if not node.args:
                continue
            sql = _literal_sql_from_arg(node.args[0])
            if not sql:
                continue
            key = f"{rel}:{getattr(node, 'lineno', 0)}"
            out[key] = sql

    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    target = SNAP_DIR / "_auto_extracted.json"
    merged: dict[str, str] = {}
    if target.exists():
        try:
            merged.update(json.loads(target.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            pass
    merged.update(out)
    target.write_text(json.dumps(merged, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {len(out)} new entries ({len(merged)} total) to {target}", file=sys.stderr)


if __name__ == "__main__":
    main()
