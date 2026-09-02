"""Causal intraday cumulative options-volume IC vs stickiness — Find & Prove / offline.

CORRECT THE RECORD (operator anger about "deliberate morning freeze"):
  The morning freeze exists to PREVENT lookahead false positives — not to inflate edge.
  EOD / late-day volume predicting same-day stickiness is circular: volume piles up where
  price already went. Freeze answers a different question: "can I act at 10:15 on the
  morning chain?" It does NOT manufacture false positives by limiting scope.

OPERATOR-VALID CRITIQUE (why this study exists):
  Live Chart yellow bars update through the day. Testing only the morning freeze does
  NOT test what the operator sees on Chart. This run uses successive option_chain
  snapshots at decision clocks T, with morning freeze as BASELINE comparator only.

Question (per clock T ∈ {10:15, 11:00, 12:00, 14:00} ET):
  Does as-of cumulative options volume from the latest snapshot ≤ T rank-predict
  subsequent stickiness better than (a) morning freeze, (b) within-day placebo,
  after ATM-distance control?

Causal rules:
  - Signal = latest option_chain snapshot at or before T (never future).
  - Targets from RTH bars STRICTLY AFTER T.
  - ATR for bands from bars before T only.
  - Morning freeze = morning_full prefer, else snap in 09:45–10:15 ET (baseline arm).
  - Skip day/clock if no snapshot within SNAP_TOL_MIN of T (honest thin density).

NO Chart/UI. NO Decide. NO push.

USAGE:
  python tools/liquidity_intraday_volume_ic_v1.py
  python tools/liquidity_intraday_volume_ic_v1.py --tickers SPY,QQQ,IWM
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

from app.domain.time_et import ET, RTH_START_MINS, is_trading_day_et  # noqa: E402

# ── Sibling IC helpers (ATM residual / Spearman) ─────────────────────────────
_IC_PATH = REPO / "tools" / "liquidity_strike_ic_v1.py"
_spec_ic = importlib.util.spec_from_file_location("liq_ic_v1", _IC_PATH)
assert _spec_ic and _spec_ic.loader
_ic = importlib.util.module_from_spec(_spec_ic)
_spec_ic.loader.exec_module(_ic)

_STICKY_PATH = REPO / "tools" / "liquidity_oi_volume_stickiness_v1.py"
_spec_st = importlib.util.spec_from_file_location("liq_sticky_v1", _STICKY_PATH)
assert _spec_st and _spec_st.loader
_sticky = importlib.util.module_from_spec(_spec_st)
_spec_st.loader.exec_module(_sticky)

_rows = _sticky._rows
_aggregate_strike_mass = _sticky._aggregate_strike_mass
_in_moneyness = _sticky._in_moneyness
_zscores = _sticky._zscores
_score_strike = _sticky._score_strike
MONEYNESS_PCT = _sticky.MONEYNESS_PCT
RTH_OPEN_MIN = _sticky.RTH_OPEN_MIN
RTH_CLOSE_MIN = _sticky.RTH_CLOSE_MIN
BAND_ATR_FRAC = _sticky.BAND_ATR_FRAC
PIERCE_ATR_MULT = _sticky.PIERCE_ATR_MULT
OBS_LO_MIN = _sticky.OBS_LO_MIN
OBS_HI_MIN = _sticky.OBS_HI_MIN

_spearman = _ic._spearman
_partial_spearman = _ic._partial_spearman
_signed_pull = _ic._signed_pull
_summarize_ics = _ic._summarize_ics
_bootstrap_mean = _ic._bootstrap_mean
_fmt = _ic._fmt
_pct = _ic._pct

STUDY = "liquidity_intraday_volume_ic_v1"
DB = REPO / "data" / "ed_console.db"
OUT_JSON = REPO / "reports" / f"{STUDY}.json"
OUT_MD = REPO / "reports" / f"{STUDY}.md"
SEED = 20260730

# Decision clocks (ET minutes from midnight)
CLOCKS: tuple[tuple[str, int], ...] = (
    ("10:15", int(RTH_START_MINS) + 45),
    ("11:00", 11 * 60),
    ("12:00", 12 * 60),
    ("14:00", 14 * 60),
)

SNAP_TOL_MIN = 30          # max lag: T − snap_min must be ≤ this
MIN_STRIKES = 8
MIN_POST_BARS = 30
MIN_PIN_MINUTES_LEFT = 60  # pin-to-close blanked if <60m of RTH remain after T
N_BOOT = 400
PASS = {
    "min_sessions": 80,
    "min_mean_ic": 0.05,
    "min_ic_ir": 0.30,
    "min_hit_rate": 0.55,
    "min_edge_vs_placebo": 0.04,
    "bootstrap_excludes_zero": True,
    # Live VOL must beat freeze on residual mean IC by this margin to claim "beats freeze"
    "min_edge_vs_freeze": 0.02,
}

# Arms: live-asof from snap ≤ T; FREEZE_* uses morning observation only
SIGNALS_LIVE = ("VOL", "OI", "PRODUCT")  # PRODUCT = OI × vol at that snap
SIGNALS_FREEZE = ("FREEZE_VOL", "FREEZE_OI", "FREEZE_PRODUCT")
SIGNALS_ALL = SIGNALS_LIVE + SIGNALS_FREEZE + ("DIST_INV",)

TARGETS = (
    "time_in_band",
    "failed_break_rate",
    "pin_closeness",
    "signed_pull",
    "composite",
)


def _et_day_and_min(ts: float) -> tuple[str, int]:
    d = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(ET)
    return d.strftime("%Y-%m-%d"), d.hour * 60 + d.minute


def _causal_atr_pre_T(sb: list[dict], t_min: int) -> float:
    """Median 1m range from RTH open through last bar BEFORE T — no post-T lookahead."""
    pre = [
        b for b in sb
        if RTH_OPEN_MIN <= b["min_of_day"] < t_min and b["high"] > b["low"]
    ]
    if len(pre) < 5:
        return 0.0
    return statistics.median(b["high"] - b["low"] for b in pre)


def _census_snapshots(con: sqlite3.Connection, tickers: list[str]) -> dict:
    """Exact density of option_chain snapshots through RTH (no JSON load)."""
    out: dict = {"by_ticker": {}, "clock_coverage": {}}
    for tk in tickers:
        by_hour: dict[int, int] = defaultdict(int)
        by_day_n: dict[str, int] = defaultdict(int)
        day_mins: dict[str, list[int]] = defaultdict(list)
        n = 0
        for (ts,) in con.execute(
            "SELECT ts_utc FROM snapshots WHERE ticker=? AND timeframe='1m' "
            "AND option_chain_json IS NOT NULL AND spot IS NOT NULL",
            (tk,),
        ):
            day, mins = _et_day_and_min(float(ts))
            if not is_trading_day_et(day):
                continue
            if not (RTH_OPEN_MIN <= mins < RTH_CLOSE_MIN):
                continue
            by_hour[mins // 60] += 1
            by_day_n[day] += 1
            day_mins[day].append(mins)
            n += 1
        vals = sorted(by_day_n.values())
        out["by_ticker"][tk] = {
            "n_rth_snaps_exact": n,
            "n_trading_days_exact": len(by_day_n),
            "snaps_per_day": {
                "min": vals[0] if vals else None,
                "median": statistics.median(vals) if vals else None,
                "max": vals[-1] if vals else None,
                "mean": round(statistics.fmean(vals), 2) if vals else None,
            },
            "by_et_hour": dict(sorted(by_hour.items())),
            "date_min": min(by_day_n) if by_day_n else None,
            "date_max": max(by_day_n) if by_day_n else None,
        }
        for label, T in CLOCKS:
            ok = 0
            lag_sums = []
            for day, mins_list in day_mins.items():
                cands = [m for m in mins_list if m <= T]
                if not cands:
                    continue
                lag = T - max(cands)
                if lag <= SNAP_TOL_MIN:
                    ok += 1
                    lag_sums.append(lag)
            out["clock_coverage"][f"{tk}|{label}"] = {
                "days_with_snap_le_T_within_tol": ok,
                "total_rth_chain_days": len(day_mins),
                "tol_min": SNAP_TOL_MIN,
                "mean_lag_min": (
                    round(statistics.fmean(lag_sums), 2) if lag_sums else None
                ),
            }
    return out


def _load_morning_freeze(
    con: sqlite3.Connection, tickers: list[str],
) -> dict[tuple[str, str], dict]:
    """Baseline morning observation: morning_full prefer, else 09:45–10:15 snap."""
    out: dict[tuple[str, str], dict] = {}
    for tk in tickers:
        for day, ts, spot, chain in con.execute(
            "SELECT et_date, ts_utc, spot, chain_json "
            "FROM option_chain_morning_full WHERE ticker=? ORDER BY et_date",
            (tk,),
        ):
            if not day or not is_trading_day_et(str(day)):
                continue
            out[(tk, str(day))] = {
                "faucet": "morning_full",
                "obs_min": None,
                "obs_ts_utc": float(ts) if ts is not None else None,
                "spot": float(spot),
                "chain_raw": chain,
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
            "obs_min": 600 - dist if dist <= 600 else None,
            "obs_ts_utc": ts,
            "spot": spot,
            "chain_raw": chain,
            "obs_dist_min": dist,
        }
    return out


def _load_snaps_at_or_before_T(
    con: sqlite3.Connection,
    tickers: list[str],
    t_min: int,
    tol: int = SNAP_TOL_MIN,
) -> dict[tuple[str, str], dict]:
    """Latest option_chain snapshot with mins ≤ T and lag ≤ tol, per (ticker, day).

    Two-pass: pick winning ts_utc without loading JSON, then fetch only winners.
    """
    # key -> (snap_min, ts_utc, lag)
    best_ts: dict[tuple[str, str], tuple[int, float, int]] = {}
    for tk in tickers:
        for (ts,) in con.execute(
            "SELECT ts_utc FROM snapshots "
            "WHERE ticker=? AND timeframe='1m' AND option_chain_json IS NOT NULL "
            "AND spot IS NOT NULL ORDER BY ts_utc",
            (tk,),
        ):
            day, mins = _et_day_and_min(float(ts))
            if not is_trading_day_et(day):
                continue
            if mins > t_min or mins < RTH_OPEN_MIN:
                continue
            lag = t_min - mins
            if lag > tol:
                continue
            key = (tk, day)
            if key not in best_ts or mins > best_ts[key][0]:
                best_ts[key] = (mins, float(ts), lag)

    out: dict[tuple[str, str], dict] = {}
    for (tk, day), (mins, ts, lag) in best_ts.items():
        row = con.execute(
            "SELECT spot, option_chain_json FROM snapshots "
            "WHERE ticker=? AND timeframe='1m' AND ts_utc=? "
            "AND option_chain_json IS NOT NULL LIMIT 1",
            (tk, ts),
        ).fetchone()
        if row is None or row[0] is None or row[1] is None:
            continue
        out[(tk, day)] = {
            "faucet": "snapshots_asof_T",
            "obs_min": mins,
            "obs_ts_utc": ts,
            "spot": float(row[0]),
            "chain_raw": row[1],
            "lag_min": lag,
        }
    return out


def _build_signal_rows(
    by_k: dict[float, dict],
    spot: float,
    *,
    freeze_by_k: dict[float, dict] | None = None,
) -> list[dict]:
    """Rows with live + freeze signals + DIST_INV in ±moneyness band."""
    band = [(sk, m) for sk, m in by_k.items() if _in_moneyness(sk, spot, MONEYNESS_PCT)]
    if len(band) < MIN_STRIKES:
        return []
    rows = []
    for sk, m in band:
        oi = float(m["oi"])
        vol = float(m["vol"])
        dist = abs(sk - spot)
        dist_inv = 1.0 / (dist + 0.01)
        fr = freeze_by_k.get(sk) if freeze_by_k else None
        f_oi = float(fr["oi"]) if fr else 0.0
        f_vol = float(fr["vol"]) if fr else 0.0
        rows.append({
            "strike": sk,
            "VOL": vol,
            "OI": oi,
            "PRODUCT": oi * vol,
            "FREEZE_VOL": f_vol,
            "FREEZE_OI": f_oi,
            "FREEZE_PRODUCT": f_oi * f_vol,
            "DIST_INV": dist_inv,
        })
    return rows


def _attach_targets(
    rows: list[dict],
    post: list[dict],
    atr: float,
    *,
    include_pin: bool,
) -> list[dict]:
    scored = []
    tibs, fbs, pins, pulls = [], [], [], []
    for r in rows:
        sc = _score_strike(post, r["strike"], atr)
        pull = _signed_pull(post, r["strike"])
        pin_close = None
        if include_pin and sc["pin_abs_dist"] is not None:
            pin_close = -float(sc["pin_abs_dist"])
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

    def _zmap(keys: list[float | None]) -> dict[int, float]:
        finite_idx = [i for i, v in enumerate(keys) if v is not None and math.isfinite(v)]
        if len(finite_idx) < 2:
            return {}
        sub = [float(keys[i]) for i in finite_idx]
        zs = _zscores(sub)
        return {finite_idx[j]: zs[j] for j in range(len(finite_idx))}

    zt = _zmap([r["time_in_band"] for r in scored])
    zf = _zmap([r["failed_break_rate"] for r in scored])
    zp = _zmap([r["pin_closeness"] for r in scored])
    zs = _zmap([r["signed_pull"] for r in scored])
    out = []
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


def _verdict(real: dict, placebo: dict, boot: dict) -> str:
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
    if mu > 0 and edge > 0 and hit > 0.5:
        return "WEAK_FAIL"
    return "FAIL"


def _pack_cell(
    sig: str,
    tgt: str,
    real_ics: list[float],
    plc_ics: list[float],
    boot_rnd: random.Random,
) -> dict:
    real_s = _summarize_ics(real_ics)
    plc_s = _summarize_ics(plc_ics)
    boot = _bootstrap_mean(real_ics, N_BOOT, boot_rnd)
    edge = None
    if real_s["mean_ic"] is not None and plc_s["mean_ic"] is not None:
        edge = real_s["mean_ic"] - plc_s["mean_ic"]
    return {
        "signal": sig,
        "target": tgt,
        "real": real_s,
        "placebo": plc_s,
        "edge_vs_placebo": edge,
        "bootstrap": boot,
        "verdict": _verdict(real_s, plc_s, boot),
    }


def _compare_live_vs_freeze(
    live_cell: dict, freeze_cell: dict,
) -> dict:
    """Does live residual mean IC beat freeze residual mean IC?"""
    lm = live_cell["real"]["mean_ic"]
    fm = freeze_cell["real"]["mean_ic"]
    if lm is None or fm is None:
        return {
            "live_mean_ic": lm,
            "freeze_mean_ic": fm,
            "delta_live_minus_freeze": None,
            "beats_freeze": None,
            "note": "blank_mean",
        }
    delta = lm - fm
    return {
        "live_mean_ic": lm,
        "freeze_mean_ic": fm,
        "delta_live_minus_freeze": delta,
        "beats_freeze": bool(delta >= PASS["min_edge_vs_freeze"]),
        "live_verdict": live_cell["verdict"],
        "freeze_verdict": freeze_cell["verdict"],
        "live_edge_vs_placebo": live_cell.get("edge_vs_placebo"),
        "freeze_edge_vs_placebo": freeze_cell.get("edge_vs_placebo"),
    }


def run(tickers: list[str]) -> dict:
    t0 = time.time()
    rnd = random.Random(SEED)
    boot_rnd = random.Random(SEED + 11)
    con = sqlite3.connect(str(DB))
    con.row_factory = sqlite3.Row

    census = _census_snapshots(con, tickers)
    freeze_obs = _load_morning_freeze(con, tickers)

    bars_by_tk = {tk: _rows(con, tk) for tk in tickers}
    bars_by_day: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for tk, brows in bars_by_tk.items():
        for b in brows:
            day = b["dt"].strftime("%Y-%m-%d")
            if is_trading_day_et(day) and RTH_OPEN_MIN <= b["min_of_day"] < RTH_CLOSE_MIN:
                bars_by_day[(tk, day)].append(b)

    mf_census = {}
    for tk in tickers:
        days = [
            str(r[0])
            for r in con.execute(
                "SELECT et_date FROM option_chain_morning_full WHERE ticker=?", (tk,),
            )
            if r[0] and is_trading_day_et(str(r[0]))
        ]
        mf_census[tk] = {
            "trading_days_exact": len(days),
            "min_et": min(days) if days else None,
            "max_et": max(days) if days else None,
        }

    # Preload snaps for each clock (one pass per clock — avoids keeping all JSONs)
    snaps_by_clock: dict[str, dict[tuple[str, str], dict]] = {}
    for label, T in CLOCKS:
        snaps_by_clock[label] = _load_snaps_at_or_before_T(con, tickers, T, SNAP_TOL_MIN)

    con.close()

    clock_results: dict[str, dict] = {}

    for label, T in CLOCKS:
        drops: dict[str, int] = defaultdict(int)
        blank_reasons: dict[str, int] = defaultdict(int)
        real_map: dict[tuple[str, str], list[float]] = defaultdict(list)
        plc_map: dict[tuple[str, str], list[float]] = defaultdict(list)
        resid_map: dict[tuple[str, str], list[float]] = defaultdict(list)
        resid_plc_map: dict[tuple[str, str], list[float]] = defaultdict(list)
        day_meta: list[dict] = []
        faucet_counts: dict[str, int] = defaultdict(int)
        lag_list: list[int] = []

        snaps = snaps_by_clock[label]
        minutes_left = RTH_CLOSE_MIN - T
        include_pin = minutes_left >= MIN_PIN_MINUTES_LEFT

        for (tk, day), meta in sorted(snaps.items()):
            sb = bars_by_day.get((tk, day), [])
            if len(sb) < 60:
                drops["short_session"] += 1
                continue
            atr = _causal_atr_pre_T(sb, T)
            if atr <= 0:
                drops["atr_zero"] += 1
                continue
            post = [b for b in sb if b["min_of_day"] > T]  # STRICTLY after T
            if len(post) < MIN_POST_BARS:
                drops["short_post_T"] += 1
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

            freeze_by_k = None
            fr = freeze_obs.get((tk, day))
            freeze_faucet = None
            if fr is not None:
                try:
                    f_contracts = json.loads(fr["chain_raw"])
                except (ValueError, TypeError):
                    f_contracts = None
                if isinstance(f_contracts, list) and f_contracts:
                    # Use freeze spot for freeze mass; band still vs live spot for fair cross-section
                    freeze_by_k = _aggregate_strike_mass(f_contracts, float(fr["spot"]))
                    freeze_faucet = fr.get("faucet")
                else:
                    drops["freeze_bad_json"] += 1
            else:
                drops["no_freeze_obs"] += 1

            sig_rows = _build_signal_rows(by_k, spot, freeze_by_k=freeze_by_k)
            if len(sig_rows) < MIN_STRIKES:
                drops["thin_band"] += 1
                continue
            # If no freeze, freeze signals are zero — still compute live; flag
            if freeze_by_k is None:
                drops["freeze_signals_zeroed"] += 1

            rows = _attach_targets(sig_rows, post, atr, include_pin=include_pin)
            faucet_counts[str(meta.get("faucet"))] += 1
            lag_list.append(int(meta.get("lag_min") or 0))

            for sig in SIGNALS_ALL:
                for tgt in TARGETS:
                    if tgt == "pin_closeness" and not include_pin:
                        blank_reasons[f"{sig}|{tgt}|pin_insufficient_day_left"] += 1
                        continue
                    real = _day_ic(rows, sig, tgt, rnd=None)
                    plc = _day_ic(rows, sig, tgt, rnd=rnd)
                    if real["blank"]:
                        blank_reasons[f"{sig}|{tgt}|{real.get('blank_reason')}"] += 1
                    else:
                        real_map[(sig, tgt)].append(float(real["ic"]))
                    if not plc["blank"]:
                        plc_map[(sig, tgt)].append(float(plc["ic"]))
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
                "obs_min": meta.get("obs_min"),
                "lag_min": meta.get("lag_min"),
                "freeze_faucet": freeze_faucet,
                "n_strikes_band": len(rows),
                "spot": spot,
                "atr_causal_pre_T": atr,
                "n_post_bars": len(post),
                "include_pin": include_pin,
            })

        # Pack cells
        cells_raw = []
        resid_cells = []
        for sig in SIGNALS_ALL:
            for tgt in TARGETS:
                cells_raw.append(
                    _pack_cell(sig, tgt, real_map[(sig, tgt)], plc_map[(sig, tgt)], boot_rnd)
                )
        for sig in SIGNALS_ALL:
            if sig == "DIST_INV":
                continue
            for tgt in TARGETS:
                cell = _pack_cell(
                    sig, tgt, resid_map[(sig, tgt)], resid_plc_map[(sig, tgt)], boot_rnd,
                )
                cell["control"] = "DIST_INV"
                cell["ic_type"] = "partial_spearman_vs_dist_inv"
                resid_cells.append(cell)

        # Live vs freeze comparisons (primary residual, key targets)
        comparisons = []
        for live_sig, freeze_sig in (
            ("VOL", "FREEZE_VOL"),
            ("OI", "FREEZE_OI"),
            ("PRODUCT", "FREEZE_PRODUCT"),
        ):
            for tgt in TARGETS:
                live_c = next(
                    (c for c in resid_cells if c["signal"] == live_sig and c["target"] == tgt),
                    None,
                )
                freeze_c = next(
                    (c for c in resid_cells if c["signal"] == freeze_sig and c["target"] == tgt),
                    None,
                )
                if live_c is None or freeze_c is None:
                    continue
                cmp = _compare_live_vs_freeze(live_c, freeze_c)
                cmp["live_signal"] = live_sig
                cmp["freeze_signal"] = freeze_sig
                cmp["target"] = tgt
                comparisons.append(cmp)

        # Clock-level verdict
        vol_comps = [c for c in comparisons if c["live_signal"] == "VOL"]
        vol_beats_freeze = [c for c in vol_comps if c.get("beats_freeze") is True]
        vol_beats_placebo = [
            c for c in resid_cells
            if c["signal"] == "VOL"
            and c["verdict"] in ("PASS", "WEAK_FAIL")
            and (c.get("edge_vs_placebo") or 0) > 0
        ]
        vol_pass = [c for c in resid_cells if c["signal"] == "VOL" and c["verdict"] == "PASS"]

        if len(day_meta) < PASS["min_sessions"]:
            clock_verdict = "UNDERPOWERED"
        elif vol_pass:
            # Live VOL residual PASS vs placebo AND beats freeze on ≥1 target
            if vol_beats_freeze:
                clock_verdict = "PASS_LIVE_BEATS_FREEZE"
            else:
                clock_verdict = "PASS_LIVE_NOT_ABOVE_FREEZE"
        elif vol_beats_freeze and vol_beats_placebo:
            clock_verdict = "WEAK_LIVE_ABOVE_FREEZE"
        elif any(c.get("beats_freeze") is False for c in vol_comps):
            # Check if freeze is better or both fail
            live_means = [c["live_mean_ic"] for c in vol_comps if c["live_mean_ic"] is not None]
            fr_means = [c["freeze_mean_ic"] for c in vol_comps if c["freeze_mean_ic"] is not None]
            if live_means and fr_means and statistics.fmean(live_means) <= statistics.fmean(fr_means):
                clock_verdict = "FAIL_LIVE_NOT_ABOVE_FREEZE"
            else:
                clock_verdict = "FAIL"
        else:
            clock_verdict = "FAIL"

        ranked_resid = sorted(
            [c for c in resid_cells if c["real"]["mean_ic"] is not None],
            key=lambda c: c["real"]["mean_ic"],
            reverse=True,
        )

        clock_results[label] = {
            "clock_et": label,
            "t_min": T,
            "minutes_rth_remaining": minutes_left,
            "include_pin": include_pin,
            "n_sessions_exact": len(day_meta),
            "sessions_by_ticker": {
                tk: sum(1 for d in day_meta if d["ticker"] == tk) for tk in tickers
            },
            "date_min": min((d["session"] for d in day_meta), default=None),
            "date_max": max((d["session"] for d in day_meta), default=None),
            "mean_lag_min": (
                round(statistics.fmean(lag_list), 2) if lag_list else None
            ),
            "median_lag_min": (
                statistics.median(lag_list) if lag_list else None
            ),
            "faucet_mix": dict(faucet_counts),
            "freeze_faucet_mix": {
                k: sum(1 for d in day_meta if d.get("freeze_faucet") == k)
                for k in ("morning_full", "snapshots_1000et")
            },
            "drops": dict(drops),
            "blank_reasons_top": dict(
                sorted(blank_reasons.items(), key=lambda x: -x[1])[:25]
            ),
            "mean_strikes_band": (
                statistics.fmean(d["n_strikes_band"] for d in day_meta) if day_meta else None
            ),
            "mean_post_bars": (
                statistics.fmean(d["n_post_bars"] for d in day_meta) if day_meta else None
            ),
            "resid_cells": resid_cells,
            "cells_raw": cells_raw,
            "live_vs_freeze": comparisons,
            "ranked_resid_top": [
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
                for c in ranked_resid[:12]
            ],
            "verdict_counts_resid": {
                "PASS": sum(1 for c in resid_cells if c["verdict"] == "PASS"),
                "WEAK_FAIL": sum(1 for c in resid_cells if c["verdict"] == "WEAK_FAIL"),
                "FAIL": sum(1 for c in resid_cells if c["verdict"] == "FAIL"),
                "UNDERPOWERED": sum(1 for c in resid_cells if c["verdict"] == "UNDERPOWERED"),
                "BLANK": sum(1 for c in resid_cells if c["verdict"] == "BLANK"),
            },
            "clock_verdict": clock_verdict,
            "day_meta_head": day_meta[:3],
        }

    # Overall: any clock where live VOL residual PASS and beats freeze?
    overall = "FAIL"
    verdicts = [clock_results[lab]["clock_verdict"] for lab, _ in CLOCKS]
    if any(v == "PASS_LIVE_BEATS_FREEZE" for v in verdicts):
        overall = "PASS_LIVE_BEATS_FREEZE"
    elif any(v == "PASS_LIVE_NOT_ABOVE_FREEZE" for v in verdicts):
        overall = "PASS_LIVE_NOT_ABOVE_FREEZE"
    elif any(v == "WEAK_LIVE_ABOVE_FREEZE" for v in verdicts):
        overall = "WEAK_LIVE_ABOVE_FREEZE"
    elif all(v == "UNDERPOWERED" for v in verdicts):
        overall = "UNDERPOWERED"
    elif any(v == "FAIL_LIVE_NOT_ABOVE_FREEZE" for v in verdicts):
        overall = "FAIL_LIVE_NOT_ABOVE_FREEZE"

    elapsed = time.time() - t0
    return {
        "study": STUDY,
        "seed": SEED,
        "tickers": tickers,
        "plain_english_record": {
            "why_freeze_exists": (
                "Morning freeze exists to PREVENT lookahead false positives. "
                "Using EOD / late-day cumulative options volume to predict same-day "
                "stickiness is circular — volume accumulates where price already went. "
                "Freeze does NOT inflate edge; it answers a different question: "
                "'can I act at 10:15 on the morning chain?'"
            ),
            "why_operator_critique_is_valid": (
                "Live Chart yellow bars update through the session. Testing only the "
                "morning freeze does not test what the operator sees on Chart. This "
                "study runs the Chart-relevant experiment: as-of cumulative volume from "
                "the latest causal snapshot at each decision clock T."
            ),
            "what_this_answers": (
                "At each T in {10:15, 11:00, 12:00, 14:00} ET: does live-updating "
                "volume beat morning freeze and beat within-day placebo after "
                "ATM-distance control?"
            ),
        },
        "ic_definition": {
            "type": "Spearman + partial Spearman controlling DIST_INV (primary)",
            "formula_primary": (
                "partial Spearman: rank(signal,target,DIST_INV); "
                "residualize ranks on DIST_INV; Pearson of residuals"
            ),
            "placebo": "within-day shuffle of signal values across strikes",
            "causal": (
                f"signal from latest option_chain snap with ET min ≤ T and lag ≤ "
                f"{SNAP_TOL_MIN}m; targets from bars with min_of_day > T; "
                "ATR from bars before T; FREEZE_* from morning_full / ~10:00 snap"
            ),
            "clocks_et": [c[0] for c in CLOCKS],
            "snap_tol_min": SNAP_TOL_MIN,
            "min_strikes": MIN_STRIKES,
            "moneyness_pct": MONEYNESS_PCT,
            "min_pin_minutes_left": MIN_PIN_MINUTES_LEFT,
            "primary_claim": "resid_cells per clock + live_vs_freeze",
        },
        "pass_gates": PASS,
        "signals": list(SIGNALS_ALL),
        "targets": list(TARGETS),
        "snapshot_census": census,
        "morning_full_census": mf_census,
        "n_freeze_obs_keys": len(freeze_obs),
        "clocks": clock_results,
        "overall_verdict": overall,
        "overall_verdict_basis": (
            "ATM-controlled partial Spearman for live VOL vs FREEZE_VOL and vs placebo, "
            "per decision clock"
        ),
        "elapsed_sec": round(elapsed, 2),
        "decision_path_effect": "WAIT — no Decide admission; IC research only",
        "reproduce": f"python tools/{STUDY}.py",
    }


def write_reports(result: dict) -> None:
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with OUT_JSON.open("w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)

    pe = result["plain_english_record"]
    lines = [
        f"# {STUDY}",
        "",
        "## Plain English (read first)",
        "",
        f"1. **Why freeze was used:** {pe['why_freeze_exists']}",
        "",
        f"2. **Why the Chart critique is right:** {pe['why_operator_critique_is_valid']}",
        "",
        "3. **What this run found:** see §Verdict summary below (numbers from same-turn run).",
        "",
        "**MISSION_CLASS:** Find & Prove — offline causal intraday volume IC",
        "**DECISION_PATH_EFFECT:** WAIT — no Decide admission; no Chart/UI change",
        f"**OVERALL VERDICT:** `{result['overall_verdict']}` "
        f"(basis: `{result.get('overall_verdict_basis')}`)",
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
        "| GAP | Morning-freeze IC tested; Chart-updating cumulative volume IC untested |",
        "| SMALLEST_COMPLETE_CHANGE | This tool + reports/*.md/*.json |",
        "| MINIMUM_SUFFICIENT_EVIDENCE | Per-clock residual IC vs placebo + vs freeze; exact n; density census |",
        "| DECISION_PATH_EFFECT | None — WAIT |",
        "| WHY_NOW | Operator: freeze is anti-cheat not false-positive machine; Chart needs updating-volume test |",
        "| TASK_ADMISSION | Admitted as Find & Prove research only |",
        "",
        "## 1) Method (locked)",
        "",
        f"- Clocks T (ET): `{[c[0] for c in CLOCKS]}`",
        f"- Snapshot tolerance: latest chain with ET minute ≤ T and lag ≤ **{SNAP_TOL_MIN}** minutes",
        "- Live signals: `VOL`, `OI`, `PRODUCT` (= OI×vol) from that as-of chain",
        "- Baseline: `FREEZE_VOL`, `FREEZE_OI`, `FREEZE_PRODUCT` from morning_full "
        "(prefer) or 09:45–10:15 snap — same freeze as prior studies",
        "- Targets on bars with `min_of_day > T` only "
        f"(pin-to-close blanked if <{MIN_PIN_MINUTES_LEFT}m RTH remain)",
        "- ATR for bands from bars before T only",
        "- Primary IC: partial Spearman controlling `DIST_INV` (ATM proximity)",
        "- Placebo: within-day shuffle of signal across strikes",
        f"- PASS gates: `{json.dumps(PASS)}`",
        "",
        "## 2) Snapshot density (exact, same-turn census)",
        "",
    ]
    for tk, c in result["snapshot_census"]["by_ticker"].items():
        lines.append(
            f"- **{tk}:** RTH chain snaps = **{c['n_rth_snaps_exact']}** across "
            f"**{c['n_trading_days_exact']}** trading days "
            f"(`{c['date_min']}` → `{c['date_max']}`); "
            f"snaps/day median={c['snaps_per_day']['median']}, "
            f"mean={c['snaps_per_day']['mean']}; "
            f"by ET hour={c['by_et_hour']}"
        )
    lines.append("")
    lines.append("Clock coverage (days with snap ≤ T within tol):")
    lines.append("")
    lines.append("| Ticker | Clock | Days covered | Total chain days | Mean lag (min) |")
    lines.append("|---|---|---:|---:|---:|")
    for key, cov in sorted(result["snapshot_census"]["clock_coverage"].items()):
        tk, clk = key.split("|", 1)
        lines.append(
            f"| {tk} | {clk} | {cov['days_with_snap_le_T_within_tol']} | "
            f"{cov['total_rth_chain_days']} | {cov['mean_lag_min']} |"
        )
    lines += [
        "",
        f"morning_full trading days: `{json.dumps(result['morning_full_census'])}`",
        f"Freeze observation keys loaded: **{result['n_freeze_obs_keys']}**",
        "",
        "## 3) Verdict summary (per clock)",
        "",
        "| Clock | n sessions | mean lag | Clock verdict |",
        "|---|---:|---:|---|",
    ]
    for label, _ in CLOCKS:
        cr = result["clocks"][label]
        lines.append(
            f"| {label} | {cr['n_sessions_exact']} | {cr['mean_lag_min']} | "
            f"`{cr['clock_verdict']}` |"
        )

    lines += [
        "",
        "## 4) Per-clock detail — PRIMARY residual IC + live vs freeze",
        "",
    ]

    for label, _ in CLOCKS:
        cr = result["clocks"][label]
        lines += [
            f"### Clock {label} ET — `{cr['clock_verdict']}`",
            "",
            f"- Sessions exact: **{cr['n_sessions_exact']}** "
            f"by ticker `{cr['sessions_by_ticker']}`",
            f"- Date range: `{cr['date_min']}` → `{cr['date_max']}`",
            f"- Mean / median snap lag: {cr['mean_lag_min']} / {cr['median_lag_min']} min",
            f"- Mean post-T bars: {_fmt(cr.get('mean_post_bars'), 1)}; "
            f"pin included: {cr['include_pin']} "
            f"(RTH minutes remaining={cr['minutes_rth_remaining']})",
            f"- Freeze faucet mix: `{cr['freeze_faucet_mix']}`",
            f"- Drops: `{cr['drops']}`",
            f"- Residual verdict counts: `{cr['verdict_counts_resid']}`",
            "",
            "#### Live vs freeze (ATM-controlled residual mean IC)",
            "",
            "| Live | Freeze | Target | live mean IC | freeze mean IC | Δ (live−freeze) | beats freeze? | live verdict | freeze verdict |",
            "|---|---|---|---:|---:|---:|---|---|---|",
        ]
        for c in cr["live_vs_freeze"]:
            lines.append(
                f"| {c['live_signal']} | {c['freeze_signal']} | {c['target']} | "
                f"{_fmt(c['live_mean_ic'])} | {_fmt(c['freeze_mean_ic'])} | "
                f"{_fmt(c['delta_live_minus_freeze'])} | {c['beats_freeze']} | "
                f"`{c.get('live_verdict')}` | `{c.get('freeze_verdict')}` |"
            )

        lines += [
            "",
            "#### Residual IC cells (control = DIST_INV)",
            "",
            "| Signal | Target | n | mean IC | IC IR | hit% | plc mean | edge | boot CI | Verdict |",
            "|---|---|---:|---:|---:|---:|---:|---:|---|---|",
        ]
        for c in cr["resid_cells"]:
            r, p, b = c["real"], c["placebo"], c["bootstrap"]
            ci = "—"
            if b.get("ci_lo") is not None:
                ci = f"[{_fmt(b['ci_lo'])}, {_fmt(b['ci_hi'])}]"
            lines.append(
                f"| {c['signal']} | {c['target']} | {r['n_days']} | {_fmt(r['mean_ic'])} | "
                f"{_fmt(r['ic_ir'], 3)} | {_pct(r['hit_rate'])} | {_fmt(p['mean_ic'])} | "
                f"{_fmt(c['edge_vs_placebo'])} | {ci} | `{c['verdict']}` |"
            )
        lines.append("")

    # Build plain-English findings paragraph with actual numbers
    findings_bits = []
    for label, _ in CLOCKS:
        cr = result["clocks"][label]
        vol_tib = next(
            (c for c in cr["live_vs_freeze"]
             if c["live_signal"] == "VOL" and c["target"] == "time_in_band"),
            None,
        )
        vol_cell = next(
            (c for c in cr["resid_cells"]
             if c["signal"] == "VOL" and c["target"] == "time_in_band"),
            None,
        )
        if vol_tib and vol_cell:
            findings_bits.append(
                f"At **{label}** (n={cr['n_sessions_exact']} sessions): live VOL residual "
                f"mean IC vs time_in_band = {_fmt(vol_tib['live_mean_ic'])} "
                f"(verdict `{vol_cell['verdict']}`, edge vs placebo "
                f"{_fmt(vol_cell.get('edge_vs_placebo'))}); "
                f"freeze VOL = {_fmt(vol_tib['freeze_mean_ic'])}; "
                f"Δ(live−freeze) = {_fmt(vol_tib['delta_live_minus_freeze'])}; "
                f"clock `{cr['clock_verdict']}`."
            )
        else:
            findings_bits.append(
                f"At **{label}** (n={cr['n_sessions_exact']}): insufficient cells; "
                f"clock `{cr['clock_verdict']}`."
            )

    # Patch section 3 findings into a dedicated block near top after we have numbers
    # Insert after "What this run found" placeholder — rewrite lines[index]
    for i, line in enumerate(lines):
        if line.startswith("3. **What this run found:**"):
            lines[i] = (
                "3. **What this run found:** "
                + " ".join(findings_bits)
                + f" Overall: `{result['overall_verdict']}`."
            )
            break

    lines += [
        "## 5) Fair-method / limits",
        "",
        "- Equal-width ±3% moneyness band (no wing SUM traps).",
        "- Cross-sectional IC within day; placebo = within-day shuffle.",
        "- Primary claim = partial Spearman vs DIST_INV (ATM control).",
        "- Snapshots skipped when lag > tol — thin clocks reported as UNDERPOWERED, not invented.",
        "- Freeze signals zeroed when morning obs missing for that day (counted in drops).",
        "- failed_break_rate sparse when pierces rare; pin blanked if <60m day left "
        "(not triggered at these clocks — all have ≥120m).",
        "- No costs; no Decide path; ranking IC ≠ tradeable edge.",
        "",
        f"Elapsed: {result['elapsed_sec']}s",
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

    # Compact stdout for parent
    summary_clocks = {}
    for label, _ in CLOCKS:
        cr = result["clocks"][label]
        vol_tib = next(
            (c for c in cr["live_vs_freeze"]
             if c["live_signal"] == "VOL" and c["target"] == "time_in_band"),
            None,
        )
        summary_clocks[label] = {
            "n": cr["n_sessions_exact"],
            "verdict": cr["clock_verdict"],
            "vol_tib_live_ic": vol_tib["live_mean_ic"] if vol_tib else None,
            "vol_tib_freeze_ic": vol_tib["freeze_mean_ic"] if vol_tib else None,
            "vol_tib_delta": vol_tib["delta_live_minus_freeze"] if vol_tib else None,
            "vol_tib_beats_freeze": vol_tib["beats_freeze"] if vol_tib else None,
        }
    print(json.dumps({
        "study": STUDY,
        "overall_verdict": result["overall_verdict"],
        "clocks": summary_clocks,
        "out_md": str(OUT_MD),
        "out_json": str(OUT_JSON),
        "elapsed_sec": result["elapsed_sec"],
        "decision_path_effect": result["decision_path_effect"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
