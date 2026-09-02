"""Gamma-conditioned strategy study v1 — the certified-greeks conditioning test.

Preregistered family (declared before results, no tuning): per candidate at
signal time T, join the LATEST certified greeks_recomputed_v1 row with
ts_utc <= T, staleness <= 900s, low_trust = 0 (fail-closed: no fresh trusted
gamma -> candidate excluded from conditioning, counted). g = net_gamma_rc;
z = robust z vs the trailing 20-SESSION per-session median/IQR (GEX-R1 gex_z
convention, self-slice-consistent). Conditions: NEG (g<0), POS (g>0),
NEG_STRONG (z<=-1), POS_STRONG (z>=+1). Holm across the 4 conditions,
DSR n_trials=4, F2 screen verbatim, plus a DAY-LEVEL gamma-shuffle placebo
replicate with a hard halt (shuffling the session->gamma map must kill edge).

Read gate: refuses to run unless recomputed_greeks_ready() is True.
Regime honesty: per within-window realized-range tercile splits are DISCLOSURE;
every verdict carries SINGLE_REGIME_VALIDITY until the F2 VIX-tercile floor
(>=2 regimes) can be satisfied.
"""

from __future__ import annotations

import json
import random
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from research.incumbent_eval_v1.stats import holm_bonferroni

from .f1_input_gates import gated_label_event_cell_f1
from .f1_s5_spy_battery import (
    DRAFT_COST_ROUND_TRIP_BP,
    DRAFT_STOP_ATR,
    DRAFT_TARGET_ATR,
    DRAFT_VERTICAL_MINUTES,
)
from .f2_tb_grid_runner import (
    CellEconomics,
    _apply_screen,
    _sessions_events,
    deflated_sharpe_prob,
    evaluate_cell,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = str(REPO_ROOT / "data" / "ed_console.db")
REPORT_PATH = REPO_ROOT / "reports" / "gamma_conditioned_study_v1_latest.json"

STALENESS_MAX_SEC = 900.0
Z_STRONG = 1.0
TRAILING_SESSIONS = 20
SEED = 20260724
CONDITIONS = ("NEG", "POS", "NEG_STRONG", "POS_STRONG")
# no_terminal_null law: a null names its door, at the PRODUCER.
NEXT_DEPTH = (
    "GEX-R1 s8.5 Rule-A reversion candidate generator (fade-to-VWAP in "
    "positive-gamma tape) under its own prereg; regime accrual toward the "
    "F2 VIX-tercile floor; QQQ replication via the batch pipeline."
)
MIN_SESSIONS = 30
MIN_CANDIDATES = 60


def robust_z(value: float, history: list[float]) -> float | None:
    """z vs median/IQR of history; None when history is thin or degenerate."""
    if len(history) < TRAILING_SESSIONS:
        return None
    s = sorted(history)
    n = len(s)
    med = s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2])
    q1 = s[max(0, int(0.25 * (n - 1)))]
    q3 = s[min(n - 1, int(0.75 * (n - 1)))]
    iqr = q3 - q1
    if iqr <= 0:
        return None
    return (value - med) / iqr


def condition_membership(g: float, z: float | None) -> set[str]:
    """Which declared conditions a candidate belongs to (sign sets partition)."""
    out: set[str] = set()
    if g < 0:
        out.add("NEG")
    elif g > 0:
        out.add("POS")
    if z is not None and z <= -Z_STRONG:
        out.add("NEG_STRONG")
    if z is not None and z >= Z_STRONG:
        out.add("POS_STRONG")
    return out


def load_certified_gamma(db_path: str, ticker: str) -> list[tuple[float, float]]:
    """(ts_utc, net_gamma_rc) rows, trusted only, ascending. Gate-checked."""
    from tools.backfill_greeks_from_chain_archive_v1 import recomputed_greeks_ready

    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        if not recomputed_greeks_ready(con):
            raise RuntimeError(
                "greeks_recomputed_v1 read gate is NOT ready - run P2 to completion first"
            )
        return [
            (float(r[0]), float(r[1]))
            for r in con.execute(
                "SELECT ts_utc, net_gamma_rc FROM greeks_recomputed_v1 "
                "WHERE ticker = ? AND low_trust = 0 AND net_gamma_rc IS NOT NULL "
                "ORDER BY ts_utc",
                (ticker,),
            )
        ]
    finally:
        con.close()


def latest_gamma_at(rows: list[tuple[float, float]], ts: float) -> float | None:
    """Latest trusted gamma at/before ts within the staleness bound (bisect)."""
    import bisect

    idx = bisect.bisect_right(rows, (ts, float("inf"))) - 1
    if idx < 0:
        return None
    g_ts, g = rows[idx]
    if ts - g_ts > STALENESS_MAX_SEC:
        return None
    return g


