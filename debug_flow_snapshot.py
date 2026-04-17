#!/usr/bin/env python3
"""
Print near-ATM flow inputs and stored vs recomputed flow_imbalance for one snapshot.

  python debug_flow_snapshot.py 12345
  python debug_flow_snapshot.py --latest SPY
"""
from __future__ import annotations

from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from calibration.paths import DEFAULT_DB
from db import get_snapshot_sql


import argparse
import json
import sqlite3
from pathlib import Path

from math_exposure_core import compute_exposures_by_strike
from math_probabilities import (
    atm_flow_window_totals,
    flow_imbalance_normalized_with_fallback,
)

from timeframe_config import CANONICAL_TIMEFRAME

ROOT = Path(__file__).resolve().parent
WINDOW = 5.0


def _contracts_from_chain_json(raw: str) -> list[dict]:
    try:
        arr = json.loads(raw)
    except Exception:
        return []
    if not isinstance(arr, list):
        return []
    out: list[dict] = []
    for ct in arr:
        if not isinstance(ct, dict):
            continue
        out.append(
            {
                "strikePrice": ct.get("strikePrice"),
                "putCall": ct.get("putCall"),
                "openInterest": ct.get("openInterest"),
                "totalVolume": ct.get("totalVolume") or ct.get("volume") or 0,
                "bidSize": ct.get("bidSize"),
                "askSize": ct.get("askSize"),
                "delta": ct.get("delta"),
                "gamma": ct.get("gamma"),
                "vega": ct.get("vega"),
                "volatility": ct.get("volatility"),
                "daysToExpiration": ct.get("daysToExpiration"),
                "multiplier": ct.get("multiplier") or 100,
                "expirationDate": ct.get("expirationDate"),
            }
        )
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Inspect flow_imbalance inputs for one snapshot")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("snapshot_id", nargs="?", type=int, help="snapshots.snapshot_id")
    g.add_argument("--latest", metavar="TICKER", help="Newest row for ticker (by snapshot_id)")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="debug_flow_snapshot", write_capable=False)

    conn = sqlite3.connect(str(args.db))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    if args.latest:
        row = cur.execute(
            get_snapshot_sql("debug_flow_snapshot.py:71"),
            (args.latest.upper(), CANONICAL_TIMEFRAME),
        ).fetchone()
    else:
        row = cur.execute(
            get_snapshot_sql("debug_flow_snapshot.py:83"),
            (args.snapshot_id,),
        ).fetchone()
    conn.close()

    if not row:
        raise SystemExit("Snapshot not found.")

    sid = int(row["snapshot_id"])
    spot = float(row["spot"]) if row["spot"] is not None else None
    raw = row["option_chain_json"]
    print(f"snapshot_id={sid}  ticker={row['ticker']}  ts_et={row['ts_et']}")
    print(f"spot={spot}")
    print(f"db flow_imbalance={row['flow_imbalance']}  smart_money_score={row['smart_money_score']}  direction={row['smart_money_direction']}")

    if not raw or len(raw) < 20:
        print("option_chain_json: missing or too short")
        return

    contracts = _contracts_from_chain_json(raw)
    print(f"contracts in chain json: {len(contracts)}")
    if spot is None or spot <= 0:
        print("spot invalid — skip recompute")
        return

    exposures, _diag = compute_exposures_by_strike(contracts, spot=spot, require_oi=False)
    sums = atm_flow_window_totals(exposures, spot, window_pts=WINDOW)
    flow_re, src = flow_imbalance_normalized_with_fallback(exposures, spot, window_pts=WINDOW)

    print(f"ATM window +/-{WINDOW:g} pt — strikes_in_window={sums['strikes_in_window']}")
    print(
        "  call_vol={:.0f}  put_vol={:.0f}".format(
            float(sums["call_vol"]), float(sums["put_vol"])
        )
    )
    print(
        "  call_bid={:.0f}  call_ask={:.0f}  put_bid={:.0f}  put_ask={:.0f}".format(
            float(sums["call_bid"]),
            float(sums["call_ask"]),
            float(sums["put_bid"]),
            float(sums["put_ask"]),
        )
    )
    print(f"recomputed flow_imbalance={flow_re}  source={src}")
    if row["flow_imbalance"] is not None:
        try:
            db_f = float(row["flow_imbalance"])
            if abs(db_f - flow_re) > 0.011:
                print(f"note: db vs recompute differ by {db_f - flow_re:.3f}")
        except (TypeError, ValueError):
            pass


if __name__ == "__main__":
    main()
