"""Study #2 runner: race trivial causal price rules on the incumbent's rows.

Usage (read-only against the canonical DB):
  python -m research.challenger_eval_v1.runner
  python -m research.challenger_eval_v1.runner --db data/ed_console.db

Reuses the Study #1 statistics (research.incumbent_eval_v1.stats) and row
gates; adds a strictly causal bar join (bar_end_ts_utc <= decision_ts_utc)
for challenger inputs. Frozen parameters come from prereg_v1.json — the
runner refuses to run if the prereg is missing or inconsistent.
"""

from __future__ import annotations

import argparse
import bisect
import json
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from research.incumbent_eval_v1 import stats
from research.incumbent_eval_v1.runner import invalid_threshold_horizons
from calibration.operable_surface_quarantine import operable_filter_sql

PREREG_PATH = Path(__file__).resolve().parent / "prereg_v1.json"
_HZ_MINUTES = {"1c": 1, "5c": 5, "15c": 15, "60c": 60}
CHALLENGER_LOOKBACKS = {
    "momentum_5": 5,
    "momentum_15": 15,
    "momentum_60": 60,
    "mean_reversion_5": 5,
}
_REVERSED = {"mean_reversion_5"}


class PreregViolationError(RuntimeError):
    """The frozen preregistration is missing or inconsistent — refuse to run."""


