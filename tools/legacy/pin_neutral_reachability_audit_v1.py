#!/usr/bin/env python3
"""
Read-only evidence for pin_neutral reachability (Issue 19 / zone logic).

Does not mutate DB. See docs/issue19_pin_neutral_1m_reachability_audit.md.
"""
from __future__ import annotations

from db import get_snapshot_sql


import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from calibration.paths import DEFAULT_DB
from market_state import derive_zone
from timeframe_config import CANONICAL_TIMEFRAME


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--json-out", type=Path, default=None)
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="tools.pin_neutral_reachability_audit_v1", write_capable=False)
    conn = sqlite3.connect(str(args.db), timeout=60)
    conn.row_factory = sqlite3.Row
    now = time.time()

    def q1(sql: str, params: tuple = ()) -> int:
        r = conn.execute(sql, params).fetchone()
        return int(r[0]) if r and r[0] is not None else 0

    # Zone distribution on canonical 1m snapshots
    z1 = conn.execute(
        get_snapshot_sql("tools/pin_neutral_reachability_audit_v1.py:38"),
        (CANONICAL_TIMEFRAME,),
    ).fetchall()

    pin_1m = q1(
        get_snapshot_sql("tools/pin_neutral_reachability_audit_v1.py:pin_1m"),
        (CANONICAL_TIMEFRAME,),
    )
    pin_5m = q1(
        get_snapshot_sql("tools/pin_neutral_reachability_audit_v1.py:pin_5m"),
        (),
    )

    # derive_zone is ONLY a function of (bias_signal, net_delta) in production
    # Snapshots do not store bias_signal — cross-check partial: expansion path uses net_delta
    # Rows labeled pin_neutral should not be breakout/breakdown if bias were expansion with same nd
    # (incomplete without bias_signal)

    # Sanity: re-apply derive_zone for hypothetical biases (documentation / tests)
    samples = []
    for bias, nd in (
        ("Neutral", None),
        ("Balanced", 0.0),
        ("Bull", 100.0),
        ("Bear", -100.0),
        ("Expansion", 10.0),
        ("Expansion", -10.0),
        ("", None),
        ("unknown_bias_xyz", 1.0),
    ):
        samples.append(
            {
                "bias_signal": bias,
                "net_delta": nd,
                "derive_zone": derive_zone(bias, nd),
            }
        )

    # 1m snapshots: null greeks vs pin_neutral
    n1m_total = q1(
        get_snapshot_sql("tools/pin_neutral_reachability_audit_v1.py:n1m_total"),
        (CANONICAL_TIMEFRAME,),
    )
    pin_1m_null_g = q1(
        get_snapshot_sql("tools/pin_neutral_reachability_audit_v1.py:pin_1m_null_g"),
        (CANONICAL_TIMEFRAME,),
    )

    report = {
        "schema": "pin_neutral_reachability_audit_v1",
        "generated_ts_utc": now,
        "db_path": str(args.db.resolve()),
        "canonical_timeframe": CANONICAL_TIMEFRAME,
        "snapshots_1m_total": n1m_total,
        "pin_neutral_1m_count": pin_1m,
        "pin_neutral_5m_count": pin_5m,
        "zone_histogram_1m": [{"zone": r["z"], "count": int(r["n"])} for r in z1],
        "pin_neutral_1m_with_null_net_gamma_or_delta": pin_1m_null_g,
        "derive_zone_truth_table_samples": samples,
        "note": (
            "Zone on snapshots is ms.zone from server.py → derive_zone(consensus_summary.bias_signal, "
            "consensus_summary.net_delta). bias_signal comes from math_levels._bias_from_net which "
            "also depends on pin_strength (not stored on snapshots). OHLC / price_bars_1m do not "
            "enter derive_zone."
        ),
    }
    conn.close()
    text = json.dumps(report, indent=2) + "\n"
    print(text)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
