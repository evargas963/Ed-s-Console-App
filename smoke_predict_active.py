#!/usr/bin/env python3
"""
Smoke-test ML stack for every ticker under models/active using the latest DB snapshot.

Runs the same paths production uses:
  - predict_direction (stack: XGB + LSTM + Transformer + meta / weighted blend)
  - get_model_outputs_for_fusion (per-model availability + probs)

Uses the latest canonical 1m snapshot row only. If none exists, the ticker is skipped
with an explicit canonical-missing / unavailable state (no inference from timeframe='5m').

Does not modify the database or models. Read-only + inference.

Usage:
  python smoke_predict_active.py
  python smoke_predict_active.py --db data/other.db
  python smoke_predict_active.py --verbose
  python smoke_predict_active.py --tickers SPY,QQQ
"""
from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from calibration.paths import DEFAULT_DB

ROOT = Path(__file__).resolve().parent


def _tickers_from_active(models_root: Path) -> list[str]:
    from ml_horizon import live_inference_horizon_slug

    hz = live_inference_horizon_slug()
    active = models_root / "active"
    if not active.is_dir():
        return []
    out: list[str] = []
    for p in sorted(active.iterdir()):
        if not p.is_dir() or p.name.startswith("."):
            continue
        t = p.name
        has_any = (
            (p / f"xgb_{t}_{hz}.pkl").exists()
            or (p / f"lstm_{t}_{hz}.pt").exists()
            or (p / f"transformer_{t}_{hz}.pt").exists()
        )
        if has_any:
            out.append(t)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Smoke-test predict_direction for models/active tickers")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument(
        "--models-dir",
        type=Path,
        default=ROOT / "models",
        help="Parent of active/ (default: ./models)",
    )
    ap.add_argument(
        "--tickers",
        type=str,
        default="",
        help="Comma-separated subset; default = all under models/active",
    )
    ap.add_argument("--verbose", action="store_true", help="Print tracebacks on errors")
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    require_canonical_db_target(args, tool_name="smoke_predict_active", write_capable=False)

    if not args.db.is_file():
        print(f"Database not found: {args.db}", file=sys.stderr)
        return 2

    tickers = _tickers_from_active(args.models_dir)
    if args.tickers.strip():
        raw = [x.strip() for x in args.tickers.split(",") if x.strip()]
        want_exact = set(raw)
        want_upper = {x.upper() for x in raw}
        tickers = [t for t in tickers if t in want_exact or t.upper() in want_upper]

    if not tickers:
        print("No tickers found under models/active with xgb/lstm/transformer artifacts.")
        return 1

    from timeframe_config import CANONICAL_TIMEFRAME
    from db import EdDB
    from ml_predict import (
        get_model_outputs_for_fusion,
        predict_direction,
        reset_caches,
    )

    reset_caches()
    db = EdDB(
        args.db,
        allow_noncanonical=bool(getattr(args, "allow_noncanonical_db", False)),
    )

    print(f"DB: {args.db}")
    print(f"Timeframe: {CANONICAL_TIMEFRAME} only (no non-1m inference base)")
    print(f"Tickers ({len(tickers)}): {', '.join(tickers)}\n")

    failures = 0
    for ticker in tickers:
        row = None
        try:
            rows = db.get_recent_snapshots(ticker, CANONICAL_TIMEFRAME, n=1)
            if not rows:
                print(
                    f"  {ticker:8} SKIP  CANONICAL_SNAPSHOT_MISSING  "
                    f"no row for timeframe={CANONICAL_TIMEFRAME!r} — inference unavailable"
                )
                failures += 1
                continue
            row = rows[0]
            from features.inference_snapshot import build_inference_snapshot_v1_from_db_row

            row_d = dict(row)
            inf_v1 = build_inference_snapshot_v1_from_db_row(
                ticker=ticker,
                expiry=None,
                as_of_ts=row_d.get("ts_utc"),
                db_row=row_d,
            )

            pred = predict_direction(row_d, ticker, db, inference_snapshot_v1=inf_v1)
            fusion = get_model_outputs_for_fusion(
                row_d, ticker, db, direction_hint="wait", inference_snapshot_v1=inf_v1
            )

            def _avail(name: str) -> str:
                block = fusion.get(name) if fusion else None
                if not block:
                    return "—"
                return "Y" if block.get("available") else "N"

            if pred is None:
                print(
                    f"  {ticker:8} PARTIAL  predict_direction=None  "
                    f"xgb={_avail('xgb')} lstm={_avail('lstm')} tr={_avail('transformer')}  tf={CANONICAL_TIMEFRAME}"
                )
                failures += 1
            else:
                print(
                    f"  {ticker:8} OK      "
                    f"up={pred.get('up')} dn={pred.get('down')} fl={pred.get('flat')}  "
                    f"xgb={_avail('xgb')} lstm={_avail('lstm')} tr={_avail('transformer')}  tf={CANONICAL_TIMEFRAME}"
                )
        except Exception as e:
            failures += 1
            print(f"  {ticker:8} FAIL    {e}")
            if args.verbose:
                traceback.print_exc()

    print()
    if failures:
        print(f"Done: {failures} ticker(s) with PARTIAL/FAIL (see above).")
        return 1
    print("Done: all runnable tickers returned a stacked prediction.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