def load_prereg() -> dict[str, Any]:
    try:
        prereg = json.loads(PREREG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise PreregViolationError(f"cannot load preregistration {PREREG_PATH}: {e}") from e
    fam = prereg.get("family") or {}
    n = len(fam.get("tickers") or []) * len(fam.get("horizons") or []) * len(fam.get("challengers") or [])
    if n != fam.get("n_tests"):
        raise PreregViolationError(f"prereg family inconsistent: computed {n} != n_tests={fam.get('n_tests')}")
    if set(fam.get("challengers") or []) != set(CHALLENGER_LOOKBACKS):
        raise PreregViolationError("prereg challenger roster diverged from code roster")
    if prereg.get("primary_metric", {}).get("name", "").split(" ")[0] != "MCC":
        raise PreregViolationError("prereg primary metric is not MCC — code and prereg diverged")
    return prereg


def challenger_prediction(
    closes: list[float], j: int, challenger: str
) -> Optional[str]:
    """Prediction from completed-bar closes; closes[j] is the last bar at/before
    the decision. None when history is insufficient or the move is exactly zero
    (a zero move carries no direction — fabricating one would be a silent default)."""
    k = CHALLENGER_LOOKBACKS[challenger]
    if j - k < 0:
        return None
    move = closes[j] - closes[j - k]
    if move == 0.0:
        return None
    pred = "up" if move > 0.0 else "down"
    if challenger in _REVERSED:
        pred = "down" if pred == "up" else "up"
    return pred


def load_bars(db_path: Path | str, tickers: list[str]) -> dict[str, tuple[list[float], list[float]]]:
    """Per ticker: (bar_end_ts sorted ascending, closes aligned) — read-only."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        out: dict[str, tuple[list[float], list[float]]] = {}
        for t in tickers:
            ends: list[float] = []
            closes: list[float] = []
            for end_ts, close in conn.execute(
                "SELECT bar_end_ts_utc, close FROM price_bars_1m"
                " WHERE ticker = ? ORDER BY bar_end_ts_utc",
                (t,),
            ):
                ends.append(float(end_ts))
                closes.append(float(close))
            out[t] = (ends, closes)
        return out
    finally:
        conn.close()


def load_decision_rows(
    db_path: Path | str, tickers: list[str], horizons: list[str]
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """Time-ordered scored rows per (ticker, horizon) — Study #1 gates, plus the
    incumbent's recorded dominant_direction kept for head-to-head comparison."""
    from time_et import ET, is_rth_ts_utc

    cells: dict[tuple[str, str], list[dict[str, Any]]] = {
        (t, hz): [] for t in tickers for hz in horizons
    }
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        sql = (
            "SELECT ticker, decision_ts_utc, model_outputs_json,"
            " outcome_1c, outcome_5c, outcome_15c, outcome_60c"
            " FROM calibration_decision_log"
            " WHERE calibration_trust='trusted' AND outcomes_attached_ts_utc IS NOT NULL"
            f" AND {operable_filter_sql(conn)}"
            f" AND ticker IN ({','.join('?' * len(tickers))})"
            " ORDER BY decision_ts_utc"
        )
        for row in conn.execute(sql, tickers):
            ts = float(row["decision_ts_utc"])
            if not is_rth_ts_utc(ts):
                continue
            try:
                bundle = json.loads(row["model_outputs_json"] or "{}")
            except (TypeError, ValueError):
                continue
            by_hz = (
                (bundle.get("stack_probs_bundle") or {}).get("multi_horizon_ml_fusion_bundle")
                or {}
            ).get("by_horizon") or {}
            et_date = datetime.fromtimestamp(ts, tz=ET).strftime("%Y-%m-%d")
            for hz in horizons:
                blk = by_hz.get(hz)
                truth = row[f"outcome_{hz}"]
                if not isinstance(blk, dict) or not blk.get("horizon_fusion_available"):
                    continue
                incumbent_pred = blk.get("dominant_direction")
                if incumbent_pred not in stats.CLASSES or truth not in stats.CLASSES:
                    continue
                cells[(str(row["ticker"]), hz)].append(
                    {
                        "ts": ts,
                        "et_date": et_date,
                        "incumbent_pred": incumbent_pred,
                        "truth": truth,
                    }
                )
    finally:
        conn.close()
    return cells


def attach_challenger_predictions(
    rows: list[dict[str, Any]],
    bars: tuple[list[float], list[float]],
    challengers: list[str],
    max_bar_age_sec: float,
) -> dict[str, int]:
    """Mutates rows in place: adds pred_<challenger> (or None). Returns skip
    tallies: BAR_GAP (no fresh completed bar) counted once per row; ZERO_OR_
    SHORT_HISTORY per challenger."""
    ends, closes = bars
    skips = {"BAR_GAP": 0}
    for c in challengers:
        skips[f"NO_PREDICTION_{c}"] = 0
    for r in rows:
        # Last completed bar at/before the decision instant (strict causality).
        j = bisect.bisect_right(ends, r["ts"]) - 1
        if j < 0 or (r["ts"] - ends[j]) > max_bar_age_sec:
            skips["BAR_GAP"] += 1
            for c in challengers:
                r[f"pred_{c}"] = None
            continue
        for c in challengers:
            pred = challenger_prediction(closes, j, c)
            r[f"pred_{c}"] = pred
            if pred is None:
                skips[f"NO_PREDICTION_{c}"] += 1
    return skips


def evaluate_test(
    rows: list[dict[str, Any]], challenger: str, hz: str, prereg: dict[str, Any]
) -> dict[str, Any]:
    """All prereg metrics for one (ticker, horizon, challenger) test — scored on
    the rows where the challenger produced a prediction; the incumbent is
    rescored on that identical subset for the head-to-head delta."""
    floors = prereg["sample_floors"]
    rnd = prereg["randomness"]
    scored = [r for r in rows if r.get(f"pred_{challenger}") is not None]
    preds = [r[f"pred_{challenger}"] for r in scored]
    truths = [r["truth"] for r in scored]
    days = sorted({r["et_date"] for r in scored})
    hz_min = _HZ_MINUTES[hz]
    n_windows = len({int(r["ts"] // (hz_min * 60.0)) for r in scored})
    cm = stats.confusion_matrix(preds, truths)
    incumbent_cm = stats.confusion_matrix([r["incumbent_pred"] for r in scored], truths)
    mcc = stats.mcc_multiclass(cm)
    incumbent_mcc = stats.mcc_multiclass(incumbent_cm)
    out: dict[str, Any] = {
        "n_rows_in_cell": len(rows),
        "n_scored": len(scored),
        "n_distinct_days": len(days),
        "date_range": [days[0], days[-1]] if days else None,
        "n_independent_windows": n_windows,
        "confusion_matrix": cm,
        "mcc": mcc,
        "balanced_accuracy": stats.balanced_accuracy(cm),
        "accuracy": stats.accuracy(cm),
        "baselines": stats.baseline_accuracies(preds, truths),
        "incumbent_on_identical_rows": {
            "mcc": incumbent_mcc,
            "accuracy": stats.accuracy(incumbent_cm),
        },
        "mcc_delta_vs_incumbent": (
            (mcc - incumbent_mcc) if mcc is not None and incumbent_mcc is not None else None
        ),
        "warnings": [],
    }
    if len(scored) > n_windows:
        out["warnings"].append("EFFECTIVE_SAMPLE_NOT_PROVEN")
    under_sampled = (
        len(scored) < int(floors["min_scored_rows_per_test"])
        or len(days) < int(floors["min_distinct_days_per_test"])
    )
    out["under_sampled"] = under_sampled
    if under_sampled:
        out["warnings"].append("UNDER_SAMPLED")
        out["bootstrap"] = None
        out["shuffle_control"] = None
        return out
    out["bootstrap"] = stats.day_block_bootstrap_mcc(
        preds, truths, [r["et_date"] for r in scored],
        n_boot=int(rnd["bootstrap_B"]), seed=int(rnd["seed"]),
    )
    out["shuffle_control"] = stats.shuffle_control_mcc(
        preds, truths, n_shuffles=int(rnd["shuffle_K"]), seed=int(rnd["seed"]),
    )
    return out


def apply_advancement_screen(tests: dict[str, dict[str, Any]], prereg: dict[str, Any]) -> None:
    """Identical screen shape to Study #1, over the declared 48-test family."""
    p_values = {
        key: (t.get("bootstrap") or {}).get("p_value") if not t["under_sampled"] else None
        for key, t in tests.items()
    }
    holm = stats.holm_bonferroni(p_values)
    for key, t in tests.items():
        t["holm"] = holm[key]
        if t["under_sampled"]:
            t["verdict"] = "UNDER_SAMPLED"
            continue
        boot = t.get("bootstrap") or {}
        ci = boot.get("ci95")
        sc = t.get("shuffle_control") or {}
        shuffle_ok = (
            sc.get("null_q025") is not None and sc["null_q025"] <= 0.0 <= sc["null_q975"]
        )
        if not shuffle_ok:
            t["verdict"] = "STOP_SHUFFLE_CONTROL_FAILED"
            t["warnings"].append("SHUFFLE_NULL_NOT_CENTERED_AT_ZERO")
            continue
        acc = t["accuracy"]
        base = t["baselines"]
        beats_baselines = acc is not None and all(
            base[b] is None or acc >= base[b]
            for b in ("always_flat", "majority_class", "persistence")
        )
        ci_excludes_zero = bool(ci) and (ci[0] > 0.0 or ci[1] < 0.0)
        significant = holm[key]["significant"] is True
        t["screen"] = {
            "ci95_excludes_zero": ci_excludes_zero,
            "holm_significant": significant,
            "beats_all_baselines": beats_baselines,
            "shuffle_control_ok": shuffle_ok,
        }
        t["verdict"] = (
            "PASS" if (ci_excludes_zero and significant and beats_baselines) else "FAIL"
        )


def run_study(db_path: Path | str) -> dict[str, Any]:
    prereg = load_prereg()
    fam = prereg["family"]
    tickers = [str(t) for t in fam["tickers"]]
    horizons = [str(h) for h in fam["horizons"]]
    challengers = [str(c) for c in fam["challengers"]]
    max_bar_age = float(prereg["data"]["max_bar_age_sec"])
    invalid_hz = invalid_threshold_horizons()
    usable_horizons = [h for h in horizons if h not in invalid_hz]
    cells = load_decision_rows(db_path, tickers, usable_horizons)
    bars = load_bars(db_path, tickers)
    skips: dict[str, dict[str, int]] = {}
    for (ticker, hz), rows in cells.items():
        # Bar joins are per (ticker, horizon) row list; tallies pooled per ticker.
        s = attach_challenger_predictions(rows, bars[ticker], challengers, max_bar_age)
        agg = skips.setdefault(ticker, {k: 0 for k in s})
        for k, v in s.items():
            agg[k] = agg.get(k, 0) + v
    tests: dict[str, dict[str, Any]] = {}
    for (ticker, hz), rows in sorted(cells.items()):
        for c in challengers:
            tests[f"{ticker}:{hz}:{c}"] = evaluate_test(rows, c, hz, prereg)
    apply_advancement_screen(tests, prereg)
    verdicts = [t["verdict"] for t in tests.values()]
    n_pass = verdicts.count("PASS")
    n_stop = verdicts.count("STOP_SHUFFLE_CONTROL_FAILED")
    summary_verdict = (
        "STOP_SHUFFLE_CONTROL_FAILED" if n_stop
        else "INSUFFICIENT_DATA" if all(v == "UNDER_SAMPLED" for v in verdicts)
        else "SIGNAL_DETECTED_IN_SOME_TESTS" if n_pass
        else "NO_SIGNAL_DETECTED"
    )
    n_beat_incumbent = sum(
        1 for t in tests.values()
        if not t["under_sampled"]
        and t["mcc_delta_vs_incumbent"] is not None
        and t["mcc_delta_vs_incumbent"] > 0.0
    )
    return {
        "schema_version": "1",
        "prereg_id": prereg["prereg_id"],
        "generated_utc": datetime.now(tz=timezone.utc).isoformat(),
        "run_id": uuid.uuid4().hex[:12],
        "db_path": str(Path(db_path).resolve()),
        "family": fam,
        "randomness": prereg["randomness"],
        "sample_floors": prereg["sample_floors"],
        "invalid_threshold_horizons_excluded": invalid_hz,
        "bar_join_skips_by_ticker": skips,
        "tests": tests,
        "summary": {
            "verdict": summary_verdict,
            "n_tests": len(tests),
            "n_pass": n_pass,
            "n_fail": verdicts.count("FAIL"),
            "n_under_sampled": verdicts.count("UNDER_SAMPLED"),
            "n_stop": n_stop,
            "n_tests_beating_incumbent_mcc": n_beat_incumbent,
            "interpretation": prereg["outcome_interpretation"],
            "not_an_admission_packet": prereg["explicitly_not"]["not_an_admission_packet"],
        },
    }


def write_report(report: dict[str, Any], out_dir: Path | str) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    et_date = report["generated_utc"][:10]
    path = out / f"challenger_eval_{et_date}_{report['run_id']}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out / "latest.json").write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def _console_summary(report: dict[str, Any]) -> str:
    s = report["summary"]
    lines = [
        f"challenger_eval_v1 — {s['verdict']}"
        f" ({s['n_pass']} PASS / {s['n_fail']} FAIL / {s['n_under_sampled']} under-sampled"
        f" of {s['n_tests']} tests; {s['n_tests_beating_incumbent_mcc']} beat incumbent MCC)",
    ]
    for key, t in report["tests"].items():
        if t["verdict"] == "UNDER_SAMPLED":
            lines.append(f"  {key:>28}  n={t['n_scored']:>6}  -> UNDER_SAMPLED")
            continue
        ci = (t.get("bootstrap") or {}).get("ci95")
        ci_txt = f"[{ci[0]:+.4f},{ci[1]:+.4f}]" if ci else "—"
        delta = t.get("mcc_delta_vs_incumbent")
        delta_txt = f"{delta:+.4f}" if delta is not None else "n/a"
        lines.append(
            f"  {key:>28}  n={t['n_scored']:>6}  MCC={t['mcc']:+.4f}  CI95={ci_txt}"
            f"  d_vs_incumbent={delta_txt}  -> {t['verdict']}"
        )
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Study #2: trivial causal challenger race")
    ap.add_argument("--db", type=Path, default=None, help="SQLite DB (default: canonical console DB)")
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "reports" / "challenger_eval",
    )
    args = ap.parse_args()
    db = args.db
    if db is None:
        from db import DB_PATH

        db = Path(DB_PATH)
    if not Path(db).is_file():
        print(f"DB not found: {db}", file=sys.stderr)
        return 1
    report = run_study(db)
    path = write_report(report, args.out_dir)
    print(_console_summary(report))
    print(f"report: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
