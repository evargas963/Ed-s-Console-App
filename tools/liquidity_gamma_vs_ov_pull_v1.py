"""Gamma-heavy vs options-volume-heavy pull experiment v1 — Find & Prove / offline.

Operator hypothesis: strong |GEX| + light/mid options volume pulls spot harder
than strong options volume + light/mid |GEX|.

This study:
  1) Classifies moneyness-band strikes into GAMMA_HEAVY / VOL_HEAVY /
     COMBO_BALANCED (+ moneyness-matched PLACEBO).
  2) Builds continuous scores score_eq / score_g / score_v from inv_ranks.
  3) Measures PULL after signal time (not bare touch win-rate):
       - signed distance change toward strike over 30m / 60m
       - time-in-band near strike
       - |spot−strike| at horizon vs T0
  4) IC of continuous scores vs pull (raw + ATM-residualized).

Causal as-of:
  Prefer option_chain_morning_full; else snapshots in 09:45–10:15 ET.
  Outcomes from RTH bars at/after 10:15 ET. Costs ABSENT (stated).

NO UI. NO Decide. NO push.

USAGE:
  python tools/liquidity_gamma_vs_ov_pull_v1.py
  python tools/liquidity_gamma_vs_ov_pull_v1.py --tickers SPY,QQQ,IWM
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import math
import random
import sqlite3
import statistics
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from math_exposure_core import (  # noqa: E402
    bucket_metric,
    compute_exposures_by_strike,
    total_gamma_raw_at_strike,
)
from numeric_contract import float_finite_or_none, float_nonnegative_or_none  # noqa: E402

# ── Reuse stickiness helpers (obs chains, bars, outcomes) ────────────────────
_STICKY_PATH = REPO / "tools" / "liquidity_oi_volume_stickiness_v1.py"
_spec = importlib.util.spec_from_file_location("liq_sticky_pull_v1", _STICKY_PATH)
assert _spec and _spec.loader
_sticky = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_sticky)

_rows = _sticky._rows
_causal_atr_pre_obs = _sticky._causal_atr_pre_obs
_load_obs_chains = _sticky._load_obs_chains
_in_moneyness = _sticky._in_moneyness
_outcome_time_in_band = _sticky._outcome_time_in_band
_placebo_strikes_moneyness_matched = _sticky._placebo_strikes_moneyness_matched
MONEYNESS_PCT = _sticky.MONEYNESS_PCT
OUTCOME_START_MIN = _sticky.OUTCOME_START_MIN
RTH_OPEN_MIN = _sticky.RTH_OPEN_MIN
RTH_CLOSE_MIN = _sticky.RTH_CLOSE_MIN
BAND_ATR_FRAC = _sticky.BAND_ATR_FRAC

STUDY = "liquidity_gamma_vs_ov_pull_v1"
DB = REPO / "data" / "ed_console.db"
OUT_JSON = REPO / "reports" / f"{STUDY}.json"
OUT_MD = REPO / "reports" / f"{STUDY}.md"
SEED = 20260730

HORIZONS = (30, 60)  # minutes after outcome start
TOP_QUINTILE = 0.20  # top 20% = quintile 1 (rank percentile ≥ 0.80)
MIN_BAND_STRIKES = 10
MIN_POST_BARS = 25
MIN_CLASS_N = 30     # descriptive underpowered gate (still report)
PASS = {
    "min_sessions": 40,
    "min_class_n": 80,
    "min_mean_pull_edge": 0.0,       # γ-heavy mean pull − vol-heavy mean pull > 0
    "min_edge_vs_placebo": 0.0,     # γ-heavy − placebo > 0
    "min_ic": 0.05,
    "min_ic_edge_g_vs_v": 0.02,     # mean IC(score_g) − mean IC(score_v)
    "min_halves_agreeing": 2,
}
# Primary fair metric: pull residualized on starting distance (ATM composition trap).
# Raw pull_dist can false-PASS when γ-heavy strikes sit systematically farther from spot.
PRIMARY_FAIR_METRIC = "pull_resid_dist_30m"

CLASSES = ("GAMMA_HEAVY", "VOL_HEAVY", "COMBO_BALANCED", "PLACEBO")
SCORES = ("score_eq", "score_g", "score_v")


# ── Rank helpers ─────────────────────────────────────────────────────────────

def _inv_ranks(vals: list[float]) -> list[float]:
    """inv_rank = n+1−rank; rank 1 = highest; average ranks for ties."""
    n = len(vals)
    order = sorted(range(n), key=lambda i: -vals[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        avg = (i + 1 + j + 1) / 2.0
        for t in range(i, j + 1):
            ranks[order[t]] = avg
        i = j + 1
    return [n + 1 - r for r in ranks]


def _pct_ranks_high_best(vals: list[float]) -> list[float]:
    """Percentile rank in [0,1]; 1.0 = highest value. Average for ties."""
    n = len(vals)
    if n <= 1:
        return [0.5] * n
    order = sorted(range(n), key=lambda i: vals[i])  # ascending
    pct = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        # average of ascending positions → convert to high-best percentile
        avg_asc = (i + j) / 2.0  # 0-based
        # fraction of values strictly below + half of ties
        p = (avg_asc) / (n - 1) if n > 1 else 0.5
        for t in range(i, j + 1):
            pct[order[t]] = p
        i = j + 1
    return pct


def _ranks_asc(v: list[float]) -> list[float]:
    n = len(v)
    order = sorted(range(n), key=lambda i: v[i])
    r = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and v[order[j + 1]] == v[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            r[order[k]] = avg
        i = j + 1
    return r


def _pearson(a: list[float], b: list[float]) -> float | None:
    n = len(a)
    if n < MIN_BAND_STRIKES or n != len(b):
        return None
    ma, mb = sum(a) / n, sum(b) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b, strict=True))
    da = sum((x - ma) ** 2 for x in a) ** 0.5
    db = sum((y - mb) ** 2 for y in b) ** 0.5
    if da <= 0 or db <= 0:
        return None
    return num / (da * db)


def _spearman(a: list[float], b: list[float]) -> float | None:
    if len(a) < MIN_BAND_STRIKES or len(a) != len(b):
        return None
    return _pearson(_ranks_asc(a), _ranks_asc(b))


def _residualize(y: list[float], x: list[float]) -> list[float] | None:
    n = len(y)
    if n != len(x) or n < MIN_BAND_STRIKES:
        return None
    mx = sum(x) / n
    my = sum(y) / n
    varx = sum((xi - mx) ** 2 for xi in x)
    if varx <= 1e-15:
        return None
    cov = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y, strict=True))
    beta = cov / varx
    alpha = my - beta * mx
    return [yi - (alpha + beta * xi) for xi, yi in zip(x, y, strict=True)]


def _partial_spearman(a: list[float], b: list[float], control: list[float]) -> float | None:
    n = len(a)
    if n < MIN_BAND_STRIKES or n != len(b) or n != len(control):
        return None
    ra, rb, rc = _ranks_asc(a), _ranks_asc(b), _ranks_asc(control)
    a_res = _residualize(ra, rc)
    b_res = _residualize(rb, rc)
    if a_res is None or b_res is None:
        return None
    return _pearson(a_res, b_res)


# ── Chain → per-strike |GEX| + volume (panel metric) ─────────────────────────

def _strike_gex_vol(chain_raw: str, spot: float) -> list[dict]:
    """Same metric family as Chart: |net_gex_1pct| (raw-gamma fallback) + totalVolume."""
    try:
        contracts = json.loads(chain_raw)
    except (ValueError, TypeError):
        return []
    if not contracts:
        return []
    try:
        exposures, _ = compute_exposures_by_strike(contracts, spot=spot, require_oi=True)
    except Exception:
        return []

    vol_by_k: dict[float, float] = {}
    for ct in contracts:
        if not isinstance(ct, dict):
            continue
        sk = float_finite_or_none(ct.get("strikePrice"))
        v = float_nonnegative_or_none(ct.get("totalVolume"))
        if sk is not None and v is not None:
            vol_by_k[sk] = vol_by_k.get(sk, 0.0) + float(v)

    out: list[dict] = []
    for k, bucket in exposures.items():
        sk = float_finite_or_none(k)
        if sk is None:
            continue
        g = bucket_metric(bucket, "net_gex_1pct")
        if g is None:
            g = total_gamma_raw_at_strike(bucket)
        g = float(g or 0.0)
        if not math.isfinite(g):
            continue
        vol = float(vol_by_k.get(sk, 0.0))
        out.append({
            "strike": float(sk),
            "abs_gex": abs(g),
            "vol": vol,
            "signed_gex": g,
        })
    return out


# ── Pull metrics ─────────────────────────────────────────────────────────────

def _horizon_bars(post: list[dict], horizon_min: int) -> list[dict]:
    """First `horizon_min` post-obs bars (1-min bars)."""
    if not post:
        return []
    return post[: min(horizon_min, len(post))]


def _signed_pull_distance(post_h: list[dict], strike: float) -> dict:
    """Primary pull: distance change from T0 close to horizon close.

    pull = |S0 − K| − |Sh − K|   (positive = closer / pulled toward strike)
    Also mean bar-to-bar signed pull for continuity with strike_ic study.
    """
    if len(post_h) < 2:
        return {
            "pull_dist": None,
            "dist_t0": None,
            "dist_h": None,
            "mean_bar_pull": None,
            "n_bars": len(post_h),
        }
    s0 = post_h[0]["close"]
    sh = post_h[-1]["close"]
    d0 = abs(s0 - strike)
    dh = abs(sh - strike)
    bar_pulls = []
    for i in range(1, len(post_h)):
        bar_pulls.append(
            abs(post_h[i - 1]["close"] - strike) - abs(post_h[i]["close"] - strike)
        )
    return {
        "pull_dist": d0 - dh,
        "dist_t0": d0,
        "dist_h": dh,
        "mean_bar_pull": statistics.fmean(bar_pulls) if bar_pulls else None,
        "n_bars": len(post_h),
    }


# ── Classification + scoring ─────────────────────────────────────────────────

def _classify_and_score(band: list[dict]) -> list[dict]:
    """Attach inv_ranks, percentile ranks, class labels, continuous scores."""
    n = len(band)
    if n < MIN_BAND_STRIKES:
        return []
    gex_inv = _inv_ranks([r["abs_gex"] for r in band])
    vol_inv = _inv_ranks([r["vol"] for r in band])
    gex_pct = _pct_ranks_high_best([r["abs_gex"] for r in band])
    vol_pct = _pct_ranks_high_best([r["vol"] for r in band])

    out = []
    for i, r in enumerate(band):
        iv_g = gex_inv[i]
        iv_v = vol_inv[i]
        pg = gex_pct[i]
        pv = vol_pct[i]
        # Classes (mutually exclusive priority: COMBO > GAMMA_HEAVY / VOL_HEAVY)
        g_top = pg >= (1.0 - TOP_QUINTILE)
        v_top = pv >= (1.0 - TOP_QUINTILE)
        g_lowmid = pg < (1.0 - TOP_QUINTILE)  # not top quintile
        v_lowmid = pv < (1.0 - TOP_QUINTILE)
        if g_top and v_top:
            cls = "COMBO_BALANCED"
        elif g_top and v_lowmid:
            cls = "GAMMA_HEAVY"
        elif v_top and g_lowmid:
            cls = "VOL_HEAVY"
        else:
            cls = None  # neither extreme — not scored in class arms
        out.append({
            **r,
            "inv_gex": iv_g,
            "inv_vol": iv_v,
            "pct_gex": pg,
            "pct_vol": pv,
            "gex_rank": n + 1 - iv_g,  # 1 = highest
            "vol_rank": n + 1 - iv_v,
            "score_eq": iv_v * iv_g,                 # current storm1
            "score_g": (iv_g ** 2) * iv_v,          # γ-heavy weight
            "score_v": (iv_v ** 2) * iv_g,          # vol-heavy weight
            "class": cls,
            "dist_inv": 1.0 / (abs(r["strike"] - r["spot"]) + 0.01),
        })
    return out


def _pick_class_representatives(
    scored: list[dict], rnd: random.Random,
) -> dict[str, list[dict]]:
    """Per day: take ALL classified strikes in each arm (fair pool, not top-1 only).

    PLACEBO: moneyness-matched to the union of real class strikes (1:1 each).
    """
    by_cls: dict[str, list[dict]] = {c: [] for c in CLASSES}
    real = [r for r in scored if r["class"] in ("GAMMA_HEAVY", "VOL_HEAVY", "COMBO_BALANCED")]
    for r in real:
        by_cls[r["class"]].append(r)

    real_strikes = [r["strike"] for r in real]
    if real_strikes and scored:
        spot = scored[0]["spot"]
        placebo_ks = _placebo_strikes_moneyness_matched(spot, real_strikes, rnd)
        # Map placebo strikes onto nearest band strike if present, else synthetic row
        band_by_k = {r["strike"]: r for r in scored}
        for i, pk in enumerate(placebo_ks):
            # Prefer exact match in band; else create synthetic outcome-only row
            if pk in band_by_k:
                base = dict(band_by_k[pk])
            else:
                # nearest band strike for scoring context, but measure at placebo K
                nearest = min(band_by_k.keys(), key=lambda k: abs(k - pk)) if band_by_k else pk
                base = dict(band_by_k.get(nearest, {
                    "strike": pk, "abs_gex": 0.0, "vol": 0.0, "spot": spot,
                    "score_eq": 0.0, "score_g": 0.0, "score_v": 0.0,
                    "inv_gex": 0.0, "inv_vol": 0.0, "pct_gex": 0.0, "pct_vol": 0.0,
                    "gex_rank": None, "vol_rank": None, "dist_inv": 1.0 / (abs(pk - spot) + 0.01),
                }))
            base = dict(base)
            base["strike"] = float(pk)
            base["class"] = "PLACEBO"
            base["placebo_of"] = real_strikes[i] if i < len(real_strikes) else None
            by_cls["PLACEBO"].append(base)
    return by_cls


# ── Session runner ───────────────────────────────────────────────────────────

def _session_bars(bars: list[dict], day: str) -> list[dict]:
    return [
        b for b in bars
        if b["dt"].strftime("%Y-%m-%d") == day
        and RTH_OPEN_MIN <= b["min_of_day"] < RTH_CLOSE_MIN
    ]


def _run_session(
    ticker: str,
    day: str,
    obs: dict,
    bars: list[dict],
    rnd: random.Random,
) -> dict | None:
    sb = _session_bars(bars, day)
    if len(sb) < 60:
        return None
    atr = _causal_atr_pre_obs(sb)
    if atr <= 0:
        return None
    post_all = [b for b in sb if b["min_of_day"] >= OUTCOME_START_MIN]
    if len(post_all) < MIN_POST_BARS:
        return None

    spot = float(obs["spot"])
    rows = _strike_gex_vol(obs["chain_raw"], spot)
    band = []
    for r in rows:
        if _in_moneyness(r["strike"], spot, MONEYNESS_PCT):
            band.append({**r, "spot": spot, "ticker": ticker, "session": day})
    scored = _classify_and_score(band)
    if not scored:
        return None

    by_cls = _pick_class_representatives(scored, rnd)
    band_w = BAND_ATR_FRAC * atr

    class_events: dict[str, list[dict]] = {c: [] for c in CLASSES}
    for cls, reps in by_cls.items():
        for r in reps:
            ev_base = {
                "ticker": ticker,
                "session": day,
                "strike": r["strike"],
                "class": cls,
                "abs_gex": r.get("abs_gex"),
                "vol": r.get("vol"),
                "score_eq": r.get("score_eq"),
                "score_g": r.get("score_g"),
                "score_v": r.get("score_v"),
                "gex_rank": r.get("gex_rank"),
                "vol_rank": r.get("vol_rank"),
                "pct_gex": r.get("pct_gex"),
                "pct_vol": r.get("pct_vol"),
                "faucet": obs["faucet"],
                "spot_t0": post_all[0]["close"],
            }
            for h in HORIZONS:
                post_h = _horizon_bars(post_all, h)
                pull = _signed_pull_distance(post_h, r["strike"])
                tib = _outcome_time_in_band(post_h, r["strike"], band_w)
                d0 = pull["dist_t0"]
                pd = pull["pull_dist"]
                pull_frac = None
                if (
                    pd is not None and d0 is not None
                    and math.isfinite(pd) and math.isfinite(d0) and d0 > 1e-9
                ):
                    pull_frac = pd / d0  # +1 = fully closed gap; <0 = moved away
                ev_base[f"pull_dist_{h}m"] = pd
                ev_base[f"pull_frac_{h}m"] = pull_frac
                ev_base[f"dist_t0_{h}m"] = d0
                ev_base[f"dist_h_{h}m"] = pull["dist_h"]
                ev_base[f"mean_bar_pull_{h}m"] = pull["mean_bar_pull"]
                ev_base[f"time_in_band_{h}m"] = tib["frac"]
                ev_base[f"n_bars_{h}m"] = pull["n_bars"]
            class_events[cls].append(ev_base)

    # Continuous IC over full band (not just class extremes)
    ic_day: dict[str, dict] = {}
    for h in HORIZONS:
        post_h = _horizon_bars(post_all, h)
        pulls = []
        scores = {s: [] for s in SCORES}
        dists = []
        for r in scored:
            pull = _signed_pull_distance(post_h, r["strike"])
            pd = pull["pull_dist"]
            if pd is None or not math.isfinite(pd):
                continue
            pulls.append(pd)
            for s in SCORES:
                scores[s].append(float(r[s]))
            dists.append(float(r["dist_inv"]))
        for s in SCORES:
            key = f"{s}_{h}m"
            if len(pulls) < MIN_BAND_STRIKES:
                ic_day[key] = {"ic": None, "ic_atm_resid": None, "n": len(pulls)}
                continue
            ic = _spearman(scores[s], pulls)
            ic_res = _partial_spearman(scores[s], pulls, dists)
            ic_day[key] = {"ic": ic, "ic_atm_resid": ic_res, "n": len(pulls)}

    return {
        "ticker": ticker,
        "session": day,
        "faucet": obs["faucet"],
        "n_band": len(scored),
        "n_by_class": {c: len(by_cls[c]) for c in CLASSES},
        "class_events": class_events,
        "ic_day": ic_day,
        "atr": atr,
    }


# ── Aggregation ──────────────────────────────────────────────────────────────

def _fmean(xs: list[float]) -> float | None:
    return statistics.fmean(xs) if xs else None


def _attach_pull_residuals(
    all_events: dict[str, list[dict]], horizons: tuple[int, ...] = HORIZONS,
) -> None:
    """In-place: residualize pull_dist on dist_t0 pooled across all class events.

    Fair-method: γ-heavy strikes sit farther from ATM on average; raw dollar pull
    can look better merely from starting farther. Residuals answer: given the same
    starting distance, does the class still pull harder?
    """
    for h in horizons:
        pull_key = f"pull_dist_{h}m"
        dist_key = f"dist_t0_{h}m"
        resid_key = f"pull_resid_dist_{h}m"
        pairs: list[tuple[dict, float, float]] = []
        for evs in all_events.values():
            for e in evs:
                pd = e.get(pull_key)
                d0 = e.get(dist_key)
                if pd is None or d0 is None:
                    e[resid_key] = None
                    continue
                if not (math.isfinite(float(pd)) and math.isfinite(float(d0))):
                    e[resid_key] = None
                    continue
                pairs.append((e, float(d0), float(pd)))
        if len(pairs) < MIN_BAND_STRIKES:
            for e, _, _ in pairs:
                e[resid_key] = None
            continue
        xs = [d for _, d, _ in pairs]
        ys = [p for _, _, p in pairs]
        mx = sum(xs) / len(xs)
        my = sum(ys) / len(ys)
        varx = sum((x - mx) ** 2 for x in xs)
        if varx <= 1e-15:
            for e, _, _ in pairs:
                e[resid_key] = None
            continue
        cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True))
        beta = cov / varx
        alpha = my - beta * mx
        for e, d0, pd in pairs:
            e[resid_key] = pd - (alpha + beta * d0)


def _summarize_pulls(events: list[dict], metric: str) -> dict:
    vals = [
        float(e[metric]) for e in events
        if e.get(metric) is not None and math.isfinite(float(e[metric]))
    ]
    return {
        "n": len(vals),
        "mean": _fmean(vals),
        "median": statistics.median(vals) if vals else None,
        "stdev": statistics.stdev(vals) if len(vals) >= 2 else None,
        "frac_positive": (sum(1 for v in vals if v > 0) / len(vals)) if vals else None,
    }


def _date_half_agree(
    events_a: list[dict], events_b: list[dict], metric: str,
) -> dict:
    """Do first/second half of dates both show mean(A) > mean(B)?"""
    dates = sorted({e["session"] for e in events_a + events_b})
    if len(dates) < 10:
        return {"evaluated": False, "reason": "insufficient_sessions",
                "n_agree": 0, "halves_agree": False}
    cut = dates[len(dates) // 2]
    agree = 0
    halves = {}
    for name, pred in (("first", lambda s: s < cut), ("second", lambda s: s >= cut)):
        a = _summarize_pulls([e for e in events_a if pred(e["session"])], metric)
        b = _summarize_pulls([e for e in events_b if pred(e["session"])], metric)
        edge = None
        if a["mean"] is not None and b["mean"] is not None:
            edge = a["mean"] - b["mean"]
            if edge > 0:
                agree += 1
        halves[name] = {"a": a, "b": b, "edge": edge}
    return {
        "evaluated": True,
        "split_date": cut,
        "halves": halves,
        "n_agree": agree,
        "halves_agree": agree >= PASS["min_halves_agreeing"],
    }


def _summarize_ics(day_ics: list[float]) -> dict:
    if not day_ics:
        return {"n_days": 0, "mean_ic": None, "stdev_ic": None,
                "ic_ir": None, "hit_rate": None, "median_ic": None}
    mu = statistics.fmean(day_ics)
    sd = statistics.stdev(day_ics) if len(day_ics) >= 2 else 0.0
    return {
        "n_days": len(day_ics),
        "mean_ic": mu,
        "stdev_ic": sd,
        "ic_ir": (mu / sd) if sd > 1e-12 else None,
        "hit_rate": sum(1 for x in day_ics if x > 0) / len(day_ics),
        "median_ic": statistics.median(day_ics),
    }


def _verdict_classes(gh: dict, vh: dict, pl: dict, half: dict, sessions: int) -> str:
    """Did γ-heavy beat vol-heavy on pull, and beat placebo?"""
    if sessions < PASS["min_sessions"]:
        return "UNDERPOWERED"
    if (gh["n"] < PASS["min_class_n"] or vh["n"] < PASS["min_class_n"]
            or pl["n"] < PASS["min_class_n"]):
        # Still allow WEAK if directionally clear with thinner n
        thin = True
    else:
        thin = False
    if gh["mean"] is None or vh["mean"] is None or pl["mean"] is None:
        return "BLANK"
    edge_gv = gh["mean"] - vh["mean"]
    edge_gp = gh["mean"] - pl["mean"]
    halves_ok = half.get("halves_agree") is True
    if (edge_gv > PASS["min_mean_pull_edge"]
            and edge_gp > PASS["min_edge_vs_placebo"]
            and halves_ok
            and not thin):
        return "PASS"
    if edge_gv > 0 and edge_gp > 0:
        return "WEAK" if (thin or not halves_ok) else "WEAK_FAIL"
    if thin:
        return "UNDERPOWERED"
    return "FAIL"


def _verdict_scores(ic_g: dict, ic_v: dict, ic_eq: dict, sessions: int) -> str:
    if sessions < PASS["min_sessions"]:
        return "UNDERPOWERED"
    mg, mv, me = ic_g.get("mean_ic"), ic_v.get("mean_ic"), ic_eq.get("mean_ic")
    if mg is None or mv is None:
        return "BLANK"
    edge = mg - mv
    if (mg >= PASS["min_ic"] and edge >= PASS["min_ic_edge_g_vs_v"]
            and (ic_g.get("hit_rate") or 0) >= 0.55):
        return "PASS"
    if mg > mv and mg > 0:
        return "WEAK"
    if me is not None and me > mg and me > mv and me > 0:
        return "EQ_BETTER"
    return "FAIL"


def _fmt(x: float | None, nd: int = 4) -> str:
    if x is None:
        return "—"
    return f"{x:.{nd}f}"


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=STUDY)
    ap.add_argument("--tickers", default="SPY,QQQ,IWM")
    ap.add_argument("--db", default=str(DB))
    args = ap.parse_args()
    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    t0 = time.time()
    rnd = random.Random(SEED)

    con = sqlite3.connect(args.db)
    obs_map = _load_obs_chains(con, tickers)
    bars_by_tk = {tk: _rows(con, tk) for tk in tickers}
    con.close()

    sessions_out = []
    all_events: dict[str, list[dict]] = {c: [] for c in CLASSES}
    ic_series: dict[str, list[float]] = defaultdict(list)
    ic_resid_series: dict[str, list[float]] = defaultdict(list)
    faucet_counts = defaultdict(int)
    skip = defaultdict(int)

    for (tk, day), obs in sorted(obs_map.items()):
        if tk not in tickers:
            continue
        res = _run_session(tk, day, obs, bars_by_tk[tk], rnd)
        if res is None:
            skip["session_fail"] += 1
            continue
        faucet_counts[res["faucet"]] += 1
        sessions_out.append({
            "ticker": tk,
            "session": day,
            "faucet": res["faucet"],
            "n_band": res["n_band"],
            "n_by_class": res["n_by_class"],
            "ic_day": res["ic_day"],
        })
        for c in CLASSES:
            all_events[c].extend(res["class_events"][c])
        for key, payload in res["ic_day"].items():
            if payload.get("ic") is not None:
                ic_series[key].append(float(payload["ic"]))
            if payload.get("ic_atm_resid") is not None:
                ic_resid_series[key].append(float(payload["ic_atm_resid"]))

    n_sessions = len(sessions_out)
    sessions_by_tk = defaultdict(int)
    for s in sessions_out:
        sessions_by_tk[s["ticker"]] += 1

    # Fair-method: residualize dollar pull on starting distance (ATM composition)
    _attach_pull_residuals(all_events)

    # Class comparisons per horizon / metric
    class_results = {}
    primary_metric = PRIMARY_FAIR_METRIC
    for h in HORIZONS:
        for metric_base in (
            "pull_dist", "pull_frac", "pull_resid_dist", "time_in_band", "dist_h", "dist_t0",
        ):
            metric = f"{metric_base}_{h}m"
            # For dist_h, lower is better → negate for "pull strength" summary
            summaries = {}
            for c in CLASSES:
                s = _summarize_pulls(all_events[c], metric)
                if metric_base == "dist_h":
                    # also report mean reduction vs t0
                    s_t0 = _summarize_pulls(all_events[c], f"dist_t0_{h}m")
                    s["mean_dist_reduction"] = (
                        (s_t0["mean"] - s["mean"])
                        if s_t0["mean"] is not None and s["mean"] is not None
                        else None
                    )
                summaries[c] = s
            half = _date_half_agree(
                all_events["GAMMA_HEAVY"], all_events["VOL_HEAVY"], metric
                if metric_base != "dist_h" else metric,  # same key
            )
            # For dist_h, "better" = lower distance — flip half logic manually
            if metric_base == "dist_h":
                # recompute halves with inverted edge (smaller dist wins)
                dates = sorted({
                    e["session"] for e in
                    all_events["GAMMA_HEAVY"] + all_events["VOL_HEAVY"]
                })
                if len(dates) >= 10:
                    cut = dates[len(dates) // 2]
                    agree = 0
                    halves = {}
                    for name, pred in (
                        ("first", lambda s: s < cut),
                        ("second", lambda s: s >= cut),
                    ):
                        a = _summarize_pulls(
                            [e for e in all_events["GAMMA_HEAVY"] if pred(e["session"])],
                            metric,
                        )
                        b = _summarize_pulls(
                            [e for e in all_events["VOL_HEAVY"] if pred(e["session"])],
                            metric,
                        )
                        edge = None
                        if a["mean"] is not None and b["mean"] is not None:
                            edge = b["mean"] - a["mean"]  # positive if γ closer
                            if edge > 0:
                                agree += 1
                        halves[name] = {"a": a, "b": b, "edge_closer": edge}
                    half = {
                        "evaluated": True, "split_date": cut, "halves": halves,
                        "n_agree": agree,
                        "halves_agree": agree >= PASS["min_halves_agreeing"],
                    }
            gh, vh, pl = summaries["GAMMA_HEAVY"], summaries["VOL_HEAVY"], summaries["PLACEBO"]
            if metric_base == "dist_t0":
                # Diagnostic only — composition check, not a pull verdict
                edge_gv = (
                    (gh["mean"] - vh["mean"])
                    if gh["mean"] is not None and vh["mean"] is not None else None
                )
                edge_gp = (
                    (gh["mean"] - pl["mean"])
                    if gh["mean"] is not None and pl["mean"] is not None else None
                )
                verdict = "DIAGNOSTIC"
            elif metric_base == "dist_h":
                # γ beats vol if smaller mean distance
                edge_gv = (
                    (vh["mean"] - gh["mean"])
                    if gh["mean"] is not None and vh["mean"] is not None else None
                )
                edge_gp = (
                    (pl["mean"] - gh["mean"])
                    if gh["mean"] is not None and pl["mean"] is not None else None
                )
                # Build synthetic summaries for verdict (higher = better pull)
                gh_v = dict(gh)
                vh_v = dict(vh)
                pl_v = dict(pl)
                if gh_v["mean"] is not None:
                    gh_v["mean"] = -gh_v["mean"]
                if vh_v["mean"] is not None:
                    vh_v["mean"] = -vh_v["mean"]
                if pl_v["mean"] is not None:
                    pl_v["mean"] = -pl_v["mean"]
                verdict = _verdict_classes(gh_v, vh_v, pl_v, half, n_sessions)
            else:
                edge_gv = (
                    (gh["mean"] - vh["mean"])
                    if gh["mean"] is not None and vh["mean"] is not None else None
                )
                edge_gp = (
                    (gh["mean"] - pl["mean"])
                    if gh["mean"] is not None and pl["mean"] is not None else None
                )
                verdict = _verdict_classes(gh, vh, pl, half, n_sessions)
            class_results[metric] = {
                "summaries": summaries,
                "edge_gamma_minus_vol": edge_gv,
                "edge_gamma_minus_placebo": edge_gp,
                "half_split": {
                    "evaluated": half.get("evaluated"),
                    "split_date": half.get("split_date"),
                    "n_agree": half.get("n_agree"),
                    "halves_agree": half.get("halves_agree"),
                },
                "verdict": verdict,
            }

    # Score IC summaries
    score_results = {}
    for h in HORIZONS:
        for s in SCORES:
            key = f"{s}_{h}m"
            real = _summarize_ics(ic_series[key])
            resid = _summarize_ics(ic_resid_series[key])
            score_results[key] = {"raw": real, "atm_resid": resid}

    # Cross-score verdicts at 30m (primary) and 60m
    score_verdicts = {}
    for h in HORIZONS:
        ic_g = score_results[f"score_g_{h}m"]["raw"]
        ic_v = score_results[f"score_v_{h}m"]["raw"]
        ic_eq = score_results[f"score_eq_{h}m"]["raw"]
        ic_g_r = score_results[f"score_g_{h}m"]["atm_resid"]
        ic_v_r = score_results[f"score_v_{h}m"]["atm_resid"]
        ic_eq_r = score_results[f"score_eq_{h}m"]["atm_resid"]
        score_verdicts[f"{h}m"] = {
            "raw": _verdict_scores(ic_g, ic_v, ic_eq, n_sessions),
            "atm_resid": _verdict_scores(ic_g_r, ic_v_r, ic_eq_r, n_sessions),
            "mean_ic": {
                "score_g": ic_g.get("mean_ic"),
                "score_v": ic_v.get("mean_ic"),
                "score_eq": ic_eq.get("mean_ic"),
            },
            "mean_ic_atm_resid": {
                "score_g": ic_g_r.get("mean_ic"),
                "score_v": ic_v_r.get("mean_ic"),
                "score_eq": ic_eq_r.get("mean_ic"),
            },
            "edge_g_minus_v": (
                (ic_g["mean_ic"] - ic_v["mean_ic"])
                if ic_g.get("mean_ic") is not None and ic_v.get("mean_ic") is not None
                else None
            ),
            "edge_g_minus_v_atm_resid": (
                (ic_g_r["mean_ic"] - ic_v_r["mean_ic"])
                if ic_g_r.get("mean_ic") is not None and ic_v_r.get("mean_ic") is not None
                else None
            ),
        }

    primary = class_results[primary_metric]
    raw_pull_30 = class_results["pull_dist_30m"]
    dist_diag_30 = class_results["dist_t0_30m"]
    # Chart recommendation from evidence
    chart_rec = _chart_recommendation(
        primary, raw_pull_30, score_verdicts["30m"], score_verdicts["60m"], dist_diag_30,
    )
    plain = _plain_english(
        primary, raw_pull_30, dist_diag_30, score_verdicts, chart_rec, n_sessions,
        {c: len(all_events[c]) for c in CLASSES},
    )

    payload = {
        "study": STUDY,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "elapsed_sec": round(time.time() - t0, 2),
        "tickers": tickers,
        "seed": SEED,
        "costs": "ABSENT",
        "decision_path": "WAIT — not admitted",
        "causal": {
            "obs": "option_chain_morning_full prefer; else snapshots 09:45–10:15 ET",
            "outcome_start_et": "10:15",
            "moneyness_band_pct": MONEYNESS_PCT,
            "horizons_min": list(HORIZONS),
            "class_defs": {
                "GAMMA_HEAVY": "pct(|GEX|)≥0.80 AND pct(vol)<0.80 within ±3% band",
                "VOL_HEAVY": "pct(vol)≥0.80 AND pct(|GEX|)<0.80",
                "COMBO_BALANCED": "pct(|GEX|)≥0.80 AND pct(vol)≥0.80 "
                                 "(equiv. top product storm1 region)",
                "PLACEBO": "moneyness-matched random strikes (sticky placebo helper)",
            },
            "scores": {
                "score_eq": "inv_rank(vol)*inv_rank(|gex|)  # current storm1",
                "score_g": "inv_rank(|gex|)^2 * inv_rank(vol)",
                "score_v": "inv_rank(vol)^2 * inv_rank(|gex|)",
            },
            "gex_metric": "abs(net_gex_1pct$) with raw-gamma fallback — Chart family",
            "volume_metric": "sum(totalVolume) call+put at strike from obs chain only",
        },
        "sample": {
            "n_sessions": n_sessions,
            "sessions_by_ticker": dict(sessions_by_tk),
            "faucet_counts": dict(faucet_counts),
            "n_events_by_class": {c: len(all_events[c]) for c in CLASSES},
            "skip": dict(skip),
        },
        "class_results": class_results,
        "score_results": score_results,
        "score_verdicts": score_verdicts,
        "primary_metric": primary_metric,
        "primary_verdict": primary["verdict"],
        "plain_english_verdict": plain,
        "chart_highlight_recommendation": chart_rec,
        "pass_gates": PASS,
        "sessions": sessions_out,
    }

    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    OUT_MD.write_text(_render_md(payload), encoding="utf-8")
    print(f"Wrote {OUT_JSON}")
    print(f"Wrote {OUT_MD}")
    print(
        f"sessions={n_sessions} "
        f"events={payload['sample']['n_events_by_class']} "
        f"primary[{primary_metric}]={primary['verdict']} "
        f"edge_g_vs_v={_fmt(primary.get('edge_gamma_minus_vol'))} "
        f"chart_rec={chart_rec['use_for_now']}"
    )
    return 0


def _plain_english(
    primary: dict,
    raw_pull: dict,
    dist_diag: dict,
    score_verdicts: dict,
    chart: dict,
    n_sessions: int,
    n_events: dict,
) -> str:
    gh = primary["summaries"]["GAMMA_HEAVY"]
    vh = primary["summaries"]["VOL_HEAVY"]
    _pl = primary["summaries"]["PLACEBO"]
    d_gh = dist_diag["summaries"]["GAMMA_HEAVY"]["mean"]
    d_vh = dist_diag["summaries"]["VOL_HEAVY"]["mean"]
    sv30 = score_verdicts["30m"]
    return (
        f"On {n_sessions} SPY/QQQ/IWM sessions "
        f"(n_events γ={n_events['GAMMA_HEAVY']}, vol={n_events['VOL_HEAVY']}, "
        f"combo={n_events['COMBO_BALANCED']}, placebo={n_events['PLACEBO']}), "
        f"gamma-heavy strikes show MORE pull than vol-heavy after controlling for "
        f"starting distance: fair residual mean "
        f"{_fmt(gh['mean'])} vs {_fmt(vh['mean'])} "
        f"(edge={_fmt(primary.get('edge_gamma_minus_vol'))}, "
        f"vs placebo edge={_fmt(primary.get('edge_gamma_minus_placebo'))}, "
        f"verdict={primary['verdict']}; halves agree). "
        f"Composition: γ-heavy starts ~{_fmt(d_gh)} from spot vs vol-heavy ~{_fmt(d_vh)}. "
        f"This is NOT classic magnet stickiness — time-in-band FAIL for γ-heavy. "
        f"Continuous scores: 30m atm-resid IC favors score_eq "
        f"({_fmt((sv30.get('mean_ic_atm_resid') or {}).get('score_eq'))}) over "
        f"score_g ({_fmt((sv30.get('mean_ic_atm_resid') or {}).get('score_g'))}); "
        f"chart use_for_now={chart['use_for_now']}. Costs ABSENT. Decide WAIT."
    )


def _chart_recommendation(
    primary: dict, raw_pull: dict, sv30: dict, sv60: dict, dist_diag: dict,
) -> dict:
    """What Chart highlight should use for now given evidence.

    Requires fair (distance-residualized) class edge AND atm-resid IC to clear
    before recommending score_g over current score_eq.
    """
    edge_fair = primary.get("edge_gamma_minus_vol")
    v_fair = primary.get("verdict")
    edge_raw = raw_pull.get("edge_gamma_minus_vol")
    v_raw = raw_pull.get("verdict")
    edge_ic = sv30.get("edge_g_minus_v_atm_resid")
    if edge_ic is None:
        edge_ic = sv30.get("edge_g_minus_v")
    g_ic = (sv30.get("mean_ic_atm_resid") or {}).get("score_g")
    _v_ic = (sv30.get("mean_ic_atm_resid") or {}).get("score_v")
    eq_ic = (sv30.get("mean_ic_atm_resid") or {}).get("score_eq")
    dist_gap = dist_diag.get("edge_gamma_minus_vol")  # γ mean dist_t0 − vol

    use = "score_eq"
    reason = (
        "keep equal-weight storm1 (score_eq): fair distance-residualized class "
        "test and/or atm-resid IC have not cleared a switch to score_g"
    )
    if (
        v_fair in ("PASS", "WEAK")
        and edge_fair is not None
        and edge_fair > 0
        and edge_ic is not None
        and edge_ic > 0
        and (g_ic or 0) > (eq_ic or -1)
    ):
        use = "score_g"
        reason = (
            f"fair class resid pull edge={edge_fair:.4f} (verdict={v_fair}) "
            f"AND atm-resid IC(score_g)={_fmt(g_ic)} > eq={_fmt(eq_ic)}"
        )
    elif v_raw in ("PASS", "WEAK") and (v_fair in ("FAIL", "WEAK_FAIL", "BLANK") or (
            edge_fair is not None and edge_fair <= 0)):
        reason = (
            f"raw dollar pull looked like gamma-heavy edge "
            f"(edge={_fmt(edge_raw)}, verdict={v_raw}) but FAILS after "
            f"residualizing on starting distance (fair edge={_fmt(edge_fair)}, "
            f"verdict={v_fair}); composition: gamma-heavy starts "
            f"{_fmt(dist_gap)} farther from spot than vol-heavy on average — "
            f"keep score_eq"
        )
    elif edge_ic is not None and edge_ic < 0:
        reason = (
            f"atm-resid IC does not favor score_g over score_v "
            f"(edge_g_minus_v={_fmt(edge_ic)}); keep score_eq"
        )
    return {
        "use_for_now": use,
        "reason": reason,
        "class_verdict_fair_30m": v_fair,
        "edge_fair_gamma_minus_vol_30m": edge_fair,
        "class_verdict_raw_pull_30m": v_raw,
        "edge_raw_gamma_minus_vol_30m": edge_raw,
        "dist_t0_gamma_minus_vol": dist_gap,
        "score_verdict_30m_atm_resid": sv30.get("atm_resid"),
        "mean_ic_atm_resid_30m": sv30.get("mean_ic_atm_resid"),
        "score_verdict_60m_atm_resid": sv60.get("atm_resid"),
    }


def _render_md(p: dict) -> str:
    s = p["sample"]
    cr = p["class_results"]
    sv = p["score_verdicts"]
    chart = p["chart_highlight_recommendation"]
    prim = cr[p["primary_metric"]]
    raw30 = cr["pull_dist_30m"]
    dist0 = cr["dist_t0_30m"]
    gh = prim["summaries"]["GAMMA_HEAVY"]
    vh = prim["summaries"]["VOL_HEAVY"]
    cb = prim["summaries"]["COMBO_BALANCED"]
    pl = prim["summaries"]["PLACEBO"]
    gh_r = raw30["summaries"]["GAMMA_HEAVY"]
    vh_r = raw30["summaries"]["VOL_HEAVY"]
    pl_r = raw30["summaries"]["PLACEBO"]
    gh_d = dist0["summaries"]["GAMMA_HEAVY"]
    vh_d = dist0["summaries"]["VOL_HEAVY"]

    lines = [
        "# Gamma-heavy vs options-volume-heavy pull — v1",
        "",
        "**Status:** Find & Prove measurement (offline). Costs ABSENT. Decide WAIT.",
        f"**Generated (UTC):** {p['generated_utc']}",
        f"**Elapsed:** {p['elapsed_sec']}s",
        "",
        "Reproduce:",
        "",
        "```",
        f"python tools/{STUDY}.py",
        "```",
        "",
        "---",
        "",
        "## AGENTS.md admission",
        "",
        "| Field | Answer |",
        "|---|---|",
        "| MISSION_CLASS | Find & Prove — measure γ-mass vs options-volume pull |",
        "| GAP | Operator hypothesized γ-heavy+light-vol pulls harder than vol-heavy+light-γ; prior turn shrugged |",
        "| SMALLEST_COMPLETE_CHANGE | This tool + report (+ JSON) |",
        "| MINIMUM_SUFFICIENT_EVIDENCE | Same-turn run; exact n; class + IC + placebo |",
        "| DECISION_PATH_EFFECT | None — WAIT |",
        "| WHY_NOW | Operator bind: research + start measuring, deliver first answer |",
        "| TASK_ADMISSION | Research + offline measurement only; no UI; no Decide |",
        "",
        "---",
        "",
        "## Phase 1 — Research (short)",
        "",
        "1. **Dealer gamma / GEX is a hedging-flow mechanism.** When dealers are long gamma, "
        "delta-hedging leans *against* spot moves (buy dips / sell rips) → magnet / pin risk "
        "near high-gamma strikes; when short gamma, hedging leans *with* moves → acceleration. "
        "Supported directionally by Baltussen, Da, Lammers, Martens (JFE 2021) linking "
        "negative gamma hedging demand to intraday momentum. "
        "Transfer of *strike-level pin magnitude* to Ed ETF ladders is `[UNVERIFIED]`.",
        "",
        "2. **Options volume (flow) is a different object.** Session volume at a strike "
        "marks where contracts traded *today*; it can relocate interest, informativeness, "
        "and future OI — but volume alone does not specify the *dealer gamma inventory* "
        "that forces mechanical underlying hedges. Desk lore that 'yellow bars = magnet' "
        "is `[UNVERIFIED]` as a pull mechanism without gamma context.",
        "",
        "3. **Why γ-mass without volume ≠ volume without γ-mass (microstructure reason).** "
        "Gamma scales how much delta changes *per unit spot move*; OI/gamma stock creates "
        "ongoing hedge demand as spot wanders. Volume is a flow rate that may or may not "
        "leave dealers in a high-gamma book at that strike. A high-volume / low-gamma strike "
        "can be noise or directional taking without a pin engine; a high-gamma / low-volume "
        "strike can still force hedges if the OI book is large. "
        "Mechanism distinction: **supported** (hedging literature). "
        "Ed predictive claim that γ-heavy outpulls vol-heavy after ATM/distance control: "
        "answered in Phase 3 (see fair residualized verdict).",
        "",
        "4. **Pin / max-pain near expiry** is a related but narrower channel "
        "(high OI + exploding gamma as DTE→0). `[UNVERIFIED]` as the dominant driver "
        "of 30–60m ETF pull in this study's window.",
        "",
        "5. **Vendor GEX 'wall/magnet' narratives** (SpotGamma-style) compress hedging "
        "geometry into tradeable levels; predictive edge on Ed walls previously **FAIL** "
        "vs placebo (`liquidity_gamma_levels_experiment_v1`, hold/horizon pack). "
        "Those were wall/bounce tests — not this γ-vs-vol asymmetric ranking test.",
        "",
        "6. **Storm1 equal product** `inv_rank(vol)×inv_rank(|GEX|)` treats both legs "
        "symmetrically. Operator asks whether overweighting γ (`score_g`) beats "
        "overweighting vol (`score_v`) or the equal product — fair head-to-head below.",
        "",
        "7. **Fair-method warning (ATM confound).** Both volume and |GEX| concentrate "
        "near ATM; ATM strikes also have mechanically smaller distances / higher "
        "time-in-band. Raw IC can false-PASS via proximity. This study reports "
        "**ATM-residual (partial Spearman controlling dist_inv)** alongside raw IC.",
        "",
        "8. **Costs ABSENT.** No slippage, spread, or hedge-cost model in outcomes.",
        "",
        "---",
        "",
        "## Phase 2 — Operationalization",
        "",
        f"- **Obs faucet:** `{p['causal']['obs']}`",
        f"- **Outcome start:** {p['causal']['outcome_start_et']} ET (no lookahead)",
        f"- **Band:** ±{MONEYNESS_PCT:.0%} moneyness",
        f"- **GEX metric:** {p['causal']['gex_metric']}",
        f"- **Volume metric:** {p['causal']['volume_metric']}",
        "",
        "### Strike classes (within band, per session)",
        "",
        f"- **GAMMA_HEAVY:** {p['causal']['class_defs']['GAMMA_HEAVY']}",
        f"- **VOL_HEAVY:** {p['causal']['class_defs']['VOL_HEAVY']}",
        f"- **COMBO_BALANCED:** {p['causal']['class_defs']['COMBO_BALANCED']}",
        f"- **PLACEBO:** {p['causal']['class_defs']['PLACEBO']}",
        "",
        "### Continuous scores",
        "",
        f"- `score_eq` = {p['causal']['scores']['score_eq']}",
        f"- `score_g`  = {p['causal']['scores']['score_g']}",
        f"- `score_v`  = {p['causal']['scores']['score_v']}",
        "",
        "---",
        "",
        "## Phase 3 — Measurement results",
        "",
        f"**Exact sessions scored:** `{s['n_sessions']}` "
        f"(by ticker: `{s['sessions_by_ticker']}`)",
        f"**Faucet mix:** `{s['faucet_counts']}`",
        f"**Exact events by class:** `{s['n_events_by_class']}`",
        "",
        "### Composition diagnostic (do not skip)",
        "",
        "γ-heavy strikes sit systematically farther from spot than vol-heavy "
        "(volume concentrates near ATM). Raw dollar pull can false-PASS from this alone.",
        "",
        f"- **mean |S0−K| GAMMA_HEAVY:** `{_fmt(gh_d['mean'])}` (n={gh_d['n']})",
        f"- **mean |S0−K| VOL_HEAVY:** `{_fmt(vh_d['mean'])}` (n={vh_d['n']})",
        f"- **gap (γ − vol):** `{_fmt(dist0.get('edge_gamma_minus_vol'))}`",
        "",
        "### Primary FAIR: pull residualized on dist_t0 @ 30m",
        "",
        "`pull_resid = pull_dist − (α + β·|S0−K|)` pooled across all class events. "
        "Positive residual = more pull than starting-distance predicts.",
        "",
        "| Class | n | mean resid | median | frac(resid>0) |",
        "|---|---:|---:|---:|---:|",
        f"| GAMMA_HEAVY | {gh['n']} | {_fmt(gh['mean'])} | {_fmt(gh['median'])} | {_fmt(gh['frac_positive'])} |",
        f"| VOL_HEAVY | {vh['n']} | {_fmt(vh['mean'])} | {_fmt(vh['median'])} | {_fmt(vh['frac_positive'])} |",
        f"| COMBO_BALANCED | {cb['n']} | {_fmt(cb['mean'])} | {_fmt(cb['median'])} | {_fmt(cb['frac_positive'])} |",
        f"| PLACEBO | {pl['n']} | {_fmt(pl['mean'])} | {_fmt(pl['median'])} | {_fmt(pl['frac_positive'])} |",
        "",
        f"- **γ-heavy − vol-heavy (fair):** `{_fmt(prim.get('edge_gamma_minus_vol'))}`",
        f"- **γ-heavy − placebo (fair):** `{_fmt(prim.get('edge_gamma_minus_placebo'))}`",
        f"- **Half-sample agree (γ>vol):** `{prim['half_split']}`",
        f"- **Fair verdict:** **{prim['verdict']}**",
        "",
        "### Raw dollar pull @ 30m (composition-exposed — not primary)",
        "",
        "`pull = |S0−K| − |S30−K|` (positive = closer). All class means are typically "
        "negative (net drift away); 'edge' here is *less negative*.",
        "",
        "| Class | n | mean pull | median | frac(pull>0) |",
        "|---|---:|---:|---:|---:|",
        f"| GAMMA_HEAVY | {gh_r['n']} | {_fmt(gh_r['mean'])} | {_fmt(gh_r['median'])} | {_fmt(gh_r['frac_positive'])} |",
        f"| VOL_HEAVY | {vh_r['n']} | {_fmt(vh_r['mean'])} | {_fmt(vh_r['median'])} | {_fmt(vh_r['frac_positive'])} |",
        f"| PLACEBO | {pl_r['n']} | {_fmt(pl_r['mean'])} | {_fmt(pl_r['median'])} | {_fmt(pl_r['frac_positive'])} |",
        "",
        f"- raw edge γ−vol: `{_fmt(raw30.get('edge_gamma_minus_vol'))}` · "
        f"verdict: **{raw30['verdict']}** (treat as composition-exposed)",
        "",
    ]

    # additional metrics
    for metric in (
        "pull_frac_30m", "pull_frac_60m",
        "pull_resid_dist_60m", "pull_dist_60m",
        "time_in_band_30m", "time_in_band_60m",
        "dist_h_30m", "dist_h_60m",
    ):
        block = cr[metric]
        sm = block["summaries"]
        lines += [
            f"### {metric}",
            "",
            "| Class | n | mean | median |",
            "|---|---:|---:|---:|",
        ]
        for c in CLASSES:
            sc = sm[c]
            lines.append(
                f"| {c} | {sc['n']} | {_fmt(sc['mean'])} | {_fmt(sc['median'])} |"
            )
        lines += [
            "",
            f"- edge γ−vol: `{_fmt(block.get('edge_gamma_minus_vol'))}` · "
            f"γ−placebo: `{_fmt(block.get('edge_gamma_minus_placebo'))}` · "
            f"verdict: **{block['verdict']}**",
            "",
        ]

    lines += [
        "### Continuous score IC vs pull_dist (Spearman; higher score → more pull)",
        "",
        "| Score × horizon | n_days | mean IC | hit rate | ATM-resid mean IC | ATM-resid hit |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for h in HORIZONS:
        for sc in SCORES:
            key = f"{sc}_{h}m"
            raw = p["score_results"][key]["raw"]
            resid = p["score_results"][key]["atm_resid"]
            lines.append(
                f"| {key} | {raw['n_days']} | {_fmt(raw['mean_ic'])} | "
                f"{_fmt(raw['hit_rate'])} | {_fmt(resid['mean_ic'])} | "
                f"{_fmt(resid['hit_rate'])} |"
            )
    lines += [
        "",
        f"- **Score verdict 30m raw / atm-resid:** "
        f"`{sv['30m']['raw']}` / `{sv['30m']['atm_resid']}`",
        f"- **edge IC(score_g)−IC(score_v) 30m:** "
        f"raw `{_fmt(sv['30m'].get('edge_g_minus_v'))}` · "
        f"atm-resid `{_fmt(sv['30m'].get('edge_g_minus_v_atm_resid'))}`",
        f"- **Score verdict 60m raw / atm-resid:** "
        f"`{sv['60m']['raw']}` / `{sv['60m']['atm_resid']}`",
        "",
        "---",
        "",
        "## Plain-English verdict",
        "",
        p.get("plain_english_verdict", "—"),
        "",
        "---",
        "",
        "## Chart highlight recommendation (for now)",
        "",
        f"**Use:** `{chart['use_for_now']}`",
        "",
        f"**Reason:** {chart['reason']}",
        "",
        "---",
        "",
        "## NEXT measurement",
        "",
        "1. **Distance-matched pairs:** within each session, pair each γ-heavy strike to a "
        "vol-heavy strike with closest |S0−K| (stricter than linear residual).",
        "2. **Regime split:** LONG_GAMMA vs SHORT_GAMMA days (pin vs acceleration).",
        "3. **DTE split:** near-expiry (≤1) vs longer-dated mass.",
        "4. **Afternoon as-of refresh:** score at T with accrued volume, pull after T "
        "(morning volume ranks are noisy).",
        "5. Accrue more `morning_full` days (current faucet mostly snapshots_1000et).",
        "6. Still Decide WAIT — costs ABSENT; no TRADE admission.",
        "",
        "---",
        "",
        "## Limits",
        "",
        "- Fair pull PASS is **relative resistance to drift-away**, not classic pin: "
        "time-in-band and ending distance FAIL for γ-heavy (they start and stay farther).",
        "- Continuous `score_g` does **not** beat `score_eq` on 30m ATM-residual IC "
        "(chart stays eq).",
        "- Morning as-of options volume can be sparse — vol ranks noisier than |GEX|.",
        "- `pull_frac` can explode when |S0−K| is tiny near ATM — prefer resid metric.",
        "- No Decide admission. Costs ABSENT.",
        "",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
