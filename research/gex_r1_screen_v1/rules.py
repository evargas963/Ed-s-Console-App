"""Mechanical VWAP-reversion and OR-breakout rules graded in dollars after costs."""

from __future__ import annotations

import math
from dataclasses import dataclass

from research.pilot_step3.data_loader import Bar1m, load_spy_1m_bars
from time_et import ET
from datetime import datetime, timezone


@dataclass
class DayRulePnL:
    reversion_pnl: float
    breakout_pnl: float
    regime_score: float  # reversion - breakout
    sigma: float
    n_rev_trades: int
    n_brk_trades: int
    cost_rt_dollars: float


def _et_mins(ts: float) -> int:
    dt = datetime.fromtimestamp(float(ts), tz=timezone.utc).astimezone(ET)
    return int(dt.hour * 60 + dt.minute)


def _session_sigma(bars: list[Bar1m]) -> float:
    """Intraday sigma from 1m close-to-close; fallback range/20."""
    closes = [b.close for b in bars if b.close and b.close > 0]
    if len(closes) < 30:
        if not bars:
            return float("nan")
        hi = max(b.high for b in bars)
        lo = min(b.low for b in bars)
        return max((hi - lo) / 20.0, 1e-6)
    rets = []
    for i in range(1, len(closes)):
        if closes[i - 1] > 0:
            rets.append(closes[i] - closes[i - 1])
    if len(rets) < 20:
        return float("nan")
    mu = sum(rets) / len(rets)
    var = sum((x - mu) ** 2 for x in rets) / (len(rets) - 1)
    return max(math.sqrt(var), 1e-6)


def _cost_dollars(spot: float, rt_bp: float) -> float:
    return float(spot) * (float(rt_bp) / 10_000.0)


def simulate_reversion(
    bars: list[Bar1m],
    *,
    sigma: float,
    m: float,
    max_entries: int,
    cost_rt: float,
) -> tuple[float, int]:
    """Fade VWAP extensions; target VWAP; stop at (m+1)·σ; flat close."""
    if not bars or not math.isfinite(sigma) or sigma <= 0:
        return 0.0, 0
    pnl = 0.0
    trades = 0
    cum_pv = 0.0
    cum_v = 0.0
    i = 0
    while i < len(bars) and trades < max_entries:
        b = bars[i]
        typ = (b.high + b.low + b.close) / 3.0
        vol = float(b.volume or 1.0)
        cum_pv += typ * vol
        cum_v += vol
        vwap = cum_pv / cum_v if cum_v > 0 else b.close
        # extension check on close
        if b.close >= vwap + m * sigma:
            side = -1  # short fade
            entry = b.close
            target = vwap
            stop = vwap + (m + 1.0) * sigma
            j = i + 1
            exit_px = bars[-1].close
            while j < len(bars):
                bj = bars[j]
                if bj.low <= target:
                    exit_px = target
                    break
                if bj.high >= stop:
                    exit_px = stop
                    break
                j += 1
            pnl += side * (exit_px - entry) - cost_rt
            trades += 1
            i = j
            continue
        if b.close <= vwap - m * sigma:
            side = 1  # long fade
            entry = b.close
            target = vwap
            stop = vwap - (m + 1.0) * sigma
            j = i + 1
            exit_px = bars[-1].close
            while j < len(bars):
                bj = bars[j]
                if bj.high >= target:
                    exit_px = target
                    break
                if bj.low <= stop:
                    exit_px = stop
                    break
                j += 1
            pnl += side * (exit_px - entry) - cost_rt
            trades += 1
            i = j
            continue
        i += 1
    return pnl, trades


def simulate_breakout(
    bars: list[Bar1m],
    *,
    sigma: float,
    m: float,
    max_entries: int,
    cost_rt: float,
    or_minutes: int,
    buffer_frac: float,
) -> tuple[float, int]:
    """OR breakout with buffer; target m·σ; stop back inside OR; flat close."""
    if not bars or not math.isfinite(sigma) or sigma <= 0:
        return 0.0, 0
    open_mins = _et_mins(bars[0].bar_start_ts_utc)
    or_end = open_mins + or_minutes
    or_bars = [b for b in bars if _et_mins(b.bar_start_ts_utc) < or_end]
    if len(or_bars) < 5:
        return 0.0, 0
    or_hi = max(b.high for b in or_bars)
    or_lo = min(b.low for b in or_bars)
    buf = buffer_frac * sigma
    pnl = 0.0
    trades = 0
    i = len(or_bars)
    while i < len(bars) and trades < max_entries:
        b = bars[i]
        if b.close >= or_hi + buf:
            side = 1
            entry = b.close
            target = entry + m * sigma
            stop = or_hi
            j = i + 1
            exit_px = bars[-1].close
            while j < len(bars):
                bj = bars[j]
                if bj.high >= target:
                    exit_px = target
                    break
                if bj.low <= stop:
                    exit_px = stop
                    break
                j += 1
            pnl += side * (exit_px - entry) - cost_rt
            trades += 1
            i = j
            continue
        if b.close <= or_lo - buf:
            side = -1
            entry = b.close
            target = entry - m * sigma
            stop = or_lo
            j = i + 1
            exit_px = bars[-1].close
            while j < len(bars):
                bj = bars[j]
                if bj.low <= target:
                    exit_px = target
                    break
                if bj.high >= stop:
                    exit_px = stop
                    break
                j += 1
            pnl += side * (exit_px - entry) - cost_rt
            trades += 1
            i = j
            continue
        i += 1
    return pnl, trades


def day_rule_pnl(
    db_path: str,
    ticker: str,
    et_date: str,
    spot: float,
    *,
    m: float,
    max_entries: int,
    cost_rt_bp: float,
    or_minutes: int,
    buffer_frac: float,
) -> DayRulePnL | None:
    rep = load_spy_1m_bars(
        db_path,
        ticker=ticker,
        require_rth_only=True,
        start_date=et_date,
        end_date=et_date,
    )
    bars = list(rep.bars)
    if len(bars) < 60:
        return None
    sigma = _session_sigma(bars)
    if not math.isfinite(sigma):
        return None
    cost = _cost_dollars(spot, cost_rt_bp)
    rev, n_r = simulate_reversion(
        bars, sigma=sigma, m=m, max_entries=max_entries, cost_rt=cost
    )
    brk, n_b = simulate_breakout(
        bars,
        sigma=sigma,
        m=m,
        max_entries=max_entries,
        cost_rt=cost,
        or_minutes=or_minutes,
        buffer_frac=buffer_frac,
    )
    return DayRulePnL(
        reversion_pnl=rev,
        breakout_pnl=brk,
        regime_score=rev - brk,
        sigma=sigma,
        n_rev_trades=n_r,
        n_brk_trades=n_b,
        cost_rt_dollars=cost,
    )
