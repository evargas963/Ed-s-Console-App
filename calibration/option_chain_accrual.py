"""The per-minute, per-strike gamma and volume of each ticker's full chain during the session
(option_chain_accrual), read by /api/exposure/flow for the /exposure page. The full chains
themselves are the chain history (calibration/complete_chain_capture.py)."""

from __future__ import annotations

import math
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from time_et import ET, is_trading_day_et  # RC-278: the calendar authority, on the WRITE side
from instrument_identity import ticker_storage_key
from json_blob_codec import encode_json_blob

ACCRUAL_START_MINS = 555   # 09:15 ET == 08:15 CT
ACCRUAL_END_MINS = 975     # 16:15 ET == 15:15 CT
ACCRUAL_SOURCE = "terrain_wide_chain_accrual"

ACCRUAL_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS option_chain_accrual (
    ticker TEXT NOT NULL,
    ts_utc REAL NOT NULL,
    et_date TEXT NOT NULL,
    et_minute INTEGER NOT NULL,
    spot REAL,
    n_strikes INTEGER NOT NULL,
    session_volume REAL,
    abs_gex_total REAL,
    per_strike_json TEXT NOT NULL,
    source TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (ticker, ts_utc)
);
CREATE INDEX IF NOT EXISTS idx_chain_accrual_ticker_date
    ON option_chain_accrual(ticker, et_date, et_minute);
"""


def accrual_window(mins: int) -> bool:
    """True inside the mandated accrual span [09:15, 16:15] ET (= 08:15-15:15 CT).

    Inclusive at BOTH ends: the operator named the boundaries as times data must exist, so a
    snapshot landing exactly at 09:15:00 or 16:15:00 belongs in the record.
    """
    return ACCRUAL_START_MINS <= int(mins) <= ACCRUAL_END_MINS


def ensure_accrual_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(ACCRUAL_TABLE_SQL)
    conn.commit()


def persist_chain_accrual(
    db_path: Path | str,
    *,
    ticker: str,
    per_strike_rows: list[Any],
    spot: float | None,
    ts_utc: float | None = None,
    source: str = ACCRUAL_SOURCE,
) -> dict[str, Any]:
    """Append one wide-chain observation: `[[strike, net_gex_1pct$, session_volume], ...]`.

    We store the PER-STRIKE AGGREGATE rather than every contract. It is exactly what the gamma
    ladder and the volume histogram consume, and it is what the terrain loop already computed
    from the wide chain it already fetched — so accrual costs ZERO additional vendor calls
    (RC-68 kept this map in memory and threw it away at the end of each cycle). Persisting whole
    chains at this cadence would add hundreds of megabytes a day for data no surface reads.

    FAIL CLOSED: no rows, or rows that carry no finite strike, writes NOTHING and says why. A
    fabricated or empty-but-present observation is worse than a gap, because a gap is visible.
    """
    et_date, mins = et_date_and_mins(ts_utc)
    # RC-278: calendar BEFORE clock. `accrual_window(mins)` asks whether the clock is inside the
    # span; 10:00 ET is inside it on a Saturday too. MEASURED: this wrote 600 minutes for
    # 2026-08-01, a Saturday. Whether a session exists at all is a precondition to where we are
    # inside one, and `is_trading_day_et` is the single authority get_forces already reads with.
    if not is_trading_day_et(et_date):
        return {"status": "skipped", "reason": "non_trading_day", "et_date": et_date}
    tk = ticker_storage_key(ticker)  # RC-345/F25: canonical option-chain storage identity
    if not tk:
        return {"status": "skipped", "reason": "no_ticker"}
    if not accrual_window(mins):
        return {"status": "skipped", "reason": "outside_accrual_window",
                "et_date": et_date, "mins": mins}

    clean: list[list[float]] = []
    vol_total = 0.0
    gex_total = 0.0
    for row in per_strike_rows or []:
        if not isinstance(row, (list, tuple)) or len(row) < 3:
            continue
        try:
            k, g, v = float(row[0]), float(row[1]), float(row[2])
        except (TypeError, ValueError):
            continue
        if not (math.isfinite(k) and math.isfinite(g) and math.isfinite(v)):
            continue
        clean.append([k, g, v])
        vol_total += v
        gex_total += abs(g)
    if not clean:
        return {"status": "skipped", "reason": "no_finite_per_strike_rows", "ticker": tk}

    ts = float(ts_utc if ts_utc is not None else time.time())
    conn = sqlite3.connect(str(db_path), timeout=60.0)
    try:
        ensure_accrual_schema(conn)
        conn.execute(
            "INSERT OR REPLACE INTO option_chain_accrual "
            "(ticker, ts_utc, et_date, et_minute, spot, n_strikes, session_volume, "
            " abs_gex_total, per_strike_json, source) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (tk, ts, et_date, int(mins),
             float(spot) if spot is not None and math.isfinite(float(spot)) else None,
             len(clean), vol_total, gex_total,
             encode_json_blob(clean), str(source)),
        )
        conn.commit()
    finally:
        conn.close()
    return {"status": "written", "ticker": tk, "et_date": et_date, "mins": mins,
            "n_strikes": len(clean), "session_volume": vol_total, "ts_utc": ts}


def et_date_and_mins(ts_utc: float | None = None) -> tuple[str, int]:
    """ET calendar date and minute of day."""
    dt = datetime.fromtimestamp(
        float(ts_utc if ts_utc is not None else time.time()),
        tz=timezone.utc,
    ).astimezone(ET)
    return dt.strftime("%Y-%m-%d"), int(dt.hour * 60 + dt.minute)
