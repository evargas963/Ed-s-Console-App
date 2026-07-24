"""F2 grid runner — 175-cell triple-barrier economics under F2_TB_GRID_V1_PREREG_V1.

Report-only. Candidates are generated ONCE per session (frozen per-session
CUSUM generator), then every preregistered (stop, target, vertical) cell labels
the same candidates through the S3-gated F1 labeler and is scored economically:
session-blocked bootstrap CI, Holm across the family, DSR against the
expected-max Sharpe of 175 trials, 2x-cost stress, per-cell sign-shuffle null.

Placebo hard gate: the identical verdict pipeline runs on a sign-shuffled
replicate of the whole grid; ANY placebo survivor halts the study
(HALT_PLACEBO_EDGE) and no real survivors are reported.
"""

from __future__ import annotations

import json
import math
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from research.incumbent_eval_v1.stats import holm_bonferroni

from .data_loader import Bar1m, load_spy_1m_bars
from .event_generation import PilotEvent, generate_events
from .f1_input_gates import gated_label_event_cell_f1
from .f1_s5_spy_battery import F1_DRAFT_CANDIDATE_CONFIG, preflight
from .labeling import build_atr_series

REPO_ROOT = Path(__file__).resolve().parents[2]
PREREG_PATH = Path(__file__).resolve().parent / "f2_tb_grid_prereg_v1.json"
DEFAULT_DB = str(REPO_ROOT / "data" / "ed_console.db")
REPORT_PATH = REPO_ROOT / "reports" / "f2_tb_grid_v1_latest.json"

# no_terminal_null law: a null names its door, at the PRODUCER.
NEXT_DEPTH = (
    "Conditioning: unconditioned entries are EV-zero by design; edge must "
    "come from state selection - the meta-classifier and the certified "
    "dealer-gamma channel."
)


def load_prereg() -> dict[str, Any]:
    prereg = json.loads(PREREG_PATH.read_text(encoding="utf-8"))
    fam = prereg["family"]
    n = (
        len(fam["stop_atr_multiples"])
        * len(fam["target_atr_multiples"])
        * len(fam["vertical_minutes"])
    )
    if n != int(fam["n_cells"]):
        raise ValueError(f"prereg family inconsistent: {n} != n_cells={fam['n_cells']}")
    return prereg


# ── Pure economics (unit-tested) ─────────────────────────────────────────────


def session_means(rows: Sequence[tuple[str, float]]) -> dict[str, float]:
    """Per-session mean net bp from (session, net_bp) rows."""
    sums: dict[str, float] = {}
    counts: dict[str, int] = {}
    for day, bp in rows:
        sums[day] = sums.get(day, 0.0) + float(bp)
        counts[day] = counts.get(day, 0) + 1
    return {d: sums[d] / counts[d] for d in sums}


def bootstrap_mean_ci(
    values: Sequence[float], *, n_boot: int, seed: int
) -> dict[str, Any]:
    """Percentile CI + two-sided sign p for the mean of session means."""
    vals = [float(v) for v in values]
    if len(vals) < 2:
        return {"ci95": None, "p_value": None, "n": len(vals), "n_boot": 0}
    rng = random.Random(seed)
    stats: list[float] = []
    n = len(vals)
    for _ in range(n_boot):
        s = 0.0
        for _k in range(n):
            s += vals[rng.randrange(n)]
        stats.append(s / n)
    stats.sort()

    def _pct(q: float) -> float:
        return stats[min(len(stats) - 1, max(0, int(q * (len(stats) - 1))))]

    n_le = sum(1 for s in stats if s <= 0.0)
    n_ge = sum(1 for s in stats if s >= 0.0)
    p = max(2.0 * min(n_le, n_ge) / len(stats), 2.0 / len(stats))
    return {"ci95": [_pct(0.025), _pct(0.975)], "p_value": p, "n": n, "n_boot": len(stats)}


def sharpe_of(values: Sequence[float]) -> float | None:
    n = len(values)
    if n < 2:
        return None
    m = sum(values) / n
    var = sum((v - m) ** 2 for v in values) / (n - 1)
    if var <= 0:
        return None
    return m / math.sqrt(var)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_ppf(q: float) -> float:
    # Acklam-style rational approximation is overkill here; bisection is exact
    # enough for the two quantiles DSR needs and has no external dependency.
    lo, hi = -10.0, 10.0
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if _norm_cdf(mid) < q:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


EULER_GAMMA = 0.5772156649015329


