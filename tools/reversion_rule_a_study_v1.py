"""Rule-A reversion study v1 — VWAP-extension fades conditioned on +dealer gamma.

GEX-R1 s8.5 Rule A, preregistered before results: per session, VWAP from
typical price x volume; sigma = rolling std of (close - VWAP) with a 30-bar
warm-up; trigger when |deviation| >= 1.5 sigma (first 30 minutes excluded,
>=5-bar gap); SHORT above / LONG below; condition = fresh (<=900s) trusted
(low_trust=0) net_gamma_rc > 0 through the P2 read gate. Barriers run through
the CERTIFIED F1 labeler with per-candidate multiples (target = |deviation|
back to VWAP, stop = 1 sigma beyond, both / ATR_T-1) so the cost floor,
same-bar ambiguity, session guards and force-flat apply unmodified.

Falsifiable bar (declared): POS must clear the full F2 screen AND beat the
unconditioned ALL arm; day-level gamma-shuffle placebo hard-halts the study.
SINGLE_REGIME_VALIDITY stamped; next_depth emitted at the producer.

Usage: python tools/reversion_rule_a_study_v1.py
"""

from __future__ import annotations

import json
import math
import random
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from research.incumbent_eval_v1.stats import holm_bonferroni  # noqa: E402
from research.pilot_step3.data_loader import Bar1m  # noqa: E402
from research.pilot_step3.event_generation import PilotEvent  # noqa: E402
from research.pilot_step3.f1_input_gates import gated_label_event_cell_f1  # noqa: E402
from research.pilot_step3.f2_tb_grid_runner import (  # noqa: E402
    CellEconomics,
    _apply_screen,
    _sessions_events,
    deflated_sharpe_prob,
    evaluate_cell,
)
from research.pilot_step3.gamma_conditioned_study_v1 import (  # noqa: E402
    latest_gamma_at,
    load_certified_gamma,
    session_gamma_medians,
)
DEFAULT_DB = str(REPO_ROOT / "data" / "ed_console.db")
REPORT_PATH = REPO_ROOT / "reports" / "batch" / "reversion_rule_a_spy_v1.json"

M_SIGMA = 1.5
WARMUP_BARS = 30
MIN_BAR_GAP = 5
STOP_SIGMA = 1.0
COST_ROUND_TRIP_BP = 1.0
SEED = 20260725
ARMS = ("POS", "NEG", "ALL")
MIN_SESSIONS = 30
MIN_CANDIDATES = 60

# no_terminal_null law: a null names its door, at the PRODUCER.
NEXT_DEPTH = (
    "If null: exhaustion-confirmed Rule-A variant (external CR-05 #4 spec class) "
    "+ QQQ replication via the batch pipeline + regime accrual toward the F2 "
    "VIX-tercile floor. If survivor: two-way audit, then operator admission review."
)


@dataclass
class RuleACandidate:
    i_sig: int
    side: str
    deviation: float
    sigma: float
    signal_ts: float


def vwap_and_deviation_sigma(bars: list[Bar1m]) -> tuple[list[float | None], list[float | None]]:
    """(vwap_i, sigma_i) per bar: session VWAP from typical price x volume and
    the rolling std of (close - vwap) over the session so far (warm-up None)."""
    vwaps: list[float | None] = []
    sigmas: list[float | None] = []
    pv = 0.0
    vv = 0.0
    devs: list[float] = []
    for b in bars:
        vol = float(b.volume) if b.volume is not None and b.volume > 0 else 0.0
        tp = (b.high + b.low + b.close) / 3.0
        pv += tp * vol
        vv += vol
        vwap = (pv / vv) if vv > 0 else None
        vwaps.append(vwap)
        if vwap is None:
            sigmas.append(None)
            continue
        devs.append(b.close - vwap)
        if len(devs) < WARMUP_BARS:
            sigmas.append(None)
            continue
        m = sum(devs) / len(devs)
        var = sum((d - m) ** 2 for d in devs) / (len(devs) - 1)
        sigmas.append(math.sqrt(var) if var > 0 else None)
    return vwaps, sigmas


