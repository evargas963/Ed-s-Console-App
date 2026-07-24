"""
Load and validate SPY 1m OHLCV from SQLite ``price_bars_1m`` or research staging
``price_bars_1m_staging`` (filtered by ``batch_id``).

No silent repair: gaps and integrity issues are surfaced for WITHHELD downstream.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from instrument_identity import ticker_storage_key
from time_et import ET as _ET

SOURCE_TABLE_CANONICAL = "price_bars_1m"
SOURCE_TABLE_STAGING = "price_bars_1m_staging"
VALID_SOURCE_TABLES = frozenset({SOURCE_TABLE_CANONICAL, SOURCE_TABLE_STAGING})

# Match ml_data_common: RTH 09:30–16:00 ET, 16:00 exclusive
RTH_START_MINS = 570
RTH_END_MINS = 960


def _et_minute_of_day(ts_utc: float) -> int:
    dt = datetime.fromtimestamp(float(ts_utc), tz=timezone.utc).astimezone(_ET)  # noqa: DTZ006
    return int(dt.hour * 60 + dt.minute)


def _is_rth_bar_start(ts_start_utc: float) -> bool:
    m = _et_minute_of_day(ts_start_utc)
    return RTH_START_MINS <= m < RTH_END_MINS


def _et_date_str(ts_start_utc: float) -> str:
    dt = datetime.fromtimestamp(float(ts_start_utc), tz=timezone.utc).astimezone(_ET)
    return dt.strftime("%Y-%m-%d")


@dataclass
class Bar1m:
    bar_start_ts_utc: float
    bar_end_ts_utc: float
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None
    # F1 S3 (additive): provenance tag from price_bars_1m.source. None = not
    # loaded — the S3 gate treats that as UNKNOWN and fails closed.
    source: str | None = None


@dataclass
class DataLoadReport:
    ticker: str
    source_table: str = SOURCE_TABLE_CANONICAL
    batch_id: str | None = None
    staging_mode: bool = False
    n_rows: int = 0
    n_rth_rows: int = 0
    ts_start: float | None = None
    ts_end: float | None = None
    duplicate_starts: int = 0
    order_violations: int = 0
    ohlc_violations: int = 0
    rth_gap_count: int = 0
    rth_gap_seconds_max: float = 0.0
    et_date_first: str | None = None
    et_date_last: str | None = None
    date_filter_start: str | None = None
    date_filter_end: str | None = None
    withheld_reason: str | None = None
    bars: list[Bar1m] = field(default_factory=list)


def load_spy_1m_bars(
    db_path: str,
    *,
    ticker: str = "SPY",
    require_rth_only: bool = True,
    start_date: str | None = None,
    end_date: str | None = None,
    source_table: str = SOURCE_TABLE_CANONICAL,
    batch_id: str | None = None,
) -> DataLoadReport:
    """
    Load 1m bars ordered by bar_start_ts_utc ascending.
    If require_rth_only, keep only bars whose bar_start falls in RTH ET window.

    ``source_table`` defaults to ``price_bars_1m``. For ``price_bars_1m_staging``,
    pass a non-empty ``batch_id``; rows are filtered by ``batch_id`` and
    ``ticker_storage_key(ticker)``.
    """
    if source_table not in VALID_SOURCE_TABLES:
        raise ValueError(f"source_table must be one of {sorted(VALID_SOURCE_TABLES)}, got {source_table!r}")
    staging = source_table == SOURCE_TABLE_STAGING
    if staging:
        bid = (batch_id or "").strip()
        if not bid:
            raise ValueError("batch_id is required when source_table is price_bars_1m_staging")
        batch_id = bid
    else:
        batch_id = None

    rep = DataLoadReport(
        ticker=ticker,
        source_table=source_table,
        batch_id=batch_id,
        staging_mode=staging,
    )
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        if staging:
            tkr = ticker_storage_key(ticker)
            cur = conn.execute(
                """
                SELECT bar_start_ts_utc, bar_end_ts_utc, open, high, low, close, volume
                FROM price_bars_1m_staging
                WHERE batch_id = ? AND ticker = ?
                ORDER BY bar_start_ts_utc ASC
                """,
                (batch_id, tkr),
            )
        else:
            cur = conn.execute(
                """
                SELECT bar_start_ts_utc, bar_end_ts_utc, open, high, low, close, volume
                FROM price_bars_1m
                WHERE ticker = ?
                ORDER BY bar_start_ts_utc ASC
                """,
                (ticker,),
            )
        rows = cur.fetchall()
    finally:
        conn.close()

    rep.n_rows = len(rows)
    prev_start: float | None = None
    bars_all: list[Bar1m] = []
    for r in rows:
        st = float(r["bar_start_ts_utc"])
        en = float(r["bar_end_ts_utc"])
        o, h, lo, c = float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"])
        v = r["volume"]
        vol = float(v) if v is not None else None
        if prev_start is not None and st <= prev_start:
            rep.duplicate_starts += 1
        if prev_start is not None and st < prev_start:
            rep.order_violations += 1
        prev_start = st
        if h < max(o, c) or lo > min(o, c) or h < lo:
            rep.ohlc_violations += 1
        bars_all.append(Bar1m(st, en, o, h, lo, c, vol))

    if require_rth_only:
        rep.bars = [b for b in bars_all if _is_rth_bar_start(b.bar_start_ts_utc)]
    else:
        rep.bars = bars_all

    if start_date or end_date:
        rep.date_filter_start = start_date
        rep.date_filter_end = end_date
        lo = start_date or "0000-01-01"
        hi = end_date or "9999-12-31"
        rep.bars = [b for b in rep.bars if lo <= _et_date_str(b.bar_start_ts_utc) <= hi]

    rep.n_rth_rows = len(rep.bars)

    if rep.bars:
        rep.ts_start = rep.bars[0].bar_start_ts_utc
        rep.ts_end = rep.bars[-1].bar_end_ts_utc
        rep.et_date_first = _et_date_str(rep.bars[0].bar_start_ts_utc)
        rep.et_date_last = _et_date_str(rep.bars[-1].bar_start_ts_utc)

    # RTH contiguous gaps (between consecutive kept bars, expect ~60s)
    for i in range(1, len(rep.bars)):
        gap = rep.bars[i].bar_start_ts_utc - rep.bars[i - 1].bar_start_ts_utc
        if gap > 90.0:
            rep.rth_gap_count += 1
            rep.rth_gap_seconds_max = max(rep.rth_gap_seconds_max, gap)

    if rep.duplicate_starts > 0 or rep.order_violations > 0:
        rep.withheld_reason = "integrity: duplicate or non-monotonic bar starts"
    elif rep.ohlc_violations > 0:
        rep.withheld_reason = "integrity: OHLC violations detected"
    return rep


def sufficient_history(rep: DataLoadReport, *, min_bars: int) -> bool:
    return rep.n_rth_rows >= min_bars and rep.withheld_reason is None
