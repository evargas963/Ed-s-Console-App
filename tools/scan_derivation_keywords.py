"""Quick inventory: Python lines that often imply derive/compute/approximate work.

Run from repo root:
  python tools/scan_derivation_keywords.py
  python tools/scan_derivation_keywords.py --max 200

This does NOT prove a Schwab replacement exists; it is the start of
\"wire first\" review: for each hit, ask whether schwab_field_dictionary.csv
already exposes the primitive.

Excludes: .git, node_modules, venv, __pycache__, .pytest_cache, backups, models/**.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SKIP_DIR_NAMES = {
    ".git",
    ".claude",
    "node_modules",
    "venv",
    ".venv",
    "env",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "backups",
}

# Line must match at least one pattern (case-sensitive for def names).
PATTERNS = [
    re.compile(r"def\s+(compute_|derive_|estimate_|infer_|approximate_|synthesize_)"),
    re.compile(r"\b(approximate|synthesize|fallback|default\s+to|synthetic)\b", re.I),
    re.compile(r"\(bid.*\+.*ask\)|\(ask.*\+.*bid\)"),
    re.compile(r"0\.20\b.*\b(iv|IV|volatility)\b|\biv\b.*0\.20", re.I),
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--max", type=int, default=0, help="Max lines to print (0 = no limit)")
    args = ap.parse_args()
    root = args.root.resolve()
    printed = 0
    for p in sorted(root.rglob("*.py")):
        parts = set(p.relative_to(root).parts)
        if parts & SKIP_DIR_NAMES:
            continue
        if "models" in parts and p.suffix == ".py":
            # skip huge model trees by default
            continue
        rel = p.relative_to(root).as_posix()
        if rel.startswith("models/"):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            if not any(rx.search(line) for rx in PATTERNS):
                continue
            if "scan_derivation_keywords.py" in rel:
                continue
            safe = line.strip()[:240].encode("ascii", "replace").decode("ascii")
            print(f"{rel}\t{i}\t{safe}")
            printed += 1
            if args.max and printed >= args.max:
                return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
