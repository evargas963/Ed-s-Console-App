#!/usr/bin/env python3
"""Repair apply_snapshot_registry.py output that wrapped get_snapshot_sql in string literals."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def fix_text(text: str) -> str:
    # """get_snapshot_sql("key")"""
    text = re.sub(
        r'"""get_snapshot_sql\("([^"]+)"\)"""',
        r'get_snapshot_sql("\1")',
        text,
    )
    # "get_snapshot_sql("key")"  (mangled nested quotes)
    text = re.sub(
        r'"get_snapshot_sql\("([^"]+)"\)"',
        r'get_snapshot_sql("\1")',
        text,
    )
    # f"get_snapshot_sql("key") ... "
    text = re.sub(
        r'f"get_snapshot_sql\("([^"]+)"\)\s*([^"]*)"',
        lambda m: 'get_snapshot_sql("' + m.group(1) + '") + f"' + m.group(2) + '"',
        text,
    )
    return text


def main() -> None:
    changed = 0
    for path in sorted(ROOT.rglob("*.py")):
        if "fix_mangled_get_snapshot_sql" in path.name:
            continue
        raw = path.read_text(encoding="utf-8")
        new = fix_text(raw)
        if new != raw:
            path.write_text(new, encoding="utf-8")
            print(path.relative_to(ROOT))
            changed += 1
    print(f"Touched {changed} files", file=sys.stderr)


if __name__ == "__main__":
    main()
