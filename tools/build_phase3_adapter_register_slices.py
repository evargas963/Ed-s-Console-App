#!/usr/bin/env python3
"""Build Phase 3 D17 adapter-trio register_slices from reconciled V4 register.

Regenerate after scanner regen on main:
  python -m tools.schwab_universal_coverage_scanner_v3 \\
    --output governance/SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv --embedding-mode mock
  python tools/stream_revert_v4_register_and_sync_perf.py --merge-slices
  python tools/build_phase3_adapter_register_slices.py
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from governance.phase3_d17_adapter_boundary import (
    PHASE3_ADAPTER_PATHS,
    PHASE3_ADAPTER_WIRE_DENYLIST,
    PHASE3_LEXICAL_KEEP_DERIVED_DENYLIST,
    PHASE3_LEXICAL_KEEP_DERIVED_DISPOSITIONS,
    PHASE3_NMD_NOTE,
    PHASE3_WIRE_DISPOSITIONS,
    PHASE3_WIRE_TRACE,
    WIRE_PATTERN_KINDS,
    WireDisposition,
)
from tools.schwab_universal_coverage_scanner_v3.register import REGISTER_COLUMNS

DEFAULT_REGISTER = ROOT / "governance" / "SCHWAB_UNIVERSAL_COVERAGE_REGISTER_V4.csv"
SLICE_DIR = ROOT / "governance" / "register_slices"

PHASE3_LEXICAL_SLICE = "phase3_adapter_lexical_not_market_data.csv"
PHASE3_WIRE_SLICE = "phase3_adapter_wire_disposition.csv"


def _norm(path: str) -> str:
    return (path or "").strip().replace("\\", "/")


def _apply_disposition(row: dict[str, str], spec: WireDisposition, *, trace: str) -> dict[str, str]:
    out = dict(row)
    out["disposition"] = spec.disposition
    if spec.canonical_field_citation:
        out["canonical_field_citation"] = spec.canonical_field_citation
    if spec.governed_ref:
        out["governed_ref"] = spec.governed_ref
    note = (out.get("notes") or "").strip()
    merged_note = spec.notes if spec.notes else trace
    out["notes"] = merged_note if not note else f"{note}; {merged_note}"
    out["v2_trace"] = trace
    return out


def _nmd_row(row: dict[str, str]) -> dict[str, str]:
    out = dict(row)
    out["disposition"] = "NOT_MARKET_DATA"
    note = (out.get("notes") or "").strip()
    out["notes"] = PHASE3_NMD_NOTE if not note else f"{note}; {PHASE3_NMD_NOTE}"
    out["v2_trace"] = PHASE3_NMD_NOTE
    return out


def _is_excluded_from_lexical_nmd(register_id: str, pattern_kind: str) -> bool:
    if register_id in PHASE3_ADAPTER_WIRE_DENYLIST:
        return True
    if register_id in PHASE3_LEXICAL_KEEP_DERIVED_DENYLIST:
        return True
    return pattern_kind in WIRE_PATTERN_KINDS


def build_slices(register: Path, *, dry_run: bool = False) -> dict[str, int | dict[str, int]]:
    lexical: list[dict[str, str]] = []
    wire: list[dict[str, str]] = []
    disposition_counts: dict[str, int] = {}

    with register.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if (row.get("disposition") or "").strip() != "UNREVIEWED":
                continue
            path = _norm(row.get("path") or "")
            if path not in PHASE3_ADAPTER_PATHS:
                continue
            rid = (row.get("register_id") or "").strip()
            pk = (row.get("pattern_kind") or "").strip()

            if rid in PHASE3_ADAPTER_WIRE_DENYLIST:
                spec = PHASE3_WIRE_DISPOSITIONS[rid]
                wire.append(_apply_disposition(row, spec, trace=PHASE3_WIRE_TRACE))
                disposition_counts[spec.disposition] = disposition_counts.get(spec.disposition, 0) + 1
                continue

            if rid in PHASE3_LEXICAL_KEEP_DERIVED_DENYLIST:
                spec = PHASE3_LEXICAL_KEEP_DERIVED_DISPOSITIONS[rid]
                wire.append(_apply_disposition(row, spec, trace=PHASE3_WIRE_TRACE))
                disposition_counts[spec.disposition] = disposition_counts.get(spec.disposition, 0) + 1
                continue

            if pk in WIRE_PATTERN_KINDS:
                raise SystemExit(
                    f"wire-pattern row missing from PHASE3_ADAPTER_WIRE_DENYLIST: "
                    f"register_id={rid!r} path={path!r} pattern_kind={pk!r}"
                )

            lexical.append(_nmd_row(row))

    counts = {
        PHASE3_LEXICAL_SLICE: len(lexical),
        PHASE3_WIRE_SLICE: len(wire),
        "disposition_counts": disposition_counts,
    }
    if dry_run:
        return counts

    SLICE_DIR.mkdir(parents=True, exist_ok=True)
    lex_path = SLICE_DIR / PHASE3_LEXICAL_SLICE
    with lex_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=REGISTER_COLUMNS)
        w.writeheader()
        w.writerows(lexical)

    wire_path = SLICE_DIR / PHASE3_WIRE_SLICE
    with wire_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=REGISTER_COLUMNS)
        w.writeheader()
        w.writerows(wire)

    return counts


def main() -> int:
    ap = argparse.ArgumentParser(description="Build Phase 3 adapter register_slices")
    ap.add_argument("--register", type=Path, default=DEFAULT_REGISTER)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if not args.register.is_file():
        print(f"register missing: {args.register}", file=sys.stderr)
        return 1

    if len(PHASE3_ADAPTER_WIRE_DENYLIST) != len(PHASE3_WIRE_DISPOSITIONS):
        print(
            "PHASE3_ADAPTER_WIRE_DENYLIST and PHASE3_WIRE_DISPOSITIONS size mismatch",
            file=sys.stderr,
        )
        return 1
    missing = PHASE3_ADAPTER_WIRE_DENYLIST - set(PHASE3_WIRE_DISPOSITIONS)
    if missing:
        print(f"missing wire dispositions for: {sorted(missing)}", file=sys.stderr)
        return 1

    counts = build_slices(args.register, dry_run=args.dry_run)
    print("phase3_slice_row_counts", {k: v for k, v in counts.items() if k != "disposition_counts"})
    print("phase3_disposition_counts", counts["disposition_counts"])
    print(
        "phase3_total_rows",
        int(counts[PHASE3_LEXICAL_SLICE]) + int(counts[PHASE3_WIRE_SLICE]),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
