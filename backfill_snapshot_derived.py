#!/usr/bin/env python3
"""
Retroactively fill snapshots (and refresh snapshots_1m_normalized):

- VWAP gaps: forward-fill per ticker, then OHLC/spot typical price; updates
  vwap, vwap_dist_pts, vwap_side together.
- iv_rank / iv_percentile: rolling prior iv_level history (min 20 points).
- pressure_label / pressure_trend: from DPI + hedging flow (+ trend on dpi_normalized).
- spy/qqq/iwm weighted_push: recompute from persisted constituent chg_pct when NULL.

Run from project root:
  python backfill_snapshot_derived.py
  python backfill_snapshot_derived.py --skip-normalizer
"""
from __future__ import annotations

from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from calibration.paths import DEFAULT_DB
from db import get_snapshot_sql


import argparse
import sqlite3
from pathlib import Path

from math_snapshot_derive import derive_pressure_trend, derive_vwap_side
from math_volatility import compute_iv_percentile, compute_iv_rank
from timeframe_config import CANONICAL_TIMEFRAME, DERIVED_TIMEFRAME

ROOT = Path(__file__).resolve().parent
IV_HIST_CAP = 5000


def backfill(db_path: Path) -> dict:
    conn = sqlite3.connect(str(db_path), timeout=60)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    for tbl in ("snapshots", "snapshots_1m_normalized"):
        for col in ("pressure_label", "pressure_trend"):
            try:
                cur.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} TEXT")
            except sqlite3.OperationalError:
                pass
    conn.commit()

    rows = cur.execute(
        get_snapshot_sql("backfill_snapshot_derived.py:76"),
        (CANONICAL_TIMEFRAME, DERIVED_TIMEFRAME),
    ).fetchall()

    iv_hist_by_ticker: dict[str, list[float]] = {}
    dpi_prev: dict[str, float | None] = {}
    last_vwap_by_ticker: dict[str, float | None] = {}
    updated = 0
    vwap_filled = 0

    for r in rows:
        sid = int(r["snapshot_id"])
        tkr = r["ticker"]
        spot = r["spot"]
        vwap_raw = r["vwap"]

        eff_vwap = None
        if vwap_raw is not None:
            try:
                vf = float(vwap_raw)
                if vf > 0:
                    eff_vwap = vf
                # treat 0 / garbage as missing so we forward-fill
            except (TypeError, ValueError):
                pass
        if eff_vwap is None:
            # Forward-fill from a prior REAL vwap on this ticker is allowed.
            # Typical-price SUBSTITUTION is forbidden (RC-213 Tier-B / census #2):
            # a fabricated vwap is worse than an absent vwap.
            eff_vwap = last_vwap_by_ticker.get(tkr)
        if eff_vwap is not None:
            last_vwap_by_ticker[tkr] = eff_vwap
        if vwap_raw is None and eff_vwap is not None:
            vwap_filled += 1

        try:
            spot_f = float(spot) if spot is not None else None
        except (TypeError, ValueError):
            spot_f = None
        vwap_dist = (
            round(spot_f - eff_vwap, 4)
            if (spot_f is not None and eff_vwap is not None)
            else None
        )
        vwap_side = derive_vwap_side(spot_f, eff_vwap)

        iv = r["iv_level"]
        try:
            iv_f = float(iv) if iv is not None and float(iv) > 0 else None
        except (TypeError, ValueError):
            iv_f = None

        hist = iv_hist_by_ticker.setdefault(tkr, [])
        iv_rank = compute_iv_rank(iv_f, hist) if iv_f is not None else None
        iv_pct = compute_iv_percentile(iv_f, hist) if iv_f is not None else None
        if iv_f is not None:
            hist.append(iv_f)
            if len(hist) > IV_HIST_CAP:
                del hist[: len(hist) - IV_HIST_CAP]

        plab = r["dpi_direction"] or r["hedging_flow_direction"] or "neutral"

        prev_dn = dpi_prev.get(tkr)
        cur_dn = None
        if r["dpi_normalized"] is not None:
            try:
                cur_dn = float(r["dpi_normalized"])
            except (TypeError, ValueError):
                cur_dn = None
        ptrend = derive_pressure_trend(prev_dn, cur_dn)
        dpi_prev[tkr] = cur_dn

        cur.execute(
            """
            UPDATE snapshots SET
                vwap = ?,
                vwap_dist_pts = ?,
                vwap_side = ?,
                iv_rank = ?,
                iv_percentile = ?,
                pressure_label = ?,
                pressure_trend = ?
            WHERE snapshot_id = ?
            """,
            (
                eff_vwap,
                vwap_dist,
                vwap_side,
                iv_rank,
                iv_pct,
                plab,
                ptrend,
                sid,
            ),
        )
        updated += 1

    conn.commit()
    conn.close()
    return {"rows_updated": updated, "vwap_rows_imputed": vwap_filled}


