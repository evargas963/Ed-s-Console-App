"""Study #1 runner: score recorded live fusion predictions vs attached outcomes.

Usage (read-only against the canonical DB):
  python -m research.incumbent_eval_v1.runner
  python -m research.incumbent_eval_v1.runner --db data/ed_console.db --out-dir reports/incumbent_eval

Every gate, metric, baseline, floor, and seed comes from prereg_v1.json in this
package — the runner refuses to run if the prereg file is missing or its
frozen fields disagree with the code's expectations.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from research.incumbent_eval_v1 import stats
from calibration.operable_surface_quarantine import operable_filter_sql

PREREG_PATH = Path(__file__).resolve().parent / "prereg_v1.json"
_HZ_MINUTES = {"1c": 1, "5c": 5, "15c": 15, "60c": 60}


class PreregViolationError(RuntimeError):
    """The frozen preregistration is missing or inconsistent — refuse to run."""


def load_prereg() -> dict[str, Any]:
    try:
        prereg = json.loads(PREREG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise PreregViolationError(f"cannot load preregistration {PREREG_PATH}: {e}") from e
    family = prereg.get("family") or {}
    expected_cells = len(family.get("tickers") or []) * len(family.get("horizons") or [])
    if expected_cells != family.get("n_cells"):
        raise PreregViolationError(
            f"prereg family inconsistent: {len(family.get('tickers') or [])} tickers x"
            f" {len(family.get('horizons') or [])} horizons != n_cells={family.get('n_cells')}"
        )
    if prereg.get("primary_metric", {}).get("name", "").split(" ")[0] != "MCC":
        raise PreregViolationError("prereg primary metric is not MCC — code and prereg diverged")
    return prereg


def invalid_threshold_horizons() -> list[str]:
    """Horizons whose governed movement threshold is missing/non-positive —
    their outcome labels are untrusted (same exclusion the v4 scoreboard applies)."""
    from movement_target_threshold import load_movement_thresholds_by_horizon_v1

    cfg = load_movement_thresholds_by_horizon_v1()
    horizons = cfg.get("horizons") or {}
    invalid: list[str] = []
    for hz in _HZ_MINUTES:
        raw = (horizons.get(hz) or {}).get("threshold_move_pts")
        try:
            if raw is None or float(raw) <= 0.0:
                invalid.append(hz)
        except (TypeError, ValueError):
            invalid.append(hz)
    return invalid


def load_cell_rows(
    db_path: Path | str, tickers: list[str], horizons: list[str]
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """Time-ordered scored rows per (ticker, horizon).

    Row gates (identical to calibration.daily_scoreboard's scoring pass):
    trusted calibration rows, RTH decisions only, horizon fusion available with
    a finite probability triplet, and an attached up/down/flat outcome label.
    """
    from time_et import ET, is_tradable_session_ts_utc

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
            if not is_tradable_session_ts_utc(ts):
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
                pred = blk.get("dominant_direction")
                if pred not in stats.CLASSES or truth not in stats.CLASSES:
                    continue
                probs = {}
                ok = True
                for c in stats.CLASSES:
                    try:
                        v = float(blk.get(f"prob_{c}"))
                    except (TypeError, ValueError):
                        ok = False
                        break
                    probs[f"prob_{c}"] = v
                if not ok:
                    continue
                cells[(str(row["ticker"]), hz)].append(
                    {
                        "ts": ts,
                        "et_date": et_date,
                        "pred": pred,
                        "truth": truth,
                        **probs,
                    }
                )
    finally:
        conn.close()
    return cells


def evaluate_cell(rows: list[dict[str, Any]], hz: str, prereg: dict[str, Any]) -> dict[str, Any]:
    """All prereg metrics for one (ticker, horizon) cell. Pure given rows."""
    floors = prereg["sample_floors"]
    rnd = prereg["randomness"]
    preds = [r["pred"] for r in rows]
    truths = [r["truth"] for r in rows]
    days = sorted({r["et_date"] for r in rows})
    hz_min = _HZ_MINUTES[hz]
    n_windows = len({int(r["ts"] // (hz_min * 60.0)) for r in rows})
    cm = stats.confusion_matrix(preds, truths)
    out: dict[str, Any] = {
        "n_scored": len(rows),
        "n_distinct_days": len(days),
        "date_range": [days[0], days[-1]] if days else None,
        "n_independent_windows": n_windows,
        "confusion_matrix": cm,
        "mcc": stats.mcc_multiclass(cm),
        "balanced_accuracy": stats.balanced_accuracy(cm),
        "accuracy": stats.accuracy(cm),
        "log_loss": stats.multiclass_log_loss(rows, truths),
        "baselines": stats.baseline_accuracies(preds, truths),
        "warnings": [],
    }
    if len(rows) > n_windows:
        out["warnings"].append("EFFECTIVE_SAMPLE_NOT_PROVEN")
    under_sampled = (
        len(rows) < int(floors["min_scored_rows_per_cell"])
        or len(days) < int(floors["min_distinct_days_per_cell"])
    )
    out["under_sampled"] = under_sampled
    if under_sampled:
        out["warnings"].append("UNDER_SAMPLED")
        out["bootstrap"] = None
        out["shuffle_control"] = None
        return out
    out["bootstrap"] = stats.day_block_bootstrap_mcc(
        preds, truths, [r["et_date"] for r in rows],
        n_boot=int(rnd["bootstrap_B"]), seed=int(rnd["seed"]),
    )
    out["shuffle_control"] = stats.shuffle_control_mcc(
        preds, truths, n_shuffles=int(rnd["shuffle_K"]), seed=int(rnd["seed"]),
    )
    return out


def apply_advancement_screen(cells: dict[str, dict[str, Any]], prereg: dict[str, Any]) -> None:
    """PASS/FAIL per the frozen screen; mutates each cell dict in place."""
    p_values = {
        key: (cell.get("bootstrap") or {}).get("p_value") if not cell["under_sampled"] else None
        for key, cell in cells.items()
    }
    holm = stats.holm_bonferroni(p_values)
    for key, cell in cells.items():
        cell["holm"] = holm[key]
        if cell["under_sampled"]:
            cell["verdict"] = "UNDER_SAMPLED"
            continue
        boot = cell.get("bootstrap") or {}
        ci = boot.get("ci95")
        sc = cell.get("shuffle_control") or {}
        shuffle_ok = (
            sc.get("null_q025") is not None
            and sc["null_q025"] <= 0.0 <= sc["null_q975"]
        )
        if not shuffle_ok:
            cell["verdict"] = "STOP_SHUFFLE_CONTROL_FAILED"
            cell["warnings"].append("SHUFFLE_NULL_NOT_CENTERED_AT_ZERO")
            continue
        acc = cell["accuracy"]
        base = cell["baselines"]
        beats_baselines = acc is not None and all(
            base[b] is None or acc >= base[b]
            for b in ("always_flat", "majority_class", "persistence")
        )
        ci_excludes_zero = bool(ci) and (ci[0] > 0.0 or ci[1] < 0.0)
        significant = holm[key]["significant"] is True
        cell["screen"] = {
            "ci95_excludes_zero": ci_excludes_zero,
            "holm_significant": significant,
            "beats_all_baselines": beats_baselines,
            "shuffle_control_ok": shuffle_ok,
        }
        cell["verdict"] = (
            "PASS" if (ci_excludes_zero and significant and beats_baselines) else "FAIL"
        )


def run_study(db_path: Path | str) -> dict[str, Any]:
    prereg = load_prereg()
    family = prereg["family"]
    tickers = [str(t) for t in family["tickers"]]
    horizons = [str(h) for h in family["horizons"]]
    invalid_hz = invalid_threshold_horizons()
    usable_horizons = [h for h in horizons if h not in invalid_hz]
    raw_cells = load_cell_rows(db_path, tickers, usable_horizons)
    cells: dict[str, dict[str, Any]] = {}
    for (ticker, hz), rows in sorted(raw_cells.items()):
        cells[f"{ticker}:{hz}"] = evaluate_cell(rows, hz, prereg)
    apply_advancement_screen(cells, prereg)
    verdicts = [c["verdict"] for c in cells.values()]
    n_pass = verdicts.count("PASS")
    n_stop = verdicts.count("STOP_SHUFFLE_CONTROL_FAILED")
    summary_verdict = (
        "STOP_SHUFFLE_CONTROL_FAILED" if n_stop
        else "INSUFFICIENT_DATA" if all(v == "UNDER_SAMPLED" for v in verdicts)
        else "SIGNAL_DETECTED_IN_SOME_CELLS" if n_pass
        else "NO_SIGNAL_DETECTED"
    )
    return {
        "schema_version": "1",
        "prereg_id": prereg["prereg_id"],
        "prereg_sha_note": "prereg file is version-controlled; report embeds its frozen parameters",
        "generated_utc": datetime.now(tz=timezone.utc).isoformat(),
        "run_id": uuid.uuid4().hex[:12],
        "db_path": str(Path(db_path).resolve()),
        "family": family,
        "randomness": prereg["randomness"],
        "sample_floors": prereg["sample_floors"],
        "invalid_threshold_horizons_excluded": invalid_hz,
        "cells": cells,
        "summary": {
            "verdict": summary_verdict,
            "n_cells": len(cells),
            "n_pass": n_pass,
            "n_fail": verdicts.count("FAIL"),
            "n_under_sampled": verdicts.count("UNDER_SAMPLED"),
            "n_stop": n_stop,
            "interpretation": prereg["outcome_interpretation"],
            "not_an_admission_packet": prereg["explicitly_not"]["not_an_admission_packet"],
        },
    }


def write_report(report: dict[str, Any], out_dir: Path | str) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    et_date = report["generated_utc"][:10]
    path = out / f"incumbent_eval_{et_date}_{report['run_id']}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    (out / "latest.json").write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def _console_summary(report: dict[str, Any]) -> str:
    lines = [
        f"incumbent_eval_v1 — {report['summary']['verdict']}"
        f" ({report['summary']['n_pass']} PASS / {report['summary']['n_fail']} FAIL /"
        f" {report['summary']['n_under_sampled']} under-sampled of {report['summary']['n_cells']} cells)",
    ]
    for key, cell in report["cells"].items():
        mcc = cell["mcc"]
        mcc_txt = f"{mcc:+.4f}" if mcc is not None else "n/a"
        boot = cell.get("bootstrap") or {}
        ci = boot.get("ci95")
        ci_txt = f"[{ci[0]:+.4f},{ci[1]:+.4f}]" if ci else "—"
        lines.append(
            f"  {key:>9}  n={cell['n_scored']:>6}  days={cell['n_distinct_days']:>3}"
            f"  MCC={mcc_txt}  CI95={ci_txt}  acc={cell['accuracy']:.3f}"
            f"  vs flat={cell['baselines']['always_flat']:.3f}"
            f"  -> {cell['verdict']}"
            if cell["accuracy"] is not None
            else f"  {key:>9}  n={cell['n_scored']:>6}  -> {cell['verdict']}"
        )
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="Study #1: incumbent stack signal-existence eval")
    ap.add_argument("--db", type=Path, default=None, help="SQLite DB (default: canonical console DB)")
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "reports" / "incumbent_eval",
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
