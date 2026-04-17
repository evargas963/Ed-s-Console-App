#!/usr/bin/env python3
"""
Multi-anchor survivorship report (shadow-only). Writes JSON; does not change production.

Example:
  python tools/similarity_feature_survivorship_report.py --db data/ed_console.db \\
    -o data/survivorship_report.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from calibration.paths import DEFAULT_DB
from db import EdDB

from similarity_feature_survivorship import (
    default_multi_anchor_set_v1,
    discover_tickers_for_survivorship,
    final_structure_from_survivorship,
    overall_confidence,
    run_multi_anchor_survivorship,
)


def main() -> int:
    p = argparse.ArgumentParser(description="Multi-anchor feature survivorship (JSON)")
    p.add_argument("--db", type=Path, default=DEFAULT_DB)
    p.add_argument("-o", "--output", type=Path, required=True)
    p.add_argument("--n-similar", type=int, default=250)
    p.add_argument("--candidate-pool-cap", type=int, default=1500)
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--min-rows-ticker", type=int, default=500)
    p.add_argument("--max-extra-tickers", type=int, default=2)
    p.add_argument("--spy-qqq-only", action="store_true", help="12 anchors only (no DB ticker discovery)")
    p.add_argument("--max-anchors", type=int, default=None, help="Limit anchor count (first N, stable order)")
    register_allow_noncanonical_flag(p)
    args = p.parse_args()
    require_canonical_db_target(args, tool_name="tools.similarity_feature_survivorship_report", write_capable=False)

    db = EdDB(
        args.db,
        allow_noncanonical=bool(getattr(args, "allow_noncanonical_db", False)),
    )
    extra: list[str] = []
    if not args.spy_qqq_only:
        extra = discover_tickers_for_survivorship(
            db, min_rows=args.min_rows_ticker, max_extra=args.max_extra_tickers
        )
    anchors = default_multi_anchor_set_v1(extra_tickers=extra)
    if args.max_anchors is not None:
        anchors = anchors[: max(1, args.max_anchors)]
    report = run_multi_anchor_survivorship(
        db,
        anchors=anchors,
        n_similar=args.n_similar,
        candidate_pool_cap=args.candidate_pool_cap,
        top_k=args.top_k,
    )
    structure = final_structure_from_survivorship(report)
    confidence = overall_confidence(report)

    out = {
        "schema": "similarity_feature_survivorship_report_bundle_v1",
        "production_authority_unchanged": True,
        "overall_confidence": confidence,
        "anchors_used": anchors,
        "survivorship": report,
        "final_structure": structure,
    }
    args.output.write_text(json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")
    print(args.output, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
