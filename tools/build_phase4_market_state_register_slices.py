#!/usr/bin/env python3
"""Build Phase 4 D17 market_state.py lexical NOT_MARKET_DATA register slice.

Regenerate after scanner regen on main:
  python -m tools.schwab_universal_coverage_scanner_v3 \\
    --output governance/SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv --embedding-mode mock
  python tools/stream_revert_v4_register_and_sync_perf.py --merge-slices
  python tools/build_phase4_market_state_register_slices.py
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from governance.phase4_d17_market_state_boundary import (
    PHASE4_LEXICAL_PATTERN_KINDS,
    PHASE4_LEXICAL_REGISTER_DENYLIST,
    PHASE4_LEXICAL_WIRE_LINE_DENYLIST,
    PHASE4_MARKET_STATE_PATH,
    PHASE4_NMD_NOTE,
    WIRE_PATTERN_KINDS,
)
from tools.schwab_universal_coverage_scanner_v3.register import REGISTER_COLUMNS

DEFAULT_REGISTER = ROOT / "governance" / "SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv"
SLICE_DIR = ROOT / "governance" / "register_slices"
PHASE4_LEXICAL_SLICE = "phase4_market_state_lexical_not_market_data.csv"


def _norm(path: str) -> str:
    return (path or "").strip().replace("\\", "/")


def _nmd_row(row: dict[str, str]) -> dict[str, str]:
    out = dict(row)
    out["disposition"] = "NOT_MARKET_DATA"
    note = (out.get("notes") or "").strip()
    out["notes"] = PHASE4_NMD_NOTE if not note else f"{note}; {PHASE4_NMD_NOTE}"
    out["v2_trace"] = PHASE4_NMD_NOTE
    return out


def _is_excluded_lexical_row(row: dict[str, str]) -> bool:
    rid = (row.get("register_id") or "").strip()
    line = (row.get("line") or "").strip()
    if rid in PHASE4_LEXICAL_REGISTER_DENYLIST:
        return True
    return line in PHASE4_LEXICAL_WIRE_LINE_DENYLIST


def build_slice(register: Path, *, dry_run: bool = False) -> dict[str, int]:
    lexical: list[dict[str, str]] = []
    skipped_wire_overlap = 0

    with register.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if (row.get("disposition") or "").strip() != "UNREVIEWED":
                continue
            if _norm(row.get("path") or "") != PHASE4_MARKET_STATE_PATH:
                continue
            pk = (row.get("pattern_kind") or "").strip()
            if pk in WIRE_PATTERN_KINDS:
                continue
            if pk not in PHASE4_LEXICAL_PATTERN_KINDS:
                continue
            if _is_excluded_lexical_row(row):
                skipped_wire_overlap += 1
                continue
            lexical.append(_nmd_row(row))

    counts = {
        PHASE4_LEXICAL_SLICE: len(lexical),
        "skipped_wire_overlap": skipped_wire_overlap,
    }
    if dry_run:
        return counts

    SLICE_DIR.mkdir(parents=True, exist_ok=True)
    out_path = SLICE_DIR / PHASE4_LEXICAL_SLICE
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=REGISTER_COLUMNS)
        w.writeheader()
        w.writerows(lexical)
    return counts


def main() -> int:
    ap = argparse.ArgumentParser(description="Build Phase 4 market_state lexical NMD slice")
    ap.add_argument("--register", type=Path, default=DEFAULT_REGISTER)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not args.register.is_file():
        print(f"register missing: {args.register}", file=sys.stderr)
        return 1

    counts = build_slice(args.register, dry_run=args.dry_run)
    print("phase4_slice_row_counts", {k: v for k, v in counts.items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
