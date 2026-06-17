"""Pure helpers for card direction vs price-movement integrity audits (read-only)."""
from __future__ import annotations

import datetime
from typing import Any, Optional

HORIZON_SLUGS: tuple[str, ...] = ("1c", "5c", "15c", "60c")
HORIZON_CARD_LABELS: dict[str, str] = {
    "1c": "1M",
    "5c": "5M",
    "15c": "15M",
    "60c": "60M",
}
HORIZON_FORWARD_BARS: dict[str, int] = {"1c": 1, "5c": 5, "15c": 15, "60c": 60}

DEFAULT_ALLOWED_DATA_AGE_SECONDS = 120.0
DEFAULT_MIN_DECLINE_MINUTES = 45
DEFAULT_MIN_DRAWDOWN_FRACTION = 0.003

CLASS_VALID_REVERSAL = "VALID_REVERSAL_FORECAST"
CLASS_VALID_MEAN_REVERSION = "VALID_MEAN_REVERSION_FORECAST"
CLASS_VALID_HTF_LONG = "VALID_PULLBACK_WITH_HIGHER_TIMEFRAME_LONG"
CLASS_STALE_PAYLOAD = "STALE_CARD_PAYLOAD"
CLASS_FROZEN_BACKEND = "FROZEN_BACKEND_SIGNAL"
CLASS_FRONTEND_STALE = "FRONTEND_RENDER_STALE"
CLASS_MISSING_GUARD = "MISSING_PRICE_INTEGRITY_GUARD"
CLASS_MODEL_DRIFT = "MODEL_DIRECTION_DRIFT"
CLASS_INSUFFICIENT = "INSUFFICIENT_EVIDENCE"

ET = datetime.timezone(datetime.timedelta(hours=-4))


def ts_et_label(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).astimezone(ET).strftime(
        "%Y-%m-%d %H:%M:%S ET"
    )


def direction_sign(direction: Optional[str]) -> int:
    d = (direction or "").upper().strip()
    if d in ("LONG", "UP", "BUY"):
        return 1
    if d in ("SHORT", "DOWN", "SELL"):
        return -1
    return 0


def return_sign(value: Optional[float], *, epsilon: float = 1e-9) -> int:
    if value is None:
        return 0
    if value > epsilon:
        return 1
    if value < -epsilon:
        return -1
    return 0


def direction_hit(displayed_direction: Optional[str], forward_realized_return: Optional[float]) -> Optional[bool]:
    ds = direction_sign(displayed_direction)
    rs = return_sign(forward_realized_return)
    if ds == 0 or rs == 0:
        return None
    return ds == rs


def trailing_conflict(displayed_direction: Optional[str], trailing_realized_return: Optional[float]) -> bool:
    ds = direction_sign(displayed_direction)
    rs = return_sign(trailing_realized_return)
    if ds == 0 or rs == 0:
        return False
    return ds != rs


def stale_conflict(
    *,
    trailing_conflict_flag: bool,
    data_age_seconds: Optional[float],
    allowed_age_seconds: float = DEFAULT_ALLOWED_DATA_AGE_SECONDS,
) -> bool:
    if not trailing_conflict_flag:
        return False
    if data_age_seconds is None:
        return False
    return float(data_age_seconds) > float(allowed_age_seconds)


def trailing_return_at_index(prices: list[float], index: int, bars_back: int) -> Optional[float]:
    if index < bars_back or index >= len(prices):
        return None
    base = prices[index - bars_back]
    if base is None or base == 0:
        return None
    return (prices[index] - base) / base


def forward_return_at_index(prices: list[float], index: int, bars_forward: int) -> Optional[float]:
    j = index + bars_forward
    if index < 0 or j >= len(prices):
        return None
    base = prices[index]
    if base is None or base == 0:
        return None
    return (prices[j] - base) / base


def drawdown_from_session_high(prices: list[float], index: int) -> Optional[float]:
    if index < 0 or index >= len(prices):
        return None
    hi = max(prices[: index + 1])
    if hi == 0:
        return None
    return (prices[index] - hi) / hi


def find_decline_intervals(
    ts_list: list[float],
    prices: list[float],
    *,
    min_decline_minutes: int = DEFAULT_MIN_DECLINE_MINUTES,
    min_drawdown_fraction: float = DEFAULT_MIN_DRAWDOWN_FRACTION,
    trailing_bars: int = 15,
) -> list[dict[str, Any]]:
    """Contiguous RTH intervals with sustained negative trailing return + drawdown."""
    if len(ts_list) != len(prices) or len(prices) < trailing_bars + 2:
        return []

    intervals: list[dict[str, Any]] = []
    run_start: Optional[int] = None
    min_bars = max(trailing_bars, min_decline_minutes)

    for i in range(trailing_bars, len(prices)):
        tr = trailing_return_at_index(prices, i, trailing_bars)
        dd = drawdown_from_session_high(prices, i)
        declining = (
            tr is not None
            and tr < 0
            and dd is not None
            and dd <= -abs(min_drawdown_fraction)
        )
        if declining:
            if run_start is None:
                run_start = i - trailing_bars
        elif run_start is not None:
            run_end = i
            if run_end - run_start >= min_bars:
                intervals.append(_interval_row(ts_list, prices, run_start, run_end))
            run_start = None

    if run_start is not None and len(prices) - run_start >= min_bars:
        intervals.append(_interval_row(ts_list, prices, run_start, len(prices) - 1))

    return intervals


