#!/usr/bin/env python3
"""Consolidate split-brain active layout into canonical active_{hz}/{T}/ trees (PR3 P2-3)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

DEFAULT_CORE = ("SPY", "QQQ", "IWM")


def _parse_tickers(raw: str | None) -> list[str]:
    if raw is None or raw.strip() == "":
        return list(DEFAULT_CORE)
    return [t.strip().upper() for t in raw.split(",") if t.strip()]


def main(argv: list[str] | None = None) -> int:
    from active_bundle_contract import (
        apply_consolidate_horizon_layout_plan,
        consolidate_horizon_layout_plan,
    )
    from ml_horizon import PRIMARY_DECISION_HORIZONS

    ap = argparse.ArgumentParser(
        description=(
            "Move misplaced horizon bundle files into canonical models/active_{hz}/{T}/ "
            "(1c → models/active/{T}/). Default tickers: SPY, QQQ, IWM."
        )
    )
    ap.add_argument(
        "--tickers",
        default=",".join(DEFAULT_CORE),
        help="Comma-separated tickers (default: SPY,QQQ,IWM)",
    )
    ap.add_argument(
        "--models-dir",
        type=Path,
        default=APP_DIR / "models",
        help="Models root (default: project models/)",
    )
    ap.add_argument(
        "--apply",
        action="store_true",
        help="Copy files into canonical dirs (default: dry-run plan only)",
    )
    ap.add_argument(
        "--remove-legacy-copies",
        action="store_true",
        help="When --apply, delete source files after successful copy",
    )
    ap.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON plan to stdout",
    )
    args = ap.parse_args(argv)

    tickers = _parse_tickers(args.tickers)
    models_dir = args.models_dir.resolve()
    all_plans: list[dict] = []
    total_moves = 0

    for ticker in tickers:
        for hz in PRIMARY_DECISION_HORIZONS:
            plan = consolidate_horizon_layout_plan(ticker, hz, models_dir=models_dir)
            moves = plan.get("moves") or []
            total_moves += len(moves)
            all_plans.append(plan)
            if args.json:
                continue
            if not moves:
                print(f"{ticker} {hz}: canonical OK (no moves)")
                continue
            print(f"{ticker} {hz}: {len(moves)} file(s) to consolidate → {plan['canonical_dir']}")
            for m in moves:
                print(f"  {m['file']}: {m['from']} → {m['to']}")

    if args.json:
        print(json.dumps({"tickers": tickers, "plans": all_plans, "move_count": total_moves}, indent=2))
        return 0

    if not args.apply:
        print(f"\nDry-run complete: {total_moves} move(s). Re-run with --apply to copy.")
        return 0

    copied_total = 0
    for plan in all_plans:
        copied = apply_consolidate_horizon_layout_plan(
            plan,
            remove_from_legacy=bool(args.remove_legacy_copies),
        )
        copied_total += len(copied)

    print(f"Applied {copied_total} file copy(ies) across {len(tickers)} ticker(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
