"""Batch universe screener + scaled F1/F2 runner (operator directive 2026-07-24).

The watchlist (31-51 tickers) is discovered from the DB (or --tickers) and every
symbol passes the SAME preregistration-template flow: liquidity/data gates first
(fail-closed, every exclusion named), then the qualifying symbols run the
declared draft-cell battery, each emitting a structured JSON report under
reports/batch/. Heavy modes (full 175-cell grid / meta) are operator-host runs;
this tool prints the exact per-ticker handoff commands instead of running them
inline.

Batch results are RESEARCH DRAFT screens under the F2 template
(F2_TB_GRID_V1_PREREG_V1 family/floors); survivor-grade claims still require a
per-ticker frozen prereg + two-way audit. No unverified asset touches serving.

Usage:
  python tools/run_batch_universe_study.py --mode screen
  python tools/run_batch_universe_study.py --mode battery
  python tools/run_batch_universe_study.py --mode battery --tickers SPY QQQ IWM
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_DB = str(REPO_ROOT / "data" / "ed_console.db")
BATCH_DIR = REPO_ROOT / "reports" / "batch"

# Screen gates (template floors; every failure is named, never silent).
MIN_TRADABLE_SESSIONS = 60      # matches the F2 template session floor
MIN_TOTAL_BARS = 20_000         # enough history for ATR warm-up + events
MIN_REAL_BAR_SHARE = 0.50       # majority of the tape must be known-real


def discover_universe(db_path: str) -> dict[str, int]:
    """Ticker -> bar count from price_bars_1m (the storage watchlist)."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return {
            str(r[0]): int(r[1])
            for r in con.execute(
                "SELECT ticker, COUNT(*) FROM price_bars_1m GROUP BY ticker"
            )
        }
    finally:
        con.close()


def screen_ticker(db_path: str, ticker: str) -> dict[str, Any]:
    """Fail-closed gate verdict for one symbol (reasons enumerated)."""
    from research.pilot_step3.f1_input_gates import classify_bar_source
    from research.pilot_step3.data_loader import load_spy_1m_bars
    from time_et import et_date_str_from_ts_utc, is_tradable_session_ts_utc

    rep = load_spy_1m_bars(db_path, ticker=ticker, require_rth_only=True)
    tradable = [b for b in rep.bars if is_tradable_session_ts_utc(b.bar_start_ts_utc)]
    sessions = {et_date_str_from_ts_utc(b.bar_start_ts_utc) for b in tradable}
    n_real = sum(1 for b in tradable if classify_bar_source(b.source) == "real")
    real_share = (n_real / len(tradable)) if tradable else 0.0
    reasons: list[str] = []
    if len(sessions) < MIN_TRADABLE_SESSIONS:
        reasons.append(f"sessions_{len(sessions)}_below_{MIN_TRADABLE_SESSIONS}")
    if rep.n_rows < MIN_TOTAL_BARS:
        reasons.append(f"bars_{rep.n_rows}_below_{MIN_TOTAL_BARS}")
    if real_share < MIN_REAL_BAR_SHARE:
        reasons.append(f"real_share_{real_share:.2f}_below_{MIN_REAL_BAR_SHARE}")
    return {
        "ticker": ticker,
        "n_bars_total": rep.n_rows,
        "n_tradable_bars": len(tradable),
        "n_tradable_sessions": len(sessions),
        "real_bar_share": round(real_share, 4),
        "qualified": not reasons,
        "exclusion_reasons": reasons,
    }