def session_gamma_medians(
    rows: list[tuple[float, float]], session_of: Any
) -> dict[str, float]:
    from app.domain.time_et import is_trading_day_et  # RC-58: the one calendar authority

    by_day: dict[str, list[float]] = {}
    for ts, g in rows:
        day = session_of(ts)
        if not is_trading_day_et(day):
            continue      # RC-58: greeks_recomputed_v1 holds 22 of 106 non-trading days
                          # (20.8 percent); a frozen day's median gamma is an artifact
        by_day.setdefault(day, []).append(g)
    out: dict[str, float] = {}
    for day, vals in by_day.items():
        s = sorted(vals)
        n = len(s)
        out[day] = s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2])
    return out


def _label_candidates(db_path: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """SPY candidates through the gated draft-cell labeler with (session, ts, net_bp)."""
    by_day, events, atrs, loader_info = _sessions_events(db_path, "SPY")
    rows: list[dict[str, Any]] = []
    for day in sorted(by_day):
        day_bars = by_day[day]
        atr_series = atrs[day]
        for ev in events[day]:
            r = gated_label_event_cell_f1(
                day_bars, atr_series, ev,
                stop_atr=DRAFT_STOP_ATR, target_atr=DRAFT_TARGET_ATR,
                vertical_minutes=DRAFT_VERTICAL_MINUTES,
                cost_round_trip_bp=DRAFT_COST_ROUND_TRIP_BP,
            )
            if r.withheld_reason is None and r.realized_return_bp_post_cost is not None:
                sig_ts = float(day_bars[ev.signal_bar_index].bar_end_ts_utc)
                rows.append(
                    {"session": day, "signal_ts": sig_ts,
                     "net_bp": float(r.realized_return_bp_post_cost)}
                )
    return rows, loader_info


def _condition_cells(
    candidates: list[dict[str, Any]],
    day_gamma_median: dict[str, float],
    gamma_rows: list[tuple[float, float]],
    *,
    day_override: dict[str, str] | None,
    seed: int,
) -> tuple[dict[str, CellEconomics], dict[str, int]]:
    """Assign candidates to conditions and build per-condition economics.

    day_override (placebo): maps session -> session whose gamma history is used
    instead - the day-level gamma-shuffle that must kill any real edge.
    """
    from app.domain.time_et import et_date_str_from_ts_utc

    sessions_sorted = sorted(day_gamma_median)
    stats = {"n_no_fresh_gamma": 0, "n_no_z_baseline": 0}
    per_condition: dict[str, list[tuple[str, float]]] = {c: [] for c in CONDITIONS}
    for cand in candidates:
        day = cand["session"]
        src_day = (day_override or {}).get(day, day)
        if day_override is None:
            g = latest_gamma_at(gamma_rows, cand["signal_ts"])
        else:
            g = day_gamma_median.get(src_day)
        if g is None:
            stats["n_no_fresh_gamma"] += 1
            continue
        idx = sessions_sorted.index(src_day) if src_day in sessions_sorted else -1
        history = [day_gamma_median[d] for d in sessions_sorted[max(0, idx - TRAILING_SESSIONS):idx]]
        z = robust_z(g, history)
        if z is None:
            stats["n_no_z_baseline"] += 1
        for c in condition_membership(g, z):
            per_condition[c].append((day, cand["net_bp"]))
    _ = et_date_str_from_ts_utc  # session keys already ET dates upstream
    cells = {
        c: evaluate_cell(
            c, rows_c, len(candidates),
            extra_cost_bp=DRAFT_COST_ROUND_TRIP_BP,
            n_boot=1000, shuffle_k=200, seed=seed + i,
        )
        for i, (c, rows_c) in enumerate(sorted(per_condition.items()))
    }
    return cells, stats


def _verdicts(cells: dict[str, CellEconomics], baseline_mean: float | None) -> dict[str, dict[str, Any]]:
    import math

    holm = holm_bonferroni(
        {k: (c.bootstrap.get("p_value") if c.n_sessions >= MIN_SESSIONS else None)
         for k, c in cells.items()}
    )
    sharpes = [c.sharpe for c in cells.values() if c.sharpe is not None]
    sr_std = 0.0
    if len(sharpes) >= 2:
        ms = sum(sharpes) / len(sharpes)
        sr_std = math.sqrt(sum((s - ms) ** 2 for s in sharpes) / (len(sharpes) - 1))
    out: dict[str, dict[str, Any]] = {}
    for k, c in cells.items():
        row: dict[str, Any] = {
            "n_selected": c.n_labeled, "n_sessions": c.n_sessions,
            "mean_net_bp": c.mean_net_bp, "bootstrap": c.bootstrap,
            "stress_bootstrap": c.stress_bootstrap, "shuffle": c.shuffle,
            "holm": holm[k],
        }
        if c.n_sessions < MIN_SESSIONS or c.n_labeled < MIN_CANDIDATES:
            row["verdict"] = "UNDER_SAMPLED"
            out[k] = row
            continue
        dsr = deflated_sharpe_prob(
            list(c.per_session_means.values()), n_trials=len(CONDITIONS),
            sr_std_across_trials=sr_std,
        )
        _apply_screen(row, c, holm_sig=holm[k]["significant"] is True, dsr=dsr,
                      psr_threshold=0.95)
        beats = (
            c.mean_net_bp is not None and baseline_mean is not None
            and c.mean_net_bp > baseline_mean
        )
        row["beats_unconditioned_baseline"] = beats
        if row["verdict"] == "SURVIVE_ECONOMIC" and not beats:
            row["verdict"] = "KILL"
        out[k] = row
    return out


def run_study(db_path: str) -> dict[str, Any]:
    t0 = time.perf_counter()
    candidates, loader_info = _label_candidates(db_path)
    gamma_rows = load_certified_gamma(db_path, "SPY")
    from app.domain.time_et import et_date_str_from_ts_utc

    day_median = session_gamma_medians(gamma_rows, et_date_str_from_ts_utc)
    baseline = evaluate_cell(
        "UNCONDITIONED", [(c["session"], c["net_bp"]) for c in candidates],
        len(candidates), extra_cost_bp=DRAFT_COST_ROUND_TRIP_BP,
        n_boot=1000, shuffle_k=200, seed=SEED + 99,
    )
    cells, stats = _condition_cells(candidates, day_median, gamma_rows,
                                    day_override=None, seed=SEED)
    verdicts = _verdicts(cells, baseline.mean_net_bp)
    days = sorted(day_median)
    shuffled = list(days)
    random.Random(SEED + 777).shuffle(shuffled)
    override = dict(zip(days, shuffled, strict=True))
    p_cells, _p_stats = _condition_cells(candidates, day_median, gamma_rows,
                                         day_override=override, seed=SEED + 500)
    p_verdicts = _verdicts(p_cells, baseline.mean_net_bp)
    placebo_survivors = [k for k, v in p_verdicts.items() if v.get("verdict") == "SURVIVE_ECONOMIC"]
    survivors = [k for k, v in verdicts.items() if v.get("verdict") == "SURVIVE_ECONOMIC"]
    halted = bool(placebo_survivors)
    report = {
        "schema": "gamma_conditioned_study_v1",
        "status": "HALT_PLACEBO_EDGE" if halted else "COMPLETE",
        "validity": "SINGLE_REGIME_VALIDITY (89-session window; F2 VIX-tercile floor unmet)",
        "not_an_admission": "conditioning study, report-only; admission requires operator sign-off",
        "generated_utc": datetime.now(tz=timezone.utc).isoformat(),
        "declared_filter": {
            "staleness_max_sec": STALENESS_MAX_SEC, "z_strong": Z_STRONG,
            "trailing_sessions": TRAILING_SESSIONS, "conditions": list(CONDITIONS),
            "trust": "low_trust=0 rows only; missing fresh gamma excludes the candidate",
        },
        "loader": loader_info,
        "n_candidates": len(candidates),
        "n_trusted_gamma_rows": len(gamma_rows),
        "conditioning_stats": stats,
        "baseline_unconditioned": {
            "n": baseline.n_labeled, "mean_net_bp": baseline.mean_net_bp,
            "bootstrap": baseline.bootstrap,
        },
        "conditions": verdicts,
        "n_survivors": 0 if halted else len(survivors),
        "survivors": [] if halted else survivors,
        "placebo_day_shuffle": {
            "n_survivors": len(placebo_survivors), "survivors": placebo_survivors,
            "hard_halt_engaged": halted,
        },
        "next_depth": NEXT_DEPTH,
        "run_sec": round(time.perf_counter() - t0, 2),
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> int:
    rep = run_study(DEFAULT_DB)
    print(json.dumps(
        {
            "status": rep["status"],
            "n_candidates": rep["n_candidates"],
            "conditioning_stats": rep["conditioning_stats"],
            "baseline_mean_net_bp": rep["baseline_unconditioned"]["mean_net_bp"],
            "conditions": {
                k: {"verdict": v["verdict"], "n": v["n_selected"], "mean_net_bp": v["mean_net_bp"]}
                for k, v in rep["conditions"].items()
            },
            "survivors": rep["survivors"],
            "placebo_survivors": rep["placebo_day_shuffle"]["n_survivors"],
            "run_sec": rep["run_sec"],
            "report": str(REPORT_PATH),
        },
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
