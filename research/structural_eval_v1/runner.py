"""Study #3 runner: race structural/dealer-positioning rules on recorded rows.

Usage (read-only against the canonical DB):
  python -m research.structural_eval_v1.runner
  python -m research.structural_eval_v1.runner --db data/ed_console.db

Reuses the Study #1 statistics and the Study #2 evaluation/screen machinery;
adds fixed semantic rules over structural fields recorded live at decision
time. Frozen parameters come from prereg_v1.json — the runner refuses to run
if the prereg is missing or inconsistent.
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

from research.challenger_eval_v1.runner import (
    apply_advancement_screen,
    challenger_prediction,
    evaluate_test,
    load_bars,
)
from research.incumbent_eval_v1 import stats
from research.incumbent_eval_v1.runner import invalid_threshold_horizons

PREREG_PATH = Path(__file__).resolve().parent / "prereg_v1.json"
RULES = ("zone_direction", "wall_attraction", "wall_repulsion", "regime_gated_momentum_15")
_ZONE_DIRECTION = {"pin_bull": "up", "pin_bear": "down", "breakout": "up", "breakdown": "down"}
_MOMENTUM_REGIMES = {"trend_continuation", "acceleration", "breakout"}


class PreregViolationError(RuntimeError):
    """The frozen preregistration is missing or inconsistent — refuse to run."""


def load_prereg() -> dict[str, Any]:
    try:
        prereg = json.loads(PREREG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise PreregViolationError(f"cannot load preregistration {PREREG_PATH}: {e}") from e
    fam = prereg.get("family") or {}
    n = len(fam.get("tickers") or []) * len(fam.get("horizons") or []) * len(fam.get("rules") or [])
    if n != fam.get("n_tests"):
        raise PreregViolationError(f"prereg family inconsistent: computed {n} != n_tests={fam.get('n_tests')}")
    if set(fam.get("rules") or []) != set(RULES):
        raise PreregViolationError("prereg rule roster diverged from code roster")
    if prereg.get("primary_metric", {}).get("name", "").split(" ")[0] != "MCC":
        raise PreregViolationError("prereg primary metric is not MCC — code and prereg diverged")
    return prereg


def zone_direction_prediction(zone: Optional[str]) -> Optional[str]:
    """Fixed semantic mapping; unknown/chaotic zones abstain honestly."""
    return _ZONE_DIRECTION.get(str(zone)) if zone else None


def wall_prediction(
    above_dist: Optional[float], below_dist: Optional[float], *, attract: bool
) -> Optional[str]:
    """Toward the nearer wall (attract) or the farther wall (repulse);
    missing/equal distances abstain — a tie carries no direction."""
    try:
        a = float(above_dist)
        b = float(below_dist)
    except (TypeError, ValueError):
        return None
    if a == b:
        return None
    toward_nearer = "up" if a < b else "down"
    if attract:
        return toward_nearer
    return "down" if toward_nearer == "up" else "up"


def regime_gated_momentum_prediction(
    regime_primary: Optional[str],
    closes: list[float],
    j: Optional[int],
) -> Optional[str]:
    """momentum_15 only inside directional regimes; abstain elsewhere or when
    the bar join failed (j is None)."""
    if str(regime_primary) not in _MOMENTUM_REGIMES or j is None:
        return None
    return challenger_prediction(closes, j, "momentum_15")


def load_decision_rows(
    db_path: Path | str, tickers: list[str], horizons: list[str]
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """Time-ordered scored rows per (ticker, horizon) with structural fields.
    Same gates as Studies #1/#2."""
    from time_et import ET, is_rth_ts_utc

    cells: dict[tuple[str, str], list[dict[str, Any]]] = {
        (t, hz): [] for t in tickers for hz in horizons
    }
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        sql = (
            "SELECT ticker, decision_ts_utc, model_outputs_json, zone, regime_primary,"
            " nearest_above_dist, nearest_below_dist,"
            " outcome_1c, outcome_5c, outcome_15c, outcome_60c"
            " FROM calibration_decision_log"
            " WHERE calibration_trust='trusted' AND outcomes_attached_ts_utc IS NOT NULL"
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
                        "zone": row["zone"],
                        "regime_primary": row["regime_primary"],
                        "nearest_above_dist": row["nearest_above_dist"],
                        "nearest_below_dist": row["nearest_below_dist"],
                    }
                )
    finally:
        conn.close()
    return cells


