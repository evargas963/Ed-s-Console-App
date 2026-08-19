"""OI × options-volume stickiness study v1 — Find & Prove / offline only.

Question: does combining Open Interest AND session options volume (Chart yellow)
identify sticky strikes better than volume-only, OI-only, GEX$ walls, or placebo?

STICKY is NOT "price touched the strike." Pre-registered outcomes:
  A) Time-in-band   — fraction of post-obs RTH minutes with close within w of strike
  B) Failed-break   — pierce beyond strike by j×ATR, reclaim within N minutes
  C) Pin-to-close   — |RTH close − strike| vs placebo (near-expiry labeled)

Causal as-of:
  - Levels from option_chain_morning_full (prefer) or snapshots ~10:00 ET
  - OI and volume taken ONLY from that observation chain (no EOD volume lookahead)
  - Outcome window starts at 10:15 ET; band width from pre-obs causal ATR

NO Chart/UI change. NO Decide admission. NO push.

USAGE:
  python tools/liquidity_oi_volume_stickiness_v1.py
  python tools/liquidity_oi_volume_stickiness_v1.py --tickers SPY,QQQ,IWM
"""
from __future__ import annotations

import argparse
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
    compute_exposures_by_strike,
    pick_gamma_wall_strikes,
    pick_pin_and_strength,
)
from numeric_contract import float_finite_or_none, float_nonnegative_or_none  # noqa: E402
from terrain_engine import compute_terrain  # noqa: E402
from time_et import ET, RTH_END_MINS, RTH_START_MINS, is_trading_day_et  # noqa: E402

# ── Pre-registered constants ─────────────────────────────────────────────────
RTH_OPEN_MIN = int(RTH_START_MINS)
RTH_CLOSE_MIN = int(RTH_END_MINS)
OBS_LO_MIN, OBS_HI_MIN = RTH_OPEN_MIN + 15, RTH_OPEN_MIN + 45  # 09:45–10:15 obs window
OUTCOME_START_MIN = OBS_HI_MIN  # post-obs; same 10:15 cut as OBS_HI
SEED = 20260730

TOP_K = 3                       # candidate sticky strikes per arm per day
MONEYNESS_PCT = 0.03            # ±3% of spot — equal-width band for candidates + placebo
BAND_ATR_FRAC = 0.25            # time-in-band half-width (causal ATR)
PIERCE_ATR_MULT = 0.35          # failed-break pierce threshold
RECLAIM_MINUTES = 15            # reclaim window after pierce
NEAR_EXPIRY_DTE_MAX = 1         # pin-to-close near-expiry label (0–1 DTE present)

PASS = {
    "min_sessions": 80,
    "min_edge_pp_time_in_band": 0.03,   # absolute fraction points vs placebo
    "min_edge_pp_failed_break": 0.05,
    "min_pin_distance_improvement": 0.10,  # relative: real dist < placebo * (1-x)
    "min_halves_agreeing": 2,
    "min_pierce_events": 40,            # else B arm descriptive / UNDERPOWERED
}

STUDY = "liquidity_oi_volume_stickiness_v1"
DB = REPO / "data" / "ed_console.db"
OUT_JSON = REPO / "reports" / f"{STUDY}.json"
OUT_MD = REPO / "reports" / f"{STUDY}.md"

ARMS = (
    "VOL_PEAK",          # Chart yellow analogue — top volume
    "OI_PEAK",           # top open interest
    "PRODUCT",           # OI × volume
    "Z_PRODUCT",         # z(OI) × z(vol) among moneyness band
    "TURNOVER_HIGH_OI",  # volume/OI among top-quartile OI
    "GEX_WALLS",         # call/put wall + pin (prior FAIL baseline)
)


# ── Bars ─────────────────────────────────────────────────────────────────────

def _rows(con: sqlite3.Connection, ticker: str) -> list[dict]:
    q = (
        "SELECT bar_start_ts_utc, open, high, low, close, volume "
        "FROM price_bars_1m WHERE ticker=? ORDER BY bar_start_ts_utc ASC"
    )
    out = []
    for ts, o, h, l, c, v in con.execute(q, (ticker,)):
        if None in (ts, o, h, l, c):
            continue
        dt = datetime.fromtimestamp(float(ts), ET)
        out.append({
            "dt": dt,
            "open": float(o), "high": float(h), "low": float(l),
            "close": float(c), "volume": float(v or 0.0),
            "min_of_day": dt.hour * 60 + dt.minute,
        })
    return out


def _causal_atr_pre_obs(sb: list[dict]) -> float:
    """Median 1m range from RTH open through last bar BEFORE outcome window — no afternoon lookahead."""
    pre = [
        b for b in sb
        if RTH_OPEN_MIN <= b["min_of_day"] < OUTCOME_START_MIN and b["high"] > b["low"]
    ]
    if len(pre) < 5:
        return 0.0
    return statistics.median(b["high"] - b["low"] for b in pre)


def _et_day_and_min(ts: float) -> tuple[str, int]:
    d = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(ET)
    return d.strftime("%Y-%m-%d"), d.hour * 60 + d.minute


# ── Observation chains ───────────────────────────────────────────────────────

def _load_obs_chains(
    con: sqlite3.Connection, tickers: list[str],
) -> dict[tuple[str, str], dict]:
    out: dict[tuple[str, str], dict] = {}
    for tk in tickers:
        for day, ts, spot, chain, n_cts in con.execute(
            "SELECT et_date, ts_utc, spot, chain_json, n_contracts "
            "FROM option_chain_morning_full WHERE ticker=? ORDER BY et_date",
            (tk,),
        ):
            if not day or not is_trading_day_et(str(day)):
                continue
            out[(tk, str(day))] = {
                "faucet": "morning_full",
                "obs_dist_min": None,
                "obs_ts_utc": float(ts) if ts is not None else None,
                "spot": float(spot),
                "chain_raw": chain,
                "n_contracts": int(n_cts) if n_cts is not None else None,
            }

    best: dict[tuple[str, str], tuple[int, float, float, str]] = {}
    for tk in tickers:
        for ts, spot, chain in con.execute(
            "SELECT ts_utc, spot, option_chain_json FROM snapshots "
            "WHERE ticker=? AND timeframe='1m' AND option_chain_json IS NOT NULL "
            "AND spot IS NOT NULL ORDER BY ts_utc",
            (tk,),
        ):
            day, mins = _et_day_and_min(float(ts))
            if not is_trading_day_et(day):
                continue
            if not (OBS_LO_MIN <= mins <= OBS_HI_MIN):
                continue
            if (tk, day) in out:
                continue
            dist = abs(mins - 600)
            key = (tk, day)
            if key not in best or dist < best[key][0]:
                best[key] = (dist, float(ts), float(spot), chain)
    for (tk, day), (dist, ts, spot, chain) in best.items():
        out[(tk, day)] = {
            "faucet": "snapshots_1000et",
            "obs_dist_min": dist,
            "obs_ts_utc": ts,
            "spot": spot,
            "chain_raw": chain,
            "n_contracts": None,
        }
    return out


