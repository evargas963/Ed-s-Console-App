#!/usr/bin/env python3
"""Late-day tail ATLAS — conditional distributions, every slice, discover/confirm split.

Operator 2026-07-21: "look at the data in every way possible... the alpha is just not
going to appear after one test. we need to find it and earn it."

Method (the guardrail that keeps looking honest): days are split chronologically —
DISCOVER = first 60%, CONFIRM = last 40%. Shapes are FOUND in discover; anything
interesting only counts if it repeats in confirm. Nothing here ships a card — a shape
that survives both halves earns a pre-registration, then the standard card pipeline.

Slices: gamma regime x |move| bucket (quiet/mid/big vs own 20d range) x day-of-week x
direction. Metrics per cell: n, continuation%, mean tail bps, median tail bps.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean, median

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.study_card_lateday_v1 import ARM_MULT, ROLL_DAYS, _daily_series  # noqa: E402
from tools.terrain_backtest_report_v1 import (  # noqa: E402
    DB,
    _load_observations,
    _score_observations,
)

OUT = ROOT / "reports" / "lateday_atlas_v1.json"
QUIET_MULT = 0.35   # |move| < 0.35x own median range = quiet (bucket edge, descriptive)


def _rows() -> list[dict]:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=120)
    obs = _load_observations(con, None)
    scored = _score_observations(obs, {
        k: {"range_pct": 0.0, "trendiness": 0.0, "high": 0, "low": 0, "close": 0}
        for k in obs})
    regimes = {(r["ticker"], r["day"]): r["regime"] for r in scored}
    series = _daily_series(con, {tk for tk, _ in obs})
    con.close()
    out = []
    for tk, days in series.items():
        out.extend(_ticker_rows(tk, days, regimes))
    return sorted(out, key=lambda r: r["day"])


def _ticker_rows(tk: str, days: dict, regimes: dict) -> list[dict]:
    ordered = sorted(days)
    rows = (_day_row(tk, days, ordered, i, regimes) for i in range(len(ordered)))
    return [r for r in rows if r is not None]


def _day_row(tk: str, days: dict, ordered: list, i: int, regimes: dict) -> dict | None:
    from datetime import date
    day = ordered[i]
    d = days[day]
    if i < ROLL_DAYS or d["c1530"] is None or (tk, day) not in regimes:
        return None
    prev = days[ordered[i - 1]]
    hist = [days[x] for x in ordered[max(0, i - ROLL_DAYS):i]]
    rngs = [(h["hi"] - h["lo"]) / h["close"] * 100 for h in hist if h["close"]]
    if not rngs or not prev["close"]:
        return None
    med_rng = median(rngs)
    move = (d["c1530"] - prev["close"]) / prev["close"] * 100
    tail = (d["close"] - d["c1530"]) / d["c1530"] * 100
    y, m, dd = (int(x) for x in day.split("-"))
    if move == 0 or tail == 0 or date(y, m, dd).weekday() > 4:
        return None
    return {
        "day": day, "dow": date(y, m, dd).weekday(),
        "short": regimes[(tk, day)] == "SHORT_GAMMA_TREND",
        "bucket": ("quiet" if abs(move) < QUIET_MULT * med_rng
                   else "big" if abs(move) >= ARM_MULT * med_rng else "mid"),
        "up": move > 0,
        "cont": (move > 0) == (tail > 0),
        "tail_bps": tail * 100 * (1 if move > 0 else -1),  # signed WITH the day
    }


def _cell(rows: list[dict]) -> dict:
    n = len(rows)
    if not n:
        return {"n": 0}
    return {"n": n, "cont_pct": round(100 * sum(r["cont"] for r in rows) / n, 1),
            "mean_tail_bps": round(mean(r["tail_bps"] for r in rows), 1),
            "med_tail_bps": round(median(r["tail_bps"] for r in rows), 1)}


def main() -> int:
    rows = _rows()
    cut = rows[int(len(rows) * 0.6)]["day"] if rows else ""
    halves = {"DISCOVER": [r for r in rows if r["day"] <= cut],
              "CONFIRM": [r for r in rows if r["day"] > cut]}
    atlas: dict = {"rows_total": len(rows), "split_day": cut, "cells": {}}
    slicers = {
        "regime": lambda r: "short" if r["short"] else "long",
        "regime_x_bucket": lambda r: f"{'short' if r['short'] else 'long'}|{r['bucket']}",
        "regime_x_bucket_x_dir": lambda r: (f"{'short' if r['short'] else 'long'}|"
                                            f"{r['bucket']}|{'up' if r['up'] else 'down'}"),
        "bucket": lambda r: r["bucket"],
        "dow": lambda r: "MTWTF"[r["dow"]] + str(r["dow"]),
        "regime_x_dow": lambda r: f"{'short' if r['short'] else 'long'}|{r['dow']}",
    }
    for sname, fn in slicers.items():
        grid: dict[str, dict] = {}
        for half, hrows in halves.items():
            groups = defaultdict(list)
            for r in hrows:
                groups[fn(r)].append(r)
            for key, g in sorted(groups.items()):
                grid.setdefault(key, {})[half] = _cell(g)
        atlas["cells"][sname] = grid
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(atlas, indent=2), encoding="utf-8")

    print(f"rows={len(rows)} split@{cut}  (cells with n>=20 in BOTH halves, sorted by "
          f"confirm cont%)")
    flat = []
    for sname, grid in atlas["cells"].items():
        for key, halves_d in grid.items():
            d_, c_ = halves_d.get("DISCOVER", {}), halves_d.get("CONFIRM", {})
            if d_.get("n", 0) >= 20 and c_.get("n", 0) >= 20:
                flat.append((sname, key, d_, c_))
    flat.sort(key=lambda x: x[3]["cont_pct"], reverse=True)
    for sname, key, d_, c_ in flat:
        print(f"{sname:24s} {key:22s} DISC n={d_['n']:4d} {d_['cont_pct']:5.1f}% "
              f"{d_['mean_tail_bps']:+7.1f}bps | CONF n={c_['n']:4d} {c_['cont_pct']:5.1f}% "
              f"{c_['mean_tail_bps']:+7.1f}bps")
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
