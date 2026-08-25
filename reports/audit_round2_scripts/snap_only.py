"""Snapshot-only truth (audit round 2, 2026-08-25): live writes per ticker/day, cadence
gaps, absent-ticker forensics. Read-only; run from repo root; ED_CONSOLE_DB_RO overrides."""
import os
import sqlite3
import statistics
from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
DB = os.environ.get("ED_CONSOLE_DB_RO", "file:data/ed_console.db?mode=ro")
conn = sqlite3.connect(DB, uri=True)
conn.row_factory = sqlite3.Row
DAYS = ["2026-08-18", "2026-08-19", "2026-08-20", "2026-08-21", "2026-08-24"]
SENT = {"SPY", "QQQ", "IWM"}

def et_ts(ds, h, m):
    y, mo, d = map(int, ds.split("-"))
    return datetime(y, mo, d, h, m, tzinfo=ET).timestamp()

def fmt(ts):
    return datetime.fromtimestamp(ts, tz=ET).strftime("%H:%M") if ts else "----"

uni = {r["ticker"]: r["category"] for r in conn.execute(
    "SELECT ticker, category FROM logging_universe "
    "WHERE category IN ('core','pinned','panel_auto','user_persisted')")}

print("SNAPSHOT-ONLY first/by-0930 per day (non-sentinel tickers WITH snapshots):")
for ds in DAYS:
    t0, t1 = et_ts(ds, 0, 0), et_ts(ds, 23, 59)
    rows = conn.execute(
        "SELECT ticker, MIN(ts_utc) mn, MAX(ts_utc) mx, COUNT(*) n FROM snapshots "
        "WHERE ts_utc>=? AND ts_utc<=? GROUP BY ticker", (t0, t1)).fetchall()
    non = [r for r in rows if r["ticker"] not in SENT]
    firsts = sorted(r["mn"] for r in non)
    by930 = sum(1 for r in non if r["mn"] <= et_ts(ds, 9, 30))
    n_tickers = len(non)
    med = firsts[len(firsts)//2] if firsts else None
    print(f"  {ds}: {n_tickers} non-sentinel tickers with snaps; earliest {fmt(firsts[0]) if firsts else '-'} "
          f"median-first {fmt(med)} latest-first {fmt(firsts[-1]) if firsts else '-'}; snap-by-0930 {by930}/{n_tickers}; "
          f"sentinel by-0930 {sum(1 for r in rows if r['ticker'] in SENT and r['mn'] <= et_ts(ds,9,30))}/3")

print("\nWhich enrolled tickers have ZERO snapshots across all days:")
t0, t1 = et_ts(DAYS[0], 0, 0), et_ts(DAYS[-1], 23, 59)
have = {r["ticker"] for r in conn.execute(
    "SELECT DISTINCT ticker FROM snapshots WHERE ts_utc>=? AND ts_utc<=?", (t0, t1))}
zero = sorted(t for t in uni if t not in have)
print(" ", [(t, uni[t]) for t in zero])

print("\nCadence: max gap (min) between consecutive snapshots inside 09:15-16:15, per day:")
for t in ["AAPL", "WMT", "SPY", "ORCL", "$SPX"]:
    line = []
    for ds in DAYS:
        ts = [r["ts_utc"] for r in conn.execute(
            "SELECT ts_utc FROM snapshots WHERE ticker=? AND ts_utc>=? AND ts_utc<=? ORDER BY ts_utc",
            (t, et_ts(ds, 9, 15), et_ts(ds, 16, 15)))]
        if len(ts) < 2:
            line.append(f"{ds[5:]}: n={len(ts)}")
        else:
            gaps = [(b - a) / 60 for a, b in zip(ts, ts[1:])]
            line.append(f"{ds[5:]}: n={len(ts)} maxgap={max(gaps):.0f}m medgap={statistics.median(gaps):.0f}m")
    print(f"  {t:6}", " | ".join(line))

print("\nGlobal snapshot count per hour (ET) on the halt-suspect day (edit as needed):")
HALT_DAY = "2026-08-20"
for r in conn.execute(
    "SELECT CAST((ts_utc - ?) / 3600 AS INT) h, COUNT(*) n FROM snapshots "
    "WHERE ts_utc>=? AND ts_utc<=? GROUP BY h ORDER BY h",
    (et_ts(HALT_DAY, 0, 0), et_ts(HALT_DAY, 0, 0), et_ts(HALT_DAY, 23, 59))):
    print(f"    {r['h']:02d}:00 ET  {r['n']}")

print("\nABSENT-ticker forensics (enrollment row + all-time counts):")
for t in ["$TNX", "RTY", "SATS", "XXT"]:
    r = conn.execute("SELECT * FROM logging_universe WHERE ticker=?", (t,)).fetchone()
    if r is None:
        print(f"  {t}: not enrolled")
        continue
    nb = conn.execute("SELECT COUNT(*) n, MAX(bar_end_ts_utc) mx FROM price_bars_1m WHERE ticker=?", (t,)).fetchone()
    ns = conn.execute("SELECT COUNT(*) n, MAX(ts_utc) mx FROM snapshots WHERE ticker=?", (t,)).fetchone()
    def dt(x):
        return datetime.fromtimestamp(x, tz=ET).strftime("%Y-%m-%d %H:%M") if x else None
    print(f"  {t}: cat={r['category']} src={r['enrollment_source']} enrolled={dt(r['enrolled_ts_utc'])} "
          f"last_seen={dt(r['last_seen_ts_utc'])} last_bg_log={dt(r['last_background_log_ts_utc'])} "
          f"| bars_alltime={nb['n']} last_bar={dt(nb['mx'])} | snaps_alltime={ns['n']} last_snap={dt(ns['mx'])}")

print("\nSnapshot tickers NOT in authoritative universe (window):")
print(" ", sorted(have - set(uni)))
