"""FIND-PIN-CHARM-V1 — test the mechanism the LITERATURE names, not the folk version.

Golez & Jackwerth (JFE 2012, "Pinning in the S&P 500 futures") attribute pinning to market
makers' rebalancing of DELTA hedges driven by the TIME DECAY of those hedges -- i.e. charm --
plus early exercise/reselling of ITM options by retail. They also document ANTI-pinning
(price pushed AWAY) around index-option expiration, so the effect is signed, not universal.

Folk GEX pinning instead assumes gamma concentration at a strike. Our residence study already
showed gamma concentration adds nothing over a placebo anchor. This asks the different,
literature-motivated question: does high |charm| pick out the days where a pin edge exists?
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
from time_et import (
    ET,
    RTH_END_MINS,
    RTH_START_MINS,
    SNAPSHOTS_GAMMA_PIN_TERRAIN_ANALYSIS_TS_UTC,
)

BAND, OBS_MIN = 0.0025, 600
con = sqlite3.connect("file:data/ed_console.db?mode=ro", uri=True, timeout=180)
con.row_factory = sqlite3.Row
def et(ts):
    return datetime.fromtimestamp(ts, ET)

bars: dict[tuple[str, Any], list[tuple[int, float, float]]] = {}
for r in con.execute("SELECT ticker,bar_start_ts_utc,high,low FROM price_bars_1m ORDER BY ticker,bar_start_ts_utc"):
    d = et(r["bar_start_ts_utc"])
    if d.weekday() >= 5: continue
    m = d.hour*60 + d.minute
    if RTH_START_MINS <= m < RTH_END_MINS:
        bars.setdefault((r["ticker"], d.date()), []).append((m, r["high"], r["low"]))

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
    """SELECT ticker,ts_utc,spot,gamma_pin,net_gamma,dte,realized_vol,charm_net
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

charms = [abs(r["charm_net"]) for (r,_) in obs.values() if r["charm_net"] is not None]
c_hi = st.quantiles(charms, n=4)[2] if len(charms) > 20 else None   # top quartile |charm|
rv_all = [r["realized_vol"] for (r,_) in obs.values() if r["realized_vol"] is not None]
rv_lo = st.quantiles(rv_all, n=3)[0] if len(rv_all) > 10 else None

def resid(pts, level, spot):
    lo, hi = level - spot*BAND, level + spot*BAND
    return sum(1 for _,h,l in pts if l <= hi and h >= lo)/len(pts)

def run(label, sel):
    pin, pbo, n = [], [], 0
    for (tk, day), (r, _) in obs.items():
        pts = bars.get((tk, day))
        if not pts: continue
        rest = [p for p in pts if p[0] >= OBS_MIN]
        if len(rest) < 60: continue
        spot, p_ = r["spot"], r["gamma_pin"]
        if not spot or not p_ or abs(p_-spot)/spot > 0.10: continue
        if not sel(r, spot, p_): continue
        n += 1
        pin.append(resid(rest, p_, spot)); pbo.append(resid(rest, spot, spot))
    if n < 30: print(f"{label:<48}{n:>5}   (insufficient)"); return
    mp, mb = st.median(pin)*100, st.median(pbo)*100
    print(f"{label:<48}{n:>5}{mp:>11.1f}%{mb:>11.1f}%{mp-mb:>+10.1f}")

near  = lambda _r,s,p: abs(p-s)/s <= 0.005
lng   = lambda r,_s,_p: (r["net_gamma"] or 0) > 0
exp_  = lambda r,_s,_p: r["dte"] is not None and r["dte"] <= 1
lowrv = lambda r,_s,_p: rv_lo is not None and r["realized_vol"] is not None and r["realized_vol"] <= rv_lo
hicharm = lambda r,_s,_p: c_hi is not None and r["charm_net"] is not None and abs(r["charm_net"]) >= c_hi
locharm = lambda r,_s,_p: c_hi is not None and r["charm_net"] is not None and abs(r["charm_net"]) < c_hi

print(f"{'cut':<48}{'n':>5}{'PIN resid':>11}{'PLACEBO':>11}{'edge':>10}")
print("-"*86)
run("full gamma setup (near+long+dte<=1+lowRV)",
    lambda r,s,p: near(r,s,p) and lng(r,s,p) and exp_(r,s,p) and lowrv(r,s,p))
run("  ... AND high |charm|  << literature driver",
    lambda r,s,p: near(r,s,p) and lng(r,s,p) and exp_(r,s,p) and lowrv(r,s,p) and hicharm(r,s,p))
run("  ... AND low |charm|   (control)",
    lambda r,s,p: near(r,s,p) and lng(r,s,p) and exp_(r,s,p) and lowrv(r,s,p) and locharm(r,s,p))
print("-"*86)
run("near strike + high |charm| (charm alone)", lambda r,s,p: near(r,s,p) and hicharm(r,s,p))
run("near strike + low |charm|  (control)",     lambda r,s,p: near(r,s,p) and locharm(r,s,p))
print("\nedge = PIN - PLACEBO residence. Charm is the driver named by Golez & Jackwerth (JFE 2012).")
print("If charm were the missing ingredient, edge must turn POSITIVE in the high-charm cuts.")
con.close()
