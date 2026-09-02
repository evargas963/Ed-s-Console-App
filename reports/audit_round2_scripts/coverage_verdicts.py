"""Per-ticker coverage verdicts (audit round 2, 2026-08-25). Read-only.

Committed so the coverage table in reports/audit_round2_2026-08-25.md is reproducible.
Run from the repo root; ED_CONSOLE_DB_RO overrides the DB. Edit DAYS for the window.

Rules:
ABSENT: 0 snapshots and 0 in-window bars that day.
LATE_START: first data (min of first snapshot, first bar start) > 09:30 ET.
EARLY_STOP: last data (max of last snapshot, last bar end) < 16:10 ET.
GAPPY: in-window 1m bars < 378 (90% of the 420 legal bar-ends 09:16..16:15).
FULL_WINDOW: none of the above. Precedence ABSENT>LATE_START>EARLY_STOP>GAPPY.
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
conn = sqlite3.connect(DB, uri=True)
conn.row_factory = sqlite3.Row

DAYS = ["2026-08-18", "2026-08-19", "2026-08-20", "2026-08-21", "2026-08-24"]
uni = conn.execute(
    "SELECT ticker, category FROM logging_universe "
    "WHERE category IN ('core','pinned','panel_auto','user_persisted')").fetchall()
cat = {r["ticker"]: r["category"] for r in uni}
tickers = sorted(cat)

def et_ts(ds, h, m):
    y, mo, d = map(int, ds.split("-"))
    return datetime(y, mo, d, h, m, tzinfo=ET).timestamp()

def fmt(ts):
    return datetime.fromtimestamp(ts, tz=ET).strftime("%H:%M") if ts else "-"

stats = {}
for ds in DAYS:
    t0, t1 = et_ts(ds, 0, 0), et_ts(ds, 23, 59)
    b0, b1 = et_ts(ds, 9, 15), et_ts(ds, 16, 15)
    snaps = {r["ticker"]: r for r in conn.execute(
        "SELECT ticker, MIN(ts_utc) mn, MAX(ts_utc) mx, COUNT(*) n "
        "FROM snapshots WHERE ts_utc>=? AND ts_utc<=? GROUP BY ticker", (t0, t1))}
    for t in tickers:
        s = snaps.get(t)
        b = conn.execute(
            "SELECT COUNT(*) n, MIN(bar_start_ts_utc) mn, MAX(bar_end_ts_utc) mx "
            "FROM price_bars_1m WHERE ticker=? AND bar_start_ts_utc>=? AND bar_start_ts_utc<?",
            (t, b0, b1)).fetchone()
        if s is None:
            s_mn, s_mx, ns = None, None, 0
        else:
            s_mn, s_mx, ns = s["mn"], s["mx"], s["n"]
        firsts = [x for x in [s_mn, b["mn"]] if x]
        lasts = [x for x in [s_mx, b["mx"]] if x]
        first = min(firsts) if firsts else None
        last = max(lasts) if lasts else None
        nb = b["n"]
        by930 = bool(first and first <= et_ts(ds, 9, 30))
        if not ns and not nb:
            v = "ABSENT"
        elif not by930:
            v = "LATE_START"
        elif last < et_ts(ds, 16, 10):
            v = "EARLY_STOP"
        elif nb < 378:
            v = "GAPPY"
        else:
            v = "FULL_WINDOW"
        stats[(t, ds)] = dict(v=v, first=first, last=last, ns=ns, nb=nb, by930=by930)

# per-ticker rollup
print(f"{'ticker':7}{'cat':16}" + "".join(f"{d[5:]:>7}" for d in DAYS) + "  bars(avg/420) snaps(avg) by930")
for t in tickers:
    row = [stats[(t, d)] for d in DAYS]
    vs = [r["v"] for r in row]
    avg_b = sum(r["nb"] for r in row) / len(DAYS)
    avg_s = sum(r["ns"] for r in row) / len(DAYS)
    n930 = sum(r["by930"] for r in row)
    code = {"FULL_WINDOW": "FULL", "LATE_START": "LATE", "EARLY_STOP": "STOP", "GAPPY": "GAP", "ABSENT": "ABS"}
    print(f"{t:7}{cat[t]:16}" + "".join(f"{code[v]:>7}" for v in vs) + f"  {avg_b:8.0f}      {avg_s:6.1f}   {n930}/5")

print("\nDETAIL first/last (ET) per day, snapshot count ns / bar count nb:")
for t in tickers:
    parts = []
    for d in DAYS:
        r = stats[(t, d)]
        parts.append(f"{d[5:]}: {fmt(r['first'])}-{fmt(r['last'])} ns={r['ns']} nb={r['nb']}")
    print(f"{t:7}" + " | ".join(parts))

# sentinel vs rest
sent = ["SPY", "QQQ", "IWM"]
def agg(group):
    rows = [stats[(t, d)] for t in group for d in DAYS]
    n = len(rows)
    return dict(
        n_ticker_days=n,
        full=sum(r["v"] == "FULL_WINDOW" for r in rows),
        late=sum(r["v"] == "LATE_START" for r in rows),
        stop=sum(r["v"] == "EARLY_STOP" for r in rows),
        gappy=sum(r["v"] == "GAPPY" for r in rows),
        absent=sum(r["v"] == "ABSENT" for r in rows),
        by930=sum(r["by930"] for r in rows),
        avg_bars=sum(r["nb"] for r in rows) / n,
        avg_snaps=sum(r["ns"] for r in rows) / n,
    )
rest = [t for t in tickers if t not in sent]
print("\nSENTINEL (SPY/QQQ/IWM):", agg(sent))
print("REST (%d tickers):" % len(rest), agg(rest))

# window-law check
print("\nWINDOW LAW CHECK (bars):")
for ds in DAYS:
    t0, t1 = et_ts(ds, 0, 0), et_ts(ds, 23, 59)
    r = conn.execute(
        "SELECT MIN(bar_end_ts_utc) mn, MAX(bar_end_ts_utc) mx, COUNT(*) n "
        "FROM price_bars_1m WHERE bar_end_ts_utc>? AND bar_end_ts_utc<=? "
        "AND ticker IN (%s)" % ",".join("?" * len(tickers)), (t0, t1, *tickers)).fetchone()
    ins = conn.execute(
        "SELECT COUNT(*) n FROM price_bars_1m WHERE bar_end_ts_utc>? AND bar_end_ts_utc<=? "
        "AND ticker IN (%s) AND (bar_end_ts_utc<=? OR bar_end_ts_utc>?)"
        % ",".join("?" * len(tickers)),
        (t0, t1, *tickers, et_ts(ds, 9, 16) - 60, et_ts(ds, 16, 15))).fetchone()
    print(f"  {ds}: earliest bar_end {fmt(r['mn'])} latest {fmt(r['mx'])} total {r['n']} outside(555,975] {ins['n']}")

print("\nSNAPSHOT WINDOW OBSERVED:")
for ds in DAYS:
    t0, t1 = et_ts(ds, 0, 0), et_ts(ds, 23, 59)
    r = conn.execute("SELECT MIN(ts_utc) mn, MAX(ts_utc) mx, COUNT(*) n FROM snapshots "
                     "WHERE ts_utc>=? AND ts_utc<=?", (t0, t1)).fetchone()
    print(f"  {ds}: first snap {fmt(r['mn'])} last {fmt(r['mx'])} total {r['n']}")
