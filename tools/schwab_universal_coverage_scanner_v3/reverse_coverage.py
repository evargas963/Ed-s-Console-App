"""Reverse coverage — V3-C / Deliverable 13."""

from __future__ import annotations

from collections import defaultdict

from .register import RegisterRow
from .schwab_csv import SchwabCsvIndex


def build_reverse_coverage_rows(
    register_rows: list[RegisterRow],
    idx: SchwabCsvIndex,
) -> list[dict[str, str]]:
    """
    For each canonical_field in the dictionary, emit field_referenced or field_orphaned
    with semicolon-separated register_id pointers.
    """
    cfs = idx.all_canonical_fields()
    cf_set = set(cfs)
    cited: dict[str, list[str]] = defaultdict(list)
    for r in register_rows:
        for part in r.csv_candidates.split(";"):
            p = part.strip()
            if p in cf_set:
                cited[p].append(r.register_id)
    out: list[dict[str, str]] = []
    for cf in cfs:
        ids = cited.get(cf)
        if ids:
            uniq = sorted(set(ids))
            out.append(
                {
                    "canonical_field": cf,
                    "status": "field_referenced",
                    "register_ids": ";".join(uniq),
                }
            )
        else:
            out.append(
                {
                    "canonical_field": cf,
                    "status": "field_orphaned",
                    "register_ids": "",
                }
            )
    return out