def deflated_sharpe_prob(
    session_values: Sequence[float],
    *,
    n_trials: int,
    sr_std_across_trials: float,
) -> float | None:
    """Bailey/Lopez de Prado DSR: PSR of the cell's Sharpe against the expected
    max Sharpe of n_trials, using the cross-trial SR dispersion."""
    sr = sharpe_of(session_values)
    if sr is None:
        return None
    t = len(session_values)
    m = sum(session_values) / t
    sd = math.sqrt(sum((v - m) ** 2 for v in session_values) / (t - 1))
    if sd <= 0:
        return None
    z3 = sum(((v - m) / sd) ** 3 for v in session_values) / t
    z4 = sum(((v - m) / sd) ** 4 for v in session_values) / t
    sr0 = sr_std_across_trials * (
        (1.0 - EULER_GAMMA) * _norm_ppf(1.0 - 1.0 / n_trials)
        + EULER_GAMMA * _norm_ppf(1.0 - 1.0 / (n_trials * math.e))
    )
    denom = 1.0 - z3 * sr + ((z4 - 1.0) / 4.0) * sr * sr
    if denom <= 0:
        return None
    return _norm_cdf(((sr - sr0) * math.sqrt(t - 1)) / math.sqrt(denom))


def sign_shuffle_null(
    net_bps: Sequence[float], *, n_shuffles: int, seed: int
) -> dict[str, Any]:
    """Null distribution of the mean under random sign flips (EV-zero world)."""
    vals = [float(v) for v in net_bps]
    if not vals:
        return {"null_q975": None, "n_shuffles": 0}
    rng = random.Random(seed)
    means: list[float] = []
    for _ in range(n_shuffles):
        s = 0.0
        for v in vals:
            s += v if rng.random() < 0.5 else -v
        means.append(s / len(vals))
    means.sort()
    q975 = means[min(len(means) - 1, max(0, int(0.975 * (len(means) - 1))))]
    return {"null_q975": q975, "n_shuffles": len(means)}


@dataclass
class CellEconomics:
    key: str
    n_candidates: int
    n_labeled: int
    n_sessions: int
    mean_net_bp: float | None
    per_session_means: dict[str, float]
    bootstrap: dict[str, Any]
    stress_bootstrap: dict[str, Any]
    shuffle: dict[str, Any]
    sharpe: float | None


def evaluate_cell(
    key: str,
    rows: Sequence[tuple[str, float]],
    n_candidates: int,
    *,
    extra_cost_bp: float,
    n_boot: int,
    shuffle_k: int,
    seed: int,
) -> CellEconomics:
    per_sess = session_means(rows)
    vals = list(per_sess.values())
    stress_rows = [(d, bp - extra_cost_bp) for d, bp in rows]
    stress_vals = list(session_means(stress_rows).values())
    all_bps = [bp for _d, bp in rows]
    return CellEconomics(
        key=key,
        n_candidates=n_candidates,
        n_labeled=len(rows),
        n_sessions=len(per_sess),
        mean_net_bp=(sum(all_bps) / len(all_bps)) if all_bps else None,
        per_session_means=per_sess,
        bootstrap=bootstrap_mean_ci(vals, n_boot=n_boot, seed=seed),
        stress_bootstrap=bootstrap_mean_ci(stress_vals, n_boot=n_boot, seed=seed + 1),
        shuffle=sign_shuffle_null(all_bps, n_shuffles=shuffle_k, seed=seed + 2),
        sharpe=sharpe_of(vals),
    )


def apply_grid_verdicts(
    cells: dict[str, CellEconomics],
    *,
    n_trials: int,
    min_sessions: int,
    min_candidates: int,
    psr_threshold: float,
) -> dict[str, dict[str, Any]]:
    """Holm across the family + DSR + screens -> verdict rows (pure)."""
    testable_sharpes = [c.sharpe for c in cells.values() if c.sharpe is not None]
    if len(testable_sharpes) >= 2:
        ms = sum(testable_sharpes) / len(testable_sharpes)
        sr_std = math.sqrt(
            sum((s - ms) ** 2 for s in testable_sharpes) / (len(testable_sharpes) - 1)
        )
    else:
        sr_std = 0.0
    p_values = {
        k: (c.bootstrap.get("p_value") if c.n_sessions >= min_sessions else None)
        for k, c in cells.items()
    }
    holm = holm_bonferroni(p_values)
    out: dict[str, dict[str, Any]] = {}
    for k, c in cells.items():
        under = c.n_sessions < min_sessions or c.n_labeled < min_candidates
        row: dict[str, Any] = {
            "n_candidates": c.n_candidates,
            "n_labeled": c.n_labeled,
            "n_sessions": c.n_sessions,
            "mean_net_bp": c.mean_net_bp,
            "bootstrap": c.bootstrap,
            "stress_bootstrap": c.stress_bootstrap,
            "shuffle": c.shuffle,
            "sharpe_sessions": c.sharpe,
            "holm": holm[k],
        }
        if under:
            row["verdict"] = "UNDER_SAMPLED"
            out[k] = row
            continue
        dsr = deflated_sharpe_prob(
            list(c.per_session_means.values()),
            n_trials=n_trials,
            sr_std_across_trials=sr_std,
        )
        _apply_screen(row, c, holm_sig=holm[k]["significant"] is True, dsr=dsr,
                      psr_threshold=psr_threshold)
        out[k] = row
    return out


