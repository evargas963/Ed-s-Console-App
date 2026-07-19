"""Once-per-day morning full-chain persist for GEX-R1 forward collection.

Stores all fetched contracts with T <= ~0.10y (not selected_exp only).
Does not widen every snapshot's option_chain_json.
"""

from __future__ import annotations

import json
import logging
import math
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from time_et import ET

log = logging.getLogger(__name__)

TABLE_SQL = """
CREATE TABLE IF NOT EXISTS option_chain_morning_full (
    ticker TEXT NOT NULL,
    et_date TEXT NOT NULL,
    ts_utc REAL NOT NULL,
    spot REAL,
    n_contracts INTEGER,
    n_expiries INTEGER,
    max_dte REAL,
    chain_json TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'schwab_chain',
    created_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (ticker, et_date)
);
"""

# ~0.10y ≈ 36.5 calendar days
MAX_DTE_DAYS = 37.0
MORNING_START_MINS = 570  # 09:30 ET
MORNING_END_MINS = 600    # 10:00 ET — capture window for first write
# Dedicated morning wide fetch (UI live path stays at CHAIN_STRIKE_COUNT=20).
GEX_FULL_CHAIN_STRIKE_COUNT = 150
SOURCE_WIDE = "schwab_chain_wide_gex"


def ensure_morning_full_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(TABLE_SQL)
    conn.commit()


def et_date_and_mins(ts_utc: float | None = None) -> tuple[str, int]:
    """Public ET calendar date + minute-of-day for morning-window gates."""
    dt = datetime.fromtimestamp(
        float(ts_utc if ts_utc is not None else time.time()),
        tz=timezone.utc,
    ).astimezone(ET)
    return dt.strftime("%Y-%m-%d"), int(dt.hour * 60 + dt.minute)


def _et_date_and_mins(ts_utc: float | None = None) -> tuple[str, int]:
    return et_date_and_mins(ts_utc)


def has_morning_full_capture(
    db_path: Path | str, ticker: str, et_date: str
) -> bool:
    """True when ``option_chain_morning_full`` already has (ticker, et_date)."""
    path = Path(db_path)
    if not path.is_file():
        return False
    try:
        conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    except sqlite3.Error:
        return False
    try:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='option_chain_morning_full'"
        ).fetchone()
        if not row:
            return False
        hit = conn.execute(
            "SELECT 1 FROM option_chain_morning_full WHERE ticker=? AND et_date=?",
            (str(ticker).upper(), str(et_date)),
        ).fetchone()
        return hit is not None
    except sqlite3.Error:
        return False
    finally:
        conn.close()


def _dte_days(ct: dict[str, Any]) -> float | None:
    if ct.get("daysToExpiration") is not None:
        try:
            return float(ct["daysToExpiration"])
        except (TypeError, ValueError):
            pass
    exp = ct.get("expirationDate")
    if not exp:
        return None
    try:
        # 2026-07-17T20:00:00.000+00:00
        day = str(exp)[:10]
        exp_dt = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return max((exp_dt - now).total_seconds() / 86400.0, 0.0)
    except (TypeError, ValueError):
        return None


def filter_near_term_contracts(contracts: list[Any], *, max_dte_days: float = MAX_DTE_DAYS) -> list[dict]:
    out: list[dict] = []
    for ct in contracts or []:
        if not isinstance(ct, dict):
            continue
        dte = _dte_days(ct)
        if dte is None or dte > max_dte_days:
            continue
        row = dict(ct)
        row.pop("raw", None)
        out.append(row)
    return out


def maybe_persist_morning_full_chain(
    db_path: Path | str,
    *,
    ticker: str,
    contracts: list[Any],
    spot: float | None,
    ts_utc: float | None = None,
    source: str = SOURCE_WIDE,
) -> dict[str, Any]:
    """Idempotent: one row per (ticker, et_date) in the morning window."""
    et_date, mins = et_date_and_mins(ts_utc)
    ticker_u = str(ticker).upper()
    if mins < MORNING_START_MINS or mins > MORNING_END_MINS:
        return {"status": "skipped", "reason": "outside_morning_window", "et_date": et_date, "mins": mins}
    if has_morning_full_capture(db_path, ticker_u, et_date):
        return {"status": "idempotent_skip", "ticker": ticker_u, "et_date": et_date}
    near = filter_near_term_contracts(contracts)
    if len(near) < 10:
        return {"status": "skipped", "reason": "too_few_near_term_contracts", "n": len(near)}

    conn = sqlite3.connect(str(db_path), timeout=60.0)
    try:
        ensure_morning_full_schema(conn)
        # Race-safe second check under write connection
        exists = conn.execute(
            "SELECT 1 FROM option_chain_morning_full WHERE ticker=? AND et_date=?",
            (ticker_u, et_date),
        ).fetchone()
        if exists:
            return {"status": "idempotent_skip", "ticker": ticker_u, "et_date": et_date}

        exps = {
            str(c.get("expirationDate") or "")[:10]
            for c in near
            if c.get("expirationDate")
        }
        dtes = [d for d in (_dte_days(c) for c in near) if d is not None]
        ts = float(ts_utc if ts_utc is not None else time.time())
        conn.execute(
            """
            INSERT INTO option_chain_morning_full(
              ticker, et_date, ts_utc, spot, n_contracts, n_expiries, max_dte, chain_json, source
            ) VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                ticker_u,
                et_date,
                ts,
                float(spot) if spot is not None and math.isfinite(float(spot)) else None,
                len(near),
                len(exps),
                max(dtes) if dtes else None,
                json.dumps(near, default=str),
                str(source),
            ),
        )
        conn.commit()
        log.info(
            "option_chain_morning_full wrote ticker=%s et_date=%s n=%s expiries=%s source=%s",
            ticker_u,
            et_date,
            len(near),
            len(exps),
            source,
        )
        return {
            "status": "ok",
            "ticker": ticker_u,
            "et_date": et_date,
            "n_contracts": len(near),
            "n_expiries": len(exps),
            "source": str(source),
        }
    finally:
        conn.close()
