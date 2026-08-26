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

from math_levels import (  # noqa: E402
    SIGN_MODEL_EMPIRICAL_PRIOR,
    compute_gamma_profile,
    gamma_at_price,
)
from terrain_engine import compute_terrain  # noqa: E402
from time_et import ET, RTH_END_MINS, RTH_START_MINS  # noqa: E402

DB = ROOT / "data" / "ed_console.db"
OUT_MD = ROOT / "reports" / "terrain_backtest_latest.md"
OUT_JSON = ROOT / "reports" / "terrain_backtest_latest.json"

SENTINELS = {"SPY", "QQQ", "IWM"}
#: Chain selection window around 10:00 ET — late enough for opening OI/greeks to settle,
#: early enough that the whole session remains to be predicted.
OBS_LO_MIN, OBS_HI_MIN = int(RTH_START_MINS) + 15, int(RTH_START_MINS) + 45
#: Realized window: strictly AFTER observation (no lookahead), to just before the close.
REAL_LO_MIN, REAL_HI_MIN = OBS_HI_MIN, int(RTH_END_MINS) - 5


def _et_day_and_min(ts: float) -> tuple[str, int]:
    d = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(ET)
    return d.strftime("%Y-%m-%d"), d.hour * 60 + d.minute


def _is_measurable_day(day: str) -> bool:
    """RC-58: only real trading days may enter this scorecard.

    The windows above are minute-of-day only, so weekend and holiday rows were admitted:
    MEASURED 245 of 1,548 joinable ticker-days (15.8 percent). That is not noise, it is a
    DETERMINISTIC bias — a market-closed day's bars are frozen (high == low on 100 percent of
    sampled weekend bars), its realized range is ~0.05 percent vs ~2.21 percent on trading days
    with NO distribution overlap, so every such day is automatically classed low-range: a
    guaranteed hit for LONG_GAMMA_CHOP, a guaranteed miss for short gamma, and a guaranteed
    wall hold (a frozen high cannot exceed a call wall). It inflated the wall-hold KPI and tied
    ~245 range values at the bottom rank of every Spearman rho.
    """
    from time_et import is_trading_day_et
    return is_trading_day_et(day)


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
        if not _is_measurable_day(day):     # RC-58: weekend / holiday -> never scored
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
            if not _is_measurable_day(day):     # RC-58: frozen weekend/holiday bars bias to null
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


def _regime_for_scoring(
    regime: str,
    net_gex_at_spot: float | None,
    *,
    spot: float | None = None,
    flip: float | None = None,
) -> str | None:
    """The regime this RESEARCH tool scores — raw naive sign, independent of display.

    SIGN-DEMOTION (2026-07-22) withholds the single-name regime LABEL from the UI,
    and compute_terrain now returns SIGN_UNPROVEN for those rows. But this tool IS
    the restoration test: dropping demoted rows would empty the single-name buckets,
    halt the TU-04 A/B accrual, and make the sentinel-vs-single split — the very
    test that gates restoration — impossible to run (a self-locking door, caught by
    adversarial review the same day the demotion shipped). Research measures the
    raw hypothesis; only the display withholds the verdict.

    Sign source mirrors terrain_read._regime_for (RC-11): net_gex_at_spot IS
    flip_diag.gamma_at_spot; when it is None/0, fall through to spot-vs-flip so
    pre/post-demotion scoring stays bit-identical for previously-scored rows.
    """
    if regime in ("LONG_GAMMA_CHOP", "SHORT_GAMMA_TREND"):
        return regime
    if regime != "SIGN_UNPROVEN":
        return None
    if net_gex_at_spot is not None and net_gex_at_spot != 0:
        return "LONG_GAMMA_CHOP" if net_gex_at_spot > 0 else "SHORT_GAMMA_TREND"
    if flip is not None and spot is not None:
        return "LONG_GAMMA_CHOP" if spot > flip else "SHORT_GAMMA_TREND"
    return None


