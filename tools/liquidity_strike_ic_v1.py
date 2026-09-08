"""Liquidity strike Information Coefficient (IC) experiment v1 — Find & Prove / offline.

Question: do morning strike signals (volume, OI, OI×vol, GEX$, turnover, …) rank-predict
subsequent stickiness / magnet outcomes across strikes *within* a session?

IC definition (this study):
  Cross-section each (ticker, session): among ±3% moneyness strikes,
    IC_day = Spearman(rank(signal_i), rank(target_i))
  Aggregate: mean IC, IC IR = mean/stdev, hit rate P(IC>0), bootstrap CI on mean IC.
  Placebo: shuffle signal ranks within day; IC should collapse toward 0.

Targets reuse stickiness defs from liquidity_oi_volume_stickiness_v1
(time-in-band, failed-break rate, pin closeness, signed pull toward strike).

Causal as-of:
  - Signals ONLY from option_chain_morning_full (prefer) or snapshots ~10:00 ET
  - Targets from RTH bars at/after 10:15 ET; band width from pre-10:15 causal ATR

NO Chart/UI. NO Decide. NO push.

USAGE:
  python tools/liquidity_strike_ic_v1.py
  python tools/liquidity_strike_ic_v1.py --tickers SPY,QQQ,IWM
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
    compute_exposures_by_strike,
    total_gex_dollars_at_strike,
)
from numeric_contract import float_finite_or_none  # noqa: E402
from time_et import is_trading_day_et  # noqa: E402

# ── Load sibling stickiness helpers without package import side-effects ──────
_STICKY_PATH = REPO / "tools" / "liquidity_oi_volume_stickiness_v1.py"
_spec = importlib.util.spec_from_file_location("liq_sticky_v1", _STICKY_PATH)
assert _spec and _spec.loader
_sticky = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_sticky)

_rows = _sticky._rows
_causal_atr_pre_obs = _sticky._causal_atr_pre_obs
_load_obs_chains = _sticky._load_obs_chains
_aggregate_strike_mass = _sticky._aggregate_strike_mass
_in_moneyness = _sticky._in_moneyness
_zscores = _sticky._zscores
_score_strike = _sticky._score_strike
_outcome_time_in_band = _sticky._outcome_time_in_band
_outcome_failed_breaks = _sticky._outcome_failed_breaks
_outcome_pin_close = _sticky._outcome_pin_close
MONEYNESS_PCT = _sticky.MONEYNESS_PCT
OUTCOME_START_MIN = _sticky.OUTCOME_START_MIN
RTH_OPEN_MIN = _sticky.RTH_OPEN_MIN
BAND_ATR_FRAC = _sticky.BAND_ATR_FRAC
PIERCE_ATR_MULT = _sticky.PIERCE_ATR_MULT

STUDY = "liquidity_strike_ic_v1"
DB = REPO / "data" / "ed_console.db"
OUT_JSON = REPO / "reports" / f"{STUDY}.json"
OUT_MD = REPO / "reports" / f"{STUDY}.md"
SEED = 20260730
MIN_STRIKES = 8          # Spearman needs enough cross-section
MIN_POST_BARS = 30
N_BOOT = 400             # bootstrap days for mean-IC CI (cheap)
N_PLACEBO_SHUFFLES = 1   # one shuffle per day (pooled); optional multi in bootstrap
PASS = {
    "min_sessions": 80,
    "min_mean_ic": 0.05,           # absolute Spearman
    "min_ic_ir": 0.30,             # mean/stdev across days
    "min_hit_rate": 0.55,          # P(IC>0)
    "min_edge_vs_placebo": 0.04,   # mean_ic - mean_placebo_ic
    "bootstrap_excludes_zero": True,
}

# Signal name -> higher means "more sticky candidate"
SIGNALS = (
    "VOL",
    "OI",
    "PRODUCT",           # OI × volume
    "Z_PRODUCT",         # z(OI) × z(vol) in band
    "TURNOVER",          # vol/OI (OI>0)
    "GEX_ABS",           # |dealer GEX$| at strike
    "DIST_INV",          # 1/(|K−S|+ε) — ATM proximity confounder baseline
)

# Target name -> higher = stickier / stronger magnet
TARGETS = (
    "time_in_band",
    "failed_break_rate",
    "pin_closeness",     # −|RTH close − K|
    "signed_pull",       # mean signed pull of close toward K (positive = magnet)
    "composite",         # equal-weight z of available stickiness targets
)


def _ranks(v: list[float]) -> list[float]:
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
    if n < MIN_STRIKES or n != len(b):
        return None
    ma, mb = sum(a) / n, sum(b) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b, strict=True))
    da = sum((x - ma) ** 2 for x in a) ** 0.5
    db = sum((y - mb) ** 2 for y in b) ** 0.5
    if da <= 0 or db <= 0:
        return None
    return num / (da * db)


def _spearman(a: list[float], b: list[float]) -> float | None:
    """Spearman rho via average ranks + Pearson. Pure Python."""
    if len(a) < MIN_STRIKES or len(a) != len(b):
        return None
    return _pearson(_ranks(a), _ranks(b))


def _residualize(y: list[float], x: list[float]) -> list[float] | None:
    """OLS residual of y on x (+intercept). Same length; None if singular."""
    n = len(y)
    if n != len(x) or n < MIN_STRIKES:
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
    """Spearman partial corr: rank all three, residualize a&b on control, Pearson."""
    n = len(a)
    if n < MIN_STRIKES or n != len(b) or n != len(control):
        return None
    ra, rb, rc = _ranks(a), _ranks(b), _ranks(control)
    a_res = _residualize(ra, rc)
    b_res = _residualize(rb, rc)
    if a_res is None or b_res is None:
        return None
    return _pearson(a_res, b_res)


def _signed_pull(post: list[dict], strike: float) -> float | None:
    """Mean signed pull of bar close toward strike: + when close moves closer.

    pull_t = |close_{t-1} − K| − |close_t − K|  (positive = closer)
    """
    if len(post) < 2:
        return None
    pulls = []
    for i in range(1, len(post)):
        d0 = abs(post[i - 1]["close"] - strike)
        d1 = abs(post[i]["close"] - strike)
        pulls.append(d0 - d1)
    return statistics.fmean(pulls) if pulls else None


def _gex_abs_by_strike(chain_raw: str, spot: float) -> dict[float, float]:
    try:
        contracts = json.loads(chain_raw)
    except (ValueError, TypeError):
        return {}
    if not contracts:
        return {}
    try:
        exposures, _ = compute_exposures_by_strike(contracts, spot=spot, require_oi=True)
    except Exception:
        return {}
    out: dict[float, float] = {}
    for k, bucket in exposures.items():
        sk = float_finite_or_none(k)
        if sk is None or not isinstance(bucket, dict):
            continue
        tg = total_gex_dollars_at_strike(bucket)
        if tg is not None and math.isfinite(tg):
            out[sk] = abs(float(tg))
    return out


def _build_signal_matrix(
    by_k: dict[float, dict],
    spot: float,
    gex_abs: dict[float, float],
) -> list[dict]:
    """One row per strike in moneyness band with all signal columns."""
    band = [(sk, m) for sk, m in by_k.items() if _in_moneyness(sk, spot, MONEYNESS_PCT)]
    if len(band) < MIN_STRIKES:
        return []
    ois = [m["oi"] for _, m in band]
    vols = [m["vol"] for _, m in band]
    zo = _zscores(ois)
    zv = _zscores(vols)
    rows = []
    for i, (sk, m) in enumerate(band):
        oi = float(m["oi"])
        vol = float(m["vol"])
        turnover = (vol / oi) if oi > 0 else 0.0
        dist = abs(sk - spot)
        dist_inv = 1.0 / (dist + 0.01)
        rows.append({
            "strike": sk,
            "VOL": vol,
            "OI": oi,
            "PRODUCT": oi * vol,
            "Z_PRODUCT": zo[i] * zv[i],
            "TURNOVER": turnover,
            "GEX_ABS": float(gex_abs.get(sk, 0.0)),
            "DIST_INV": dist_inv,
            "min_dte": m.get("min_dte"),
        })
    return rows


def _attach_targets(rows: list[dict], post: list[dict], atr: float) -> list[dict]:
    out = []
    tibs, fbs, pins, pulls = [], [], [], []
    scored = []
    for r in rows:
        sc = _score_strike(post, r["strike"], atr)
        pull = _signed_pull(post, r["strike"])
        pin_close = None if sc["pin_abs_dist"] is None else -float(sc["pin_abs_dist"])
        nr = {
            **r,
            "time_in_band": sc["time_in_band"],
            "failed_break_rate": sc["failed_break_rate"],
            "pin_closeness": pin_close,
            "signed_pull": pull,
            "n_pierce": sc["n_pierce"],
        }
        scored.append(nr)
        if sc["time_in_band"] is not None:
            tibs.append(sc["time_in_band"])
        if sc["failed_break_rate"] is not None:
            fbs.append(sc["failed_break_rate"])
        if pin_close is not None:
            pins.append(pin_close)
        if pull is not None:
            pulls.append(pull)

    # Composite = mean of available z-scored stickiness targets (equal weight)
    def _zmap(vals: list[float], keys: list[float | None]) -> dict[int, float]:
        finite_idx = [i for i, v in enumerate(keys) if v is not None and math.isfinite(v)]
        if len(finite_idx) < 2:
            return {}
        sub = [float(keys[i]) for i in finite_idx]
        zs = _zscores(sub)
        return {finite_idx[j]: zs[j] for j in range(len(finite_idx))}

    zt = _zmap(tibs, [r["time_in_band"] for r in scored])
    zf = _zmap(fbs, [r["failed_break_rate"] for r in scored])
    zp = _zmap(pins, [r["pin_closeness"] for r in scored])
    zs = _zmap(pulls, [r["signed_pull"] for r in scored])
    for i, r in enumerate(scored):
        parts = []
        if i in zt:
            parts.append(zt[i])
        if i in zf:
            parts.append(zf[i])
        if i in zp:
            parts.append(zp[i])
        if i in zs:
            parts.append(zs[i])
        r["composite"] = statistics.fmean(parts) if parts else None
        out.append(r)
    return out


def _day_ic(
    rows: list[dict],
    signal: str,
    target: str,
    rnd: random.Random | None = None,
    *,
    residualize_dist: bool = False,
) -> dict:
    """Compute Spearman IC; optional placebo shuffle; optional ATM partial IC.

    When residualize_dist=True: partial Spearman controlling for DIST_INV
    (ATM proximity confounder). DIST_INV vs itself is undefined → blank.
    """
    pairs = []
    for r in rows:
        s = r.get(signal)
        t = r.get(target)
        d = r.get("DIST_INV")
        if s is None or t is None or d is None:
            continue
        if not (
            math.isfinite(float(s))
            and math.isfinite(float(t))
            and math.isfinite(float(d))
        ):
            continue
        pairs.append((float(s), float(t), float(d)))
    n = len(pairs)
    blank = {
        "ic": None, "n_strikes": n, "blank": True,
        "blank_reason": "insufficient_pairs" if n < MIN_STRIKES else None,
    }
    if n < MIN_STRIKES:
        return blank
    if residualize_dist and signal == "DIST_INV":
        return {
            "ic": None, "n_strikes": n, "blank": True,
            "blank_reason": "control_is_signal",
        }
    sigs = [p[0] for p in pairs]
    tgts = [p[1] for p in pairs]
    dists = [p[2] for p in pairs]
    if statistics.pstdev(sigs) <= 1e-15 or statistics.pstdev(tgts) <= 1e-15:
        return {
            "ic": None, "n_strikes": n, "blank": True,
            "blank_reason": "zero_variance",
        }
    if rnd is not None:
        sigs = list(sigs)
        rnd.shuffle(sigs)
    if residualize_dist:
        if statistics.pstdev(dists) <= 1e-15:
            return {
                "ic": None, "n_strikes": n, "blank": True,
                "blank_reason": "zero_dist_variance",
            }
        ic = _partial_spearman(sigs, tgts, dists)
    else:
        ic = _spearman(sigs, tgts)
    return {
        "ic": ic,
        "n_strikes": n,
        "blank": ic is None,
        "blank_reason": "spearman_undefined" if ic is None else None,
    }


def _summarize_ics(day_ics: list[float]) -> dict:
    if not day_ics:
        return {
            "n_days": 0,
            "mean_ic": None,
            "stdev_ic": None,
            "ic_ir": None,
            "hit_rate": None,
            "median_ic": None,
        }
    mu = statistics.fmean(day_ics)
    sd = statistics.stdev(day_ics) if len(day_ics) >= 2 else 0.0
    ir = (mu / sd) if sd > 1e-12 else None
    hit = sum(1 for x in day_ics if x > 0) / len(day_ics)
    med = statistics.median(day_ics)
    return {
        "n_days": len(day_ics),
        "mean_ic": mu,
        "stdev_ic": sd,
        "ic_ir": ir,
        "hit_rate": hit,
        "median_ic": med,
    }


def _bootstrap_mean(day_ics: list[float], n_boot: int, rnd: random.Random) -> dict:
    if len(day_ics) < 5:
        return {"n_boot": 0, "ci_lo": None, "ci_hi": None, "excludes_zero": None}
    boots = []
    n = len(day_ics)
    for _ in range(n_boot):
        sample = [day_ics[rnd.randrange(n)] for _ in range(n)]
        boots.append(statistics.fmean(sample))
    boots.sort()
    lo = boots[int(0.025 * n_boot)]
    hi = boots[min(n_boot - 1, int(0.975 * n_boot))]
    return {
        "n_boot": n_boot,
        "ci_lo": lo,
        "ci_hi": hi,
        "excludes_zero": bool(lo > 0 or hi < 0),
        "mean_of_boots": statistics.fmean(boots),
    }


def _verdict(real: dict, placebo: dict, boot: dict) -> str:
    """PASS only if reliable IC > 0 AND clears placebo."""
    if real["n_days"] < PASS["min_sessions"]:
        return "UNDERPOWERED"
    mu = real["mean_ic"]
    ir = real["ic_ir"]
    hit = real["hit_rate"]
    pmu = placebo["mean_ic"]
    if mu is None or ir is None or hit is None or pmu is None:
        return "BLANK"
    edge = mu - pmu
    clears = (
        mu >= PASS["min_mean_ic"]
        and ir >= PASS["min_ic_ir"]
        and hit >= PASS["min_hit_rate"]
        and edge >= PASS["min_edge_vs_placebo"]
        and (not PASS["bootstrap_excludes_zero"] or boot.get("excludes_zero") is True)
        and boot.get("ci_lo") is not None
        and boot["ci_lo"] > 0
    )
    if clears:
        return "PASS"
    # Weak positive but fails gates
    if mu > 0 and edge > 0 and hit > 0.5:
        return "WEAK_FAIL"
    return "FAIL"


def _fmt(x: float | None, nd: int = 4) -> str:
    if x is None:
        return "—"
    return f"{x:.{nd}f}"


def _pct(x: float | None) -> str:
    if x is None:
        return "—"
    return f"{100 * x:.1f}%"


def run(tickers: list[str]) -> dict:
    t0 = time.time()
    rnd = random.Random(SEED)
    boot_rnd = random.Random(SEED + 7)
    con = sqlite3.connect(str(DB))
    con.row_factory = sqlite3.Row

    obs = _load_obs_chains(con, tickers)
    bars_by_tk = {tk: _rows(con, tk) for tk in tickers}
    bars_by_day: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for tk, rows in bars_by_tk.items():
        for b in rows:
            day = b["dt"].strftime("%Y-%m-%d")
            if is_trading_day_et(day) and RTH_OPEN_MIN <= b["min_of_day"] < _sticky.RTH_CLOSE_MIN:
                bars_by_day[(tk, day)].append(b)

    # morning_full census
    mf_census: dict[str, dict] = {}
    for tk in tickers:
        raw = con.execute(
            "SELECT COUNT(*), MIN(et_date), MAX(et_date) FROM option_chain_morning_full WHERE ticker=?",
            (tk,),
        ).fetchone()
        _td = con.execute(
            "SELECT COUNT(DISTINCT et_date) FROM option_chain_morning_full WHERE ticker=?",
            (tk,),
        ).fetchone()[0]
        # trading-day filter
        days = [
            r[0] for r in con.execute(
                "SELECT et_date FROM option_chain_morning_full WHERE ticker=?", (tk,),
            )
            if r[0] and is_trading_day_et(str(r[0]))
        ]
        mf_census[tk] = {
            "raw": int(raw[0] or 0),
            "trading_days": len(days),
            "min_et": raw[1],
            "max_et": raw[2],
        }

    con.close()

    drops: dict[str, int] = defaultdict(int)
    faucet_counts: dict[str, int] = defaultdict(int)
    # (signal, target) -> list of day IC
    real_map: dict[tuple[str, str], list[float]] = defaultdict(list)
    plc_map: dict[tuple[str, str], list[float]] = defaultdict(list)
    resid_map: dict[tuple[str, str], list[float]] = defaultdict(list)
    resid_plc_map: dict[tuple[str, str], list[float]] = defaultdict(list)
    day_meta: list[dict] = []
    blank_reasons: dict[str, int] = defaultdict(int)

    for (tk, day), meta in sorted(obs.items()):
        sb = bars_by_day.get((tk, day), [])
        if len(sb) < 60:
            drops["short_session"] += 1
            continue
        atr = _causal_atr_pre_obs(sb)
        if atr <= 0:
            drops["atr_zero"] += 1
            continue
        post = [b for b in sb if b["min_of_day"] >= OUTCOME_START_MIN]
        if len(post) < MIN_POST_BARS:
            drops["short_post_obs"] += 1
            continue
        spot = float(meta["spot"])
        try:
            contracts = json.loads(meta["chain_raw"])
        except (ValueError, TypeError):
            drops["bad_chain_json"] += 1
            continue
        if not isinstance(contracts, list) or not contracts:
            drops["empty_chain"] += 1
            continue
        by_k = _aggregate_strike_mass(contracts, spot)
        gex_abs = _gex_abs_by_strike(meta["chain_raw"], spot)
        sig_rows = _build_signal_matrix(by_k, spot, gex_abs)
        if len(sig_rows) < MIN_STRIKES:
            drops["thin_band"] += 1
            continue
        rows = _attach_targets(sig_rows, post, atr)
        faucet = str(meta.get("faucet") or "unknown")
        faucet_counts[faucet] += 1

        # Regime label if available (net GEX at spot)
        regime = None
        try:
            gex_pack = _sticky._gex_levels_from_chain(tk, spot, meta["chain_raw"])
            if gex_pack and "regime" in gex_pack:
                regime = gex_pack.get("regime")
        except Exception:
            regime = None

        day_ics_present = 0
        for sig in SIGNALS:
            for tgt in TARGETS:
                real = _day_ic(rows, sig, tgt, rnd=None)
                plc = _day_ic(rows, sig, tgt, rnd=rnd)
                if real["blank"]:
                    blank_reasons[f"{sig}|{tgt}|{real.get('blank_reason')}"] += 1
                else:
                    real_map[(sig, tgt)].append(float(real["ic"]))
                    day_ics_present += 1
                if not plc["blank"]:
                    plc_map[(sig, tgt)].append(float(plc["ic"]))
                # ATM-controlled partial Spearman (primary for liquidity claims)
                r_real = _day_ic(rows, sig, tgt, rnd=None, residualize_dist=True)
                r_plc = _day_ic(rows, sig, tgt, rnd=rnd, residualize_dist=True)
                if r_real["blank"]:
                    blank_reasons[f"RESID|{sig}|{tgt}|{r_real.get('blank_reason')}"] += 1
                else:
                    resid_map[(sig, tgt)].append(float(r_real["ic"]))
                if not r_plc["blank"]:
                    resid_plc_map[(sig, tgt)].append(float(r_plc["ic"]))

        day_meta.append({
            "ticker": tk,
            "session": day,
            "faucet": faucet,
            "regime": regime,
            "n_strikes_band": len(rows),
            "spot": spot,
            "atr_causal": atr,
            "n_post_bars": len(post),
            "n_ic_cells_nonblank": day_ics_present,
        })

    def _pack_cell(sig: str, tgt: str, real_ics: list[float], plc_ics: list[float]) -> dict:
        real_s = _summarize_ics(real_ics)
        plc_s = _summarize_ics(plc_ics)
        boot = _bootstrap_mean(real_ics, N_BOOT, boot_rnd)
        edge = None
        if real_s["mean_ic"] is not None and plc_s["mean_ic"] is not None:
            edge = real_s["mean_ic"] - plc_s["mean_ic"]
        halves = {"h1_mean": None, "h2_mean": None, "agree_sign": None}
        if len(real_ics) >= 20:
            mid = len(real_ics) // 2
            h1 = statistics.fmean(real_ics[:mid])
            h2 = statistics.fmean(real_ics[mid:])
            halves = {
                "h1_mean": h1,
                "h2_mean": h2,
                "agree_sign": bool(h1 * h2 > 0),
            }
        return {
            "signal": sig,
            "target": tgt,
            "real": real_s,
            "placebo": plc_s,
            "edge_vs_placebo": edge,
            "bootstrap": boot,
            "halves": halves,
            "verdict": _verdict(real_s, plc_s, boot),
        }

    # Raw IC cells (descriptive; ATM geometry inflates)
    cells = []
    for sig in SIGNALS:
        for tgt in TARGETS:
            cells.append(_pack_cell(sig, tgt, real_map[(sig, tgt)], plc_map[(sig, tgt)]))

    # Residual / partial IC controlling for DIST_INV (PRIMARY for liquidity claims)
    resid_cells = []
    for sig in SIGNALS:
        if sig == "DIST_INV":
            continue
        for tgt in TARGETS:
            cell = _pack_cell(sig, tgt, resid_map[(sig, tgt)], resid_plc_map[(sig, tgt)])
            cell["control"] = "DIST_INV"
            cell["ic_type"] = "partial_spearman_vs_dist_inv"
            resid_cells.append(cell)

    n_pass = sum(1 for c in cells if c["verdict"] == "PASS")
    n_weak = sum(1 for c in cells if c["verdict"] == "WEAK_FAIL")
    n_fail = sum(1 for c in cells if c["verdict"] == "FAIL")
    n_under = sum(1 for c in cells if c["verdict"] == "UNDERPOWERED")
    n_blank = sum(1 for c in cells if c["verdict"] == "BLANK")

    r_pass = sum(1 for c in resid_cells if c["verdict"] == "PASS")
    r_weak = sum(1 for c in resid_cells if c["verdict"] == "WEAK_FAIL")
    r_fail = sum(1 for c in resid_cells if c["verdict"] == "FAIL")
    r_under = sum(1 for c in resid_cells if c["verdict"] == "UNDERPOWERED")
    r_blank = sum(1 for c in resid_cells if c["verdict"] == "BLANK")

    ranked = sorted(
        [c for c in cells if c["real"]["mean_ic"] is not None],
        key=lambda c: c["real"]["mean_ic"],
        reverse=True,
    )
    ranked_resid = sorted(
        [c for c in resid_cells if c["real"]["mean_ic"] is not None],
        key=lambda c: c["real"]["mean_ic"],
        reverse=True,
    )

    # PRIMARY overall: residual IC (liquidity beyond ATM). DIST_INV raw PASS is geometry.
    overall = "FAIL"
    if r_pass > 0:
        overall = "PASS"
    elif r_weak > 0 and ranked_resid and (ranked_resid[0].get("edge_vs_placebo") or 0) > 0.02:
        overall = "WEAK_FAIL"
    elif r_under == len(resid_cells) and resid_cells:
        overall = "UNDERPOWERED"
    # Note if raw ATM geometry alone would have passed
    raw_geometry_note = (
        "Raw DIST_INV IC is strong (mechanical ATM↔pin geometry); "
        "liquidity signals judged on partial Spearman controlling for DIST_INV."
    )

    # By-ticker / by-regime slices for top cells (descriptive)
    # Recompute per-ticker IC means for reporting (top 3 by |mean|)
    _ticker_slice: dict[str, list] = {}
    # Rebuild day-level detail would be heavy; skip — report sample splits only

    elapsed = time.time() - t0
    result = {
        "study": STUDY,
        "seed": SEED,
        "tickers": tickers,
        "ic_definition": {
            "type": "Spearman rank IC + partial Spearman controlling DIST_INV",
            "formula_raw": "IC_day = corr(rank(signal), rank(target)) across ±3% moneyness strikes",
            "formula_primary": (
                "partial Spearman: rank(signal,target,DIST_INV); "
                "residualize ranks on DIST_INV; Pearson of residuals"
            ),
            "aggregate": "mean IC, IC IR = mean/stdev, hit rate P(IC>0), bootstrap 95% CI",
            "placebo": "shuffle signal values within day, recompute Spearman / partial Spearman",
            "causal": "signals from morning_full / ~10:00 snapshot; targets from RTH ≥10:15 ET",
            "min_strikes": MIN_STRIKES,
            "moneyness_pct": MONEYNESS_PCT,
            "band_atr_frac": BAND_ATR_FRAC,
            "pierce_atr_mult": PIERCE_ATR_MULT,
            "outcome_start_min_et": OUTCOME_START_MIN,
            "primary_claim": "resid_cells (ATM-controlled)",
        },
        "pass_gates": PASS,
        "signals": list(SIGNALS),
        "targets": list(TARGETS),
        "sample": {
            "n_obs_keys_loaded": len(obs),
            "n_day_records": len(day_meta),
            "n_sessions_exact": len(day_meta),
            "tickers_in_days": sorted({d["ticker"] for d in day_meta}),
            "sessions_by_ticker": {
                tk: sum(1 for d in day_meta if d["ticker"] == tk) for tk in tickers
            },
            "faucet_mix": dict(faucet_counts),
            "morning_full_census": mf_census,
            "drops": dict(drops),
            "blank_reasons_top": dict(
                sorted(blank_reasons.items(), key=lambda x: -x[1])[:20]
            ),
            "date_min": min((d["session"] for d in day_meta), default=None),
            "date_max": max((d["session"] for d in day_meta), default=None),
            "mean_strikes_band": (
                statistics.fmean(d["n_strikes_band"] for d in day_meta) if day_meta else None
            ),
        },
        "cells_raw": cells,
        "cells": cells,  # alias: raw Spearman (ATM-inflated; see resid_cells)
        "resid_cells": resid_cells,
        "ranked_by_mean_ic": [
            {
                "signal": c["signal"],
                "target": c["target"],
                "mean_ic": c["real"]["mean_ic"],
                "ic_ir": c["real"]["ic_ir"],
                "hit_rate": c["real"]["hit_rate"],
                "placebo_mean_ic": c["placebo"]["mean_ic"],
                "edge_vs_placebo": c["edge_vs_placebo"],
                "verdict": c["verdict"],
            }
            for c in ranked[:15]
        ],
        "ranked_resid_by_mean_ic": [
            {
                "signal": c["signal"],
                "target": c["target"],
                "mean_ic": c["real"]["mean_ic"],
                "ic_ir": c["real"]["ic_ir"],
                "hit_rate": c["real"]["hit_rate"],
                "placebo_mean_ic": c["placebo"]["mean_ic"],
                "edge_vs_placebo": c["edge_vs_placebo"],
                "verdict": c["verdict"],
            }
            for c in ranked_resid[:15]
        ],
        "verdict_counts_raw": {
            "PASS": n_pass,
            "WEAK_FAIL": n_weak,
            "FAIL": n_fail,
            "UNDERPOWERED": n_under,
            "BLANK": n_blank,
        },
        "verdict_counts": {
            "PASS": r_pass,
            "WEAK_FAIL": r_weak,
            "FAIL": r_fail,
            "UNDERPOWERED": r_under,
            "BLANK": r_blank,
        },
        "verdict_counts_resid": {
            "PASS": r_pass,
            "WEAK_FAIL": r_weak,
            "FAIL": r_fail,
            "UNDERPOWERED": r_under,
            "BLANK": r_blank,
        },
        "overall_verdict": overall,
        "overall_verdict_basis": "partial_spearman_controlling_DIST_INV",
        "raw_geometry_note": raw_geometry_note,
        "elapsed_sec": round(elapsed, 2),
        "decision_path_effect": "WAIT — no Decide admission; IC research only",
        "reproduce": f"python tools/{STUDY}.py",
    }
    # Keep day_meta light in JSON (count only; full list optional)
    result["sample"]["day_meta_head"] = day_meta[:5]
    result["sample"]["n_regimes"] = {
        "LONG_GAMMA": sum(1 for d in day_meta if d.get("regime") == "LONG_GAMMA"),
        "SHORT_GAMMA": sum(1 for d in day_meta if d.get("regime") == "SHORT_GAMMA"),
        "UNKNOWN": sum(1 for d in day_meta if not d.get("regime")),
    }
    return result


def write_reports(result: dict) -> None:
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    # Slim JSON: drop huge blanks noise already summarized
    with OUT_JSON.open("w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)

    s = result["sample"]
    lines = [
        f"# {STUDY}",
        "",
        "**MISSION_CLASS:** Find & Prove — offline Information Coefficient (Spearman) on strike signals vs stickiness",
        "**DECISION_PATH_EFFECT:** WAIT — no Decide admission; no Chart/UI change",
        "**COSTS:** ABSENT (ranking study, not a trade system)",
        f"**OVERALL VERDICT:** `{result['overall_verdict']}` "
        f"(basis: `{result.get('overall_verdict_basis')}`)",
        "",
        f"**NOTE:** {result.get('raw_geometry_note', '')}",
        "",
        "Reproduce:",
        "```",
        result["reproduce"],
        "```",
        "",
        "## AGENTS.md admission",
        "",
        "| Field | Answer |",
        "|---|---|",
        "| MISSION_CLASS | Find & Prove — research + offline IC |",
        "| GAP | Prior packs scored top-K touch/hold/stickiness; continuous cross-sectional rank IC untested |",
        "| SMALLEST_COMPLETE_CHANGE | This tool + reports/*.md/*.json |",
        "| MINIMUM_SUFFICIENT_EVIDENCE | Same-turn mean IC / IR / hit / bootstrap vs within-day signal shuffle; primary = ATM-partial IC |",
        "| DECISION_PATH_EFFECT | None — WAIT |",
        "| WHY_NOW | Operator: try Information Coefficient; brainstorm what else |",
        "| TASK_ADMISSION | Admitted as Find & Prove research only |",
        "",
        "## 1) IC definition (locked)",
        "",
        "For each session and each (signal, target) pair, take all option strikes within "
        f"**±{100*MONEYNESS_PCT:.0f}%** of morning spot. Compute",
        "",
        "```",
        "IC_day = Spearman( rank(signal_strike), rank(target_strike) )",
        "```",
        "",
        "**Primary (liquidity claim):** partial Spearman controlling for `DIST_INV` "
        "(ATM proximity). Rank-transform signal, target, and DIST_INV; residualize "
        "signal ranks and target ranks on DIST_INV ranks; Pearson of residuals. "
        "This blocks the lazy trap where volume/OI/GEX merely tag near-spot strikes "
        "that are mechanically closer to the close / in-band.",
        "",
        "Aggregate across sessions:",
        "",
        "- **mean IC** — average of day ICs",
        "- **IC IR** — mean / stdev (information ratio of the IC series)",
        "- **hit rate** — fraction of days with IC > 0",
        f"- **bootstrap** — {N_BOOT} day-resamples → 95% CI on mean IC",
        "",
        "**Placebo:** shuffle signal values across strikes *within* the same day, then "
        "recompute Spearman (or partial Spearman). A real ranking relationship should "
        "show mean IC ≫ placebo (~0).",
        "",
        "**Causal:** signals from `option_chain_morning_full` (prefer) or snapshots in "
        "09:45–10:15 ET; stickiness targets from RTH bars at/after 10:15 ET; ATR for bands "
        "from pre-10:15 bars only (same as `liquidity_oi_volume_stickiness_v1`).",
        "",
        "### Signals (higher = stronger candidate magnet)",
        "",
        "| Signal | Definition |",
        "|---|---|",
        "| VOL | Summed as-of options volume at strike |",
        "| OI | Summed open interest |",
        "| PRODUCT | OI × volume |",
        "| Z_PRODUCT | z(OI) × z(vol) within band |",
        "| TURNOVER | volume / OI (0 if OI=0) |",
        "| GEX_ABS | abs(dealer GEX$) at strike from morning chain |",
        "| DIST_INV | 1/(|K−S|+0.01) — ATM proximity confounder |",
        "",
        "### Targets (higher = stickier)",
        "",
        "| Target | Definition |",
        "|---|---|",
        "| time_in_band | Fraction of post-10:15 closes within 0.25×causalATR of K |",
        "| failed_break_rate | Reclaim rate after pierce ≥0.35×ATR (sparse; often blank) |",
        "| pin_closeness | negative abs(RTH close − K) |",
        "| signed_pull | Mean bar-to-bar reduction in abs(close−K) |",
        "| composite | Equal-weight z of available stickiness targets |",
        "",
        "### PASS gates (pre-registered)",
        "",
        "```",
        json.dumps(PASS, indent=2),
        "```",
        "",
        "## 2) Sample (exact)",
        "",
        f"- Tickers: `{result['tickers']}`",
        f"- Observation keys loaded: **{s['n_obs_keys_loaded']}**",
        f"- Sessions with IC computed: **{s['n_sessions_exact']}**",
        f"- Date range: `{s['date_min']}` → `{s['date_max']}`",
        f"- Sessions by ticker: `{s['sessions_by_ticker']}`",
        f"- Faucet mix: `{s['faucet_mix']}`",
        f"- morning_full census: `{json.dumps(s['morning_full_census'])}`",
        f"- Regime labels: `{s['n_regimes']}`",
        f"- Mean strikes in ±3% band: **{_fmt(s.get('mean_strikes_band'), 1)}**",
        f"- Drops: `{s['drops']}`",
        f"- Blank reasons (top): `{s['blank_reasons_top']}`",
        f"- Elapsed: {result['elapsed_sec']}s",
        "",
        "## 3) PRIMARY — partial Spearman IC (control = DIST_INV / ATM)",
        "",
        "Liquidity signals must clear placebo **after** removing ATM proximity. "
        "DIST_INV itself is excluded here (it is the control).",
        "",
        "| Signal | Target | n | mean IC | IC IR | hit% | plc mean | edge | boot CI | Verdict |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for c in result.get("resid_cells") or []:
        r, p, b = c["real"], c["placebo"], c["bootstrap"]
        ci = "—"
        if b.get("ci_lo") is not None:
            ci = f"[{_fmt(b['ci_lo'])}, {_fmt(b['ci_hi'])}]"
        lines.append(
            f"| {c['signal']} | {c['target']} | {r['n_days']} | {_fmt(r['mean_ic'])} | "
            f"{_fmt(r['ic_ir'], 3)} | {_pct(r['hit_rate'])} | {_fmt(p['mean_ic'])} | "
            f"{_fmt(c['edge_vs_placebo'])} | {ci} | `{c['verdict']}` |"
        )

    lines += [
        "",
        "### Ranked residual IC (top 15)",
        "",
        "| Rank | Signal | Target | mean IC | IR | hit% | edge vs plc | Verdict |",
        "|---:|---|---|---:|---:|---:|---:|---|",
    ]
    for i, c in enumerate(result.get("ranked_resid_by_mean_ic") or [], 1):
        lines.append(
            f"| {i} | {c['signal']} | {c['target']} | {_fmt(c['mean_ic'])} | "
            f"{_fmt(c['ic_ir'], 3)} | {_pct(c['hit_rate'])} | "
            f"{_fmt(c['edge_vs_placebo'])} | `{c['verdict']}` |"
        )

    lines += [
        "",
        "## 4) DESCRIPTIVE — raw Spearman IC (ATM-inflated)",
        "",
        "Includes DIST_INV. Strong raw IC here can be pure geometry "
        "(near-spot strikes sit closer to the close / in-band when spot does not travel far).",
        "",
        "| Signal | Target | n | mean IC | IC IR | hit% | plc mean | edge | boot CI | Verdict |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for c in result["cells"]:
        r, p, b = c["real"], c["placebo"], c["bootstrap"]
        ci = "—"
        if b.get("ci_lo") is not None:
            ci = f"[{_fmt(b['ci_lo'])}, {_fmt(b['ci_hi'])}]"
        lines.append(
            f"| {c['signal']} | {c['target']} | {r['n_days']} | {_fmt(r['mean_ic'])} | "
            f"{_fmt(r['ic_ir'], 3)} | {_pct(r['hit_rate'])} | {_fmt(p['mean_ic'])} | "
            f"{_fmt(c['edge_vs_placebo'])} | {ci} | `{c['verdict']}` |"
        )

    lines += [
        "",
        "### Ranked raw IC (top 15)",
        "",
        "| Rank | Signal | Target | mean IC | IR | hit% | edge vs plc | Verdict |",
        "|---:|---|---|---:|---:|---:|---:|---|",
    ]
    for i, c in enumerate(result["ranked_by_mean_ic"], 1):
        lines.append(
            f"| {i} | {c['signal']} | {c['target']} | {_fmt(c['mean_ic'])} | "
            f"{_fmt(c['ic_ir'], 3)} | {_pct(c['hit_rate'])} | "
            f"{_fmt(c['edge_vs_placebo'])} | `{c['verdict']}` |"
        )

    lines += [
        "",
        "## 5) Verdict",
        "",
        f"- Residual (primary) cell counts: `{result['verdict_counts']}`",
        f"- Raw (descriptive) cell counts: `{result.get('verdict_counts_raw')}`",
        f"- **Overall (ATM-controlled):** `{result['overall_verdict']}`",
        "",
        "Interpretation rule: a *liquidity* signal has reliable IC only if "
        "**partial** mean IC (control=DIST_INV) clears absolute gates **and** "
        "bootstrap CI excludes 0 **and** mean IC − placebo mean clears the edge gate. "
        "Raw DIST_INV PASS shows ATM geometry predicts pin/in-band — expected, not edge.",
        "",
        "## 6) Blanks / limits (fair-method)",
        "",
        "- Equal-width ±3% moneyness band for all strikes (no wide-wing SUM traps).",
        "- Cross-sectional IC within day — not pooling strikes across days (avoids day-effect).",
        "- Primary claim uses partial Spearman vs DIST_INV (blocks ATM mechanical inflation).",
        "- failed_break_rate can be noisy when pierces are sparse per strike.",
        "- morning_full coverage is thin vs snapshot faucet (exact census above).",
        "- Regime labels mostly UNKNOWN on snapshot faucet (GEX recon only on some days).",
        "- No costs; no Decide path; ranking IC ≠ tradeable edge.",
        "",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "",
    ]
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    global DB
    ap = argparse.ArgumentParser(description=STUDY)
    ap.add_argument("--tickers", default="SPY,QQQ,IWM")
    ap.add_argument("--db", default=str(DB))
    args = ap.parse_args()
    DB = Path(args.db)
    tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    result = run(tickers)
    write_reports(result)
    print(json.dumps({
        "study": STUDY,
        "overall_verdict": result["overall_verdict"],
        "overall_verdict_basis": result.get("overall_verdict_basis"),
        "n_sessions": result["sample"]["n_sessions_exact"],
        "verdict_counts_resid": result["verdict_counts"],
        "verdict_counts_raw": result.get("verdict_counts_raw"),
        "top3_resid": (result.get("ranked_resid_by_mean_ic") or [])[:3],
        "top3_raw": result["ranked_by_mean_ic"][:3],
        "out_md": str(OUT_MD),
        "out_json": str(OUT_JSON),
        "elapsed_sec": result["elapsed_sec"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