def attach_rule_predictions(
    rows: list[dict[str, Any]],
    bars: tuple[list[float], list[float]],
    max_bar_age_sec: float,
) -> dict[str, int]:
    """Mutates rows in place: adds pred_<rule> (or None). Returns abstention
    tallies per rule (abstention is honest behavior, not an error)."""
    ends, closes = bars
    abstains = {f"ABSTAIN_{r}": 0 for r in RULES}
    for r in rows:
        j = bisect.bisect_right(ends, r["ts"]) - 1
        if j < 0 or (r["ts"] - ends[j]) > max_bar_age_sec:
            j = None
        preds = {
            "zone_direction": zone_direction_prediction(r["zone"]),
            "wall_attraction": wall_prediction(
                r["nearest_above_dist"], r["nearest_below_dist"], attract=True
            ),
            "wall_repulsion": wall_prediction(
                r["nearest_above_dist"], r["nearest_below_dist"], attract=False
            ),
            "regime_gated_momentum_15": regime_gated_momentum_prediction(
                r["regime_primary"], closes, j
            ),
        }
        for rule, pred in preds.items():
            r[f"pred_{rule}"] = pred
            if pred is None:
                abstains[f"ABSTAIN_{rule}"] += 1
    return abstains


def run_study(db_path: Path | str) -> dict[str, Any]:
    prereg = load_prereg()
    fam = prereg["family"]
    tickers = [str(t) for t in fam["tickers"]]
    horizons = [str(h) for h in fam["horizons"]]
    rules = [str(r) for r in fam["rules"]]
    max_bar_age = 120.0
    invalid_hz = invalid_threshold_horizons()
    usable_horizons = [h for h in horizons if h not in invalid_hz]
    cells = load_decision_rows(db_path, tickers, usable_horizons)
    bars = load_bars(db_path, tickers)
    abstains: dict[str, dict[str, int]] = {}
    for (ticker, hz), rows in cells.items():
        s = attach_rule_predictions(rows, bars[ticker], max_bar_age)
        agg = abstains.setdefault(ticker, {k: 0 for k in s})
        for k, v in s.items():
            agg[k] = agg.get(k, 0) + v
    tests: dict[str, dict[str, Any]] = {}
    for (ticker, hz), rows in sorted(cells.items()):
        for rule in rules:
            t = evaluate_test(rows, rule, hz, prereg)
            n_rows = t["n_rows_in_cell"]
            t["abstention_rate"] = (
                (n_rows - t["n_scored"]) / n_rows if n_rows else None
            )
            tests[f"{ticker}:{hz}:{rule}"] = t
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
        "abstentions_by_ticker": abstains,
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
    path = out / f"structural_eval_{et_date}_{report['run_id']}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out / "latest.json").write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def _console_summary(report: dict[str, Any]) -> str:
    s = report["summary"]
    lines = [
        f"structural_eval_v1 — {s['verdict']}"
        f" ({s['n_pass']} PASS / {s['n_fail']} FAIL / {s['n_under_sampled']} under-sampled"
        f" of {s['n_tests']} tests; {s['n_tests_beating_incumbent_mcc']} beat incumbent MCC)",
    ]
    for key, t in report["tests"].items():
        if t["verdict"] == "UNDER_SAMPLED":
            lines.append(f"  {key:>36}  n={t['n_scored']:>6}  -> UNDER_SAMPLED")
            continue
        ci = (t.get("bootstrap") or {}).get("ci95")
        ci_txt = f"[{ci[0]:+.4f},{ci[1]:+.4f}]" if ci else "—"
        delta = t.get("mcc_delta_vs_incumbent")
        delta_txt = f"{delta:+.4f}" if delta is not None else "n/a"
        lines.append(
            f"  {key:>36}  n={t['n_scored']:>6}  MCC={t['mcc']:+.4f}  CI95={ci_txt}"
            f"  d_vs_incumbent={delta_txt}  -> {t['verdict']}"
        )
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Study #3: structural/dealer-positioning rule race")
    ap.add_argument("--db", type=Path, default=None, help="SQLite DB (default: canonical console DB)")
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "reports" / "structural_eval",
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
