#!/usr/bin/env python3
"""
Per-horizon temperature calibration for the fusion output triplet (up/down/flat).

Operator design (2026-06-10): the stack stays one contiguous pipeline — calibration
applies at exactly ONE door, the per-horizon Bayesian fusion triplet, never inside
any layer. Temperature scaling is the most sample-efficient honest method (one
parameter per horizon): p_cal_i = p_i^(1/T) / sum_j p_j^(1/T). T > 1 flattens
overconfident probabilities (the observed 60c failure mode: high top_probability
on misses), T < 1 sharpens, T = 1 is identity. Ranking is preserved, so the
dominant direction NEVER changes — only the honesty of the confidence number.

Fit data: trusted calibration_decision_log rows (RTH, pooled tickers) with the
per-horizon outcome label attached by calibration.backfill_outcomes. The fitter
reads the RAW triplet (prob_up_raw when present — logged once the serve hook is
live — else prob_up from the pre-calibration era), so refits never calibrate
already-calibrated probabilities.

Apply gate (fail-closed, per horizon): a temperature is only marked apply=true
when (a) the fit window has >= MIN_FIT_SAMPLES rows, (b) the chronological
holdout has >= MIN_HOLDOUT_SAMPLES rows, and (c) holdout NLL strictly improves
vs the raw triplet. Anything else serves the raw triplet unchanged.

Usage (operator / scheduled):
  python -m calibration.fusion_temperature                # fit all horizons, write artifact
  python -m calibration.fusion_temperature SPY QQQ IWM    # ticker-filtered fit
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Optional

from instrument_identity import ticker_storage_key

log = logging.getLogger(__name__)

HORIZON_SLUGS = ("1c", "5c", "15c", "60c")
ARTIFACT_SCHEMA_VERSION = "1"
DEFAULT_ARTIFACT_PATH = (
    Path(__file__).resolve().parents[1] / "models" / "calibration" / "fusion_temperature.json"
)

MIN_FIT_SAMPLES = 500
MIN_HOLDOUT_SAMPLES = 125
HOLDOUT_FRACTION = 0.2  # chronological tail — never random (no leakage across time)
# Fit-window floor: only rows logged AT OR AFTER the serve-stack repair commit
# 561d9fe (2026-06-09 21:37:52 ET — XGB qqq_vs_spy serve crash + Schwab ms-epoch
# bar regression) are admissible fit data. Rows before it carry triplets emitted
# by the broken serve stack: measured per-session raw NLL 1.4–2.4 vs uniform
# 1.0986 (systematic anti-skill), while post-repair sessions beat uniform raw
# (0.94–1.00). Mixing the eras drove the 2026-06-10 fit to T=16 pinned at the
# grid edge — near-uniform flattening that made the 1c/5c tradeable gate
# (TRADEABLE_DOM_MIN=0.38) structurally unreachable. The floor moves forward
# only when a serve-stack break invalidates logged probabilities again.
FIT_WINDOW_FLOOR_UTC = 1781059072.0  # git show -s --format=%ct 561d9fe
# Grid bounds cover sharpening (0.25) through near-uniform flattening (16.0): the
# 2026-06-10 production fit pinned at a 4.0 upper bound on every applied horizon,
# so the bound was raised — T=16 maps a 0.8 top prob to ~0.36, i.e. the honest
# "barely better than uniform" statement the holdout NLL was asking for. 97
# log-spaced points give ~4.4%/step resolution, finer than the NLL curvature needs.
TEMPERATURE_GRID = tuple(
    round(0.25 * (64.0 ** (i / 96.0)), 6) for i in range(97)
)
_PROB_FLOOR = 1e-9
_OUTCOME_INDEX = {"up": 0, "down": 1, "flat": 2}


def apply_temperature(
    pu: float, pd: float, pf: float, temperature: float
) -> tuple[float, float, float]:
    """Power-scale a normalized triplet by 1/T and renormalize. Order-preserving."""
    t = float(temperature)
    if not math.isfinite(t) or t <= 0:
        raise ValueError(f"temperature must be finite and > 0, got {temperature!r}")
    if t == 1.0:
        return pu, pd, pf
    scaled = [max(float(p), _PROB_FLOOR) ** (1.0 / t) for p in (pu, pd, pf)]
    s = sum(scaled)
    return scaled[0] / s, scaled[1] / s, scaled[2] / s


def _nll(rows: list[dict[str, Any]], temperature: float) -> float:
    """Mean negative log-likelihood of the observed outcome under the (scaled) triplet."""
    total = 0.0
    for r in rows:
        pu, pd, pf = apply_temperature(r["prob_up"], r["prob_down"], r["prob_flat"], temperature)
        p_true = (pu, pd, pf)[_OUTCOME_INDEX[r["outcome"]]]
        total += -math.log(max(p_true, _PROB_FLOOR))
    return total / len(rows)


def load_fusion_calibration_rows(
    db_path: Path | str,
    tickers: Optional[list[str]] = None,
    min_decision_ts_utc: float = FIT_WINDOW_FLOOR_UTC,
) -> dict[str, list[dict[str, Any]]]:
    """Per horizon: trusted RTH decision rows with raw fusion triplet + outcome label.

    Rows before ``min_decision_ts_utc`` (default: the serve-stack repair floor)
    are excluded — their logged triplets predate the current serve stack and
    poison the temperature fit (see FIT_WINDOW_FLOOR_UTC).
    """
    from time_et import is_rth_ts_utc

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    sql = (
        "SELECT ticker, decision_ts_utc, model_outputs_json,"
        " outcome_1c, outcome_5c, outcome_15c, outcome_60c"
        " FROM calibration_decision_log"
        " WHERE calibration_trust='trusted' AND model_outputs_json IS NOT NULL"
        " AND decision_ts_utc >= ?"
    )
    params: list[Any] = [float(min_decision_ts_utc)]
    if tickers:
        sql += f" AND ticker IN ({','.join('?' * len(tickers))})"
        params.extend(tickers)
    out: dict[str, list[dict[str, Any]]] = {hz: [] for hz in HORIZON_SLUGS}
    try:
        for row in conn.execute(sql + " ORDER BY decision_ts_utc", params):
            if not is_rth_ts_utc(float(row["decision_ts_utc"])):
                continue
            try:
                bundle = json.loads(row["model_outputs_json"] or "{}")
            except (TypeError, ValueError):
                continue
            sb = bundle.get("stack_probs_bundle") or {}
            by_hz = (sb.get("multi_horizon_ml_fusion_bundle") or {}).get("by_horizon") or {}
            for hz in HORIZON_SLUGS:
                outcome = row[f"outcome_{hz}"]
                if outcome not in _OUTCOME_INDEX:
                    continue
                blk = by_hz.get(hz)
                if not isinstance(blk, dict) or not blk.get("horizon_fusion_available"):
                    continue
                # RAW triplet: prob_*_raw once the serve hook logs it; legacy rows
                # predate calibration so prob_* IS raw there. Never fit on calibrated.
                triplet = {}
                for k in ("up", "down", "flat"):
                    v = blk.get(f"prob_{k}_raw")
                    if v is None:
                        v = blk.get(f"prob_{k}")
                    try:
                        fv = float(v)
                    except (TypeError, ValueError):
                        fv = float("nan")
                    triplet[k] = fv
                if any(not math.isfinite(v) or v < 0 for v in triplet.values()):
                    continue
                s = sum(triplet.values())
                if s <= 0:
                    continue
                out[hz].append(
                    {
                        "ticker": str(row["ticker"]),
                        "decision_ts_utc": float(row["decision_ts_utc"]),
                        "prob_up": triplet["up"] / s,
                        "prob_down": triplet["down"] / s,
                        "prob_flat": triplet["flat"] / s,
                        "outcome": str(outcome),
                    }
                )
    finally:
        conn.close()
    return out


def fit_horizon_temperature(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Fit one horizon's temperature on a chronological split with a no-harm holdout gate."""
    n = len(rows)
    n_holdout = int(round(n * HOLDOUT_FRACTION))
    n_fit = n - n_holdout
    result: dict[str, Any] = {
        "n_rows": n,
        "n_fit": n_fit,
        "n_holdout": n_holdout,
        "temperature": None,
        "nll_holdout_raw": None,
        "nll_holdout_calibrated": None,
        "apply": False,
        "status": "ok",
    }
    if n_fit < MIN_FIT_SAMPLES or n_holdout < MIN_HOLDOUT_SAMPLES:
        result["status"] = "insufficient_sample"
        return result
    fit_rows, holdout_rows = rows[:n_fit], rows[n_fit:]
    best_t = min(TEMPERATURE_GRID, key=lambda t: _nll(fit_rows, t))
    if best_t in (TEMPERATURE_GRID[0], TEMPERATURE_GRID[-1]):
        log.warning(
            "fusion_temperature: best T=%s pinned at grid edge — the NLL optimum lies "
            "outside [%s, %s]; consider widening TEMPERATURE_GRID",
            best_t,
            TEMPERATURE_GRID[0],
            TEMPERATURE_GRID[-1],
        )
    nll_raw = _nll(holdout_rows, 1.0)
    nll_cal = _nll(holdout_rows, best_t)
    result["temperature"] = best_t
    result["nll_holdout_raw"] = round(nll_raw, 6)
    result["nll_holdout_calibrated"] = round(nll_cal, 6)
    # No-harm gate: only apply when the holdout strictly improves. T=1.0 (identity)
    # never improves strictly, so it correctly stays apply=false.
    result["apply"] = bool(nll_cal < nll_raw)
    if not result["apply"]:
        result["status"] = "no_holdout_improvement"
    return result


