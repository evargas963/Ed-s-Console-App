#!/usr/bin/env python3
"""
Issue 21 — read-only inspection of tier-driven similar-set selection.

**Default (canonical):** similarity SQL parameters are built only from canonical MVP features
(``--canonical-features-json``) or from a DB snapshot row (``--db-row-json``) via the same
adapters as production/replay — no parallel legacy semantic path.

**raw-sql-debug:** explicit non-semantic mode that passes zone/vwap/distances directly to
``get_similar_setups``. Output is stamped so it cannot be mistaken for canonical analysis.
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
from db import DB_PATH, EdDB  # noqa: E402
from similarity_audit import (  # noqa: E402
    build_similar_inspection_bundle,
    similarity_trace_machine_summary,
    validate_selected_rows_match_tier,
)


def _run_inspection(
    db: EdDB,
    *,
    ticker: str,
    timeframe: str,
    zone: str,
    vwap_side: str,
    nearest_above_dist: float | None,
    nearest_below_dist: float | None,
    max_rows: int,
    validate_rows: bool,
    mode_tag: str,
    mode_warning: str | None = None,
) -> dict:
    similar, trace = db.get_similar_setups(
        ticker=ticker.upper(),
        timeframe=timeframe,
        zone=zone,
        vwap_side=vwap_side,
        nearest_above_dist=nearest_above_dist,
        nearest_below_dist=nearest_below_dist,
        return_trace=True,
    )
    tier = int(trace.get("chosen_tier") or 0)
    out: dict = {
        "mode": mode_tag,
        "mode_warning": mode_warning,
        "machine_summary": similarity_trace_machine_summary(trace),
        "inspection": build_similar_inspection_bundle(similar, trace, max_rows=max_rows),
        "full_trace": trace,
    }
    if validate_rows:
        ctx = trace.get("query_context") or {}
        out["row_constraint_audit"] = validate_selected_rows_match_tier(similar, tier, ctx)
    return out


def _cmd_canonical(args: argparse.Namespace) -> int:
    require_canonical_db_target(args, tool_name="tools.inspect_similar_set", write_capable=False)
    from features.fusion_model_input import (
        FusionModelInputError,
        similar_setup_filters_from_canonical_features,
        similar_setup_filters_from_db_snapshot_row,
    )

    if args.canonical_features_json:
        feats = json.loads(Path(args.canonical_features_json).read_text(encoding="utf-8"))
        if not isinstance(feats, dict):
            print("canonical-features-json must be a JSON object (MVP feature dict)", file=sys.stderr)
            return 2
        f = similar_setup_filters_from_canonical_features(feats)
    elif args.db_row_json:
        row = json.loads(Path(args.db_row_json).read_text(encoding="utf-8"))
        if not isinstance(row, dict):
            print("db-row-json must be a JSON object (DB snapshot row)", file=sys.stderr)
            return 2
        try:
            f = similar_setup_filters_from_db_snapshot_row(row)
        except FusionModelInputError as e:
            print(f"FusionModelInputError: {e}", file=sys.stderr)
            return 2
    else:
        print("Specify --canonical-features-json or --db-row-json", file=sys.stderr)
        return 2

    db = EdDB(
        args.db,
        allow_noncanonical=bool(getattr(args, "allow_noncanonical_db", False)),
    )
    out = _run_inspection(
        db,
        ticker=args.ticker,
        timeframe=args.timeframe,
        zone=f["zone"],
        vwap_side=f["vwap_side"],
        nearest_above_dist=f["nearest_above_dist"],
        nearest_below_dist=f["nearest_below_dist"],
        max_rows=args.max_rows,
        validate_rows=args.validate_rows,
        mode_tag="CANONICAL_MVP_FILTERS",
        mode_warning=None,
    )
    json.dump(out, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")
    return 0


def _cmd_raw_sql_debug(args: argparse.Namespace) -> int:
    require_canonical_db_target(args, tool_name="tools.inspect_similar_set", write_capable=False)
    db = EdDB(
        args.db,
        allow_noncanonical=bool(getattr(args, "allow_noncanonical_db", False)),
    )
    out = _run_inspection(
        db,
        ticker=args.ticker,
        timeframe=args.timeframe,
        zone=args.zone,
        vwap_side=args.vwap_side,
        nearest_above_dist=args.nad,
        nearest_below_dist=args.nbd,
        max_rows=args.max_rows,
        validate_rows=args.validate_rows,
        mode_tag="RAW_SQL_DEBUG_NON_SEMANTIC",
        mode_warning=(
            "Parameters were passed directly to get_similar_setups without canonical MVP "
            "coercion. Do not compare to production or replay semantics."
        ),
    )
    json.dump(out, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        description="Inspect similar-set tier trace + rows (Issue 21). "
        "Default: canonical MVP filters only. Use raw-sql-debug for legacy SQL probes.",
    )
    register_allow_noncanonical_flag(p)
    sub = p.add_subparsers(dest="command", required=True)

    c = sub.add_parser(
        "canonical",
        help="Build filters from canonical MVP JSON or DB row JSON (production/replay truth path).",
    )
    c.add_argument("--db", type=Path, default=DB_PATH, help="SQLite path")
    c.add_argument("--ticker", required=True)
    c.add_argument("--timeframe", default="1m")
    c.add_argument(
        "--canonical-features-json",
        type=str,
        default=None,
        help="Path to JSON dict: MVP canonical feature names → values",
    )
    c.add_argument(
        "--db-row-json",
        type=str,
        default=None,
        help="Path to JSON dict: DB snapshot row (uses similar_setup_filters_from_db_snapshot_row)",
    )
    c.add_argument("--max-rows", type=int, default=50)
    c.add_argument("--validate-rows", action="store_true")
    c.set_defaults(func=_cmd_canonical)

    r = sub.add_parser(
        "raw-sql-debug",
        help="Pass zone/vwap/distances directly to SQL (non-semantic; hypothesis testing only).",
    )
    r.add_argument("--db", type=Path, default=DB_PATH)
    r.add_argument("--ticker", required=True)
    r.add_argument("--timeframe", default="1m")
    r.add_argument("--zone", default="unknown")
    r.add_argument("--vwap-side", default="above", dest="vwap_side")
    r.add_argument("--nad", type=float, default=None)
    r.add_argument("--nbd", type=float, default=None)
    r.add_argument("--max-rows", type=int, default=50)
    r.add_argument("--validate-rows", action="store_true")
    r.set_defaults(func=_cmd_raw_sql_debug)

    args = p.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
