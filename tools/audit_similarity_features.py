#!/usr/bin/env python3
"""
Developer audit: feature contract + ablation impact for tier-driven similarity (analysis only).

Does not change production get_similar_setups. Outputs JSON to stdout.

Example:
  python tools/audit_similarity_features.py --db data/ed_console.db \\
    --ticker SPY --zone pin_neutral --vwap-side above --nad 1.0 --nbd -1.0

  python tools/audit_similarity_features.py --emit-contract verification/similarity_feature_contract_v1.json
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
from verification.similarity_feature_audit import (  # noqa: E402
    emit_contract_json,
    run_feature_impact_audit,
)


def main() -> int:
    p = argparse.ArgumentParser(description="Similarity feature audit (non-authoritative)")
    p.add_argument("--emit-contract", type=Path, default=None, help="Write baseline_feature_contract_v1 JSON to path")
    p.add_argument("--db", type=Path, default=DB_PATH)
    p.add_argument("--ticker", default="SPY")
    p.add_argument("--timeframe", default="1m")
    p.add_argument("--zone", default="pin_neutral")
    p.add_argument("--vwap-side", default="above", dest="vwap_side")
    p.add_argument("--nad", type=float, default=None)
    p.add_argument("--nbd", type=float, default=None)
    p.add_argument("--n-similar", type=int, default=500)
    p.add_argument("--as-of-ts-utc", type=float, default=None)
    register_allow_noncanonical_flag(p)
    args = p.parse_args()

    if args.emit_contract is not None:
        emit_contract_json(args.emit_contract)
        print(args.emit_contract, file=sys.stderr)
        return 0

    require_canonical_db_target(args, tool_name="tools.audit_similarity_features", write_capable=False)
    db = EdDB(
        args.db,
        allow_noncanonical=bool(getattr(args, "allow_noncanonical_db", False)),
    )
    report = run_feature_impact_audit(
        db,
        ticker=args.ticker.upper(),
        timeframe=args.timeframe,
        zone=args.zone,
        vwap_side=args.vwap_side,
        nearest_above_dist=args.nad,
        nearest_below_dist=args.nbd,
        n_similar=args.n_similar,
        as_of_ts_utc=args.as_of_ts_utc,
    )
    json.dump(report, sys.stdout, indent=2, default=str)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
