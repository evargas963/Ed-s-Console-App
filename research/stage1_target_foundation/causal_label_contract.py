"""Causal label reconstruction contract + mechanical lookahead guards (research-only).

This module RE-IMPLEMENTS the production fixed-horizon label formula (proven by
audit: db._apply_bar_based_outcome_updates / horizon_outcomes.py) from an
immutable list of 1-minute bars, so that:

  * every label reconstructs deterministically from source-row identity alone
    (ticker, bar_start_ts_utc, close) — Phase E/J;
  * mechanical guards fail closed on lookahead, incomplete-bar use, session
    crossover, timestamp aliasing, duplicate anchors, horizon confusion, and
    cross-ticker attachment — Phase E;
  * realized MFE/MAE from the OHLC path is available as a research label
    (distinct from the runtime Monte-Carlo forecast) — Phase H.

It is NOT wired into production. It never reads snapshots.spot, quotes, or any
future bar beyond the label's own forward bar. Session classification uses the
canonical ts_utc->DST-ET authority (time_et.is_rth_ts_utc) — never a stored
et_hour/et_minute column (the RTH-integrity contradiction those columns cause is
documented in the Stage 1 report and session/cohort contract).
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass

BAR_SECONDS = 60
# canonical horizons in candles (1 candle = 1 minute); matches ml_horizon primary set
HORIZON_MINUTES = {"1c": 1, "5c": 5, "15c": 15, "60c": 60}


@dataclass(frozen=True)
class Bar:
    """One immutable 1-minute OHLC bar. Identity = (ticker, bar_start_ts_utc)."""
    ticker: str
    bar_start_ts_utc: int
    open: float
    high: float
    low: float
    close: float

    @property
    def bar_end_ts_utc(self) -> int:
        return self.bar_start_ts_utc + BAR_SECONDS


class CausalLabelError(ValueError):
    """Raised when a label request would violate the causal contract (fail closed)."""


def _index_bars(bars: list[Bar], ticker: str) -> tuple[list[int], dict[int, Bar]]:
    """Return (sorted bar_start list, start->Bar map) for one ticker, rejecting
    duplicate anchors and cross-ticker rows."""
    starts: list[int] = []
    by_start: dict[int, Bar] = {}
    for b in bars:
        if b.ticker != ticker:
            continue
        if b.bar_start_ts_utc in by_start:
            raise CausalLabelError(
                f"duplicate anchor bar_start {b.bar_start_ts_utc} for {ticker}"
            )
        if b.bar_start_ts_utc % BAR_SECONDS != 0:
            raise CausalLabelError(
                f"bar_start {b.bar_start_ts_utc} not aligned to the 60s grid (timestamp aliasing)"
            )
        by_start[b.bar_start_ts_utc] = b
        starts.append(b.bar_start_ts_utc)
    starts.sort()
    return starts, by_start


def anchor_bar_for(bars: list[Bar], ticker: str, anchor_ts_utc: float) -> Bar | None:
    """Last completed 1m bar whose bar_end_ts_utc <= anchor_ts_utc (production rule)."""
    starts, by_start = _index_bars(bars, ticker)
    ends = [s + BAR_SECONDS for s in starts]
    i = bisect.bisect_right(ends, anchor_ts_utc) - 1
    if i < 0:
        return None
    return by_start[starts[i]]


def classify_direction_pts(pts: float, threshold: float) -> str:
    """Mirror of math_probabilities.classify_direction_pts (fail closed to flat)."""
    if threshold is None or threshold <= 0:
        return "flat"
    if pts > threshold:
        return "up"
    if pts < -threshold:
        return "down"
    return "flat"


def reconstruct_fixed_horizon_label(
    bars: list[Bar],
    ticker: str,
    anchor_ts_utc: float,
    horizon: str,
    threshold_pts: float,
    *,
    now_ts_utc: float,
) -> dict:
    """Deterministically reconstruct the production fixed-horizon outcome for one
    (ticker, anchor, horizon) from immutable bars. Fails closed on any causal
    hazard. Returns {outcome, pts, forward_bar_start, anchor_bar_start,
    complete, reconstructable}."""
    if horizon not in HORIZON_MINUTES:
        raise CausalLabelError(f"unknown horizon {horizon!r} (horizon confusion)")
    n_min = HORIZON_MINUTES[horizon]
    anchor = anchor_bar_for(bars, ticker, anchor_ts_utc)
    if anchor is None:
        return {"outcome": None, "pts": None, "reconstructable": False,
                "reason": "no anchor bar <= anchor_ts_utc"}
    fwd_start = int((anchor_ts_utc + n_min * BAR_SECONDS) // BAR_SECONDS) * BAR_SECONDS
    fwd_end = fwd_start + BAR_SECONDS
    # LOOKAHEAD GUARD: the label may only be written once its forward bar is fully
    # complete relative to observation time (now_ts_utc). Requesting it earlier is
    # a lookahead violation, not a NULL.
    if now_ts_utc < fwd_end:
        raise CausalLabelError(
            f"lookahead: forward bar [{fwd_start},{fwd_end}) not complete at "
            f"now_ts_utc={now_ts_utc} (horizon {horizon})"
        )
    _starts, by_start = _index_bars(bars, ticker)
    fwd = by_start.get(fwd_start)
    if fwd is None:
        return {"outcome": None, "pts": None, "reconstructable": True,
                "forward_bar_start": fwd_start, "anchor_bar_start": anchor.bar_start_ts_utc,
                "complete": True, "reason": "forward bar missing (NULL label)"}
    pts = round(fwd.close - anchor.close, 4)
    return {
        "outcome": classify_direction_pts(pts, threshold_pts),
        "pts": pts,
        "forward_bar_start": fwd_start,
        "anchor_bar_start": anchor.bar_start_ts_utc,
        "complete": True,
        "reconstructable": True,
    }


def realized_mfe_mae(
    bars: list[Bar],
    ticker: str,
    anchor_ts_utc: float,
    horizon: str,
    *,
    now_ts_utc: float,
) -> dict:
    """Realized favorable/adverse excursion over the horizon window from the OHLC
    path (research label — NOT the Monte-Carlo forecast). Causal: uses only bars
    up to the horizon's forward bar; fails closed on lookahead."""
    if horizon not in HORIZON_MINUTES:
        raise CausalLabelError(f"unknown horizon {horizon!r}")
    n_min = HORIZON_MINUTES[horizon]
    anchor = anchor_bar_for(bars, ticker, anchor_ts_utc)
    if anchor is None:
        return {"mfe": None, "mae": None, "reconstructable": False}
    fwd_start = int((anchor_ts_utc + n_min * BAR_SECONDS) // BAR_SECONDS) * BAR_SECONDS
    if now_ts_utc < fwd_start + BAR_SECONDS:
        raise CausalLabelError("lookahead: horizon window not complete for MFE/MAE")
    starts, by_start = _index_bars(bars, ticker)
    window = [by_start[s] for s in starts if anchor.bar_start_ts_utc < s <= fwd_start]
    if not window:
        return {"mfe": None, "mae": None, "reconstructable": True, "reason": "empty window"}
    hi = max(b.high for b in window)
    lo = min(b.low for b in window)
    return {
        "mfe": round(hi - anchor.close, 4),
        "mae": round(anchor.close - lo, 4),
        "window_bars": len(window),
        "reconstructable": True,
    }
