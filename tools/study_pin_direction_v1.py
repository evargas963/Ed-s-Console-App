"""FIND-PIN-DIRECTION-V1: does gamma_pin (or another level) predict the RTH close,
measured against the random-walk baseline (close ~= spot at observation time)?"""
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
    snapshots_gamma_pin_is_terrain_analysis_safe,
)

con = sqlite3.connect("file:data/ed_console.db?mode=ro", uri=True, timeout=120)
con.row_factory = sqlite3.Row

LEVELS = ["gamma_pin", "oi_center", "gamma_inflection", "wall_mid", "vanna_mid"]

def et(ts):
    return datetime.fromtimestamp(ts, ET)

# ---- day close from price bars (last RTH bar) ----
closes = {}
for r in con.execute("SELECT ticker, bar_start_ts_utc, close FROM price_bars_1m ORDER BY ticker, bar_start_ts_utc"):
    d = et(r["bar_start_ts_utc"])
    if d.weekday() >= 5: continue
    m = d.hour*60 + d.minute
    if not (RTH_START_MINS <= m < RTH_END_MINS): continue
    closes[(r["ticker"], d.date())] = r["close"]
print(f"ticker-days with an RTH close: {len(closes):,}")
print(
    "GAMMA_PIN semantic: terrain_total_gamma_pin only "
    f"(ts_utc >= {SNAPSHOTS_GAMMA_PIN_TERRAIN_ANALYSIS_TS_UTC}); other levels use full history"
)
print(
    "OUT-OF-SCOPE: snapshots.gamma_pin before 95a61031 is selected-expiry net-GEX peak; "
    "land-to-pad is mixed_until_restart (RC-429). Do not mix eras under one GAMMA_PIN label."
)

# ---- observation snapshots at ~T+5 and ~T+30 after the open ----
rows = con.execute("""
  SELECT ticker, ts_utc, spot, gamma_pin, oi_center, gamma_inflection,
         call_gamma_wall, put_gamma_wall, call_vanna_wall, put_vanna_wall, net_gamma
  FROM snapshots WHERE spot IS NOT NULL ORDER BY ticker, ts_utc
""").fetchall()

obs: dict[tuple[str, Any, str], tuple[Any, int]] = {}   # (ticker, date, tag) -> row
for r in rows:
    d = et(r["ts_utc"])
    if d.weekday() >= 5: continue
    m = d.hour*60 + d.minute
    for tag, target in (("T5", 575), ("T30", 600)):   # 09:35 and 10:00 ET
        if abs(m - target) <= 4:
            k = (r["ticker"], d.date(), tag)
            if k not in obs or abs(m-target) < obs[k][1]:
                obs[k] = (r, abs(m-target))

def level_value(r, name):
    if name == "wall_mid":
        c, p = r["call_gamma_wall"], r["put_gamma_wall"]
        return (c+p)/2 if c and p else None
    if name == "vanna_mid":
        c, p = r["call_vanna_wall"], r["put_vanna_wall"]
        return (c+p)/2 if c and p else None
    return r[name]

for tag in ("T5", "T30"):
    print(f"\n{'='*78}\nOBSERVED AT {tag}  ({'09:35' if tag=='T5' else '10:00'} ET)\n{'='*78}")
    print(f"{'level':<18}{'n':>6}{'medAE':>9}{'base medAE':>12}{'closer%':>9}{'dir%':>8}{'skill':>8}")
    for name in LEVELS:
        ae, base, closer, dirhit = [], [], 0, 0
        n = 0
        for (tk, day, t), (r, _) in obs.items():
            if t != tag: continue
            close = closes.get((tk, day))
            lv = level_value(r, name)
            spot = r["spot"]
            if name == "gamma_pin" and not snapshots_gamma_pin_is_terrain_analysis_safe(
                r["ts_utc"]
            ):
                continue
            if close is None or lv is None or not spot: continue
            if abs(lv - spot)/spot > 0.10: continue          # reject absurd levels
            n += 1
            a, b = abs(close-lv), abs(close-spot)
            ae.append(a/spot*100); base.append(b/spot*100)
            closer += (a < b)
            if (lv-spot) != 0 and (close-spot) != 0:
                dirhit += ((lv-spot) > 0) == ((close-spot) > 0)
        if n < 50: 
            print(f"{name:<18}{n:>6}   (insufficient)"); continue
        m_ae, m_base = st.median(ae), st.median(base)
        skill = (m_base - m_ae)/m_base*100
        print(f"{name:<18}{n:>6}{m_ae:>9.3f}{m_base:>12.3f}{closer/n*100:>8.1f}%{dirhit/n*100:>7.1f}%{skill:>7.1f}%")
    print("  medAE/base in % of spot. closer% = level beat the random-walk baseline.")
    print("  dir% = level pointed the correct side of spot. skill% = error reduction vs baseline (>0 = adds info).")
con.close()
