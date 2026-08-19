"""LP-01 Step 5 — the Find & Prove gate for structure levels.

THE QUESTION: when price touches a structure level, does anything happen that would not have
happened at that time of day anyway?

Until this gate PASSes, the levels stay STRUCTURE-ONLY: displayed as reference prices, never
admitted to the decision path. A level that does not beat its own time-of-day baseline is a
landmark, not an edge, and the honest thing is to keep drawing it and stop implying more.

NO LOOKAHEAD — the three guarantees, each enforced in code:

  1. Every level is FIXED BEFORE the touch that tests it. Prior-session levels (PDH/PDL/PDC and
     the prior-day profile) and the overnight range are complete at 09:30; the opening range is
     complete at ORB_END_MIN. Today's POC/VAH/VAL and the VWAP bands are DELIBERATELY EXCLUDED:
     they evolve intraday, and the values our snapshot exposes are end-of-session, so testing a
     touch against them would let the outcome inform the level.
  2. Forward returns read bars STRICTLY AFTER the touch bar, and never cross a session boundary.
  3. The time-of-day baseline is built from the same forward-return function, so a touch and its
     baseline are the same measurement taken at the same clock minute — the comparison isolates
     the touch, not the hour.

The baseline is the point. Volatility has a strong intraday shape: the open and the close move
more than midday. A "levels work" result that simply rediscovers that shape is the null wearing
a costume, and comparing raw post-touch moves against an all-day average would manufacture one.

USAGE: python tools/lp01_touch_study_v1.py [--tickers SPY,QQQ] [--limit-sessions N]
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sqlite3
import statistics
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from liquidity_models import PlaybookConfig  # noqa: E402
from liquidity_value_engine import (  # noqa: E402
    compute_opening_range,
    get_overnight_levels,
    get_previous_day_levels,
)
from time_et import ET, RTH_END_MINS, RTH_START_MINS  # noqa: E402

# ── PRE-REGISTERED, before any result was seen ───────────────────────────────────────────────
#: Forward horizons in minutes.
HORIZONS = (5, 15, 30)
#: A touch is a bar whose [low, high] contains the level. It must RE-ARM before counting again,
#: otherwise a price resting on a level books one "event" per minute and n is fiction.
REARM_ATR_MULT = 0.25
#: Levels whose value is fixed before any touch that tests them.
CAUSAL_LEVELS = ("PDH", "PDL", "PDC", "PD_POC", "PD_VAH", "PD_VAL",
                 "ON_HIGH", "ON_LOW", "ORB_HIGH", "ORB_LOW", "ORB_MID")
RTH_OPEN_MIN, RTH_CLOSE_MIN = int(RTH_START_MINS), int(RTH_END_MINS)
ORB_END_MIN = RTH_OPEN_MIN + 15  # 09:45 ET — opening-range complete (width, not a second open)

#: PLACEBO — the control that decides whether this study measured LEVELS or measured its own
#: selection rule. A touch requires the bar's [low, high] to CONTAIN the level, so touches
#: preferentially select WIDE-RANGE bars; bar range is autocorrelated with forward volatility, so
#: volatility clustering alone produces a positive effect with no level information at all. The
#: time-of-day baseline controls for the clock, not for the bar's own volatility state.
#: Placebo levels are the real levels displaced by a random offset: same count, same session,
#: same neighbourhood, same touch mechanism — everything except being a structure level. If the
#: placebo reproduces the effect, the effect is the METHOD, and the gate must FAIL.
PLACEBO_OFFSET_PCT = (0.003, 0.012)   # displaced far enough not to be the level, near enough to be touched
PLACEBO_SEED = 20260730

#: H1 (the hypothesis this gate tests): a touch is followed by a LARGER absolute forward move
#: than the same clock minute produces on an ordinary bar — i.e. the level marks a decision
#: point. Reported two-sided; a significant move in the opposite direction (levels DAMPEN) is a
#: real finding and is reported as such, but it does not PASS this gate, which was registered
#: for H1.
PASS = {
    "min_events_per_horizon": 200,
    "min_abs_cohens_d": 0.10,
    "bootstrap_ci_excludes_zero": True,
    "min_horizons_agreeing": 2,          # of 3
    "must_hold_out_of_sample": True,     # first half vs second half by session date
    # The real levels must beat DISPLACED levels by this much of an effect, at every horizon
    # that passes. Without it, a positive result is indistinguishable from the selection rule.
    "min_effect_over_placebo": 0.05,
}
BOOTSTRAP_N = 2000
BOOTSTRAP_SEED = 20260730             # fixed: the study must reproduce exactly


def _rows(con: sqlite3.Connection, ticker: str) -> list[dict]:
    # session-universe-ok: LP-01 touch study; bars are session-gated by the study's ET window logic downstream of this raw read
    q = ("SELECT bar_start_ts_utc, open, high, low, close, volume FROM price_bars_1m "
         "WHERE ticker=? ORDER BY bar_start_ts_utc ASC")
    out = []
    for ts, o, h, l, c, v in con.execute(q, (ticker,)):
        if None in (ts, o, h, l, c):
            continue
        dt = datetime.fromtimestamp(float(ts), ET)
        out.append({"dt": dt, "datetime": int(float(ts) * 1000), "open": float(o),
                    "high": float(h), "low": float(l), "close": float(c),
                    "volume": float(v or 0.0), "min_of_day": dt.hour * 60 + dt.minute})
    return out


def _levels_for_session(all_bars: list[dict], sess: date) -> dict:
    """Levels fixed before the session (or by ORB_END_MIN), via the ACCEPTED Step 1/2 engine.

    Recomputing them here would create a second producer of numbers the engine owns (RC-80) and
    would test something the console does not display.
    """
    cfg = PlaybookConfig()
    # Only the recent window can matter: the engine needs the PRIOR TRADING SESSION (RC-153) plus
    # this session's overnight and opening range. 10 calendar days spans any weekend or holiday
    # run while keeping this O(window) instead of O(all history) per session.
    lo = sess - timedelta(days=10)
    hist = [b for b in all_bars if lo <= b["dt"].date() <= sess]
    prev = get_previous_day_levels(hist, sess, cfg) or {}
    over = get_overnight_levels(hist, sess) or {}
    orb = compute_opening_range(hist, sess, cfg) or {}
    lv = {
        "PDH": prev.get("pdh"), "PDL": prev.get("pdl"), "PDC": prev.get("pdc"),
        "PD_POC": prev.get("pd_poc"), "PD_VAH": prev.get("pd_vah"), "PD_VAL": prev.get("pd_val"),
        "ON_HIGH": over.get("overnight_high"), "ON_LOW": over.get("overnight_low"),
        "ORB_HIGH": orb.get("orb_high"), "ORB_LOW": orb.get("orb_low"),
        "ORB_MID": orb.get("orb_mid"),
    }
    return {k: float(v) for k, v in lv.items()
            if v is not None and isinstance(v, (int, float)) and math.isfinite(float(v))}


def _forward_ret(session_bars: list[dict], i: int, h: int) -> float | None:
    """Return from bar i's close to the close h bars later, WITHIN this session only."""
    j = i + h
    if j >= len(session_bars):
        return None                       # no cross-session forward return, ever
    c0 = session_bars[i]["close"]
    if c0 <= 0:
        return None
    return (session_bars[j]["close"] - c0) / c0


