"""Conditional cut: liquid sentinels only, split by dealer-gamma regime (net_gamma sign).
Pinning is a LONG-gamma mechanism; if it is real it must show up there and not in short gamma."""
from __future__ import annotations

from typing import Any

import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve().parents[1]
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

import sqlite3, statistics as st
from datetime import datetime
from time_et import ET, RTH_END_MINS, RTH_START_MINS
con = sqlite3.connect("file:data/ed_console.db?mode=ro", uri=True, timeout=120)
con.row_factory = sqlite3.Row
def et(ts):
    return datetime.fromtimestamp(ts, ET)

closes = {}
for r in con.execute("SELECT ticker, bar_start_ts_utc, close FROM price_bars_1m ORDER BY ticker, bar_start_ts_utc"):
    d = et(r["bar_start_ts_utc"])
    if d.weekday() >= 5: continue
    m = d.hour*60+d.minute
    if RTH_START_MINS <= m < RTH_END_MINS: closes[(r["ticker"], d.date())] = r["close"]

rows = con.execute("""
  SELECT ticker, ts_utc, spot, gamma_pin, call_gamma_wall, put_gamma_wall, net_gamma
  FROM snapshots WHERE spot IS NOT NULL AND gamma_pin IS NOT NULL AND net_gamma IS NOT NULL
  ORDER BY ticker, ts_utc""").fetchall()
obs: dict[tuple[str, Any], tuple[Any, int]] = {}
for r in rows:
    d = et(r["ts_utc"])
    if d.weekday() >= 5: continue
    m = d.hour*60+d.minute
    if abs(m-600) <= 4:
        k = (r["ticker"], d.date())
        if k not in obs or abs(m-600) < obs[k][1]: obs[k] = (r, abs(m-600))

def report(label, sel):
    ae, base, closer, dirhit, n = [], [], 0, 0, 0
    for (tk, day), (r, _) in obs.items():
        if not sel(tk, r): continue
        close = closes.get((tk, day)); lv = r["gamma_pin"]; spot = r["spot"]
        if close is None or not lv or not spot: continue
        if abs(lv-spot)/spot > 0.10: continue
        n += 1
        a, b = abs(close-lv), abs(close-spot)
        ae.append(a/spot*100); base.append(b/spot*100)
        closer += (a < b)
        if (lv-spot) and (close-spot): dirhit += ((lv-spot)>0)==((close-spot)>0)
    if n < 30: print(f"{label:<42}{n:>5}   (insufficient)"); return
    m_ae, m_base = st.median(ae), st.median(base)
    print(f"{label:<42}{n:>5}{m_ae:>9.3f}{m_base:>10.3f}{closer/n*100:>8.1f}%{dirhit/n*100:>7.1f}%{(m_base-m_ae)/m_base*100:>8.1f}%")

SENT = ("SPY","QQQ","IWM")
print(f"{'cut (gamma_pin @10:00 ET -> RTH close)':<42}{'n':>5}{'medAE':>9}{'base':>10}{'closer%':>8}{'dir%':>7}{'skill%':>8}")
print("-"*89)
report("ALL tickers", lambda _tk,_r: True)
report("liquid sentinels SPY/QQQ/IWM", lambda tk,_r: tk in SENT)
report("  sentinels, LONG gamma (net>0)", lambda tk,_r: tk in SENT and r["net_gamma"]>0)
report("  sentinels, SHORT gamma (net<0)", lambda tk,_r: tk in SENT and r["net_gamma"]<0)
report("non-sentinel, LONG gamma", lambda tk,_r: tk not in SENT and r["net_gamma"]>0)
report("non-sentinel, SHORT gamma", lambda tk,_r: tk not in SENT and r["net_gamma"]<0)
print("\nskill% > 0 means the pin beats 'close = spot now'. 50% dir% = coin flip.")
con.close()