def _replay_instant(ts_utc):
    """The stored snapshot's instant as ET-aware datetime — the valuation clock for a replay.

    Gamma audit 2026-08-26: every reprice in this report must value contracts as of the SNAPSHOT,
    not as of the run. Returns None when the timestamp is unusable, which makes compute_terrain
    fall back to now_et() exactly as before — degrade, never crash a report.
    """
    from time_et import ET
    try:
        return datetime.fromtimestamp(float(ts_utc), tz=ET)
    except (TypeError, ValueError, OSError, OverflowError):
        return None


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
        # Gamma audit 2026-08-26: reprice at the SNAPSHOT's instant, not today's clock. `_ts` was
        # unpacked and ignored, so every stored chain was revalued against now(): contracts whose
        # expiry has since passed return T=None and are DROPPED from the profile, and the survivors
        # get an understated T. The backtest was therefore scoring a chain the live engine never saw
        # — a validation result computed on the wrong clock is not evidence.
        _snap_now = _replay_instant(_ts)
        snap = compute_terrain(tk, contracts, float(spot), now=_snap_now)
        scoring_regime = _regime_for_scoring(
            snap.regime, snap.net_gex_at_spot,
            spot=float(spot), flip=snap.gamma_flip,
        )
        if scoring_regime is None:
            continue
        # WEIGHTING HEAD-TO-HEAD (operator challenge 2026-07-22 "we have enough
        # data... your testing or data was wrong"): the volume-vs-OI divergence
        # study could not attribute blame. This can: the FULL volume-weighted
        # terrain (same production pipeline, substituted inputs) on every scored
        # day, judged by the same forward outcomes — realized range, hit-vs-own-
        # median, and wall holds. Arbiter is reality, not agreement.
        from tools.study_volume_vs_oi_terrain_v1 import volume_substituted
        gas_vol = vol_cw = vol_pw = None
        vol_regime = None
        try:
            vol_contracts, _n_vol = volume_substituted(contracts)
            snap_vol = compute_terrain(tk, vol_contracts, float(spot))
            gas_vol = snap_vol.net_gex_at_spot
            vol_cw, vol_pw = snap_vol.call_wall, snap_vol.put_wall
            vol_regime = _regime_for_scoring(
                snap_vol.regime, gas_vol, spot=float(spot), flip=snap_vol.gamma_flip)
        except Exception as exc:
            # A day whose volume-substituted terrain cannot compute scores as
            # ABSENT on the volume map (hit_vol None; excluded from same-row
            # comparisons) — never fabricated. Printed so a systematic failure
            # is visible in the run log, not silent.
            print(f"volume-map compute failed {tk} {day}: {type(exc).__name__}: {exc}")
        # TU-04 A/B: the GPO empirical prior (+call/+put) for single names. Net gamma
        # under it is C+P > 0 ALWAYS, so it is a CONSTANT LONG_GAMMA classifier — the
        # honest A/B question is "does naive's short-gamma call beat 'always dampen'?"
        # Computed anyway (never assumed) so a chain that violates the expectation
        # would show up as data, not dogma. Sentinels stay naive-only (index naive is
        # validated; the prior is a single-name hypothesis).
        regime_prior = None
        if tk not in SENTINELS:
            gp = gamma_at_price(
                compute_gamma_profile(contracts, float(spot),
                                      sign_model=SIGN_MODEL_EMPIRICAL_PRIOR,
                                      now=_snap_now),   # gamma audit: snapshot clock, not today's
                float(spot))
            if gp is not None and gp != 0:
                regime_prior = "LONG_GAMMA_CHOP" if gp > 0 else "SHORT_GAMMA_TREND"
        scored.append({
            "ticker": tk, "day": day, "regime": scoring_regime,
            "net_gex_at_spot": snap.net_gex_at_spot,
            "net_gex_at_spot_vol": gas_vol,
            "regime_vol": vol_regime,
            "call_wall_vol": vol_cw, "put_wall_vol": vol_pw,
            "regime_prior": regime_prior,
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
        rp = r.get("regime_prior")
        r["hit_prior"] = ((rp == "SHORT_GAMMA_TREND") == r["range_class_high"]
                          if rp is not None else None)
        rv = r.get("regime_vol")
        r["hit_vol"] = ((rv == "SHORT_GAMMA_TREND") == r["range_class_high"]
                        if rv is not None else None)
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
    # RC-130: the working-side filter is CORRECT (SpotGamma's own SPX stats condition the
    # same way — "held" is meaningless for a wall already breached at observation) but it
    # was SILENT. The excluded wrong-side rows are now counted and reported, so the KPI
    # states its own denominator instead of implying it covered every session.
    cx = px = 0
    for r in rows:
        cw, pw, spot = r.get("call_wall"), r.get("put_wall"), r.get("spot")
        hi, lo, close = r.get("high"), r.get("low"), r.get("close")
        if None in (spot, hi, lo, close):
            continue
        if cw is not None and cw > spot:
            cn += 1
            ch += hi <= cw
            ccb += close <= cw
        elif cw is not None:
            cx += 1
        if pw is not None and pw < spot:
            pn += 1
            ph += lo >= pw
            pca += close >= pw
        elif pw is not None:
            px += 1
    pct = lambda h, n: round(100.0 * h / n, 1) if n else None  # noqa: E731
    return {"call_n": cn, "call_held_pct": pct(ch, cn), "call_close_below_pct": pct(ccb, cn),
            "put_n": pn, "put_held_pct": pct(ph, pn), "put_close_above_pct": pct(pca, pn),
            "call_excluded_breached_at_obs": cx, "put_excluded_breached_at_obs": px,
            "spotgamma_spx_benchmark": SG_BENCH}


def _sign_ab(rows: list[dict]) -> dict:
    """TU-04: naive vs empirical-prior hit rates on the SAME single-name rows."""
    ab = [r for r in rows if r["ticker"] not in SENTINELS and r.get("hit_prior") is not None]
    n = len(ab)
    if not n:
        return {"n": 0, "naive_hit_pct": None, "prior_hit_pct": None,
                "prior_always_long_pct": None}
    always_long = sum(r.get("regime_prior") == "LONG_GAMMA_CHOP" for r in ab)
    return {
        "n": n,
        "naive_hit_pct": round(100 * sum(r["hit"] for r in ab) / n, 1),
        "prior_hit_pct": round(100 * sum(r["hit_prior"] for r in ab) / n, 1),
        # measured, not assumed: expected 100.0 (C+P>0); anything else = data anomaly
        "prior_always_long_pct": round(100 * always_long / n, 1),
    }


def _spearman(a: list[float], b: list[float]) -> float | None:
    """Spearman rho via rank Pearson (ties -> average rank). Pure python, n up to ~3k."""
    n = len(a)
    if n < 8 or n != len(b):
        return None

    def ranks(v: list[float]) -> list[float]:
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

    ra, rb = ranks(a), ranks(b)
    ma, mb = sum(ra) / n, sum(rb) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb, strict=True))
    da = sum((x - ma) ** 2 for x in ra) ** 0.5
    db = sum((y - mb) ** 2 for y in rb) ** 0.5
    return num / (da * db) if da > 0 and db > 0 else None


