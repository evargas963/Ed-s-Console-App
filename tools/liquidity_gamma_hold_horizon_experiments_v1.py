"""Liquidity gamma hold / flip-regime / multi-horizon experiments v1.

Find & Prove / offline only. NO Decide admission. NO UI. NO server path.

Reuses observation + terrain reconstruction patterns from
tools/liquidity_gamma_levels_experiment_v1.py and barrier discipline from
tools/liquidity_synthesis_experiments_v1.py.

Experiments (operator ranked list #3, #4, #7):
  #3 Wall-hold / magnet — session respect + touch-and-hold vs break-and-go
     (NOT the prior touch→bounce objective).
  #4 morning_full / flip + regime — exact day counts; flip touches;
     LONG/SHORT split when present; LIMIT if one-sided.
  #7 Multi-horizon barriers — 15m / 60m / EOD on the SAME zones + placebo.

Causal rule: levels from morning_full (prefer) or snapshots@10:00 ET
(09:45–10:15); touch / post-obs scoring starts at 10:15 ET. Costs ABSENT.

USAGE:
  python tools/liquidity_gamma_hold_horizon_experiments_v1.py
  python tools/liquidity_gamma_hold_horizon_experiments_v1.py --tickers SPY,QQQ,IWM
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
from time_et import ET, is_trading_day_et  # noqa: E402

# ── Pre-registered constants ─────────────────────────────────────────────────
RTH_OPEN_MIN = 9 * 60 + 30
RTH_CLOSE_MIN = 16 * 60
OBS_LO_MIN, OBS_HI_MIN = 9 * 60 + 45, 10 * 60 + 15
TOUCH_START_MIN = 10 * 60 + 15
WIDTH_ATR_FRAC = 0.25
REARM_ATR_MULT = 0.25
K_ATR = 1.0
SEED = 20260730

# #3 hold / respect parameters (pre-registered)
APPROACH_ATR = 0.50          # "approach within X ATR"
CLOSE_THROUGH_ATR = 0.25     # "without closing through by Y ATR"
HOLD_HORIZON_MIN = 30        # touch-and-hold window for event arm

# #7 horizons
HORIZONS = {
    "15m": 15,
    "60m": 60,
    "EOD": None,             # session end (last RTH bar)
}

LEVEL_KINDS = ("CALL_WALL", "PUT_WALL", "GAMMA_FLIP", "GAMMA_PIN")
WALL_KINDS = ("CALL_WALL", "PUT_WALL", "GAMMA_PIN")

PASS = {
    "min_events_per_arm": 150,
    "min_hold_edge_pp": 0.05,       # real - placebo hold_rate among approached/touched
    "min_win_rate_edge_pp": 0.05,   # #7 bounce arm (continuity with prior pack)
    "min_halves_agreeing": 2,
    "min_regime_resolved": 150,
    "min_morning_full_days_per_ticker": 20,  # ops target — not invented
}

STUDY = "liquidity_gamma_hold_horizon_experiments_v1"
DB = REPO / "data" / "ed_console.db"


# ── Bars ─────────────────────────────────────────────────────────────────────

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
    horizon: int | None,
    k: float = K_ATR,
) -> dict:
    """direction +1 support bounce; -1 resistance bounce. Costs ABSENT.
    horizon=None → score until last session bar (EOD)."""
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
    if horizon is None:
        end = len(sb) - 1
    else:
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


def _summarize_binary(events: list[dict], flag: str) -> dict:
    """flag True = hold/success among events that qualify (approached/touched)."""
    n = len(events)
    holds = sum(1 for e in events if e.get(flag))
    rate = holds / n if n else None
    return {"n": n, "holds": holds, "hold_rate": rate}


def _date_half_edge_binary(
    real: list[dict], placebo: list[dict], flag: str = "held",
) -> dict:
    dates = sorted({e["session"] for e in real + placebo})
    if len(dates) < 20:
        return {"evaluated": False, "reason": "insufficient sessions",
                "halves_agree": False, "n_agree": 0}
    cut = dates[len(dates) // 2]
    agree = 0
    halves = {}
    for name, pred in (("first", lambda s: s < cut), ("second", lambda s: s >= cut)):
        r = _summarize_binary([e for e in real if pred(e["session"])], flag)
        p = _summarize_binary([e for e in placebo if pred(e["session"])], flag)
        edge = None
        if r["hold_rate"] is not None and p["hold_rate"] is not None:
            edge = r["hold_rate"] - p["hold_rate"]
            if edge >= 0:
                agree += 1
        halves[name] = {"real": r, "placebo": p, "edge_pp": edge}
    return {
        "evaluated": True, "split_date": cut, "halves": halves,
        "halves_agree": agree >= PASS["min_halves_agreeing"], "n_agree": agree,
    }


def _date_half_edge_labels(real: list[dict], placebo: list[dict]) -> dict:
    dates = sorted({e["session"] for e in real + placebo})
    if len(dates) < 20:
        return {"evaluated": False, "reason": "insufficient sessions",
                "halves_agree": False, "n_agree": 0}
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
    return {
        "evaluated": True, "split_date": cut, "halves": halves,
        "halves_agree": agree >= PASS["min_halves_agreeing"], "n_agree": agree,
    }


def _verdict_hold(real_s: dict, placebo_s: dict, oos: dict) -> str:
    if (real_s["n"] < PASS["min_events_per_arm"]
            or placebo_s["n"] < PASS["min_events_per_arm"]):
        return "FAIL"
    if real_s["hold_rate"] is None or placebo_s["hold_rate"] is None:
        return "FAIL"
    edge = real_s["hold_rate"] - placebo_s["hold_rate"]
    if edge < PASS["min_hold_edge_pp"]:
        return "FAIL"
    if not oos.get("halves_agree"):
        return "FAIL"
    return "PASS"


def _verdict_bounce(real_s: dict, placebo_s: dict, oos: dict) -> str:
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


# ── Gamma observation / levels ───────────────────────────────────────────────

def _et_day_and_min(ts: float) -> tuple[str, int]:
    d = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(ET)
    return d.strftime("%Y-%m-%d"), d.hour * 60 + d.minute


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


def _morning_full_counts(con: sqlite3.Connection, tickers: list[str]) -> dict:
    """Exact COUNT(*) per ticker from option_chain_morning_full (trading days)."""
    by_tk = {}
    for tk in tickers:
        n = 0
        days = []
        for (day,) in con.execute(
            "SELECT et_date FROM option_chain_morning_full WHERE ticker=? ORDER BY et_date",
            (tk,),
        ):
            if day and is_trading_day_et(str(day)):
                n += 1
                days.append(str(day))
        by_tk[tk] = {
            "n_days": n,
            "date_min": days[0] if days else None,
            "date_max": days[-1] if days else None,
            "meets_ops_target_20": n >= PASS["min_morning_full_days_per_ticker"],
        }
    return by_tk


def _levels_from_snap(ticker: str, spot: float, chain_raw: str) -> dict | None:
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
    gex = snap.net_gex_at_spot
    regime = None
    # RC-345 / F07: the gamma-regime SIGN is classified by the ONE authority,
    # terrain_read.regime_from_signed_gamma — this backtest does not re-derive `gex > 0`
    # locally. It maps the canonical verdict into its own two-token research vocabulary
    # (LONG_GAMMA / SHORT_GAMMA), the way institutional_behavior maps to its hint labels.
    from terrain_read import regime_from_signed_gamma, REGIME_LONG_GAMMA
    _canon = regime_from_signed_gamma(gex)
    if _canon is not None:
        regime = "LONG_GAMMA" if _canon == REGIME_LONG_GAMMA else "SHORT_GAMMA"
    elif snap.regime in ("LONG_GAMMA_CHOP", "SHORT_GAMMA_TREND"):
        # Carry the canonical terrain regime (also produced by terrain_read._regime_for).
        regime = "LONG_GAMMA" if snap.regime.startswith("LONG") else "SHORT_GAMMA"
    # RC-345 / F07: NO local `spot > gamma_flip` reconstruction. When neither the signed
    # gamma nor the canonical terrain regime is available, the regime is WITHHELD (None) —
    # the backtest does not manufacture a second gamma-regime authority from spot vs flip.
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


def _direction_approach(kind: str, prev_c: float, mid: float) -> int:
    return 1 if prev_c >= mid else -1


def _role_side(kind: str) -> str | None:
    """CALL_WALL = resistance above; PUT_WALL = support below; PIN = magnet (both)."""
    if kind == "CALL_WALL":
        return "resistance"
    if kind == "PUT_WALL":
        return "support"
    if kind == "GAMMA_PIN":
        return "magnet"
    return None


# ── #3 Session respect + touch-hold ──────────────────────────────────────────

def _session_respect_one(
    sb: list[dict],
    kind: str,
    mid: float,
    *,
    atr: float,
    spot_morn: float,
) -> dict | None:
    """Post-10:15 session high/low/close vs morning level.

    CALL_WALL (resistance):
      approached = session_high >= mid - APPROACH_ATR*atr
      held = approached AND session_close <= mid + CLOSE_THROUGH_ATR*atr
             AND session_high <= mid + APPROACH_ATR*atr
             (approach from below without trading far through)
    PUT_WALL (support): symmetric.
    GAMMA_PIN (magnet):
      approached = min(|H-mid|,|L-mid|,|C-mid|) path: high/low range covers mid±approach
                   OR abs(close-mid) <= APPROACH_ATR*atr
      held (magnet) = approached AND abs(session_close - mid) <= APPROACH_ATR*atr
                      (finished near pin — magnet close, not bounce)
    """
    post = [b for b in sb if b["min_of_day"] >= TOUCH_START_MIN]
    if not post or atr <= 0:
        return None
    hi = max(b["high"] for b in post)
    lo = min(b["low"] for b in post)
    close = post[-1]["close"]
    x = APPROACH_ATR * atr
    y = CLOSE_THROUGH_ATR * atr
    side = _role_side(kind)
    if side == "resistance":
        # Only score walls that started at/above morning spot (role-consistent)
        if mid < spot_morn - x:
            role_ok = False
        else:
            role_ok = True
        approached = hi >= (mid - x)
        held = bool(
            approached and close <= (mid + y) and hi <= (mid + x + y)
        )
        # break-and-go: approached and closed through
        broke = bool(approached and close > (mid + y))
        mae = max(0.0, hi - mid) / atr  # adverse for short-at-wall (in ATR)
    elif side == "support":
        if mid > spot_morn + x:
            role_ok = False
        else:
            role_ok = True
        approached = lo <= (mid + x)
        held = bool(
            approached and close >= (mid - y) and lo >= (mid - x - y)
        )
        broke = bool(approached and close < (mid - y))
        mae = max(0.0, mid - lo) / atr
    elif side == "magnet":
        role_ok = True
        approached = (lo <= mid + x) and (hi >= mid - x)
        held = bool(approached and abs(close - mid) <= x)
        broke = bool(approached and abs(close - mid) > x)
        mae = abs(close - mid) / atr
    else:
        return None
    return {
        "kind": kind,
        "mid": mid,
        "side": side,
        "role_ok": role_ok,
        "approached": approached,
        "held": held,
        "broke": broke,
        "mae_atr": mae,
        "session_high": hi,
        "session_low": lo,
        "session_close": close,
    }


def _touch_hold_events(
    sb: list[dict],
    levels: dict[str, float],
    *,
    ticker: str,
    sess: str,
    atr_session: float,
    half_width: float,
    regime: str | None,
    confidence: str | None,
    arm: str,
    horizon_min: int = HOLD_HORIZON_MIN,
) -> list[dict]:
    """First-touch after 10:15: HOLD if no close-through within horizon; else BREAK."""
    if atr_session <= 0 or half_width <= 0 or not levels:
        return []
    zones = []
    for kind, mid in levels.items():
        if kind not in WALL_KINDS:
            continue
        zones.append({
            "kind": kind, "mid": mid,
            "lo": mid - half_width, "hi": mid + half_width,
            "side": _role_side(kind),
        })
    rearm = atr_session * REARM_ATR_MULT
    armed = [True] * len(zones)
    events = []
    for i, b in enumerate(sb):
        if b["min_of_day"] < TOUCH_START_MIN or i == 0:
            continue
        for zi, z in enumerate(zones):
            inside = b["low"] <= z["hi"] and b["high"] >= z["lo"]
            if inside and armed[zi]:
                armed[zi] = False
                atr = _causal_atr(sb, i)
                if atr <= 0:
                    continue
                y = CLOSE_THROUGH_ATR * atr
                end = min(len(sb) - 1, i + horizon_min)
                held = True
                bars_to_break = None
                for j in range(i, end + 1):
                    c = sb[j]["close"]
                    if z["side"] == "resistance":
                        if c > z["hi"] + y:
                            held = False
                            bars_to_break = j - i
                            break
                    elif z["side"] == "support":
                        if c < z["lo"] - y:
                            held = False
                            bars_to_break = j - i
                            break
                    else:  # magnet: break = leave the zone band by y
                        if c > z["hi"] + y or c < z["lo"] - y:
                            held = False
                            bars_to_break = j - i
                            break
                events.append({
                    "ticker": ticker, "session": sess, "i": i,
                    "kind": z["kind"], "mid": z["mid"],
                    "zone_lo": z["lo"], "zone_hi": z["hi"],
                    "side": z["side"],
                    "regime": regime, "confidence": confidence,
                    "held": held, "broke": not held,
                    "bars_to_break": bars_to_break,
                    "arm": arm,
                    "label": "HOLD" if held else "BREAK",
                })
            elif not inside:
                if abs(b["close"] - z["mid"]) > rearm:
                    armed[zi] = True
    return events


def _scan_bounce_touches(
    sb: list[dict],
    levels: dict[str, float],
    *,
    ticker: str,
    sess: str,
    atr_session: float,
    half_width: float,
    regime: str | None,
    confidence: str | None,
    horizon: int | None,
    arm: str,
    kind_filter: tuple[str, ...] | None = None,
) -> list[dict]:
    if atr_session <= 0 or half_width <= 0 or not levels:
        return []
    zones = []
    for kind, mid in levels.items():
        if kind_filter and kind not in kind_filter:
            continue
        zones.append({
            "kind": kind, "mid": mid,
            "lo": mid - half_width, "hi": mid + half_width,
        })
    rearm = atr_session * REARM_ATR_MULT
    armed = [True] * len(zones)
    events = []
    for i, b in enumerate(sb):
        if b["min_of_day"] < TOUCH_START_MIN or i == 0:
            continue
        for zi, z in enumerate(zones):
            inside = b["low"] <= z["hi"] and b["high"] >= z["lo"]
            if inside and armed[zi]:
                armed[zi] = False
                prev_c = sb[i - 1]["close"]
                direction = _direction_approach(z["kind"], prev_c, z["mid"])
                atr = _causal_atr(sb, i)
                tb = _triple_barrier(
                    sb, i, direction=direction,
                    zone_lo=z["lo"], zone_hi=z["hi"], atr=atr,
                    horizon=horizon,
                )
                if tb["label"] is None:
                    continue
                events.append({
                    "ticker": ticker, "session": sess, "i": i,
                    "kind": z["kind"], "mid": z["mid"],
                    "zone_lo": z["lo"], "zone_hi": z["hi"],
                    "direction": direction,
                    "regime": regime, "confidence": confidence,
                    "label": tb["label"], "reward_risk": tb["reward_risk"],
                    "bars": tb.get("bars"),
                    "arm": arm,
                    "horizon": "EOD" if horizon is None else f"{horizon}m",
                })
            elif not inside:
                if abs(b["close"] - z["mid"]) > rearm:
                    armed[zi] = True
    return events


def _random_levels_same_distance(
    real_levels: dict[str, float],
    spot: float,
    rth_lo: float,
    rth_hi: float,
    rnd: random.Random,
) -> dict[str, float]:
    """Placebo: same |distance from spot| as real, random side / clamp into RTH span.
    Fair same-distance null (operator: random same-distance levels)."""
    out = {}
    for i, (kind, mid) in enumerate(real_levels.items()):
        dist = abs(mid - spot)
        sign = rnd.choice((-1.0, 1.0))
        fake = spot + sign * dist
        # keep inside session range ± small pad so approach is possible
        fake = min(max(fake, rth_lo), rth_hi)
        if abs(fake - spot) < 1e-9:
            fake = rnd.uniform(rth_lo, rth_hi)
        out[f"RAND_{kind}_{i}"] = fake
    return out


def _random_levels_uniform(
    n: int, rth_lo: float, rth_hi: float, rnd: random.Random,
) -> dict[str, float]:
    if n <= 0 or rth_hi <= rth_lo:
        return {}
    return {f"RAND_{i}": rnd.uniform(rth_lo, rth_hi) for i in range(n)}


# ── Study body ───────────────────────────────────────────────────────────────

def run(tickers: list[str]) -> dict:
    t0 = time.time()
    rnd = random.Random(SEED)
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)

    mf_counts = _morning_full_counts(con, tickers)
    obs = _load_obs_chains(con, tickers)
    coverage = {tk: 0 for tk in tickers}
    for tk, _day in obs:
        coverage[tk] = coverage.get(tk, 0) + 1

    bars_by_tk = {tk: _rows(con, tk) for tk in tickers}
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

    # Accumulators
    recon_ok = recon_fail = recon_empty = 0
    level_presence = {k: 0 for k in LEVEL_KINDS}
    conf_counts: dict[str, int] = defaultdict(int)
    regime_day_counts: dict[str, int] = defaultdict(int)
    faucet_counts: dict[str, int] = defaultdict(int)
    mf_regime_day_counts: dict[str, int] = defaultdict(int)
    mf_level_presence = {k: 0 for k in LEVEL_KINDS}
    mf_conf_counts: dict[str, int] = defaultdict(int)

    # #3
    sess_respect_real: list[dict] = []
    sess_respect_placebo: list[dict] = []
    touch_hold_real: list[dict] = []
    touch_hold_placebo: list[dict] = []

    # #4
    flip_touches_real: list[dict] = []
    flip_touches_placebo: list[dict] = []
    wall_hold_by_regime_real: list[dict] = []
    wall_hold_by_regime_placebo: list[dict] = []

    # #7
    bounce_by_h: dict[str, list[dict]] = {h: [] for h in HORIZONS}
    placebo_by_h: dict[str, list[dict]] = {h: [] for h in HORIZONS}

    day_rows: list[dict] = []

    for (tk, day), meta in sorted(obs.items()):
        sb = sess_bars.get((tk, day))
        if not sb or len(sb) < 40:
            continue
        got = _levels_from_snap(tk, meta["spot"], meta["chain_raw"])
        if got is None or "error" in got:
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
        spot_morn = float(got["spot"])

        if faucet == "morning_full":
            mf_conf_counts[conf] += 1
            if regime:
                mf_regime_day_counts[regime] += 1
            for k in levels:
                mf_level_presence[k] = mf_level_presence.get(k, 0) + 1

        atr = _session_atr(sb)
        if atr <= 0:
            continue
        half = WIDTH_ATR_FRAC * atr
        rth_lo = min(b["low"] for b in sb)
        rth_hi = max(b["high"] for b in sb)

        day_rows.append({
            "ticker": tk, "day": day, "spot": spot_morn,
            "regime": regime, "confidence": conf, "faucet": faucet,
            "levels": {k: levels[k] for k in levels},
            "n_levels": len(levels),
            "net_gex_at_spot": got.get("net_gex_at_spot"),
            "n_contracts": got.get("n_contracts") or meta.get("n_contracts"),
        })

        # Placebo levels: same-distance (primary null for #3 session) + uniform for touches
        wall_levels = {k: levels[k] for k in WALL_KINDS if k in levels}
        placebo_dist = _random_levels_same_distance(
            wall_levels, spot_morn, rth_lo, rth_hi, rnd,
        )
        # Map placebo keys back to roles for session scoring
        placebo_role_levels = {}
        for (rk, _), (pk, pv) in zip(wall_levels.items(), placebo_dist.items()):
            # preserve role kind for scoring semantics
            placebo_role_levels[rk] = pv

        # ── #3 session respect ──
        for kind, mid in wall_levels.items():
            row = _session_respect_one(
                sb, kind, mid, atr=atr, spot_morn=spot_morn,
            )
            if row is None or not row["role_ok"]:
                continue
            if not row["approached"]:
                continue  # fair: only score approached days (else hold_rate meaningless)
            sess_respect_real.append({
                "ticker": tk, "session": day, "arm": "real",
                "regime": regime, "confidence": conf, "faucet": faucet,
                **row,
            })
        for kind, mid in placebo_role_levels.items():
            row = _session_respect_one(
                sb, kind, mid, atr=atr, spot_morn=spot_morn,
            )
            if row is None or not row["role_ok"]:
                continue
            if not row["approached"]:
                continue
            sess_respect_placebo.append({
                "ticker": tk, "session": day, "arm": "placebo",
                "regime": regime, "confidence": conf, "faucet": faucet,
                **row,
            })

        # ── #3 touch-and-hold ──
        thr = _touch_hold_events(
            sb, wall_levels, ticker=tk, sess=day, atr_session=atr,
            half_width=half, regime=regime, confidence=conf, arm="real",
        )
        thp = _touch_hold_events(
            sb, placebo_role_levels, ticker=tk, sess=day, atr_session=atr,
            half_width=half, regime=regime, confidence=conf, arm="placebo",
        )
        for e in thp:
            e["kind"] = "RAND"
        touch_hold_real.extend(thr)
        touch_hold_placebo.extend(thp)

        # ── #4 flip touches (morning_full preferred; score wherever flip present) ──
        if "GAMMA_FLIP" in levels:
            flip_only = {"GAMMA_FLIP": levels["GAMMA_FLIP"]}
            fr = _scan_bounce_touches(
                sb, flip_only, ticker=tk, sess=day, atr_session=atr,
                half_width=half, regime=regime, confidence=conf,
                horizon=30, arm="real", kind_filter=("GAMMA_FLIP",),
            )
            # same-distance placebo for flip
            flip_plac = _random_levels_same_distance(
                flip_only, spot_morn, rth_lo, rth_hi, rnd,
            )
            fp_levels = {"GAMMA_FLIP": next(iter(flip_plac.values()))}
            fp = _scan_bounce_touches(
                sb, fp_levels, ticker=tk, sess=day, atr_session=atr,
                half_width=half, regime=regime, confidence=conf,
                horizon=30, arm="placebo", kind_filter=("GAMMA_FLIP",),
            )
            for e in fp:
                e["kind"] = "RAND_FLIP"
            flip_touches_real.extend(fr)
            flip_touches_placebo.extend(fp)

        # Regime-conditional wall hold (session respect, walls only) — for #4
        if regime:
            for kind in ("CALL_WALL", "PUT_WALL"):
                if kind not in levels:
                    continue
                row = _session_respect_one(
                    sb, kind, levels[kind], atr=atr, spot_morn=spot_morn,
                )
                if row is None or not row["role_ok"] or not row["approached"]:
                    continue
                wall_hold_by_regime_real.append({
                    "ticker": tk, "session": day, "arm": "real",
                    "regime": regime, "faucet": faucet, **row,
                })
                pmid = placebo_role_levels.get(kind)
                if pmid is None:
                    continue
                prow = _session_respect_one(
                    sb, kind, pmid, atr=atr, spot_morn=spot_morn,
                )
                if prow is None or not prow["role_ok"] or not prow["approached"]:
                    continue
                wall_hold_by_regime_placebo.append({
                    "ticker": tk, "session": day, "arm": "placebo",
                    "regime": regime, "faucet": faucet, **prow,
                })

        # ── #7 multi-horizon bounce (same zones) ──
        all_levels = dict(levels)
        for hname, hmin in HORIZONS.items():
            br = _scan_bounce_touches(
                sb, all_levels, ticker=tk, sess=day, atr_session=atr,
                half_width=half, regime=regime, confidence=conf,
                horizon=hmin, arm="real",
            )
            n_zones = len(all_levels)
            fake = _random_levels_uniform(n_zones, rth_lo, rth_hi, rnd)
            bp = _scan_bounce_touches(
                sb, fake, ticker=tk, sess=day, atr_session=atr,
                half_width=half, regime=regime, confidence=conf,
                horizon=hmin, arm="placebo",
            )
            for e in bp:
                e["kind"] = "RAND"
            bounce_by_h[hname].extend(br)
            placebo_by_h[hname].extend(bp)

    # ── Summaries ────────────────────────────────────────────────────────────

    def hold_block(real, placebo, *, name: str, question: str) -> dict:
        rs = _summarize_binary(real, "held")
        ps = _summarize_binary(placebo, "held")
        edge = None
        if rs["hold_rate"] is not None and ps["hold_rate"] is not None:
            edge = rs["hold_rate"] - ps["hold_rate"]
        oos = _date_half_edge_binary(real, placebo, "held")
        verdict = _verdict_hold(rs, ps, oos)
        by_kind = {}
        for kind in WALL_KINDS:
            by_kind[kind] = _summarize_binary(
                [e for e in real if e.get("kind") == kind], "held",
            )
        by_kind["RAND"] = ps
        # MAE descriptive
        mae_real = [e["mae_atr"] for e in real if e.get("mae_atr") is not None]
        mae_plac = [e["mae_atr"] for e in placebo if e.get("mae_atr") is not None]
        return {
            "name": name,
            "question": question,
            "real": rs,
            "placebo": ps,
            "hold_rate_edge": edge,
            "mean_mae_atr_real": statistics.fmean(mae_real) if mae_real else None,
            "mean_mae_atr_placebo": statistics.fmean(mae_plac) if mae_plac else None,
            "oos": {
                "evaluated": oos.get("evaluated"),
                "split_date": oos.get("split_date"),
                "halves_agree": oos.get("halves_agree"),
                "n_agree": oos.get("n_agree"),
                "halves": {
                    h: {
                        "edge_pp": oos["halves"][h]["edge_pp"],
                        "real_hold_rate": oos["halves"][h]["real"]["hold_rate"],
                        "placebo_hold_rate": oos["halves"][h]["placebo"]["hold_rate"],
                        "real_n": oos["halves"][h]["real"]["n"],
                        "placebo_n": oos["halves"][h]["placebo"]["n"],
                    }
                    for h in (oos.get("halves") or {})
                } if oos.get("evaluated") else None,
            },
            "by_kind": by_kind,
            "verdict": verdict,
            "costs": "ABSENT",
            "definition": {
                "approach_atr": APPROACH_ATR,
                "close_through_atr": CLOSE_THROUGH_ATR,
                "touch_hold_horizon_min": HOLD_HORIZON_MIN,
                "placebo": "same |distance from morning spot|, role-preserving",
            },
        }

    exp3_session = hold_block(
        sess_respect_real, sess_respect_placebo,
        name="session_respect",
        question=(
            "Given morning CALL_WALL / PUT_WALL / PIN, when post-10:15 price "
            "approaches within 0.5×ATR, does the session hold (no close-through "
            "by 0.25×ATR / pin-close magnet) better than same-distance random levels?"
        ),
    )
    exp3_touch = hold_block(
        touch_hold_real, touch_hold_placebo,
        name="touch_and_hold",
        question=(
            "On first post-10:15 zone touch, does price avoid close-through within "
            f"{HOLD_HORIZON_MIN}m more often than same-distance placebo?"
        ),
    )
    # MAE not on touch events — clear
    exp3_touch["mean_mae_atr_real"] = None
    exp3_touch["mean_mae_atr_placebo"] = None

    # #4 flip + regime
    flip_real_s = _summarize_labels(flip_touches_real)
    flip_plac_s = _summarize_labels(flip_touches_placebo)
    flip_edge = None
    if flip_real_s["win_rate"] is not None and flip_plac_s["win_rate"] is not None:
        flip_edge = flip_real_s["win_rate"] - flip_plac_s["win_rate"]
    flip_oos = _date_half_edge_labels(flip_touches_real, flip_touches_placebo)
    flip_verdict = (
        "BLOCKED"
        if flip_real_s["n"] == 0
        else _verdict_bounce(flip_real_s, flip_plac_s, flip_oos)
    )

    by_regime_hold = {}
    for reg in ("LONG_GAMMA", "SHORT_GAMMA"):
        sub_r = [e for e in wall_hold_by_regime_real if e.get("regime") == reg]
        sub_p = [e for e in wall_hold_by_regime_placebo if e.get("regime") == reg]
        rs = _summarize_binary(sub_r, "held")
        ps = _summarize_binary(sub_p, "held")
        edge = None
        if rs["hold_rate"] is not None and ps["hold_rate"] is not None:
            edge = rs["hold_rate"] - ps["hold_rate"]
        by_regime_hold[reg] = {"real": rs, "placebo": ps, "hold_rate_edge": edge}

    long_n_days = regime_day_counts.get("LONG_GAMMA", 0)
    short_n_days = regime_day_counts.get("SHORT_GAMMA", 0)
    mf_long = mf_regime_day_counts.get("LONG_GAMMA", 0)
    mf_short = mf_regime_day_counts.get("SHORT_GAMMA", 0)

    limits_4 = []
    if any(not mf_counts[tk]["meets_ops_target_20"] for tk in tickers):
        limits_4.append(
            f"morning_full days/ticker below ops target "
            f"{PASS['min_morning_full_days_per_ticker']}: "
            + ", ".join(f"{tk}={mf_counts[tk]['n_days']}" for tk in tickers)
            + ". Accrue more TRUSTED morning_full sessions (ops) — do not invent."
        )
    if flip_real_s["n"] == 0:
        limits_4.append(
            "GAMMA_FLIP post-10:15 touches = 0 in this sample "
            "(flip typically outside traded range). Flip bounce arm BLOCKED."
        )
    if long_n_days == 0:
        limits_4.append(
            "LONG_GAMMA reconstructed days = 0 in scored sample "
            f"(SHORT_GAMMA days={short_n_days}; morning_full regime days "
            f"LONG={mf_long} SHORT={mf_short}). Regime split one-sided; "
            "SHORT-only wall-hold numbers are descriptive with caveat."
        )
    thin_reg = any(
        by_regime_hold[r]["real"]["n"] < PASS["min_regime_resolved"]
        for r in ("LONG_GAMMA", "SHORT_GAMMA")
    )
    if thin_reg:
        limits_4.append(
            f"Regime-conditional hold n below PASS min_regime_resolved="
            f"{PASS['min_regime_resolved']}; no PASS claim on regime split."
        )

    exp4 = {
        "name": "morning_full_flip_regime",
        "question": (
            "On TRUSTED morning_full (+ causal snapshot fill for walls), "
            "do flip touches exist and does wall-hold differ by LONG/SHORT gamma?"
        ),
        "morning_full_exact_counts": mf_counts,
        "ops_note": (
            f"Accrue to N≥{PASS['min_morning_full_days_per_ticker']} "
            "TRUSTED morning_full days/ticker is an ops Collect target — "
            "not synthetic history."
        ),
        "faucet_counts": dict(faucet_counts),
        "regime_day_counts_all_faucets": dict(regime_day_counts),
        "regime_day_counts_morning_full_only": dict(mf_regime_day_counts),
        "mf_level_presence": dict(mf_level_presence),
        "mf_confidence": dict(mf_conf_counts),
        "flip_touches": {
            "n_real": flip_real_s["n"],
            "n_placebo": flip_plac_s["n"],
            "real": flip_real_s,
            "placebo": flip_plac_s,
            "win_rate_edge": flip_edge,
            "verdict": flip_verdict,
            "oos_halves_agree": flip_oos.get("halves_agree"),
        },
        "wall_hold_by_regime": by_regime_hold,
        "LIMITS": limits_4,
        "verdict": (
            "BLOCKED" if flip_real_s["n"] == 0 and long_n_days == 0
            else ("FAIL" if flip_verdict in ("FAIL", "BLOCKED") else flip_verdict)
        ),
        "costs": "ABSENT",
    }
    # Pack-level #4: if flip blocked and only SHORT measurable, verdict = LIMIT/FAIL
    if flip_real_s["n"] == 0:
        # Still report SHORT wall-hold descriptive
        short_edge = by_regime_hold["SHORT_GAMMA"]["hold_rate_edge"]
        short_n = by_regime_hold["SHORT_GAMMA"]["real"]["n"]
        if short_n >= PASS["min_events_per_arm"] and short_edge is not None:
            exp4["verdict"] = (
                "FAIL" if short_edge < PASS["min_hold_edge_pp"] else "PASS_SHORT_ONLY_CAVEAT"
            )
            # Never PASS without OOS + LONG — downgrade
            if exp4["verdict"] == "PASS_SHORT_ONLY_CAVEAT":
                exp4["verdict"] = "FAIL"  # one-sided sample cannot PASS pack gate
                exp4["short_only_note"] = (
                    f"SHORT wall-hold edge={short_edge:.3f} on n={short_n} "
                    "approached events — descriptive only; pack FAIL (no LONG, no flip touches)."
                )
        else:
            exp4["verdict"] = "BLOCKED"

    # #7 multi-horizon
    exp7 = {"name": "multi_horizon_barriers", "horizons": {}, "verdicts": {}}
    for hname in HORIZONS:
        real = bounce_by_h[hname]
        plac = placebo_by_h[hname]
        rs = _summarize_labels(real)
        ps = _summarize_labels(plac)
        edge = None
        if rs["win_rate"] is not None and ps["win_rate"] is not None:
            edge = rs["win_rate"] - ps["win_rate"]
        oos = _date_half_edge_labels(real, plac)
        verdict = _verdict_bounce(rs, ps, oos)
        by_kind = {
            k: _summarize_labels([e for e in real if e.get("kind") == k])
            for k in LEVEL_KINDS
        }
        exp7["horizons"][hname] = {
            "horizon": hname,
            "horizon_min": HORIZONS[hname],
            "n_real": len(real),
            "n_placebo": len(plac),
            "real": rs,
            "placebo": ps,
            "win_rate_edge": edge,
            "oos": {
                "evaluated": oos.get("evaluated"),
                "split_date": oos.get("split_date"),
                "halves_agree": oos.get("halves_agree"),
                "n_agree": oos.get("n_agree"),
            },
            "by_kind": by_kind,
            "verdict": verdict,
            "costs": "ABSENT",
        }
        exp7["verdicts"][hname] = verdict
    # Did any horizon flip FAIL→PASS?
    exp7["horizon_changes_verdict"] = {
        h: exp7["verdicts"][h] for h in HORIZONS
    }
    exp7["any_horizon_pass"] = any(v == "PASS" for v in exp7["verdicts"].values())
    exp7["question"] = (
        "On the same morning gamma zones, do 15m / 60m / EOD triple-barrier "
        "bounce labels beat placebo, and does horizon change FAIL→PASS?"
    )
    exp7["pack_verdict"] = "PASS" if exp7["any_horizon_pass"] else "FAIL"

    days_sorted = sorted(day_rows, key=lambda r: (r["day"], r["ticker"]))
    date_min = days_sorted[0]["day"] if days_sorted else None
    date_max = days_sorted[-1]["day"] if days_sorted else None

    pack_verdicts = {
        "E3_session_respect": exp3_session["verdict"],
        "E3_touch_and_hold": exp3_touch["verdict"],
        "E4_flip_regime": exp4["verdict"],
        "E7_multi_horizon": exp7["pack_verdict"],
    }
    # Binding pack: all must PASS for PASS; else FAIL (BLOCKED counts as non-PASS)
    pack = "PASS" if all(v == "PASS" for v in pack_verdicts.values()) else "FAIL"

    result = {
        "study": STUDY,
        "mission": "Find & Prove — DISCUSSION/EXPERIMENT only",
        "decision_path": "NONE — Decide WAIT; no admission",
        "seed": SEED,
        "pass_gate": PASS,
        "definitions": {
            "E3_session_respect": exp3_session["definition"],
            "E3_touch_and_hold": {
                "hold": f"no close-through by {CLOSE_THROUGH_ATR}×ATR within "
                        f"{HOLD_HORIZON_MIN}m after first touch",
                "break": "close-through within horizon",
            },
            "E7_horizons": {k: v for k, v in HORIZONS.items()},
            "costs": "ABSENT",
            "no_lookahead": "levels ≤10:15 ET obs; scoring after 10:15 ET",
        },
        "source": {
            "faucet_priority": [
                "option_chain_morning_full (prefer)",
                "snapshots.option_chain_json nearest 10:00 ET (fill)",
            ],
            "recompute": "terrain_engine.compute_terrain",
            "levels": list(LEVEL_KINDS),
            "trading_days_only": True,
        },
        "sample": {
            "tickers": tickers,
            "obs_days_available": coverage,
            "morning_full_exact_counts": mf_counts,
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
                f"morning_full exact: "
                + ", ".join(f"{tk}={mf_counts[tk]['n_days']}" for tk in tickers)
                + ". No invented levels / no invented future accrual."
            ),
        },
        "experiments": {
            "E3_session_respect": exp3_session,
            "E3_touch_and_hold": exp3_touch,
            "E4_flip_regime": exp4,
            "E7_multi_horizon": exp7,
        },
        "verdicts": pack_verdicts,
        "pack_verdict": pack,
        "runtime_sec": round(time.time() - t0, 1),
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
    e3s = res["experiments"]["E3_session_respect"]
    e3t = res["experiments"]["E3_touch_and_hold"]
    e4 = res["experiments"]["E4_flip_regime"]
    e7 = res["experiments"]["E7_multi_horizon"]
    L = [
        "# Liquidity gamma hold / horizon experiments v1",
        "",
        f"**Pack verdict: {res['pack_verdict']}**",
        "",
        f"- Mission: `{res['mission']}`",
        f"- Decision path: {res['decision_path']}",
        f"- Tickers: `{', '.join(s['tickers'])}`",
        f"- Sessions scored: **{s['n_sessions_scored']}** "
        f"(obs available: {json.dumps(s['obs_days_available'])})",
        f"- Date range: `{s['date_min']}` → `{s['date_max']}`",
        f"- Faucet mix: `{json.dumps(s.get('faucet_counts', {}))}`",
        f"- Seed: `{res['seed']}` · Runtime: {res['runtime_sec']}s",
        "- Costs: **ABSENT** · No lookahead (obs ≤10:15; score after 10:15 ET)",
        "",
        "Discussion (plain English): "
        "`reports/liquidity_gamma_storm_discussion_v1.md`",
        "",
        "## AGENTS.md admission",
        "",
        "| Field | Answer |",
        "|---|---|",
        "| MISSION_CLASS | Find & Prove — offline hold/horizon/regime gamma experiments |",
        "| GAP | Prior bounce pack FAIL; magnet/hold + multi-horizon + morning_full flip untested |",
        "| SMALLEST_COMPLETE_CHANGE | `tools/liquidity_gamma_hold_horizon_experiments_v1.py` + this report |",
        "| MINIMUM_SUFFICIENT_EVIDENCE | Same-turn harness; placebo; exact n; LIMITs stated |",
        "| DECISION_PATH_EFFECT | None — WAIT |",
        "| WHY_NOW | Operator asked experiments #3/#4/#7 + storm discussion |",
        "| TASK_ADMISSION | Admitted as research/backtest only |",
        "",
        "## Pre-registered PASS",
        "",
        "```",
        json.dumps(PASS, indent=2),
        "```",
        "",
        "## Sample LIMIT (PROVEN)",
        "",
        s["LIMIT"],
        "",
        "### morning_full exact day counts (PROVEN `COUNT(*)` trading days)",
        "",
        "| ticker | n_days | date_min | date_max | meets_ops_≥20 |",
        "|---|---|---|---|---|",
    ]
    for tk in s["tickers"]:
        m = s["morning_full_exact_counts"][tk]
        L.append(
            f"| {tk} | {m['n_days']} | {m['date_min']} | {m['date_max']} | "
            f"{m['meets_ops_target_20']} |"
        )
    L += [
        "",
        f"- Level presence (ticker-days): `{json.dumps(s['level_presence_days'])}`",
        f"- Confidence: `{json.dumps(s['confidence_counts'])}`",
        f"- Regime days (all faucets): `{json.dumps(s['regime_day_counts'])}`",
        "",
        "## Verdicts",
        "",
        "| Experiment | Verdict |",
        "|---|---|",
        f"| E3 session respect (magnet/hold) | **{e3s['verdict']}** |",
        f"| E3 touch-and-hold | **{e3t['verdict']}** |",
        f"| E4 flip + regime | **{e4['verdict']}** |",
        f"| E7 multi-horizon (any PASS?) | **{e7['pack_verdict']}** |",
        f"| Pack | **{res['pack_verdict']}** |",
        "",
        "## E3 — Wall-hold / magnet (not bounce)",
        "",
        "### E3a session respect",
        "",
        f"**Verdict: {e3s['verdict']}**",
        "",
        f"> {e3s['question']}",
        "",
        f"- Real approached events: n={e3s['real']['n']}, "
        f"hold_rate={_fmt_rate(e3s['real']['hold_rate'])}",
        f"- Placebo: n={e3s['placebo']['n']}, "
        f"hold_rate={_fmt_rate(e3s['placebo']['hold_rate'])}",
        f"- Edge: {_fmt_rate(e3s['hold_rate_edge'])}",
        f"- Mean MAE (ATR, real/placebo): "
        f"{_fmt(e3s.get('mean_mae_atr_real'))} / "
        f"{_fmt(e3s.get('mean_mae_atr_placebo'))}",
        f"- OOS halves_agree: {e3s['oos'].get('halves_agree')}",
        f"- Costs: {e3s['costs']}",
        "",
        "| kind | n | hold_rate |",
        "|---|---|---|",
    ]
    for kind, row in e3s["by_kind"].items():
        if kind == "RAND":
            continue
        L.append(f"| {kind} | {row['n']} | {_fmt_rate(row['hold_rate'])} |")
    L += [
        "",
        "### E3b touch-and-hold vs break-and-go",
        "",
        f"**Verdict: {e3t['verdict']}**",
        "",
        f"> {e3t['question']}",
        "",
        f"- Real: n={e3t['real']['n']}, hold_rate={_fmt_rate(e3t['real']['hold_rate'])}",
        f"- Placebo: n={e3t['placebo']['n']}, "
        f"hold_rate={_fmt_rate(e3t['placebo']['hold_rate'])}",
        f"- Edge: {_fmt_rate(e3t['hold_rate_edge'])}",
        f"- OOS halves_agree: {e3t['oos'].get('halves_agree')}",
        "",
        "| kind | n | hold_rate |",
        "|---|---|---|",
    ]
    for kind, row in e3t["by_kind"].items():
        if kind == "RAND":
            continue
        L.append(f"| {kind} | {row['n']} | {_fmt_rate(row['hold_rate'])} |")

    L += [
        "",
        "## E4 — morning_full / flip + regime",
        "",
        f"**Verdict: {e4['verdict']}**",
        "",
        f"> {e4['question']}",
        "",
        f"- Ops note: {e4['ops_note']}",
        f"- morning_full regime days: "
        f"`{json.dumps(e4['regime_day_counts_morning_full_only'])}`",
        f"- All-faucet regime days: "
        f"`{json.dumps(e4['regime_day_counts_all_faucets'])}`",
        f"- Flip touches real n={e4['flip_touches']['n_real']} "
        f"(placebo n={e4['flip_touches']['n_placebo']}); "
        f"verdict={e4['flip_touches']['verdict']}",
        "",
    ]
    if e4.get("LIMITS"):
        L.append("### LIMITS")
        L.append("")
        for lim in e4["LIMITS"]:
            L.append(f"- {lim}")
        L.append("")
    if e4.get("short_only_note"):
        L += [f"- {e4['short_only_note']}", ""]

    L += [
        "### Wall-hold by regime (descriptive if thin)",
        "",
        "| regime | real n | real hold% | placebo hold% | edge |",
        "|---|---|---|---|---|",
    ]
    for reg, block in e4["wall_hold_by_regime"].items():
        L.append(
            f"| {reg} | {block['real']['n']} | "
            f"{_fmt_rate(block['real']['hold_rate'])} | "
            f"{_fmt_rate(block['placebo']['hold_rate'])} | "
            f"{_fmt_rate(block['hold_rate_edge'])} |"
        )

    L += [
        "",
        "## E7 — Multi-horizon barriers (same zones)",
        "",
        f"**Pack (any horizon PASS?): {e7['pack_verdict']}**",
        "",
        f"> {e7['question']}",
        "",
        "| horizon | real win% | placebo win% | edge | resolved real/plac | "
        "halves_agree | verdict |",
        "|---|---|---|---|---|---|---|",
    ]
    for hname, block in e7["horizons"].items():
        L.append(
            f"| {hname} | {_fmt_rate(block['real']['win_rate'])} | "
            f"{_fmt_rate(block['placebo']['win_rate'])} | "
            f"{_fmt_rate(block['win_rate_edge'])} | "
            f"{block['real']['resolved']}/{block['placebo']['resolved']} | "
            f"{block['oos'].get('halves_agree')} | **{block['verdict']}** |"
        )
    L += [
        "",
        f"Horizon changes FAIL→PASS? **{'YES' if e7['any_horizon_pass'] else 'NO'}** "
        f"(map: `{json.dumps(e7['horizon_changes_verdict'])}`).",
        "",
        "## Disposition",
        "",
        f"- Pack: **{res['pack_verdict']}**",
        "- Decide stays WAIT. No admission.",
        f"- Reproduce: `python tools/{STUDY}.py`",
        "",
        "## Method notes",
        "",
        "- E3 placebo: same |distance from morning spot| as real wall/pin, "
          "role-preserving scoring.",
        "- E7 placebo: uniform random centers in session RTH high/low, same half-width.",
        "- Fair-method: equal zone width; approached-only for session hold rates; "
          "no invented morning_full days.",
        "- Magnet ≠ bounce: PIN held = session close near pin; walls held = "
          "no close-through after approach.",
        "- Pos vs neg gamma: absorb/pin vs accelerate is literature-supported "
          "directionally; Ed sample here is SHORT-heavy — see E4 LIMITS.",
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
    (out / f"{STUDY}.json").write_text(
        json.dumps(res, indent=2, default=str), encoding="utf-8",
    )
    (out / f"{STUDY}.md").write_text(_markdown(res), encoding="utf-8")
    print(
        f"pack={res['pack_verdict']} sessions={res['sample']['n_sessions_scored']} "
        f"runtime={res['runtime_sec']}s",
    )
    for k, v in res["verdicts"].items():
        print(f"  {k}: {v}")
    e7 = res["experiments"]["E7_multi_horizon"]
    for h, block in e7["horizons"].items():
        print(
            f"  E7 {h}: {block['verdict']} real={block['real']['win_rate']} "
            f"plac={block['placebo']['win_rate']} edge={block['win_rate_edge']}",
        )
    print(f"wrote {out / (STUDY + '.md')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