def _placebo_levels(real: dict, rnd: random.Random) -> dict:
    """Same count, same neighbourhood, displaced off the structure. The control arm."""
    out = {}
    for name, val in real.items():
        sign = 1 if rnd.random() < 0.5 else -1
        pct = rnd.uniform(*PLACEBO_OFFSET_PCT)
        out[name] = val * (1.0 + sign * pct)
    return out


def run(tickers: list[str], limit_sessions: int | None) -> dict:
    con = sqlite3.connect(f"file:{REPO / 'data' / 'ed_console.db'}?mode=ro", uri=True)
    touches: list[dict] = []
    placebo_touches: list[dict] = []
    baseline: dict[int, dict[int, list[float]]] = {h: {} for h in HORIZONS}
    sessions_used: list[str] = []
    prnd = random.Random(PLACEBO_SEED)

    for tk in tickers:
        bars = _rows(con, tk)
        if not bars:
            continue
        by_sess: dict[date, list[dict]] = {}
        for b in bars:
            if RTH_OPEN_MIN <= b["min_of_day"] < RTH_CLOSE_MIN:
                by_sess.setdefault(b["dt"].date(), []).append(b)
        sess_dates = sorted(by_sess)
        if limit_sessions:
            sess_dates = sess_dates[-limit_sessions:]
        for sess in sess_dates:
            sb = by_sess[sess]
            if len(sb) < max(HORIZONS) + 30:
                continue
            lv = _levels_for_session(bars, sess)
            if not lv:
                continue
            sessions_used.append(f"{tk}:{sess.isoformat()}")

            # time-of-day baseline: EVERY bar contributes, touch or not
            for i, b in enumerate(sb):
                for h in HORIZONS:
                    r = _forward_ret(sb, i, h)
                    if r is not None:
                        baseline[h].setdefault(b["min_of_day"], []).append(abs(r))

            rng = statistics.median([b["high"] - b["low"] for b in sb]) or 0.0
            rearm = rng * REARM_ATR_MULT
            # REAL and PLACEBO run through the IDENTICAL scan. Any difference between the arms
            # therefore cannot come from the touch rule, the re-arm rule, the horizon handling or
            # the baseline — only from where the levels sit.
            for arm, levels, sink in (("real", lv, touches),
                                      ("placebo", _placebo_levels(lv, prnd), placebo_touches)):
                armed = {k: True for k in levels}
                for i, b in enumerate(sb):
                    # ORB levels are not knowable before the opening range completes
                    if b["min_of_day"] < ORB_END_MIN:
                        usable = {k: v for k, v in levels.items() if not k.startswith("ORB")}
                    else:
                        usable = levels
                    for name, val in usable.items():
                        inside = b["low"] <= val <= b["high"]
                        if inside and armed.get(name, True):
                            armed[name] = False
                            ev = {"ticker": tk, "session": sess.isoformat(), "level": name,
                                  "arm": arm, "min_of_day": b["min_of_day"], "value": val}
                            keep = False
                            for h in HORIZONS:
                                r = _forward_ret(sb, i, h)
                                ev[f"fwd_{h}"] = r
                                if r is not None:
                                    keep = True
                            if keep:
                                sink.append(ev)
                        elif not inside and abs(b["close"] - val) > rearm:
                            armed[name] = True

    con.close()
    return _analyse(touches, baseline, sessions_used, tickers, placebo_touches)


