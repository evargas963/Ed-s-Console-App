#!/usr/bin/env python3

# DEPRECATED — 7-horizon era (pre Phase D3 schema drop).
# Targets retired outcome_3c/8c/13c columns; do not run against post-D3 databases.
# Relocated to tools/legacy/horizon_7/ for audit history only.
"""
Phase 4C — prove real-time (stored governed labels) equals backfill (recompute from price_bars_1m).

- Same anchor / forward / classify logic as db._apply_bar_based_outcome_updates (BAR_ANCHOR_V1).
- Determinism: two independent passes per row must match (anchor, forward closes, derived outcomes).
- Order invariance: shuffle processing order; results identical when sorted by snapshot_id.
"""
from __future__ import annotations

import argparse
import bisect
import json
import random
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from horizon_outcomes import OUTCOME_BAR_SPECS, bar_complete_by_utc, forward_bar_start_utc  # noqa: E402
from math_exposure import classify_direction  # noqa: E402

DEFAULT_DB = ROOT / "data" / "ed_console.db"


def _load_bars(conn: sqlite3.Connection, ticker: str) -> tuple[list[float], list[float], dict[float, float]]:
    bar_end_rows = conn.execute(
        "SELECT bar_end_ts_utc, close FROM price_bars_1m WHERE ticker = ? ORDER BY bar_end_ts_utc ASC",
        (ticker,),
    ).fetchall()
    bar_ends = [float(r["bar_end_ts_utc"]) for r in bar_end_rows]
    bar_end_closes = [float(r["close"]) for r in bar_end_rows]
    close_by_start = {
        float(r["bar_start_ts_utc"]): float(r["close"])
        for r in conn.execute(
            "SELECT bar_start_ts_utc, close FROM price_bars_1m WHERE ticker = ?",
            (ticker,),
        ).fetchall()
    }
    return bar_ends, bar_end_closes, close_by_start


def _compute_row(
    *,
    ts_utc: float,
    bar_ends: list[float],
    bar_end_closes: list[float],
    close_by_start: dict[float, float],
    tz_eval: float,
) -> dict[str, Any]:
    """Single BAR_ANCHOR_V1 row: anchor + per-horizon forward start/close/outcome (if completable)."""
    t_snap = float(ts_utc)
    anch_idx = bisect.bisect_right(bar_ends, t_snap) - 1
    if anch_idx < 0:
        return {"anchor_ok": False}
    anchor_close = bar_end_closes[anch_idx]
    anchor_bar_end = bar_ends[anch_idx]
    out: dict[str, Any] = {
        "anchor_ok": True,
        "anchor_close": anchor_close,
        "anchor_bar_end_ts_utc": anchor_bar_end,
        "horizons": {},
    }
    for odir, _opt, n_min in OUTCOME_BAR_SPECS:
        b_start = forward_bar_start_utc(t_snap, n_min)
        h: dict[str, Any] = {"forward_bar_start_ts_utc": b_start}
        if not bar_complete_by_utc(b_start, tz_eval):
            h["complete"] = False
            h["forward_close"] = None
            h["outcome"] = None
            h["pts"] = None
        else:
            fc = close_by_start.get(float(b_start))
            h["complete"] = True
            h["forward_close"] = fc
            if fc is None:
                h["outcome"] = None
                h["pts"] = None
            else:
                pts = float(fc) - float(anchor_close)
                h["outcome"] = classify_direction(pts, anchor_close)
                h["pts"] = round(pts, 4)
        out["horizons"][odir] = h
    return out


def _rows_close(a: float | None, b: float | None) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(float(a) - float(b)) <= 1e-9


