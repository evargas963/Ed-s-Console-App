#!/usr/bin/env python3

# DEPRECATED — 7-horizon era (pre Phase D3 schema drop).
# Targets retired outcome_3c/8c/13c columns; do not run against post-D3 databases.
# Relocated to tools/legacy/horizon_7/ for audit history only.
"""Universal ticker readiness enforcement and artifact emission."""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from db import configure_sqlite_connection
from features.inference_snapshot import build_inference_snapshot_v1_from_db_row
from ml_horizon import (
    ML_HORIZON_SLUGS,
    directional_label_column,
    move_label_column,
    normalize_ml_horizon_slug,
)
import ml_predict
from ml_predict import reset_caches
from ml_train import TARGET_MODE_DIR, TARGET_MODE_MOVE, load_data, train_ticker

TRAIN_MIN_ROWS = 80

GOV_WHERE = """
timeframe = '1m'
AND COALESCE(horizon_outcome_schema_version, 3) = 3
AND outcome_1c IS NOT NULL AND outcome_1c_pts IS NOT NULL
AND outcome_3c IS NOT NULL AND outcome_3c_pts IS NOT NULL
AND outcome_5c IS NOT NULL AND outcome_5c_pts IS NOT NULL
AND outcome_8c IS NOT NULL AND outcome_8c_pts IS NOT NULL
AND outcome_13c IS NOT NULL AND outcome_13c_pts IS NOT NULL
AND outcome_15c IS NOT NULL AND outcome_15c_pts IS NOT NULL
AND outcome_60c IS NOT NULL AND outcome_60c_pts IS NOT NULL
AND EXISTS (
  SELECT 1 FROM price_bars_1m p
  WHERE p.ticker = snapshots.ticker AND p.bar_end_ts_utc <= snapshots.ts_utc
)
""".strip()


def _app_tickers(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """
        SELECT ticker FROM logging_universe
        WHERE category IN ('core','pinned','user_persisted')
        ORDER BY CASE category
            WHEN 'core' THEN 0
            WHEN 'pinned' THEN 1
            WHEN 'user_persisted' THEN 2
            ELSE 3 END,
            ticker COLLATE NOCASE
        """
    ).fetchall()
    out = []
    for r in rows:
        t = str(r[0] or "").strip().upper()
        if t:
            out.append(t)
    return out