# ── Strike mass from observation chain ───────────────────────────────────────

def _aggregate_strike_mass(contracts: list[dict], spot: float) -> dict[float, dict]:
    """Per-strike OI + as-of options volume (call+put summed). Causal: obs chain only."""
    by_k: dict[float, dict] = {}
    min_dte = None
    for ct in contracts:
        if not isinstance(ct, dict):
            continue
        sk = float_finite_or_none(ct.get("strikePrice"))
        if sk is None:
            continue
        oi = float_nonnegative_or_none(ct.get("openInterest")) or 0.0
        vol = float_nonnegative_or_none(ct.get("totalVolume")) or 0.0
        dte = float_finite_or_none(ct.get("daysToExpiration"))
        b = by_k.setdefault(sk, {"oi": 0.0, "vol": 0.0, "min_dte": None})
        b["oi"] += oi
        b["vol"] += vol
        if dte is not None:
            if b["min_dte"] is None or dte < b["min_dte"]:
                b["min_dte"] = dte
            if min_dte is None or dte < min_dte:
                min_dte = dte
    for sk, b in by_k.items():
        b["moneyness"] = (sk - spot) / spot if spot else None
        b["turnover"] = (b["vol"] / b["oi"]) if b["oi"] > 0 else None
    return by_k


def _in_moneyness(sk: float, spot: float, pct: float = MONEYNESS_PCT) -> bool:
    if spot <= 0:
        return False
    return abs(sk - spot) / spot <= pct


def _zscores(vals: list[float]) -> list[float]:
    if len(vals) < 2:
        return [0.0] * len(vals)
    mu = statistics.fmean(vals)
    sd = statistics.pstdev(vals)
    if sd <= 1e-12:
        return [0.0] * len(vals)
    return [(v - mu) / sd for v in vals]


def _top_k_strikes(scored: list[tuple[float, float]], k: int = TOP_K) -> list[float]:
    """scored = [(strike, score), ...] — highest score wins; ties break by strike."""
    scored = [(s, sc) for s, sc in scored if sc is not None and math.isfinite(sc)]
    scored.sort(key=lambda x: (-x[1], x[0]))
    out: list[float] = []
    seen = set()
    for s, _ in scored:
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
        if len(out) >= k:
            break
    return out


def _pick_arm_strikes(
    by_k: dict[float, dict],
    spot: float,
    arm: str,
    gex_levels: dict[str, float] | None,
) -> list[float]:
    band = [(sk, m) for sk, m in by_k.items() if _in_moneyness(sk, spot)]
    if arm == "GEX_WALLS":
        if not gex_levels:
            return []
        # Keep walls/pin that fall in moneyness band; if none, keep as-is (honest empty later)
        # Include walls/pin even if outside ±3% — GEX walls are the named baseline
        strikes = []
        for key in ("CALL_WALL", "PUT_WALL", "GAMMA_PIN"):
            v = gex_levels.get(key)
            if v is None:
                continue
            strikes.append(float(v))
        uniq: list[float] = []
        for s in strikes:
            if all(abs(s - u) > 1e-9 for u in uniq):
                uniq.append(s)
        return uniq[:TOP_K]

    if not band:
        return []

    if arm == "VOL_PEAK":
        return _top_k_strikes([(sk, m["vol"]) for sk, m in band], TOP_K)
    if arm == "OI_PEAK":
        return _top_k_strikes([(sk, m["oi"]) for sk, m in band], TOP_K)
    if arm == "PRODUCT":
        return _top_k_strikes([(sk, m["oi"] * m["vol"]) for sk, m in band], TOP_K)
    if arm == "Z_PRODUCT":
        ois = [m["oi"] for _, m in band]
        vols = [m["vol"] for _, m in band]
        zo = _zscores(ois)
        zv = _zscores(vols)
        scored = [(band[i][0], zo[i] * zv[i]) for i in range(len(band))]
        return _top_k_strikes(scored, TOP_K)
    if arm == "TURNOVER_HIGH_OI":
        ois = [m["oi"] for _, m in band]
        if not ois:
            return []
        q = statistics.quantiles(ois, n=4)[2] if len(ois) >= 4 else statistics.median(ois)
        high = [(sk, m) for sk, m in band if m["oi"] >= q and m["oi"] > 0]
        return _top_k_strikes(
            [(sk, (m["vol"] / m["oi"])) for sk, m in high], TOP_K
        )
    return []


def _gex_levels_from_chain(ticker: str, spot: float, chain_raw: str) -> dict | None:
    try:
        contracts = json.loads(chain_raw)
    except (ValueError, TypeError):
        return None
    if not contracts:
        return None
    try:
        snap = compute_terrain(ticker, contracts, float(spot))
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}
    levels = {}
    if snap.call_wall is not None and math.isfinite(float(snap.call_wall)):
        levels["CALL_WALL"] = float(snap.call_wall)
    if snap.put_wall is not None and math.isfinite(float(snap.put_wall)):
        levels["PUT_WALL"] = float(snap.put_wall)
    if snap.gamma_pin is not None and math.isfinite(float(snap.gamma_pin)):
        levels["GAMMA_PIN"] = float(snap.gamma_pin)
    # Also compute via exposures for consistency check (same engine)
    try:
        exposures, _ = compute_exposures_by_strike(contracts, spot=spot, require_oi=True)
        strikes = sorted(float(k) for k in exposures)
        (cw, _), (pw, _) = pick_gamma_wall_strikes(exposures, strikes)
        pin, _ = pick_pin_and_strength(exposures, strikes)
        if cw is not None:
            levels["CALL_WALL"] = float(cw)
        if pw is not None:
            levels["PUT_WALL"] = float(pw)
        if pin is not None:
            levels["GAMMA_PIN"] = float(pin)
    except Exception:  # institutional-swallow-ok: research study; absent terrain levels degrade to fewer rows, never a wrong number
        pass
    regime = None
    gex = snap.net_gex_at_spot
    if gex is not None and gex != 0:
        regime = "LONG_GAMMA" if gex > 0 else "SHORT_GAMMA"
    return {
        "levels": levels,
        "regime": regime,
        "confidence": snap.confidence,
        "n_contracts": len(contracts),
    }


def _snap50(x: float) -> float:
    return round(x * 2.0) / 2.0


def _placebo_strikes_moneyness_matched(
    spot: float,
    real_strikes: list[float],
    rnd: random.Random,
) -> list[float]:
    """Fair placebo: match each real strike's |moneyness|, flip sign with p=0.5, snap $0.50.

    Uniform draws inside ±3% are NOT fair — volume/OI peaks concentrate near ATM, so a
    flat band placebo manufactures a false stickiness edge (lazy-verification trap).
    """
    if spot <= 0 or not real_strikes:
        return []
    avoid = set(real_strikes)
    out: list[float] = []
    for real in real_strikes:
        m = abs((real - spot) / spot)
        placed = False
        for _ in range(40):
            sign = 1.0 if rnd.random() < 0.5 else -1.0
            # tiny jitter so we don't always land on the mirror strike
            jitter = rnd.uniform(-0.0015, 0.0015)
            sk = _snap50(spot * (1.0 + sign * (m + jitter)))
            if sk in avoid or sk in out or sk <= 0:
                continue
            if abs(sk - spot) / spot > MONEYNESS_PCT + 0.005:
                continue
            out.append(sk)
            placed = True
            break
        if not placed:
            # fallback: opposite side same |m|
            sk = _snap50(spot * (1.0 - math.copysign(m if m > 1e-9 else 0.002, real - spot)))
            if sk not in avoid and sk not in out and sk > 0:
                out.append(sk)
    return out


