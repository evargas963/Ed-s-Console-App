"""Meta-XGBoost conditioned study under META_XGB_TB_V1_PREREG_V1.

Report-only. Ingest per META_XGB_TB_INGEST_V1: one row per labeled candidate,
features strictly as-of the SIGNAL bar from same-session bars, mask-and-drop
(no imputation, no NaN reaches fit), overnight gap only as a named feature,
greeks era floor enforced structurally (v1 feature set is price-only).

Gate: the F2 economics verbatim over the preregistered tau policy family,
PLUS the unconditional baseline comparison, PLUS a per-fold label-permutation
control with the two-sided verdict (leakage OR anti-signal halts the study).
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from .data_loader import Bar1m
from .event_generation import PilotEvent
from .f1_input_gates import (
    gated_label_event_cell_f1,
    permutation_control_verdict,
    placebo_shuffle_train_only,
)
from .f2_tb_grid_runner import (
    CellEconomics,
    _apply_screen,
    _sessions_events,
    deflated_sharpe_prob,
    evaluate_cell,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
PREREG_PATH = Path(__file__).resolve().parent / "meta_xgb_tb_prereg_v1.json"
DEFAULT_DB = str(REPO_ROOT / "data" / "ed_console.db")
REPORT_PATH = REPO_ROOT / "reports" / "meta_xgb_tb_v1_latest.json"

# no_terminal_null law: a null names its door, at the PRODUCER.
NEXT_DEPTH = (
    "Dealer-gamma feature channel via the certified greeks_recomputed_v1 "
    "recompute, then the GEX-R1 Rule-A reversion candidate generator prereg."
)

FEATURE_NAMES: tuple[str, ...] = (
    "side_sign", "z_trigger", "cusum_pos", "cusum_neg", "sma_spread_atr",
    "minutes_since_open", "time_sin", "time_cos",
    "ret_5m_atr", "ret_15m_atr", "rv_15m_atr", "range_pos_20",
    "atr_t1_pct", "overnight_gap_atr",
)


def load_prereg() -> dict[str, Any]:
    return json.loads(PREREG_PATH.read_text(encoding="utf-8"))


@dataclass
class CandidateRow:
    session: str
    features: dict[str, float | None]
    label: int | None          # 1 WIN / 0 LOSS / None excluded
    net_bp: float | None
    exclude_reason: str | None


def _ret_atr(closes: Sequence[float], i: int, k: int, atr: float) -> float | None:
    """k-bar same-session return in ATR units, None if window incomplete."""
    if i - k < 0:
        return None
    return (closes[i] - closes[i - k]) / atr


def _rv_atr(closes: Sequence[float], i: int, k: int, atr: float) -> float | None:
    if i - k < 0:
        return None
    diffs = [closes[j] - closes[j - 1] for j in range(i - k + 1, i + 1)]
    m = sum(diffs) / len(diffs)
    var = sum((d - m) ** 2 for d in diffs) / len(diffs)
    return math.sqrt(var) / atr


def _range_pos(day_bars: Sequence[Bar1m], i: int, k: int) -> float | None:
    if i - k + 1 < 0:
        return None
    win = day_bars[i - k + 1 : i + 1]
    hi = max(b.high for b in win)
    lo = min(b.low for b in win)
    if hi <= lo:
        return None
    return (day_bars[i].close - lo) / (hi - lo)


def candidate_features(
    day_bars: Sequence[Bar1m],
    ev: PilotEvent,
    atr_t1: float | None,
    prev_session_close: float | None,
) -> dict[str, float | None]:
    """All as-of the SIGNAL bar close; same-session windows only (INGEST_V1)."""
    from time_et import RTH_START_MINS, RTH_SESSION_MINUTES, et_minute_total_from_ts_utc

    i = ev.signal_bar_index
    b = day_bars[i]
    closes = [x.close for x in day_bars]
    if atr_t1 is None or atr_t1 <= 0:
        return {name: None for name in FEATURE_NAMES}
    mins = et_minute_total_from_ts_utc(b.bar_start_ts_utc) - RTH_START_MINS
    prog = max(0.0, min(1.0, mins / float(RTH_SESSION_MINUTES)))
    gap = (
        (day_bars[0].open - prev_session_close) / atr_t1
        if prev_session_close is not None
        else None
    )
    return {
        "side_sign": 1.0 if ev.side == "LONG" else -1.0,
        "z_trigger": float(ev.z_trigger),
        "cusum_pos": float(ev.cusum_pos),
        "cusum_neg": float(ev.cusum_neg),
        "sma_spread_atr": (float(ev.sma_fast) - float(ev.sma_slow)) / atr_t1,
        "minutes_since_open": float(mins),
        "time_sin": math.sin(2.0 * math.pi * prog),
        "time_cos": math.cos(2.0 * math.pi * prog),
        "ret_5m_atr": _ret_atr(closes, i, 5, atr_t1),
        "ret_15m_atr": _ret_atr(closes, i, 15, atr_t1),
        "rv_15m_atr": _rv_atr(closes, i, 15, atr_t1),
        "range_pos_20": _range_pos(day_bars, i, 20),
        "atr_t1_pct": atr_t1 / b.close if b.close > 0 else None,
        "overnight_gap_atr": gap,
    }


def build_candidate_rows(
    by_day: dict[str, list[Bar1m]],
    events: dict[str, list[PilotEvent]],
    atrs: dict[str, list[float | None]],
    cell: dict[str, Any],
) -> tuple[list[CandidateRow], dict[str, int]]:
    rows: list[CandidateRow] = []
    stats = {"n_candidates": 0, "excluded_label": 0, "excluded_timeout_ff": 0}
    prev_close: float | None = None
    for day in sorted(by_day):
        day_bars = by_day[day]
        atr_series = atrs[day]
        for ev in events[day]:
            stats["n_candidates"] += 1
            r = gated_label_event_cell_f1(
                day_bars, atr_series, ev,
                stop_atr=float(cell["stop_atr"]),
                target_atr=float(cell["target_atr"]),
                vertical_minutes=int(cell["vertical_minutes"]),
                cost_round_trip_bp=float(cell["cost_round_trip_bp"]),
            )
            i_atr = ev.signal_bar_index - 1
            atr_t1 = atr_series[i_atr] if 0 <= i_atr < len(atr_series) else None
            feats = candidate_features(day_bars, ev, atr_t1, prev_close)
            if r.withheld_reason is not None:
                stats["excluded_label"] += 1
                rows.append(CandidateRow(day, feats, None, None, r.withheld_reason))
                continue
            if r.barrier_hit not in ("WIN", "LOSS"):
                stats["excluded_timeout_ff"] += 1
                rows.append(CandidateRow(day, feats, None, None, f"non_binary_{r.barrier_hit}"))
                continue
            rows.append(
                CandidateRow(
                    day, feats,
                    1 if r.barrier_hit == "WIN" else 0,
                    float(r.realized_return_bp_post_cost or 0.0),
                    None,
                )
            )
        prev_close = day_bars[-1].close
    return rows, stats


def mask_and_drop(
    rows: Sequence[CandidateRow],
) -> tuple[list[list[float]], list[int], list[str], list[float], int]:
    """INGEST_V1: a row with any None feature or no binary label is dropped."""
    x: list[list[float]] = []
    y: list[int] = []
    sessions: list[str] = []
    net: list[float] = []
    dropped = 0
    for r in rows:
        if r.label is None or r.net_bp is None:
            dropped += 1
            continue
        vals = [r.features[name] for name in FEATURE_NAMES]
        if any(v is None or not math.isfinite(float(v)) for v in vals):
            dropped += 1
            continue
        x.append([float(v) for v in vals])  # type: ignore[arg-type]
        y.append(int(r.label))
        sessions.append(r.session)
        net.append(float(r.net_bp))
    for row_vals in x:
        for v in row_vals:
            if not math.isfinite(v):
                raise ValueError("NaN/inf reached the training matrix — ingest contract broken")
    return x, y, sessions, net, dropped


def purged_session_folds(
    session_list: Sequence[str], *, n_folds: int, embargo_sessions: int
) -> list[tuple[list[str], list[str]]]:
    """Expanding walk-forward over unique sessions with an embargo gap."""
    days = sorted(set(session_list))
    if len(days) < n_folds + embargo_sessions + 1:
        return []
    fold_size = max(1, len(days) // (n_folds + 1))
    folds: list[tuple[list[str], list[str]]] = []
    for f in range(1, n_folds + 1):
        split = f * fold_size
        test_end = min(len(days), split + fold_size) if f < n_folds else len(days)
        train = days[: max(0, split - embargo_sessions)]
        test = days[split:test_end]
        if train and test:
            folds.append((train, test))
    return folds


def _fit_predict_fold(
    x: list[list[float]], y: list[int], train_idx: list[int], test_idx: list[int],
    params: dict[str, Any], seed: int,
) -> list[float]:
    from xgboost import XGBClassifier

    mdl = XGBClassifier(random_state=seed, **params)
    mdl.fit([x[i] for i in train_idx], [y[i] for i in train_idx])
    probs = mdl.predict_proba([x[i] for i in test_idx])
    return [float(p[1]) for p in probs]


def _balanced_accuracy(y_true: Sequence[int], y_pred: Sequence[int]) -> float | None:
    pos = [p for t, p in zip(y_true, y_pred, strict=True) if t == 1]
    neg = [p for t, p in zip(y_true, y_pred, strict=True) if t == 0]
    if not pos or not neg:
        return None
    tpr = sum(1 for p in pos if p == 1) / len(pos)
    tnr = sum(1 for p in neg if p == 0) / len(neg)
    return (tpr + tnr) / 2.0


def _run_one_fold(
    x: list[list[float]],
    y: list[int],
    tr: list[int],
    te: list[int],
    params: dict[str, Any],
    fold_seed: int,
    *,
    oos_p: dict[int, float],
    perm_true: list[int],
    perm_pred: list[int],
) -> None:
    """Real fit + label-permutation control fit for one fold (mutates collectors)."""
    probs = _fit_predict_fold(x, y, tr, te, params, fold_seed)
    for i, p in zip(te, probs, strict=True):
        oos_p[i] = p
    shuffled = placebo_shuffle_train_only(
        [str(v) for v in y], [i in set(tr) for i in range(len(y))], fold_seed + 9000
    )
    probs_c = _fit_predict_fold(x, [int(v) for v in shuffled], tr, te, params, fold_seed)
    perm_true.extend(y[i] for i in te)
    perm_pred.extend(1 if p >= 0.5 else 0 for p in probs_c)


def _run_folds(
    x: list[list[float]],
    y: list[int],
    sessions: list[str],
    prereg: dict[str, Any],
    seed: int,
) -> tuple[dict[int, float], dict[str, Any]]:
    """Walk-forward OOS probabilities + the per-fold label-permutation control."""
    folds = purged_session_folds(
        sessions,
        n_folds=int(prereg["splits"]["n_folds"]),
        embargo_sessions=int(prereg["splits"]["embargo_sessions"]),
    )
    idx_by_day: dict[str, list[int]] = {}
    for i, d in enumerate(sessions):
        idx_by_day.setdefault(d, []).append(i)
    oos_p: dict[int, float] = {}
    perm_true: list[int] = []
    perm_pred: list[int] = []
    for f_i, (train_days, test_days) in enumerate(folds):
        tr = [i for d in train_days for i in idx_by_day.get(d, [])]
        te = [i for d in test_days for i in idx_by_day.get(d, [])]
        if len(tr) < 50 or not te:
            continue
        _run_one_fold(
            x, y, tr, te, prereg["model"]["params"], seed + f_i,
            oos_p=oos_p, perm_true=perm_true, perm_pred=perm_pred,
        )
    perm_bal = _balanced_accuracy(perm_true, perm_pred)
    perm_verdict: dict[str, Any] = (
        {"balanced_accuracy": perm_bal, **permutation_control_verdict(perm_bal, chance=0.5)}
        if perm_bal is not None
        else {
            "balanced_accuracy": None,
            "collapsed_to_chance": False,
            "leakage_stop": True,
            "anti_signal_stop": False,
        }
    )
    return oos_p, {"n_folds_run": len(folds), "permutation_control": perm_verdict}


def _evaluate_policies(
    oos_p: dict[int, float],
    sessions: list[str],
    net: list[float],
    prereg: dict[str, Any],
    seed: int,
) -> tuple[dict[str, dict[str, Any]], list[str], CellEconomics]:
    """Tau-family economics + F2 screen + baseline comparison."""
    from research.incumbent_eval_v1.stats import holm_bonferroni

    cell = prereg["labeling_cell"]
    rnd = prereg["randomness"]
    floors = prereg["sample_floors"]
    taus = [float(t) for t in prereg["policy_family"]["taus"]]
    cells: dict[str, CellEconomics] = {}
    for t_i, tau in enumerate(taus):
        sel = [(sessions[i], net[i]) for i, p in oos_p.items() if p >= tau]
        cells[f"tau_{tau}"] = evaluate_cell(
            f"tau_{tau}", sel, len(oos_p),
            extra_cost_bp=float(cell["cost_round_trip_bp"]),
            n_boot=int(rnd["bootstrap_B"]),
            shuffle_k=int(rnd["sign_shuffle_K"]),
            seed=seed + 100 + t_i,
        )
    baseline = evaluate_cell(
        "baseline_all_oos", [(sessions[i], net[i]) for i in oos_p], len(oos_p),
        extra_cost_bp=float(cell["cost_round_trip_bp"]),
        n_boot=int(rnd["bootstrap_B"]), shuffle_k=int(rnd["sign_shuffle_K"]),
        seed=seed + 999,
    )
    min_sess = int(floors["min_sessions_with_selected_trades"])
    min_cand = int(floors["min_selected_candidates"])
    holm = holm_bonferroni(
        {k: (c.bootstrap.get("p_value") if c.n_sessions >= min_sess else None) for k, c in cells.items()}
    )
    sharpes = [c.sharpe for c in cells.values() if c.sharpe is not None]
    sr_std = 0.0
    if len(sharpes) >= 2:
        ms = sum(sharpes) / len(sharpes)
        sr_std = math.sqrt(sum((s - ms) ** 2 for s in sharpes) / (len(sharpes) - 1))
    verdict_rows: dict[str, dict[str, Any]] = {}
    survivors: list[str] = []
    for k, c in cells.items():
        row = _policy_verdict_row(
            c, holm[k],
            n_oos=len(oos_p), min_sess=min_sess, min_cand=min_cand,
            n_taus=len(taus), sr_std=sr_std, baseline_mean=baseline.mean_net_bp,
        )
        if row["verdict"] == "SURVIVE_ECONOMIC":
            survivors.append(k)
        verdict_rows[k] = row
    return verdict_rows, survivors, baseline


def _policy_verdict_row(
    c: CellEconomics,
    holm_row: dict[str, Any],
    *,
    n_oos: int,
    min_sess: int,
    min_cand: int,
    n_taus: int,
    sr_std: float,
    baseline_mean: float | None,
) -> dict[str, Any]:
    """One tau policy through floors, the F2 screen, and the baseline test."""
    row: dict[str, Any] = {
        "n_selected": c.n_labeled,
        "n_sessions": c.n_sessions,
        "selection_rate": (c.n_labeled / n_oos) if n_oos else None,
        "mean_net_bp": c.mean_net_bp,
        "bootstrap": c.bootstrap,
        "stress_bootstrap": c.stress_bootstrap,
        "shuffle": c.shuffle,
        "holm": holm_row,
    }
    if c.n_sessions < min_sess or c.n_labeled < min_cand:
        row["verdict"] = "UNDER_SAMPLED"
        return row
    dsr = deflated_sharpe_prob(
        list(c.per_session_means.values()), n_trials=n_taus, sr_std_across_trials=sr_std
    )
    _apply_screen(row, c, holm_sig=holm_row["significant"] is True, dsr=dsr, psr_threshold=0.95)
    beats = (
        c.mean_net_bp is not None
        and baseline_mean is not None
        and c.mean_net_bp > baseline_mean
    )
    row["beats_unconditional_baseline"] = beats
    if row["verdict"] == "SURVIVE_ECONOMIC" and not beats:
        row["verdict"] = "KILL"
    return row


def run_study(db_path: str) -> dict[str, Any]:
    t0 = time.perf_counter()
    prereg = load_prereg()
    rnd = prereg["randomness"]
    seed = int(rnd["seed"])
    by_day, events, atrs, loader_info = _sessions_events(db_path)
    rows, ingest_stats = build_candidate_rows(by_day, events, atrs, prereg["labeling_cell"])
    x, y, sessions, net, n_dropped = mask_and_drop(rows)
    ingest_stats["n_trainable"] = len(y)
    ingest_stats["n_dropped_mask"] = n_dropped

    oos_p, fold_info = _run_folds(x, y, sessions, prereg, seed)
    perm_verdict = fold_info["permutation_control"]
    verdict_rows, survivors, baseline = _evaluate_policies(oos_p, sessions, net, prereg, seed)

    halted = bool(perm_verdict["leakage_stop"] or perm_verdict["anti_signal_stop"])
    status = "HALT_PERMUTATION_CONTROL" if halted else "COMPLETE"
    return {
        "schema": "meta_xgb_tb_v1",
        "prereg_id": prereg["prereg_id"],
        "status": status,
        "not_an_admission": prereg["explicitly_not"]["not_an_admission_packet"],
        "generated_utc": datetime.now(tz=timezone.utc).isoformat(),
        "db_path": str(db_path),
        "loader": loader_info,
        "ingest": ingest_stats,
        "n_oos_scored": len(oos_p),
        "n_folds_run": fold_info["n_folds_run"],
        "permutation_control": perm_verdict,
        "baseline_all_oos": {
            "n": baseline.n_labeled,
            "mean_net_bp": baseline.mean_net_bp,
            "bootstrap": baseline.bootstrap,
        },
        "policies": verdict_rows,
        "n_survivors": 0 if halted else len(survivors),
        "survivors": [] if halted else survivors,
        "greeks_channel": "era-floored to >=1784502281; empty in v1 (price-only feature set)",
        "next_depth": NEXT_DEPTH,
        "run_sec": round(time.perf_counter() - t0, 2),
    }


def main() -> int:
    report = run_study(DEFAULT_DB)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    summary = {
        "status": report["status"],
        "n_oos_scored": report["n_oos_scored"],
        "permutation_control": report["permutation_control"],
        "baseline_mean_net_bp": report["baseline_all_oos"]["mean_net_bp"],
        "policies": {
            k: {"verdict": v["verdict"], "n_selected": v["n_selected"], "mean_net_bp": v["mean_net_bp"]}
            for k, v in report["policies"].items()
        },
        "survivors": report["survivors"],
        "run_sec": report["run_sec"],
        "report": str(REPORT_PATH),
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
