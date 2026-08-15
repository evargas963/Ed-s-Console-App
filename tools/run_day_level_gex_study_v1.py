"""Day-level GEX study v1 — GEX-R1 s8.6 at the unit where the evidence lives.

Preregistered design (declared before results): every 1.5-sigma VWAP-extension
trigger bar spawns TWO candidates through the CERTIFIED F1 labeler with
identical costs — FADE (Rule A: target back to VWAP-at-signal, stop 1 sigma
beyond the extreme) and CHASE (Rule B mirror: target 1.5 sigma further with
the extension, stop 1 sigma back toward VWAP). Per session:
    regime_score_day = sum(fade net bp) - sum(chase net bp)
Morning gamma = FIRST trusted (low_trust=0) greeks_recomputed_v1 row in
09:30-10:15 ET, via the P2 read gate.

Primary tests (s8.6 verbatim, adapted to the economic unit):
 1. Association: Spearman(morning_gamma, regime_score) with a gamma->day
    shuffle permutation p (K=2000) - the original finding's replication at
    the PnL unit.
 2. Conditioned strategy: each day run the rule gamma selects (g>0 -> FADE,
    g<0 -> CHASE); success bar = mean net bp > 0, session-bootstrap CI > 0,
    BEATS THE BEST unconditional rule, survives 2x cost and the gamma->day
    shuffle (K=2000). Thin n (= sessions) is disclosed, never laundered.

Usage: python tools/run_day_level_gex_study_v1.py
"""

from __future__ import annotations

import json
import math
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from research.pilot_step3.f1_input_gates import gated_label_event_cell_f1  # noqa: E402
from research.pilot_step3.f2_tb_grid_runner import _sessions_events, bootstrap_mean_ci  # noqa: E402
from research.pilot_step3.gamma_conditioned_study_v1 import load_certified_gamma  # noqa: E402
from tools.reversion_rule_a_study_v1 import (  # noqa: E402
    M_SIGMA,
    STOP_SIGMA,
    RuleACandidate,
    _event_for,
    rule_a_multiples,
    scan_rule_a_candidates,
)

DEFAULT_DB = str(REPO_ROOT / "data" / "ed_console.db")
REPORT_PATH = REPO_ROOT / "reports" / "batch" / "day_level_gex_study_spy_v1.json"

COST_ROUND_TRIP_BP = 1.0
VERTICAL_MINUTES = 30
MORNING_WINDOW_MINS = 45          # 09:30-10:15 ET per GEX-R1 s9
PERMUTATIONS = 2000
SEED = 20260726
MIN_SESSIONS = 40

# no_terminal_null law: a null names its door, at the PRODUCER.
NEXT_DEPTH = (
    "If null: terrain gamma-sign stays a DISPLAY conditioning lane "
    "(explains-not-predicts); QQQ replication via the batch pipeline; regime "
    "accrual toward the F2 VIX-tercile floor; external multi-year chain data "
    "for cross-regime power. If survivor: two-way audit, paper-trade card, "
    "operator admission review - never live wiring from one regime."
)


def chase_multiples(cand: RuleACandidate, atr_t1: float) -> tuple[float, float] | None:
    """Rule-B mirror geometry: stop 1 sigma back toward VWAP, target M_SIGMA
    sigma further WITH the extension."""
    if atr_t1 <= 0:
        return None
    return (STOP_SIGMA * cand.sigma / atr_t1, M_SIGMA * cand.sigma / atr_t1)


def chase_event(cand: RuleACandidate):
    ev = _event_for(cand)
    flipped = "LONG" if cand.side == "SHORT" else "SHORT"
    return type(ev)(
        event_id=ev.event_id + "-chase", signal_bar_index=ev.signal_bar_index,
        T_close_ts_utc=ev.T_close_ts_utc, side=flipped, sma_fast=0.0, sma_slow=0.0,
        cusum_pos=0.0, cusum_neg=0.0, z_trigger=ev.z_trigger,
        candidate_generator_id="RULE_B_VWAP_CHASE_MIRROR_V1",
    )