def backfill_weighted_pushes(db_path: Path) -> dict[str, int]:
    """Fill NULL spy/qqq/iwm weighted_push from persisted constituent chg_pct columns."""
    import bisect

    from market_context import (
        merged_snapshot_chg_map,
        symbols_without_snapshot_chg_col,
        weighted_pushes_from_snapshot_row,
    )

    conn = sqlite3.connect(str(db_path), timeout=120)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    stats = {"spy_filled": 0, "qqq_filled": 0, "iwm_filled": 0, "rows_scanned": 0}

    tick_series: dict[str, list[tuple[float, float]]] = {}
    try:
        tick_rows = cur.execute(
            """
            SELECT ticker, ts_utc, chg_pct
            FROM confluence_quote_ticks
            WHERE chg_pct IS NOT NULL
            ORDER BY ticker COLLATE NOCASE, ts_utc ASC
            """
        ).fetchall()
        for tr in tick_rows:
            sym = str(tr["ticker"]).upper()
            try:
                ts = float(tr["ts_utc"])
                chg = float(tr["chg_pct"])
            except (TypeError, ValueError):
                continue
            tick_series.setdefault(sym, []).append((ts, chg))
    except sqlite3.OperationalError:
        tick_series = {}

    def _chg_as_of(sym: str, ts_utc: float) -> float | None:
        series = tick_series.get(sym.upper())
        if not series:
            return None
        stamps = [s for s, _ in series]
        idx = bisect.bisect_right(stamps, ts_utc) - 1
        if idx < 0:
            return None
        return series[idx][1]

    need_tick_syms = symbols_without_snapshot_chg_col()
    rows = cur.execute(
        """
        SELECT snapshot_id, ts_utc,
               spy_weighted_push, qqq_weighted_push, iwm_weighted_push,
               nvda_chg_pct, aapl_chg_pct, msft_chg_pct, amzn_chg_pct,
               googl_chg_pct, avgo_chg_pct, meta_chg_pct, tsla_chg_pct,
               kre_chg_pct, xbi_chg_pct, psci_chg_pct, xrt_chg_pct
        FROM snapshots
        WHERE spy_weighted_push IS NULL
           OR qqq_weighted_push IS NULL
           OR iwm_weighted_push IS NULL
        ORDER BY ts_utc ASC, snapshot_id ASC
        """
    ).fetchall()
    for r in rows:
        stats["rows_scanned"] += 1
        row = dict(r)
        ts_utc = row.get("ts_utc")
        extra: dict[str, float | None] = {}
        if ts_utc is not None and need_tick_syms:
            try:
                ts_f = float(ts_utc)
            except (TypeError, ValueError):
                ts_f = None
            if ts_f is not None:
                base = merged_snapshot_chg_map(row)
                for sym in need_tick_syms:
                    if base.get(sym) is not None:
                        continue
                    v = _chg_as_of(sym, ts_f)
                    if v is not None:
                        extra[sym] = v
        pushes = weighted_pushes_from_snapshot_row(row, extra_chg=extra or None)
        updates: dict[str, float] = {}
        for col, stat_key in (
            ("spy_weighted_push", "spy_filled"),
            ("qqq_weighted_push", "qqq_filled"),
            ("iwm_weighted_push", "iwm_filled"),
        ):
            if row.get(col) is not None:
                continue
            val = pushes.get(col)
            if val is not None:
                updates[col] = val
                stats[stat_key] += 1
        if not updates:
            continue
        sets = ", ".join(f"{k} = ?" for k in updates)
        cur.execute(
            f"UPDATE snapshots SET {sets} WHERE snapshot_id = ?",
            (*updates.values(), int(r["snapshot_id"])),
        )
    conn.commit()
    conn.close()
    return stats


def main() -> None:
    ap = argparse.ArgumentParser(description="Backfill derived snapshot fields")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--skip-normalizer", action="store_true")
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="backfill_snapshot_derived", write_capable=True)
    if not args.db.exists():
        raise SystemExit(f"DB not found: {args.db}")
    stats = backfill(args.db)
    print("backfill_snapshot_derived:", stats)
    wp = backfill_weighted_pushes(args.db)
    print("backfill_weighted_pushes:", wp)
    if not args.skip_normalizer:
        from normalized_training_sync import ensure_normalized_training_table

        out = ensure_normalized_training_table(args.db, force=False)
        print("normalized_training_sync:", out)


if __name__ == "__main__":
    main()
