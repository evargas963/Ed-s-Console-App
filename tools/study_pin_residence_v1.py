"""FIND-PIN-RESIDENCE-V1 — pinning tested as its own theory states it.

Pinning does NOT claim price travels toward a strike (that was the mis-specified test of
2026-07-19, which measured direction and correctly found 50.0%). It claims that under
specific conditions price STAYS NEAR the strike and compresses.

Conditions (from the operator's framework): near expiration, strike near spot, dealers
LONG gamma, low realized vol, OI concentrated.

Control: a PLACEBO anchor = spot at observation time. It is equally "near price" but carries
no gamma meaning. If pinning is real, residence around the pin must exceed residence around
the placebo -- and must do so specifically when the conditions hold.
"""
from __future__ import annotations

from typing import Any

import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve().parents[1]
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

import sqlite3, statistics as st
from datetime import datetime
from app.domain.time_et import (
    ET,
    RTH_END_MINS,
    RTH_START_MINS,
    SNAPSHOTS_GAMMA_PIN_TERRAIN_ANALYSIS_TS_UTC,
)

BAND = 0.0025          # +/-0.25% of spot counts as "at the level"
OBS_MIN = 600          # 10:00 ET

con = sqlite3.connect("file:data/ed_console.db?mode=ro", uri=True, timeout=180)
con.row_factory = sqlite3.Row
def et(ts):
    return datetime.fromtimestamp(ts, ET)

bars: dict[tuple[str, Any], list[tuple[int, float, float, float]]] = {}
for r in con.execute("SELECT ticker,bar_start_ts_utc,high,low,close FROM price_bars_1m ORDER BY ticker,bar_start_ts_utc"):
    d = et(r["bar_start_ts_utc"])
    if d.weekday() >= 5: continue
    m = d.hour*60 + d.minute
    if RTH_START_MINS <= m < RTH_END_MINS:
        bars.setdefault((r["ticker"], d.date()), []).append((m, r["high"], r["low"], r["close"]))

obs: dict[tuple[str, Any], tuple[Any, int]] = {}
print(
    "GAMMA_PIN semantic: terrain_total_gamma_pin only "
    f"(ts_utc >= {SNAPSHOTS_GAMMA_PIN_TERRAIN_ANALYSIS_TS_UTC})"
)
print(
    "OUT-OF-SCOPE: snapshots.gamma_pin before 95a61031 is selected-expiry net-GEX peak; "
    "land-to-pad is mixed_until_restart (RC-429). Do not mix eras under one GAMMA_PIN label."
)
for r in con.execute(
    """SELECT ticker,ts_utc,spot,gamma_pin,net_gamma,dte,realized_vol
                        FROM snapshots WHERE spot IS NOT NULL AND gamma_pin IS NOT NULL
                        AND ts_utc >= ?
                        ORDER BY ticker,ts_utc""",
    (SNAPSHOTS_GAMMA_PIN_TERRAIN_ANALYSIS_TS_UTC,),
):
    d = et(r["ts_utc"])
    if d.weekday() >= 5: continue
    m = d.hour*60 + d.minute
    if abs(m-OBS_MIN) <= 4:
        k = (r["ticker"], d.date())
        if k not in obs or abs(m-OBS_MIN) < obs[k][1]: obs[k] = (r, abs(m-OBS_MIN))

rv_all = [r["realized_vol"] for (r,_) in obs.values() if r["realized_vol"] is not None]
rv_lo = st.quantiles(rv_all, n=3)[0] if len(rv_all) > 10 else None

def residence(pts, level, spot):
    """fraction of remaining minutes whose bar straddles/sits inside the band"""
    lo, hi = level*(1-BAND/1), level*(1+BAND/1)
    lo, hi = level - spot*BAND, level + spot*BAND
    n = sum(1 for _,h,l,_ in pts if l <= hi and h >= lo)
    return n/len(pts)

