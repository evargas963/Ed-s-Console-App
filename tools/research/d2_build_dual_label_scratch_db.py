#!/usr/bin/env python3
"""
D2 dual-label backtest — scratch DB builder (research-only; operator-approved
mission D2_DUAL_LABEL_BACKTEST_EXECUTE, 2026-07-06).

Builds data/research/d2_dual_label.db from the production DB opened READ-ONLY
(sqlite URI mode=ro — mutation of the source is impossible by construction):

  1. Clones RTH-training-relevant ``snapshots`` columns (all columns EXCEPT the
     two heavy JSON blobs option_chain_json / replay_context_json) for the
     requested tickers, plus their full ``price_bars_1m`` series.
  2. Adds SCRATCH-ONLY triple-barrier label columns per horizon:
       outcome_tb_{hz} / tb_touch_{hz} / tb_barrier_pts_{hz} / tb_truncated_{hz}
  3. Fits k_hz per horizon on the chronological train split (first 80%% of
     pooled base-ticker rows) so the non-truncated no-touch share lands in the
     approved 25-35%% window (prior: k_base * sqrt(N/5)).
  4. Generates TB labels for every cloned row with a same-session RTH window:
       - symmetric barriers at anchor ± k_hz * ATR_row
       - vertical barrier at N one-minute bars
       - windows crossing the RTH close are truncated and flagged
         tb_truncated=1 (labels never span sessions)
       - ambiguous intrabar (both barriers in one bar): close-side resolution,
         tb_touch='ambiguous'
  5. Writes a manifest JSON next to the scratch DB.

Schwab CSV authority checked: yes
CSV row(s): NO_SCHWAB_EQUIVALENT — research label generation over persisted
  bars/snapshots in a scratch database; no production market field read,
  derivation, emission, or actionability logic changed.
Derived-field disposition: none required (research-only scratch outputs).
All consumers checked: yes — outputs live only in data/research/; production
  ed_console.db is opened mode=ro.
SCHWAB_CSV_CHECKED
"""
from __future__ import annotations

import argparse
import bisect
import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

HORIZONS = {"1c": 1, "5c": 5, "15c": 15, "60c": 60}
BASE_TICKERS = ("SPY", "QQQ", "IWM")
BLOB_COLUMNS = ("option_chain_json", "replay_context_json")
K_BASE_PRIOR = 0.9          # fitted downward/upward per horizon by the share search
NO_TOUCH_TARGET = 0.30      # approved window 0.25-0.35
NO_TOUCH_LO, NO_TOUCH_HI = 0.25, 0.35
TRAIN_FRACTION = 0.8        # chronological — k is fitted on the train split only
from time_et import RTH_END_MINS as RTH_END_MIN, RTH_START_MINS as RTH_START_MIN


def et_minutes(ts_utc: float) -> tuple[str, int]:
    """(et_date, minutes_since_midnight_et) via the canonical time_et authority
    (repo lock: only time_et.py may hold the NY ZoneInfo literal)."""
    from time_et import et_date_str_from_ts_utc, et_minute_total_from_ts_utc

    return et_date_str_from_ts_utc(float(ts_utc)), et_minute_total_from_ts_utc(float(ts_utc))


def tb_label_for_window(
    anchor_close: float,
    path_bars: list[tuple[float, float, float, float]],  # (start_ts, high, low, close)
    barrier_pts: float,
    n_bars_vertical: int,
) -> tuple[str, str, int]:
    """Pure triple-barrier core (unit-lockable).

    Returns (label, touch_type, truncated):
      label      up | down | flat
      touch_type pt_up | sl_down | ambiguous | vertical | vertical_truncated
      truncated  1 when the window ended before n_bars_vertical bars (session cut)
    Ambiguous policy (approved primary): both barriers inside one bar resolve to
    the bar-close side, touch_type='ambiguous'.
    """
    up_bar = anchor_close + barrier_pts
    dn_bar = anchor_close - barrier_pts
    for _ts, hi, lo, cl in path_bars:
        touch_up = hi >= up_bar
        touch_dn = lo <= dn_bar
        if touch_up and touch_dn:
            return ("up" if cl >= anchor_close else "down"), "ambiguous", 0
        if touch_up:
            return "up", "pt_up", 0
        if touch_dn:
            return "down", "sl_down", 0
    truncated = 1 if len(path_bars) < n_bars_vertical else 0
    return "flat", ("vertical_truncated" if truncated else "vertical"), truncated


