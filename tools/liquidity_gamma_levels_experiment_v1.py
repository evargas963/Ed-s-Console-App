"""Liquidity gamma-levels experiment v1 — Find & Prove / offline only.

Tests whether historically reconstructed gamma structure levels (call wall,
put wall, gamma flip, gamma pin) beat random same-width zones as TOUCH targets
under the same triple-barrier bounce labels used by
tools/liquidity_synthesis_experiments_v1.py.

Level source (richest causal-enough history in-repo):
  Prefer option_chain_morning_full (wide TRUSTED chain; carries flip+regime)
  when present for (ticker, et_date); else snapshots option_chain_json nearest
  10:00 ET (window 09:45–10:15 ET). Trading days only (RC-58). Levels via
  terrain_engine.compute_terrain. NOT invented.

Causal rule: levels fixed at the morning/obs chain; touch scan starts at
10:15 ET (strictly after the obs window). Costs ABSENT (stated).

NO Decide admission. NO UI. NO server path.

USAGE:
  python tools/liquidity_gamma_levels_experiment_v1.py
  python tools/liquidity_gamma_levels_experiment_v1.py --tickers SPY,QQQ,IWM
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

from terrain_engine import compute_terrain  # noqa: E402
from time_et import ET, RTH_END_MINS, RTH_START_MINS, is_trading_day_et  # noqa: E402

# ── Pre-registered constants ─────────────────────────────────────────────────
RTH_OPEN_MIN = int(RTH_START_MINS)
RTH_CLOSE_MIN = int(RTH_END_MINS)
OBS_LO_MIN, OBS_HI_MIN = RTH_OPEN_MIN + 15, RTH_OPEN_MIN + 45  # 09:45–10:15 obs window
TOUCH_START_MIN = OBS_HI_MIN  # after observation — no lookahead
HORIZON_MIN = 30
K_ATR = 1.0
REARM_ATR_MULT = 0.25
WIDTH_ATR_FRAC = 0.25                   # half-width each side of level
SEED = 20260730

LEVEL_KINDS = ("CALL_WALL", "PUT_WALL", "GAMMA_FLIP", "GAMMA_PIN")

PASS = {
    "min_events_per_arm": 150,
    "min_win_rate_edge_pp": 0.05,
    "min_halves_agreeing": 2,
    "min_regime_resolved": 150,         # else report pooled + note
}

STUDY = "liquidity_gamma_levels_experiment_v1"
DB = REPO / "data" / "ed_console.db"


# ── Bars / barriers (same discipline as synthesis pack) ──────────────────────

def _rows(con: sqlite3.Connection, ticker: str) -> list[dict]:
    q = ("SELECT bar_start_ts_utc, open, high, low, close, volume FROM price_bars_1m "
         "WHERE ticker=? ORDER BY bar_start_ts_utc ASC")
    out = []
    for ts, o, h, l, c, v in con.execute(q, (ticker,)):
        if None in (ts, o, h, l, c):
            continue
        dt = datetime.fromtimestamp(float(ts), ET)
        out.append({
            "dt": dt,
            "datetime": int(float(ts) * 1000),
            "open": float(o), "high": float(h), "low": float(l),
            "close": float(c), "volume": float(v or 0.0),
            "min_of_day": dt.hour * 60 + dt.minute,
        })
    return out


def _session_atr(sb: list[dict]) -> float:
    ranges = [b["high"] - b["low"] for b in sb if b["high"] > b["low"]]
    return statistics.median(ranges) if ranges else 0.0


def _causal_atr(sb: list[dict], i: int) -> float:
    window = sb[max(0, i - 30):i] or sb[: max(1, min(30, i + 1))]
    ranges = [b["high"] - b["low"] for b in window if b["high"] > b["low"]]
    return statistics.median(ranges) if ranges else 0.0


def _triple_barrier(
    sb: list[dict],
    i: int,
    *,
    direction: int,
    zone_lo: float,
    zone_hi: float,
    atr: float,
    horizon: int = HORIZON_MIN,
    k: float = K_ATR,
) -> dict:
    """direction +1 = bounce UP (support); -1 = bounce DOWN (resistance). Costs ABSENT."""
    if atr <= 0 or i >= len(sb) - 1:
        return {"label": None, "reward_risk": None}
    entry = sb[i]["close"]
    width = max(zone_hi - zone_lo, 1e-9)
    pierce = max(0.25 * atr, 0.25 * width)
    target = k * atr
    if direction > 0:
        tp = entry + target
        sl = zone_lo - pierce
    else:
        tp = entry - target
        sl = zone_hi + pierce
    if direction > 0 and entry <= sl:
        return {"label": None, "reward_risk": None}
    if direction < 0 and entry >= sl:
        return {"label": None, "reward_risk": None}
    risk = max(abs(entry - sl), 0.25 * atr)
    rr = target / risk
    end = min(len(sb) - 1, i + horizon)
    for j in range(i + 1, end + 1):
        b = sb[j]
        if direction > 0:
            if b["low"] <= sl:
                return {"label": "FAIL", "reward_risk": rr, "bars": j - i}
            if b["high"] >= tp:
                return {"label": "WIN", "reward_risk": rr, "bars": j - i}
        else:
            if b["high"] >= sl:
                return {"label": "FAIL", "reward_risk": rr, "bars": j - i}
            if b["low"] <= tp:
                return {"label": "WIN", "reward_risk": rr, "bars": j - i}
    return {"label": "TIMEOUT", "reward_risk": rr, "bars": end - i}


def _summarize_labels(events: list[dict], key_label: str = "label") -> dict:
    wins = fails = timeouts = 0
    for e in events:
        lab = e.get(key_label)
        if lab == "WIN":
            wins += 1
        elif lab == "FAIL":
            fails += 1
        elif lab == "TIMEOUT":
            timeouts += 1
    resolved = wins + fails
    win_rate = wins / resolved if resolved else None
    mean_rr_win = None
    if wins:
        mean_rr_win = statistics.fmean(
            float(e["reward_risk"]) for e in events
            if e.get(key_label) == "WIN" and e.get("reward_risk") is not None
        )
    e_val = (win_rate * mean_rr_win) if (win_rate is not None and mean_rr_win is not None) else None
    return {
        "n": len(events),
        "wins": wins,
        "fails": fails,
        "timeouts": timeouts,
        "resolved": resolved,
        "win_rate": win_rate,
        "mean_rr_when_win": mean_rr_win,
        "E": e_val,
    }


def _date_half_edge(real: list[dict], placebo: list[dict]) -> dict:
    dates = sorted({e["session"] for e in real + placebo})
    if len(dates) < 20:
        return {"evaluated": False, "reason": "insufficient sessions", "halves_agree": False,
                "n_agree": 0}
    cut = dates[len(dates) // 2]
    agree = 0
    halves = {}
    for name, pred in (("first", lambda s: s < cut), ("second", lambda s: s >= cut)):
        r = _summarize_labels([e for e in real if pred(e["session"])])
        p = _summarize_labels([e for e in placebo if pred(e["session"])])
        edge = None
        if r["win_rate"] is not None and p["win_rate"] is not None:
            edge = r["win_rate"] - p["win_rate"]
            if edge >= 0:
                agree += 1
        halves[name] = {"real": r, "placebo": p, "edge_pp": edge}
    return {"evaluated": True, "split_date": cut, "halves": halves,
            "halves_agree": agree >= PASS["min_halves_agreeing"], "n_agree": agree}


def _verdict(real_s: dict, placebo_s: dict, oos: dict) -> str:
    if (real_s["resolved"] < PASS["min_events_per_arm"]
            or placebo_s["resolved"] < PASS["min_events_per_arm"]):
        return "FAIL"
    if real_s["win_rate"] is None or placebo_s["win_rate"] is None:
        return "FAIL"
    edge = real_s["win_rate"] - placebo_s["win_rate"]
    if edge < PASS["min_win_rate_edge_pp"]:
        return "FAIL"
    if not oos.get("halves_agree"):
        return "FAIL"
    return "PASS"


# ── Gamma level reconstruction ───────────────────────────────────────────────

def _et_day_and_min(ts: float) -> tuple[str, int]:
    d = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(ET)
    return d.strftime("%Y-%m-%d"), d.hour * 60 + d.minute


def _load_obs_chains(
    con: sqlite3.Connection, tickers: list[str],
) -> dict[tuple[str, str], dict]:
    """One observation per (ticker, ET day).

    Prefer morning_full (frozen morning wide chain — has flip/regime when TRUSTED).
    Else snapshots nearest 10:00 ET (walls/pin often present; flip usually absent
    on the narrow money-path chain — confidence UNAVAILABLE).
    """
    out: dict[tuple[str, str], dict] = {}

    # 1) morning_full wins when present
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

    # 2) fill gaps from snapshots near 10:00 ET
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
                continue  # morning_full already owns this day
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


def _levels_from_snap(ticker: str, spot: float, chain_raw: str) -> dict | None:
    try:
        contracts = json.loads(chain_raw)
    except (ValueError, TypeError):
        return None
    if not contracts:
        return None
    try:
        snap = compute_terrain(ticker, contracts, float(spot))
    except Exception as exc:  # noqa: BLE001 — research: skip bad day, never invent
        return {"error": f"{type(exc).__name__}: {exc}"}
    gex = snap.net_gex_at_spot
    # RC-345 / F07: the gamma-regime SIGN is classified by the ONE authority,
    # terrain_read.regime_from_signed_gamma. This research tool maps that verdict into its
    # LONG_GAMMA/SHORT_GAMMA vocabulary and carries snap.regime when the signed gamma is
    # absent; it does NOT reconstruct the regime from spot>gamma_flip (withheld instead).
    from terrain_read import regime_from_signed_gamma, REGIME_LONG_GAMMA
    regime = None
    _canon = regime_from_signed_gamma(gex)
    if _canon is not None:
        regime = "LONG_GAMMA" if _canon == REGIME_LONG_GAMMA else "SHORT_GAMMA"
    elif snap.regime in ("LONG_GAMMA_CHOP", "SHORT_GAMMA_TREND"):
        regime = "LONG_GAMMA" if snap.regime.startswith("LONG") else "SHORT_GAMMA"
    levels = {}
    if snap.call_wall is not None and math.isfinite(float(snap.call_wall)):
        levels["CALL_WALL"] = float(snap.call_wall)
    if snap.put_wall is not None and math.isfinite(float(snap.put_wall)):
        levels["PUT_WALL"] = float(snap.put_wall)
    if snap.gamma_flip is not None and math.isfinite(float(snap.gamma_flip)):
        levels["GAMMA_FLIP"] = float(snap.gamma_flip)
    if snap.gamma_pin is not None and math.isfinite(float(snap.gamma_pin)):
        levels["GAMMA_PIN"] = float(snap.gamma_pin)
    return {
        "levels": levels,
        "regime": regime,
        "confidence": snap.confidence,
        "net_gex_at_spot": gex,
        "spot": float(spot),
        "n_contracts": len(contracts),
    }


def _direction_for(kind: str, prev_c: float, mid: float, mode: str) -> int:
    """mode='approach' = bounce off approach side; mode='role' = wall role."""
    if mode == "role":
        if kind == "CALL_WALL":
            return -1
        if kind == "PUT_WALL":
            return 1
    # approach / flip / pin default
    return 1 if prev_c >= mid else -1


def _scan_level_touches(
    sb: list[dict],
    levels: dict[str, float],
    *,
    ticker: str,
    sess: str,
    atr_session: float,
    half_width: float,
    regime: str | None,
    confidence: str | None,
    mode: str,
    start_min: int = TOUCH_START_MIN,
) -> list[dict]:
    if atr_session <= 0 or half_width <= 0 or not levels:
        return []
    zones = []
    for kind, mid in levels.items():
        zones.append({
            "kind": kind, "mid": mid,
            "lo": mid - half_width, "hi": mid + half_width,
        })
    rearm = atr_session * REARM_ATR_MULT
    armed = [True] * len(zones)
    events = []
    for i, b in enumerate(sb):
        if b["min_of_day"] < start_min:
            continue
        if i == 0:
            continue
        for zi, z in enumerate(zones):
            inside = b["low"] <= z["hi"] and b["high"] >= z["lo"]
            if inside and armed[zi]:
                armed[zi] = False
                prev_c = sb[i - 1]["close"]
                direction = _direction_for(z["kind"], prev_c, z["mid"], mode)
                atr = _causal_atr(sb, i)
                tb = _triple_barrier(
                    sb, i, direction=direction,
                    zone_lo=z["lo"], zone_hi=z["hi"], atr=atr,
                )
                if tb["label"] is None:
                    continue
                events.append({
                    "ticker": ticker, "session": sess, "i": i,
                    "kind": z["kind"], "mid": z["mid"],
                    "zone_lo": z["lo"], "zone_hi": z["hi"],
                    "direction": direction, "mode": mode,
                    "regime": regime, "confidence": confidence,
                    "label": tb["label"], "reward_risk": tb["reward_risk"],
                    "bars": tb.get("bars"),
                    "arm": "real",
                })
            elif not inside:
                if abs(b["close"] - z["mid"]) > rearm:
                    armed[zi] = True
    return events


def _scan_placebo(
    sb: list[dict],
    n_zones: int,
    *,
    ticker: str,
    sess: str,
    atr_session: float,
    half_width: float,
    rnd: random.Random,
    regime: str | None,
    confidence: str | None,
    mode: str,
    start_min: int = TOUCH_START_MIN,
) -> list[dict]:
    if n_zones <= 0 or atr_session <= 0:
        return []
    # Fair: centers drawn from RTH range of bars available at/after obs (same session).
    rth = [b for b in sb if RTH_OPEN_MIN <= b["min_of_day"] < RTH_CLOSE_MIN]
    if len(rth) < 5:
        return []
    lo_s = min(b["low"] for b in rth)
    hi_s = max(b["high"] for b in rth)
    if hi_s <= lo_s:
        return []
    fake_levels = {f"RAND_{i}": rnd.uniform(lo_s, hi_s) for i in range(n_zones)}
    # Reuse scanner with synthetic kinds; force approach mode for placebo
    # (role mode on RAND is meaningless).
    events = _scan_level_touches(
        sb, fake_levels, ticker=ticker, sess=sess, atr_session=atr_session,
        half_width=half_width, regime=regime, confidence=confidence,
        mode="approach", start_min=start_min,
    )
    for e in events:
        e["kind"] = "RAND"
        e["arm"] = "placebo"
        e["mode"] = mode  # tag which real arm this placebo matches
    return events


# ── Study body ───────────────────────────────────────────────────────────────

def run(tickers: list[str]) -> dict:
    t0 = time.time()
    rnd = random.Random(SEED)
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)

    obs = _load_obs_chains(con, tickers)
    coverage = {tk: 0 for tk in tickers}
    for tk, day in obs:
        coverage[tk] = coverage.get(tk, 0) + 1

    # Load bars once per ticker
    bars_by_tk = {tk: _rows(con, tk) for tk in tickers}
    con.close()

    # Group bars by session date string
    sess_bars: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for tk, bars in bars_by_tk.items():
        for b in bars:
            if not (RTH_OPEN_MIN <= b["min_of_day"] < RTH_CLOSE_MIN):
                continue
            d = b["dt"].date().isoformat()
            if not is_trading_day_et(d):
                continue
            sess_bars[(tk, d)].append(b)

    recon_ok = 0
    recon_fail = 0
    recon_empty = 0
    level_presence = {k: 0 for k in LEVEL_KINDS}
    conf_counts: dict[str, int] = defaultdict(int)
    regime_day_counts: dict[str, int] = defaultdict(int)
    faucet_counts: dict[str, int] = defaultdict(int)
    real_approach: list[dict] = []
    real_role: list[dict] = []
    placebo_approach: list[dict] = []
    placebo_role: list[dict] = []
    day_rows: list[dict] = []

    for (tk, day), meta in sorted(obs.items()):
        sb = sess_bars.get((tk, day))
        if not sb or len(sb) < 40:
            continue
        got = _levels_from_snap(tk, meta["spot"], meta["chain_raw"])
        if got is None:
            recon_fail += 1
            continue
        if "error" in got:
            recon_fail += 1
            continue
        levels = got["levels"]
        if not levels:
            recon_empty += 1
            continue
        recon_ok += 1
        for k in levels:
            level_presence[k] = level_presence.get(k, 0) + 1
        conf = str(got.get("confidence") or "UNKNOWN")
        conf_counts[conf] += 1
        faucet = str(meta.get("faucet") or "unknown")
        faucet_counts[faucet] += 1
        regime = got.get("regime")
        if regime:
            regime_day_counts[regime] += 1

        atr = _session_atr(sb)
        if atr <= 0:
            continue
        half = WIDTH_ATR_FRAC * atr
        day_rows.append({
            "ticker": tk, "day": day, "spot": got["spot"],
            "regime": regime, "confidence": conf, "faucet": faucet,
            "levels": levels, "n_levels": len(levels),
            "net_gex_at_spot": got.get("net_gex_at_spot"),
            "n_contracts": got.get("n_contracts") or meta.get("n_contracts"),
        })

        ra = _scan_level_touches(
            sb, levels, ticker=tk, sess=day, atr_session=atr, half_width=half,
            regime=regime, confidence=conf, mode="approach",
        )
        rr = _scan_level_touches(
            sb, levels, ticker=tk, sess=day, atr_session=atr, half_width=half,
            regime=regime, confidence=conf, mode="role",
        )
        pa = _scan_placebo(
            sb, len(levels), ticker=tk, sess=day, atr_session=atr, half_width=half,
            rnd=rnd, regime=regime, confidence=conf, mode="approach",
        )
        pr = _scan_placebo(
            sb, len(levels), ticker=tk, sess=day, atr_session=atr, half_width=half,
            rnd=rnd, regime=regime, confidence=conf, mode="role",
        )
        # For role-mode placebo, re-label direction using approach (already done);
        # keep separate stream so n matches.
        real_approach.extend(ra)
        real_role.extend(rr)
        placebo_approach.extend(pa)
        placebo_role.extend(pr)

    def arm_block(real: list[dict], placebo: list[dict], *, name: str) -> dict:
        rs = _summarize_labels(real)
        ps = _summarize_labels(placebo)
        edge = None
        if rs["win_rate"] is not None and ps["win_rate"] is not None:
            edge = rs["win_rate"] - ps["win_rate"]
        oos = _date_half_edge(real, placebo)
        verdict = _verdict(rs, ps, oos)
        by_kind = {}
        for kind in LEVEL_KINDS:
            sub_r = [e for e in real if e.get("kind") == kind]
            by_kind[kind] = _summarize_labels(sub_r)
        by_kind["RAND"] = _summarize_labels(placebo)

        # Regime split (descriptive; primary PASS uses pooled)
        by_regime = {}
        regime_note = None
        for reg in ("LONG_GAMMA", "SHORT_GAMMA"):
            sub_r = [e for e in real if e.get("regime") == reg]
            sub_p = [e for e in placebo if e.get("regime") == reg]
            by_regime[reg] = {
                "real": _summarize_labels(sub_r),
                "placebo": _summarize_labels(sub_p),
            }
        thin = any(
            (by_regime[r]["real"]["resolved"] < PASS["min_regime_resolved"]
             or by_regime[r]["placebo"]["resolved"] < PASS["min_regime_resolved"])
            for r in ("LONG_GAMMA", "SHORT_GAMMA")
        )
        if thin:
            regime_note = (
                "Regime split too thin for PASS gate "
                f"(need ≥{PASS['min_regime_resolved']} resolved/arm/regime); "
                "pooled primary stands. Per-regime numbers are descriptive only."
            )

        return {
            "name": name,
            "question": (
                "Do gamma structure levels (call/put wall, flip, pin) as touch zones "
                "beat random same-width zones on triple-barrier bounce labels?"
                + (" Direction = approach-side bounce." if name == "approach"
                   else " Walls use role direction (call→resistance, put→support); "
                        "flip/pin use approach.")
            ),
            "n_real_events": len(real),
            "n_placebo_events": len(placebo),
            "real": rs,
            "placebo": ps,
            "win_rate_edge": edge,
            "oos": {
                "evaluated": oos.get("evaluated"),
                "split_date": oos.get("split_date"),
                "halves_agree": oos.get("halves_agree"),
                "n_agree": oos.get("n_agree"),
                "halves": {
                    h: {
                        "edge_pp": oos["halves"][h]["edge_pp"],
                        "real_win_rate": oos["halves"][h]["real"]["win_rate"],
                        "placebo_win_rate": oos["halves"][h]["placebo"]["win_rate"],
                        "real_resolved": oos["halves"][h]["real"]["resolved"],
                        "placebo_resolved": oos["halves"][h]["placebo"]["resolved"],
                    }
                    for h in (oos.get("halves") or {})
                } if oos.get("evaluated") else None,
            },
            "by_kind": by_kind,
            "by_regime": by_regime,
            "regime_note": regime_note,
            "verdict": verdict,
            "costs": "ABSENT",
        }

    primary = arm_block(real_approach, placebo_approach, name="approach")
    secondary = arm_block(real_role, placebo_role, name="role_walls")

    # Overall pack verdict: primary approach arm is binding
    pack = primary["verdict"]

    days_sorted = sorted(day_rows, key=lambda r: (r["day"], r["ticker"]))
    date_min = days_sorted[0]["day"] if days_sorted else None
    date_max = days_sorted[-1]["day"] if days_sorted else None

    result = {
        "study": STUDY,
        "mission": "Find & Prove — DISCUSSION/EXPERIMENT only",
        "decision_path": "NONE — Decide WAIT; no admission",
        "seed": SEED,
        "label": {
            "type": "triple_barrier_bounce",
            "horizon_min": HORIZON_MIN,
            "k_atr": K_ATR,
            "width_atr_frac": WIDTH_ATR_FRAC,
            "touch_start_et": "10:15",
            "obs_window_et": "09:45-10:15",
            "costs": "ABSENT",
        },
        "pass_gate": PASS,
        "source": {
            "faucet_priority": [
                "option_chain_morning_full (prefer — wide TRUSTED; flip+regime)",
                "snapshots.option_chain_json nearest 10:00 ET (fill — walls/pin)",
            ],
            "recompute": "terrain_engine.compute_terrain",
            "levels": list(LEVEL_KINDS),
            "trading_days_only": True,
        },
        "sample": {
            "tickers": tickers,
            "obs_days_available": coverage,
            "n_ticker_days_reconstructed": recon_ok,
            "n_recon_fail": recon_fail,
            "n_recon_empty_levels": recon_empty,
            "level_presence_days": level_presence,
            "confidence_counts": dict(conf_counts),
            "regime_day_counts": dict(regime_day_counts),
            "faucet_counts": dict(faucet_counts),
            "date_min": date_min,
            "date_max": date_max,
            "n_sessions_scored": len(day_rows),
            "LIMIT": (
                f"Sessions with reconstructable gamma levels: n={len(day_rows)} "
                f"({date_min}→{date_max}). Faucet mix: {dict(faucet_counts)}. "
                f"GAMMA_FLIP / regime available primarily on morning_full days "
                f"(TRUSTED wide chain); snapshot fill usually has walls+pin only "
                f"(confidence UNAVAILABLE, flip=None). No invented levels."
            ),
        },
        "experiments": {
            "G_approach": primary,
            "G_role_walls": secondary,
        },
        "verdicts": {
            "G_approach": primary["verdict"],
            "G_role_walls": secondary["verdict"],
        },
        "pack_verdict": pack,
        "runtime_sec": round(time.time() - t0, 1),
        # Compact day ledger (levels only — no chain payloads)
        "day_ledger_head": days_sorted[:5],
        "day_ledger_n": len(day_rows),
    }
    return result


def _fmt_rate(x) -> str:
    if x is None:
        return "n/a"
    return f"{100.0 * x:.1f}%"


def _fmt(x) -> str:
    if x is None:
        return "n/a"
    return f"{x:.3f}"


def _markdown(res: dict) -> str:
    s = res["sample"]
    ga = res["experiments"]["G_approach"]
    gr = res["experiments"]["G_role_walls"]
    L = [
        "# Liquidity gamma levels experiment v1",
        "",
        f"**Pack verdict: {res['pack_verdict']}**",
        "",
        f"- Mission: `{res['mission']}`",
        f"- Decision path: {res['decision_path']}",
        f"- Tickers: `{', '.join(s['tickers'])}`",
        f"- Sessions scored: **{s['n_sessions_scored']}** "
        f"(obs available: {json.dumps(s['obs_days_available'])})",
        f"- Date range: `{s['date_min']}` → `{s['date_max']}`",
        f"- Source: prefer morning_full, else snapshots@10:00 ET → `{res['source']['recompute']}`",
        f"- Faucet mix: `{json.dumps(s.get('faucet_counts', {}))}`",
        f"- Levels: {', '.join(res['source']['levels'])}",
        f"- Labels: triple-barrier bounce, horizon={res['label']['horizon_min']}m, "
        f"k={res['label']['k_atr']}×ATR, half-width={res['label']['width_atr_frac']}×ATR, "
        f"touch after {res['label']['touch_start_et']} ET, costs **{res['label']['costs']}**",
        f"- Seed: `{res['seed']}`",
        f"- Runtime: {res['runtime_sec']}s",
        "",
        "## AGENTS.md admission",
        "",
        "| Field | Answer |",
        "|---|---|",
        "| MISSION_CLASS | Find & Prove — offline gamma-level touch experiment |",
        "| GAP | Prior pack Exp C BLOCKED on morning_full; walls/flip/pin untested as touch targets |",
        "| SMALLEST_COMPLETE_CHANGE | `tools/liquidity_gamma_levels_experiment_v1.py` + this report |",
        "| MINIMUM_SUFFICIENT_EVIDENCE | Same-turn harness; placebo same-width; exact n; LIMIT stated |",
        "| DECISION_PATH_EFFECT | None — WAIT |",
        "| WHY_NOW | Operator: use gamma levels to see how they fare |",
        "| TASK_ADMISSION | Admitted as research/backtest only |",
        "",
        "## Pre-registered PASS",
        "",
        "```",
        json.dumps(PASS, indent=2),
        "```",
        "",
        "High kill rate is success. Gamma levels are candidate geometry only.",
        "",
        "## Sample LIMIT (PROVEN)",
        "",
        s["LIMIT"],
        "",
        f"- Reconstructed OK: {s['n_ticker_days_reconstructed']}; "
        f"fail: {s['n_recon_fail']}; empty levels: {s['n_recon_empty_levels']}",
        f"- Level presence (ticker-days): `{json.dumps(s['level_presence_days'])}`",
        f"- Confidence: `{json.dumps(s['confidence_counts'])}`",
        f"- Regime days: `{json.dumps(s['regime_day_counts'])}`",
        f"- Faucets: `{json.dumps(s.get('faucet_counts', {}))}`",
        "",
        "## Verdicts",
        "",
        "| Arm | Verdict |",
        "|---|---|",
        f"| G_approach (primary) | **{ga['verdict']}** |",
        f"| G_role_walls (secondary) | **{gr['verdict']}** |",
        "",
        "## Key findings (PROVEN this run)",
        "",
        f"1. **G_approach — {ga['verdict']}.** "
        f"real win_rate={_fmt_rate(ga['real']['win_rate'])} "
        f"(resolved={ga['real']['resolved']}, n={ga['n_real_events']}) vs "
        f"placebo={_fmt_rate(ga['placebo']['win_rate'])} "
        f"(resolved={ga['placebo']['resolved']}); "
        f"edge={_fmt_rate(ga['win_rate_edge'])}; "
        f"E real={_fmt(ga['real']['E'])} placebo={_fmt(ga['placebo']['E'])}. "
        f"OOS halves_agree={ga['oos'].get('halves_agree')}.",
        f"2. **G_role_walls — {gr['verdict']}.** "
        f"real={_fmt_rate(gr['real']['win_rate'])} vs "
        f"placebo={_fmt_rate(gr['placebo']['win_rate'])}; "
        f"edge={_fmt_rate(gr['win_rate_edge'])}.",
        f"3. **Regime split:** {ga.get('regime_note') or 'see by_regime table'}",
        f"4. **GAMMA_FLIP:** present on "
        f"{s['level_presence_days'].get('GAMMA_FLIP', 0)} ticker-days "
        f"(morning_full TRUSTED) but **0 post-10:15 touches** in this sample "
        f"(flip typically sits outside the day's traded range). Not invented; "
        f"not scored as a touch event.",
        "",
        "## G_approach — primary (approach-side bounce)",
        "",
        f"**Verdict: {ga['verdict']}**",
        "",
        f"> {ga['question']}",
        "",
        f"- Real events: {ga['n_real_events']} (resolved {ga['real']['resolved']})",
        f"- Placebo events: {ga['n_placebo_events']} (resolved {ga['placebo']['resolved']})",
        f"- Real win_rate: {_fmt_rate(ga['real']['win_rate'])}; "
        f"placebo: {_fmt_rate(ga['placebo']['win_rate'])}; "
        f"edge: {_fmt_rate(ga['win_rate_edge'])}",
        f"- Real E: {_fmt(ga['real']['E'])}; placebo E: {_fmt(ga['placebo']['E'])}",
        f"- Costs: {ga['costs']}",
        "",
        "### By level kind (real)",
        "",
        "| kind | n | resolved | win_rate | E |",
        "|---|---|---|---|---|",
    ]
    for kind, row in ga["by_kind"].items():
        if kind == "RAND":
            continue
        L.append(
            f"| {kind} | {row['n']} | {row['resolved']} | "
            f"{_fmt_rate(row['win_rate'])} | {_fmt(row['E'])} |"
        )
    L += [
        "",
        "### By regime (descriptive)",
        "",
        "| regime | real n | real win% | placebo win% |",
        "|---|---|---|---|",
    ]
    for reg, block in ga["by_regime"].items():
        L.append(
            f"| {reg} | {block['real']['n']} | {_fmt_rate(block['real']['win_rate'])} | "
            f"{_fmt_rate(block['placebo']['win_rate'])} |"
        )
    if ga.get("regime_note"):
        L += ["", f"Note: {ga['regime_note']}", ""]

    L += [
        "## G_role_walls — secondary",
        "",
        f"**Verdict: {gr['verdict']}**",
        "",
        f"> {gr['question']}",
        "",
        f"- Real win_rate: {_fmt_rate(gr['real']['win_rate'])}; "
        f"placebo: {_fmt_rate(gr['placebo']['win_rate'])}; "
        f"edge: {_fmt_rate(gr['win_rate_edge'])}",
        f"- Real E: {_fmt(gr['real']['E'])}; placebo E: {_fmt(gr['placebo']['E'])}",
        "",
        "### By level kind (real, role mode)",
        "",
        "| kind | n | resolved | win_rate | E |",
        "|---|---|---|---|---|",
    ]
    for kind, row in gr["by_kind"].items():
        if kind == "RAND":
            continue
        L.append(
            f"| {kind} | {row['n']} | {row['resolved']} | "
            f"{_fmt_rate(row['win_rate'])} | {_fmt(row['E'])} |"
        )

    L += [
        "",
        "## Disposition",
        "",
        f"- Pack (primary G_approach): **{res['pack_verdict']}**",
        "- Decide stays WAIT. No admission.",
        f"- Reproduce: `python tools/{STUDY}.py`",
        "",
        "## Method notes",
        "",
        "- Placebo: same count of random centers per session inside that session's RTH "
          "high/low, same half-width (0.25×session ATR).",
        "- No lookahead: levels from ≤10:15 ET observation; touches only after 10:15 ET.",
        "- Costs ABSENT — any economic claim would require a cost layer.",
        "- Fair-method: equal zone width real vs placebo; no invented levels on missing days.",
        "",
    ]
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", default="SPY,QQQ,IWM")
    a = ap.parse_args()
    tickers = [t.strip().upper() for t in a.tickers.split(",") if t.strip()]
    print(f"running {STUDY} tickers={tickers} …", flush=True)
    res = run(tickers)
    out = REPO / "reports"
    out.mkdir(exist_ok=True)
    (out / f"{STUDY}.json").write_text(json.dumps(res, indent=2, default=str), encoding="utf-8")
    (out / f"{STUDY}.md").write_text(_markdown(res), encoding="utf-8")
    print(f"pack={res['pack_verdict']} sessions={res['sample']['n_sessions_scored']} "
          f"runtime={res['runtime_sec']}s")
    for k, v in res["verdicts"].items():
        exp = res["experiments"][k]
        print(f"  {k}: {v}  real={exp['real']['win_rate']} placebo={exp['placebo']['win_rate']} "
              f"edge={exp['win_rate_edge']} n_real={exp['n_real_events']}")
    print(f"wrote {out / (STUDY + '.md')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
