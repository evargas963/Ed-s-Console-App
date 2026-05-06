"""CLI wrapper for manual A1 conformal artifact production."""

from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

from calibration.a1_conformal_artifact_production import produce_a1_conformal_artifact


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Produce an A1 conformal artifact manually.")
    parser.add_argument("--db-path", required=True, type=Path)
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--horizon", required=True)
    parser.add_argument("--train-start", required=True, type=float)
    parser.add_argument("--train-end", required=True, type=float)
    parser.add_argument("--calibration-start", required=True, type=float)
    parser.add_argument("--calibration-end", required=True, type=float)
    parser.add_argument("--holdout-start", required=True, type=float)
    parser.add_argument("--holdout-end", required=True, type=float)
    parser.add_argument("--eval-start", required=True, type=float)
    parser.add_argument("--eval-end", required=True, type=float)
    parser.add_argument("--governed-max-age-seconds", required=True, type=float)
    parser.add_argument("--data-root", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(message)s")
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        result = produce_a1_conformal_artifact(
            db_path=args.db_path,
            ticker=args.ticker,
            horizon=args.horizon,
            train_start=args.train_start,
            train_end=args.train_end,
            calibration_start=args.calibration_start,
            calibration_end=args.calibration_end,
            holdout_start=args.holdout_start,
            holdout_end=args.holdout_end,
            eval_start=args.eval_start,
            eval_end=args.eval_end,
            governed_max_age_seconds=args.governed_max_age_seconds,
            now_epoch_seconds=time.time(),
            data_root=args.data_root,
        )
    except Exception:
        logging.exception("A1 conformal artifact production failed")
        return 2

    logging.info(
        "A1 conformal artifact production status=%s pointer_updated=%s artifact_path=%s eligibility_reason=%s",
        result["status"],
        result["pointer_updated"],
        result["artifact_path"],
        result["eligibility_reason"],
    )
    return 0 if result["pointer_updated"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
