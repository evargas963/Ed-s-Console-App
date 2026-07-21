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
            out[(tk, day)] = {"range_pct": rng, "trendiness": trend,
                              "high": a["hi"], "low": a["lo"], "close": a["c"]}
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


#: SpotGamma's published SPX stats (2019-05-10..2024-05-28) — EXTERNAL benchmark only,
#: never a pass bar: https://support.spotgamma.com/hc/en-us/articles/31209900542867
SG_BENCH = {"call_held": 83.0, "call_close_below": 88.0,
            "put_held": 89.0, "put_close_above": 93.0}


def wall_hold_stats(rows: list[dict]) -> dict:
    """Hold/close-side rates for 10:00-ET walls vs the rest-of-session extremes.

    Counts only walls on the working side of spot at observation (call wall above,
    put wall below) — a wall already breached at 10:00 makes 'held' meaningless.
    """
    cn = ch = ccb = pn = ph = pca = 0
    for r in rows:
        cw, pw, spot = r.get("call_wall"), r.get("put_wall"), r.get("spot")
        hi, lo, close = r.get("high"), r.get("low"), r.get("close")
        if None in (spot, hi, lo, close):
            continue
        if cw is not None and cw > spot:
            cn += 1
            ch += hi <= cw
            ccb += close <= cw
        if pw is not None and pw < spot:
            pn += 1
            ph += lo >= pw
            pca += close >= pw
    pct = lambda h, n: round(100.0 * h / n, 1) if n else None  # noqa: E731
    return {"call_n": cn, "call_held_pct": pct(ch, cn), "call_close_below_pct": pct(ccb, cn),
            "put_n": pn, "put_held_pct": pct(ph, pn), "put_close_above_pct": pct(pca, pn),
            "spotgamma_spx_benchmark": SG_BENCH}


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
        # Wall stats use ALL scored rows (no median filter needed) — TRUSTED split is
        # the honest one: narrow-chain walls are strike-truncated by construction.
        "wall_hold_all": wall_hold_stats(scored),
        "wall_hold_trusted": wall_hold_stats(
            [r for r in scored if r["confidence"] == "TRUSTED"]),
        "median_trendiness_short": round(median([r["trendiness"] for r in rows
                                                 if r["regime"] == "SHORT_GAMMA_TREND"]), 3)
        if any(r["regime"] == "SHORT_GAMMA_TREND" for r in rows) else None,
        "median_trendiness_long": round(median([r["trendiness"] for r in rows
                                                if r["regime"] == "LONG_GAMMA_CHOP"]), 3)
        if any(r["regime"] == "LONG_GAMMA_CHOP" for r in rows) else None,
    }


def _wall_line(name: str, w: dict) -> str:
    def v(x):
        return "—" if x is None else f"{x}%"
    return (f"| {name} | {w['call_n']} | {v(w['call_held_pct'])} | "
            f"{v(w['call_close_below_pct'])} | {w['put_n']} | {v(w['put_held_pct'])} | "
            f"{v(w['put_close_above_pct'])} |")


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
        "## Wall hold rates (10:00 ET walls vs rest-of-session)",
        "",
        "| slice | call n | call held% | close≤CW% | put n | put held% | close≥PW% |",
        "|---|---|---|---|---|---|---|",
        _wall_line("ALL rows", rep["wall_hold_all"]),
        _wall_line("TRUSTED only", rep["wall_hold_trusted"]),
        "",
        f"_External benchmark (SpotGamma SPX 2019-2024, different walls/market — context, "
        f"not a pass bar): call held {SG_BENCH['call_held']}% / close below "
        f"{SG_BENCH['call_close_below']}%; put held {SG_BENCH['put_held']}% / close above "
        f"{SG_BENCH['put_close_above']}%._",
        "",
        "_Bar to clear: beat the placebo, not 50%. Narrow-chain rows are structurally "
        "LOW_CONFIDENCE (20-strike history) — the TRUSTED row is the honest one._",
    ]
    return "\n".join(L) + "\n"




# ── PDCA: the decision rules live HERE, so the card treats itself ────────────
# TQM's heart (operator 2026-07-20): a thermometer nobody treats is not a quality loop.
# Every daily run appends one line of history, computes the rolling window, and prints a
# VERDICT with the rule that fired. Thresholds are operator policy — change them here,
# with a comment, never ad-hoc.
HISTORY = ROOT / "reports" / "terrain_scorecard_history.jsonl"
PDCA_WINDOW_SESSIONS = 20          # rolling window before ACT decisions have footing
PDCA_PROMOTE_PTS = 5.0             # gap >= +5pts  -> promote toward the economic test
PDCA_ADJUST_PTS = -5.0             # gap <= -5pts  -> input change via registered tests


