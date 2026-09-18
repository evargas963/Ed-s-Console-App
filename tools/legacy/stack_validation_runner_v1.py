#!/usr/bin/env python3
"""
CLI: production stack bundle validation (XGB vs meta stack vs MC vs Bayesian fusion).

Examples (PowerShell, repo root):
  python tools/stack_validation_runner_v1.py --db (python -c "from db import DB_PATH; print(DB_PATH)") --ticker SPY --model-dir models\\parallel\\SPY

  python tools/stack_validation_runner_v1.py --ablation-only --db C:\\data\\EdConsole.sqlite --ticker QQQ --model-dir models\\parallel\\QQQ

  python tools/stack_validation_runner_v1.py --calibration-json-out models\\validation_runs\\manual\\calibration_SPY_1c.json --db ... --ticker SPY --horizons 1c
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Repo root on sys.path
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from arch_competition.stack_bundle_eval_v1 import (
    DEFAULT_ALL_MODES,
    StackBundleEvalOptions,
    VALID_MODES,
    run_stack_bundle_evaluation,
)


def _default_db() -> str:
    try:
        from db import DB_PATH

        return str(DB_PATH)
    except Exception:
        return ""


def _write_summary_csv(path: Path, horizon_manifests: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "ml_horizon_slug",
        "config",
        "n_rows_scored",
        "multiclass_log_loss",
        "balanced_accuracy",
        "macro_f1",
        "accuracy",
        "brier_score_multiclass_mean_squared_error",
        "calibration_top_predicted_class_ece",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for man in horizon_manifests:
            hz = man.get("ml_horizon_slug", "")
            for cfg, m in (man.get("metrics_by_config") or {}).items():
                row = {"ml_horizon_slug": hz, "config": cfg, **m}
                w.writerow(row)


def _write_calibration_json(path: Path, horizon_manifests: list[dict]) -> None:
    out = {"schema_version": "1", "by_horizon": {}}
    for man in horizon_manifests:
        hz = man.get("ml_horizon_slug", "")
        block = {}
        for cfg, m in (man.get("metrics_by_config") or {}).items():
            block[cfg] = {
                "reliability_bins_top_class": m.get("reliability_bins_top_class"),
                "confidence_buckets_quantile": m.get("confidence_buckets_quantile"),
                "confidence_reliability_proxy": m.get("confidence_reliability_proxy"),
                "overconfidence_diagnostics": m.get("overconfidence_diagnostics"),
                "calibration_top_predicted_class_ece": m.get("calibration_top_predicted_class_ece"),
            }
        out["by_horizon"][hz] = block
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2), encoding="utf-8")


def _write_authority_md(path: Path, horizon_manifests: list[dict]) -> None:
    lines = [
        "# Stack bundle authority report",
        "",
        f"Generated (UTC): {datetime.now(timezone.utc).isoformat()}",
        "",
        "Primary metric: **multiclass log loss** (lower is better).",
        "Paired rows: only timestamps where every requested mode produced probabilities.",
        "",
        "## Per horizon",
        "",
    ]
    for man in horizon_manifests:
        hz = man.get("ml_horizon_slug", "")
        lines.append(f"### {hz}")
        lines.append("")
        auth = man.get("authority_decision") or {}
        lines.append(f"- **Authoritative winner**: `{auth.get('authoritative_winner_config')}`")
        lines.append(f"- **Runner-up**: `{auth.get('runner_up_config')}`")
        lines.append(f"- **Winner log loss**: {auth.get('winner_multiclass_log_loss')}")
        lines.append(f"- **Margin vs runner-up**: {auth.get('margin_log_loss_vs_runner_up')}")
        lines.append(f"- **Full fusion beats XGB+meta stack (log loss)**: {auth.get('full_stack_beats_xgb_meta_stack_log_loss')}")
        lines.append(f"- **Full fusion beats XGB-only (log loss)**: {auth.get('full_fusion_beats_xgb_only_log_loss')}")
        lines.append(f"- **MC improves vs fusion-without-MC**: {auth.get('monte_carlo_improves_vs_fusion_without_mc_log_loss')}")
        lines.append(f"- **Bayesian fusion improves vs meta stack**: {auth.get('bayesian_fusion_improves_vs_meta_stack_log_loss')}")
        lines.append(
            f"- **Bayesian fusion improves vs explicit weighted triplet**: "
            f"{auth.get('bayesian_fusion_improves_vs_explicit_weighted_triplet_log_loss')}"
        )
        lines.append(f"- **Edge vs uniform 3-class**: {auth.get('edge_vs_uniform_3class_baseline')}")
        lines.append(f"- **Deployable (heuristic)**: {auth.get('deployable_now_governance_heuristic')}")
        lines.append(f"- **Policy calibration may proceed (heuristic)**: {auth.get('policy_calibration_may_proceed_heuristic')}")
        lines.append(f"- **Trade plan work may proceed (heuristic)**: {auth.get('trade_plan_work_may_proceed_heuristic')}")
        lines.append("")
        lines.append("| config | n | log_loss | bal_acc | macro_F1 | ECE |")
        lines.append("|--------|---|----------|---------|----------|-----|")
        for cfg, m in (man.get("metrics_by_config") or {}).items():
            lines.append(
                f"| {cfg} | {m.get('n_rows_scored')} | {m.get('multiclass_log_loss')} | "
                f"{m.get('balanced_accuracy')} | {m.get('macro_f1')} | {m.get('calibration_top_predicted_class_ece')} |"
            )
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Stack bundle validation (XGB / meta / MC / fusion).")
    ap.add_argument("--db", default=_default_db(), help="SQLite DB path (default: db.DB_PATH when importable)")
    ap.add_argument("--ticker", required=True, help="Ticker symbol, e.g. SPY")
    ap.add_argument(
        "--model-dir",
        default="",
        help="Directory with xgb_*.pkl, lstm_*.pt, transformer_*.pt, meta_*.pkl for horizon. Default: models/parallel/{TICKER}",
    )
    ap.add_argument(
        "--horizons",
        default="1c,5c,15c,60c",
        help="Comma-separated ml horizon slugs (must exist as trained artifacts under model-dir)",
    )
    ap.add_argument(
        "--out-dir",
        default="",
        help="Output directory. Default: models/validation_runs/<UTC>_{ticker}",
    )
    ap.add_argument(
        "--allowed-et-dates",
        default="",
        help="Optional comma-separated ET dates (YYYY-MM-DD) to restrict rows (walk-forward OOS slice)",
    )
    ap.add_argument(
        "--modes",
        default="",
        help=(
            "Comma-separated modes. Default: full component matrix "
            f"({','.join(DEFAULT_ALL_MODES)}). "
            f"Valid: {','.join(sorted(VALID_MODES))}"
        ),
    )
    ap.add_argument(
        "--ablation-only",
        action="store_true",
        help="Restrict modes to xgb_only, meta_stack, fusion_without_mc, full_fusion (skip transformer_only)",
    )
    ap.add_argument(
        "--fast-skip-fusion-mc",
        action="store_true",
        help=(
            "All DEFAULT_ALL_MODES except fusion_without_mc and full_fusion (base + blends only; "
            "no Bayesian fusion / MC — faster)."
        ),
    )
    ap.add_argument(
        "--calibration-json-out",
        default="",
        help="Write calibration-only JSON (reliability bins, buckets) to this path",
    )
    ap.add_argument("--min-paired-rows", type=int, default=50)
    ap.add_argument("--min-delta-log-loss", type=float, default=0.02)
    ap.add_argument(
        "--max-rows",
        type=int,
        default=0,
        help="Optional cap: keep only the last N chronological rows after filters (0 = no cap). Smoke / dev only.",
    )
    args = ap.parse_args()

    if not args.db or not Path(args.db).is_file():
        print("ERROR: --db must point to an existing SQLite file (or set db.DB_PATH).", file=sys.stderr)
        return 2

    ticker = args.ticker.strip().upper()
    model_dir = Path(args.model_dir) if args.model_dir else _ROOT / "models" / "parallel" / ticker
    if not model_dir.is_dir():
        print(f"ERROR: model-dir not found: {model_dir}", file=sys.stderr)
        return 2

    allowed: set[str] | None = None
    if args.allowed_et_dates.strip():
        allowed = {x.strip() for x in args.allowed_et_dates.split(",") if x.strip()}

    if args.fast_skip_fusion_mc:
        modes = tuple(m for m in DEFAULT_ALL_MODES if m not in ("fusion_without_mc", "full_fusion"))
    elif args.ablation_only:
        modes = ("xgb_only", "meta_stack", "fusion_without_mc", "full_fusion")
    elif args.modes.strip():
        modes = tuple(x.strip() for x in args.modes.split(",") if x.strip())
        bad = [m for m in modes if m not in VALID_MODES]
        if bad:
            print(
                f"ERROR: invalid mode(s) {bad!r}. Valid: {sorted(VALID_MODES)}",
                file=sys.stderr,
            )
            return 2
    else:
        modes = DEFAULT_ALL_MODES

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(args.out_dir) if args.out_dir else _ROOT / "models" / "validation_runs" / f"{ts}_{ticker}"
    out_dir.mkdir(parents=True, exist_ok=True)

    horizons_requested = [x.strip() for x in args.horizons.split(",") if x.strip()]
    horizons = []
    missing = []
    for hz in horizons_requested:
        xgb_p = model_dir / f"xgb_{ticker}_{hz}.pkl"
        if xgb_p.is_file():
            horizons.append(hz)
        else:
            missing.append(str(xgb_p))
    if not horizons:
        print(
            "ERROR: no horizons have xgb artifacts under model-dir. Missing:\n  " + "\n  ".join(missing),
            file=sys.stderr,
        )
        return 2
    if missing:
        print(
            "WARNING: skipping horizons without xgb artifact:\n  " + "\n  ".join(missing),
            file=sys.stderr,
        )

    opts = StackBundleEvalOptions(
        allowed_et_dates=allowed,
        min_paired_rows=args.min_paired_rows,
        min_delta_log_loss=args.min_delta_log_loss,
        max_rows=int(args.max_rows) if args.max_rows and args.max_rows > 0 else None,
    )

    manifests: list[dict] = []
    for hz in horizons:
        man = run_stack_bundle_evaluation(
            db_path=args.db,
            ticker=ticker,
            model_dir=model_dir,
            ml_horizon_slug=hz,
            options=opts,
            modes=modes,
        )
        man["ml_horizon_slug"] = hz
        jpath = out_dir / f"stack_bundle_{ticker}_{hz}.json"
        jpath.write_text(json.dumps(man, indent=2, default=str), encoding="utf-8")
        manifests.append(man)

    index = {
        "schema_version": "1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "db_path": str(Path(args.db).resolve()),
        "ticker": ticker,
        "model_dir": str(model_dir.resolve()),
        "horizons": horizons,
        "modes": list(modes),
        "out_dir": str(out_dir.resolve()),
        "artifacts": [str((out_dir / f"stack_bundle_{ticker}_{hz}.json").resolve()) for hz in horizons],
    }
    (out_dir / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
    _write_summary_csv(out_dir / "summary_by_horizon.csv", manifests)
    _write_authority_md(out_dir / "AUTHORITY_REPORT.md", manifests)

    cal_out = args.calibration_json_out.strip()
    if cal_out:
        _write_calibration_json(Path(cal_out), manifests)
    else:
        _write_calibration_json(out_dir / "calibration_by_horizon.json", manifests)

    print(json.dumps({"ok": True, "out_dir": str(out_dir.resolve()), "horizons": horizons}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
