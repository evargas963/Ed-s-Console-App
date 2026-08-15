"""(a) How soon after the open are levels actually available?
   (b) Is the dealer-gamma regime stable enough intraday to be read once at the open?"""
from __future__ import annotations

from typing import Any

import sys as _sys
from pathlib import Path as _Path
_ROOT = _Path(__file__).resolve().parents[1]
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

import sqlite3, statistics as st
from datetime import datetime
con = sqlite3.connect("file:data/ed_console.db?mode=ro", uri=True, timeout=120)
con.row_factory = sqlite3.Row
def et(ts):
    from time_et import ET  # single ET authority (COH-SA2)
    return datetime.fromtimestamp(ts, ET)

rows = con.execute("""
  SELECT ticker, ts_utc, spot, gamma_pin, call_gamma_wall, put_gamma_wall, net_gamma
  FROM snapshots WHERE spot IS NOT NULL ORDER BY ticker, ts_utc""").fetchall()

first_ok: dict[tuple[str, Any], int] = {}
series: dict[tuple[str, Any], list[tuple[int, float]]] = {}
for r in rows:
    d = et(r["ts_utc"])
    if d.weekday() >= 5: continue
    m = d.hour*60 + d.minute
    if not (570 <= m <= 959): continue
    k = (r["ticker"], d.date())
    usable = r["net_gamma"] is not None and r["call_gamma_wall"] and r["put_gamma_wall"]
    if usable and k not in first_ok:
        first_ok[k] = m - 570                       # minutes after the 09:30 open
    if r["net_gamma"] is not None:
        series.setdefault(k, []).append((m, r["net_gamma"]))

SENT = ("SPY","QQQ","IWM")
for label, sel in (("SPY/QQQ/IWM", lambda tk: tk in SENT), ("all tickers", lambda tk: True)):  # noqa: ARG005
    v = sorted(x for (tk,_),x in first_ok.items() if sel(tk))
    if not v: continue
    def within(n, v=v): return sum(1 for x in v if x <= n)/len(v)*100
    print(f"\nLEVELS READY AFTER THE OPEN — {label}  (n={len(v):,} ticker-days)")
    print(f"  median {st.median(v):.0f} min   |  <=5min {within(5):.0f}%   <=15min {within(15):.0f}%"
          f"   <=30min {within(30):.0f}%   <=60min {within(60):.0f}%")

print("\n\nREGIME STABILITY — does net_gamma keep its sign through the day?")
print(f"{'group':<16}{'ticker-days':>12}{'sign flips/day':>16}{'open sign held to close':>26}")
for label, sel in (("SPY/QQQ/IWM", lambda tk: tk in SENT), ("all tickers", lambda tk: True)):  # noqa: ARG005
    flips, held, n = [], 0, 0
    for (tk, _day), pts in series.items():
        if not sel(tk) or len(pts) < 20: continue
        pts.sort()
        signs = [1 if g > 0 else -1 for _, g in pts if g != 0]
        if len(signs) < 20: continue
        n += 1
        flips.append(sum(1 for a, b in zip(signs, signs[1:], strict=False) if a != b))
        held += signs[0] == signs[-1]
    if n: print(f"{label:<16}{n:>12,}{st.median(flips):>16.0f}{held/n*100:>25.1f}%")
con.close()