def spearman(xs: list[float], ys: list[float]) -> float | None:
    """Spearman rank correlation (average ranks for ties)."""
    n = len(xs)
    if n < 3 or n != len(ys):
        return None

    def _ranks(vals: list[float]) -> list[float]:
        order = sorted(range(n), key=lambda i: vals[i])
        ranks = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and vals[order[j + 1]] == vals[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                ranks[order[k]] = avg
            i = j + 1
        return ranks

    rx, ry = _ranks(xs), _ranks(ys)
    mx = sum(rx) / n
    my = sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    vx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    vy = math.sqrt(sum((b - my) ** 2 for b in ry))
    if vx <= 0 or vy <= 0:
        return None
    return cov / (vx * vy)


def morning_gamma_by_session(
    gamma_rows: list[tuple[float, float]]
) -> dict[str, float]:
    """First trusted gamma inside 09:30-10:15 ET per session."""
    from time_et import (RTH_START_MINS, et_date_str_from_ts_utc,
                         et_minute_total_from_ts_utc, is_trading_day_et)  # RC-58

    out: dict[str, float] = {}
    for ts, g in gamma_rows:                       # ascending ts
        mins = et_minute_total_from_ts_utc(ts) - RTH_START_MINS
        if not (0 <= mins <= MORNING_WINDOW_MINS):
            continue
        day = et_date_str_from_ts_utc(ts)
        if not is_trading_day_et(day):
            continue          # RC-58: the intersection with gated pnls happened to filter
                              # weekends out; the loader itself must not rely on that
        if day not in out:
            out[day] = g
    return out


def _session_rule_pnls(db_path: str) -> tuple[dict[str, dict[str, float]], dict[str, Any]]:
    """Per session: summed net bp of FADE and CHASE candidates (identical triggers)."""
    by_day, _ev, atrs, loader_info = _sessions_events(db_path, "SPY")
    out: dict[str, dict[str, float]] = {}
    stats = {"n_triggers": 0, "n_fade_labeled": 0, "n_chase_labeled": 0}
    for day in sorted(by_day):
        day_bars = by_day[day]
        atr_series = atrs[day]
        fade_sum = 0.0
        chase_sum = 0.0
        for cand in scan_rule_a_candidates(day_bars):
            stats["n_triggers"] += 1
            i_atr = cand.i_sig - 1
            atr_t1 = atr_series[i_atr] if 0 <= i_atr < len(atr_series) else None
            if not atr_t1 or atr_t1 <= 0:
                continue
            fm = rule_a_multiples(cand, float(atr_t1))
            cm = chase_multiples(cand, float(atr_t1))
            if fm is None or cm is None:
                continue
            rf = gated_label_event_cell_f1(
                day_bars, atr_series, _event_for(cand),
                stop_atr=fm[0], target_atr=fm[1],
                vertical_minutes=VERTICAL_MINUTES, cost_round_trip_bp=COST_ROUND_TRIP_BP,
            )
            rc = gated_label_event_cell_f1(
                day_bars, atr_series, chase_event(cand),
                stop_atr=cm[0], target_atr=cm[1],
                vertical_minutes=VERTICAL_MINUTES, cost_round_trip_bp=COST_ROUND_TRIP_BP,
            )
            if rf.withheld_reason is None and rf.realized_return_bp_post_cost is not None:
                fade_sum += float(rf.realized_return_bp_post_cost)
                stats["n_fade_labeled"] += 1
            if rc.withheld_reason is None and rc.realized_return_bp_post_cost is not None:
                chase_sum += float(rc.realized_return_bp_post_cost)
                stats["n_chase_labeled"] += 1
        out[day] = {"fade": fade_sum, "chase": chase_sum, "regime_score": fade_sum - chase_sum}
    return out, {"loader": loader_info, **stats}


def _permutation_p(observed: float, values: list[float], pair_stat, k: int, seed: int) -> float:
    """Two-sided permutation p for a statistic recomputed under value shuffles."""
    rng = random.Random(seed)
    hits = 0
    for _ in range(k):
        shuffled = list(values)
        rng.shuffle(shuffled)
        s = pair_stat(shuffled)
        if s is not None and abs(s) >= abs(observed):
            hits += 1
    return max(hits / k, 1.0 / k)


def _association(days: list[str], morning: dict[str, float], pnls: dict[str, dict[str, float]]) -> dict[str, Any]:
    gammas = [morning[d] for d in days]
    scores = [pnls[d]["regime_score"] for d in days]
    rho = spearman(gammas, scores)
    rho_p = (
        _permutation_p(rho, gammas, lambda gs: spearman(gs, scores), PERMUTATIONS, SEED)
        if rho is not None
        else None
    )
    return {"spearman_gamma_vs_regime_score": rho, "permutation_p": rho_p,
            "n_permutations": PERMUTATIONS}


def _s86_screen(
    *, n_days: int, mean_cond: float | None, ci: list[float] | None,
    best_uncond: float | None, strat_p: float | None, sci: list[float] | None,
) -> dict[str, bool]:
    """The declared s8.6 success bar as six named booleans."""
    return {
        "n_sessions_ok": n_days >= MIN_SESSIONS,
        "mean_positive": mean_cond is not None and mean_cond > 0,
        "ci95_above_zero": ci is not None and ci[0] > 0,
        "beats_best_unconditional": (
            mean_cond is not None and best_uncond is not None and mean_cond > best_uncond
        ),
        "gamma_shuffle_p_lt_05": strat_p is not None and strat_p < 0.05,
        "stress_2x_ok": sci is not None and sci[0] > 0,
    }


def _conditioned_strategy(
    days: list[str], morning: dict[str, float], pnls: dict[str, dict[str, float]]
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """(strategy block, baselines block, screen block) for the s8.6 bar."""
    gammas = [morning[d] for d in days]
    per_day_cond = [pnls[d]["fade"] if morning[d] > 0 else pnls[d]["chase"] for d in days]
    mean_cond = sum(per_day_cond) / len(per_day_cond) if per_day_cond else None
    boot = bootstrap_mean_ci(per_day_cond, n_boot=2000, seed=SEED + 1)
    mean_fade = sum(pnls[d]["fade"] for d in days) / len(days) if days else None
    mean_chase = sum(pnls[d]["chase"] for d in days) / len(days) if days else None
    uncond = [v for v in (mean_fade, mean_chase) if v is not None]
    best_uncond = max(uncond) if uncond else None
    strat_p = (
        _permutation_p(
            mean_cond, gammas,
            lambda gs: sum(
                pnls[d]["fade"] if g > 0 else pnls[d]["chase"]
                for d, g in zip(days, gs, strict=True)
            ) / len(days),
            PERMUTATIONS, SEED + 2,
        )
        if mean_cond is not None
        else None
    )
    boot_stress = bootstrap_mean_ci(
        [v - COST_ROUND_TRIP_BP for v in per_day_cond], n_boot=2000, seed=SEED + 3
    )
    screen = _s86_screen(
        n_days=len(days), mean_cond=mean_cond, ci=boot.get("ci95"),
        best_uncond=best_uncond, strat_p=strat_p, sci=boot_stress.get("ci95"),
    )
    strategy = {"mean_net_bp_per_session": mean_cond, "bootstrap": boot,
                "stress_2x_bootstrap": boot_stress, "gamma_shuffle_p": strat_p}
    baselines = {"always_fade_mean_bp": mean_fade, "always_chase_mean_bp": mean_chase,
                 "best_unconditional": best_uncond}
    return strategy, baselines, screen


def run_study(db_path: str) -> dict[str, Any]:
    t0 = time.perf_counter()
    pnls, gen_stats = _session_rule_pnls(db_path)
    gamma_rows = load_certified_gamma(db_path, "SPY")
    morning = morning_gamma_by_session(gamma_rows)
    days = sorted(set(pnls) & set(morning))
    n_no_morning = len(pnls) - len(days)
    association = _association(days, morning, pnls)
    strategy, baselines, screen = _conditioned_strategy(days, morning, pnls)
    survive = all(screen.values())
    report = {
        "schema": "day_level_gex_study_spy_v1",
        "status": "COMPLETE",
        "verdict": "SURVIVE_ECONOMIC" if survive else "KILL",
        "validity": "SINGLE_REGIME_VALIDITY (one ~4-month vol regime; F2 VIX-tercile floor unmet)",
        "not_an_admission": "report-only; survival requires two-way audit + operator admission",
        "generated_utc": datetime.now(tz=timezone.utc).isoformat(),
        "declared_design": {
            "unit": "session", "trigger": f"{M_SIGMA} sigma VWAP extension (shared by both rules)",
            "fade": "target back to VWAP, stop 1 sigma beyond (Rule A)",
            "chase": "target 1.5 sigma further, stop 1 sigma back (Rule B mirror)",
            "regime_score": "sum(fade bp) - sum(chase bp) per session",
            "morning_gamma": "first trusted greeks_recomputed_v1 row 09:30-10:15 ET",
            "conditioned_strategy": "g>0 -> fade day; g<0 -> chase day",
            "success_bar": "mean>0 AND CI>0 AND beats best unconditional AND shuffle p<0.05 AND 2x cost",
        },
        "generator_stats": gen_stats,
        "n_sessions_scored": len(days),
        "n_sessions_no_morning_gamma": n_no_morning,
        "association": association,
        "conditioned_strategy": strategy,
        "baselines": baselines,
        "screen": screen,
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
            "verdict": rep["verdict"],
            "n_sessions_scored": rep["n_sessions_scored"],
            "association": rep["association"],
            "conditioned_mean_bp": rep["conditioned_strategy"]["mean_net_bp_per_session"],
            "gamma_shuffle_p": rep["conditioned_strategy"]["gamma_shuffle_p"],
            "baselines": rep["baselines"],
            "screen": rep["screen"],
            "run_sec": rep["run_sec"],
            "report": str(REPORT_PATH),
        },
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
