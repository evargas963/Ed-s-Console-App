"""
Per-cell pilot metrics and PASS/FAIL flags (pilot v1).

purge_embargo_status: NOT_IMPLEMENTED_IN_PILOT_V1 — do not fabricate purge metrics.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Iterable

from .labeling import TripleBarrierResult


@dataclass
class CellMetrics:
    cell_id: str
    stop_atr: float
    target_atr: float
    vertical_minutes: int
    raw_events: int = 0
    valid_events: int = 0
    withheld_events: int = 0
    win_n: int = 0
    loss_n: int = 0
    timeout_n: int = 0
    force_flat_n: int = 0
    same_bar_ambiguous_n: int = 0
    reject_n: int = 0
    mean_realized_R: float | None = None
    mean_realized_return_bp: float | None = None
    mean_realized_return_bp_post_cost: float | None = None
    runtime_sec: float = 0.0
    data_gaps_flag: bool = False
    purge_embargo_status: str = "NOT_IMPLEMENTED_IN_PILOT_V1"
    effective_n: float | None = None
    pass_flags: list[str] = field(default_factory=list)
    fail_flags: list[str] = field(default_factory=list)


def _mean(xs: list[float]) -> float | None:
    return float(sum(xs) / len(xs)) if xs else None


def aggregate_cell(
    cell_id: str,
    stop_atr: float,
    target_atr: float,
    vertical_minutes: int,
    labels: Iterable[TripleBarrierResult],
    *,
    raw_event_count: int,
    rules: dict[str, Any],
    runtime_sec: float,
    data_gaps_flag: bool,
) -> CellMetrics:
    m = CellMetrics(
        cell_id=cell_id,
        stop_atr=stop_atr,
        target_atr=target_atr,
        vertical_minutes=vertical_minutes,
        runtime_sec=runtime_sec,
        data_gaps_flag=data_gaps_flag,
    )
    m.raw_events = int(raw_event_count)
    rs: list[float] = []
    bps: list[float] = []
    bpsp: list[float] = []

    for lb in labels:
        if lb.withheld_reason:
            m.withheld_events += 1
            continue
        if lb.label_conservative is None:
            m.withheld_events += 1
            continue
        m.valid_events += 1
        c = lb.label_conservative
        if c == "WIN":
            m.win_n += 1
        elif c == "LOSS":
            m.loss_n += 1
        else:
            m.timeout_n += 1
        if lb.force_flat and lb.barrier_hit == "FORCE_FLAT":
            m.force_flat_n += 1
        if lb.same_bar_ambiguous:
            m.same_bar_ambiguous_n += 1
        if lb.label_reject == "REJECT":
            m.reject_n += 1
        if lb.realized_R is not None:
            rs.append(float(lb.realized_R))
        if lb.realized_return_bp is not None:
            bps.append(float(lb.realized_return_bp))
        if lb.realized_return_bp_post_cost is not None:
            bpsp.append(float(lb.realized_return_bp_post_cost))

    n = max(m.valid_events, 1)
    win_pct = 100.0 * m.win_n / n
    loss_pct = 100.0 * m.loss_n / n
    timeout_pct = 100.0 * m.timeout_n / n

    m.mean_realized_R = _mean(rs)
    m.mean_realized_return_bp = _mean(bps)
    m.mean_realized_return_bp_post_cost = _mean(bpsp)
    m.effective_n = float(m.valid_events)

    th = rules["timeout_pct"]
    if timeout_pct < th["min"]:
        m.fail_flags.append("TIMEOUT_pct_below_min")
    if timeout_pct > th["max"]:
        m.fail_flags.append("TIMEOUT_pct_above_max")
    if min(win_pct, loss_pct) < rules["min_win_loss_pct"]:
        m.fail_flags.append("WIN_or_LOSS_pct_too_low")
    if m.valid_events < rules["min_valid_events"]:
        m.fail_flags.append("valid_events_below_min")
    amb_rate = 100.0 * m.same_bar_ambiguous_n / n
    if amb_rate > rules["same_bar_ambiguous_max_pct"]:
        m.fail_flags.append("same_bar_ambiguity_dominates")
    if m.mean_realized_return_bp_post_cost is not None and m.mean_realized_return_bp_post_cost <= 0:
        m.fail_flags.append("mean_post_cost_return_non_positive")
    if data_gaps_flag:
        m.fail_flags.append("data_gaps_affect_labels")

    if not m.fail_flags:
        m.pass_flags.append("cell_pilot_checks_passed")

    return m


def cell_to_dict(cm: CellMetrics) -> dict[str, Any]:
    n = max(cm.valid_events, 1)
    return {
        "cell_id": cm.cell_id,
        "stop_atr": cm.stop_atr,
        "target_atr": cm.target_atr,
        "vertical_minutes": cm.vertical_minutes,
        "raw_events": cm.raw_events,
        "valid_events": cm.valid_events,
        "withheld_events": cm.withheld_events,
        "WIN_pct": 100.0 * cm.win_n / n,
        "LOSS_pct": 100.0 * cm.loss_n / n,
        "TIMEOUT_pct": 100.0 * cm.timeout_n / n,
        "FORCE_FLAT_count": cm.force_flat_n,
        "FORCE_FLAT_pct": 100.0 * cm.force_flat_n / n,
        "same_bar_ambiguous_count": cm.same_bar_ambiguous_n,
        "same_bar_ambiguous_pct": 100.0 * cm.same_bar_ambiguous_n / n,
        "REJECT_count": cm.reject_n,
        "REJECT_pct": 100.0 * cm.reject_n / n,
        "mean_realized_R": cm.mean_realized_R,
        "mean_realized_return_bp": cm.mean_realized_return_bp,
        "mean_realized_return_bp_post_cost": cm.mean_realized_return_bp_post_cost,
        "runtime_sec": cm.runtime_sec,
        "data_gaps_flag": cm.data_gaps_flag,
        "purge_embargo_status": cm.purge_embargo_status,
        "effective_n": cm.effective_n,
        "PASS": len(cm.fail_flags) == 0,
        "fail_flags": cm.fail_flags,
        "pass_flags": cm.pass_flags,
    }