def fit_fusion_temperature_artifact(
    db_path: Path | str,
    tickers: Optional[list[str]] = None,
    min_decision_ts_utc: float = FIT_WINDOW_FLOOR_UTC,
) -> dict[str, Any]:
    """Fit all four horizons and return the JSON-serializable artifact."""
    rows_by_hz = load_fusion_calibration_rows(
        db_path, tickers=tickers, min_decision_ts_utc=min_decision_ts_utc
    )
    artifact: dict[str, Any] = {
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "method": "temperature_scaling",
        "raw_probability_field": "multi_horizon_ml_fusion_bundle.by_horizon.{hz}.prob_*",
        "fitted_at_utc": time.time(),
        "db_path": str(db_path),
        "tickers": sorted(tickers) if tickers else None,
        "fit_window_floor_utc": float(min_decision_ts_utc),
        "by_horizon": {},
    }
    for hz in HORIZON_SLUGS:
        artifact["by_horizon"][hz] = fit_horizon_temperature(rows_by_hz[hz])
    return artifact


def write_fusion_temperature_artifact(
    artifact: dict[str, Any], path: Path | str = DEFAULT_ARTIFACT_PATH
) -> Path:
    from arch_competition.atomic_io import write_json_file_atomically

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    write_json_file_atomically(p, artifact, indent=2, sort_keys=True)
    return p


