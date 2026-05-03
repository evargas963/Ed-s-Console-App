#!/usr/bin/env python3
"""
Before/after: legacy daily-reset sigma vs continuous+floor (same k, h, filters).

Usage:
  python -m research.pilot_step3.sigma_contract_compare_diagnostic \\
    --batch-id spy_staging_pilot_30d_v1
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from research.pilot_step3 import pilot_config
from research.pilot_step3.data_loader import load_spy_1m_bars
from research.pilot_step3.event_generation import (
    _et_minute_of_day_from_start,
    _ewm_std_by_rth_day_legacy,
    _in_first_30min_rth,
    build_sigma_for_cusum,
    generate_events,
    sma,
)

_ET = ZoneInfo("America/New_York")


def _instrument(
    bars,
    prereg: dict,
    *,
    sigma: np.ndarray,
) -> dict:
    cg = prereg["candidate_generator"]
    k = float(cg["cusum"]["k"])
    h = float(cg["cusum"]["h_threshold"])
    min_gap = int(cg["min_bar_gap"])
    exclude_first_30 = bool(cg.get("exclude_first_30min_rth", True))
    sma_fast_n = int(cg["sma"]["fast"])
    sma_slow_n = int(cg["sma"]["slow"])
    sma_tol = float(cg.get("sma", {}).get("near_equal_tolerance", 1e-9))

    closes = np.array([b.close for b in bars], dtype=float)
    starts = np.array([b.bar_start_ts_utc for b in bars], dtype=float)
    sma_f = sma(closes, sma_fast_n)
    sma_s = sma(closes, sma_slow_n)

    z_gt_100 = 0
    pos = neg = 0.0
    fire = 0
    emit = 0
    last_emit = -10**9
    event_mods: list[int] = []

    for i in range(1, len(bars)):
        sig = sigma[i]
        if not np.isfinite(sig) or sig <= 0:
            continue
        r = (closes[i] - closes[i - 1]) / max(closes[i - 1], 1e-12)
        z = r / sig
        if abs(z) > 100:
            z_gt_100 += 1
        pos = max(0.0, pos + z - k)
        neg = max(0.0, neg - z - k)
        if not (pos >= h or neg >= h):
            continue
        fire += 1
        if exclude_first_30 and _in_first_30min_rth(starts[i]):
            pos = neg = 0.0
            continue
        if i - last_emit < min_gap:
            pos = neg = 0.0
            continue
        if i + 1 >= len(bars):
            break
        sf, ss = sma_f[i], sma_s[i]
        if not (np.isfinite(sf) and np.isfinite(ss)):
            pos = neg = 0.0
            continue
        if abs(float(sf) - float(ss)) < sma_tol:
            pos = neg = 0.0
            continue
        emit += 1
        event_mods.append(_et_minute_of_day_from_start(starts[i]))
        last_emit = i
        pos = neg = 0.0

    return {
        "z_gt_100_count": z_gt_100,
        "fire_count": fire,
        "event_count": emit,
        "event_minute_hist_top": Counter(event_mods).most_common(12),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=None)
    ap.add_argument("--batch-id", default="spy_staging_pilot_30d_v1")
    ap.add_argument("--source-table", default="price_bars_1m_staging")
    args = ap.parse_args()
    try:
        from db import DB_PATH
    except Exception:
        DB_PATH = None  # type: ignore[misc, assignment]
    db_path = args.db or (str(DB_PATH) if DB_PATH else None)
    if not db_path:
        print("Need --db", file=sys.stderr)
        return 2

    prereg = pilot_config.load_prereg()
    ticker = prereg["instrument"]["ticker"]
    rep = load_spy_1m_bars(
        db_path,
        ticker=ticker,
        source_table=args.source_table,
        batch_id=args.batch_id.strip(),
    )
    bars = rep.bars
    cg = prereg["candidate_generator"]
    closes = np.array([b.close for b in bars], dtype=float)
    starts = np.array([b.bar_start_ts_utc for b in bars], dtype=float)
    span = int((cg.get("sigma_contract") or {}).get("ewm_span_bars", cg["ewm_span_bars"]))

    sigma_legacy = _ewm_std_by_rth_day_legacy(closes, starts, span=span)
    sigma_new = build_sigma_for_cusum(closes, starts, cg)

    leg = _instrument(bars, prereg, sigma=sigma_legacy)
    neu = _instrument(bars, prereg, sigma=sigma_new)

    ev_new, _ = generate_events(bars, prereg)
    assert neu["event_count"] == len(ev_new)

    out = {
        "n_rth_bars": len(bars),
        "batch_id": rep.batch_id,
        "legacy_daily_reset": leg,
        "continuous_rel_floor": neu,
    }
    print(json.dumps(out, indent=2))
    print("\n| metric              | legacy | new    |")
    print("|---------------------|--------|--------|")
    print(f"| z_gt_100_count      | {leg['z_gt_100_count']:6d} | {neu['z_gt_100_count']:6d} |")
    print(f"| fire_count          | {leg['fire_count']:6d} | {neu['fire_count']:6d} |")
    print(f"| event_count         | {leg['event_count']:6d} | {neu['event_count']:6d} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