def _cohens_d(a: list[float], b: list[float]) -> float | None:
    if len(a) < 2 or len(b) < 2:
        return None
    va, vb = statistics.pvariance(a), statistics.pvariance(b)
    pooled = math.sqrt(((len(a) - 1) * va + (len(b) - 1) * vb) / (len(a) + len(b) - 2))
    if pooled <= 0:
        return None
    return (statistics.fmean(a) - statistics.fmean(b)) / pooled


def _boot_ci(diffs: list[float], n: int = BOOTSTRAP_N) -> tuple[float, float] | None:
    if len(diffs) < 30:
        return None
    rnd = random.Random(BOOTSTRAP_SEED)
    means = []
    k = len(diffs)
    for _ in range(n):
        means.append(statistics.fmean([diffs[rnd.randrange(k)] for _ in range(k)]))
    means.sort()
    return means[int(0.025 * n)], means[int(0.975 * n)]


def _paired(touches: list[dict], baseline: dict, h: int) -> tuple[list, list, list]:
    """Each touch paired with the MEAN |forward return| of its own clock minute."""
    obs, base, diff = [], [], []
    for t in touches:
        r = t.get(f"fwd_{h}")
        if r is None:
            continue
        pool = baseline[h].get(t["min_of_day"])
        if not pool or len(pool) < 20:
            continue
        b = statistics.fmean(pool)
        obs.append(abs(r))
        base.append(b)
        diff.append(abs(r) - b)
    return obs, base, diff


