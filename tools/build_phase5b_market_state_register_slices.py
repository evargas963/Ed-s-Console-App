#!/usr/bin/env python3
"""Build Phase 5B D17 market_state.py mixed-line lexical NOT_MARKET_DATA register slice.

Regenerate after scanner regen + slice merge on main:
  python -m tools.schwab_universal_coverage_scanner_v3 \\
    --output governance/SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv --embedding-mode mock
  python tools/stream_revert_v4_register_and_sync_perf.py --merge-slices
  python tools/build_phase5b_market_state_register_slices.py
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from governance.phase5b_d17_market_state_mixed_line_boundary import (
    PHASE4_LEXICAL_PATTERN_KINDS,
    PHASE5B_MARKET_STATE_PATH,
    PHASE5B_MIXED_LINE_LEXICAL_REGISTER_IDS,
    PHASE5B_NMD_NOTE,
    WIRE_PATTERN_KINDS,
)
from tools.schwab_universal_coverage_scanner_v3.register import REGISTER_COLUMNS

DEFAULT_REGISTER = ROOT / "governance" / "SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv"
SLICE_DIR = ROOT / "governance" / "register_slices"
PHASE5B_MIXED_LINE_SLICE = "phase5b_market_state_mixed_line_lexical_not_market_data.csv"


def _norm(path: str) -> str:
    return (path or "").strip().replace("\\", "/")


def _nmd_row(row: dict[str, str]) -> dict[str, str]:
    out = dict(row)
    out["disposition"] = "NOT_MARKET_DATA"
    note = (out.get("notes") or "").strip()
    out["notes"] = PHASE5B_NMD_NOTE if not note else f"{note}; {PHASE5B_NMD_NOTE}"
    out["v2_trace"] = PHASE5B_NMD_NOTE
    return out


def _is_phase5b_candidate(row: dict[str, str]) -> bool:
    rid = (row.get("register_id") or "").strip()
    if rid not in PHASE5B_MIXED_LINE_LEXICAL_REGISTER_IDS:
        return False
    pk = (row.get("pattern_kind") or "").strip()
    if pk not in PHASE4_LEXICAL_PATTERN_KINDS:
        return False
    if pk in WIRE_PATTERN_KINDS:
        return False
    return _norm(row.get("path") or "") == PHASE5B_MARKET_STATE_PATH


def build_slice(register: Path, *, dry_run: bool = False) -> dict[str, int]:
    selected: list[dict[str, str]] = []
    seen_ids: set[str] = set()

    with register.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if (row.get("disposition") or "").strip() != "UNREVIEWED":
                continue
            if not _is_phase5b_candidate(row):
                continue
            rid = (row.get("register_id") or "").strip()
            if rid in seen_ids:
                continue
            seen_ids.add(rid)
            selected.append(_nmd_row(row))

    counts = {
        PHASE5B_MIXED_LINE_SLICE: len(selected),
        "expected_rows": len(PHASE5B_MIXED_LINE_LEXICAL_REGISTER_IDS),
    }
    if dry_run:
        return counts

    if len(selected) != len(PHASE5B_MIXED_LINE_LEXICAL_REGISTER_IDS):
        missing = PHASE5B_MIXED_LINE_LEXICAL_REGISTER_IDS - seen_ids
        raise SystemExit(
            f"phase5b slice row count {len(selected)} != "
            f"expected {len(PHASE5B_MIXED_LINE_LEXICAL_REGISTER_IDS)}; "
            f"missing register_ids={sorted(missing)}"
        )

    SLICE_DIR.mkdir(parents=True, exist_ok=True)
    out_path = SLICE_DIR / PHASE5B_MIXED_LINE_SLICE
    selected.sort(key=lambda r: (int(r.get("line") or 0), (r.get("register_id") or "")))
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=REGISTER_COLUMNS)
        w.writeheader()
        w.writerows(selected)
    return counts


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Build Phase 5B market_state mixed-line lexical NMD slice"
    )
    ap.add_argument("--register", type=Path, default=DEFAULT_REGISTER)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not args.register.is_file():
        print(f"register missing: {args.register}", file=sys.stderr)
        return 1

    counts = build_slice(args.register, dry_run=args.dry_run)
    print("phase5b_slice_row_counts", {k: v for k, v in counts.items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
