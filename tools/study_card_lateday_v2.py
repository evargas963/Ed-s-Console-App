#!/usr/bin/env python3
"""Card #1 REDESIGN per external (Gemini) adversarial audit 2026-07-21 — exact spec.

The v1 test was ruled INVALID (design mismatch): gap-contaminated predictor, pooled
universes, MOC-window response, point-estimate verdict. This v2 implements the audit's
specification verbatim — windows must NOT be altered:

  Universe:  SPY/QQQ/IWM separate from single names (reported separately, never pooled).
  Regime:    net dealer gamma < 0 at ~10:00 ET; chain-confidence composition DISCLOSED.
             NOTE: terrain_read fail-closed — only TRUSTED regimes enter scored rows, so
             SINGLE_NAMES_ALL_CONF is structurally identical to TRUSTED_ONLY until
             non-TRUSTED regimes are scored into observations (disclosed, not silent).
  Predictor: 09:30 open -> 15:30 ET return, STRICTLY intraday (overnight gap zeroed).
  Condition: |ret 09:30->15:30| >= 0.75 x 20-day median INTRADAY range.
  Response:  15:30 -> 15:55 ET (MOC auction window excluded).
  Verdict:   10,000-run permutation test (shuffle short/long labels among big-move
             days), p<0.05 required; n<100 per universe = UNDERPOWERED/PENDING, no kill.
"""
from __future__ import annotations

import json
import random
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from time_et import is_trading_day_et  # RC-58: the one calendar authority
from tools.terrain_backtest_report_v1 import (  # noqa: E402
    DB,
    SENTINELS,
    _et_day_and_min,
    _load_observations,
    _score_observations,
)

ARM_MULT = 0.75
ROLL_DAYS = 20
N_PERM = 10_000
OUT = ROOT / "reports" / "card_lateday_v2_gemini_spec.json"


def _series(con: sqlite3.Connection, tickers: set[str]) -> dict:
    out: dict[str, dict[str, dict]] = defaultdict(dict)
    for tk in sorted(tickers):
        cur = con.execute(
            "SELECT bar_start_ts_utc, open, high, low, close FROM price_bars_1m "
            "WHERE ticker=? ORDER BY bar_start_ts_utc", (tk,))
        for ts, o, h, lo, c in cur:
            day, mins = _et_day_and_min(ts)
            if not is_trading_day_et(day):
                continue      # RC-58: calendar gate — minute windows admit weekend bars
            if not (9 * 60 + 30 <= mins <= 15 * 60 + 59):
                continue
            d = out[tk].setdefault(day, {"open": o, "hi": h, "lo": lo,
                                         "c1530": None, "c1555": None})
            d["hi"], d["lo"] = max(d["hi"], h), min(d["lo"], lo)
            if mins <= 15 * 60 + 30:
                d["c1530"] = c
            if mins <= 15 * 60 + 55:
                d["c1555"] = c
    return out


def _day_row(tk, days, ordered, i, reg) -> dict | None:
    day = ordered[i]
    d = days[day]
    if i < ROLL_DAYS or None in (d["c1530"], d["c1555"]) or (tk, day) not in reg:
        return None
    hist = [days[x] for x in ordered[i - ROLL_DAYS:i]]
    rngs = [(h["hi"] - h["lo"]) / h["open"] * 100 for h in hist if h["open"]]
    if not rngs or not d["open"]:
        return None
    move = (d["c1530"] - d["open"]) / d["open"] * 100          # STRICTLY intraday
    tail = (d["c1555"] - d["c1530"]) / d["c1530"] * 100        # 15:30 -> 15:55
    if move == 0 or tail == 0:
        return None
    regime, conf = reg[(tk, day)]
    return {"ticker": tk, "day": day, "short": regime == "SHORT_GAMMA_TREND",
            "conf": conf, "big": abs(move) >= ARM_MULT * median(rngs),
            "hit": (move > 0) == (tail > 0)}


def _perm_test(big: list[dict]) -> dict:
    """Shuffle short/long labels among big-move days; where does observed fall?"""
    n_short = sum(r["short"] for r in big)
    if not n_short or n_short == len(big):
        return {"p_low": None, "p_high": None}
    hits = [r["hit"] for r in big]
    obs = sum(h for r, h in zip(big, hits, strict=True) if r["short"]) / n_short
    rng = random.Random(20260721)                     # seeded: reproducible
    lo = hi = 0
    idx = list(range(len(big)))
    for _ in range(N_PERM):
        rng.shuffle(idx)
        rate = sum(hits[j] for j in idx[:n_short]) / n_short
        lo += rate <= obs
        hi += rate >= obs
    return {"observed_short_hit": round(100 * obs, 1),
            "p_low": round(lo / N_PERM, 4), "p_high": round(hi / N_PERM, 4)}


def _universe_report(rows: list[dict]) -> dict:
    big = [r for r in rows if r["big"]]
    n_arm = sum(r["short"] for r in big)
    conf_mix: dict[str, int] = defaultdict(int)
    for r in rows:
        conf_mix[r["conf"]] += 1
    return {
        "rows": len(rows), "big_move_days": len(big),
        "armed_short_gamma_n": n_arm,
        "confidence_mix": dict(conf_mix),
        "verdict_gate": ("UNDERPOWERED_PENDING" if n_arm < 100 else "POWERED"),
        "card_hit_pct": (round(100 * sum(r["hit"] for r in big if r["short"]) / n_arm, 1)
                         if n_arm else None),
        "long_gamma_placebo_pct": (round(100 * sum(r["hit"] for r in big if not r["short"])
                                         / max(1, len(big) - n_arm), 1)
                                   if len(big) > n_arm else None),
        "permutation": _perm_test(big) if len(big) >= 10 else {"p_low": None, "p_high": None},
    }


def main() -> int:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=120)
    obs = _load_observations(con, None)
    scored = _score_observations(obs, {
        k: {"range_pct": 0.0, "trendiness": 0.0, "high": 0, "low": 0, "close": 0}
        for k in obs})
    reg = {(r["ticker"], r["day"]): (r["regime"], r["confidence"]) for r in scored}
    series = _series(con, {tk for tk, _ in obs})
    con.close()

    rows: list[dict] = []
    for tk, days in series.items():
        ordered = sorted(days)
        rows.extend(r for i in range(len(ordered))
                    if (r := _day_row(tk, days, ordered, i, reg)) is not None)

    rep = {
        "spec": "Gemini adversarial audit 2026-07-21 — windows verbatim, seed 20260721",
        "INDEX_SPY_QQQ_IWM": _universe_report([r for r in rows if r["ticker"] in SENTINELS]),
        "SINGLE_NAMES_ALL_CONF": _universe_report([r for r in rows if r["ticker"] not in SENTINELS]),
        "SINGLE_NAMES_TRUSTED_ONLY": _universe_report(
            [r for r in rows if r["ticker"] not in SENTINELS and r["conf"] == "TRUSTED"]),
        "note_earnings_exclusion": "NOT applied — no earnings calendar held; disclosed "
                                   "as spec deviation, to be added when calendar lands",
        "note_all_conf_equals_trusted": "terrain_read fail-closed drops non-TRUSTED; "
                                       "ALL_CONF bucket == TRUSTED_ONLY by construction",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rep, indent=2), encoding="utf-8")
    print(json.dumps(rep, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