def _sign_split_gex_r1(rows: list[dict], n_perm: int = 2000, seed: int = 20260722) -> dict:
    """REGISTERED TEST 1 of the single-name sign row (due 2026-08-03): the GEX-R1
    gamma-vs-range correlation, split sentinels vs single names.

    GEX-R1 (sentinel-confirmed): signed dealer gamma correlates NEGATIVELY with
    realized range (long gamma dampens). If the naive sign convention breaks on
    single names, their correlation degrades toward zero or flips. Permutation p
    (one-sided, rho<0) via day-shuffle within each universe; seeded, reproducible.
    Run 2026-07-22 the night the test unblocked — nothing gated it but the queue.
    """
    import random
    out: dict[str, dict] = {}
    for name, pred in (("sentinels", lambda r: r["ticker"] in SENTINELS),
                       ("single_names", lambda r: r["ticker"] not in SENTINELS)):
        sub = [r for r in rows
               if pred(r) and r.get("net_gex_at_spot") is not None]
        g = [float(r["net_gex_at_spot"]) for r in sub]
        rng_ = [float(r["range_pct"]) for r in sub]
        rho = _spearman(g, rng_)
        p = None
        if rho is not None:
            rnd = random.Random(seed)
            worse = 0
            for _ in range(n_perm):
                shuffled = rng_[:]
                rnd.shuffle(shuffled)
                rp = _spearman(g, shuffled)
                if rp is not None and rp <= rho:
                    worse += 1
            p = round(worse / n_perm, 4)
        out[name] = {"n": len(sub),
                     "spearman_gamma_vs_range": round(rho, 4) if rho is not None else None,
                     "p_one_sided_neg": p}
    return out


