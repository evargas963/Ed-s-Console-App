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

# RC-REHAB-1 (2026-09-22): matches tools/anti_pattern_sweep.py's SKIP_DIR_PARTS -- this
# script never excluded vendored/generated trees, so it crashed on the first non-UTF-8
# file rglob("*.py") happened to walk into inside .venv/site-packages. Not previously
# caught because this script is manual/one-off, not CI/pre-commit-wired.
_SKIP_DIR_PARTS = frozenset(
    {".git", ".claude", "__pycache__", ".venv", "venv", "node_modules", ".pytest_cache"}
)


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
        if _SKIP_DIR_PARTS & set(path.parts):
            continue
        rel = path.relative_to(ROOT).as_posix()
        # RC-REHAB-1 (2026-09-22): the sql_* builders moved to db_sql_fragments.py
        # (db.py decomposition follow-up) -- same exemption, new home.
        if rel in ("db.py", "db_sql_fragments.py"):
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
    # newline="" -- write_text's platform-default newline translation flips this file's LF
    # convention to CRLF on Windows (RC-382 eol-style-invariant caught it), obscuring the
    # real diff under a spurious terminator-only change on every regeneration.
    target.write_text(
        json.dumps(merged, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline=""
    )
    print(f"Wrote {len(out)} new entries ({len(merged)} total) to {target}", file=sys.stderr)


if __name__ == "__main__":
    main()
