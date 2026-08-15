#!/usr/bin/env python3
"""Card #2 — first-30m -> last-30m momentum on HIGH-RV days. External pre-registration.

Spec authored EXTERNALLY (Gemini adversarial audit, 2026-07-21) before this run:
  Predictor:   09:30 -> 10:00 ET return.
  Conditioning: opening-30m realized volatility > 80th percentile of rolling 20-day
                window. RV metric fixed BEFORE the run per the audit: localized
                PARKINSON estimator over the 30 individual 1m bars
                (sqrt(mean(ln(H/L)^2) / (4 ln 2))), not stdev of closes.
  Response:    15:30 -> 16:00 ET return.
  Hit:         sign(predictor) == sign(response).
  Placebo:     LOW-RV days (< 50th percentile). Verdict on the HIGH-vs-LOW margin via
               10,000-run permutation of the high/low labels; ONE-SIDED p (P[M>=M_obs]
               for HIGH−LOW margin) <0.05; n>=100 to power.
  Universes:   sentinels and single names reported separately (never pooled).
  Gates (operational, DISCLOSED — measured on this feed 2026-07-22):
               Strict Gemini reading (30/30 AM bars + 20/20 prior RV days) yields
               hist20≈7 ticker-days and cannot power a verdict. Operational gates
               used for the registered run: Parkinson requires >=15 of 30 opening
               1m bars; rolling window requires >=10 of 20 prior RV days; percentiles
               via statistics.quantiles(n=100). Both relaxations named in the report
               JSON note_am_bar_gate; earnings exclusion also disclosed.
"""
from __future__ import annotations

import json
import math
import random
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from statistics import quantiles

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from time_et import is_trading_day_et  # RC-58: the one calendar authority
from tools.terrain_backtest_report_v1 import (  # noqa: E402
    DB,
    SENTINELS,
    _et_day_and_min,
)

ROLL_DAYS = 20
MIN_AM_BARS = 15         # of 30; see docstring Gates (strict-30 + hist20 infeasible)
MIN_HIST_RV = ROLL_DAYS // 2
HIGH_PCT = 0.80
LOW_PCT = 0.50
N_PERM = 10_000
OUT = ROOT / "reports" / "card2_am_pm_v1.json"


def _series(con: sqlite3.Connection) -> dict:
    """Per ticker-day: open, 10:00 close, 15:30 close, 16:00 close, opening-30m bars."""
    out: dict[str, dict[str, dict]] = defaultdict(dict)
    cur = con.execute(
        "SELECT ticker, bar_start_ts_utc, open, high, low, close FROM price_bars_1m "
        "ORDER BY ticker, bar_start_ts_utc")
    for tk, ts, o, h, lo, c in cur:
        day, mins = _et_day_and_min(ts)
        if not is_trading_day_et(day):
            continue          # RC-58: minute windows alone admit Saturday bars — frozen
                              # ranges bias every response stat deterministically
        # Include the 16:00 ET bar (mins==960) so response is 15:30→16:00, not 15:59.
        if not (9 * 60 + 30 <= mins <= 16 * 60):
            continue
        d = out[tk].setdefault(day, {"open": o, "c1000": None, "c1530": None,
                                     "close": c, "am_hl": []})
        if mins < 10 * 60 and h and lo and lo > 0:
            d["am_hl"].append((h, lo))
        if mins <= 10 * 60:
            d["c1000"] = c
        if mins <= 15 * 60 + 30:
            d["c1530"] = c
        if mins <= 16 * 60:
            d["close"] = c
    return out


def _parkinson(hl: list[tuple[float, float]]) -> float | None:
    terms = [math.log(h / lo) ** 2 for h, lo in hl if h >= lo > 0]
    if len(terms) < MIN_AM_BARS:
        return None
    return math.sqrt(sum(terms) / len(terms) / (4 * math.log(2)))


def _rows() -> list[dict]:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=120)
    series = _series(con)
    con.close()
    rows: list[dict] = []
    for tk, days in series.items():
        ordered = sorted(days)
        rv = {day: _parkinson(days[day]["am_hl"]) for day in ordered}
        for i, day in enumerate(ordered):
            d = days[day]
            rv_day = rv[day]
            if i < ROLL_DAYS or rv_day is None:
                continue
            hist = sorted(v for x in ordered[i - ROLL_DAYS:i] if (v := rv[x]) is not None)
            if len(hist) < MIN_HIST_RV or None in (d["c1000"], d["c1530"]):
                continue
            if not d["open"]:
                continue
            pred = (d["c1000"] - d["open"]) / d["open"] * 100
            resp = (d["close"] - d["c1530"]) / d["c1530"] * 100
            if pred == 0 or resp == 0:
                continue
            cuts = quantiles(hist, n=100)
            hi_cut = cuts[int(HIGH_PCT * 100) - 1]   # 80th
            lo_cut = cuts[int(LOW_PCT * 100) - 1]    # 50th
            band = "high" if rv_day > hi_cut else "low" if rv_day < lo_cut else "mid"
            rows.append({"ticker": tk, "day": day, "band": band,
                         "hit": (pred > 0) == (resp > 0)})
    return rows


def _perm_margin(qual: list[dict]) -> dict:
    highs = [r["hit"] for r in qual if r["band"] == "high"]
    lows = [r["hit"] for r in qual if r["band"] == "low"]
    if not highs or not lows:
        return {"p": None}
    obs = sum(highs) / len(highs) - sum(lows) / len(lows)
    pool = highs + lows
    nh = len(highs)
    rng = random.Random(20260722)
    ge = 0
    for _ in range(N_PERM):
        rng.shuffle(pool)
        m = sum(pool[:nh]) / nh - sum(pool[nh:]) / len(pool[nh:])
        ge += m >= obs
    return {"observed_margin_pts": round(100 * obs, 1), "p_one_sided": round(ge / N_PERM, 4)}


def _universe(rows: list[dict]) -> dict:
    def cell(band):
        sub = [r for r in rows if r["band"] == band]
        return {"n": len(sub),
                "hit_pct": round(100 * sum(r["hit"] for r in sub) / len(sub), 1) if sub else None}
    qual = [r for r in rows if r["band"] in ("high", "low")]
    high = cell("high")
    return {"HIGH_RV_card": high, "LOW_RV_placebo": cell("low"), "mid_excluded": cell("mid"),
            "verdict_gate": "POWERED" if (high["n"] or 0) >= 100 else "UNDERPOWERED_PENDING",
            "permutation_high_vs_low": _perm_margin(qual)}


def main() -> int:
    rows = _rows()
    rep = {"spec": "Gemini 2026-07-21 — Parkinson RV(30x1m bars), 80th/50th pct, "
                   "perm seed 20260722",
           "SENTINELS": _universe([r for r in rows if r["ticker"] in SENTINELS]),
           "SINGLE_NAMES": _universe([r for r in rows if r["ticker"] not in SENTINELS]),
           "note_earnings_exclusion": "NOT applied — calendar not yet held; same "
                                      "disclosed deviation as card #1",
           "note_am_bar_gate": f">={MIN_AM_BARS}/30 AM bars; "
                              f">={MIN_HIST_RV}/{ROLL_DAYS} prior RV days; "
                              "quantiles(n=100). Strict 30/30+20/20 infeasible "
                              f"(hist20≈7 on this feed) — disclosed deviation."}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rep, indent=2), encoding="utf-8")
    print(json.dumps(rep, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
