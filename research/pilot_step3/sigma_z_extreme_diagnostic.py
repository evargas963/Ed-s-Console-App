#!/usr/bin/env python3
"""
Pipeline validation: log bars with σ < 1e-6 or |z| > 100 (pilot staging / canonical).

Does not modify event_generation, prereg thresholds, k, h, or filters.
Reads the same prereg span/k as generate_events for CUSUM state mirroring.

Usage:
  python -m research.pilot_step3.sigma_z_extreme_diagnostic \\
    --db data/ed_console.db --batch-id spy_staging_pilot_30d_v1

Writes CSV under research/pilot_step3/diagnostics/ and prints summary tables.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import numpy as np

from app.domain.time_et import ET as _ET

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from research.pilot_step3 import pilot_config
from research.pilot_step3.data_loader import load_spy_1m_bars
from research.pilot_step3.event_generation import (
    _et_calendar_key,
    _et_minute_of_day_from_start,
    _in_first_30min_rth,
    build_sigma_for_cusum,
)

SIGMA_EXTREME = 1e-6
Z_EXTREME = 100.0


def _et_ts_str(ts_utc: float) -> str:
    dt = datetime.fromtimestamp(float(ts_utc), tz=timezone.utc).astimezone(_ET)
    return dt.strftime("%Y-%m-%d %H:%M:%S %Z")


def main() -> int:
    ap = argparse.ArgumentParser(description="σ/z extreme-bar diagnostic (pilot pipeline validation)")
    ap.add_argument("--db", default=None, help="SQLite path (default: db.DB_PATH)")
    ap.add_argument(
        "--source-table",
        default="price_bars_1m_staging",
        choices=["price_bars_1m", "price_bars_1m_staging"],
    )
    ap.add_argument("--batch-id", default=None, help="Required for staging")
    ap.add_argument("--ticker", default=None, help="Override instrument (default from prereg)")
    args = ap.parse_args()

    try:
        from db import DB_PATH
    except Exception:
        DB_PATH = None  # type: ignore[misc, assignment]

    db_path = args.db or (str(DB_PATH) if DB_PATH else None)
    if not db_path:
        print("Need --db or db.DB_PATH", file=sys.stderr)
        return 2
    if args.source_table == "price_bars_1m_staging" and not (args.batch_id or "").strip():
        print("--batch-id required for staging", file=sys.stderr)
        return 2

    prereg = pilot_config.load_prereg()
    ticker = (args.ticker or prereg["instrument"]["ticker"]).strip()
    cg = prereg["candidate_generator"]
    k = float(cg["cusum"]["k"])

    rep = load_spy_1m_bars(
        db_path,
        ticker=ticker,
        source_table=args.source_table,
        batch_id=(args.batch_id or "").strip() or None,
    )
    bars = rep.bars
    if len(bars) < 2:
        print("Not enough bars", file=sys.stderr)
        return 3

    closes = np.array([b.close for b in bars], dtype=float)
    starts = np.array([b.bar_start_ts_utc for b in bars], dtype=float)
    day_keys = np.array([_et_calendar_key(float(t)) for t in starts])

    sigma = build_sigma_for_cusum(closes, starts, cg)
    rets = np.zeros(len(closes), dtype=float)
    rets[1:] = (closes[1:] - closes[:-1]) / np.maximum(closes[:-1], 1e-12)

    pos = neg = 0.0
    extreme_rows: list[dict] = []
    # Full-population stats (i >= 1)
    sig_finite_pos: list[float] = []
    z_finite: list[float] = []

    for i in range(1, len(bars)):
        sig = float(sigma[i])
        r = float(rets[i])
        z = float(r / sig) if (np.isfinite(sig) and sig > 0) else float("nan")
        session_start = day_keys[i] != day_keys[i - 1]
        mod = _et_minute_of_day_from_start(starts[i])
        in_first = _in_first_30min_rth(starts[i])

        if np.isfinite(sig) and sig > 0:
            sig_finite_pos.append(sig)
            if np.isfinite(z):
                z_finite.append(z)

        if not np.isfinite(sig) or sig <= 0:
            pos_after = pos
            neg_after = neg
            reason_parts: list[str] = []
            if np.isfinite(sig) and sig < SIGMA_EXTREME:
                reason_parts.append("sigma_lt_1e6")
            if np.isfinite(z) and abs(z) > Z_EXTREME:
                reason_parts.append("abs_z_gt_100")
            if reason_parts:
                extreme_rows.append(
                    {
                        "bar_index": i,
                        "bar_start_ts_utc": float(starts[i]),
                        "et_timestamp": _et_ts_str(starts[i]),
                        "et_date": day_keys[i],
                        "minute_of_day": mod,
                        "session_et_day_start": str(session_start).lower(),
                        "r": r,
                        "sigma": sig,
                        "z": z,
                        "cusum_pos_after": pos_after,
                        "cusum_neg_after": neg_after,
                        "in_first_30min_rth": str(in_first).lower(),
                        "extreme_reason": "|".join(reason_parts),
                    }
                )
            continue

        z = r / sig
        pos = max(0.0, pos + z - k)
        neg = max(0.0, neg - z - k)
        pos_after, neg_after = pos, neg

        reasons: list[str] = []
        if sig < SIGMA_EXTREME:
            reasons.append("sigma_lt_1e6")
        if abs(z) > Z_EXTREME:
            reasons.append("abs_z_gt_100")
        if reasons:
            extreme_rows.append(
                {
                    "bar_index": i,
                    "bar_start_ts_utc": float(starts[i]),
                    "et_timestamp": _et_ts_str(starts[i]),
                    "et_date": day_keys[i],
                    "minute_of_day": mod,
                    "session_et_day_start": str(session_start).lower(),
                    "r": r,
                    "sigma": sig,
                    "z": z,
                    "cusum_pos_after": pos_after,
                    "cusum_neg_after": neg_after,
                    "in_first_30min_rth": str(in_first).lower(),
                    "extreme_reason": "|".join(reasons),
                }
            )

    out_dir = Path(__file__).resolve().parent / "diagnostics"
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "sigma_z_extreme_bars.csv"
    if extreme_rows:
        fields = list(extreme_rows[0].keys())
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(extreme_rows)

    # --- A. sigma distribution (finite, >0) ---
    sg = np.array(sig_finite_pos, dtype=float)
    print("=== A. Sigma distribution (all bars i>=1 with finite sigma>0) ===")
    print("n", len(sg))
    if len(sg):
        qs = [0, 1, 5, 10, 25, 50, 75, 90, 95, 99, 100]
        pct = np.percentile(sg, qs)
        for q, v in zip(qs, pct):
            print(f"  p{q:3d}: {v:.6e}")
        print(f"  min: {float(np.min(sg)):.6e}  max: {float(np.max(sg)):.6e}")
        hist_bins = [0, 1e-8, 1e-7, 1e-6, 1e-5, 1e-4, 1e-3, 1e-2, 1e-1, 10.0]
        h, edges = np.histogram(sg, bins=hist_bins)
        print("  histogram (right-inclusive bin edges):")
        for c, lo, hi in zip(h, edges[:-1], edges[1:]):
            print(f"    ({lo:.0e}, {hi:.0e}]: {int(c)}")

    # --- B. z distribution (finite z on same bars as above population) ---
    zv = np.array(z_finite, dtype=float)
    print("\n=== B. z-score distribution (finite z where sigma finite>0) ===")
    print("n", len(zv))
    if len(zv):
        qs = [0, 1, 5, 25, 50, 75, 95, 99, 100]
        pct = np.percentile(np.abs(zv), qs)
        print("  |z| percentiles:")
        for q, v in zip(qs, pct):
            print(f"  p{q:3d}: {v:.6e}")
        print(f"  min(z): {float(np.min(zv)):.6e}  max(z): {float(np.max(zv)):.6e}")

    # --- C. extreme z by minute-of-day (|z|>100 only) ---
    extreme_z_mods = [int(r["minute_of_day"]) for r in extreme_rows if "abs_z_gt_100" in r["extreme_reason"]]
    print("\n=== C. Count of |z|>100 events by minute-of-day (ET) ===")
    cz = Counter(extreme_z_mods)
    for mod in sorted(cz.keys()):
        print(f"  mod {mod:4d}: {cz[mod]}")

    # --- D. % extreme z in first 30 min ---
    ez = [r for r in extreme_rows if "abs_z_gt_100" in r["extreme_reason"]]
    n_ez = len(ez)
    n_ez_f30 = sum(1 for r in ez if r["in_first_30min_rth"] == "true")
    print("\n=== D. |z|>100 in first 30 min RTH ===")
    if n_ez:
        pct_f30 = 100.0 * n_ez_f30 / n_ez
        print(f"  count |z|>100: {n_ez}")
        print(f"  in_first_30min: {n_ez_f30}  ({pct_f30:.1f}%)")
    else:
        print("  (no |z|>100 rows)")

    # sigma_lt only without huge z
    print("\n=== D2. sigma < 1e-6 rows: first-30 share ===")
    sl = [r for r in extreme_rows if "sigma_lt_1e6" in r["extreme_reason"]]
    if sl:
        f30 = sum(1 for r in sl if r["in_first_30min_rth"] == "true")
        print(f"  count sigma<1e-6: {len(sl)}  in_first_30min: {f30} ({100*f30/len(sl):.1f}%)")

    # --- E. top 20 |z| ---
    print("\n=== E. Top 20 by |z| (among logged extreme rows) ===")
    ranked = sorted(extreme_rows, key=lambda r: abs(float(r["z"])) if np.isfinite(r["z"]) else 0.0, reverse=True)[:20]
    for r in ranked:
        print(
            f"  idx={r['bar_index']:5d} {r['et_timestamp']} mod={r['minute_of_day']} "
            f"sig={r['sigma']:.6e} z={r['z']:.4e} r={r['r']:.6e} "
            f"pos={r['cusum_pos_after']:.4e} neg={r['cusum_neg_after']:.4e} "
            f"first30={r['in_first_30min_rth']} day_start={r['session_et_day_start']} {r['extreme_reason']}"
        )

    print(f"\nCSV written: {csv_path}  rows={len(extreme_rows)}")
    print(
        "\n=== Root cause (hypothesis) ===\n"
        "Sigma collapse + session reset at open: see if sigma<1e-6 and |z|>100 cluster at\n"
        "minute_of_day=570 (09:30) with session_et_day_start=true and first30=true."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