def load_applied_temperatures(path: Path | str = DEFAULT_ARTIFACT_PATH) -> dict[str, float]:
    """Per-horizon temperatures that passed the apply gate. {} on any problem (fail-closed)."""
    p = Path(path)
    try:
        artifact = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(artifact, dict) or artifact.get("method") != "temperature_scaling":
        return {}
    out: dict[str, float] = {}
    for hz, blk in (artifact.get("by_horizon") or {}).items():
        if not isinstance(blk, dict) or not blk.get("apply"):
            continue
        try:
            t = float(blk.get("temperature"))
        except (TypeError, ValueError):
            continue
        if math.isfinite(t) and t > 0 and t != 1.0 and hz in HORIZON_SLUGS:
            out[hz] = t
    return out


def main() -> int:
    from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
    from calibration.paths import DEFAULT_DB

    ap = argparse.ArgumentParser(description="Fit per-horizon fusion temperature calibration")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--out", type=Path, default=DEFAULT_ARTIFACT_PATH)
    ap.add_argument(
        "--fit-window-floor",
        type=float,
        default=FIT_WINDOW_FLOOR_UTC,
        help="UTC epoch: exclude decision rows logged before this (default: serve-stack repair floor)",
    )
    ap.add_argument("tickers", nargs="*", metavar="TICKER", help="Optional ticker filter")
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()

    if not args.db.is_file():
        print(f"DB not found: {args.db}", file=sys.stderr)
        return 1
    require_canonical_db_target(args, tool_name="calibration.fusion_temperature", write_capable=False)

    tickers = [ticker_storage_key(t) for t in args.tickers if t.strip()] or None  # RC-345/F25: canonical CLI ticker list
    artifact = fit_fusion_temperature_artifact(
        args.db, tickers=tickers, min_decision_ts_utc=float(args.fit_window_floor)
    )
    path = write_fusion_temperature_artifact(artifact, args.out)
    print(json.dumps({"artifact": str(path), "by_horizon": artifact["by_horizon"]}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