def scan_rule_a_candidates(bars: list[Bar1m]) -> list[RuleACandidate]:
    """Declared trigger: |close - vwap| >= M_SIGMA * sigma, warm-up + gap hygiene."""
    vwaps, sigmas = vwap_and_deviation_sigma(bars)
    out: list[RuleACandidate] = []
    last_i = -(10**9)
    for i, b in enumerate(bars):
        vwap, sigma = vwaps[i], sigmas[i]
        if vwap is None or sigma is None or i < WARMUP_BARS:
            continue
        dev = b.close - vwap
        if abs(dev) < M_SIGMA * sigma or (i - last_i) < MIN_BAR_GAP:
            continue
        last_i = i
        out.append(
            RuleACandidate(
                i_sig=i,
                side="SHORT" if dev > 0 else "LONG",
                deviation=dev,
                sigma=sigma,
                signal_ts=float(b.bar_end_ts_utc),
            )
        )
    return out


def rule_a_multiples(cand: RuleACandidate, atr_t1: float) -> tuple[float, float] | None:
    """(stop_atr, target_atr): stop = STOP_SIGMA*sigma beyond, target = |dev| to VWAP."""
    if atr_t1 <= 0:
        return None
    return (STOP_SIGMA * cand.sigma / atr_t1, abs(cand.deviation) / atr_t1)


def _event_for(cand: RuleACandidate) -> PilotEvent:
    return PilotEvent(
        event_id=f"ruleA-{cand.i_sig}",
        signal_bar_index=cand.i_sig,
        T_close_ts_utc=cand.signal_ts,
        side="LONG" if cand.side == "LONG" else "SHORT",
        sma_fast=0.0, sma_slow=0.0, cusum_pos=0.0, cusum_neg=0.0,
        z_trigger=cand.deviation / cand.sigma if cand.sigma else 0.0,
        candidate_generator_id="RULE_A_VWAP_FADE_POSGAMMA_V1",
    )


def _label_all_candidates(db_path: str) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, int]]:
    by_day, _events, atrs, loader_info = _sessions_events(db_path, "SPY")
    rows: list[dict[str, Any]] = []
    stats = {"n_triggers": 0, "n_labeled": 0, "n_withheld": 0}
    for day in sorted(by_day):
        day_bars = by_day[day]
        atr_series = atrs[day]
        for cand in scan_rule_a_candidates(day_bars):
            stats["n_triggers"] += 1
            i_atr = cand.i_sig - 1
            atr_t1 = atr_series[i_atr] if 0 <= i_atr < len(atr_series) else None
            mults = rule_a_multiples(cand, float(atr_t1)) if atr_t1 else None
            if mults is None:
                stats["n_withheld"] += 1
                continue
            stop_atr, target_atr = mults
            r = gated_label_event_cell_f1(
                day_bars, atr_series, _event_for(cand),
                stop_atr=stop_atr, target_atr=target_atr,
                vertical_minutes=30, cost_round_trip_bp=COST_ROUND_TRIP_BP,
            )
            if r.withheld_reason is not None or r.realized_return_bp_post_cost is None:
                stats["n_withheld"] += 1
                continue
            stats["n_labeled"] += 1
            rows.append(
                {"session": day, "signal_ts": cand.signal_ts,
                 "net_bp": float(r.realized_return_bp_post_cost)}
            )
    return rows, loader_info, stats


def _arm_cells(
    rows: list[dict[str, Any]],
    gamma_rows: list[tuple[float, float]],
    day_median: dict[str, float],
    day_override: dict[str, str] | None,
    seed: int,
) -> tuple[dict[str, CellEconomics], int]:
    per_arm: dict[str, list[tuple[str, float]]] = {a: [] for a in ARMS}
    n_no_gamma = 0
    for r in rows:
        per_arm["ALL"].append((r["session"], r["net_bp"]))
        src_day = (day_override or {}).get(r["session"], r["session"])
        if day_override is None:
            g = latest_gamma_at(gamma_rows, r["signal_ts"])
        else:
            g = day_median.get(src_day)
        if g is None:
            n_no_gamma += 1
            continue
        if g > 0:
            per_arm["POS"].append((r["session"], r["net_bp"]))
        elif g < 0:
            per_arm["NEG"].append((r["session"], r["net_bp"]))
    cells = {
        a: evaluate_cell(
            a, arm_rows, len(rows), extra_cost_bp=COST_ROUND_TRIP_BP,
            n_boot=1000, shuffle_k=200, seed=seed + i,
        )
        for i, (a, arm_rows) in enumerate(sorted(per_arm.items()))
    }
    return cells, n_no_gamma