class TickerBars:
    def __init__(self, rows: list[tuple]):
        # rows: (bar_start_ts_utc, bar_end_ts_utc, high, low, close) tuples
        self.start = [float(r[0]) for r in rows]
        self.end = [float(r[1]) for r in rows]
        self.high = [float(r[2]) for r in rows]
        self.low = [float(r[3]) for r in rows]
        self.close = [float(r[4]) for r in rows]

    def window(self, ts_utc: float, n_min: int):
        """(anchor_close, path_bars_same_session) or None when no anchor bar exists.

        Path = up to n_min bars strictly after the anchor bar, cut at the first
        bar that leaves the anchor's RTH session (date change or >= 16:00 ET).
        """
        ai = bisect.bisect_right(self.end, ts_utc) - 1
        if ai < 0:
            return None
        anchor_close = self.close[ai]
        anchor_date, _ = et_minutes(self.start[ai])
        path = []
        for j in range(ai + 1, min(ai + 1 + n_min, len(self.start))):
            if self.start[j] > self.start[ai] + n_min * 60:
                break
            d, m = et_minutes(self.start[j])
            if d != anchor_date or m >= RTH_END_MIN:
                break
            path.append((self.start[j], self.high[j], self.low[j], self.close[j]))
        return anchor_close, path


def fit_k_for_horizon(
    train_rows: list[tuple[float, float, "TickerBars"]], n_min: int
) -> dict:
    """Grid-search k so the NON-TRUNCATED no-touch share lands in [0.25, 0.35]."""
    prior = K_BASE_PRIOR * (n_min / 5.0) ** 0.5
    grid = sorted({round(prior * m, 4) for m in
                   (0.25, 0.4, 0.55, 0.7, 0.85, 1.0, 1.2, 1.45, 1.75, 2.1, 2.6, 3.2, 4.0)})
    best = None
    trace = []
    for k in grid:
        flat = 0
        n = 0
        for ts, atr, bars in train_rows:
            w = bars.window(ts, n_min)
            if w is None:
                continue
            anchor, path = w
            if len(path) < n_min:
                continue  # k-fit uses full (non-truncated) windows only
            lab, _touch, _tr = tb_label_for_window(anchor, path, k * atr, n_min)
            n += 1
            flat += lab == "flat"
        share = (flat / n) if n else None
        trace.append({"k": k, "n": n, "no_touch_share": None if share is None else round(share, 4)})
        if share is None:
            continue
        dist = abs(share - NO_TOUCH_TARGET)
        if best is None or dist < best[0]:
            best = (dist, k, share, n)
    _, k, share, n = best
    return {
        "k": k,
        "prior": round(prior, 4),
        "train_no_touch_share": round(share, 4),
        "in_target_window": bool(NO_TOUCH_LO <= share <= NO_TOUCH_HI),
        "n_fit_windows": n,
        "grid_trace": trace,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Build the D2 dual-label scratch DB")
    ap.add_argument("--src", type=Path, default=ROOT / "data" / "ed_console.db")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "research" / "d2_dual_label.db")
    ap.add_argument("--tickers", nargs="+", default=["SPY", "QQQ", "IWM", "AAPL", "TSLA"])
    args = ap.parse_args()

    t0 = time.time()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.out.exists():
        args.out.unlink()

    # READ-ONLY source: mutation of production is impossible on this handle.
    src = sqlite3.connect(f"file:{args.src.as_posix()}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    dst = sqlite3.connect(str(args.out))

    src_cols = [r["name"] for r in src.execute("PRAGMA table_info(snapshots)")]
    keep_cols = [c for c in src_cols if c not in BLOB_COLUMNS]
    tb_cols: list[str] = []
    for hz in HORIZONS:
        tb_cols += [
            f"outcome_tb_{hz} TEXT", f"tb_touch_{hz} TEXT",
            f"tb_barrier_pts_{hz} REAL", f"tb_truncated_{hz} INTEGER",
        ]
    col_defs = ", ".join([f'"{c}"' for c in keep_cols] + tb_cols)
    dst.execute(f"CREATE TABLE snapshots ({col_defs})")
    dst.execute(
        "CREATE TABLE price_bars_1m (ticker TEXT, bar_start_ts_utc REAL, bar_end_ts_utc REAL,"
        " open REAL, high REAL, low REAL, close REAL, volume REAL, source TEXT)"
    )

    ph = ",".join("?" * len(args.tickers))
    sel = ", ".join(f'"{c}"' for c in keep_cols)
    n_snap = 0
    for row in src.execute(
        f"SELECT {sel} FROM snapshots WHERE timeframe='1m' AND ticker IN ({ph})", args.tickers
    ):
        dst.execute(
            f"INSERT INTO snapshots ({sel}) VALUES ({','.join('?' * len(keep_cols))})",
            tuple(row),
        )
        n_snap += 1
    n_bars = 0
    for row in src.execute(
        f"SELECT ticker, bar_start_ts_utc, bar_end_ts_utc, open, high, low, close, volume, source"
        f" FROM price_bars_1m WHERE ticker IN ({ph})", args.tickers
    ):
        dst.execute("INSERT INTO price_bars_1m VALUES (?,?,?,?,?,?,?,?,?)", tuple(row))  # collect-window-ok: verbatim copy into isolated scratch DB data/research/d2_dual_label.db; source opened mode=ro (RC-183)
        n_bars += 1
    dst.commit()

    bars_by_ticker: dict[str, TickerBars] = {}
    for tkr in args.tickers:
        rows = list(dst.execute(
            "SELECT bar_start_ts_utc, bar_end_ts_utc, high, low, close FROM price_bars_1m"
            " WHERE ticker=? ORDER BY bar_start_ts_utc", (tkr,)))
        bars_by_ticker[tkr] = TickerBars(rows)

    # k-fit rows: pooled BASE tickers, RTH, ATR present, chronological first 80%.
    fit_manifest: dict = {}
    label_rows = list(dst.execute(
        "SELECT rowid, ticker, ts_utc, atr, et_hour, et_minute FROM snapshots"
        " WHERE atr IS NOT NULL ORDER BY ts_utc"))
    rth = [r for r in label_rows
           if r[4] is not None and RTH_START_MIN <= (r[4] * 60 + (r[5] or 0)) < RTH_END_MIN]
    base_rth = [r for r in rth if r[1] in BASE_TICKERS]
    n_train = int(len(base_rth) * TRAIN_FRACTION)
    train = base_rth[:n_train]
    for hz, n_min in HORIZONS.items():
        fit_rows = [(float(r[2]), float(r[3]), bars_by_ticker[r[1]]) for r in train]
        fit_manifest[hz] = fit_k_for_horizon(fit_rows, n_min)

    # Label generation for every RTH row with an in-session window.
    counts = {hz: {"labeled": 0, "truncated": 0, "ambiguous": 0,
                   "dist": {"up": 0, "down": 0, "flat": 0},
                   "agree_with_fixed": 0, "fixed_comparable": 0} for hz in HORIZONS}
    fixed_lookup_cols = {hz: f"outcome_{hz}" for hz in HORIZONS}
    upd_sql = {hz: (f"UPDATE snapshots SET outcome_tb_{hz}=?, tb_touch_{hz}=?,"
                    f" tb_barrier_pts_{hz}=?, tb_truncated_{hz}=? WHERE rowid=?")
               for hz in HORIZONS}
    for r in rth:
        rowid, tkr, ts, atr = r[0], r[1], float(r[2]), float(r[3])
        bars = bars_by_ticker[tkr]
        for hz, n_min in HORIZONS.items():
            k = fit_manifest[hz]["k"]
            w = bars.window(ts, n_min)
            if w is None:
                continue
            anchor, path = w
            if not path:
                continue
            barrier = k * atr
            lab, touch, trunc = tb_label_for_window(anchor, path, barrier, n_min)
            dst.execute(upd_sql[hz], (lab, touch, round(barrier, 6), trunc, rowid))
            c = counts[hz]
            c["labeled"] += 1
            c["truncated"] += trunc
            c["ambiguous"] += touch == "ambiguous"
            c["dist"][lab] += 1
            fixed = dst.execute(
                f"SELECT {fixed_lookup_cols[hz]} FROM snapshots WHERE rowid=?", (rowid,)
            ).fetchone()[0]
            if fixed in ("up", "down", "flat"):
                c["fixed_comparable"] += 1
                c["agree_with_fixed"] += fixed == lab
    dst.commit()

    per_ticker = {t: dst.execute("SELECT COUNT(*) FROM snapshots WHERE ticker=?", (t,)).fetchone()[0]
                  for t in args.tickers}
    manifest = {
        "schema": "d2_dual_label_scratch_v1",
        "built_at_utc": time.time(),
        "src": str(args.src),
        "src_opened": "sqlite_uri_mode_ro",
        "out": str(args.out),
        "tickers": list(args.tickers),
        "base_tickers": list(BASE_TICKERS),
        "excluded_blob_columns": list(BLOB_COLUMNS),
        "snapshots_cloned": n_snap,
        "bars_cloned": n_bars,
        "per_ticker_rows": per_ticker,
        "rth_rows_with_atr": len(rth),
        "k_fit_train_rows": n_train,
        "k_fit": {hz: {k: v for k, v in m.items() if k != "grid_trace"}
                  for hz, m in fit_manifest.items()},
        "k_fit_grid_trace": {hz: m["grid_trace"] for hz, m in fit_manifest.items()},
        "labels": {
            hz: {
                **{k: v for k, v in c.items() if k not in ("agree_with_fixed", "fixed_comparable")},
                "agreement_with_fixed_pct": (
                    round(100.0 * c["agree_with_fixed"] / c["fixed_comparable"], 1)
                    if c["fixed_comparable"] else None
                ),
            }
            for hz, c in counts.items()
        },
        "elapsed_s": round(time.time() - t0, 1),
    }
    # ── Scratch-only normalized carry (operator approval 2026-07-06) ─────────
    # Create snapshots_1m_normalized INSIDE THE SCRATCH DB from the production
    # DDL plus the 16 TB research columns, then run the UNCHANGED production
    # materializer against the scratch DB. The production normalizer's insert
    # list is the name-intersection of snapshots vs snapshots_1m_normalized
    # (snapshot_normalizer._normalized_insert_columns), so the TB columns are
    # carried automatically here and NEVER in production (whose normalized
    # table has no TB columns). Zero production code or schema change.
    ddl_row = src.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='snapshots_1m_normalized'"
    ).fetchone()
    if ddl_row and ddl_row["sql"]:
        dst.execute(ddl_row["sql"])
        for hz in HORIZONS:
            for cdef in (
                f"outcome_tb_{hz} TEXT", f"tb_touch_{hz} TEXT",
                f"tb_barrier_pts_{hz} REAL", f"tb_truncated_{hz} INTEGER",
            ):
                dst.execute(f"ALTER TABLE snapshots_1m_normalized ADD COLUMN {cdef}")
        dst.commit()
        dst.close()
        from snapshot_normalizer import materialize_normalized_table

        norm_res = materialize_normalized_table(db_path=args.out, tickers=list(args.tickers))
        dst = sqlite3.connect(str(args.out))
        dst.row_factory = sqlite3.Row
        norm_tb = dst.execute(
            "SELECT COUNT(*) FROM snapshots_1m_normalized WHERE outcome_tb_5c IS NOT NULL"
        ).fetchone()[0]
        manifest["normalized_carry"] = {
            "normalized_rows": norm_res.get("normalized_rows"),
            "normalized_errors": norm_res.get("errors"),
            "normalized_rows_with_tb_5c": norm_tb,
            "tb_columns_added": 16,
        }
    else:
        manifest["normalized_carry"] = {"error": "source normalized DDL not found"}

    manifest_path = args.out.with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    src.close()
    dst.close()
    print(json.dumps({k: v for k, v in manifest.items() if k != "k_fit_grid_trace"}, indent=1))
    print(f"manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