def _same_compute(a: dict[str, Any], b: dict[str, Any]) -> bool:
    if a.get("anchor_ok") != b.get("anchor_ok"):
        return False
    if not a.get("anchor_ok"):
        return True
    if not _rows_close(a.get("anchor_close"), b.get("anchor_close")):
        return False
    if a.get("anchor_bar_end_ts_utc") != b.get("anchor_bar_end_ts_utc"):
        return False
    for odir in [s[0] for s in OUTCOME_BAR_SPECS]:
        h1 = a["horizons"][odir]
        h2 = b["horizons"][odir]
        if h1.get("forward_bar_start_ts_utc") != h2.get("forward_bar_start_ts_utc"):
            return False
        if not _rows_close(h1.get("forward_close"), h2.get("forward_close")):
            return False
        if h1.get("outcome") != h2.get("outcome"):
            return False
        if h1.get("pts") != h2.get("pts"):
            return False
    return True


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--skip-shuffle-test", action="store_true")
    args = ap.parse_args()
    db_path = args.db.resolve()
    tz_eval = time.time()

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    selection_sql = """
        SELECT snapshot_id, ticker, ts_utc, market_session,
               outcome_1c, outcome_3c, outcome_5c, outcome_8c, outcome_13c, outcome_15c, outcome_60c
        FROM snapshots
        WHERE timeframe = '1m'
          AND COALESCE(horizon_outcome_schema_version, 3) = 3
        ORDER BY snapshot_id
    """
    all_rows = conn.execute(selection_sql).fetchall()

    counts_by_ticker: dict[str, int] = {}
    counts_by_session: dict[str, int] = {}
    for r in all_rows:
        counts_by_ticker[r["ticker"]] = counts_by_ticker.get(r["ticker"], 0) + 1
        ms = r["market_session"] or "unknown"
        counts_by_session[ms] = counts_by_session.get(ms, 0) + 1

    bars_cache: dict[str, tuple[list[float], list[float], dict[float, float]]] = {}

    def get_bars(tkr: str):
        if tkr not in bars_cache:
            bars_cache[tkr] = _load_bars(conn, tkr)
        return bars_cache[tkr]

    outcome_cols = [s[0] for s in OUTCOME_BAR_SPECS]

    det_anchor_mism = 0
    det_fwd_mism = 0
    det_out_mism = 0
    stored_vs_bf_out = 0
    stored_vs_bf_by_h = {c: 0 for c in outcome_cols}

    examples: list[dict] = []

    # Pass A and Pass B: same function, compare (determinism)
    for r in all_rows:
        sid = int(r["snapshot_id"])
        tkr = r["ticker"]
        ts = float(r["ts_utc"])
        be, bec, cbs = get_bars(tkr)
        c1 = _compute_row(ts_utc=ts, bar_ends=be, bar_end_closes=bec, close_by_start=cbs, tz_eval=tz_eval)
        c2 = _compute_row(ts_utc=ts, bar_ends=be, bar_end_closes=bec, close_by_start=cbs, tz_eval=tz_eval)

        if c1.get("anchor_ok") != c2.get("anchor_ok"):
            det_anchor_mism += 1
            continue
        if not c1.get("anchor_ok"):
            continue
        if not _rows_close(c1["anchor_close"], c2["anchor_close"]):
            det_anchor_mism += 1
        if c1["anchor_bar_end_ts_utc"] != c2["anchor_bar_end_ts_utc"]:
            det_anchor_mism += 1

        for odir in outcome_cols:
            h1 = c1["horizons"][odir]
            h2 = c2["horizons"][odir]
            if h1["forward_bar_start_ts_utc"] != h2["forward_bar_start_ts_utc"]:
                det_fwd_mism += 1
            if not _rows_close(h1.get("forward_close"), h2.get("forward_close")):
                det_fwd_mism += 1
            if h1.get("outcome") != h2.get("outcome"):
                det_out_mism += 1
            st = r[odir]
            if st is not None and h1.get("outcome") is not None:
                if st != h1["outcome"]:
                    stored_vs_bf_out += 1
                    stored_vs_bf_by_h[odir] += 1
                    if len(examples) < 15:
                        examples.append(
                            {
                                "snapshot_id": sid,
                                "ticker": tkr,
                                "ts_utc": ts,
                                "horizon": odir,
                                "stored_outcome": st,
                                "recomputed_outcome": h1["outcome"],
                                "anchor_close": c1["anchor_close"],
                                "forward_close": h1.get("forward_close"),
                            }
                        )

    # Order invariance: shuffle row order, recompute, compare by snapshot_id
    shuffle_mism = 0
    if not args.skip_shuffle_test and all_rows:
        rng = random.Random(args.seed)
        shuffled = list(all_rows)
        rng.shuffle(shuffled)
        by_id: dict[int, dict] = {}
        for r in shuffled:
            sid = int(r["snapshot_id"])
            tkr = r["ticker"]
            ts = float(r["ts_utc"])
            be, bec, cbs = get_bars(tkr)
            by_id[sid] = _compute_row(
                ts_utc=ts, bar_ends=be, bar_end_closes=bec, close_by_start=cbs, tz_eval=tz_eval
            )
        for r in all_rows:
            sid = int(r["snapshot_id"])
            ts = float(r["ts_utc"])
            tkr = r["ticker"]
            be, bec, cbs = get_bars(tkr)
            ref = _compute_row(
                ts_utc=ts, bar_ends=be, bar_end_closes=bec, close_by_start=cbs, tz_eval=tz_eval
            )
            if not _same_compute(by_id[sid], ref):
                shuffle_mism += 1

    # Bar SELECT order invariance: close_by_start dict must match whether rows read ASC or DESC.
    bar_select_order_ok = True
    if all_rows:
        probe_ticker = max(counts_by_ticker, key=counts_by_ticker.get)
        asc_d = {
            float(r["bar_start_ts_utc"]): float(r["close"])
            for r in conn.execute(
                "SELECT bar_start_ts_utc, close FROM price_bars_1m WHERE ticker = ? ORDER BY bar_start_ts_utc ASC",
                (probe_ticker,),
            )
        }
        desc_d = {
            float(r["bar_start_ts_utc"]): float(r["close"])
            for r in conn.execute(
                "SELECT bar_start_ts_utc, close FROM price_bars_1m WHERE ticker = ? ORDER BY bar_start_ts_utc DESC",
                (probe_ticker,),
            )
        }
        bar_select_order_ok = asc_d == desc_d and len(asc_d) > 0

    conn.close()

    n = len(all_rows)
    out = {
        "phase": "4c_rt_vs_backfill_equivalence_v1",
        "db_path": str(db_path),
        "selection_sql": " ".join(selection_sql.split()),
        "tz_eval_utc_used_for_bar_complete": tz_eval,
        "total_rows_selected": n,
        "counts_by_ticker_top40": dict(
            sorted(counts_by_ticker.items(), key=lambda x: -x[1])[:40]
        ),
        "counts_by_market_session": counts_by_session,
        "determinism_double_compute": {
            "anchor_mismatches": det_anchor_mism,
            "forward_field_mismatches": det_fwd_mism,
            "derived_outcome_mismatches": det_out_mism,
        },
        "stored_snapshot_vs_recompute_from_bars": {
            "outcome_cell_mismatches": stored_vs_bf_out,
            "outcome_mismatches_by_horizon": stored_vs_bf_by_h,
        },
        "order_invariance_shuffled_recompute_mismatches": shuffle_mism,
        "bar_close_lookup_dict_invariant_to_select_order_spy": bar_select_order_ok,
        "example_stored_mismatches": examples,
    }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