def pdca_verdict(gap_pts: float | None, sessions: int) -> tuple[str, str]:
    """(colour, action) from the rolling TRUSTED-minus-placebo gap. Pure; unit-tested."""
    if sessions < PDCA_WINDOW_SESSIONS:
        return ("YELLOW", f"ACCUMULATE — {sessions}/{PDCA_WINDOW_SESSIONS} sessions in "
                          f"window; no ACT decision until it fills (Deming: don't tamper "
                          f"on common-cause noise)")
    if gap_pts is None:
        return ("RED", "CHECK BROKEN — window full but no TRUSTED rows scored; "
                       "capture/coverage is the defect, fix DO before judging the signal")
    if gap_pts >= PDCA_PROMOTE_PTS:
        return ("GREEN", f"PROMOTE — signal beats placebo by {gap_pts:+.1f}pts over "
                         f"{PDCA_WINDOW_SESSIONS} sessions; advance to the FP-64 "
                         f"economic/sizing test")
    if gap_pts <= PDCA_ADJUST_PTS:
        return ("RED", f"ADJUST INPUTS — {gap_pts:+.1f}pts below placebo; run the "
                       f"registered input tests (volume-weighting, single-name sign "
                       f"split) — never ad-hoc tweaks")
    return ("YELLOW", f"REFINE MEASUREMENT — gap {gap_pts:+.1f}pts is inside the noise "
                      f"band; next registered refinement is tail-quantile scoring "
                      f"(the literature says this signal lives in tails)")


def _todays_coverage() -> int:
    """How many tickers got their wide capture today — the DO-step health number."""
    from calibration.option_chain_morning_full import et_date_and_mins
    day, _ = et_date_and_mins()
    try:
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=30)
        n = con.execute("SELECT COUNT(*) FROM option_chain_morning_full WHERE et_date=?",
                        (day,)).fetchone()[0]
        con.close()
        return int(n)
    except sqlite3.Error:
        return 0


def _append_history(rep: dict, day: str, coverage: int) -> list[dict]:
    """One line per ET day (rerun overwrites that day); returns full history."""
    hist: list[dict] = []
    if HISTORY.exists():
        for ln in HISTORY.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(ln)
            except ValueError:
                continue
            if row.get("day") != day:
                hist.append(row)
    t = rep["trusted_only"]
    hist.append({"day": day, "coverage": coverage,
                 "trusted_n": t["n"], "trusted_hit_pct": t["hit_pct"],
                 "placebo_n": rep["placebo_persistence"]["n"],
                 "placebo_hit_pct": rep["placebo_persistence"]["hit_pct"]})
    hist.sort(key=lambda r: r.get("day", ""))
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    HISTORY.write_text("\n".join(json.dumps(r) for r in hist) + "\n", encoding="utf-8")
    return hist


def rolling_gap(hist: list[dict], window: int = PDCA_WINDOW_SESSIONS
                ) -> tuple[float | None, int]:
    """Aggregate TRUSTED-vs-placebo gap over the last `window` sessions (hit-weighted)."""
    tail = hist[-window:]
    th = tn = ph = pn = 0.0
    for r in tail:
        if r.get("trusted_hit_pct") is not None and r.get("trusted_n"):
            th += r["trusted_hit_pct"] * r["trusted_n"] / 100.0
            tn += r["trusted_n"]
        if r.get("placebo_hit_pct") is not None and r.get("placebo_n"):
            ph += r["placebo_hit_pct"] * r["placebo_n"] / 100.0
            pn += r["placebo_n"]
    if tn == 0 or pn == 0:
        return None, len(tail)
    return 100.0 * th / tn - 100.0 * ph / pn, len(tail)


def render_pdca(coverage: int, gap: float | None, sessions: int) -> str:
    colour, action = pdca_verdict(gap, sessions)
    return "\n".join([
        "", "## PDCA — the loop, self-treating", "",
        f"- **DO (coverage)**: {coverage} tickers wide-captured today "
        f"({'healthy' if coverage >= 40 else 'DEGRADED — expect ~50; the capture is the defect today'})",
        f"- **CHECK (window)**: {sessions}/{PDCA_WINDOW_SESSIONS} sessions accumulated; "
        f"rolling TRUSTED−placebo gap: {f'{gap:+.1f}pts' if gap is not None else '—'}",
        f"- **ACT** → **{colour}**: {action}", "",
        "_Rules: ≥+5pts promote · −5..+5 refine measurement · ≤−5 adjust inputs via "
        "register · window unfilled = accumulate. Single days never trigger ACT "
        "(special-vs-common cause)._",
    ]) + "\n"


def main() -> int:
    # Windows consoles default to cp1252; the report legitimately uses ≤/≥/−.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=None, help="YYYY-MM-DD lower bound (ET days)")
    args = ap.parse_args()
    rep = run(args.since)
    from calibration.option_chain_morning_full import et_date_and_mins
    day, _ = et_date_and_mins()
    coverage = _todays_coverage()
    hist = _append_history(rep, day, coverage)
    gap, sessions = rolling_gap(hist)
    md = render_md(rep) + render_pdca(coverage, gap, sessions)
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    rep["pdca"] = {"coverage": coverage, "window_sessions": sessions,
                   "rolling_gap_pts": round(gap, 2) if gap is not None else None,
                   "verdict": pdca_verdict(gap, sessions)}
    OUT_JSON.write_text(json.dumps(rep, indent=2), encoding="utf-8")
    OUT_MD.write_text(md, encoding="utf-8")
    print(md)
    print("wrote", OUT_MD, "and", OUT_JSON, "and", HISTORY)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
