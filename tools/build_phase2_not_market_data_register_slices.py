#!/usr/bin/env python3
"""Build Phase 2 D17 register_slices bulk NOT_MARKET_DATA CSVs from reconciled V4 register.

Regenerate after scanner regen on main:
  python -m tools.schwab_universal_coverage_scanner_v3 \\
    --output governance/SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv --embedding-mode mock
  python tools/stream_revert_v4_register_and_sync_perf.py --merge-slices
  python tools/build_phase2_not_market_data_register_slices.py
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from governance.phase2_d17_contract_test_denylist import (
    MEGA_INVENTORY_PATHS,
    PHASE2_CONTRACT_TEST_DENYLIST,
    PHASE2_NMD_NOTE,
    ROOT_PROGRAM_LAW_PATHS,
)
from tools.schwab_universal_coverage_scanner_v3.register import REGISTER_COLUMNS

DEFAULT_REGISTER = ROOT / "governance" / "SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv"
SLICE_DIR = ROOT / "governance" / "register_slices"

PHASE2_SLICE_FILES = (
    "phase2_governance_md_not_market_data.csv",
    "phase2_docs_md_not_market_data.csv",
    "phase2_mega_inventories_not_market_data.csv",
    "phase2_tests_non_contract_not_market_data.csv",
)


def _norm(path: str) -> str:
    return (path or "").strip().replace("\\", "/")


def _nmd_row(row: dict[str, str]) -> dict[str, str]:
    out = dict(row)
    out["disposition"] = "NOT_MARKET_DATA"
    note = (out.get("notes") or "").strip()
    out["notes"] = PHASE2_NMD_NOTE if not note else f"{note}; {PHASE2_NMD_NOTE}"
    out["v2_trace"] = "Phase 2 D17 bulk NOT_MARKET_DATA disposition slice"
    return out


def _classify(path: str) -> str | None:
    if path.startswith("governance/") and path.endswith(".md"):
        return "phase2_governance_md_not_market_data.csv"
    if path.startswith("docs/") and path.endswith(".md"):
        return "phase2_docs_md_not_market_data.csv"
    if path in MEGA_INVENTORY_PATHS:
        return "phase2_mega_inventories_not_market_data.csv"
    if path.startswith("tests/") and path not in PHASE2_CONTRACT_TEST_DENYLIST:
        return "phase2_tests_non_contract_not_market_data.csv"
    return None


def build_slices(register: Path, *, dry_run: bool = False) -> dict[str, int]:
    buckets: dict[str, list[dict[str, str]]] = {name: [] for name in PHASE2_SLICE_FILES}
    with register.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if (row.get("disposition") or "").strip() != "UNREVIEWED":
                continue
            path = _norm(row.get("path") or "")
            if path in ROOT_PROGRAM_LAW_PATHS:
                continue
            bucket = _classify(path)
            if bucket is None:
                continue
            buckets[bucket].append(_nmd_row(row))

    counts: dict[str, int] = {}
    if dry_run:
        return {name: len(rows) for name, rows in buckets.items()}

    SLICE_DIR.mkdir(parents=True, exist_ok=True)
    for name, rows in buckets.items():
        out = SLICE_DIR / name
        with out.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=REGISTER_COLUMNS)
            w.writeheader()
            w.writerows(rows)
        counts[name] = len(rows)
    return counts


def main() -> int:
    ap = argparse.ArgumentParser(description="Build Phase 2 NOT_MARKET_DATA register_slices")
    ap.add_argument("--register", type=Path, default=DEFAULT_REGISTER)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not args.register.is_file():
        print(f"register missing: {args.register}", file=sys.stderr)
        return 1
    counts = build_slices(args.register, dry_run=args.dry_run)
    total = sum(counts.values())
    print("phase2_slice_row_counts", dict(counts))
    print("phase2_total_nmd_rows", total)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
