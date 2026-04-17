"""Read-only diagnostic: pin_neutral vs labeling gates (evidence for repair design)."""
from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from db import DB_PATH, get_snapshot_sql
from timeframe_config import CANONICAL_TIMEFRAME, DERIVED_TIMEFRAME

DB = DB_PATH
_PIN_TF = (CANONICAL_TIMEFRAME, DERIVED_TIMEFRAME)


def main() -> None:
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    now = time.time()
    win = now - 14 * 86400
    r = conn.execute(
        get_snapshot_sql("tools/_diag_pin_neutral_outcomes.py:pin_tf_summary"),
        _PIN_TF,
    ).fetchone()
    print("pin_neutral rows", r["n"], "ts_utc min/max", r["tmin"], r["tmax"])
    if r["tmax"]:
        print("max_age_days", (now - r["tmax"]) / 86400, "min_age_days", (now - r["tmin"]) / 86400)
    in_win = conn.execute(
        get_snapshot_sql("tools/_diag_pin_neutral_outcomes.py:pin_tf_window"),
        (*_PIN_TF, win, now),
    ).fetchone()[0]
    print("pin_neutral in fill_outcomes 14d window (approx):", in_win)
    print("--- horizon_outcome_schema_version ---")
    for row in conn.execute(
        get_snapshot_sql("tools/_diag_pin_neutral_outcomes.py:schema_v_hist"),
        _PIN_TF,
    ):
        print(dict(row))
    print("--- outcome_filled ---")
    for row in conn.execute(
        get_snapshot_sql("tools/_diag_pin_neutral_outcomes.py:outcome_filled_hist"),
        _PIN_TF,
    ):
        print(dict(row))
    print("--- outcome_1c ---")
    for row in conn.execute(
        get_snapshot_sql("tools/_diag_pin_neutral_outcomes.py:outcome_1c_hist"),
        _PIN_TF,
    ):
        print(dict(row))
    print("--- tickers pin_neutral ---")
    for row in conn.execute(
        get_snapshot_sql("tools/_diag_pin_neutral_outcomes.py:ticker_hist"),
        _PIN_TF,
    ):
        print(dict(row))
    print("--- schema compare pin_bull sample (canonical 1m) ---")
    r2 = conn.execute(
        get_snapshot_sql("tools/_diag_pin_neutral_outcomes.py:pin_bull_schema_sample"),
        (CANONICAL_TIMEFRAME,),
    ).fetchall()
    for x in r2:
        print(dict(x))
    conn.close()


if __name__ == "__main__":
    main()