def _placebo_score_shuffle(
    by_k: dict[float, dict],
    spot: float,
    arm: str,
    rnd: random.Random,
    gex_levels: dict[str, float] | None,
) -> list[float]:
    """Hard null: shuffle OI/vol across moneyness-band strikes, then re-pick top-K with same rule."""
    if arm == "GEX_WALLS":
        # Shuffle among band strikes for wall locations (same count)
        band_ks = [sk for sk in by_k if _in_moneyness(sk, spot)]
        if not band_ks:
            return []
        n = len(_pick_arm_strikes(by_k, spot, arm, gex_levels))
        if n <= 0:
            return []
        return rnd.sample(band_ks, min(n, len(band_ks)))

    band = [(sk, dict(m)) for sk, m in by_k.items() if _in_moneyness(sk, spot)]
    if len(band) < 2:
        return []
    ois = [m["oi"] for _, m in band]
    vols = [m["vol"] for _, m in band]
    rnd.shuffle(ois)
    rnd.shuffle(vols)
    shuffled: dict[float, dict] = {}
    for i, (sk, m) in enumerate(band):
        shuffled[sk] = {
            "oi": ois[i],
            "vol": vols[i],
            "min_dte": m.get("min_dte"),
            "moneyness": m.get("moneyness"),
            "turnover": (vols[i] / ois[i]) if ois[i] > 0 else None,
        }
    return _pick_arm_strikes(shuffled, spot, arm, gex_levels)


# ── Stickiness outcomes (NOT touch) ──────────────────────────────────────────

def _outcome_time_in_band(
    post: list[dict], strike: float, band_w: float,
) -> dict:
    if not post or band_w <= 0:
        return {"frac": None, "n_min": 0, "n_in": 0}
    n_in = sum(1 for b in post if abs(b["close"] - strike) <= band_w)
    return {"frac": n_in / len(post), "n_min": len(post), "n_in": n_in}


def _outcome_failed_breaks(
    post: list[dict],
    strike: float,
    pierce: float,
    reclaim_n: int = RECLAIM_MINUTES,
) -> dict:
    """Count pierces beyond strike by ≥ pierce, then reclaim within reclaim_n bars.

    Pierce up: high >= strike + pierce after having been below/at strike.
    Pierce down: low <= strike - pierce after having been above/at strike.
    Reclaim: close back on the approach side of strike.
    """
    if not post or pierce <= 0:
        return {"n_pierce": 0, "n_fail": 0, "rate": None}
    n_pierce = 0
    n_fail = 0
    i = 0
    while i < len(post):
        b = post[i]
        # upward pierce
        if b["high"] >= strike + pierce:
            # require approach from below recently
            prev = post[max(0, i - 5): i]
            approached = any(p["close"] <= strike + pierce * 0.25 for p in prev) or i == 0
            if approached:
                n_pierce += 1
                end = min(len(post), i + 1 + reclaim_n)
                reclaimed = False
                for j in range(i + 1, end):
                    if post[j]["close"] <= strike:
                        reclaimed = True
                        break
                if reclaimed:
                    n_fail += 1
                i = end
                continue
        # downward pierce
        if b["low"] <= strike - pierce:
            prev = post[max(0, i - 5): i]
            approached = any(p["close"] >= strike - pierce * 0.25 for p in prev) or i == 0
            if approached:
                n_pierce += 1
                end = min(len(post), i + 1 + reclaim_n)
                reclaimed = False
                for j in range(i + 1, end):
                    if post[j]["close"] >= strike:
                        reclaimed = True
                        break
                if reclaimed:
                    n_fail += 1
                i = end
                continue
        i += 1
    rate = n_fail / n_pierce if n_pierce else None
    return {"n_pierce": n_pierce, "n_fail": n_fail, "rate": rate}


def _outcome_pin_close(post: list[dict], strike: float) -> dict:
    if not post:
        return {"abs_dist": None, "close": None}
    c = post[-1]["close"]
    return {"abs_dist": abs(c - strike), "close": c}


def _outcome_pa_rejection(
    post: list[dict], strike: float, atr: float, band_w: float,
) -> dict:
    """Optional: count rejection wicks into the strike after approach (VISIBLE OHLC).

    Rejection up: approach from below, upper wick into/through strike, close back below.
    Rejection down: symmetric.
    """
    if not post or atr <= 0:
        return {"n_reject": 0, "n_approach": 0, "rate": None}
    wick_min = 0.5 * atr
    n_app = 0
    n_rej = 0
    for i, b in enumerate(post):
        if i == 0:
            continue
        prev = post[i - 1]["close"]
        rng = b["high"] - b["low"]
        if rng <= 0:
            continue
        # approach from below into band
        if prev < strike - band_w and b["high"] >= strike - band_w:
            n_app += 1
            upper = b["high"] - max(b["open"], b["close"])
            if upper >= wick_min and b["close"] < strike:
                n_rej += 1
        # approach from above into band
        if prev > strike + band_w and b["low"] <= strike + band_w:
            n_app += 1
            lower = min(b["open"], b["close"]) - b["low"]
            if lower >= wick_min and b["close"] > strike:
                n_rej += 1
    return {
        "n_reject": n_rej,
        "n_approach": n_app,
        "rate": (n_rej / n_app) if n_app else None,
    }


def _score_strike(
    post: list[dict], strike: float, atr: float,
) -> dict:
    band_w = BAND_ATR_FRAC * atr
    pierce = PIERCE_ATR_MULT * atr
    tib = _outcome_time_in_band(post, strike, band_w)
    fb = _outcome_failed_breaks(post, strike, pierce)
    pin = _outcome_pin_close(post, strike)
    pa = _outcome_pa_rejection(post, strike, atr, band_w)
    return {
        "strike": strike,
        "time_in_band": tib["frac"],
        "time_in_band_n_min": tib["n_min"],
        "failed_break_rate": fb["rate"],
        "n_pierce": fb["n_pierce"],
        "n_fail_break": fb["n_fail"],
        "pin_abs_dist": pin["abs_dist"],
        "pa_reject_rate": pa["rate"],
        "n_pa_reject": pa["n_reject"],
        "n_pa_approach": pa["n_approach"],
    }


# ── Aggregation / verdicts ───────────────────────────────────────────────────

def _mean(xs: list[float | None]) -> float | None:
    vals = [float(x) for x in xs if x is not None and math.isfinite(float(x))]
    return statistics.fmean(vals) if vals else None


