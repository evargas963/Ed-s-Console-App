"""
Lightweight equal-rate base money-path snapshot capture (SPY / QQQ / IWM).

Quote-only inserts tagged logger_source=base_money_path — no full _fetch_state stack.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError, as_completed
from dataclasses import dataclass
from typing import Any, Callable, Optional

LOGGER_SOURCE_BASE_MONEY_PATH = "base_money_path"
LOGGER_SOURCE_BACKGROUND = "background_logger"
LOGGER_SOURCE_UI_SSE = "ui_sse"
LOGGER_SOURCE_UI_REST = "ui_rest"
LOGGER_SOURCE_MANUAL = "manual_backfill"

ALL_LOGGER_SOURCES = frozenset(
    {
        LOGGER_SOURCE_BASE_MONEY_PATH,
        LOGGER_SOURCE_BACKGROUND,
        LOGGER_SOURCE_UI_SSE,
        LOGGER_SOURCE_UI_REST,
        LOGGER_SOURCE_MANUAL,
    }
)


def resolve_logger_source_from_update_source(update_source: Optional[str]) -> Optional[str]:
    """Map Tier C update_source tags to persisted snapshot logger_source."""
    if not update_source:
        return None
    src = str(update_source).strip().lower()
    if src in ("sse_loop", "sse_fanout_rest"):
        return LOGGER_SOURCE_UI_SSE
    if src in (
        "rest_poll_legacy",
        "rest_analytics",
        "rest_poll",
        "client_warm",
        "tick_coherent",
    ) or src.startswith("rest"):
        return LOGGER_SOURCE_UI_REST
    if src == LOGGER_SOURCE_BASE_MONEY_PATH:
        return LOGGER_SOURCE_BASE_MONEY_PATH
    if src == LOGGER_SOURCE_BACKGROUND:
        return LOGGER_SOURCE_BACKGROUND
    return None


@dataclass(frozen=True)
class BaseCaptureAttempt:
    ticker: str
    status: str
    duration_sec: float
    logger_source: str = LOGGER_SOURCE_BASE_MONEY_PATH


def build_lightweight_snapshot_row_from_quote(
    ticker: str,
    quote_fields: dict[str, Any],
    *,
    ts_utc: float,
    now_et,
) -> Any:
    """Minimal SnapshotRow from Schwab quote parse — valid for normalization."""
    from db import SnapshotRow, build_ts_et, market_session
    from math_exposure import session_bucket
    from timeframe_config import CANONICAL_TIMEFRAME

    t = ticker.upper().strip()
    spot_f = float(quote_fields["spot_f"])
    et_h = int(now_et.hour)
    et_m = int(now_et.minute)
    from numeric_contract import float_finite_or_none as _fin
    # single source: finite bid/ask (raw float() admitted NaN into spread AND the stored
    # bid_price/ask_price below); canonical reader also removes the need for try/except.
    bid = _fin(quote_fields.get("bid"))
    ask = _fin(quote_fields.get("ask"))
    spread = None
    if bid is not None and ask is not None:
        spread = round(ask - bid, 4)

    return SnapshotRow(
        ticker=t,
        timeframe=CANONICAL_TIMEFRAME,
        ts_utc=ts_utc,
        ts_et=build_ts_et(now_et),
        et_hour=et_h,
        et_minute=et_m,
        market_session=market_session(et_h, et_m, et_date=now_et.strftime("%Y-%m-%d")),  # RC-278
        spot=spot_f,
        spread=spread,
        bid_price=bid,
        ask_price=ask,
        bid_size=quote_fields.get("bid_size"),
        ask_size=quote_fields.get("ask_size"),
        last_size=quote_fields.get("last_size"),
        total_volume=quote_fields.get("total_volume"),
        candle_open=spot_f,
        candle_high=spot_f,
        candle_low=spot_f,
        candle_close=spot_f,
        session_bucket=session_bucket(et_h, et_m),
        logger_source=LOGGER_SOURCE_BASE_MONEY_PATH,
    )


def run_base_money_path_capture_cycle(
    tickers: tuple[str, ...] | list[str],
    *,
    capture_one: Callable[[str], BaseCaptureAttempt],
    max_workers: int = 3,
    per_ticker_timeout_sec: float = 45.0,
    log: Optional[logging.Logger] = None,
) -> list[BaseCaptureAttempt]:
    """
    Concurrent base capture — one attempt per ticker per cycle.

    Slow SPY fetch must not block QQQ/IWM attempts (bounded timeout per future).
    """
    symbols = tuple(t.upper() for t in tickers)
    if not symbols:
        return []

    workers = max(1, min(int(max_workers), len(symbols)))
    results: list[BaseCaptureAttempt] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_map = {pool.submit(capture_one, t): t for t in symbols}
        for fut in as_completed(future_map):
            t = future_map[fut]
            try:
                results.append(fut.result(timeout=per_ticker_timeout_sec))
            except TimeoutError:
                msg = f"error:timeout>{per_ticker_timeout_sec:.0f}s"
                results.append(
                    BaseCaptureAttempt(t, msg, per_ticker_timeout_sec)
                )
                if log:
                    log.warning("Base money-path capture timeout: %s", t)
            except Exception as exc:
                results.append(
                    BaseCaptureAttempt(t, f"error:{str(exc)[:80]}", 0.0)
                )
                if log:
                    log.warning("Base money-path capture failed: %s — %s", t, exc)
    results.sort(key=lambda r: symbols.index(r.ticker))
    return results
