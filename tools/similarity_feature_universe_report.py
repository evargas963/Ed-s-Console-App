#!/usr/bin/env python3
"""
Developer-facing JSON report: full similarity feature universe + staged shadow search.

Analysis only — does not change get_similar_setups, Issue 19/20/21/22 behavior.

Example:
  python tools/similarity_feature_universe_report.py --db data/ed_console.db \\
    --ticker SPY --zone pin_neutral --vwap-side above --nad 1.0 --nbd -1.0
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
from db import EdDB  # noqa: E402
from similarity_feature_search import (  # noqa: E402
    analyze_baseline_feature_outcome_divergence,
    latest_snapshot_as_anchor_overlay,
    run_staged_shadow_search,
    synthesize_per_feature_recommendations,
)
from similarity_feature_universe import (  # noqa: E402
    build_feature_universe_inventory_v1,
    sqlite_snapshot_column_names,
)
from timeframe_config import CANONICAL_TIMEFRAME  # noqa: E402


def build_report(
    db: EdDB,
    *,
    ticker: str,
    timeframe: str,
    zone: str,
    vwap_side: str,
    nearest_above_dist: float | None,
    nearest_below_dist: float | None,
    skip_search: bool,
    skip_divergence: bool,
    n_similar: int,
    candidate_pool_cap: int,
    no_anchor_overlay: bool,
) -> dict:
    cols = sqlite_snapshot_column_names(db)
    inv = build_feature_universe_inventory_v1(sqlite_columns=cols)
    overlay = {} if no_anchor_overlay else latest_snapshot_as_anchor_overlay(db, ticker, timeframe)
    staged = {"schema": "skipped"}
    divergence = {"schema": "skipped"}
    if not skip_search:
        staged = run_staged_shadow_search(
            db,
            ticker=ticker,
            timeframe=timeframe,
            zone=zone,
            vwap_side=vwap_side,
            nearest_above_dist=nearest_above_dist,
            nearest_below_dist=nearest_below_dist,
            n_similar=n_similar,
            candidate_pool_cap=candidate_pool_cap,
            anchor_overlay=overlay or None,
            extra_soft_candidates=sorted(overlay.keys()) if overlay else None,
        )
    if not skip_divergence:
        divergence = analyze_baseline_feature_outcome_divergence(
            db, ticker=ticker, timeframe=timeframe
        )
    synth = synthesize_per_feature_recommendations(
        inv.get("partitions") or {},
        staged if not skip_search else {"trials": []},
        None if skip_divergence else divergence,
    )
    return {
        "schema": "similarity_feature_universe_report_v1",
        "production_authority_unchanged": True,
        "anchor_overlay_used": overlay,
        "feature_universe_inventory": inv,
        "staged_shadow_search": staged,
        "baseline_divergence_analysis": divergence,
        "per_feature_recommendations": synth,
        "suggested_next_adaptive_shadow_config": {
            "use_weight_bands": ["MEDIUM", "HIGH"],
            "ordering_presets_to_compare": sorted(
                __import__(
                    "adaptive_similarity_engine", fromlist=["ORDERING_PRESETS"]
                ).ORDERING_PRESETS.keys()
            ),
            "extra_soft_categorical_allowlist_note": (
                "Pass anchor_overlay from latest_snapshot_as_anchor_overlay for meaningful extra-soft trials."
            ),
            "cli": "python tools/adaptive_shadow_report.py --db ...",
        },
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Similarity feature universe + staged shadow report (JSON).")
    p.add_argument("--db", type=Path, default=DEFAULT_DB, help="Path to SQLite DB")
    p.add_argument("--ticker", required=True)
    p.add_argument("--timeframe", default=CANONICAL_TIMEFRAME)
    p.add_argument("--zone", required=True)
    p.add_argument("--vwap-side", required=True, dest="vwap_side")
    p.add_argument("--nad", type=float, default=None, dest="nearest_above_dist")
    p.add_argument("--nbd", type=float, default=None, dest="nearest_below_dist")
    p.add_argument("--n-similar", type=int, default=500)
    p.add_argument("--candidate-pool-cap", type=int, default=5000)
    p.add_argument("--skip-search", action="store_true")
    p.add_argument("--skip-divergence", action="store_true")
    p.add_argument("--no-anchor-overlay", action="store_true")
    p.add_argument("-o", "--output", help="Write JSON to file instead of stdout")
    register_allow_noncanonical_flag(p)
    args = p.parse_args()
    require_canonical_db_target(args, tool_name="tools.similarity_feature_universe_report", write_capable=False)

    db = EdDB(
        args.db,
        allow_noncanonical=bool(getattr(args, "allow_noncanonical_db", False)),
    )
    report = build_report(
        db,
        ticker=args.ticker,
        timeframe=args.timeframe,
        zone=args.zone,
        vwap_side=args.vwap_side,
        nearest_above_dist=args.nearest_above_dist,
        nearest_below_dist=args.nearest_below_dist,
        skip_search=args.skip_search,
        skip_divergence=args.skip_divergence,
        n_similar=args.n_similar,
        candidate_pool_cap=args.candidate_pool_cap,
        no_anchor_overlay=args.no_anchor_overlay,
    )
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