def _arm_verdicts(cells: dict[str, CellEconomics]) -> dict[str, dict[str, Any]]:
    holm = holm_bonferroni(
        {k: (c.bootstrap.get("p_value") if c.n_sessions >= MIN_SESSIONS else None)
         for k, c in cells.items()}
    )
    sharpes = [c.sharpe for c in cells.values() if c.sharpe is not None]
    sr_std = 0.0
    if len(sharpes) >= 2:
        ms = sum(sharpes) / len(sharpes)
        sr_std = math.sqrt(sum((s - ms) ** 2 for s in sharpes) / (len(sharpes) - 1))
    baseline_mean = cells["ALL"].mean_net_bp
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
            list(c.per_session_means.values()), n_trials=len(ARMS),
            sr_std_across_trials=sr_std,
        )
        _apply_screen(row, c, holm_sig=holm[k]["significant"] is True, dsr=dsr,
                      psr_threshold=0.95)
        beats = (
            k == "ALL"
            or (c.mean_net_bp is not None and baseline_mean is not None
                and c.mean_net_bp > baseline_mean)
        )
        row["beats_unconditioned_all"] = beats
        if row["verdict"] == "SURVIVE_ECONOMIC" and not beats:
            row["verdict"] = "KILL"
        out[k] = row
    return out


def run_study(db_path: str) -> dict[str, Any]:
    from app.domain.time_et import et_date_str_from_ts_utc

    t0 = time.perf_counter()
    rows, loader_info, gen_stats = _label_all_candidates(db_path)
    gamma_rows = load_certified_gamma(db_path, "SPY")
    day_median = session_gamma_medians(gamma_rows, et_date_str_from_ts_utc)
    cells, n_no_gamma = _arm_cells(rows, gamma_rows, day_median, None, SEED)
    verdicts = _arm_verdicts(cells)
    days = sorted(day_median)
    shuffled = list(days)
    random.Random(SEED + 777).shuffle(shuffled)
    p_cells, _n = _arm_cells(rows, gamma_rows, day_median,
                             dict(zip(days, shuffled, strict=True)), SEED + 500)
    p_verdicts = _arm_verdicts(p_cells)
    placebo_survivors = [k for k, v in p_verdicts.items()
                         if k != "ALL" and v.get("verdict") == "SURVIVE_ECONOMIC"]
    survivors = [k for k, v in verdicts.items() if v.get("verdict") == "SURVIVE_ECONOMIC"]
    halted = bool(placebo_survivors)
    report = {
        "schema": "reversion_rule_a_spy_v1",
        "status": "HALT_PLACEBO_EDGE" if halted else "COMPLETE",
        "validity": "SINGLE_REGIME_VALIDITY (89-session window; F2 VIX-tercile floor unmet)",
        "not_an_admission": "report-only; survival requires two-way audit + operator admission",
        "generated_utc": datetime.now(tz=timezone.utc).isoformat(),
        "declared_generator": {
            "id": "RULE_A_VWAP_FADE_POSGAMMA_V1",
            "m_sigma": M_SIGMA, "warmup_bars": WARMUP_BARS, "min_bar_gap": MIN_BAR_GAP,
            "stop_sigma_beyond": STOP_SIGMA, "target": "back to VWAP-at-signal",
            "vertical_minutes": 30, "cost_round_trip_bp": COST_ROUND_TRIP_BP,
            "condition": "fresh (<=900s) trusted (low_trust=0) net_gamma_rc > 0",
            "falsifiable_bar": "POS clears full F2 screen AND beats unconditioned ALL",
        },
        "loader": loader_info,
        "generator_stats": gen_stats,
        "n_candidates_labeled": len(rows),
        "n_no_fresh_gamma": n_no_gamma,
        "arms": verdicts,
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
            "generator_stats": rep["generator_stats"],
            "n_no_fresh_gamma": rep["n_no_fresh_gamma"],
            "arms": {k: {"verdict": v["verdict"], "n": v["n_selected"],
                         "mean_net_bp": v["mean_net_bp"]}
                     for k, v in rep["arms"].items()},
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