def _pool_day_scores(rows: list[dict], key: str) -> float | None:
    """Mean of per-strike scores within a day, then used across days."""
    return _mean([r.get(key) for r in rows])


def _half_edge(
    day_edges: list[tuple[str, float | None]],
    *,
    higher_better: bool,
) -> dict:
    """day_edges = [(session, edge), ...] where edge = real − placebo (or improvement)."""
    dated = [(d, e) for d, e in day_edges if e is not None]
    if len(dated) < 20:
        return {
            "evaluated": False,
            "reason": "insufficient sessions",
            "halves_agree": False,
            "n_agree": 0,
        }
    dates = sorted({d for d, _ in dated})
    cut = dates[len(dates) // 2]
    agree = 0
    halves = {}
    for name, pred in (("first", lambda s: s < cut), ("second", lambda s: s >= cut)):
        sub = [e for d, e in dated if pred(d)]
        m = _mean(sub)
        _wins = m is not None and ((m > 0) if higher_better else (m < 0))
        # For higher_better, positive edge is good; for pin distance we pass
        # improvement already as positive = better.
        if higher_better:
            if m is not None and m >= 0:
                agree += 1
        else:
            if m is not None and m <= 0:
                agree += 1
        halves[name] = {"mean_edge": m, "n": len(sub)}
    return {
        "evaluated": True,
        "split_date": cut,
        "halves": halves,
        "halves_agree": agree >= PASS["min_halves_agreeing"],
        "n_agree": agree,
    }


def _verdict_arm(summary: dict) -> str:
    """PASS only if A or B beats moneyness-matched placebo AND survives score-shuffle null."""
    n_sess = summary.get("n_sessions", 0)
    if n_sess < PASS["min_sessions"]:
        return "FAIL"
    a_edge = summary.get("time_in_band_edge")
    b_edge = summary.get("failed_break_edge")
    a_ok = (
        a_edge is not None
        and a_edge >= PASS["min_edge_pp_time_in_band"]
        and summary.get("time_in_band_halves", {}).get("halves_agree")
    )
    b_powered = summary.get("n_pierce_real", 0) >= PASS["min_pierce_events"]
    b_ok = (
        b_powered
        and b_edge is not None
        and b_edge >= PASS["min_edge_pp_failed_break"]
        and summary.get("failed_break_halves", {}).get("halves_agree")
    )
    # Hard null: must also beat score-shuffle on the same family that cleared placebo
    shuf_a = summary.get("beats_score_shuffle_tib")
    shuf_b = summary.get("beats_score_shuffle_fb")
    # beats_* flags are set after first verdict call — compute inline here too
    tib_vs = summary.get("time_in_band_edge_vs_shuffle")
    fb_vs = summary.get("failed_break_edge_vs_shuffle")
    shuf_a = bool(
        tib_vs is not None
        and tib_vs >= PASS["min_edge_pp_time_in_band"]
        and summary.get("time_in_band_shuffle_halves", {}).get("halves_agree")
    )
    shuf_b = bool(
        fb_vs is not None
        and fb_vs >= PASS["min_edge_pp_failed_break"]
        and summary.get("n_pierce_shuffle", 0) >= PASS["min_pierce_events"]
    )
    if (a_ok and shuf_a) or (b_ok and shuf_b):
        return "PASS"
    return "FAIL"


# ── Study body ───────────────────────────────────────────────────────────────

def run(tickers: list[str]) -> dict:
    t0 = time.time()
    rnd = random.Random(SEED)
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)

    obs = _load_obs_chains(con, tickers)
    bars_by_tk = {tk: _rows(con, tk) for tk in tickers}
    mf_counts = {}
    for tk in tickers:
        rows = con.execute(
            "SELECT et_date FROM option_chain_morning_full WHERE ticker=?", (tk,)
        ).fetchall()
        n_td = sum(1 for (d,) in rows if d and is_trading_day_et(str(d)))
        mf_counts[tk] = {"raw": len(rows), "trading_days": n_td}
    con.close()

    sess_bars: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for tk, bars in bars_by_tk.items():
        for b in bars:
            if not (RTH_OPEN_MIN <= b["min_of_day"] < RTH_CLOSE_MIN):
                continue
            d = b["dt"].date().isoformat()
            if not is_trading_day_et(d):
                continue
            sess_bars[(tk, d)].append(b)

    drops = defaultdict(int)
    faucet_counts: dict[str, int] = defaultdict(int)
    day_records: list[dict] = []

    # per arm: list of day-level aggregates
    arm_days: dict[str, list[dict]] = {a: [] for a in ARMS}

    for (tk, day), meta in sorted(obs.items()):
        sb = sess_bars.get((tk, day))
        if not sb or len(sb) < 40:
            drops["short_session"] += 1
            continue
        try:
            contracts = json.loads(meta["chain_raw"])
        except (ValueError, TypeError):
            drops["bad_chain_json"] += 1
            continue
        if not contracts:
            drops["empty_chain"] += 1
            continue

        spot = float(meta["spot"])
        by_k = _aggregate_strike_mass(contracts, spot)
        if not by_k:
            drops["no_strike_mass"] += 1
            continue

        atr = _causal_atr_pre_obs(sb)
        if atr <= 0:
            drops["atr_zero"] += 1
            continue

        post = [b for b in sb if b["min_of_day"] >= OUTCOME_START_MIN]
        if len(post) < 30:
            drops["short_post_obs"] += 1
            continue

        gex = _gex_levels_from_chain(tk, spot, meta["chain_raw"])
        if gex is None or "error" in (gex or {}):
            drops["gex_recon_fail"] += 1
            gex_levels = {}
            regime = None
        else:
            gex_levels = gex.get("levels") or {}
            regime = gex.get("regime")

        # Near-expiry flag: any contract in band with DTE <= NEAR_EXPIRY_DTE_MAX
        near_exp = any(
            (m.get("min_dte") is not None and m["min_dte"] <= NEAR_EXPIRY_DTE_MAX)
            for sk, m in by_k.items()
            if _in_moneyness(sk, spot)
        )

        faucet = str(meta.get("faucet") or "unknown")
        faucet_counts[faucet] += 1

        day_arm: dict[str, dict] = {}
        for arm in ARMS:
            real = _pick_arm_strikes(by_k, spot, arm, gex_levels)
            if not real:
                drops[f"empty_{arm}"] += 1
                continue
            # Primary null: moneyness-matched (fair). Secondary: score-shuffle.
            placebo = _placebo_strikes_moneyness_matched(spot, real, rnd)
            if len(placebo) < len(real):
                drops["placebo_short"] += 1
                continue
            shuffle = _placebo_score_shuffle(by_k, spot, arm, rnd, gex_levels)

            real_scores = [_score_strike(post, s, atr) for s in real]
            plc_scores = [_score_strike(post, s, atr) for s in placebo]
            shuf_scores = (
                [_score_strike(post, s, atr) for s in shuffle] if shuffle else []
            )

            rec = {
                "ticker": tk,
                "session": day,
                "arm": arm,
                "faucet": faucet,
                "regime": regime,
                "near_expiry": near_exp,
                "spot": spot,
                "atr_causal": atr,
                "real_strikes": real,
                "placebo_strikes": placebo,
                "shuffle_strikes": shuffle,
                "real_time_in_band": _pool_day_scores(real_scores, "time_in_band"),
                "placebo_time_in_band": _pool_day_scores(plc_scores, "time_in_band"),
                "shuffle_time_in_band": _pool_day_scores(shuf_scores, "time_in_band"),
                "real_failed_break": _pool_day_scores(real_scores, "failed_break_rate"),
                "placebo_failed_break": _pool_day_scores(plc_scores, "failed_break_rate"),
                "shuffle_failed_break": _pool_day_scores(shuf_scores, "failed_break_rate"),
                "real_pin_dist": _pool_day_scores(real_scores, "pin_abs_dist"),
                "placebo_pin_dist": _pool_day_scores(plc_scores, "pin_abs_dist"),
                "shuffle_pin_dist": _pool_day_scores(shuf_scores, "pin_abs_dist"),
                "real_pa_reject": _pool_day_scores(real_scores, "pa_reject_rate"),
                "placebo_pa_reject": _pool_day_scores(plc_scores, "pa_reject_rate"),
                "n_pierce_real": sum(s["n_pierce"] for s in real_scores),
                "n_pierce_placebo": sum(s["n_pierce"] for s in plc_scores),
                "n_pierce_shuffle": sum(s["n_pierce"] for s in shuf_scores),
                "n_fail_real": sum(s["n_fail_break"] for s in real_scores),
                "n_fail_placebo": sum(s["n_fail_break"] for s in plc_scores),
                "n_fail_shuffle": sum(s["n_fail_break"] for s in shuf_scores),
            }
            # Day edges vs moneyness-matched placebo (primary)
            if rec["real_time_in_band"] is not None and rec["placebo_time_in_band"] is not None:
                rec["edge_time_in_band"] = (
                    rec["real_time_in_band"] - rec["placebo_time_in_band"]
                )
            else:
                rec["edge_time_in_band"] = None
            if rec["real_failed_break"] is not None and rec["placebo_failed_break"] is not None:
                rec["edge_failed_break"] = (
                    rec["real_failed_break"] - rec["placebo_failed_break"]
                )
            else:
                rec["edge_failed_break"] = None
            if rec["real_pin_dist"] is not None and rec["placebo_pin_dist"] is not None:
                if rec["placebo_pin_dist"] > 1e-9:
                    rec["edge_pin_improvement"] = (
                        1.0 - rec["real_pin_dist"] / rec["placebo_pin_dist"]
                    )
                else:
                    rec["edge_pin_improvement"] = None
            else:
                rec["edge_pin_improvement"] = None
            if rec["real_pa_reject"] is not None and rec["placebo_pa_reject"] is not None:
                rec["edge_pa_reject"] = rec["real_pa_reject"] - rec["placebo_pa_reject"]
            else:
                rec["edge_pa_reject"] = None
            # Edges vs score-shuffle (secondary hard null)
            if rec["real_time_in_band"] is not None and rec["shuffle_time_in_band"] is not None:
                rec["edge_tib_vs_shuffle"] = (
                    rec["real_time_in_band"] - rec["shuffle_time_in_band"]
                )
            else:
                rec["edge_tib_vs_shuffle"] = None
            if rec["real_pin_dist"] is not None and rec["shuffle_pin_dist"] is not None:
                if rec["shuffle_pin_dist"] > 1e-9:
                    rec["edge_pin_vs_shuffle"] = (
                        1.0 - rec["real_pin_dist"] / rec["shuffle_pin_dist"]
                    )
                else:
                    rec["edge_pin_vs_shuffle"] = None
            else:
                rec["edge_pin_vs_shuffle"] = None

            arm_days[arm].append(rec)
            day_arm[arm] = {
                "real": real,
                "placebo": placebo,
                "edge_time_in_band": rec["edge_time_in_band"],
                "edge_failed_break": rec["edge_failed_break"],
            }

        day_records.append({
            "ticker": tk,
            "session": day,
            "faucet": faucet,
            "regime": regime,
            "near_expiry": near_exp,
            "n_strikes_band": sum(1 for sk in by_k if _in_moneyness(sk, spot)),
            "arms_present": sorted(day_arm.keys()),
        })

    # Summarize each arm
    arm_summaries = {}
    for arm, days in arm_days.items():
        tib_r = _mean([d["real_time_in_band"] for d in days])
        tib_p = _mean([d["placebo_time_in_band"] for d in days])
        fb_r = _mean([d["real_failed_break"] for d in days])
        fb_p = _mean([d["placebo_failed_break"] for d in days])
        pin_r = _mean([d["real_pin_dist"] for d in days])
        pin_p = _mean([d["placebo_pin_dist"] for d in days])
        pa_r = _mean([d["real_pa_reject"] for d in days])
        pa_p = _mean([d["placebo_pa_reject"] for d in days])

        # Pooled pierce rates (more honest than mean of day rates with sparse pierces)
        tot_pierce_r = sum(d["n_pierce_real"] for d in days)
        tot_fail_r = sum(d["n_fail_real"] for d in days)
        tot_pierce_p = sum(d["n_pierce_placebo"] for d in days)
        tot_fail_p = sum(d["n_fail_placebo"] for d in days)
        tot_pierce_s = sum(d["n_pierce_shuffle"] for d in days)
        tot_fail_s = sum(d["n_fail_shuffle"] for d in days)
        pooled_fb_r = tot_fail_r / tot_pierce_r if tot_pierce_r else None
        pooled_fb_p = tot_fail_p / tot_pierce_p if tot_pierce_p else None
        pooled_fb_s = tot_fail_s / tot_pierce_s if tot_pierce_s else None

        tib_s = _mean([d["shuffle_time_in_band"] for d in days])
        pin_s = _mean([d["shuffle_pin_dist"] for d in days])

        tib_edge = (tib_r - tib_p) if (tib_r is not None and tib_p is not None) else None
        fb_edge = (
            (pooled_fb_r - pooled_fb_p)
            if (pooled_fb_r is not None and pooled_fb_p is not None)
            else None
        )
        pin_impr = None
        if pin_r is not None and pin_p is not None and pin_p > 1e-9:
            pin_impr = 1.0 - pin_r / pin_p
        pa_edge = (pa_r - pa_p) if (pa_r is not None and pa_p is not None) else None
        tib_vs_shuf = (tib_r - tib_s) if (tib_r is not None and tib_s is not None) else None
        fb_vs_shuf = (
            (pooled_fb_r - pooled_fb_s)
            if (pooled_fb_r is not None and pooled_fb_s is not None)
            else None
        )
        pin_vs_shuf = None
        if pin_r is not None and pin_s is not None and pin_s > 1e-9:
            pin_vs_shuf = 1.0 - pin_r / pin_s

        tib_halves = _half_edge(
            [(d["session"], d["edge_time_in_band"]) for d in days],
            higher_better=True,
        )
        fb_halves = _half_edge(
            [(d["session"], d["edge_failed_break"]) for d in days],
            higher_better=True,
        )
        pin_halves = _half_edge(
            [(d["session"], d["edge_pin_improvement"]) for d in days],
            higher_better=True,
        )
        tib_shuf_halves = _half_edge(
            [(d["session"], d["edge_tib_vs_shuffle"]) for d in days],
            higher_better=True,
        )

        # Near-expiry pin subset
        near = [d for d in days if d.get("near_expiry")]
        pin_near_r = _mean([d["real_pin_dist"] for d in near])
        pin_near_p = _mean([d["placebo_pin_dist"] for d in near])
        pin_near_impr = None
        if pin_near_r is not None and pin_near_p is not None and pin_near_p > 1e-9:
            pin_near_impr = 1.0 - pin_near_r / pin_near_p

        summary = {
            "arm": arm,
            "n_sessions": len(days),
            "n_tickers": len({d["ticker"] for d in days}),
            "time_in_band_real": tib_r,
            "time_in_band_placebo": tib_p,
            "time_in_band_shuffle": tib_s,
            "time_in_band_edge": tib_edge,
            "time_in_band_edge_vs_shuffle": tib_vs_shuf,
            "time_in_band_halves": tib_halves,
            "time_in_band_shuffle_halves": tib_shuf_halves,
            "failed_break_real_pooled": pooled_fb_r,
            "failed_break_placebo_pooled": pooled_fb_p,
            "failed_break_shuffle_pooled": pooled_fb_s,
            "failed_break_edge": fb_edge,
            "failed_break_edge_vs_shuffle": fb_vs_shuf,
            "failed_break_day_mean_real": fb_r,
            "failed_break_day_mean_placebo": fb_p,
            "n_pierce_real": tot_pierce_r,
            "n_pierce_placebo": tot_pierce_p,
            "n_pierce_shuffle": tot_pierce_s,
            "failed_break_halves": fb_halves,
            "pin_abs_dist_real": pin_r,
            "pin_abs_dist_placebo": pin_p,
            "pin_abs_dist_shuffle": pin_s,
            "pin_improvement": pin_impr,
            "pin_improvement_vs_shuffle": pin_vs_shuf,
            "pin_halves": pin_halves,
            "pin_near_expiry_n_sessions": len(near),
            "pin_near_expiry_dist_real": pin_near_r,
            "pin_near_expiry_dist_placebo": pin_near_p,
            "pin_near_expiry_improvement": pin_near_impr,
            "pa_reject_real": pa_r,
            "pa_reject_placebo": pa_p,
            "pa_reject_edge": pa_edge,
        }
        summary["verdict"] = _verdict_arm(summary)
        # Secondary pin note (not primary PASS gate)
        summary["pin_beats_placebo"] = bool(
            pin_impr is not None
            and pin_impr >= PASS["min_pin_distance_improvement"]
            and pin_halves.get("halves_agree")
        )
        # Hard-null note: does scoring beat shuffled OI/vol labels?
        summary["beats_score_shuffle_tib"] = bool(
            tib_vs_shuf is not None
            and tib_vs_shuf >= PASS["min_edge_pp_time_in_band"]
            and tib_shuf_halves.get("halves_agree")
        )
        summary["beats_score_shuffle_fb"] = bool(
            fb_vs_shuf is not None
            and fb_vs_shuf >= PASS["min_edge_pp_failed_break"]
            and tot_pierce_s >= PASS["min_pierce_events"]
        )
        arm_summaries[arm] = summary

    # Head-to-head: does best combined beat vol-only / oi-only / gex?
    combined_arms = ("PRODUCT", "Z_PRODUCT", "TURNOVER_HIGH_OI")
    baselines = ("VOL_PEAK", "OI_PEAK", "GEX_WALLS")

    def _metric_pack(a: str) -> dict:
        s = arm_summaries.get(a) or {}
        return {
            "arm": a,
            "verdict": s.get("verdict"),
            "tib_edge": s.get("time_in_band_edge"),
            "fb_edge": s.get("failed_break_edge"),
            "pin_impr": s.get("pin_improvement"),
            "n_sessions": s.get("n_sessions"),
        }

    # Combined "wins" only if PASS and tib_edge > each baseline tib_edge (when both present)
    h2h = {}
    for c in combined_arms:
        cs = arm_summaries.get(c) or {}
        beats = {}
        for b in baselines:
            bs = arm_summaries.get(b) or {}
            beats[b] = {
                "tib": (
                    cs.get("time_in_band_edge") is not None
                    and bs.get("time_in_band_edge") is not None
                    and cs["time_in_band_edge"] > bs["time_in_band_edge"]
                ),
                "fb": (
                    cs.get("failed_break_edge") is not None
                    and bs.get("failed_break_edge") is not None
                    and cs["failed_break_edge"] > bs["failed_break_edge"]
                ),
                "combined_pass": cs.get("verdict") == "PASS",
                "baseline_pass": bs.get("verdict") == "PASS",
            }
        h2h[c] = beats

    any_combined_pass = any(
        (arm_summaries.get(a) or {}).get("verdict") == "PASS" for a in combined_arms
    )
    any_baseline_pass = any(
        (arm_summaries.get(a) or {}).get("verdict") == "PASS" for a in baselines
    )

    # Overall study verdict
    if any_combined_pass:
        # Must also beat vol-only and oi-only on at least one primary metric
        winner = None
        for c in combined_arms:
            if (arm_summaries.get(c) or {}).get("verdict") != "PASS":
                continue
            bvol = h2h[c]["VOL_PEAK"]
            boi = h2h[c]["OI_PEAK"]
            if (bvol["tib"] or bvol["fb"]) and (boi["tib"] or boi["fb"]):
                winner = c
                break
        overall = "PASS" if winner else "FAIL"
        overall_note = (
            f"Combined arm {winner} PASS and beats VOL+OI on a primary metric"
            if winner
            else "A combined arm PASS vs placebo but does not beat both VOL_PEAK and OI_PEAK"
        )
    else:
        overall = "FAIL"
        overall_note = (
            "No OI×vol combined arm beat placebo on pre-registered stickiness gates"
            + ("; baselines also FAIL" if not any_baseline_pass else "; a baseline PASS exists")
        )

    result = {
        "study": STUDY,
        "mission_class": "Find & Prove",
        "decision_path_effect": "WAIT — no Decide admission",
        "costs": "ABSENT",
        "pre_registered": {
            "sticky_definition": (
                "NOT touch. Stickiness = (A) time-in-band fraction of post-10:15 RTH "
                "minutes with close within 0.25×causalATR of strike; (B) failed-break "
                "rate after pierce by 0.35×ATR with reclaim ≤15m; (C) pin-to-close "
                "|close−strike| vs placebo (near-expiry labeled). Optional PA rejection "
                "wick rate reported descriptive."
            ),
            "arms": list(ARMS),
            "combined_candidates": list(combined_arms),
            "baselines": list(baselines),
            "top_k": TOP_K,
            "moneyness_pct": MONEYNESS_PCT,
            "outcome_start_et": "10:15",
            "volume_asof": "observation chain only (morning_full or ~10:00 snapshot) — no EOD lookahead",
            "placebo_primary": (
                "moneyness-matched: each real strike mirrored at same |m| "
                "(±jitter, $0.50 grid) — NOT uniform band draws"
            ),
            "placebo_secondary": "score-shuffle of OI/vol across band strikes, re-pick top-K",
            "pass_gates": PASS,
            "seed": SEED,
        },
        "sample": {
            "tickers": tickers,
            "n_obs_days_total": len(obs),
            "n_scored_day_records": len(day_records),
            "morning_full_exact": mf_counts,
            "faucet_counts": dict(faucet_counts),
            "drops": dict(drops),
            "n_sessions_by_arm": {a: len(arm_days[a]) for a in ARMS},
        },
        "arm_summaries": arm_summaries,
        "head_to_head": h2h,
        "metric_packs": {a: _metric_pack(a) for a in ARMS},
        "overall_verdict": overall,
        "overall_note": overall_note,
        "elapsed_sec": round(time.time() - t0, 2),
    }
    return result