def run(label, sel):
    pin_res, pbo_res, rng, n = [], [], [], 0
    for (tk, day), (r, _) in obs.items():
        pts = bars.get((tk, day))
        if not pts: continue
        rest = [p for p in pts if p[0] >= OBS_MIN]
        if len(rest) < 60: continue
        spot, pin = r["spot"], r["gamma_pin"]
        if not spot or not pin or abs(pin-spot)/spot > 0.10: continue
        if not sel(r, spot, pin): continue
        n += 1
        pin_res.append(residence(rest, pin, spot))
        pbo_res.append(residence(rest, spot, spot))
        hi = max(h for _,h,_,_ in rest); lo = min(l for _,_,l,_ in rest)
        rng.append((hi-lo)/spot*100)
    if n < 30:
        print(f"{label:<46}{n:>5}   (insufficient)"); return
    mp, mb = st.median(pin_res)*100, st.median(pbo_res)*100
    print(f"{label:<46}{n:>5}{mp:>11.1f}%{mb:>12.1f}%{mp-mb:>+10.1f}{st.median(rng):>10.2f}%")

near   = lambda _r,s,p: abs(p-s)/s <= 0.005
lng    = lambda r,_s,_p: (r["net_gamma"] or 0) > 0
short_ = lambda r,_s,_p: (r["net_gamma"] or 0) < 0
exp    = lambda r,_s,_p: r["dte"] is not None and r["dte"] <= 1
lowrv  = lambda r,_s,_p: rv_lo is not None and r["realized_vol"] is not None and r["realized_vol"] <= rv_lo

print(f"{'cut':<46}{'n':>5}{'PIN resid':>12}{'PLACEBO':>12}{'edge':>10}{'day range':>11}")
print("-"*96)
run("ALL ticker-days (unconditional)", lambda _r,_s,_p: True)
run("strike near spot (<=0.5%)", near)
run("+ dealers LONG gamma", lambda r,s,p: near(r,s,p) and lng(r,s,p))
run("+ near expiry (dte<=1)", lambda r,s,p: near(r,s,p) and lng(r,s,p) and exp(r,s,p))
run("+ low realized vol  << FULL PIN SETUP", lambda r,s,p: near(r,s,p) and lng(r,s,p) and exp(r,s,p) and lowrv(r,s,p))
print("-"*96)
run("CONTRAST: near + SHORT gamma", lambda r,s,p: near(r,s,p) and short_(r,s,p))
run("CONTRAST: near+SHORT+expiry", lambda r,s,p: near(r,s,p) and short_(r,s,p) and exp(r,s,p))
print("\nresid = % of remaining RTH minutes price sat within +/-0.25% of the level.")
print("PLACEBO = spot at 10:00 ET (equally near price, no gamma meaning). edge = PIN - PLACEBO.")
print("Pinning is real only if edge > 0 AND grows as the conditions are added.")
con.close()

# ── Follow-up: does dealer gamma predict COMPRESSION beyond low realized vol alone? ──
# The range drop above is confounded: low RV is itself one of the conditions, and RV
# trivially forecasts range. Isolate the gamma contribution WITHIN the low-RV stratum.
def ranges(sel):
    out = []
    for (tk, day), (r, _) in obs.items():
        pts = bars.get((tk, day))
        if not pts: continue
        rest = [p for p in pts if p[0] >= OBS_MIN]
        if len(rest) < 60: continue
        spot, pin = r["spot"], r["gamma_pin"]
        if not spot or not pin or abs(pin-spot)/spot > 0.10: continue
        if not sel(r, spot, pin): continue
        hi = max(h for _,h,_,_ in rest); lo = min(l for _,_,l,_ in rest)
        out.append((hi-lo)/spot*100)
    return out

print("\n\nDOES DEALER GAMMA ADD ANYTHING BEYOND LOW REALIZED VOL?")
print(f"{'stratum':<46}{'n':>5}{'median day range':>19}")
print("-"*70)
for lbl, sel in (
    ("low RV, LONG gamma",  lambda r,s,p: lowrv(r,s,p) and lng(r,s,p)),
    ("low RV, SHORT gamma", lambda r,s,p: lowrv(r,s,p) and short_(r,s,p)),
    ("high RV, LONG gamma", lambda r,s,p: not lowrv(r,s,p) and lng(r,s,p)),
    ("high RV, SHORT gamma",lambda r,s,p: not lowrv(r,s,p) and short_(r,s,p)),
):
    v = ranges(sel)
    print(f"{lbl:<46}{len(v):>5}{(st.median(v) if len(v)>=30 else float('nan')):>18.2f}%")
print("\nIf LONG vs SHORT gamma ranges match within a RV stratum, gamma adds nothing")
print("beyond realized vol and the compression finding is just 'quiet days are quiet'.")
