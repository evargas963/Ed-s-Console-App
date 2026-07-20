#!/usr/bin/env python3
"""Terrain regime backtest + daily scorecard (read-only; writes only reports/).

WHAT IT SCORES. For each (ticker, ET day): recompute the terrain regime from the stored
chain nearest 10:00 ET, then measure what the session actually did from price_bars_1m
(10:15 -> 15:55 ET). The regime's claim (Baltussen JFE 2021; Barbon-Buraschi 2021; CBOE
Dim-Eraker-Vilkov):

    LONG_GAMMA_CHOP   -> dealers dampen -> LOWER realized range than typical for the name
    SHORT_GAMMA_TREND -> dealers amplify -> HIGHER realized range than typical

"Typical" is the ticker's own median day-range over the scored history, so every name is
judged against itself (the ATR lesson: cross-ticker absolute thresholds lie).

PLACEBO (binding: every level study needs one): persistence — predict today's range class
from YESTERDAY'S realized class. Any real signal must beat it; range is autocorrelated,
so beating 50% is not the bar, beating the placebo is.

HONESTY GATES. Non-sentinel rows recompute from the 20-strike money-path chain, which the
confidence verdict marks LOW_CONFIDENCE_NARROW_CHAIN — reported SEPARATELY, never pooled
with TRUSTED rows. The report also splits sentinels vs single names, which doubles as the
first half of the registered single-name sign-assumption test (due 2026-08-03).

Usage:
    python tools/terrain_backtest_report_v1.py                # full history
    python tools/terrain_backtest_report_v1.py --since 2026-06-01
Writes reports/terrain_backtest_latest.{md,json}; exit 0 on success.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from terrain_engine import compute_terrain  # noqa: E402
from time_et import ET  # noqa: E402

DB = ROOT / "data" / "ed_console.db"
OUT_MD = ROOT / "reports" / "terrain_backtest_latest.md"
OUT_JSON = ROOT / "reports" / "terrain_backtest_latest.json"

SENTINELS = {"SPY", "QQQ", "IWM"}
#: Chain selection window around 10:00 ET — late enough for opening OI/greeks to settle,
#: early enough that the whole session remains to be predicted.
OBS_LO_MIN, OBS_HI_MIN = 9 * 60 + 45, 10 * 60 + 15
#: Realized window: strictly AFTER observation (no lookahead), to just before the close.
REAL_LO_MIN, REAL_HI_MIN = 10 * 60 + 15, 15 * 60 + 55


def _et_day_and_min(ts: float) -> tuple[str, int]:
    d = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(ET)
    return d.strftime("%Y-%m-%d"), d.hour * 60 + d.minute


def _load_observations(con: sqlite3.Connection, since: str | None):
    """One (ticker, day) observation: the stored chain nearest 10:00 ET."""
    rows = con.execute(
        "SELECT ticker, ts_utc, spot, option_chain_json FROM snapshots "
        "WHERE timeframe='1m' AND option_chain_json IS NOT NULL AND spot IS NOT NULL "
        "ORDER BY ticker, ts_utc"
    )
    best: dict[tuple[str, str], tuple[int, float, float, str]] = {}
    for tk, ts, spot, chain in rows:
        day, mins = _et_day_and_min(ts)
        if since and day < since:
            continue
        if not (OBS_LO_MIN <= mins <= OBS_HI_MIN):
            continue
        dist = abs(mins - 600)
        key = (tk, day)
        if key not in best or dist < best[key][0]:
            best[key] = (dist, ts, spot, chain)
    return best


def _load_realized(con: sqlite3.Connection, tickers: set[str], since: str | None):
    """Per (ticker, day): range% and trendiness over the post-observation RTH window."""
    out: dict[tuple[str, str], dict] = {}
    for tk in sorted(tickers):
        cur = con.execute(
            "SELECT bar_start_ts_utc, open, high, low, close FROM price_bars_1m "
            "WHERE ticker=? ORDER BY bar_start_ts_utc", (tk,)
        )
        acc: dict[str, dict] = {}
        for ts, o, h, low, c in cur:
            day, mins = _et_day_and_min(ts)
            if since and day < since:
                continue
            if not (REAL_LO_MIN <= mins <= REAL_HI_MIN):
                continue
            a = acc.setdefault(day, {"o": o, "hi": h, "lo": low, "c": c})
            a["hi"] = max(a["hi"], h)
            a["lo"] = min(a["lo"], low)
            a["c"] = c
        for day, a in acc.items():
            if not a["o"] or a["o"] <= 0:
                continue
            rng = (a["hi"] - a["lo"]) / a["o"] * 100.0
            width = a["hi"] - a["lo"]
            trend = abs(a["c"] - a["o"]) / width if width > 0 else 0.0
            out[(tk, day)] = {"range_pct": rng, "trendiness": trend}
    return out


def _score_observations(obs: dict, realized: dict) -> list[dict]:
    """Recompute terrain per observation; keep only rows with a definite regime."""
    scored = []
    for (tk, day), (_d, _ts, spot, chain_raw) in sorted(obs.items()):
        real = realized.get((tk, day))
        if real is None:
            continue
        try:
            contracts = json.loads(chain_raw)
        except ValueError:
            continue
        snap = compute_terrain(tk, contracts, float(spot))
        if snap.regime not in ("LONG_GAMMA_CHOP", "SHORT_GAMMA_TREND"):
            continue
        scored.append({
            "ticker": tk, "day": day, "regime": snap.regime,
            "confidence": snap.confidence, "spot": float(spot),
            "gamma_flip": snap.gamma_flip, "call_wall": snap.call_wall,
            "put_wall": snap.put_wall, **real,
        })
    return scored


def _classify_and_hit(scored: list[dict]) -> tuple[list[dict], dict[str, float]]:
    """Per-ticker own-median split (>=4 days) + regime hit flag on each kept row."""
    by_tk: dict[str, list[float]] = defaultdict(list)
    for r in scored:
        by_tk[r["ticker"]].append(r["range_pct"])
    med = {tk: median(v) for tk, v in by_tk.items() if len(v) >= 4}
    rows = [r for r in scored if r["ticker"] in med]
    for r in rows:
        r["range_class_high"] = r["range_pct"] > med[r["ticker"]]
        r["hit"] = (r["regime"] == "SHORT_GAMMA_TREND") == r["range_class_high"]
    return rows, med


def _placebo_persistence(rows: list[dict]) -> tuple[int, int]:
    """Hits/n for 'yesterday's realized class predicts today's', per ticker."""
    p_hit = p_n = 0
    by_tk_rows: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_tk_rows[r["ticker"]].append(r)
    for rs in by_tk_rows.values():
        rs.sort(key=lambda r: r["day"])
        for prev, cur in zip(rs, rs[1:], strict=False):
            p_n += 1
            p_hit += prev["range_class_high"] == cur["range_class_high"]
    return p_hit, p_n


def run(since: str | None) -> dict:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=120)
    t0 = time.time()
    obs = _load_observations(con, since)
    realized = _load_realized(con, {tk for tk, _ in obs}, since)
    scored = _score_observations(obs, realized)
    con.close()

    rows, med = _classify_and_hit(scored)
    p_hit, p_n = _placebo_persistence(rows)

    def bucket(pred):
        sub = [r for r in rows if pred(r)]
        n = len(sub)
        return {"n": n, "hit_pct": round(100 * sum(r["hit"] for r in sub) / n, 1) if n else None}

    return {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "since": since, "runtime_sec": round(time.time() - t0, 1),
        "observations": len(obs), "scored_ticker_days": len(rows),
        "tickers": len(med),
        "claim": "SHORT_GAMMA_TREND -> above-own-median range; LONG_GAMMA_CHOP -> below",
        "overall": bucket(lambda _r: True),
        "trusted_only": bucket(lambda r: r["confidence"] == "TRUSTED"),
        "narrow_chain_only": bucket(lambda r: r["confidence"] != "TRUSTED"),
        "sentinels": bucket(lambda r: r["ticker"] in SENTINELS),
        "single_names": bucket(lambda r: r["ticker"] not in SENTINELS),
        "long_gamma_days": bucket(lambda r: r["regime"] == "LONG_GAMMA_CHOP"),
        "short_gamma_days": bucket(lambda r: r["regime"] == "SHORT_GAMMA_TREND"),
        "placebo_persistence": {"n": p_n,
                                "hit_pct": round(100 * p_hit / p_n, 1) if p_n else None},
        "median_trendiness_short": round(median([r["trendiness"] for r in rows
                                                 if r["regime"] == "SHORT_GAMMA_TREND"]), 3)
        if any(r["regime"] == "SHORT_GAMMA_TREND" for r in rows) else None,
        "median_trendiness_long": round(median([r["trendiness"] for r in rows
                                                if r["regime"] == "LONG_GAMMA_CHOP"]), 3)
        if any(r["regime"] == "LONG_GAMMA_CHOP" for r in rows) else None,
    }


def render_md(rep: dict) -> str:
    def line(name, b):
        return (f"| {name} | {b['n']} | {b['hit_pct'] if b['hit_pct'] is not None else '—'}% |"
                if isinstance(b, dict) else "")
    L = [
        "# Terrain regime backtest — " + rep["generated_utc"],
        "",
        f"Scored **{rep['scored_ticker_days']}** ticker-days across **{rep['tickers']}** "
        f"tickers ({rep['runtime_sec']}s). Claim: {rep['claim']}.",
        "",
        "| slice | n | hit% |", "|---|---|---|",
        line("ALL", rep["overall"]),
        line("TRUSTED only", rep["trusted_only"]),
        line("narrow-chain only (LOW_CONFIDENCE — caveated)", rep["narrow_chain_only"]),
        line("sentinels (SPY/QQQ/IWM)", rep["sentinels"]),
        line("single names", rep["single_names"]),
        line("long-gamma days", rep["long_gamma_days"]),
        line("short-gamma days", rep["short_gamma_days"]),
        line("PLACEBO: yesterday's class persists", rep["placebo_persistence"]),
        "",
        f"Trendiness (|close-open|/range) median — short-gamma days: "
        f"{rep['median_trendiness_short']}, long-gamma days: {rep['median_trendiness_long']} "
        "(mechanism check: short-gamma days should trend more).",
        "",
        "_Bar to clear: beat the placebo, not 50%. Narrow-chain rows are structurally "
        "LOW_CONFIDENCE (20-strike history) — the TRUSTED row is the honest one._",
    ]
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=None, help="YYYY-MM-DD lower bound (ET days)")
    args = ap.parse_args()
    rep = run(args.since)
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(rep, indent=2), encoding="utf-8")
    OUT_MD.write_text(render_md(rep), encoding="utf-8")
    print(render_md(rep))
    print("wrote", OUT_MD, "and", OUT_JSON)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