def _apply_screen(
    row: dict[str, Any],
    c: CellEconomics,
    *,
    holm_sig: bool,
    dsr: float | None,
    psr_threshold: float,
) -> None:
    """Mutates row with screen booleans, anti-signal flag, and verdict."""
    ci: list[float] | None = c.bootstrap.get("ci95")
    sci: list[float] | None = c.stress_bootstrap.get("ci95")
    q975 = c.shuffle.get("null_q975")
    mean_pos = c.mean_net_bp is not None and c.mean_net_bp > 0
    ci_pos = ci is not None and ci[0] > 0
    ci_neg = ci is not None and ci[1] < 0
    stress_ok = sci is not None and sci[0] > 0
    shuffle_ok = q975 is not None and c.mean_net_bp is not None and c.mean_net_bp > q975
    dsr_ok = dsr is not None and dsr >= psr_threshold
    row["dsr_prob"] = dsr
    row["screen"] = {
        "mean_positive": mean_pos,
        "ci95_above_zero": ci_pos,
        "holm_significant": holm_sig,
        "dsr_ok": dsr_ok,
        "stress_2x_ok": stress_ok,
        "sign_shuffle_ok": shuffle_ok,
    }
    row["anti_signal"] = bool(ci_neg and holm_sig)
    survive = mean_pos and ci_pos and holm_sig and dsr_ok and stress_ok and shuffle_ok
    row["verdict"] = "SURVIVE_ECONOMIC" if survive else "KILL"


# ── Grid orchestration ───────────────────────────────────────────────────────


def _sessions_events(db_path: str, ticker: str = "SPY") -> tuple[dict[str, list[Bar1m]], dict[str, list[PilotEvent]], dict[str, list[float | None]], dict[str, Any]]:
    from time_et import et_date_str_from_ts_utc, is_tradable_session_ts_utc

    rep = load_spy_1m_bars(db_path, ticker=ticker, require_rth_only=True)
    tradable = [b for b in rep.bars if is_tradable_session_ts_utc(b.bar_start_ts_utc)]
    by_day: dict[str, list[Bar1m]] = {}
    for b in tradable:
        by_day.setdefault(et_date_str_from_ts_utc(b.bar_start_ts_utc), []).append(b)
    events: dict[str, list[PilotEvent]] = {}
    atrs: dict[str, list[float | None]] = {}
    for day in sorted(by_day):
        evs, _stats = generate_events(by_day[day], F1_DRAFT_CANDIDATE_CONFIG)
        events[day] = evs
        atrs[day] = build_atr_series(by_day[day])
    loader_info = {
        "n_rows": rep.n_rows,
        "n_tradable_bars": len(tradable),
        "n_sessions": len(by_day),
        "n_events_total": sum(len(v) for v in events.values()),
    }
    return by_day, events, atrs, loader_info


def _label_cell_rows(
    by_day: dict[str, list[Bar1m]],
    events: dict[str, list[PilotEvent]],
    atrs: dict[str, list[float | None]],
    *,
    stop_atr: float,
    target_atr: float,
    vertical_minutes: int,
    cost_round_trip_bp: float,
) -> tuple[list[tuple[str, float]], int]:
    rows: list[tuple[str, float]] = []
    n_candidates = 0
    for day, evs in events.items():
        day_bars = by_day[day]
        atr_series = atrs[day]
        for ev in evs:
            n_candidates += 1
            r = gated_label_event_cell_f1(
                day_bars,
                atr_series,
                ev,
                stop_atr=stop_atr,
                target_atr=target_atr,
                vertical_minutes=vertical_minutes,
                cost_round_trip_bp=cost_round_trip_bp,
            )
            if r.withheld_reason is None and r.realized_return_bp_post_cost is not None:
                rows.append((day, float(r.realized_return_bp_post_cost)))
    return rows, n_candidates


