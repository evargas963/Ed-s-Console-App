"""
Pilot Step 3 runner: load prereg, data, events, label grid, write reports.

Usage:
  python -m research.pilot_step3.pilot_runner [--db PATH] [--start-date YYYY-MM-DD] [--end-date YYYY-MM-DD]
  python -m research.pilot_step3.pilot_runner --source-table price_bars_1m_staging --batch-id <id> ...

Does not wire to production UI or legacy signal authority.
Reads ``price_bars_1m`` by default; optional staging reads do not merge into canonical bars.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import subprocess
import sys
import time
import uuid
import warnings
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from research.pilot_step3 import pilot_config
from research.pilot_step3.data_loader import load_spy_1m_bars, sufficient_history
from research.pilot_step3.event_generation import generate_events
from research.pilot_step3.labeling import build_atr_series, label_event_cell
from research.pilot_step3.metrics import aggregate_cell, cell_to_dict
from research.pilot_step3.scaffold_audit import legacy_stack_contamination_scan

try:
    from db import DB_PATH
except Exception:  # pragma: no cover
    DB_PATH = None


def _setup_logging(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(log_path, encoding="utf-8"), logging.StreamHandler(sys.stdout)],
    )


def _run_pytest_pilot_tests(root: Path) -> tuple[bool, str]:
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "tests/test_pilot_step3_trade_labels.py",
        "tests/test_pilot_step3_events.py",
        "tests/test_pilot_step3_data_loader.py",
        "tests/test_pilot_step3_sigma_contract.py",
        "tests/test_pilot_prereg_framework_binding.py",
        "-q",
    ]
    r = subprocess.run(cmd, cwd=str(root), capture_output=True, text=True)
    out = (r.stdout or "") + "\n" + (r.stderr or "")
    return r.returncode == 0, out.strip()


def _verify_next_bar_open_labels(
    events: list,
    bars: list,
    atr_series: list,
    *,
    stop_atr: float,
    target_atr: float,
    vertical_minutes: int,
    cost_bp: float,
) -> bool:
    """True if every resolved label uses entry at signal_bar_index + 1 (not signal bar T)."""
    for ev in events:
        lb = label_event_cell(
            bars,
            atr_series,
            ev,
            stop_atr=stop_atr,
            target_atr=target_atr,
            vertical_minutes=vertical_minutes,
            cost_round_trip_bp=cost_bp,
        )
        if lb.withheld_reason or lb.label_conservative is None:
            continue
        i_ent = ev.signal_bar_index + 1
        if i_ent >= len(bars):
            return False
        b = bars[i_ent]
        if abs(lb.entry_ts_utc - b.bar_start_ts_utc) > 1e-2:
            return False
        if abs(lb.entry_price - b.open) > 1e-5 * max(1.0, abs(b.open)):
            return False
    return True


def _verify_costs_do_not_change_classification(
    events: list,
    bars: list,
    atr_series: list,
    *,
    stop_atr: float,
    target_atr: float,
    vertical_minutes: int,
) -> bool:
    """WIN/LOSS/TIMEOUT (conservative) and barrier_hit invariant to post-label cost."""
    c_lo, c_hi = 0.0, 50_000.0
    for ev in events:
        lb0 = label_event_cell(
            bars,
            atr_series,
            ev,
            stop_atr=stop_atr,
            target_atr=target_atr,
            vertical_minutes=vertical_minutes,
            cost_round_trip_bp=c_lo,
        )
        lb1 = label_event_cell(
            bars,
            atr_series,
            ev,
            stop_atr=stop_atr,
            target_atr=target_atr,
            vertical_minutes=vertical_minutes,
            cost_round_trip_bp=c_hi,
        )
        if lb0.withheld_reason != lb1.withheld_reason:
            return False
        if lb0.label_conservative != lb1.label_conservative:
            return False
        if lb0.barrier_hit != lb1.barrier_hit:
            return False
    return True


def _evaluate_scaffold_pass(
    *,
    prereg_hash_checked: bool,
    pytest_ok: bool,
    legacy_ok: bool,
    n_cells: int,
    expected_cells: int,
    purge_ok: bool,
    artifacts_ok: bool,
    label_path_ok: bool,
    cost_invariant_ok: bool,
) -> tuple[bool, dict[str, object]]:
    reasons: list[str] = []
    if not prereg_hash_checked:
        reasons.append("prereg_hash_not_validated")
    if not pytest_ok:
        reasons.append("pytest_pilot_tests_failed")
    if not legacy_ok:
        reasons.append("legacy_stack_contamination_scan_failed")
    if n_cells != expected_cells:
        reasons.append(f"cell_count_mismatch got={n_cells} expected={expected_cells}")
    if not purge_ok:
        reasons.append("purge_embargo_status_not_NOT_IMPLEMENTED_IN_PILOT_V1_everywhere")
    if not artifacts_ok:
        reasons.append("missing_output_artifacts")
    if not label_path_ok:
        reasons.append("label_path_not_strictly_next_bar_after_signal")
    if not cost_invariant_ok:
        reasons.append("costs_altered_classification_or_barrier_hit")
    ok = len(reasons) == 0
    return ok, {
        "scaffold_PASS": ok,
        "scaffold_FAIL_reasons": reasons,
        "criteria": {
            "prereg_hash_validated": prereg_hash_checked,
            "pytest_pilot_modules_passed": pytest_ok,
            "no_legacy_decision_imports_in_pilot_py": legacy_ok,
            "all_barrier_cells_completed_no_crash": n_cells == expected_cells,
            "purge_embargo_status_NOT_IMPLEMENTED_IN_PILOT_V1": purge_ok,
            "artifacts_pilot_summary_json_csv_manifest_log": artifacts_ok,
            "no_label_path_on_signal_bar_T": label_path_ok,
            "costs_do_not_alter_WIN_LOSS_TIMEOUT": cost_invariant_ok,
        },
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Pilot Step 3 trade-outcome label scaffold")
    ap.add_argument("--db", default=None, help="SQLite path (default: db.DB_PATH)")
    ap.add_argument("--start-date", default=None, metavar="YYYY-MM-DD", help="ET date inclusive lower bound on bar_start")
    ap.add_argument("--end-date", default=None, metavar="YYYY-MM-DD", help="ET date inclusive upper bound on bar_start")
    ap.add_argument(
        "--skip-hash-check",
        action="store_true",
        help="Deprecated: prereg integrity is always enforced in load_prereg(); flag is ignored for validation.",
    )
    ap.add_argument("--fix-prereg-hash", action="store_true", help="Print computed content_hash for prereg_v1.json")
    ap.add_argument(
        "--skip-pytest",
        action="store_true",
        help="Do not run pytest from the runner (scaffold will FAIL this criterion unless tests were run elsewhere).",
    )
    ap.add_argument(
        "--source-table",
        default="price_bars_1m",
        choices=["price_bars_1m", "price_bars_1m_staging"],
        help="1m OHLCV table to read (default: price_bars_1m)",
    )
    ap.add_argument(
        "--batch-id",
        default=None,
        metavar="ID",
        help="Required when --source-table is price_bars_1m_staging; filters staging rows",
    )
    args = ap.parse_args(argv)
    if args.source_table == "price_bars_1m_staging" and not (args.batch_id or "").strip():
        ap.error("--batch-id is required when --source-table is price_bars_1m_staging")

    if args.fix_prereg_hash:
        prereg = pilot_config.load_prereg(validate=False)
        print(pilot_config.prereg_content_hash(prereg))
        return 0

    prereg = pilot_config.load_prereg()
    if args.skip_hash_check:
        warnings.warn(
            "--skip-hash-check is deprecated; load_prereg() always validates hash and framework binding",
            DeprecationWarning,
            stacklevel=1,
        )

    prereg_hash_checked = True

    db_path = args.db or (str(DB_PATH) if DB_PATH else None)
    if not db_path:
        logging.error("No database path: pass --db or ensure db.DB_PATH resolves")
        return 2

    run_id = str(uuid.uuid4())[:12]
    base = Path(__file__).resolve().parent
    reports = base / "reports"
    manifests = base / "manifests"
    logs = base / "logs"
    reports.mkdir(parents=True, exist_ok=True)
    manifests.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)

    log_path = logs / f"{run_id}.log"
    _setup_logging(log_path)
    log = logging.getLogger("pilot_runner")

    legacy_ok, leg_violations = legacy_stack_contamination_scan(pilot_dir=base)
    if not legacy_ok:
        for v in leg_violations:
            log.error("legacy_scan: %s", v)

    t0 = time.perf_counter()
    rep = load_spy_1m_bars(
        db_path,
        ticker=prereg["instrument"]["ticker"],
        start_date=args.start_date,
        end_date=args.end_date,
        source_table=args.source_table,
        batch_id=(args.batch_id or "").strip() or None,
    )
    min_bars = int(prereg["data"]["min_bars_required"])
    if not sufficient_history(rep, min_bars=min_bars):
        log.error("Insufficient history or data integrity: %s", rep.withheld_reason or rep.n_rth_rows)
        return 3

    log.info(
        "Loaded RTH bars=%s ET_range=%s..%s date_filters=%s..%s "
        "source_table=%s batch_id=%s staging_mode=%s",
        rep.n_rth_rows,
        rep.et_date_first,
        rep.et_date_last,
        args.start_date or "*",
        args.end_date or "*",
        rep.source_table,
        rep.batch_id if rep.staging_mode else None,
        rep.staging_mode,
    )

    gaps_flag = rep.rth_gap_count > 0
    if gaps_flag:
        log.warning("RTH gaps detected: count=%s max_gap_s=%.1f", rep.rth_gap_count, rep.rth_gap_seconds_max)

    atr_series = build_atr_series(rep.bars)
    events, ev_stats = generate_events(rep.bars, prereg)
    dropped_none = int(ev_stats.get("dropped_none_sma_near_equal", 0))
    log.info(
        "events=%s dropped_none_count=%s bars_rth=%s",
        len(events),
        dropped_none,
        rep.n_rth_rows,
    )

    grid = pilot_config.pilot_grid(prereg)
    cost_bp = float(prereg["costs"]["round_trip_bp"])

    cell_rows: list[dict] = []
    for cell in grid:
        t_cell = time.perf_counter()
        labels = []
        for ev in events:
            lb = label_event_cell(
                rep.bars,
                atr_series,
                ev,
                stop_atr=cell["stop_atr"],
                target_atr=cell["target_atr"],
                vertical_minutes=int(cell["vertical_minutes"]),
                cost_round_trip_bp=cost_bp,
            )
            labels.append(lb)
        dt = time.perf_counter() - t_cell
        cm = aggregate_cell(
            cell["cell_id"],
            cell["stop_atr"],
            cell["target_atr"],
            int(cell["vertical_minutes"]),
            labels,
            raw_event_count=len(events),
            rules=prereg["pilot_rejection_rules"],
            runtime_sec=dt,
            data_gaps_flag=gaps_flag,
        )
        cell_rows.append(cell_to_dict(cm))

    expected_cells = int(prereg["barrier_grid"]["total_cells"])
    purge_ok = all(
        row.get("purge_embargo_status") == "NOT_IMPLEMENTED_IN_PILOT_V1" for row in cell_rows
    ) and len(cell_rows) == expected_cells

    probe = grid[0]
    label_path_ok = _verify_next_bar_open_labels(
        events,
        rep.bars,
        atr_series,
        stop_atr=float(probe["stop_atr"]),
        target_atr=float(probe["target_atr"]),
        vertical_minutes=int(probe["vertical_minutes"]),
        cost_bp=cost_bp,
    )
    cost_invariant_ok = _verify_costs_do_not_change_classification(
        events,
        rep.bars,
        atr_series,
        stop_atr=float(probe["stop_atr"]),
        target_atr=float(probe["target_atr"]),
        vertical_minutes=int(probe["vertical_minutes"]),
    )

    if args.skip_pytest:
        pytest_ok, pytest_log = False, "skipped_by_flag"
        log.warning("pytest skipped via --skip-pytest; scaffold_PASS cannot succeed on criterion pytest")
    else:
        pytest_ok, pytest_log = _run_pytest_pilot_tests(_ROOT)
    if not pytest_ok and not args.skip_pytest:
        log.error("pytest pilot tests failed:\n%s", pytest_log)

    json_path = reports / "pilot_summary.json"
    csv_path = reports / "pilot_summary.csv"
    manifest_path = manifests / f"{run_id}.json"

    summary = {
        "run_id": run_id,
        "instrument": prereg["instrument"]["ticker"],
        "source_table": rep.source_table,
        "batch_id": rep.batch_id,
        "staging_mode": rep.staging_mode,
        "n_bars_rth": rep.n_rth_rows,
        "et_date_first": rep.et_date_first,
        "et_date_last": rep.et_date_last,
        "date_filter_start": args.start_date,
        "date_filter_end": args.end_date,
        "n_events": len(events),
        "event_stats": ev_stats,
        "dropped_none_count": dropped_none,
        "rth_gaps": rep.rth_gap_count,
        "purge_embargo_status": "NOT_IMPLEMENTED_IN_PILOT_V1",
        "elapsed_sec": time.perf_counter() - t0,
        "cells": len(cell_rows),
    }

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        if cell_rows:
            w = csv.DictWriter(f, fieldnames=list(cell_rows[0].keys()))
            w.writeheader()
            w.writerows(cell_rows)

    json_path.write_text(json.dumps({"summary": summary, "cells": cell_rows}, indent=2), encoding="utf-8")
    manifest = {
        "run_id": run_id,
        "prereg_content_hash": prereg.get("content_hash"),
        "db_path": db_path,
        "source_table": rep.source_table,
        "batch_id": rep.batch_id,
        "staging_mode": rep.staging_mode,
        "summary": summary,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    artifacts_ok = (
        json_path.is_file()
        and json_path.stat().st_size > 0
        and csv_path.is_file()
        and csv_path.stat().st_size > 0
        and manifest_path.is_file()
        and manifest_path.stat().st_size > 0
        and log_path.is_file()
    )

    scaffold_ok, scaffold_detail = _evaluate_scaffold_pass(
        prereg_hash_checked=prereg_hash_checked,
        pytest_ok=pytest_ok,
        legacy_ok=legacy_ok,
        n_cells=len(cell_rows),
        expected_cells=expected_cells,
        purge_ok=purge_ok,
        artifacts_ok=artifacts_ok,
        label_path_ok=label_path_ok,
        cost_invariant_ok=cost_invariant_ok,
    )
    summary["scaffold_evaluation"] = scaffold_detail
    json_path.write_text(json.dumps({"summary": summary, "cells": cell_rows}, indent=2), encoding="utf-8")
    manifest["summary"] = summary
    manifest["scaffold_PASS"] = scaffold_detail.get("scaffold_PASS")
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    log.info("scaffold_PASS=%s detail=%s", scaffold_ok, scaffold_detail)

    if not scaffold_ok:
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
