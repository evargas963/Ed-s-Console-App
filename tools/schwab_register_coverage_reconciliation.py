#!/usr/bin/env python3
"""Machine-counted register coverage reconciliation (D17 recovery evidence).

Partitions EVERY current register row into exactly one category so the coverage
arithmetic has no unexplained remainder, and accounts for every reviewed slice
row on the slice-side denominator. Written for
POST_MERGE_MAIN_RECOVERY_UNIVERSAL_CLOSURE_V2: the coordinate-identity defect
made three numbers circulate with different denominators (4,903 stale
inheritances measured on a dirty-tree register; 4,786 d17 path+line-only slice
rejects; 7 rekeyed REPLACED rows) — this tool recomputes all coverage facts
from the CURRENT bytes with the denominator stated per figure.

Register-row categories (a partition; total == sum of all):
  NO_HISTORICAL_CLAIMANT   no reviewed slice row claims this row's identity
  CONTENT_MATCH_APPLIED    claimant(s) with byte-equal surface and ONE disposition
  CONTENT_MISMATCH_REFUSED claimant exists but reviewed surface differs (the
                           stale-coordinate-inheritance class, now fail-closed)
  CONFLICT_REFUSED         byte-equal claimants disagree on disposition
  EMPTY_SURFACE_REFUSED    row or claimant carries no content identity

Slice-side categories for reviewed rows (a partition of reviewed slice rows):
  RESOLVES_TO_CURRENT_ROW  applied by the content-bound resolver
  SITE_CONTENT_ABSENT      no current register row carries the reviewed surface
                           on the reviewed path (code removed or rewritten)
  SITE_CONTENT_AMBIGUOUS   >1 current row carries the reviewed surface (unsafe
                           to rekey automatically)
  SITE_PRESENT_NOT_KEYED   exactly one current row carries the reviewed surface
                           but identity (id/site) differs — unique rekey candidate

Usage:
  python tools/schwab_register_coverage_reconciliation.py \
      [--register CSV] [--slice-dir DIR] [--out JSON]

Deterministic output (sorted keys, no timestamps). The register itself is
gitignored; retained evidence lives under
governance/artifacts/register_reconciliation/ (scanner-scope excluded, so the
evidence can never perturb the pin it describes).

Schwab CSV authority checked: yes
CSV row(s): NO_SCHWAB_EQUIVALENT — governance coverage accounting only.
SCHWAB_CSV_CHECKED
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from governance.phase2_d17_contract_test_denylist import MONEY_PATH_PATHS  # noqa: E402
from tools.stream_revert_v4_register_and_sync_perf import (  # noqa: E402
    DEFAULT_REGISTER,
    DEFAULT_SLICE_DIR,
    _resolve_slice_row,
    load_slice_disposition_maps,
    site_key,
)

DEFAULT_OUT = (
    ROOT / "governance" / "artifacts" / "register_reconciliation"
    / "post_merge_recovery_v2_reconciliation.json"
)

REGISTER_CATEGORIES = (
    "NO_HISTORICAL_CLAIMANT",
    "CONTENT_MATCH_APPLIED",
    "CONTENT_MISMATCH_REFUSED",
    "CONFLICT_REFUSED",
    "EMPTY_SURFACE_REFUSED",
)


def classify_register_row(
    row: dict[str, str],
    by_id: dict[str, list[dict[str, str]]],
    by_site: dict,
    by_path_line: dict,
) -> str:
    rid = (row.get("register_id") or "").strip()
    claimants: list[dict[str, str]] = []
    claimants += by_id.get(rid, [])
    claimants += by_site.get(site_key(row), [])
    pl = by_path_line.get(
        ((row.get("path") or "").strip().replace("\\", "/"), int(row.get("line") or 0))
    )
    if pl is not None:
        claimants.append(pl)
    if not claimants:
        return "NO_HISTORICAL_CLAIMANT"
    sf = row.get("surface_form") or ""
    if not sf.strip() or all(not (c.get("surface_form") or "").strip() for c in claimants):
        return "EMPTY_SURFACE_REFUSED"
    # mirror of _surface_bound: EXACT-BYTE content identity (indentation included)
    matching = [c for c in claimants if (c.get("surface_form") or "") == sf]
    if not matching:
        return "CONTENT_MISMATCH_REFUSED"
    disps = {(c.get("disposition") or "").strip() for c in matching}
    if len(disps) != 1:
        return "CONFLICT_REFUSED"
    return "CONTENT_MATCH_APPLIED"


def reconcile(register: Path, slice_dir: Path) -> dict:
    by_site, by_id, by_pl = load_slice_disposition_maps(slice_dir)

    per_cat: dict[str, int] = {c: 0 for c in REGISTER_CATEGORIES}
    per_cat_money: dict[str, int] = {c: 0 for c in REGISTER_CATEGORIES}
    per_file_refused: dict[str, int] = defaultdict(int)
    disposition_census: dict[str, int] = defaultdict(int)
    replaced_rows_total = 0
    replaced_rows_resolving = 0
    total = 0
    reg_surfaces_by_path: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    reg_id_surface: dict[str, str] = {}
    reg_site_surface: dict[tuple, str] = {}

    with register.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            total += 1
            path = (row.get("path") or "").strip().replace("\\", "/")
            disp = (row.get("disposition") or "").strip()
            disposition_census[disp or "UNREVIEWED"] += 1
            reg_surfaces_by_path[path][(row.get("surface_form") or "")] += 1
            reg_id_surface[(row.get("register_id") or "").strip()] = row.get("surface_form") or ""
            reg_site_surface[site_key(row)] = row.get("surface_form") or ""
            cat = classify_register_row(row, by_id, by_site, by_pl)
            per_cat[cat] += 1
            if path in MONEY_PATH_PATHS:
                per_cat_money[cat] += 1
            if cat in ("CONTENT_MISMATCH_REFUSED", "CONFLICT_REFUSED", "EMPTY_SURFACE_REFUSED"):
                per_file_refused[path] += 1
            if disp == "REPLACED":
                replaced_rows_total += 1
                if _resolve_slice_row(row, by_id, by_site, by_pl) is not None:
                    replaced_rows_resolving += 1

    # slice-side accounting over reviewed rows
    slice_rows: list[dict[str, str]] = []
    seen = set()
    for rows in list(by_id.values()) + list(by_site.values()):
        for r in rows:
            key = (id(r))
            if key in seen:
                continue
            seen.add(key)
            slice_rows.append(r)
    slice_side = {
        "RESOLVES_TO_CURRENT_ROW": 0,
        "SITE_CONTENT_ABSENT": 0,
        "SITE_CONTENT_AMBIGUOUS": 0,
        "SITE_PRESENT_NOT_KEYED": 0,
        "EMPTY_SURFACE_CLAIM": 0,
    }
    unresolved_by_disposition: dict[str, int] = defaultdict(int)
    for r in slice_rows:
        sf = r.get("surface_form") or ""
        path = (r.get("path") or "").strip().replace("\\", "/")
        if not sf.strip():
            slice_side["EMPTY_SURFACE_CLAIM"] += 1
            continue
        occurrences = reg_surfaces_by_path.get(path, {}).get(sf, 0)
        rid = (r.get("register_id") or "").strip()
        # identity hit = the reviewed identity (register_id or full site key) is
        # present in the register AND that row carries the reviewed content —
        # exactly the content-bound resolver's application condition
        identity_hit = (
            reg_id_surface.get(rid) == sf
            or reg_site_surface.get(site_key(r)) == sf
        )
        if identity_hit:
            slice_side["RESOLVES_TO_CURRENT_ROW"] += 1
        elif occurrences == 0:
            slice_side["SITE_CONTENT_ABSENT"] += 1
            unresolved_by_disposition[(r.get("disposition") or "").strip()] += 1
        elif occurrences > 1:
            slice_side["SITE_CONTENT_AMBIGUOUS"] += 1
            unresolved_by_disposition[(r.get("disposition") or "").strip()] += 1
        else:
            slice_side["SITE_PRESENT_NOT_KEYED"] += 1
            unresolved_by_disposition[(r.get("disposition") or "").strip()] += 1

    arithmetic_ok = total == sum(per_cat.values())
    report = {
        "schema": "REGISTER_COVERAGE_RECONCILIATION",
        "schema_version": 1,
        "register_rows_total": total,
        "register_categories": dict(sorted(per_cat.items())),
        "register_categories_money_path": dict(sorted(per_cat_money.items())),
        "arithmetic_identity_total_equals_category_sum": arithmetic_ok,
        "disposition_census": dict(sorted(disposition_census.items())),
        "replaced_rows_total": replaced_rows_total,
        "replaced_rows_resolving_content_bound": replaced_rows_resolving,
        "reviewed_slice_rows_total": len(slice_rows),
        "slice_side_categories": dict(sorted(slice_side.items())),
        "slice_side_arithmetic_ok": len(slice_rows) == sum(slice_side.values()),
        "slice_unresolved_by_disposition": dict(sorted(unresolved_by_disposition.items())),
        "refused_rows_by_file_top40": dict(
            sorted(per_file_refused.items(), key=lambda kv: -kv[1])[:40]
        ),
        "money_path_paths": sorted(MONEY_PATH_PATHS),
        "denominator_notes": {
            "register_categories": "current register rows (one category each)",
            "slice_side_categories": "reviewed slice claimant rows (one category each)",
            "historical_4903_figure": (
                "CONTENT_MISMATCH-class rows measured 2026-07-15 on a dirty-tree "
                "register before the V2 recomputation; superseded by "
                "register_categories.CONTENT_MISMATCH_REFUSED on clean bytes"
            ),
            "historical_4786_figure": (
                "d17 rekey path+line-only rejects — a SLICE-row denominator, not a "
                "register-row denominator; superseded by slice_side_categories"
            ),
            "seven_rekeyed_rows": (
                "REPLACED slice rows re-keyed to unique byte-identical sites in the "
                "c0ca01e recovery commit; they appear here inside "
                "RESOLVES_TO_CURRENT_ROW / CONTENT_MATCH_APPLIED"
            ),
        },
    }
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--register", type=Path, default=DEFAULT_REGISTER)
    ap.add_argument("--slice-dir", type=Path, default=DEFAULT_SLICE_DIR)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args(argv)
    if not args.register.is_file():
        print(f"register not found: {args.register}", file=sys.stderr)
        return 2
    report = reconcile(args.register, args.slice_dir)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n",
                        encoding="utf-8", newline="")
    print(json.dumps({k: report[k] for k in (
        "register_rows_total", "register_categories",
        "arithmetic_identity_total_equals_category_sum",
        "replaced_rows_total", "replaced_rows_resolving_content_bound",
        "reviewed_slice_rows_total", "slice_side_categories",
        "slice_side_arithmetic_ok",
    )}, indent=1, sort_keys=True))
    ok = (report["arithmetic_identity_total_equals_category_sum"]
          and report["slice_side_arithmetic_ok"]
          and report["replaced_rows_total"] == report["replaced_rows_resolving_content_bound"])
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