def _weighting_head_to_head(rows: list[dict]) -> dict:
    """OI- vs VOLUME-weighted gamma judged by the SAME realized range, same rows.

    PRE-REGISTERED DECISION RULE (written 2026-07-22 BEFORE the first run, after
    the divergence study proved only that the weightings disagree, not who is
    wrong): per universe, on rows where BOTH weightings produce a value, compare
    Spearman(gamma_at_spot, realized range). More NEGATIVE rho (stronger
    dampening read) wins; |delta rho| < 0.03 is a TIE. Reality is the arbiter.
    """
    out: dict[str, dict] = {}
    for name, pred in (("sentinels", lambda r: r["ticker"] in SENTINELS),
                       ("single_names", lambda r: r["ticker"] not in SENTINELS),
                       ("all", lambda _r: True)):
        sub = [r for r in rows if pred(r)
               and r.get("net_gex_at_spot") is not None
               and r.get("net_gex_at_spot_vol") is not None]
        rng_ = [float(r["range_pct"]) for r in sub]
        rho_oi = _spearman([float(r["net_gex_at_spot"]) for r in sub], rng_)
        rho_vol = _spearman([float(r["net_gex_at_spot_vol"]) for r in sub], rng_)
        winner = None
        if rho_oi is not None and rho_vol is not None:
            delta = rho_oi - rho_vol
            winner = ("TIE" if abs(delta) < 0.03
                      else ("OI" if rho_oi < rho_vol else "VOLUME"))
        out[name] = {"n": len(sub),
                     "rho_oi": round(rho_oi, 4) if rho_oi is not None else None,
                     "rho_vol": round(rho_vol, 4) if rho_vol is not None else None,
                     "winner": winner}
    return out