def _placebo_replicate(
    real_rows: dict[str, list[tuple[str, float]]],
    real_counts: dict[str, int],
    prereg: dict[str, Any],
    seed: int,
) -> dict[str, dict[str, Any]]:
    rnd = prereg["randomness"]
    floors = prereg["sample_floors"]
    cells: dict[str, CellEconomics] = {}
    for i, (key, rows) in enumerate(sorted(real_rows.items())):
        rng = random.Random(seed + i)
        shuffled = [(d, bp if rng.random() < 0.5 else -bp) for d, bp in rows]
        cells[key] = evaluate_cell(
            key,
            shuffled,
            real_counts[key],
            extra_cost_bp=float(prereg["costs"]["round_trip_bp"]),
            n_boot=int(rnd["bootstrap_B"]),
            shuffle_k=int(rnd["sign_shuffle_K"]),
            seed=seed + 1000 + i,
        )
    return apply_grid_verdicts(
        cells,
        n_trials=int(prereg["family"]["n_cells"]),
        min_sessions=int(floors["min_sessions_with_candidates_per_cell"]),
        min_candidates=int(floors["min_labeled_candidates_per_cell"]),
        psr_threshold=0.95,
    )


def run_grid(db_path: str) -> dict[str, Any]:
    t0 = time.perf_counter()
    prereg = load_prereg()
    fam = prereg["family"]
    rnd = prereg["randomness"]
    floors = prereg["sample_floors"]
    seed = int(rnd["seed"])
    pf = preflight(db_path)
    by_day, events, atrs, loader_info = _sessions_events(db_path)

    cell_rows: dict[str, list[tuple[str, float]]] = {}
    cell_counts: dict[str, int] = {}
    cells: dict[str, CellEconomics] = {}
    i = 0
    for stop in fam["stop_atr_multiples"]:
        for target in fam["target_atr_multiples"]:
            for vert in fam["vertical_minutes"]:
                key = f"s{stop}_t{target}_v{vert}"
                rows, n_cand = _label_cell_rows(
                    by_day, events, atrs,
                    stop_atr=float(stop),
                    target_atr=float(target),
                    vertical_minutes=int(vert),
                    cost_round_trip_bp=float(prereg["costs"]["round_trip_bp"]),
                )
                cell_rows[key] = rows
                cell_counts[key] = n_cand
                cells[key] = evaluate_cell(
                    key, rows, n_cand,
                    extra_cost_bp=float(prereg["costs"]["round_trip_bp"]),
                    n_boot=int(rnd["bootstrap_B"]),
                    shuffle_k=int(rnd["sign_shuffle_K"]),
                    seed=seed + i,
                )
                i += 1

    verdicts = apply_grid_verdicts(
        cells,
        n_trials=int(fam["n_cells"]),
        min_sessions=int(floors["min_sessions_with_candidates_per_cell"]),
        min_candidates=int(floors["min_labeled_candidates_per_cell"]),
        psr_threshold=0.95,
    )
    placebo = _placebo_replicate(cell_rows, cell_counts, prereg, seed + 777_000)
    placebo_survivors = [k for k, v in placebo.items() if v.get("verdict") == "SURVIVE_ECONOMIC"]
    survivors = [k for k, v in verdicts.items() if v.get("verdict") == "SURVIVE_ECONOMIC"]
    anti = [k for k, v in verdicts.items() if v.get("anti_signal")]
    halted = bool(placebo_survivors)
    status = (
        "HALT_PLACEBO_EDGE"
        if halted
        else "STOP_ANTI_SIGNAL"
        if anti
        else "COMPLETE"
    )
    # Drop bulky per-session maps from the report rows (report size discipline).
    return {
        "schema": "f2_tb_grid_v1",
        "prereg_id": prereg["prereg_id"],
        "status": status,
        "not_an_admission": prereg["explicitly_not"]["not_an_admission_packet"],
        "generated_utc": datetime.now(tz=timezone.utc).isoformat(),
        "db_path": str(db_path),
        "preflight": pf,
        "loader": loader_info,
        "n_cells": len(verdicts),
        "n_survivors": 0 if halted else len(survivors),
        "survivors": [] if halted else survivors,
        "anti_signal_cells": anti,
        "placebo": {
            "n_survivors": len(placebo_survivors),
            "survivors": placebo_survivors,
            "hard_halt_engaged": halted,
        },
        "cells": verdicts,
        "next_depth": NEXT_DEPTH,
        "run_sec": round(time.perf_counter() - t0, 2),
    }


def main() -> int:
    report = run_grid(DEFAULT_DB)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    summary = {
        "status": report["status"],
        "n_cells": report["n_cells"],
        "n_survivors": report["n_survivors"],
        "survivors": report["survivors"][:10],
        "anti_signal_cells": report["anti_signal_cells"][:10],
        "placebo_survivors": report["placebo"]["n_survivors"],
        "loader": report["loader"],
        "run_sec": report["run_sec"],
        "report": str(REPORT_PATH),
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