def _interval_row(
    ts_list: list[float],
    prices: list[float],
    start_idx: int,
    end_idx: int,
) -> dict[str, Any]:
    start_ts = float(ts_list[start_idx])
    end_ts = float(ts_list[end_idx])
    seg = prices[start_idx : end_idx + 1]
    seg_hi = max(seg) if seg else None
    seg_lo = min(seg) if seg else None
    seg_move = (seg[-1] - seg[0]) / seg[0] if seg and seg[0] else None
    return {
        "start_idx": start_idx,
        "end_idx": end_idx,
        "start_ts_utc": start_ts,
        "end_ts_utc": end_ts,
        "start_ts_et": ts_et_label(start_ts),
        "end_ts_et": ts_et_label(end_ts),
        "duration_minutes": round((end_ts - start_ts) / 60.0, 1),
        "segment_return": round(seg_move, 6) if seg_move is not None else None,
        "segment_high": seg_hi,
        "segment_low": seg_lo,
    }


def mhap_direction_map(mhap_rows: list[dict[str, Any]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in mhap_rows or []:
        hz = str(row.get("horizon") or "").lower()
        call = str(row.get("call") or "").upper()
        if hz in HORIZON_SLUGS and call:
            out[hz] = call
    return out


def fusion_direction_from_probs(up: Optional[float], down: Optional[float], flat: Optional[float]) -> str:
    triple = {
        "LONG": float(up or 0.0),
        "SHORT": float(down or 0.0),
        "FLAT": float(flat or 0.0),
    }
    best = max(triple, key=triple.get)
    if triple[best] <= 0:
        return "WAIT"
    return best if best != "FLAT" else "FLAT"


def classify_long_during_decline(
    *,
    displayed_direction: str,
    trailing_return_1m: Optional[float],
    trailing_return_60m: Optional[float],
    forward_return_1m: Optional[float],
    forward_return_60m: Optional[float],
    data_age_seconds: Optional[float],
    payload_frozen: bool,
    fusion_stayed_long: bool,
    histogram_stayed_long: bool,
    final_tradeable: Optional[bool],
    allowed_age_seconds: float = DEFAULT_ALLOWED_DATA_AGE_SECONDS,
) -> list[str]:
    """Classify LONG (or directional) cards during a price-decline window."""
    tags: list[str] = []
    d = direction_sign(displayed_direction)
    if d != 1:
        return tags

    tr_conflict = trailing_conflict(displayed_direction, trailing_return_1m)
    if not tr_conflict:
        return tags

    if payload_frozen:
        tags.append(CLASS_FROZEN_BACKEND)
    if stale_conflict(
        trailing_conflict_flag=True,
        data_age_seconds=data_age_seconds,
        allowed_age_seconds=allowed_age_seconds,
    ):
        tags.append(CLASS_STALE_PAYLOAD)

    fwd1_hit = direction_hit(displayed_direction, forward_return_1m)
    fwd60_hit = direction_hit(displayed_direction, forward_return_60m)

    if fwd1_hit is True or fwd60_hit is True:
        if return_sign(trailing_return_1m) == -1 and return_sign(forward_return_1m) == 1:
            tags.append(CLASS_VALID_REVERSAL)
        if return_sign(trailing_return_60m) == -1 and return_sign(forward_return_60m) == 1:
            tags.append(CLASS_VALID_MEAN_REVERSION)
    elif fwd1_hit is False and fwd60_hit is True:
        tags.append(CLASS_VALID_HTF_LONG)
    elif fusion_stayed_long and histogram_stayed_long and fwd1_hit is False:
        tags.append(CLASS_MODEL_DRIFT)

    if tr_conflict and final_tradeable is False and not tags:
        tags.append(CLASS_MISSING_GUARD)

    if not tags:
        tags.append(CLASS_INSUFFICIENT)

    return sorted(set(tags))


def aggregate_horizon_metrics(rows: list[dict[str, Any]], horizon: str) -> dict[str, Any]:
    key = f"horizon_{horizon}"
    subset = [r for r in rows if r.get(key)]
    hits = [r[key]["direction_hit"] for r in subset if r[key].get("direction_hit") is not None]
    misses = [h for h in hits if h is False]
    trailing_conflicts = sum(1 for r in subset if r[key].get("trailing_conflict"))
    stale_conflicts = sum(1 for r in subset if r[key].get("stale_conflict"))
    return {
        "horizon": horizon,
        "samples": len(subset),
        "direction_hits": sum(1 for h in hits if h is True),
        "direction_misses": len(misses),
        "direction_hit_rate": round(sum(1 for h in hits if h is True) / len(hits), 4) if hits else None,
        "trailing_conflict_count": trailing_conflicts,
        "stale_conflict_count": stale_conflicts,
    }


def ui_card_state_from_probe(probe: dict[str, Any]) -> dict[str, str]:
    """Derive ALL/PLAN display contract from replay probe (no browser)."""
    from tools.replay_money_path_probe import ui_card_derivation

    ui = ui_card_derivation(
        str(probe.get("final_bias") or "WAIT"),
        bool(probe.get("final_tradeable")),
        str(probe.get("entry_state") or "no_setup"),
    )
    return {
        "ALL_direction": ui.get("ALL_pill_direction") or "FLAT",
        "PLAN_state": ui.get("PLAN_pill_state") or "NO SETUP",
        "ALL_visual_state": ui.get("ALL_pill_visual_state") or "dim/neutral",
    }