def _weighting_scorecard(rows: list[dict], scored: list[dict]) -> dict:
    """Map A (OI) vs Map B (VOLUME) vs placebo on FORWARD outcomes — the full
    predictive scorecard (external directive 2026-07-22; comparison rules the
    same pre-set family as the rho head-to-head: same rows, reality as arbiter).

    hit% = regime vs own-median range class, computed on rows where BOTH maps
    classify (no universe mismatch); placebo = yesterday's class persists, on
    the same row set. Wall holds use each map's OWN walls on identical days.
    """
    out: dict[str, dict] = {}
    for name, pred in (("sentinels", lambda r: r["ticker"] in SENTINELS),
                       ("single_names", lambda r: r["ticker"] not in SENTINELS)):
        both = [r for r in rows if pred(r) and r.get("hit_vol") is not None]
        n = len(both)
        p_hit, p_n = _placebo_persistence(both)
        vol_wall_rows = [
            {"spot": r["spot"], "call_wall": r.get("call_wall_vol"),
             "put_wall": r.get("put_wall_vol"), "high": r.get("high"),
             "low": r.get("low"), "close": r.get("close")}
            for r in scored if pred(r)]
        out[name] = {
            "n_both_classified": n,
            "hit_oi_pct": round(100 * sum(r["hit"] for r in both) / n, 1) if n else None,
            "hit_vol_pct": round(100 * sum(r["hit_vol"] for r in both) / n, 1) if n else None,
            "placebo_pct": round(100 * p_hit / p_n, 1) if p_n else None,
            "wall_hold_oi": wall_hold_stats([r for r in scored if pred(r)]),
            "wall_hold_vol": wall_hold_stats(vol_wall_rows),
        }
    return out


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
        # Corrected 2026-08-26: `narrow_chain_only` was `confidence != "TRUSTED"`, which was
        # accurate when there were only two tiers. There are now three, so that predicate also
        # swept in LEVEL_APPROX_NARROW_SPAN rows — chains wide enough for a sound at-spot regime,
        # merely too narrow to place the LEVEL — and reported them under a "LOW_CONFIDENCE" label.
        # Split so each bucket means what its name says.
        "level_approx_only": bucket(lambda r: r["confidence"] == "LEVEL_APPROX_NARROW_SPAN"),
        "narrow_chain_only": bucket(lambda r: r["confidence"] == "LOW_CONFIDENCE_NARROW_CHAIN"),
        "sentinels": bucket(lambda r: r["ticker"] in SENTINELS),
        "single_names": bucket(lambda r: r["ticker"] not in SENTINELS),
        "long_gamma_days": bucket(lambda r: r["regime"] == "LONG_GAMMA_CHOP"),
        "short_gamma_days": bucket(lambda r: r["regime"] == "SHORT_GAMMA_TREND"),
        "placebo_persistence": {"n": p_n,
                                "hit_pct": round(100 * p_hit / p_n, 1) if p_n else None},
        # TU-04 sign-model A/B, single names only. Reported WITH its structural note:
        # the prior is constant-LONG by construction (C+P>0), so this measures whether
        # naive's short-gamma discrimination adds anything over "always dampen".
        "sign_ab_single_names": _sign_ab(rows),
        # REGISTERED TEST 1 (single-name sign row, due 2026-08-03): GEX-R1 split.
        "sign_split_gex_r1": _sign_split_gex_r1(rows),
        # Weighting head-to-head: reality as arbiter (rule pre-set in the fn).
        "weighting_head_to_head": _weighting_head_to_head(rows),
        # Full predictive scorecard: hit% vs placebo + wall holds, both maps.
        "weighting_scorecard": _weighting_scorecard(rows, scored),
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


def _sign_ab_line(ab: dict) -> str:
    if not ab.get("n"):
        return "_No A/B rows scored yet._"
    return (f"naive {ab['naive_hit_pct']}% vs empirical-prior {ab['prior_hit_pct']}% on "
            f"n={ab['n']} shared rows (prior classified LONG on "
            f"{ab['prior_always_long_pct']}% of rows — it is constant-LONG by "
            f"construction, C+P>0, so this measures whether naive's short-gamma call "
            f"beats 'always dampen'; GPO prior, Garleanu-Pedersen-Poteshman Table 1).")


def _wall_line(name: str, w: dict) -> str:
    def v(x):
        return "—" if x is None else f"{x}%"
    return (f"| {name} | {w['call_n']} | {v(w['call_held_pct'])} | "
            f"{v(w['call_close_below_pct'])} | {w['put_n']} | {v(w['put_held_pct'])} | "
            f"{v(w['put_close_above_pct'])} |")


def _pct(x) -> str:
    return "—" if x is None else f"{x}%"


