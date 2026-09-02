"""F1 S5 — first real-data run: SPY through the gated triple-barrier pipeline.

RESEARCH DRAFT, report-only, NOT preregistered and NOT an admission packet:
one declared barrier cell from the pilot's pledged grid, run to produce the
first class-balance / flag-rate report on real bars. The formal preregistered
study (full grid + F2 economic gate) is a later section.

Session integrity (S5 constraint #3): CUSUM runs PER ET SESSION — bars are
grouped by trading day and generate_events sees one session at a time, so the
accumulator and its sigma reset at each 09:30 ET open and an overnight gap can
never contribute a z-trigger. Cost: sigma re-warms each morning (EWM span 390
on a 390-bar day), so early-session events are rarer than the continuous-tape
pilot — DISCLOSED in the report, not hidden.

Usage:
  python -m research.pilot_step3.f1_s5_spy_battery            # full run
  python -m research.pilot_step3.f1_s5_spy_battery --preflight  # counts only
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.domain.time_et import is_tradable_session_ts_utc

from .data_loader import Bar1m, load_spy_1m_bars
from .event_generation import generate_events
from .f1_input_gates import (
    classify_bar_source,
    gated_label_event_cell_f1,
    build_label_quality_report,
)
from .labeling import TripleBarrierResult, build_atr_series

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = str(REPO_ROOT / "data" / "ed_console.db")
REPORT_PATH = REPO_ROOT / "reports" / "f1_s5_spy_battery_v1.json"

# Declared draft cell (middle of the pilot's pledged barrier grid) + pilot
# COST_V1 round trip. Draft constants for the smoke run — the formal study
# sweeps the pledged grid under its own prereg.
DRAFT_STOP_ATR = 1.0
DRAFT_TARGET_ATR = 1.5
DRAFT_VERTICAL_MINUTES = 30
DRAFT_COST_ROUND_TRIP_BP = 1.0

# Pilot CUSUM/SMA parameters reused verbatim, but under a NEW generator id:
# the per-session feed makes this a different generator than the frozen
# continuous-tape pilot, and it must never claim that identity.
F1_DRAFT_CANDIDATE_CONFIG: dict[str, Any] = {
    "candidate_generator": {
        "candidate_generator_id": "CUSUM_SMA_F1_DRAFT_PER_SESSION_V1",
        "cusum": {"k": 0.7, "h_threshold": 2.5},
        "ewm_span_bars": 390,
        "sigma_contract": {
            "contract_id": "CONTINUOUS_EWM_REL_FLOOR_V1_PER_SESSION",
            "ewm_span_bars": 390,
            "relative_floor": {"enabled": True, "M": 120, "phi": 0.25},
        },
        "exclude_first_30min_rth": True,
        "min_bar_gap": 5,
        "sma": {"fast": 8, "slow": 21, "near_equal_tolerance": 1e-09},
        "side_rule": "SMA_CROSS_TREND_ONLY_V1",
    }
}


def preflight(db_path: str, ticker: str = "SPY") -> dict[str, Any]:
    """Row counts + source distribution (read-only) before any heavy work."""
    tk = str(ticker).upper().strip()
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        t0 = time.perf_counter()
        n, ts_min, ts_max = con.execute(
            "SELECT COUNT(*), MIN(bar_start_ts_utc), MAX(bar_start_ts_utc) "
            "FROM price_bars_1m WHERE ticker = ?",
            (tk,),
        ).fetchone()
        sources = {
            (row[0] if row[0] is not None else "NULL"): int(row[1])
            for row in con.execute(
                "SELECT source, COUNT(*) FROM price_bars_1m "
                "WHERE ticker = ? GROUP BY source",
                (tk,),
            )
        }
        return {
            "ticker": tk,
            "n_bars": int(n),
            "ts_min": float(ts_min) if ts_min is not None else None,
            "ts_max": float(ts_max) if ts_max is not None else None,
            "source_distribution": sources,
            "preflight_sec": round(time.perf_counter() - t0, 2),
        }
    finally:
        con.close()


def _group_by_et_session(bars: list[Bar1m]) -> dict[str, list[Bar1m]]:
    from app.domain.time_et import et_date_str_from_ts_utc

    by_day: dict[str, list[Bar1m]] = {}
    for b in bars:
        by_day.setdefault(et_date_str_from_ts_utc(b.bar_start_ts_utc), []).append(b)
    return by_day


def run_battery(db_path: str) -> dict[str, Any]:
    t_start = time.perf_counter()
    pf = preflight(db_path)
    rep = load_spy_1m_bars(db_path, require_rth_only=True)
    tradable = [b for b in rep.bars if is_tradable_session_ts_utc(b.bar_start_ts_utc)]
    n_calendar_dropped = len(rep.bars) - len(tradable)
    src_counts = {"real": 0, "synthetic": 0, "unknown": 0}
    for b in tradable:
        src_counts[classify_bar_source(b.source)] += 1

    by_day = _group_by_et_session(tradable)
    results: list[TripleBarrierResult] = []
    day_stats: list[dict[str, Any]] = []
    for day in sorted(by_day):
        day_bars = by_day[day]
        events, gen_stats = generate_events(day_bars, F1_DRAFT_CANDIDATE_CONFIG)
        atr_series = build_atr_series(day_bars)
        day_results = [
            gated_label_event_cell_f1(
                day_bars,
                atr_series,
                ev,
                stop_atr=DRAFT_STOP_ATR,
                target_atr=DRAFT_TARGET_ATR,
                vertical_minutes=DRAFT_VERTICAL_MINUTES,
                cost_round_trip_bp=DRAFT_COST_ROUND_TRIP_BP,
            )
            for ev in events
        ]
        results.extend(day_results)
        day_stats.append(
            {
                "et_date": day,
                "n_bars": len(day_bars),
                "n_events": len(events),
                "n_labeled": sum(1 for r in day_results if r.withheld_reason is None),
                "generator_stats": gen_stats,
            }
        )

    quality = build_label_quality_report({"SPY": results})
    return {
        "schema": "f1_s5_spy_battery_v1",
        "status": "RESEARCH_DRAFT_NOT_PREREGISTERED_NOT_AN_ADMISSION",
        "generated_utc": datetime.now(tz=timezone.utc).isoformat(),
        "db_path": str(db_path),
        "preflight": pf,
        "loader": {
            "n_rows": rep.n_rows,
            "n_rth_rows": rep.n_rth_rows,
            "n_calendar_dropped_by_session_authority": n_calendar_dropped,
            "n_tradable_bars": len(tradable),
            "rth_gap_count": rep.rth_gap_count,
            "et_date_first": rep.et_date_first,
            "et_date_last": rep.et_date_last,
            "tradable_bar_source_counts": src_counts,
        },
        "draft_cell": {
            "stop_atr": DRAFT_STOP_ATR,
            "target_atr": DRAFT_TARGET_ATR,
            "vertical_minutes": DRAFT_VERTICAL_MINUTES,
            "cost_round_trip_bp": DRAFT_COST_ROUND_TRIP_BP,
        },
        "candidate_generator": F1_DRAFT_CANDIDATE_CONFIG["candidate_generator"],
        "disclosures": [
            "CUSUM + sigma reset per ET session: overnight gaps cannot trigger events; "
            "sigma re-warms each morning so early-session events are rarer than the "
            "continuous-tape pilot generator.",
            "Single declared draft barrier cell; the pledged 175-cell grid runs under "
            "its own prereg in a later section.",
            "Labels from this run are research artifacts; nothing here touches "
            "production columns or the decision path.",
        ],
        "n_sessions": len(day_stats),
        "n_events_total": sum(d["n_events"] for d in day_stats),
        "per_session": day_stats,
        "label_quality_report": quality,
        "run_sec": round(time.perf_counter() - t_start, 2),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--preflight", action="store_true", help="counts only, no battery")
    ap.add_argument("--out", default=str(REPORT_PATH))
    args = ap.parse_args()
    if args.preflight:
        print(json.dumps(preflight(args.db), indent=2))
        return 0
    report = run_battery(args.db)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    summary = {
        "n_sessions": report["n_sessions"],
        "n_events_total": report["n_events_total"],
        "quality": report["label_quality_report"],
        "run_sec": report["run_sec"],
        "report": str(out),
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