def _analyse(touches, baseline, sessions_used, tickers, placebo=None) -> dict:
    placebo = placebo or []
    per_h, agreeing = {}, 0
    for h in HORIZONS:
        obs, base, diff = _paired(touches, baseline, h)
        d = _cohens_d(obs, base)
        ci = _boot_ci(diff)
        p_obs, p_base, _ = _paired(placebo, baseline, h)
        p_d = _cohens_d(p_obs, p_base)
        # The decisive comparison: how much of the effect survives the control arm?
        excess = None if (d is None or p_d is None) else d - p_d
        n_ok = len(obs) >= PASS["min_events_per_horizon"]
        d_ok = d is not None and abs(d) >= PASS["min_abs_cohens_d"]
        ci_ok = ci is not None and (ci[0] > 0 or ci[1] < 0)
        h1 = d is not None and d > 0            # H1: touches move MORE
        placebo_ok = excess is not None and excess >= PASS["min_effect_over_placebo"]
        passed = bool(n_ok and d_ok and ci_ok and h1 and placebo_ok)
        if passed:
            agreeing += 1
        per_h[h] = {
            "n_events": len(obs),
            "mean_abs_fwd_after_touch": statistics.fmean(obs) if obs else None,
            "mean_abs_fwd_tod_baseline": statistics.fmean(base) if base else None,
            "mean_diff": statistics.fmean(diff) if diff else None,
            "cohens_d": d, "bootstrap_ci95_of_diff": ci,
            "placebo_n": len(p_obs), "placebo_cohens_d": p_d, "effect_over_placebo": excess,
            "meets_n": n_ok, "meets_effect": d_ok, "ci_excludes_zero": ci_ok,
            "direction_matches_H1": h1, "beats_placebo": placebo_ok, "horizon_pass": passed,
        }

    # out-of-sample: split by session date, require the same verdict in both halves
    dates = sorted({t["session"] for t in touches})
    oos = {"evaluated": False, "reason": "insufficient sessions"}
    if len(dates) >= 20:
        cut = dates[len(dates) // 2]
        halves = {}
        for name, keep in (("first", lambda s: s < cut), ("second", lambda s: s >= cut)):
            sub = [t for t in touches if keep(t["session"])]
            hh = {}
            for h in HORIZONS:
                o, b, df = _paired(sub, baseline, h)
                dd = _cohens_d(o, b)
                hh[h] = {"n": len(o), "cohens_d": dd, "positive": bool(dd is not None and dd > 0)}
            halves[name] = hh
        consistent = all(
            halves["first"][h]["positive"] == halves["second"][h]["positive"]
            for h in HORIZONS)
        oos = {"evaluated": True, "split_date": cut, "halves": halves, "consistent": consistent}

    verdict = "PASS" if (agreeing >= PASS["min_horizons_agreeing"]
                         and oos.get("evaluated") and oos.get("consistent")) else "FAIL"
    return {
        "study": "lp01_touch_study_v1",
        "question": ("When price touches a structure level, is the forward move larger than the "
                     "same clock minute produces anyway?"),
        "preregistered_pass_criteria": PASS,
        "horizons_min": list(HORIZONS),
        "levels_tested": list(CAUSAL_LEVELS),
        "levels_excluded_for_lookahead": ["TODAY_POC", "TODAY_VAH", "TODAY_VAL",
                                          "VWAP", "VWAP_P1", "VWAP_M1", "VWAP_P2", "VWAP_M2"],
        "tickers": tickers,
        "n_sessions": len(set(sessions_used)),
        "n_touch_events": len(touches),
        "per_horizon": per_h,
        "horizons_passing": agreeing,
        "out_of_sample": oos,
        "verdict": verdict,
        "decision_path_effect": "NONE — structure-only regardless of verdict; this study does "
                                "not admit anything to Decide.",
    }


def _markdown(res: dict) -> str:
    L = [f"# LP-01 Step 5 — touch study ({res['study']})", "",
         f"**VERDICT: {res['verdict']}**", "",
         f"> {res['question']}", "",
         f"- tickers: `{', '.join(res['tickers'])}`",
         f"- sessions: {res['n_sessions']}",
         f"- touch events: {res['n_touch_events']}",
         f"- levels tested: {', '.join(res['levels_tested'])}",
         f"- excluded to avoid lookahead: {', '.join(res['levels_excluded_for_lookahead'])}", "",
         "## Pre-registered PASS criteria", "",
         "```", json.dumps(res["preregistered_pass_criteria"], indent=2), "```", "",
         "## Result by horizon", "",
         "| horizon | n | mean abs fwd (touch) | time-of-day base | Cohen's d | "
         "PLACEBO d | d − placebo | bootstrap CI95 | pass |",
         "|---|---|---|---|---|---|---|---|---|"]
    for h, r in res["per_horizon"].items():
        f = lambda x, p=6: "—" if x is None else f"{x:.{p}f}"  # noqa: E731
        ci = r["bootstrap_ci95_of_diff"]
        L.append(f"| {h}m | {r['n_events']} | {f(r['mean_abs_fwd_after_touch'])} | "
                 f"{f(r['mean_abs_fwd_tod_baseline'])} | {f(r['cohens_d'], 3)} | "
                 f"{f(r.get('placebo_cohens_d'), 3)} | {f(r.get('effect_over_placebo'), 3)} | "
                 f"{'—' if not ci else f'[{ci[0]:.6f}, {ci[1]:.6f}]'} | "
                 f"{'YES' if r['horizon_pass'] else 'no'} |")
    L += ["", "### Placebo control", "",
          "Touches select bars whose range CONTAINS the level, so they preferentially sample "
          "wide-range bars — and range is autocorrelated with forward volatility. Volatility "
          "clustering alone therefore produces a positive effect with no level information. The "
          "placebo arm displaces every level by a random 0.3–1.2% and runs the identical scan; "
          "whatever it reproduces is the METHOD, not the levels."]
    oos = res["out_of_sample"]
    L += ["", "## Out-of-sample (split by session date)", ""]
    if oos.get("evaluated"):
        L.append(f"- split at `{oos['split_date']}`, consistent: **{oos['consistent']}**")
        for half, hh in oos["halves"].items():
            L.append(f"  - {half}: " + ", ".join(
                f"{h}m d={'—' if v['cohens_d'] is None else format(v['cohens_d'], '.3f')} (n={v['n']})"
                for h, v in hh.items()))
    else:
        L.append(f"- not evaluated: {oos.get('reason')}")
    L += ["", "## Disposition", "",
          f"- **{res['verdict']}** against the pre-registered criteria.",
          f"- Decision-path effect: {res['decision_path_effect']}"]
    if res["verdict"] != "PASS":
        L += ["- The levels remain **structure-only**: they are displayed as reference prices "
              "and are NOT admitted to the decision path. Decide stays WAIT.",
              "- A failure here is not a defect. It is the search working: the levels are "
              "landmarks until something measures otherwise."]
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", default="SPY,QQQ,IWM")
    ap.add_argument("--limit-sessions", type=int, default=None)
    a = ap.parse_args()
    res = run([t.strip().upper() for t in a.tickers.split(",") if t.strip()], a.limit_sessions)
    out_dir = REPO / "reports"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "lp01_touch_study_v1.json").write_text(
        json.dumps(res, indent=2, default=str), encoding="utf-8")
    (out_dir / "lp01_touch_study_v1.md").write_text(_markdown(res), encoding="utf-8")
    print(f"verdict={res['verdict']} sessions={res['n_sessions']} touches={res['n_touch_events']}")
    for h, r in res["per_horizon"].items():
        print(f"  {h}m n={r['n_events']} d={r['cohens_d']} pass={r['horizon_pass']}")
    print(f"wrote {out_dir / 'lp01_touch_study_v1.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