def _weighting_md(rep: dict) -> list[str]:
    """TU-13 parallel OI-vs-VOLUME table — surfaces scorecard + rho head-to-head."""
    sc = rep.get("weighting_scorecard") or {}
    hh = rep.get("weighting_head_to_head") or {}
    lines = [
        "## TU-13 OI-vs-VOLUME regime A/B (parallel profile — never silent swap)",
        "",
        "| universe | n both | OI hit% | VOL hit% | placebo% | rho OI | rho VOL | winner |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name, label in (("sentinels", "sentinels (SPY/QQQ/IWM)"),
                        ("single_names", "single names")):
        s = sc.get(name) or {}
        h = hh.get(name) or {}
        lines.append(
            f"| {label} | {s.get('n_both_classified', 0)} | "
            f"{_pct(s.get('hit_oi_pct'))} | {_pct(s.get('hit_vol_pct'))} | "
            f"{_pct(s.get('placebo_pct'))} | "
            f"{h.get('rho_oi') if h.get('rho_oi') is not None else '—'} | "
            f"{h.get('rho_vol') if h.get('rho_vol') is not None else '—'} | "
            f"{h.get('winner') or '—'} |"
        )
    lines += [
        "",
        "_Parallel-profile law (TU-04 pattern): a weighting swap goes through PDCA "
        "rules, never a silent default change. History accrues `ab_*` fields from "
        "the sentinel slice (sign-proven universe)._",
        "",
    ]
    return lines


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
        line("coverage OK (TRUSTED span) only", rep["trusted_only"]),
        line("level-approx only (regime sound, LEVEL not placed)", rep["level_approx_only"]),
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
        "## TU-04 sign-model A/B (single names; registered test due 2026-08-03)",
        "",
        _sign_ab_line(rep["sign_ab_single_names"]),
        "",
        *_weighting_md(rep),
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
        # RC-130: the denominator's exclusion is stated, never silent — hold% only covers
        # walls on the working side at 10:00 ET; breached-at-observation rows are counted.
        f"_Excluded as breached at observation (wall on the wrong side of spot at 10:00 ET; "
        f"hold undefined): ALL rows — call {rep['wall_hold_all'].get('call_excluded_breached_at_obs', 0)}, "
        f"put {rep['wall_hold_all'].get('put_excluded_breached_at_obs', 0)}; TRUSTED — call "
        f"{rep['wall_hold_trusted'].get('call_excluded_breached_at_obs', 0)}, put "
        f"{rep['wall_hold_trusted'].get('put_excluded_breached_at_obs', 0)}._",
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
#: Roster-aware coverage bar. Operator 2026-07-21: the 17 panel_auto tickers STAY
#: excluded (confluence-only by design; their fix is a separate work item), so the
#: capturable ceiling is ~35 — a "expect ~50" bar would cry DEGRADED every healthy day
#: and teach the operator to ignore the loop. 33 = ceiling minus slack for per-symbol
#: fetch hiccups. Revisit WITH the roster decision, never independently of it.
COVERAGE_HEALTHY_MIN = 33


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
    """One line per ET day (rerun overwrites that day); returns full history.

    TU-13: each line also carries sentinel-slice OI-vs-VOLUME A/B
    (`ab_n` / `ab_hit_oi_pct` / `ab_hit_vol_pct`) so the parallel profile accrues
    daily — never a silent weighting swap.
    """
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
    ab = (rep.get("weighting_scorecard") or {}).get("sentinels") or {}
    hist.append({"day": day, "coverage": coverage,
                 "trusted_n": t["n"], "trusted_hit_pct": t["hit_pct"],
                 "placebo_n": rep["placebo_persistence"]["n"],
                 "placebo_hit_pct": rep["placebo_persistence"]["hit_pct"],
                 "ab_n": ab.get("n_both_classified"),
                 "ab_hit_oi_pct": ab.get("hit_oi_pct"),
                 "ab_hit_vol_pct": ab.get("hit_vol_pct")})
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
        f"({'healthy — at roster ceiling (17 confluence-only exclusions stand, operator 2026-07-21)' if coverage >= COVERAGE_HEALTHY_MIN else 'DEGRADED — below the ~35-ticker roster ceiling; the capture is the defect today'})",
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
    from tools.run_provenance import stamp_report
    rep = stamp_report(rep)
    OUT_JSON.write_text(json.dumps(rep, indent=2), encoding="utf-8")
    OUT_MD.write_text(md, encoding="utf-8")
    print(md)
    print("wrote", OUT_MD, "and", OUT_JSON, "and", HISTORY)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
