#!/usr/bin/env python3
"""
Historical canonical 1m backfill for persistently enrolled tickers.

Universe: EdDB.logging_universe_authoritative_tickers() (core + pinned + user_persisted).

Writes: Schwab minute price history -> market_data_adapter.schwab_candles_to_bars -> EdDB.upsert_1m_bars
        (same path as live server; ON CONFLICT upsert; governed outcomes refreshed inside upsert).

Post: EdDB.refresh_all_governed_bar_anchor_outcomes_v1()

Usage:
  python tools/historical_backfill_enrolled_1m_v1.py --db data/ed_console.db --dry-run
  python tools/historical_backfill_enrolled_1m_v1.py --db data/ed_console.db --lookback-days 21
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bar_rehydration_issue19_v1 import _fetch_minute_window  # noqa: E402
from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target  # noqa: E402
from calibration.paths import DEFAULT_DB  # noqa: E402
from db import EdDB  # noqa: E402
from market_data_adapter import schwab_candles_to_bars  # noqa: E402


def _symbol_schwab_plausible(sym: str) -> bool:
    """Exclude corrupted logging_universe fragments (e.g. '$', '$SP', 'IW')."""
    t = (sym or "").strip().upper()
    if len(t) < 2 or len(t) > 12:
        return False
    if t.startswith("$"):
        return len(t) >= 4 and t[1:].replace("^", "").isalnum()
    return all(c.isalnum() or c in ". -" for c in t)


def _enrolled_tickers_with_data(db: EdDB) -> list[str]:
    """Authoritative enrolled symbols that actually appear in snapshots or price_bars_1m."""
    auth = [x.upper().strip() for x in db.logging_universe_authoritative_tickers()]
    with db._connect() as conn:
        snap = {r[0].upper() for r in conn.execute("SELECT DISTINCT ticker FROM snapshots WHERE timeframe='1m'")}
        bars = {r[0].upper() for r in conn.execute("SELECT DISTINCT ticker FROM price_bars_1m")}
    used = snap | bars
    out = [t for t in auth if t in used and _symbol_schwab_plausible(t)]
    return sorted(set(out))


def _per_ticker_bar_stats(db: EdDB, tickers: list[str]) -> list[dict]:
    out = []
    with db._connect() as conn:
        for t in tickers:
            r = conn.execute(
                """
                SELECT COUNT(*) AS n,
                       MIN(bar_start_ts_utc) AS mn,
                       MAX(bar_start_ts_utc) AS mx
                FROM price_bars_1m WHERE ticker = ?
                """,
                (t,),
            ).fetchone()
            days = conn.execute(
                """
                SELECT COUNT(DISTINCT strftime('%Y-%m-%d', bar_start_ts_utc, 'unixepoch'))
                FROM price_bars_1m WHERE ticker = ?
                """,
                (t,),
            ).fetchone()[0]
            sn = conn.execute(
                """
                SELECT COUNT(*) AS n, MIN(ts_utc) AS mn, MAX(ts_utc) AS mx
                FROM snapshots WHERE timeframe = '1m' AND ticker = ?
                """,
                (t,),
            ).fetchone()
            out.append(
                {
                    "ticker": t,
                    "price_bars_1m_count": int(r["n"] or 0),
                    "bar_start_min": r["mn"],
                    "bar_start_max": r["mx"],
                    "distinct_bar_utc_days": int(days or 0),
                    "snapshots_1m_count": int(sn["n"] or 0),
                    "snapshot_ts_min": sn["mn"],
                    "snapshot_ts_max": sn["mx"],
                }
            )
    return out


def run(
    db_path: Path,
    *,
    lookback_days: int,
    window_days: int,
    dry_run: bool,
    only_under_covered: bool,
    under_covered_max_bars: int,
) -> dict:
    db_path = db_path.resolve()
    db = EdDB(db_path)
    tickers = _enrolled_tickers_with_data(db)
    excluded = sorted(
        set(x.upper().strip() for x in db.logging_universe_authoritative_tickers()) - set(tickers)
    )
    if only_under_covered:
        filt: list[str] = []
        for row in _per_ticker_bar_stats(db, tickers):
            if int(row["price_bars_1m_count"] or 0) < under_covered_max_bars:
                filt.append(row["ticker"])
        tickers = filt
    tickers = sorted(set(tickers))

    end_dt = datetime.now(timezone.utc) - timedelta(seconds=90)
    start_dt = end_dt - timedelta(days=max(1, lookback_days))

    audit: dict = {
        "schema": "historical_backfill_enrolled_1m_v1",
        "db_path": str(db_path),
        "lookback_days": lookback_days,
        "window_days": window_days,
        "window_start_utc": start_dt.isoformat(),
        "window_end_utc": end_dt.isoformat(),
        "tickers_targeted": tickers,
        "n_tickers": len(tickers),
        "tickers_excluded_malformed_or_unused": excluded,
        "dry_run": dry_run,
        "per_ticker_before": _per_ticker_bar_stats(db, tickers),
    }

    if dry_run:
        audit["status"] = "dry_run"
        return audit

    try:
        from server import get_client
    except Exception as e:
        audit["error"] = f"get_client import failed: {e}"
        return audit

    try:
        client = get_client()
    except Exception as e:
        audit["error"] = f"Schwab client init failed: {e}"
        return audit

    windows_log: list[dict] = []
    total_written = 0
    for sym in tickers:
        cursor = start_dt
        sym_upper = (sym or "").strip()
        if not sym_upper:
            continue
        while cursor < end_dt:
            w_end = min(cursor + timedelta(days=window_days), end_dt)
            if w_end <= cursor:
                break
            wl = {
                "ticker": sym_upper,
                "window_start_utc": cursor.isoformat(),
                "window_end_utc": w_end.isoformat(),
                "http_status": None,
                "n_candles": 0,
                "bars_upsert_count": 0,
                "error": None,
            }
            try:
                resp = _fetch_minute_window(client, sym_upper, cursor, w_end)
                wl["http_status"] = resp.status_code
                data = resp.json()
                candles = data.get("candles") or []
                wl["n_candles"] = len(candles)
                bars = schwab_candles_to_bars(candles)
                n = db.upsert_1m_bars(sym_upper, bars)
                wl["bars_upsert_count"] = n
                total_written += n
            except Exception as e:
                wl["error"] = str(e)[:500]
                windows_log.append(wl)
                audit.setdefault("window_errors", []).append(
                    {"ticker": sym_upper, "window_start": wl["window_start_utc"], "error": wl["error"]}
                )
                cursor = w_end
                time.sleep(0.35)
                continue
            windows_log.append(wl)
            cursor = w_end
            time.sleep(0.35)
        time.sleep(0.35)

    audit["windows"] = windows_log
    audit["total_bar_rows_passed_to_upsert"] = total_written
    audit["per_ticker_after"] = _per_ticker_bar_stats(db, tickers)

    ref = db.refresh_all_governed_bar_anchor_outcomes_v1()
    audit["refresh_all_governed_bar_anchor_outcomes_v1"] = ref
    return audit


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--lookback-days", type=int, default=21, help="Calendar days of history to request (UTC window end = now).")
    ap.add_argument("--window-days", type=int, default=7, help="Max days per Schwab request chunk.")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--only-under-covered",
        action="store_true",
        help="Only tickers with price_bars_1m count < --under-covered-max-bars.",
    )
    ap.add_argument("--under-covered-max-bars", type=int, default=4000)
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="historical_backfill_enrolled_1m_v1", write_capable=not args.dry_run)

    out = run(
        args.db,
        lookback_days=args.lookback_days,
        window_days=args.window_days,
        dry_run=args.dry_run,
        only_under_covered=args.only_under_covered,
        under_covered_max_bars=args.under_covered_max_bars,
    )
    print(json.dumps(out, indent=2, default=str))
    return 0 if "error" not in out else 1


if __name__ == "__main__":
    sys.exit(main())
