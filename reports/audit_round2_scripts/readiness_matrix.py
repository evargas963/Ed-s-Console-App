"""By-9:30 readiness matrix (audit round 2, 2026-08-25). Read-only.

Committed so RC-481's next-RTH rerun is reproducible from the tree. Run from the repo
root; point ED_CONSOLE_DB_RO at another checkout's DB if needed. Edit DAYS/PREV for the
window under audit.

Universe: CORE + logging_universe categories user_persisted/pinned (mirrors
server._hydrate_logger_tickers_from_db).
Requirements measured AT 09:30 ET per (ticker, day):
  R1 prev-day bars   : COUNT(price_bars_1m) on prior trading day
  R2 first bar       : MIN(bar_end_ts_utc) today  -> met if <= 09:30 ET
  R3 first chain     : MIN(option_chain_accrual.ts_utc) today -> met if < 09:30 ET
  R4 first snapshot  : MIN(snapshots.ts_utc) today (any source) -> met if < 09:30 ET
  R4b first FULL snap: MIN over logger_source='background' rows (chain-bearing)
"""
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.domain.time_et import ET  # noqa: E402 — the ONE NY-zone authority (COH-SA-2)

DB = os.environ.get("ED_CONSOLE_DB_RO")
if DB is None:
    DB = "file:data/ed_console.db?mode=ro"
CORE = ["SPY", "QQQ", "IWM", "NVDA", "AAPL", "MSFT", "AMZN", "META", "TSLA", "GOOGL", "AVGO"]
DAYS = ["2026-08-18", "2026-08-19", "2026-08-20", "2026-08-21", "2026-08-24"]
PREV = {"2026-08-18": "2026-08-17", "2026-08-19": "2026-08-18", "2026-08-20": "2026-08-19",
        "2026-08-21": "2026-08-20", "2026-08-24": "2026-08-21"}

def day_bounds(d):
    y, m, dd = (int(x) for x in d.split("-"))
    start = datetime(y, m, dd, 0, 0, tzinfo=ET).timestamp()
    return start, start + 86400.0

def open_ts(d):
    y, m, dd = (int(x) for x in d.split("-"))
    return datetime(y, m, dd, 9, 30, tzinfo=ET).timestamp()

def et_hm(ts):
    if ts is None:
        return "  --  "
    return datetime.fromtimestamp(ts, tz=ET).strftime("%H:%M:%S")

conn = sqlite3.connect(DB, uri=True)
cur = conn.cursor()

# universe
uni = list(CORE)
for (t, cat) in cur.execute("SELECT ticker, category FROM logging_universe "
                            "WHERE category IN ('user_persisted','pinned') ORDER BY ticker"):
    if t not in uni:
        uni.append(t)
cat_of = {t: "core" for t in CORE}
for (t, cat) in cur.execute("SELECT ticker, category FROM logging_universe"):
    cat_of.setdefault(t, cat)
print(f"UNIVERSE n={len(uni)}: {uni}")

# accrual row count sanity (bounded)
n_acc = cur.execute("SELECT COUNT(*) FROM option_chain_accrual WHERE et_date >= ?",
                    (DAYS[0],)).fetchone()[0]
print(f"option_chain_accrual rows since {DAYS[0]}:", n_acc)

# logger_source values in window
s0, _ = day_bounds(DAYS[0]); _, s1 = day_bounds(DAYS[-1])
print("snapshot logger_source counts in window:",
      cur.execute("SELECT logger_source, COUNT(*) FROM snapshots WHERE ts_utc>=? AND ts_utc<? "
                  "GROUP BY logger_source", (s0, s1)).fetchall())

# per-day aggregates
first_snap = {}       # (d,t) -> ts
first_full_snap = {}  # (d,t) -> ts  (logger_source='background')
for d in DAYS:
    a, b = day_bounds(d)
    for t, mn in cur.execute("SELECT ticker, MIN(ts_utc) FROM snapshots "
                             "WHERE ts_utc>=? AND ts_utc<? GROUP BY ticker", (a, b)):
        first_snap[(d, t)] = mn
    for t, mn in cur.execute("SELECT ticker, MIN(ts_utc) FROM snapshots "
                             "WHERE ts_utc>=? AND ts_utc<? AND logger_source='background' "
                             "GROUP BY ticker", (a, b)):
        first_full_snap[(d, t)] = mn

first_chain = {}
for d in DAYS:
    for t, mn in cur.execute("SELECT ticker, MIN(ts_utc) FROM option_chain_accrual "
                             "WHERE et_date=? GROUP BY ticker", (d,)):
        first_chain[(d, t)] = mn

morning_full = {}
for t, d, ts in cur.execute("SELECT ticker, et_date, ts_utc FROM option_chain_morning_full "
                            "WHERE et_date>=?", (DAYS[0],)):
    morning_full[(d, t)] = ts

bars_first = {}
bars_prev_count = {}
alldays = sorted(set(DAYS) | set(PREV.values()))
for d in alldays:
    a, b = day_bounds(d)
    for t in uni:
        r = cur.execute("SELECT MIN(bar_end_ts_utc), COUNT(*) FROM price_bars_1m "
                        "WHERE ticker=? AND bar_start_ts_utc>=? AND bar_start_ts_utc<?",
                        (t, a, b)).fetchone()
        bars_first[(d, t)] = r[0]
        bars_prev_count[(d, t)] = r[1]

# matrix
fails = {"R1": [], "R2": [], "R3": [], "R4": [], "R4b": []}
for d in DAYS:
    o = open_ts(d)
    print(f"\n===== {d}  (prev trading day {PREV[d]}) — met/miss AT 09:30 ET =====")
    print(f"{'ticker':8s} {'cat':6s} | {'prevbars':>8s} | {'1st bar':>8s} | {'1st chain':>9s} | "
          f"{'1st snap':>8s} | {'1st fullsnap':>11s} | {'morning_full':>12s} | verdict")
    for t in uni:
        pb = bars_prev_count[(PREV[d], t)]
        fb = bars_first[(d, t)]
        fc = first_chain.get((d, t))
        fs = first_snap.get((d, t))
        ffs = first_full_snap.get((d, t))
        mf = morning_full.get((d, t))
        r1 = pb > 0
        r2 = fb is not None and fb <= o
        r3 = fc is not None and fc < o
        r4 = fs is not None and fs < o
        r4b = ffs is not None and ffs < o
        for name, ok in (("R1", r1), ("R2", r2), ("R3", r3), ("R4", r4), ("R4b", r4b)):
            if not ok:
                fails[name].append((d, t))
        verdict = "READY" if (r1 and r2 and r3 and r4) else \
                  "MISS:" + ",".join(n for n, ok in (("prevbars", r1), ("bar", r2),
                                                     ("chain", r3), ("snap", r4)) if not ok)
        print(f"{t:8s} {cat_of.get(t,'?'):6s} | {pb:8d} | {et_hm(fb):>8s} | {et_hm(fc):>9s} | "
              f"{et_hm(fs):>8s} | {et_hm(ffs):>11s} | {et_hm(mf):>12s} | {verdict}")

print("\n===== SUMMARY (ticker-days failing, of %d) =====" % (len(uni) * len(DAYS)))
for k, v in fails.items():
    per_t = {}
    for d, t in v:
        per_t.setdefault(t, []).append(d[-2:])
    print(f"{k}: {len(v)} fails -> " + "; ".join(f"{t}({len(ds)}d)" for t, ds in sorted(per_t.items())))
conn.close()
