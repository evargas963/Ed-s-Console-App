"""Liquidity synthesis experiments v1 — DISCUSSION / Find & Prove only.

Offline bar backtests of confluence / width / OB / FVG hypotheses from
reports/liquidity_synthesis_research_v1.md. Reuses LP-01 bar loading and causal
level constructors. Does NOT reopen LP-01 touch→magnitude as PASS.

NO Decide admission. NO UI. NO server path. Costs ABSENT (stated in report).

USAGE:
  python tools/liquidity_synthesis_experiments_v1.py
  python tools/liquidity_synthesis_experiments_v1.py --tickers SPY,QQQ,IWM --limit-sessions 60
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
from app.domain.time_et import ET, RTH_END_MINS, RTH_START_MINS  # noqa: E402

# ── Pre-registered constants (before results) ────────────────────────────────
RTH_OPEN_MIN, RTH_CLOSE_MIN = int(RTH_START_MINS), int(RTH_END_MINS)
ORB_END_MIN = RTH_OPEN_MIN + 15  # 09:45 ET — opening-range complete (width, not a second open)
HORIZON_MIN = 30
K_ATR = 1.0                    # profit target multiple of session ATR proxy
REARM_ATR_MULT = 0.25
SEED = 20260730

# Family map for causal (pre-touch) levels — operator §2.3 minus lookahead families.
# TODAY_VP and VWAP excluded (intraday evolve; end-of-day values would leak).
# GAMMA excluded from A/B (see Experiment C BLOCKED).
LEVEL_FAMILY = {
    "PDH": "PRIOR_DAY", "PDL": "PRIOR_DAY", "PDC": "PRIOR_DAY",
    "PD_POC": "PRIOR_DAY", "PD_VAH": "PRIOR_DAY", "PD_VAL": "PRIOR_DAY",
    "ON_HIGH": "OVERNIGHT", "ON_LOW": "OVERNIGHT",
    "ORB_HIGH": "ORB", "ORB_LOW": "ORB", "ORB_MID": "ORB",
}

# Width sweep in ATR fractions (half-width each side of a level center).
WIDTH_ATR_FRACS = (0.10, 0.25, 0.50, 1.00, 1.50)

# OB / FVG geometry (OBJECTIVE operationalizations — ICT discretionary labels are [UNVERIFIED])
OB_IMPULSE_ATR = 1.5           # displacement magnitude
OB_IMPULSE_BARS = 5            # within this many bars after the opposing candle
OB_MAX_PER_SESSION = 8         # cap density so one trend day does not flood n
FVG_MIN_GAP_ATR = 0.15
FVG_MAX_PER_SESSION = 12

# PASS: real must beat placebo; high kill rate is success.
PASS = {
    "min_events_per_arm": 150,
    "min_win_rate_edge_pp": 0.05,   # real - placebo win rate among resolved
    "min_halves_agreeing": 2,       # both date-halves show real >= placebo
}

STUDY = "liquidity_synthesis_experiments_v1"


# ── Data access (LP-01 pattern) ──────────────────────────────────────────────

def _rows(con: sqlite3.Connection, ticker: str) -> list[dict]:
    """LP-01 bar shape: `datetime` ms is required by liquidity_value_engine._bars_to_list."""
    # session-universe-ok: research experiment; downstream windows are RTH-scoped by the study's own ET filters before any statistic is computed
    q = ("SELECT bar_start_ts_utc, open, high, low, close, volume FROM price_bars_1m "
         "WHERE ticker=? ORDER BY bar_start_ts_utc ASC")
    out = []
    for ts, o, h, l, c, v in con.execute(q, (ticker,)):
        if None in (ts, o, h, l, c):
            continue
        dt = datetime.fromtimestamp(float(ts), ET)
        out.append({
            "dt": dt,
            "datetime": int(float(ts) * 1000),  # engine timestamp authority (same as LP-01)
            "open": float(o), "high": float(h), "low": float(l),
            "close": float(c), "volume": float(v or 0.0),
            "min_of_day": dt.hour * 60 + dt.minute,
        })
    return out


def _levels_for_session(all_bars: list[dict], sess: date) -> dict[str, float]:
    cfg = PlaybookConfig()
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


def _session_atr(sb: list[dict]) -> float:
    """ATR proxy = median RTH bar range for the session (known as session progresses;
    for labeling we use full-session median only for width *definitions of random zones*
    matched within the same session — for barrier targets we use *causal* ATR:
    median range of bars STRICTLY BEFORE the event index (fallback: first 30 bars)."""
    ranges = [b["high"] - b["low"] for b in sb if b["high"] > b["low"]]
    return statistics.median(ranges) if ranges else 0.0


def _causal_atr(sb: list[dict], i: int) -> float:
    window = sb[max(0, i - 30):i] or sb[: max(1, min(30, i + 1))]
    ranges = [b["high"] - b["low"] for b in window if b["high"] > b["low"]]
    return statistics.median(ranges) if ranges else 0.0


# ── Triple barrier (session-bound, no lookahead) ─────────────────────────────

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
    """direction +1 = expect bounce UP (support); -1 = bounce DOWN (resistance).

    WIN: price reaches entry ± k*ATR in the bounce direction BEFORE piercing the
         far edge of the zone by max(0.25*ATR, 0.25*zone_width).
    FAIL: far-edge pierce first.
    TIMEOUT: neither within horizon bars; never crosses session end.
    Entry = touch bar close. Costs ABSENT.
    """
    if atr <= 0 or i >= len(sb) - 1:
        return {"label": None, "reward_risk": None}
    entry = sb[i]["close"]
    width = max(zone_hi - zone_lo, 1e-9)
    pierce = max(0.25 * atr, 0.25 * width)
    target = k * atr
    if direction > 0:
        tp = entry + target
        # far edge for support = below zone_lo
        sl = zone_lo - pierce
    else:
        tp = entry - target
        sl = zone_hi + pierce
    # Fair-method: floor risk at 0.25×ATR so hairline zones cannot manufacture
    # infinite R:R (and explode placebo E). Events already past the stop are SKIP.
    raw_risk = abs(entry - sl)
    if direction > 0 and entry <= sl:
        return {"label": None, "reward_risk": None}
    if direction < 0 and entry >= sl:
        return {"label": None, "reward_risk": None}
    risk = max(raw_risk, 0.25 * atr)
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
    rrs = []
    for e in events:
        lab = e.get(key_label)
        if lab == "WIN":
            wins += 1
            if e.get("reward_risk") is not None:
                rrs.append(float(e["reward_risk"]))
        elif lab == "FAIL":
            fails += 1
            if e.get("reward_risk") is not None:
                rrs.append(0.0)  # lost: EV contribution 0 from win side; tracked separately
        elif lab == "TIMEOUT":
            timeouts += 1
    resolved = wins + fails
    win_rate = wins / resolved if resolved else None
    # E(w) style: P(win among all events incl timeout as non-win) * mean R among wins' R
    # Fair: use P(win|resolved) * mean(R|resolved events) where FAIL R=0, WIN R=rr
    # so E = win_rate * mean_rr_of_wins  (TIMEOUT excluded from EV denominator = resolved)
    mean_rr_win = statistics.fmean([e["reward_risk"] for e in events
                                    if e.get(key_label) == "WIN" and e.get("reward_risk")]) if wins else None
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
        return {"evaluated": False, "reason": "insufficient sessions", "halves_agree": False}
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


# ── Zone helpers ─────────────────────────────────────────────────────────────

def _cluster_levels(
    levels: dict[str, float],
    band: float,
    family_of: dict[str, str] | None = None,
) -> list[dict]:
    """Greedy merge of levels within `band` dollars. Returns zones with tags/families."""
    family_of = family_of or LEVEL_FAMILY
    items = sorted(((n, v) for n, v in levels.items()), key=lambda x: x[1])
    if not items:
        return []
    zones = []
    cur_names = [items[0][0]]
    cur_vals = [items[0][1]]
    for name, val in items[1:]:
        if val - cur_vals[0] <= band:  # width from first in cluster
            cur_names.append(name)
            cur_vals.append(val)
        else:
            lo, hi = min(cur_vals), max(cur_vals)
            # pad to at least band so single-level zones have a width
            mid = 0.5 * (lo + hi)
            half = max(0.5 * (hi - lo), 0.5 * band)
            fams = sorted({family_of.get(n, "OTHER") for n in cur_names})
            zones.append({
                "lo": mid - half, "hi": mid + half, "mid": mid,
                "tags": list(cur_names), "n_tags": len(cur_names),
                "families": fams, "n_families": len(fams),
            })
            cur_names, cur_vals = [name], [val]
    lo, hi = min(cur_vals), max(cur_vals)
    mid = 0.5 * (lo + hi)
    half = max(0.5 * (hi - lo), 0.5 * band)
    fams = sorted({family_of.get(n, "OTHER") for n in cur_names})
    zones.append({
        "lo": mid - half, "hi": mid + half, "mid": mid,
        "tags": list(cur_names), "n_tags": len(cur_names),
        "families": fams, "n_families": len(fams),
    })
    return zones


def _scan_zone_touches(
    sb: list[dict],
    zones: list[dict],
    *,
    ticker: str,
    sess: str,
    atr_session: float,
    start_min: int = ORB_END_MIN,
    meta_extra: dict | None = None,
) -> list[dict]:
    """First-touch with re-arm; direction from prior close vs zone mid."""
    if atr_session <= 0 or not zones:
        return []
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
                direction = 1 if prev_c >= z["mid"] else -1
                atr = _causal_atr(sb, i)
                tb = _triple_barrier(
                    sb, i, direction=direction,
                    zone_lo=z["lo"], zone_hi=z["hi"], atr=atr,
                )
                if tb["label"] is None:
                    continue
                ev = {
                    "ticker": ticker, "session": sess, "i": i,
                    "direction": direction,
                    "zone_lo": z["lo"], "zone_hi": z["hi"],
                    "width": z["hi"] - z["lo"],
                    "n_tags": z.get("n_tags"), "n_families": z.get("n_families"),
                    "families": z.get("families"), "tags": z.get("tags"),
                    "label": tb["label"], "reward_risk": tb["reward_risk"],
                    "bars": tb.get("bars"),
                }
                if meta_extra:
                    ev.update(meta_extra)
                events.append(ev)
            elif not inside:
                mid = z["mid"]
                if abs(b["close"] - mid) > rearm:
                    armed[zi] = True
    return events


# ── Experiment A: family-count vs tag-count ──────────────────────────────────

def exp_A_family_count(sessions: list[dict], rnd: random.Random) -> dict:
    """Does n_families≥2 beat n_families==1 at zone touch? Placebo = shuffled families."""
    band_pct = 0.0015  # 0.15% of price — fixed narrow band
    real_events: list[dict] = []
    placebo_events: list[dict] = []
    for S in sessions:
        sb, lv, tk, sess = S["sb"], S["levels"], S["ticker"], S["session"]
        if not lv:
            continue
        ref = statistics.fmean(lv.values())
        band = ref * band_pct
        zones = _cluster_levels(lv, band)
        atr = _session_atr(sb)
        real_events.extend(_scan_zone_touches(sb, zones, ticker=tk, sess=sess, atr_session=atr))

        # Placebo: same prices, shuffled family labels → re-cluster under fake families
        names = list(lv.keys())
        fams = [LEVEL_FAMILY[n] for n in names]
        rnd.shuffle(fams)
        fake_map = dict(zip(names, fams))
        zones_p = _cluster_levels(lv, band, family_of=fake_map)
        # Preserve structure but tag with placebo family counts from shuffled map
        placebo_events.extend(
            _scan_zone_touches(sb, zones_p, ticker=tk, sess=sess, atr_session=atr,
                               meta_extra={"arm": "placebo_shuffle_families"})
        )

    def bucket(events, pred):
        return _summarize_labels([e for e in events if pred(e)])

    real_hi = bucket(real_events, lambda e: (e.get("n_families") or 0) >= 2)
    real_lo = bucket(real_events, lambda e: (e.get("n_families") or 0) == 1)
    # Placebo "≥2 families" under shuffled labels
    p_hi = bucket(placebo_events, lambda e: (e.get("n_families") or 0) >= 2)
    p_lo = bucket(placebo_events, lambda e: (e.get("n_families") or 0) == 1)

    # Tag-count comparison on REAL arm only (descriptive) + family edge vs placebo hi
    by_tags = {}
    for tmin, tmax, name in ((1, 1, "tags_1"), (2, 2, "tags_2"), (3, 99, "tags_ge3")):
        by_tags[name] = bucket(real_events, lambda e, a=tmin, b=tmax: a <= (e.get("n_tags") or 0) <= b)

    # Primary test: family≥2 real vs family≥2 placebo (shuffled families)
    oos = _date_half_edge(
        [e for e in real_events if (e.get("n_families") or 0) >= 2],
        [e for e in placebo_events if (e.get("n_families") or 0) >= 2],
    )
    # Secondary: family≥2 vs family==1 on real (no placebo) — informational
    fam_edge = None
    if real_hi["win_rate"] is not None and real_lo["win_rate"] is not None:
        fam_edge = real_hi["win_rate"] - real_lo["win_rate"]

    verdict = _verdict(real_hi, p_hi, oos)
    # Also require family≥2 beats family==1 on real (operator claim substance)
    if verdict == "PASS" and (fam_edge is None or fam_edge < PASS["min_win_rate_edge_pp"]):
        verdict = "FAIL"

    return {
        "id": "A_family_count",
        "question": ("Does zone touch with n_families≥2 beat (i) n_families==1 and "
                     "(ii) placebo zones built with shuffled family labels?"),
        "band_pct": band_pct,
        "n_real_events": len(real_events),
        "n_placebo_events": len(placebo_events),
        "real_families_ge2": real_hi,
        "real_families_eq1": real_lo,
        "placebo_families_ge2": p_hi,
        "placebo_families_eq1": p_lo,
        "real_by_tag_count": by_tags,
        "family_ge2_minus_eq1_win_rate": fam_edge,
        "oos": oos,
        "verdict": verdict,
        "note": ("Causal families only: PRIOR_DAY, OVERNIGHT, ORB. "
                 "TODAY_VP/VWAP/GAMMA excluded (lookahead or BLOCKED)."),
    }


# ── Experiment B: width / E(w) ───────────────────────────────────────────────

def exp_B_width_ev(sessions: list[dict], rnd: random.Random) -> dict:
    """Bounce win-rate vs E by width; random-center placebo. Tsinaslanidis trap check."""
    by_w_real: dict[float, list] = {w: [] for w in WIDTH_ATR_FRACS}
    by_w_placebo: dict[float, list] = {w: [] for w in WIDTH_ATR_FRACS}

    for S in sessions:
        sb, lv, tk, sess = S["sb"], S["levels"], S["ticker"], S["session"]
        if not lv:
            continue
        atr = _session_atr(sb)
        if atr <= 0:
            continue
        # Real: each causal level as center
        for wfrac in WIDTH_ATR_FRACS:
            half = wfrac * atr
            zones = [{"lo": v - half, "hi": v + half, "mid": v,
                      "n_tags": 1, "n_families": 1, "tags": [name], "families": [LEVEL_FAMILY[name]]}
                     for name, v in lv.items()]
            by_w_real[wfrac].extend(
                _scan_zone_touches(sb, zones, ticker=tk, sess=sess, atr_session=atr,
                                   meta_extra={"width_atr_frac": wfrac, "arm": "real"})
            )
            # Placebo: same count, random centers inside session RTH range
            lo_s = min(b["low"] for b in sb)
            hi_s = max(b["high"] for b in sb)
            pz = []
            for _ in lv:
                c = rnd.uniform(lo_s, hi_s)
                pz.append({"lo": c - half, "hi": c + half, "mid": c,
                           "n_tags": 1, "n_families": 1, "tags": ["RAND"], "families": ["RAND"]})
            by_w_placebo[wfrac].extend(
                _scan_zone_touches(sb, pz, ticker=tk, sess=sess, atr_session=atr,
                                   meta_extra={"width_atr_frac": wfrac, "arm": "placebo"})
            )

    table = []
    for w in WIDTH_ATR_FRACS:
        rs = _summarize_labels(by_w_real[w])
        ps = _summarize_labels(by_w_placebo[w])
        edge = None
        if rs["win_rate"] is not None and ps["win_rate"] is not None:
            edge = rs["win_rate"] - ps["win_rate"]
        table.append({
            "width_atr_frac": w,
            "real": rs,
            "placebo": ps,
            "win_rate_edge": edge,
            "E_real": rs["E"],
            "E_placebo": ps["E"],
        })

    # Tsinaslanidis trap: hit/win rate rises with width while E does not improve vs placebo
    win_rates = [t["real"]["win_rate"] for t in table if t["real"]["win_rate"] is not None]
    e_vals = [t["real"]["E"] for t in table if t["real"]["E"] is not None]
    trap = False
    if len(win_rates) >= 3 and len(e_vals) >= 3:
        # monotonic-ish rise in win_rate from narrow→wide AND E at widest <= E at mid
        trap = (win_rates[-1] > win_rates[0] + 0.02) and (e_vals[-1] <= max(e_vals) * 0.98)

    # PASS if some width has real beating placebo on win_rate AND E, with n, and OOS
    best = None
    verdict = "FAIL"
    for t in table:
        rs, ps = t["real"], t["placebo"]
        oos = _date_half_edge(by_w_real[t["width_atr_frac"]], by_w_placebo[t["width_atr_frac"]])
        v = _verdict(rs, ps, oos)
        # also require E_real > E_placebo when both present
        if v == "PASS" and rs["E"] is not None and ps["E"] is not None and rs["E"] > ps["E"]:
            verdict = "PASS"
            best = t["width_atr_frac"]
            break

    return {
        "id": "B_width_Ev",
        "question": ("As zone width rises, does bounce win-rate rise while E(w)=P(win)×R "
                     "fails to beat random-center zones? (Tsinaslanidis discipline)"),
        "table": table,
        "tsinaslanidis_trap_flag": trap,
        "best_width_passing": best,
        "verdict": verdict,
        "costs": "ABSENT",
    }


# ── Experiment C: gamma regime — availability gate ───────────────────────────

def exp_C_gamma_gate(con: sqlite3.Connection, tickers: list[str]) -> dict:
    rows = list(con.execute(
        "SELECT ticker, COUNT(*), MIN(et_date), MAX(et_date) FROM option_chain_morning_full "
        "WHERE ticker IN ({}) GROUP BY ticker ORDER BY 1".format(
            ",".join("?" * len(tickers))),
        tickers,
    ))
    by_tk = {r[0]: {"n_days": r[1], "min": r[2], "max": r[3]} for r in rows}
    n_total = sum(v["n_days"] for v in by_tk.values())
    # Need enough days to stratify barrier events; <20 sessions per sentinel → BLOCKED
    min_days = min((by_tk.get(t, {}).get("n_days", 0) for t in tickers), default=0)
    blocked = min_days < 20
    return {
        "id": "C_gamma_regime",
        "question": ("Do structure-zone barrier outcomes differ under LONG vs SHORT gamma "
                     "(morning_full terrain sign)?"),
        "morning_full_coverage": by_tk,
        "n_ticker_days": n_total,
        "min_days_per_ticker": min_days,
        "threshold_days": 20,
        "status": "BLOCKED" if blocked else "RUNNABLE",
        "reason": (
            f"option_chain_morning_full has only {min_days} days on the thinnest sentinel "
            f"(need ≥20 for regime-stratified barrier inference). Bars span ~100 RTH sessions; "
            f"joining would shrink the sample into an underpowered mixture. No invented gamma."
            if blocked else "coverage sufficient — not executed in this pack (A/B/D/E priority)."
        ),
        "verdict": "BLOCKED" if blocked else "SKIPPED",
    }


# ── Experiment D: objective Order Blocks ─────────────────────────────────────

def _detect_order_blocks(sb: list[dict]) -> list[dict]:
    """OBJECTIVE OB (not ICT discretion):

    Bullish OB: last bearish candle (close < open) immediately before a forward
    displacement where close[i+k] >= close[i] + OB_IMPULSE_ATR * atr_causal,
    for some k in 1..OB_IMPULSE_BARS. Zone = that bearish candle's [low, high].
    Bearish OB: mirror with bullish candle + down displacement.

    Formation index = i+k (impulse confirmation bar). Touches only after formation.
    [UNVERIFIED] that this equals any vendor 'order block' product.
    """
    out = []
    n = len(sb)
    for i in range(1, n - 1):
        if sb[i]["min_of_day"] < RTH_OPEN_MIN or sb[i]["min_of_day"] >= RTH_CLOSE_MIN - OB_IMPULSE_BARS:
            continue
        atr = _causal_atr(sb, i)
        if atr <= 0:
            continue
        need = OB_IMPULSE_ATR * atr
        o, h, l, c = sb[i]["open"], sb[i]["high"], sb[i]["low"], sb[i]["close"]
        bearish = c < o
        bullish = c > o
        if not (bearish or bullish):
            continue
        for k in range(1, OB_IMPULSE_BARS + 1):
            j = i + k
            if j >= n:
                break
            if bearish and sb[j]["close"] >= c + need:
                out.append({
                    "form_i": j, "lo": l, "hi": h, "mid": 0.5 * (l + h),
                    "direction": 1, "kind": "bull_ob",
                    "n_tags": 1, "n_families": 1, "tags": ["OB_BULL"], "families": ["OB"],
                })
                break
            if bullish and sb[j]["close"] <= c - need:
                out.append({
                    "form_i": j, "lo": l, "hi": h, "mid": 0.5 * (l + h),
                    "direction": -1, "kind": "bear_ob",
                    "n_tags": 1, "n_families": 1, "tags": ["OB_BEAR"], "families": ["OB"],
                })
                break
    # Dedup overlapping / keep earliest per direction cluster
    out.sort(key=lambda z: z["form_i"])
    return out


def _scan_formed_zones(
    sb: list[dict],
    zones: list[dict],
    *,
    ticker: str,
    sess: str,
    atr_session: float,
    max_keep: int,
) -> list[dict]:
    """Touch scan for zones that become valid only after form_i; fixed bounce direction."""
    if atr_session <= 0 or not zones:
        return []
    # Limit per session by earliest formation
    zones = zones[:max_keep]
    rearm = atr_session * REARM_ATR_MULT
    armed = [True] * len(zones)
    events = []
    for i, b in enumerate(sb):
        if b["min_of_day"] < ORB_END_MIN:
            continue
        for zi, z in enumerate(zones):
            if i <= z["form_i"]:
                continue
            inside = b["low"] <= z["hi"] and b["high"] >= z["lo"]
            if inside and armed[zi]:
                armed[zi] = False
                atr = _causal_atr(sb, i)
                tb = _triple_barrier(
                    sb, i, direction=int(z["direction"]),
                    zone_lo=z["lo"], zone_hi=z["hi"], atr=atr,
                )
                if tb["label"] is None:
                    continue
                events.append({
                    "ticker": ticker, "session": sess, "i": i,
                    "kind": z.get("kind"), "direction": z["direction"],
                    "zone_lo": z["lo"], "zone_hi": z["hi"],
                    "width": z["hi"] - z["lo"],
                    "label": tb["label"], "reward_risk": tb["reward_risk"],
                    "bars": tb.get("bars"),
                })
            elif not inside and abs(b["close"] - z["mid"]) > rearm:
                armed[zi] = True
    return events


def exp_D_order_blocks(sessions: list[dict], rnd: random.Random) -> dict:
    real_events: list[dict] = []
    placebo_events: list[dict] = []
    n_zones = 0
    for S in sessions:
        sb, tk, sess = S["sb"], S["ticker"], S["session"]
        atr = _session_atr(sb)
        if atr <= 0:
            continue
        obs = _detect_order_blocks(sb)
        n_zones += len(obs)
        real_events.extend(
            _scan_formed_zones(sb, obs, ticker=tk, sess=sess, atr_session=atr,
                               max_keep=OB_MAX_PER_SESSION)
        )
        # Placebo: random same-width zones from random RTH bars, random direction
        pz = []
        for z in obs[:OB_MAX_PER_SESSION]:
            w = z["hi"] - z["lo"]
            bi = rnd.randrange(0, max(1, len(sb) - HORIZON_MIN - 1))
            mid = 0.5 * (sb[bi]["high"] + sb[bi]["low"])
            pz.append({
                "form_i": bi, "lo": mid - 0.5 * w, "hi": mid + 0.5 * w, "mid": mid,
                "direction": 1 if rnd.random() < 0.5 else -1,
                "kind": "rand_ob",
            })
        placebo_events.extend(
            _scan_formed_zones(sb, pz, ticker=tk, sess=sess, atr_session=atr,
                               max_keep=OB_MAX_PER_SESSION)
        )

    rs = _summarize_labels(real_events)
    ps = _summarize_labels(placebo_events)
    oos = _date_half_edge(real_events, placebo_events)
    return {
        "id": "D_order_block",
        "question": ("Do objective order-block zones beat random same-width zones on "
                     "triple-barrier bounce labels?"),
        "definition": {
            "bullish_ob": ("last bearish candle before close displacement ≥ "
                           f"{OB_IMPULSE_ATR}×causal_ATR within {OB_IMPULSE_BARS} bars; "
                           "zone=[L,H] of that candle"),
            "bearish_ob": "mirror",
            "ict_disclaimer": "[UNVERIFIED] operationalization — not vendor ICT equivalence",
        },
        "n_zones_detected": n_zones,
        "n_real_events": len(real_events),
        "n_placebo_events": len(placebo_events),
        "real": rs,
        "placebo": ps,
        "win_rate_edge": (None if rs["win_rate"] is None or ps["win_rate"] is None
                          else rs["win_rate"] - ps["win_rate"]),
        "oos": oos,
        "verdict": _verdict(rs, ps, oos),
        "costs": "ABSENT",
    }


# ── Experiment E: objective FVG ──────────────────────────────────────────────

def _detect_fvgs(sb: list[dict]) -> list[dict]:
    """OBJECTIVE FVG (3-candle imbalance):

    Bullish FVG at i (i>=2): low[i] > high[i-2]; zone = [high[i-2], low[i]].
    Bearish FVG: high[i] < low[i-2]; zone = [high[i], low[i-2]].
    Min gap ≥ FVG_MIN_GAP_ATR × causal ATR. Formation index = i.
    Bounce direction: bull FVG → +1 (support on retest); bear → -1.
    [UNVERIFIED] vs discretionary ICT FVG trade rules (entry/mitigation folklore).
    """
    out = []
    for i in range(2, len(sb)):
        if sb[i]["min_of_day"] < RTH_OPEN_MIN or sb[i]["min_of_day"] >= RTH_CLOSE_MIN:
            continue
        atr = _causal_atr(sb, i)
        if atr <= 0:
            continue
        min_gap = FVG_MIN_GAP_ATR * atr
        # bull
        if sb[i]["low"] > sb[i - 2]["high"]:
            lo, hi = sb[i - 2]["high"], sb[i]["low"]
            if hi - lo >= min_gap:
                out.append({
                    "form_i": i, "lo": lo, "hi": hi, "mid": 0.5 * (lo + hi),
                    "direction": 1, "kind": "bull_fvg",
                })
        if sb[i]["high"] < sb[i - 2]["low"]:
            lo, hi = sb[i]["high"], sb[i - 2]["low"]
            if hi - lo >= min_gap:
                out.append({
                    "form_i": i, "lo": lo, "hi": hi, "mid": 0.5 * (lo + hi),
                    "direction": -1, "kind": "bear_fvg",
                })
    out.sort(key=lambda z: z["form_i"])
    return out


def exp_E_fvg(sessions: list[dict], rnd: random.Random) -> dict:
    real_events: list[dict] = []
    placebo_events: list[dict] = []
    n_zones = 0
    for S in sessions:
        sb, tk, sess = S["sb"], S["ticker"], S["session"]
        atr = _session_atr(sb)
        if atr <= 0:
            continue
        fvgs = _detect_fvgs(sb)
        n_zones += len(fvgs)
        real_events.extend(
            _scan_formed_zones(sb, fvgs, ticker=tk, sess=sess, atr_session=atr,
                               max_keep=FVG_MAX_PER_SESSION)
        )
        # Placebo: random same-width zones
        pz = []
        for z in fvgs[:FVG_MAX_PER_SESSION]:
            w = z["hi"] - z["lo"]
            bi = rnd.randrange(2, max(3, len(sb) - HORIZON_MIN - 1))
            mid = 0.5 * (sb[bi]["high"] + sb[bi]["low"])
            pz.append({
                "form_i": bi, "lo": mid - 0.5 * w, "hi": mid + 0.5 * w, "mid": mid,
                "direction": 1 if rnd.random() < 0.5 else -1,
                "kind": "rand_fvg",
            })
        placebo_events.extend(
            _scan_formed_zones(sb, pz, ticker=tk, sess=sess, atr_session=atr,
                               max_keep=FVG_MAX_PER_SESSION)
        )

    rs = _summarize_labels(real_events)
    ps = _summarize_labels(placebo_events)
    oos = _date_half_edge(real_events, placebo_events)
    return {
        "id": "E_fvg",
        "question": ("Do objective 3-candle FVG zones beat random same-width zones on "
                     "triple-barrier bounce labels?"),
        "definition": {
            "bull_fvg": "low[i] > high[i-2]; zone=[high[i-2], low[i]]; min gap "
                        f"{FVG_MIN_GAP_ATR}×ATR",
            "bear_fvg": "high[i] < low[i-2]; zone=[high[i], low[i-2]]",
            "ict_disclaimer": "[UNVERIFIED] operationalization — not ICT course equivalence",
        },
        "n_zones_detected": n_zones,
        "n_real_events": len(real_events),
        "n_placebo_events": len(placebo_events),
        "real": rs,
        "placebo": ps,
        "win_rate_edge": (None if rs["win_rate"] is None or ps["win_rate"] is None
                          else rs["win_rate"] - ps["win_rate"]),
        "oos": oos,
        "verdict": _verdict(rs, ps, oos),
        "costs": "ABSENT",
    }


# ── Session pack + main ──────────────────────────────────────────────────────

def _load_sessions(
    tickers: list[str], limit_sessions: int | None,
) -> tuple[list[dict], dict, dict]:
    con = sqlite3.connect(f"file:{REPO / 'data' / 'ed_console.db'}?mode=ro", uri=True)
    sessions: list[dict] = []
    bar_counts = {}
    date_min, date_max = None, None
    for tk in tickers:
        bars = _rows(con, tk)
        bar_counts[tk] = len(bars)
        by_sess: dict[date, list[dict]] = {}
        for b in bars:
            if RTH_OPEN_MIN <= b["min_of_day"] < RTH_CLOSE_MIN:
                by_sess.setdefault(b["dt"].date(), []).append(b)
        sess_dates = sorted(by_sess)
        if limit_sessions:
            sess_dates = sess_dates[-limit_sessions:]
        for sess in sess_dates:
            sb = by_sess[sess]
            if len(sb) < HORIZON_MIN + 40:
                continue
            lv = _levels_for_session(bars, sess)
            sessions.append({
                "ticker": tk, "session": sess.isoformat(), "sb": sb, "levels": lv,
            })
            if date_min is None or sess < date_min:
                date_min = sess
            if date_max is None or sess > date_max:
                date_max = sess
    meta = {
        "tickers": tickers,
        "n_sessions": len(sessions),
        "bar_counts": bar_counts,
        "date_min": date_min.isoformat() if date_min else None,
        "date_max": date_max.isoformat() if date_max else None,
        "exact_bar_counts_sql": "SELECT ticker, COUNT(*) FROM price_bars_1m GROUP BY ticker",
    }
    gamma = exp_C_gamma_gate(con, tickers)
    con.close()
    return sessions, meta, gamma


def run(tickers: list[str], limit_sessions: int | None) -> dict:
    sessions, meta, gamma = _load_sessions(tickers, limit_sessions)
    rnd_a = random.Random(SEED)
    rnd_b = random.Random(SEED + 1)
    rnd_d = random.Random(SEED + 2)
    rnd_e = random.Random(SEED + 3)

    A = exp_A_family_count(sessions, rnd_a)
    B = exp_B_width_ev(sessions, rnd_b)
    D = exp_D_order_blocks(sessions, rnd_d)
    E = exp_E_fvg(sessions, rnd_e)

    overall = {
        "A": A["verdict"], "B": B["verdict"], "C": gamma["verdict"],
        "D": D["verdict"], "E": E["verdict"],
    }
    any_pass = any(v == "PASS" for v in overall.values())
    return {
        "study": STUDY,
        "mission_class": "Find & Prove — DISCUSSION/EXPERIMENT only",
        "decision_path_effect": "NONE — Decide WAIT; no admission",
        "lp01_touch_magnitude": "FAIL locked — not reopened",
        "label": {
            "type": "triple_barrier",
            "horizon_min": HORIZON_MIN,
            "k_atr": K_ATR,
            "session_bound": True,
            "costs": "ABSENT",
        },
        "pass_criteria": PASS,
        "sample": meta,
        "experiments": {"A": A, "B": B, "C": gamma, "D": D, "E": E},
        "verdicts": overall,
        "pack_verdict": "ANY_PASS" if any_pass else "ALL_FAIL_OR_BLOCKED",
        "seed": SEED,
    }


def _fmt_rate(x) -> str:
    return "—" if x is None else f"{100 * x:.1f}%"


def _fmt(x, p=3) -> str:
    return "—" if x is None else f"{x:.{p}f}"


def _markdown(res: dict) -> str:
    s = res["sample"]
    L = [
        "# Liquidity synthesis experiments v1",
        "",
        f"**Pack verdict: {res['pack_verdict']}**",
        "",
        f"- Mission: `{res['mission_class']}`",
        f"- Decision path: {res['decision_path_effect']}",
        f"- LP-01 touch→magnitude: {res['lp01_touch_magnitude']}",
        f"- Tickers: `{', '.join(s['tickers'])}`",
        f"- Sessions: **{s['n_sessions']}** (exact pack count)",
        f"- Date range: `{s['date_min']}` → `{s['date_max']}`",
        "- Bars loaded: " + ", ".join(f"{k}={v}" for k, v in s["bar_counts"].items()),
        f"- Labels: triple-barrier, horizon={res['label']['horizon_min']}m, "
        f"k={res['label']['k_atr']}×ATR, costs **{res['label']['costs']}**",
        f"- Seed: `{res['seed']}`",
        "",
        "## AGENTS.md admission",
        "",
        "| Field | Answer |",
        "|---|---|",
        "| MISSION_CLASS | Find & Prove — offline experiments |",
        "| GAP | LP-01 kill left richer confluence/OB/FVG/width questions untested |",
        "| SMALLEST_COMPLETE_CHANGE | `tools/liquidity_synthesis_experiments_v1.py` + this report |",
        "| MINIMUM_SUFFICIENT_EVIDENCE | Same-turn harness output; placebos; exact n |",
        "| DECISION_PATH_EFFECT | None — WAIT |",
        "| WHY_NOW | Operator asked experiment-only follow-up from synthesis research |",
        "| TASK_ADMISSION | Admitted as research/backtest only |",
        "",
        "## Pre-registered PASS",
        "",
        "```",
        json.dumps(PASS, indent=2),
        "```",
        "",
        "High kill rate is success. ICT/SMC names are candidate geometry only.",
        "",
        "## Verdicts",
        "",
        "| Exp | Verdict |",
        "|---|---|",
    ]
    for k, v in res["verdicts"].items():
        L.append(f"| {k} | **{v}** |")

    A = res["experiments"]["A"]
    B = res["experiments"]["B"]
    D = res["experiments"]["D"]
    E = res["experiments"]["E"]
    L += [
        "",
        "## Key findings (PROVEN this run)",
        "",
        f"1. **A family-count — {A['verdict']}.** "
        f"fam>=2 win_rate={_fmt_rate(A['real_families_ge2']['win_rate'])} "
        f"(resolved={A['real_families_ge2']['resolved']}) vs fam=1 "
        f"{_fmt_rate(A['real_families_eq1']['win_rate'])}; "
        f"delta={_fmt_rate(A['family_ge2_minus_eq1_win_rate'])}. "
        f"Placebo shuffled fam>=2={_fmt_rate(A['placebo_families_ge2']['win_rate'])}.",
        f"2. **B width/E(w) — {B['verdict']}.** "
        f"Tsinaslanidis trap={B['tsinaslanidis_trap_flag']}. "
        f"Width 0.10→1.50×ATR: win_rate "
        f"{_fmt_rate(B['table'][0]['real']['win_rate'])}→"
        f"{_fmt_rate(B['table'][-1]['real']['win_rate'])}; E "
        f"{_fmt(B['table'][0]['real']['E'])}→{_fmt(B['table'][-1]['real']['E'])}.",
        f"3. **C gamma — {res['experiments']['C']['verdict']}.** "
        f"{res['experiments']['C']['reason']}",
        f"4. **D OB — {D['verdict']}.** real={_fmt_rate(D['real']['win_rate'])} vs "
        f"placebo={_fmt_rate(D['placebo']['win_rate'])} "
        f"(edge={_fmt_rate(D['win_rate_edge'])}).",
        f"5. **E FVG — {E['verdict']}.** real={_fmt_rate(E['real']['win_rate'])} vs "
        f"placebo={_fmt_rate(E['placebo']['win_rate'])} "
        f"(edge={_fmt_rate(E['win_rate_edge'])}).",
        "",
        "## A — Family-count vs tag-count",
        "",
        f"**Verdict: {A['verdict']}**",
        "",
        f"> {A['question']}",
        "",
        f"- Band: {A['band_pct']*100:.2f}% of price",
        f"- Real events: {A['n_real_events']}; placebo (shuffled families): {A['n_placebo_events']}",
        f"- {A['note']}",
        "",
        "| bucket | n | resolved | win_rate | E |",
        "|---|---|---|---|---|",
        f"| real families≥2 | {A['real_families_ge2']['n']} | {A['real_families_ge2']['resolved']} | "
        f"{_fmt_rate(A['real_families_ge2']['win_rate'])} | {_fmt(A['real_families_ge2']['E'])} |",
        f"| real families=1 | {A['real_families_eq1']['n']} | {A['real_families_eq1']['resolved']} | "
        f"{_fmt_rate(A['real_families_eq1']['win_rate'])} | {_fmt(A['real_families_eq1']['E'])} |",
        f"| placebo families≥2 | {A['placebo_families_ge2']['n']} | {A['placebo_families_ge2']['resolved']} | "
        f"{_fmt_rate(A['placebo_families_ge2']['win_rate'])} | {_fmt(A['placebo_families_ge2']['E'])} |",
        f"| Δ(fam≥2 − fam=1) win_rate | | | {_fmt_rate(A['family_ge2_minus_eq1_win_rate'])} | |",
        "",
        "### By raw tag count (real arm, descriptive)",
        "",
        "| bucket | n | win_rate | E |",
        "|---|---|---|---|",
    ]
    for name, row in A["real_by_tag_count"].items():
        L.append(f"| {name} | {row['n']} | {_fmt_rate(row['win_rate'])} | {_fmt(row['E'])} |")

    B = res["experiments"]["B"]
    L += [
        "",
        "## B — Zone width / E(w)",
        "",
        f"**Verdict: {B['verdict']}**",
        "",
        f"> {B['question']}",
        "",
        f"- Tsinaslanidis trap flag: **{B['tsinaslanidis_trap_flag']}**",
        f"- Costs: {B['costs']}",
        "",
        "| width (×ATR) | real n | real win% | real E | placebo win% | placebo E | edge win% |",
        "|---|---|---|---|---|---|---|",
    ]
    for t in B["table"]:
        L.append(
            f"| {t['width_atr_frac']:.2f} | {t['real']['n']} | {_fmt_rate(t['real']['win_rate'])} | "
            f"{_fmt(t['real']['E'])} | {_fmt_rate(t['placebo']['win_rate'])} | "
            f"{_fmt(t['placebo']['E'])} | {_fmt_rate(t['win_rate_edge'])} |"
        )

    C = res["experiments"]["C"]
    L += [
        "",
        "## C — Gamma regime split",
        "",
        f"**Status: {C['status']} — Verdict: {C['verdict']}**",
        "",
        f"> {C['question']}",
        "",
        f"- Reason: {C['reason']}",
        f"- Coverage: `{json.dumps(C['morning_full_coverage'])}`",
        "",
    ]

    for key in ("D", "E"):
        X = res["experiments"][key]
        L += [
            f"## {key} — {X['id']}",
            "",
            f"**Verdict: {X['verdict']}**",
            "",
            f"> {X['question']}",
            "",
            f"- Definition: `{json.dumps(X['definition'])}`",
            f"- Zones detected: {X['n_zones_detected']}",
            f"- Real events: {X['n_real_events']} (resolved {X['real']['resolved']})",
            f"- Placebo events: {X['n_placebo_events']} (resolved {X['placebo']['resolved']})",
            f"- Real win_rate: {_fmt_rate(X['real']['win_rate'])}; "
            f"placebo: {_fmt_rate(X['placebo']['win_rate'])}; "
            f"edge: {_fmt_rate(X['win_rate_edge'])}",
            f"- Real E: {_fmt(X['real']['E'])}; placebo E: {_fmt(X['placebo']['E'])}",
            f"- Costs: {X['costs']}",
            "",
        ]

    L += [
        "## Disposition",
        "",
        f"- Pack: **{res['pack_verdict']}**",
        "- Structure-only. Decide stays WAIT.",
        "- Reproduce: `python tools/liquidity_synthesis_experiments_v1.py`",
        "",
        "## Next (discussion)",
        "",
        "1. Accrue morning_full / terrain days until C is runnable (≥20/ticker).",
        "2. If A stays FAIL with only 3 causal families, retest when TODAY_VP/VWAP can be "
           "constructed *causally* (running VP/VWAP at touch time — new Collect feature).",
        "3. Trigger layer (absorption / rejection wick) nested on the same barrier labels.",
        "4. Do not promote OB/FVG to UI from this pack unless a later run PASSes placebos.",
        "",
    ]
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", default="SPY,QQQ,IWM")
    ap.add_argument("--limit-sessions", type=int, default=None)
    a = ap.parse_args()
    tickers = [t.strip().upper() for t in a.tickers.split(",") if t.strip()]
    res = run(tickers, a.limit_sessions)
    out = REPO / "reports"
    out.mkdir(exist_ok=True)
    (out / f"{STUDY}.json").write_text(json.dumps(res, indent=2, default=str), encoding="utf-8")
    (out / f"{STUDY}.md").write_text(_markdown(res), encoding="utf-8")
    print(f"pack={res['pack_verdict']} sessions={res['sample']['n_sessions']}")
    for k, v in res["verdicts"].items():
        print(f"  {k}: {v}")
    print(f"wrote {out / (STUDY + '.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
