#!/usr/bin/env python3
"""CR-05a late-day continuation card — BACKTEST against full held history.

Pre-registered (governance/unproven_register.md 2026-07-21) BEFORE this file was
written: arm when net dealer gamma < 0 (naive, ~10:00 ET terrain) AND
|prior-close -> 15:30 ET return| >= 0.75 x ticker's rolling 20-day median daily range.
Claim: the 15:30->16:00 ET move continues the day's direction more often than placebo.
Both-ways: the LONG-gamma arm must NOT work (Baltussen JFE 2021 mechanism).
RESULT 2026-07-21 (recorded in the register): NULL AS REGISTERED — armed n=53 hit
49.1% vs placebo 46.6%/53.2%. Kill PROVISIONAL pending external (Kimi) design audit.

RESTORED 2026-07-21: this file and its result JSON were deleted by a commit-round
cleanup; rebuilt verbatim from the session so the recorded result stays reproducible.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.terrain_backtest_report_v1 import (  # noqa: E402
    DB,
    _et_day_and_min,
    _load_observations,
    _score_observations,
)

ARM_MULT = 0.75          # PRE-REGISTERED — do not tune
ROLL_DAYS = 20
CUT_MIN = 15 * 60 + 30   # 15:30 ET
OUT = ROOT / "reports" / "card_lateday_backtest_v1.json"


def _daily_series(con: sqlite3.Connection, tickers: set[str]) -> dict:
    out: dict[str, dict[str, dict]] = defaultdict(dict)
    for tk in sorted(tickers):
        cur = con.execute(
            "SELECT bar_start_ts_utc, high, low, close FROM price_bars_1m "
            "WHERE ticker=? ORDER BY bar_start_ts_utc", (tk,))
        for ts, h, lo, c in cur:
            day, mins = _et_day_and_min(ts)
            if not (9 * 60 + 30 <= mins <= 15 * 60 + 59):
                continue
            d = out[tk].setdefault(day, {"hi": h, "lo": lo, "c1530": None, "close": c})
            d["hi"], d["lo"] = max(d["hi"], h), min(d["lo"], lo)
            if mins <= CUT_MIN:
                d["c1530"] = c
            d["close"] = c
    return out


def _tally(rows: list[dict], pred) -> dict:
    sub = [r for r in rows if pred(r)]
    n = len(sub)
    return {"n": n, "hit_pct": round(100 * sum(r["hit"] for r in sub) / n, 1) if n else None}


def main() -> int:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=120)
    obs = _load_observations(con, None)
    scored = _score_observations(obs, {
        k: {"range_pct": 0.0, "trendiness": 0.0, "high": 0, "low": 0, "close": 0}
        for k in obs})
    regimes = {(r["ticker"], r["day"]): r["regime"] for r in scored}
    series = _daily_series(con, {tk for tk, _ in obs})
    con.close()

    rows: list[dict] = []
    for tk, days in series.items():
        ordered = sorted(days)
        for i, day in enumerate(ordered):
            d = days[day]
            if i < ROLL_DAYS or d["c1530"] is None or (tk, day) not in regimes:
                continue
            prev = days[ordered[i - 1]]
            hist = [days[x] for x in ordered[max(0, i - ROLL_DAYS):i]]
            rngs = [(h["hi"] - h["lo"]) / h["close"] * 100 for h in hist if h["close"]]
            if not rngs or not prev["close"]:
                continue
            bound = ARM_MULT * median(rngs)
            move = (d["c1530"] - prev["close"]) / prev["close"] * 100
            tail = (d["close"] - d["c1530"]) / d["c1530"] * 100
            if move == 0 or tail == 0:
                continue
            rows.append({
                "ticker": tk, "day": day,
                "short_gamma": regimes[(tk, day)] == "SHORT_GAMMA_TREND",
                "big_move": abs(move) >= bound,
                "hit": (move > 0) == (tail > 0),
            })

    rep = {
        "preregistered": {"arm_mult": ARM_MULT, "roll_days": ROLL_DAYS,
                          "window": "15:30->16:00 ET"},
        "rows_scored": len(rows),
        "CARD_short_gamma_AND_big_move": _tally(rows, lambda r: r["short_gamma"] and r["big_move"]),
        "BOTHWAYS_long_gamma_AND_big_move": _tally(rows, lambda r: not r["short_gamma"] and r["big_move"]),
        "PLACEBO_big_move_any_gamma": _tally(rows, lambda r: r["big_move"]),
        "PLACEBO_all_days_unconditional": _tally(rows, lambda *_: True),
        "small_move_short_gamma": _tally(rows, lambda r: r["short_gamma"] and not r["big_move"]),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rep, indent=2), encoding="utf-8")
    print(json.dumps(rep, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
