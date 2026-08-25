"""GEX capture accrual audit (audit round 2, 2026-08-25). Read-only; run from repo root;
ED_CONSOLE_DB_RO overrides the DB. Edit CUT for the window."""
import os
import sqlite3

DB = os.environ.get("ED_CONSOLE_DB_RO", "file:data/ed_console.db?mode=ro")
conn = sqlite3.connect(DB, uri=True)
cur = conn.cursor()

tabs = [r[0] for r in cur.execute(
    "SELECT name FROM sqlite_master WHERE type='table' AND (name LIKE '%chain%' OR name LIKE '%gex%' "
    "OR name LIKE '%terrain%' OR name LIKE '%exposure%')").fetchall()]
print("TABLES:", tabs)

CUT = "2026-07-26"  # last 30 days at authoring time

print("\n== option_chain_morning_full: per-day ticker count + total rows (>= %s) ==" % CUT)
for r in cur.execute(
    "SELECT et_date, COUNT(*) n, COUNT(DISTINCT ticker) nt, ROUND(AVG(n_contracts),0) "
    "FROM option_chain_morning_full WHERE et_date >= ? GROUP BY et_date ORDER BY et_date", (CUT,)):
    print(r)

print("\n== morning_full: overall date span + total ==")
print(cur.execute("SELECT MIN(et_date), MAX(et_date), COUNT(*) FROM option_chain_morning_full").fetchone())

print("\n== morning_full: per-ticker day counts in window (top 60) ==")
for r in cur.execute(
    "SELECT ticker, COUNT(*) FROM option_chain_morning_full WHERE et_date >= ? "
    "GROUP BY ticker ORDER BY ticker LIMIT 60", (CUT,)):
    print(r)

print("\n== option_chain_accrual: per-day rows + tickers (>= %s) ==" % CUT)
for r in cur.execute(
    "SELECT et_date, COUNT(*) n, COUNT(DISTINCT ticker) nt, MIN(et_minute), MAX(et_minute) "
    "FROM option_chain_accrual WHERE et_date >= ? GROUP BY et_date ORDER BY et_date", (CUT,)):
    print(r)

print("\n== accrual: overall span + total ==")
print(cur.execute("SELECT MIN(et_date), MAX(et_date), COUNT(*) FROM option_chain_accrual").fetchone())

print("\n== last trading day captured, both tables ==")
print("morning_full last 3 dates:", cur.execute(
    "SELECT et_date, COUNT(*), COUNT(DISTINCT ticker) FROM option_chain_morning_full "
    "GROUP BY et_date ORDER BY et_date DESC LIMIT 3").fetchall())
print("accrual last 3 dates:", cur.execute(
    "SELECT et_date, COUNT(*), COUNT(DISTINCT ticker) FROM option_chain_accrual "
    "GROUP BY et_date ORDER BY et_date DESC LIMIT 3").fetchall())
conn.close()