def _head_paths(ticker: str, hz: str, head: str) -> tuple[Path, Path]:
    d = ROOT / "models" / "active" / ticker
    p = d / f"xgb_{ticker}_{hz}_{head}.pkl"
    m = d / f"xgb_{ticker}_{hz}_{head}_meta.json"
    return p, m


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _train_native_if_feasible(db_path: str, ticker: str, hz: str, head: str) -> tuple[bool, str]:
    label_col = move_label_column(hz) if head == "move" else directional_label_column(hz)
    target_mode = TARGET_MODE_MOVE if head == "move" else TARGET_MODE_DIR
    try:
        df = load_data(db_path, ticker=ticker, ml_horizon_slug=hz, label_column=label_col)
    except Exception as e:
        return False, f"load_failed:{e}"
    if len(df) < TRAIN_MIN_ROWS:
        return False, f"insufficient_rows:{len(df)}<{TRAIN_MIN_ROWS}"
    if int(df[label_col].nunique()) < 2:
        return False, f"single_class:{label_col}"
    out_dir = ROOT / "models" / "active" / ticker
    out_dir.mkdir(parents=True, exist_ok=True)
    train_ticker(
        ticker=ticker,
        df=df,
        model_dir=out_dir,
        nan_threshold=0.35,
        skip_sanity=True,
        show_importance=False,
        compare=False,
        evaluate_only=False,
        ml_horizon_slug=hz,
        target_mode=target_mode,
    )
    return True, "trained_native"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "ed_console.db")
    ap.add_argument("--sample-per-ticker", type=int, default=1)
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="enforce_universal_ticker_readiness_v1", write_capable=True)

    db_path = str(args.db.resolve())
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    configure_sqlite_connection(conn)

    horizons = [normalize_ml_horizon_slug(h) for h in ML_HORIZON_SLUGS]
    tickers = _app_tickers(conn)

    phase65_cleanup = _load_json(ROOT / "data" / "phase65_movement_cleanup_v1_result.json")
    phase65_isolation = _load_json(ROOT / "data" / "phase65_movement_isolation_v1_report.json")
    validate_cov = _load_json(ROOT / "data" / "validate_movement_prediction_coverage_v1.json")

    policy_slice_ids = {str(r.get("slice_id")) for r in phase65_cleanup.get("policy_usable", [])}

    required_rows: list[dict] = []
    remediation_actions: list[dict] = []
    ticker_rows: list[dict] = []

    # Remediate feasible native gaps first.
    for t in tickers:
        for hz in horizons:
            for head in ("move", "dir"):
                p, m = _head_paths(t, hz, head)
                cloned = False
                if m.is_file():
                    md = _load_json(m)
                    cloned = bool(md.get("cloned_from_horizon"))
                needs_native = (not p.is_file()) or cloned
                if not needs_native:
                    continue
                ok, reason = _train_native_if_feasible(db_path, t, hz, head)
                remediation_actions.append(
                    {
                        "ticker": t,
                        "horizon": hz,
                        "head": head,
                        "action": "train_native_if_feasible",
                        "result": "TRAINED" if ok else "BLOCKED",
                        "reason": reason,
                    }
                )

    # Build inventory + readiness now.
    reset_caches()
    ml_predict._xgb_movehead_registry.clear()

    for t in tickers:
        total_rows = int(conn.execute("SELECT COUNT(*) FROM snapshots WHERE ticker = ?", (t,)).fetchone()[0])
        governed_rows = int(
            conn.execute(f"SELECT COUNT(*) FROM snapshots WHERE ticker = ? AND {GOV_WHERE}", (t,)).fetchone()[0]
        )
        by_hz_valid_dir: dict[str, int] = {}
        for hz in horizons:
            vd = int(
                conn.execute(
                    f"SELECT COUNT(*) FROM snapshots_1m_normalized "
                    f"WHERE ticker=? AND {directional_label_column(hz)} IS NOT NULL "
                    f"AND CAST(valid_dir_{hz} AS INTEGER)=1",
                    (t,),
                ).fetchone()[0]
            )
            by_hz_valid_dir[hz] = vd

        missing_native: list[str] = []
        cloned_heads: list[str] = []
        loadable_count = 0
        required_total = 0
        train_feasible_missing = 0
        train_blocked_missing = 0

        for hz in horizons:
            for head in ("move", "dir"):
                required_total += 1
                p, mp = _head_paths(t, hz, head)
                meta = _load_json(mp) if mp.is_file() else {}
                cloned = bool(meta.get("cloned_from_horizon"))
                native = p.is_file() and mp.is_file() and not cloned
                loadable = p.is_file() and mp.is_file()
                if loadable:
                    loadable_count += 1
                if cloned:
                    cloned_heads.append(f"{hz}:{head}")
                if not native:
                    missing_native.append(f"{hz}:{head}")
                    lbl = move_label_column(hz) if head == "move" else directional_label_column(hz)
                    try:
                        df = load_data(db_path, ticker=t, ml_horizon_slug=hz, label_column=lbl)
                        feasible = len(df) >= TRAIN_MIN_ROWS and int(df[lbl].nunique()) >= 2
                    except Exception:
                        feasible = False
                    if feasible:
                        train_feasible_missing += 1
                    else:
                        train_blocked_missing += 1
                required_rows.append(
                    {
                        "ticker": t,
                        "horizon": hz,
                        "head_type": head,
                        "move_head_required_y": True if head == "move" else False,
                        "dir_head_required_y": True if head == "dir" else False,
                        "native_model_present_y": native,
                        "cloned_model_present_y": cloned,
                        "metadata_present_y": mp.is_file(),
                        "loadable_y": loadable,
                        "model_path": str(p.resolve()),
                        "meta_path": str(mp.resolve()),
                    }
                )

        # Inference + persistence check
        infer_ok = 0
        infer_total = 0
        cov_per_h = {}
        inference_reasons: list[str] = []
        for hz in horizons:
            n_total = governed_rows
            n_move = int(
                conn.execute(
                    f"SELECT COUNT(*) FROM snapshots WHERE ticker=? AND {GOV_WHERE} AND fused_move_prob_{hz} IS NOT NULL",
                    (t,),
                ).fetchone()[0]
            )
            n_dir = int(
                conn.execute(
                    f"SELECT COUNT(*) FROM snapshots WHERE ticker=? AND {GOV_WHERE} AND fused_dir_up_prob_{hz} IS NOT NULL",
                    (t,),
                ).fetchone()[0]
            )
            cm = (n_move / n_total) if n_total else 0.0
            cd = (n_dir / n_total) if n_total else 0.0
            cov_per_h[hz] = {"coverage_move": round(cm, 6), "coverage_dir": round(cd, 6)}
            if n_total and (cm < 1.0 or cd < 1.0):
                inference_reasons.append(f"{hz}:coverage_move={cm:.3f},coverage_dir={cd:.3f}")

        # cold path one row/horizon for ticker
        row = conn.execute(f"SELECT * FROM snapshots WHERE ticker=? AND {GOV_WHERE} LIMIT 1", (t,)).fetchone()
        if row:
            d = dict(row)
            if d.get("spread") is not None and float(d["spread"]) < 0:
                d["spread"] = abs(float(d["spread"]))
            try:
                _ = build_inference_snapshot_v1_from_db_row(
                    ticker=t, expiry=d.get("expiry"), as_of_ts=float(d["ts_utc"]), db_row=d
                )
                for hz in horizons:
                    infer_total += 1
                    fpm = d.get(f"fused_move_prob_{hz}")
                    fpu = d.get(f"fused_dir_up_prob_{hz}")
                    ok = (
                        fpm is not None
                        and fpu is not None
                        and all(math.isfinite(float(x)) for x in (fpm, fpu))
                        and 0.0 <= float(fpm) <= 1.0
                        and 0.0 <= float(fpu) <= 1.0
                    )
                    if ok:
                        infer_ok += 1
                    else:
                        inference_reasons.append(f"{hz}:fusion_policy_missing_or_invalid")
            except Exception as e:
                inference_reasons.append(f"build_inference_failed:{e}")
        else:
            inference_reasons.append("no_governed_row_for_inference")

        # Status derivation
        data_reasons: list[str] = []
        if total_rows == 0:
            data_status = "INSUFFICIENT_DATA"
            data_reasons.append("no_snapshots_rows")
        elif governed_rows == 0:
            data_status = "INSUFFICIENT_DATA"
            data_reasons.append("no_governed_rows")
        else:
            data_status = "DATA_READY"

        if train_feasible_missing > 0:
            training_status = "TRAIN_READY"
            training_reasons = [f"feasible_missing_native_heads={train_feasible_missing}"]
        elif len(missing_native) == 0:
            training_status = "TRAINED_NATIVE"
            training_reasons = []
        elif loadable_count > 0:
            training_status = "TRAINED_PARTIAL"
            training_reasons = [f"blocked_missing_native_heads={train_blocked_missing}"]
        else:
            training_status = "TRAIN_BLOCKED"
            training_reasons = [f"blocked_missing_native_heads={train_blocked_missing}"]

        if loadable_count == 0:
            artifact_status = "NO_COVERAGE"
        elif cloned_heads:
            artifact_status = "CLONED_COVERAGE_PRESENT"
        elif len(missing_native) > 0:
            artifact_status = "PARTIAL_COVERAGE"
        else:
            artifact_status = "FULL_NATIVE_COVERAGE"

        if infer_total == 0 or infer_ok == 0:
            inference_status = "INFERENCE_BLOCKED"
        elif infer_ok < infer_total or inference_reasons:
            inference_status = "INFERENCE_PARTIAL"
        else:
            inference_status = "INFERENCE_READY"

        if governed_rows == 0:
            evaluation_status = "EVAL_BLOCKED"
            eval_reasons = ["not_in_governed_population"]
        elif inference_status != "INFERENCE_READY":
            evaluation_status = "EVAL_PARTIAL"
            eval_reasons = ["inference_not_fully_ready"]
        else:
            evaluation_status = "EVAL_READY"
            eval_reasons = []

        if artifact_status == "FULL_NATIVE_COVERAGE" and inference_status == "INFERENCE_READY" and governed_rows > 0:
            calibration_status = "CALIBRATION_ELIGIBLE"
            cal_reasons = []
        else:
            calibration_status = "CALIBRATION_BLOCKED"
            cal_reasons = []
            if artifact_status != "FULL_NATIVE_COVERAGE":
                cal_reasons.append(f"artifact_status={artifact_status}")
            if inference_status != "INFERENCE_READY":
                cal_reasons.append(f"inference_status={inference_status}")
            if governed_rows == 0:
                cal_reasons.append("no_governed_rows")

        if calibration_status == "CALIBRATION_ELIGIBLE":
            policy_status = "POLICY_ELIGIBLE"
            policy_reasons = []
        else:
            policy_status = "POLICY_BLOCKED"
            policy_reasons = [f"calibration_status={calibration_status}"]
            if cloned_heads:
                policy_reasons.append("cloned_coverage_present")

        verdict = (
            "READY_GLOBAL_STANDARD"
            if policy_status == "POLICY_ELIGIBLE"
            else ("READY_WITH_LIMITATIONS" if inference_status != "INFERENCE_BLOCKED" else "NOT_READY")
        )

        ticker_rows.append(
            {
                "ticker": t,
                "data_status": data_status,
                "training_status": training_status,
                "artifact_status": artifact_status,
                "inference_status": inference_status,
                "evaluation_status": evaluation_status,
                "calibration_status": calibration_status,
                "policy_status": policy_status,
                "final_readiness_verdict": verdict,
                "reasons": {
                    "data": data_reasons,
                    "training": training_reasons,
                    "artifact": ([] if artifact_status == "FULL_NATIVE_COVERAGE" else [f"missing_native={missing_native}"])
                    + ([f"cloned_heads={cloned_heads}"] if cloned_heads else []),
                    "inference": inference_reasons,
                    "evaluation": eval_reasons,
                    "calibration": cal_reasons,
                    "policy": policy_reasons,
                },
                "metrics": {
                    "snapshot_rows": total_rows,
                    "governed_rows": governed_rows,
                    "valid_dir_rows_by_horizon": by_hz_valid_dir,
                    "required_heads": required_total,
                    "loadable_heads": loadable_count,
                    "missing_native_heads": missing_native,
                    "cloned_heads": cloned_heads,
                    "inference_smoke_ok": infer_ok,
                    "inference_smoke_total": infer_total,
                    "coverage_by_horizon": cov_per_h,
                },
                "evaluation_representation": {
                    "evaluation_universe": "represented" if governed_rows > 0 else "excluded",
                    "calibration_universe": "represented" if governed_rows > 0 else "excluded",
                    "policy_universe": "represented_via_global_session_regime_slices",
                    "policy_usable_slice_ids_global": sorted(policy_slice_ids),
                },
            }
        )

    onboarding_rules = {
        "version": "v1",
        "deterministic_inputs": [
            "ticker symbol",
            "snapshots_1m_normalized row counts",
            "governed snapshot counts",
            "valid_dir_* row counts",
            "required artifact inventory",
        ],
        "thresholds": {
            "train_min_rows_per_head": TRAIN_MIN_ROWS,
            "binary_class_diversity_required": 2,
            "canonical_timeframe": "1m",
        },
        "decision_flow": [
            "If snapshot rows == 0 -> DATA_STATUS=INSUFFICIENT_DATA",
            "If governed rows == 0 -> DATA_STATUS=INSUFFICIENT_DATA",
            "For each horizon and head: if rows>=80 and classes>=2 then TRAINABLE else TRAIN_BLOCKED with reason",
            "Train only missing native heads when TRAINABLE",
            "Never auto-clone on onboarding; cloning is disallowed as default",
            "If all required heads native+loadable -> FULL_NATIVE_COVERAGE",
            "Else classify PARTIAL/CLONED/NO_COVERAGE explicitly",
            "Inference/persistence must pass before CALIBRATION_ELIGIBLE",
            "POLICY_ELIGIBLE only when FULL_NATIVE_COVERAGE + INFERENCE_READY + DATA_READY",
        ],
        "universal_onboarding_verdict": "UNIVERSAL_ONBOARDING_READY",
        "blocked_reason_codes": [
            "no_snapshots_rows",
            "no_governed_rows",
            "insufficient_rows",
            "single_class",
            "missing_native_head",
            "cloned_coverage_present",
            "inference_invalid_or_null",
        ],
    }

    now = time.time()
    out_inventory = {
        "created_ts_utc": now,
        "canonical_timeframe": "1m",
        "required_horizons": horizons,
        "rows": required_rows,
    }
    out_readiness = {
        "created_ts_utc": now,
        "db_path": str(args.db.resolve()),
        "ticker_count": len(tickers),
        "tickers": ticker_rows,
        "remediation_actions": remediation_actions,
        "global_coverage_report": validate_cov,
    }
    out_lookup = {
        "created_ts_utc": now,
        "db_path": str(args.db.resolve()),
        "lookup": {r["ticker"]: r for r in ticker_rows},
        "required_inventory_path": str((ROOT / "data" / "required_model_inventory_v1.json").resolve()),
        "onboarding_rules_path": str((ROOT / "data" / "new_ticker_onboarding_rules_v1.json").resolve()),
    }

    p_inventory = ROOT / "data" / "required_model_inventory_v1.json"
    p_readiness = ROOT / "data" / "ticker_readiness_matrix_v1.json"
    p_onboarding = ROOT / "data" / "new_ticker_onboarding_rules_v1.json"
    p_lookup = ROOT / "data" / "ticker_readiness_lookup_v1.json"

    p_inventory.write_text(json.dumps(out_inventory, indent=2), encoding="utf-8")
    p_readiness.write_text(json.dumps(out_readiness, indent=2), encoding="utf-8")
    p_onboarding.write_text(json.dumps(onboarding_rules, indent=2), encoding="utf-8")
    p_lookup.write_text(json.dumps(out_lookup, indent=2), encoding="utf-8")

    print(
        json.dumps(
            {
                "wrote": [str(p_inventory), str(p_readiness), str(p_onboarding), str(p_lookup)],
                "tickers": len(tickers),
                "remediation_actions": len(remediation_actions),
            },
            indent=2,
        )
    )
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