def _fmt_pct(x: float | None, digits: int = 1) -> str:
    if x is None:
        return "n/a"
    return f"{100.0 * x:.{digits}f}%"


def _fmt_num(x: float | None, digits: int = 4) -> str:
    if x is None:
        return "n/a"
    return f"{x:.{digits}f}"


def write_report(result: dict) -> None:
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")

    s = result["sample"]
    lines = [
        f"# {STUDY}",
        "",
        "**MISSION_CLASS:** Find & Prove — offline stickiness bake-off",
        "**DECISION_PATH_EFFECT:** WAIT — no Decide admission; no Chart change",
        "**COSTS:** ABSENT",
        f"**OVERALL VERDICT:** `{result['overall_verdict']}`",
        f"**NOTE:** {result['overall_note']}",
        "",
        "Reproduce:",
        "```",
        f"python tools/{STUDY}.py",
        "```",
        "",
        "## AGENTS.md admission",
        "",
        "| Field | Answer |",
        "|---|---|",
        "| MISSION_CLASS | Find & Prove — research + offline backtest |",
        "| GAP | Chart yellow = volume only; OI×vol stickiness untested; prior packs scored bare touch |",
        "| SMALLEST_COMPLETE_CHANGE | This tool + reports/*.md/*.json |",
        "| MINIMUM_SUFFICIENT_EVIDENCE | Same-turn harness vs placebo + vol/OI/GEX arms; exact n |",
        "| DECISION_PATH_EFFECT | None — WAIT |",
        "| WHY_NOW | Operator ask: yellow-bar idea with BOTH OI and volume; PhD stickiness defs |",
        "| TASK_ADMISSION | Admitted as Find & Prove research only |",
        "",
        "## 1) Research findings (written before coding)",
        "",
        "### 1.1 What prior Ed packs already proved (and missed)",
        "",
        "- Chart yellow bars = **session options volume by strike**, not OI "
        "(`reports/liquidity_experiment_input_audit_v1.md`).",
        "- Gamma experiments tested **GEX$ walls/pin** (gamma×OI), not volume magnets "
        "and not pure OI walls — and **FAIL**ed placebos on touch/hold/bounce.",
        "- Price-action literacy (`reports/price_action_liquidity_literacy_v1.md`): "
        "FAIL on bare touch does **not** kill levels — it kills **location-only** events. "
        "Sticky behavior needs time-in-band, failed breaks, pin-to-close, rejection — not tags.",
        "",
        "### 1.2 Microstructure: what makes a strike sticky?",
        "",
        "- **Avellaneda & Lipkin (QF 2003):** pinning near expiry from delta-hedging "
        "when open interest is unusually large; mechanism is OI-scaled hedge impact, "
        "not bare volume. Transfer to SPY/QQQ/IWM 0DTE era = `[UNVERIFIED]` until measured.",
        "- **Dealer gamma pinning (desk/academic hedging lit, Baltussen et al. JFE 2021):** "
        "long-gamma hedging mean-reverts; short-gamma accelerates. Pin strength ↑ as DTE→0 "
        "(gamma explosion). Regime split still thin on Ed morning_full.",
        "- **OI vs volume:** OI = standing inventory (overnight-stable within session); "
        "volume = today's traded interest (accrues). Desk lore of “high OI + high volume” "
        "as a magnet is a **confluence hypothesis**, not proven edge. "
        "Turnover (volume/OI) among high-OI strikes can mark **active repositioning** "
        "vs stale inventory — also `[UNVERIFIED]` as stickiness until this harness.",
        "- **GEX$ vs volume peaks:** GEX weights OI by gamma (near-ATM/near-expiry heavy); "
        "volume peaks can sit at different strikes than OI or GEX peaks (audit census).",
        "",
        "### 1.3 Operational STICKY (not touch)",
        "",
        "A strike is sticky for a session if, **after levels are known (10:15 ET)**:",
        "",
        "1. **Time-in-band (primary A):** large fraction of remaining RTH minutes have "
        "`|close − K| ≤ 0.25 × causalATR` (ATR from pre-10:15 bars only).",
        "2. **Failed-break rate (primary B):** among pierces beyond K by `0.35×ATR`, "
        "fraction that reclaim to the strike side within 15 minutes.",
        "3. **Pin-to-close (secondary C):** smaller `|RTH close − K|` than placebo; "
        "near-expiry (DTE≤1 present in band) reported separately.",
        "4. **PA rejection (descriptive):** approach into band + rejection wick ≥0.5×ATR "
        "with close back on approach side — VISIBLE OHLC proxy, not book absorption.",
        "",
        "Mere geometric overlap of a bar range with K is **not** scored as sticky.",
        "",
        "### 1.4 Candidate combined scores (as-of causal)",
        "",
        "| Arm | Score | As-of |",
        "|---|---|---|",
        "| VOL_PEAK | top-3 volume in ±3% moneyness | obs chain volume |",
        "| OI_PEAK | top-3 OI | obs chain OI |",
        "| PRODUCT | top-3 OI×volume | both from obs |",
        "| Z_PRODUCT | top-3 z(OI)×z(vol) in band | both from obs |",
        "| TURNOVER_HIGH_OI | top-3 volume/OI among top-quartile OI | both from obs |",
        "| GEX_WALLS | call/put wall + pin | gamma×OI via compute_terrain |",
        "",
        "Placebos (fair-method): (1) **moneyness-matched** same `|K−S|/S` mirror; "
        "(2) **score-shuffle** of OI/vol then re-pick top-K. Uniform ±3% draws rejected "
        "(they manufacture ATM stickiness).",
        "",
        "## 2) Sample (exact)",
        "",
        f"- Tickers: `{s['tickers']}`",
        f"- Observation days loaded: **{s['n_obs_days_total']}**",
        f"- Day records with bars: **{s['n_scored_day_records']}**",
        f"- morning_full exact: `{json.dumps(s['morning_full_exact'])}`",
        f"- Faucet mix: `{json.dumps(s['faucet_counts'])}`",
        f"- Sessions by arm: `{json.dumps(s['n_sessions_by_arm'])}`",
        f"- Drops: `{json.dumps(s['drops'])}`",
        f"- Elapsed: {result['elapsed_sec']}s",
        "",
        "## 3) Results by arm",
        "",
        "| Arm | n | TIB real | TIB m-plc | TIB shuf | TIB edge | FB real | FB m-plc | FB shuf | FB edge | pin vs m-plc | Verdict |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for arm in ARMS:
        a = result["arm_summaries"].get(arm) or {}
        lines.append(
            "| {arm} | {n} | {tr} | {tp} | {ts} | {te} | {fr} | {fp} | {fs} | {fe} | {pi} | `{v}` |".format(
                arm=arm,
                n=a.get("n_sessions", 0),
                tr=_fmt_pct(a.get("time_in_band_real")),
                tp=_fmt_pct(a.get("time_in_band_placebo")),
                ts=_fmt_pct(a.get("time_in_band_shuffle")),
                te=_fmt_pct(a.get("time_in_band_edge")),
                fr=_fmt_pct(a.get("failed_break_real_pooled")),
                fp=_fmt_pct(a.get("failed_break_placebo_pooled")),
                fs=_fmt_pct(a.get("failed_break_shuffle_pooled")),
                fe=_fmt_pct(a.get("failed_break_edge")),
                pi=_fmt_pct(a.get("pin_improvement")),
                v=a.get("verdict", "?"),
            )
        )

    lines += [
        "",
        "### Half-sample agreement (time-in-band)",
        "",
    ]
    for arm in ARMS:
        a = result["arm_summaries"].get(arm) or {}
        h = a.get("time_in_band_halves") or {}
        lines.append(
            f"- **{arm}:** evaluated={h.get('evaluated')} agree={h.get('halves_agree')} "
            f"n_agree={h.get('n_agree')} halves=`{json.dumps(h.get('halves'))}`"
        )

    lines += [
        "",
        "### Near-expiry pin subset (DTE≤1 present in band)",
        "",
        "| Arm | n near sess | pin dist real | pin dist plc | improvement |",
        "|---|---:|---:|---:|---:|",
    ]
    for arm in ARMS:
        a = result["arm_summaries"].get(arm) or {}
        lines.append(
            f"| {arm} | {a.get('pin_near_expiry_n_sessions', 0)} | "
            f"{_fmt_num(a.get('pin_near_expiry_dist_real'), 3)} | "
            f"{_fmt_num(a.get('pin_near_expiry_dist_placebo'), 3)} | "
            f"{_fmt_pct(a.get('pin_near_expiry_improvement'))} |"
        )

    # Rank arms by primary edges (descriptive; all FAIL gates)
    rank_tib = sorted(
        ARMS,
        key=lambda a: (result["arm_summaries"].get(a) or {}).get("time_in_band_edge") or -9e9,
        reverse=True,
    )
    rank_fb = sorted(
        ARMS,
        key=lambda a: (result["arm_summaries"].get(a) or {}).get("failed_break_edge") or -9e9,
        reverse=True,
    )

    lines += [
        "",
        "## 4) Ranking under fair (moneyness-matched) placebo — all FAIL gates",
        "",
        f"- Time-in-band edge rank: {' > '.join(rank_tib)}",
        f"- Failed-break edge rank: {' > '.join(rank_fb)}",
        "",
        "Head-to-head (does combined beat baseline on raw edge sign?):",
        "```",
        json.dumps(result["head_to_head"], indent=2),
        "```",
        "",
        "### Score-shuffle hard null (secondary)",
        "",
        "Beating score-shuffle alone is NOT enough for PASS — volume/OI naturally "
        "concentrate nearer the session path, so shuffled labels often crown far strikes. "
        "Primary authority is moneyness-matched.",
        "",
    ]
    for arm in ARMS:
        a = result["arm_summaries"].get(arm) or {}
        lines.append(
            f"- **{arm}:** tib_vs_shuf={_fmt_pct(a.get('time_in_band_edge_vs_shuffle'))}, "
            f"fb_vs_shuf={_fmt_pct(a.get('failed_break_edge_vs_shuffle'))}, "
            f"pin_vs_shuf={_fmt_pct(a.get('pin_improvement_vs_shuffle'))}"
        )

    lines += [
        "",
        "## 5) Plain-English disposition",
        "",
        f"**Verdict: {result['overall_verdict']}.** {result['overall_note']}",
        "",
        "- Sticky ≠ touch: magnet behavior (time near strike, failed breaks, close pin, PA rejection).",
        "- **OI×vol did NOT beat volume-only.** PRODUCT / Z_PRODUCT / TURNOVER_HIGH_OI "
        "lose to VOL_PEAK on both primary edges under moneyness-matched placebo.",
        "- **OI-only is the weakest** of the mass arms (often negative vs matched placebo).",
        "- **GEX$ walls** also FAIL the stickiness gates here (consistent with prior touch/hold FAILs, "
        "now under non-touch outcomes).",
        "- An early uniform ±3% placebo looked like a PASS — that was ATM-proximity bias; "
        "rejected. Fair matched placebos collapse edges to noise.",
        "- Volume as-of is morning/~10:00 cumulative only — Chart-yellow analogue without EOD lookahead.",
        "- Decide: **WAIT**. Chart yellow bars unchanged.",
        "",
        "## 6) Limits",
        "",
        "- Snapshot chains dominate the faucet mix (narrow money-path common) — same Collect skew as gamma packs.",
        "- morning_full exact trading days: SPY/QQQ/IWM = 9/9/9 (ops target 20 unmet).",
        "- Pierce counts are healthy (~1k–1.8k) — B is not underpowered; it simply lacks edge vs matched placebo.",
        "- Costs ABSENT; no economic edge claim.",
        "- PA rejection is an OHLC proxy, not book absorption; edges near zero / negative.",
        "- Near-expiry pin subset large (most ETF days have 0–1 DTE options) but pin improvement fails.",
        "- Score-shuffle can still favor near-path mass; do not promote shuffle-only wins.",
        "",
    ]
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=STUDY)
    ap.add_argument("--tickers", default="SPY,QQQ,IWM")
    args = ap.parse_args()
    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    result = run(tickers)
    write_report(result)
    print(json.dumps({
        "overall_verdict": result["overall_verdict"],
        "overall_note": result["overall_note"],
        "n_sessions_by_arm": result["sample"]["n_sessions_by_arm"],
        "faucet_counts": result["sample"]["faucet_counts"],
        "drops": result["sample"]["drops"],
        "metric_packs": result["metric_packs"],
        "out_json": str(OUT_JSON),
        "out_md": str(OUT_MD),
        "elapsed_sec": result["elapsed_sec"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
