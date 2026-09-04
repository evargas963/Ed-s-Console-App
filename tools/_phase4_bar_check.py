import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from db import DB_PATH
from horizon_outcomes import forward_bar_start_utc, OUTCOME_BAR_SPECS
from app.domain.instrument_identity import ticker_storage_key

ts = 1775926978.9349923
conn = sqlite3.connect(str(DB_PATH), timeout=120.0)
conn.row_factory = sqlite3.Row
tkr = ticker_storage_key("SPY")
for odir, opt, n_min in OUTCOME_BAR_SPECS:
    b_start = forward_bar_start_utc(ts, n_min)
    r = conn.execute(
        "SELECT close FROM price_bars_1m WHERE ticker=? AND bar_start_ts_utc=?",
        (tkr, b_start),
    ).fetchone()
    print(odir, "b_start", b_start, "close", r["close"] if r else None)
conn.close()
