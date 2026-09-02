#!/usr/bin/env python3
"""Time-Slice Reversal Test — external (Gemini) spec 2026-07-22, run verbatim.

Purpose: DEFENSIVE terrain map, not a card. Prove/disprove that fading an extreme
open-anchored move is a trap BEFORE the flat-by-the-bell window:
  Test A (Morning Trap): predictor 09:30->11:00, response 11:00->11:30.
  Test B (Mid-Day Drift): predictor 09:30->13:00, response 13:00->13:30.
  Trigger both: |predictor| >= 1.0 x rolling 20-day median intraday range.
  Hit = REVERSAL (sign flip). Expected under the physics: A well below 50 (freight
  train), B ~50 (chop).
  Slice C (15:30->15:55, same 1.0x trigger) is printed as the CONTAMINATED DISCOVERY
  REFERENCE only — card #4's proof remains forward-only; C is context, never evidence.
Null tests on Mar-Jul history are explicitly allowed by the OOS lock (testing failure,
not shipping edge). Earnings days deliberately INCLUDED per spec (they strengthen the
momentum thesis if anything). Exact two-sided binomial p vs 50% per cell.
"""
from __future__ import annotations

import json
import math
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.domain.time_et import RTH_END_MINS, RTH_START_MINS, is_trading_day_et  # RC-58: the one calendar authority
from tools.terrain_backtest_report_v1 import (  # noqa: E402
    DB,
    SENTINELS,
    _et_day_and_min,
)

ROLL_DAYS = 20
TRIGGER = 1.0
SLICES = {"A_morning_1100": (11 * 60, 11 * 60 + 30),
          "B_midday_1300": (13 * 60, 13 * 60 + 30),
          "C_late_1530_CONTAMINATED_REF": (15 * 60 + 30, 15 * 60 + 55)}
OUT = ROOT / "reports" / "timeslice_reversal_v1.json"


def _series(con: sqlite3.Connection) -> dict:
    marks = sorted({m for pair in SLICES.values() for m in pair})
    out: dict[str, dict[str, dict]] = defaultdict(dict)
    cur = con.execute(
        "SELECT ticker, bar_start_ts_utc, open, high, low, close FROM price_bars_1m "
        "ORDER BY ticker, bar_start_ts_utc")
    for tk, ts, o, h, lo, c in cur:
        day, mins = _et_day_and_min(ts)
        if not is_trading_day_et(day):
            continue          # RC-58: calendar gate — minute windows admit weekend bars
        if not (RTH_START_MINS <= mins < RTH_END_MINS):
            continue
        d = out[tk].setdefault(day, {"open": o, "hi": h, "lo": lo, "at": {}})
        d["hi"], d["lo"] = max(d["hi"], h), min(d["lo"], lo)
        for m in marks:
            if mins <= m:
                d["at"][m] = c
    return out


def _binom_p_two_sided(hits: int, n: int) -> float:
    """Exact two-sided binomial p vs 0.5 (sum of outcomes as extreme as observed)."""
    if n == 0:
        return 1.0
    p_obs = math.comb(n, hits)
    total = sum(math.comb(n, k) for k in range(n + 1) if math.comb(n, k) <= p_obs)
    return round(min(1.0, total / 2 ** n), 4)


def _cell(rows: list[dict]) -> dict:
    n = len(rows)
    hits = sum(r["rev"] for r in rows)
    return {"n": n, "reversal_hit_pct": round(100 * hits / n, 1) if n else None,
            "binom_p_vs_50": _binom_p_two_sided(hits, n) if n else None}


def _day_slices(tk: str, d: dict, bound: float, rows: dict) -> None:
    for sname, (t0, t1) in SLICES.items():
        p0, p1 = d["at"].get(t0), d["at"].get(t1)
        if p0 is None or p1 is None:
            continue
        pred = (p0 - d["open"]) / d["open"] * 100
        resp = (p1 - p0) / p0 * 100
        if pred == 0 or resp == 0 or abs(pred) < bound:
            continue
        rows[sname].append({"ticker": tk, "rev": (resp > 0) != (pred > 0)})


def main() -> int:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=120)
    series = _series(con)
    con.close()
    rows: dict[str, list[dict]] = defaultdict(list)
    for tk, days in series.items():
        ordered = sorted(days)
        for i, day in enumerate(ordered):
            d = days[day]
            if i < ROLL_DAYS or not d["open"]:
                continue
            hist = [days[x] for x in ordered[i - ROLL_DAYS:i]]
            rngs = [(h["hi"] - h["lo"]) / h["open"] * 100 for h in hist if h["open"]]
            if not rngs:
                continue
            _day_slices(tk, d, TRIGGER * median(rngs), rows)
    rep: dict = {"spec": "Gemini Time-Slice Reversal Test 2026-07-22, trigger 1.0x "
                         "20d median intraday range, earnings INCLUDED per spec"}
    for sname in SLICES:
        rep[sname] = {
            "SENTINELS": _cell([r for r in rows[sname] if r["ticker"] in SENTINELS]),
            "SINGLE_NAMES": _cell([r for r in rows[sname] if r["ticker"] not in SENTINELS]),
        }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rep, indent=2), encoding="utf-8")
    print(json.dumps(rep, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