def run_ticker_battery(db_path: str, ticker: str) -> dict[str, Any]:
    """Draft-cell gated battery for one qualifying symbol (S5-equivalent)."""
    from research.pilot_step3.f1_input_gates import (
        build_label_quality_report,
        gated_label_event_cell_f1,
    )
    from research.pilot_step3.f1_s5_spy_battery import (
        DRAFT_COST_ROUND_TRIP_BP,
        DRAFT_STOP_ATR,
        DRAFT_TARGET_ATR,
        DRAFT_VERTICAL_MINUTES,
    )
    from research.pilot_step3.f2_tb_grid_runner import _sessions_events

    t0 = time.perf_counter()
    by_day, events, atrs, loader_info = _sessions_events(db_path, ticker)
    results = []
    for day in sorted(by_day):
        day_bars = by_day[day]
        atr_series = atrs[day]
        for ev in events[day]:
            results.append(
                gated_label_event_cell_f1(
                    day_bars, atr_series, ev,
                    stop_atr=DRAFT_STOP_ATR,
                    target_atr=DRAFT_TARGET_ATR,
                    vertical_minutes=DRAFT_VERTICAL_MINUTES,
                    cost_round_trip_bp=DRAFT_COST_ROUND_TRIP_BP,
                )
            )
    return {
        "schema": "batch_ticker_battery_v1",
        "status": "RESEARCH_DRAFT_SCREEN_NOT_PREREGISTERED_NOT_AN_ADMISSION",
        "template": "F2_TB_GRID_V1_PREREG_V1 draft cell",
        "ticker": ticker,
        "generated_utc": datetime.now(tz=timezone.utc).isoformat(),
        "loader": loader_info,
        "draft_cell": {
            "stop_atr": DRAFT_STOP_ATR,
            "target_atr": DRAFT_TARGET_ATR,
            "vertical_minutes": DRAFT_VERTICAL_MINUTES,
            "cost_round_trip_bp": DRAFT_COST_ROUND_TRIP_BP,
        },
        "label_quality_report": build_label_quality_report({ticker: results}),
        "run_sec": round(time.perf_counter() - t0, 2),
    }


def run_batch(db_path: str, tickers: list[str] | None, mode: str) -> dict[str, Any]:
    t0 = time.perf_counter()
    universe = discover_universe(db_path)
    chosen = tickers if tickers else sorted(universe)
    screens: list[dict[str, Any]] = []
    battery_files: dict[str, str] = {}
    handoff: list[str] = []
    BATCH_DIR.mkdir(parents=True, exist_ok=True)
    for tk in chosen:
        s = screen_ticker(db_path, tk)
        screens.append(s)
        if not s["qualified"]:
            continue
        if mode == "battery":
            rep = run_ticker_battery(db_path, tk)
            out = BATCH_DIR / f"{tk.replace('$', 'S_')}_battery_v1.json"
            out.write_text(json.dumps(rep, indent=2), encoding="utf-8")
            battery_files[tk] = str(out)
        handoff.append(
            f"python -m research.pilot_step3.f2_tb_grid_runner --ticker {tk}"
            "  # EXP-1 grid handoff (operator host, ~1 min/ticker; --ticker flag ships with EXP-1, ACTIVE_PROGRAM §F2 expansion)"
        )
    n_q = sum(1 for s in screens if s["qualified"])
    summary = {
        "schema": "batch_universe_summary_v1",
        "generated_utc": datetime.now(tz=timezone.utc).isoformat(),
        "mode": mode,
        "n_universe": len(chosen),
        "n_qualified": n_q,
        "n_excluded": len(chosen) - n_q,
        "gates": {
            "min_tradable_sessions": MIN_TRADABLE_SESSIONS,
            "min_total_bars": MIN_TOTAL_BARS,
            "min_real_bar_share": MIN_REAL_BAR_SHARE,
        },
        "screens": screens,
        "battery_reports": battery_files,
        "run_sec": round(time.perf_counter() - t0, 2),
    }
    (BATCH_DIR / "universe_summary_v1.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    return summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--mode", choices=("screen", "battery"), default="screen")
    ap.add_argument("--tickers", nargs="*", default=None)
    args = ap.parse_args()
    summary = run_batch(args.db, args.tickers, args.mode)
    compact = {
        "mode": summary["mode"],
        "n_universe": summary["n_universe"],
        "n_qualified": summary["n_qualified"],
        "qualified": [s["ticker"] for s in summary["screens"] if s["qualified"]],
        "excluded": {
            s["ticker"]: s["exclusion_reasons"]
            for s in summary["screens"]
            if not s["qualified"]
        },
        "run_sec": summary["run_sec"],
        "summary_report": str(BATCH_DIR / "universe_summary_v1.json"),
    }
    print(json.dumps(compact, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
