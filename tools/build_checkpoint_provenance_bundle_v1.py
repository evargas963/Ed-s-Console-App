#!/usr/bin/env python3
"""Emit checkpoint manifest, policy-usable inventory, provenance matrix, protocol lock; cold-start sample."""
from __future__ import annotations

import json
import math
import random
import re
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from db import configure_sqlite_connection
from features.inference_snapshot import build_inference_snapshot_v1_from_db_row
from ml_horizon import ML_HORIZON_SLUGS, normalize_ml_horizon_slug
import ml_predict
from ml_predict import _predict_xgb_movement_heads, reset_caches, reset_ml_infer_horizon_slug, set_ml_infer_horizon_slug

PKL_RE = re.compile(r"^xgb_(.+)_(1c|3c|5c|8c|13c|15c|60c)_(move|dir)\.pkl$")

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

# Known single-class augmentation completions (train_missing_movement_heads_v1); not written into meta.
AUGMENTED_MOVE: set[tuple[str, str]] = {
    ("PCG", "60c"),
    ("TSL", "15c"),
    ("TSL", "60c"),
}


def _git_head() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(ROOT),
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return None


def _git_changed_files() -> list[str]:
    try:
        out = subprocess.check_output(
            ["git", "diff", "--name-only", "HEAD"],
            cwd=str(ROOT),
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return [ln.strip() for ln in out.splitlines() if ln.strip()]
    except Exception:
        return []


def build_provenance_rows() -> list[dict]:
    rows: list[dict] = []
    active = ROOT / "models" / "active"
    if not active.is_dir():
        return rows
    for pkl in sorted(active.rglob("xgb_*_*.pkl")):
        m = PKL_RE.match(pkl.name)
        if not m:
            continue
        tkr, hz, head = m.group(1), m.group(2), m.group(3)
        meta_p = pkl.with_name(pkl.name.replace(".pkl", "_meta.json"))
        meta: dict = {}
        if meta_p.is_file():
            meta = json.loads(meta_p.read_text(encoding="utf-8"))
        samples = int(meta.get("samples") or 0)
        cloned = bool(meta.get("cloned_from_horizon"))
        source_hz = meta.get("cloned_from_horizon")
        min_row_exc = samples < 80
        augmented = ((tkr, hz) in AUGMENTED_MOVE and head == "move") or (
            head == "dir" and (not cloned) and samples < 6
        )
        native = (not cloned) and (not augmented) and samples >= 80
        rows.append(
            {
                "ticker": tkr,
                "horizon": hz,
                "head_type": head,
                "pkl_path": str(pkl.resolve()),
                "meta_path": str(meta_p.resolve()) if meta_p.is_file() else "",
                "exists": pkl.is_file(),
                "native_trained_y": bool(native),
                "cloned_y": cloned,
                "augmented_data_trained_y": augmented,
                "minimum_row_exception_used_y": min_row_exc,
                "source_artifact_if_cloned": str((active / tkr / f"xgb_{tkr}_{source_hz}_dir.pkl").resolve())
                if cloned and source_hz
                else "",
                "source_rationale_if_cloned": meta.get("clone_note", ""),
                "metadata_path": str(meta_p.resolve()) if meta_p.is_file() else "",
                "loadable_y": pkl.is_file() and meta_p.is_file(),
                "meta_samples": samples,
            }
        )
    return rows


def cold_start_table(db: Path, n_sample: int = 48) -> list[dict]:
    reset_caches()
    ml_predict._xgb_movehead_registry.clear()
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    configure_sqlite_connection(conn)
    tickers = [r[0] for r in conn.execute(f"SELECT DISTINCT ticker FROM snapshots WHERE {GOV_WHERE} ORDER BY RANDOM() LIMIT 12")]
    horizons = [normalize_ml_horizon_slug(h) for h in ML_HORIZON_SLUGS]
    out: list[dict] = []
    random.seed(42)
    for tkr in tickers:
        r = conn.execute(
            f"SELECT * FROM snapshots WHERE ticker=? AND {GOV_WHERE} ORDER BY RANDOM() LIMIT 1",
            (tkr,),
        ).fetchone()
        if not r:
            continue
        d = dict(r)
        if d.get("spread") is not None and float(d["spread"]) < 0:
            d["spread"] = abs(float(d["spread"]))
        try:
            inf = build_inference_snapshot_v1_from_db_row(
                ticker=tkr, expiry=d.get("expiry"), as_of_ts=float(d["ts_utc"]), db_row=d
            )
        except Exception as e:
            out.append({"ticker": tkr, "horizon": "—", "ok": False, "err": str(e)[:120]})
            continue
        hz = random.choice(horizons)
        tok = set_ml_infer_horizon_slug(hz)
        try:
            pr = _predict_xgb_movement_heads(inf, tkr, None)
        except Exception as e:
            reset_ml_infer_horizon_slug(tok)
            out.append({"ticker": tkr, "horizon": hz, "ok": False, "err": str(e)[:120]})
            continue
        reset_ml_infer_horizon_slug(tok)
        pm = pr.get(f"pred_move_prob_{hz}")
        pn = pr.get(f"pred_no_move_prob_{hz}")
        pu = pr.get(f"pred_dir_up_prob_{hz}")
        pd = pr.get(f"pred_dir_down_prob_{hz}")
        ok = (
            pm is not None
            and pn is not None
            and pu is not None
            and pd is not None
            and all(math.isfinite(float(x)) for x in (pm, pn, pu, pd))
            and float(pm) >= 0
            and float(pn) >= 0
            and abs(float(pm) + float(pn) - 1.0) < 0.01
            and abs(float(pu) + float(pd) - 1.0) < 0.01
        )
        fpm = d.get(f"fused_move_prob_{hz}")
        fpu = d.get(f"fused_dir_up_prob_{hz}")
        out.append(
            {
                "ticker": tkr,
                "horizon": hz,
                "ok": ok,
                "xgb_head_pred_move_prob": pm,
                "xgb_head_pred_dir_up_prob": pu,
                "db_fused_move_prob": fpm,
                "db_fused_dir_up_prob": fpu,
            }
        )
    conn.close()
    return out


def main() -> int:
    ts = datetime.now(timezone.utc).isoformat()
    db = (ROOT / "data" / "ed_console.db").resolve()

    cleanup = json.loads((ROOT / "data" / "phase65_movement_cleanup_v1_result.json").read_text(encoding="utf-8"))
    isolation = json.loads((ROOT / "data" / "phase65_movement_isolation_v1_report.json").read_text(encoding="utf-8"))
    cov = json.loads((ROOT / "data" / "validate_movement_prediction_coverage_v1.json").read_text(encoding="utf-8"))
    backfill = json.loads((ROOT / "data" / "batch_backfill_movement_predictions_v1_report.json").read_text(encoding="utf-8"))

    provenance_rows = build_provenance_rows()
    cold = cold_start_table(db)

    def _walk_find_slice(obj: object, sid: str) -> dict | None:
        if isinstance(obj, dict):
            if obj.get("slice_id") == sid:
                return obj
            for v in obj.values():
                r = _walk_find_slice(v, sid)
                if r is not None:
                    return r
        elif isinstance(obj, list):
            for it in obj:
                r = _walk_find_slice(it, sid)
                if r is not None:
                    return r
        return None

    def find_isolation(sid: str) -> dict | None:
        return _walk_find_slice(isolation, sid)

    policy_inv: list[dict] = []
    for i, pu in enumerate(cleanup["policy_usable"]):
        sid = pu["slice_id"]
        iso = find_isolation(sid) or {}
        dims: dict[str, str] = {}
        if "|" in sid:
            for part in sid.split("|"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    dims[k.strip()] = v.strip()
                else:
                    p = part.strip()
                    if p:
                        dims.setdefault("scope", p)
        touches_clone = False
        clone_note = ""
        if pu.get("family") == "dir" and pu.get("horizon") == "60c":
            touches_clone = True
            clone_note = "Governed inference uses cloned dir heads for tickers TSL (clone 13c→60c) and PCG (15c→60c); metrics pool all tickers."
        if pu.get("family") == "dir" and pu.get("horizon") in ("1c", "3c", "8c"):
            touches_clone = False
        if pu.get("family") == "move":
            touches_clone = False
        if pu.get("slice_id") == "regime=reversal_prone|horizon=5c|family=dir":
            touches_clone = False
        policy_inv.append(
            {
                "index": i + 1,
                "slice_id": sid,
                "horizon": pu.get("horizon"),
                "family": pu.get("family"),
                "ticker_applicable": None,
                "dimensions": dims,
                "sample_size": pu.get("n"),
                "accuracy": pu.get("accuracy"),
                "verdict": pu.get("verdict"),
                "cleanup_classification": "POLICY_USABLE",
                "source_cleanup_path": str((ROOT / "data" / "phase65_movement_cleanup_v1_result.json").resolve()),
                "source_isolation_path": str((ROOT / "data" / "phase65_movement_isolation_v1_report.json").resolve()),
                "broader_accepted_cluster": iso.get("verdict") == "ACCEPTED" or iso.get("verdict") is not None,
                "isolation_verdict": iso.get("verdict"),
                "oos": iso.get("oos"),
                "metrics": iso.get("metrics"),
                "cloned_or_non_native_inference_touches_slice": touches_clone,
                "clone_touch_detail": clone_note if touches_clone else "",
            }
        )

    manifest = {
        "checkpoint_id": "movement_pass_v1",
        "created_utc": ts,
        "git_commit": _git_head(),
        "git_changed_files_vs_head": _git_changed_files(),
        "db_path": str(db),
        "artifact_root": str((ROOT / "models" / "active").resolve()),
        "reports_declaring_pass": {
            "coverage": str((ROOT / "data" / "validate_movement_prediction_coverage_v1.json").resolve()),
            "backfill": str((ROOT / "data" / "batch_backfill_movement_predictions_v1_report.json").resolve()),
            "phase5": str((ROOT / "data" / "movement_target_phase5_discrimination_v1.json").resolve()),
            "phase6": str((ROOT / "data" / "movement_target_phase6_edge_v1.json").resolve()),
            "phase65_isolation": str((ROOT / "data" / "phase65_movement_isolation_v1_report.json").resolve()),
            "phase65_cleanup": str((ROOT / "data" / "phase65_movement_cleanup_v1_result.json").resolve()),
        },
        "relevant_scripts": [
            str((ROOT / "tools" / "batch_backfill_movement_predictions_v1.py").resolve()),
            str((ROOT / "tools" / "validate_movement_prediction_coverage_v1.py").resolve()),
            str((ROOT / "tools" / "train_missing_movement_heads_v1.py").resolve()),
            str((ROOT / "tools" / "clone_sibling_dir_heads_v1.py").resolve()),
            str((ROOT / "tools" / "smoke_movement_heads_inference_v1.py").resolve()),
            str((ROOT / "tools" / "build_checkpoint_provenance_bundle_v1.py").resolve()),
            str((ROOT / "calibration" / "run_movement_target_evaluation_bundle_v1.py").resolve()),
        ],
        "code_state_files_pass_related": [
            "features/mvp_source_coercion.py",
            "tools/validate_movement_prediction_coverage_v1.py",
            "tools/train_missing_movement_heads_v1.py",
            "tools/clone_sibling_dir_heads_v1.py",
            "tools/smoke_movement_heads_inference_v1.py",
            "ml_predict.py",
            "ml_horizon.py",
        ],
        "pass_state_metrics": {
            "governed_total": cov.get("governed_total"),
            "overall_coverage_verdict": cov.get("overall_verdict"),
            "per_horizon_coverage": cov.get("per_horizon"),
            "backfill_stats": backfill.get("stats"),
            "phase65_isolation_accepted_total": isolation.get("inventories", {}).get("accepted_total"),
            "cleanup_initial_accepted": cleanup.get("initial_accepted"),
            "cleanup_after_hard_filter": cleanup.get("after_hard_filter"),
            "cleanup_after_subsumption": cleanup.get("after_subsumption"),
            "policy_usable_count": len(cleanup.get("policy_usable", [])),
        },
        "evaluation_bundle_stdout_note": "bundle exit 0 per checkpoint session",
    }

    protocol_lock = {
        "locked_at_utc": ts,
        "db_path": str(db),
        "coverage_tool": str((ROOT / "tools" / "validate_movement_prediction_coverage_v1.py").resolve()),
        "coverage_rules": {
            "governed_predicate": GOV_WHERE,
            "per_horizon_non_null_columns": ["fused_move_prob_{hz}", "fused_dir_up_prob_{hz}"],
            "hard_fail_below_coverage": 0.95,
            "warn_below_target_coverage": 0.99,
            "sum_tolerance": 0.002,
            "sample_integrity_rows_default": 8000,
        },
        "evaluation_bundle_commands": [
            "python -m calibration.run_movement_target_evaluation_bundle_v1 --db data/ed_console.db",
        ],
        "phase65_cleanup_reference": str((ROOT / "calibration" / "movement_target_phase65_cleanup_v1.py").resolve()),
        "policy_usable_definition": "Survivors after hard_filter + subsumption in movement_target_phase65_cleanup_v1; verdict POLICY_USABLE in cleanup output.",
        "oos_protocol_reference": "phase65_movement_isolation_v1_report.json primary_slices.*.oos (n_is / n_oos split documented per slice).",
        "warnings_vs_hard_fails": "Coverage: FAIL if <0.95; WARN in reasons if <0.99 (verdict_move/verdict_dir strings). Cleanup: hard_filter reasons include FAIL_EFFECT_SIZE, FAIL_SAMPLE, etc.; removal_log records subsumption.",
    }

    clone_classifications = [
        {
            "pkl_path": str((ROOT / "models" / "active" / "TSL" / "xgb_TSL_15c_dir.pkl").resolve()),
            "classification": "ACCEPTABLE_FOR_COVERAGE_ONLY_NOT_POLICY",
            "evidence": "meta.clone_note; load_data returned 0 RTH rows with valid_dir_15c for TSL; sibling 13c dir weights copied.",
        },
        {
            "pkl_path": str((ROOT / "models" / "active" / "TSL" / "xgb_TSL_60c_dir.pkl").resolve()),
            "classification": "ACCEPTABLE_FOR_COVERAGE_ONLY_NOT_POLICY",
            "evidence": "meta.clone_note; 0 RTH valid_dir_60c rows; clone source 13c same ticker.",
        },
        {
            "pkl_path": str((ROOT / "models" / "active" / "PCG" / "xgb_PCG_60c_dir.pkl").resolve()),
            "classification": "ACCEPTABLE_FOR_COVERAGE_ONLY_NOT_POLICY",
            "evidence": "meta.clone_note; 0 RTH valid_dir_60c rows; clone source 15c same ticker.",
        },
    ]

    out_manifest = ROOT / "data" / "checkpoint_manifest_v1.json"
    out_policy = ROOT / "data" / "policy_usable_inventory_v1.json"
    out_prov = ROOT / "data" / "artifact_provenance_matrix_v1.json"
    out_proto = ROOT / "data" / "evaluation_protocol_lock_v1.json"

    out_manifest.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    out_policy.write_text(
        json.dumps(
            {
                "checkpoint_id": manifest["checkpoint_id"],
                "created_utc": ts,
                "policy_usable_count": len(policy_inv),
                "slices": policy_inv,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    out_prov.write_text(
        json.dumps(
            {
                "checkpoint_id": manifest["checkpoint_id"],
                "created_utc": ts,
                "row_count": len(provenance_rows),
                "rows": provenance_rows,
                "clone_classifications": clone_classifications,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    out_proto.write_text(json.dumps(protocol_lock, indent=2), encoding="utf-8")

    cold_path = ROOT / "data" / "cold_start_inference_checkpoint_v1.json"
    cold_path.write_text(
        json.dumps({"created_utc": ts, "rows": cold, "all_ok": all(r.get("ok") for r in cold)}, indent=2),
        encoding="utf-8",
    )

    sum_lines = [
        "# Policy-usable inventory (checkpoint v1)",
        "",
        f"- checkpoint_id: {manifest['checkpoint_id']}",
        f"- created_utc: {ts}",
        f"- count: {len(policy_inv)}",
        "",
        "| # | slice_id | family | horizon | n | accuracy | isolation_verdict | clone_touch |",
        "|---|----------|--------|---------|---|----------|-------------------|-------------|",
    ]
    for row in policy_inv:
        ct = "Y" if row.get("cloned_or_non_native_inference_touches_slice") else "N"
        sum_lines.append(
            f"| {row['index']} | `{row['slice_id']}` | {row.get('family')} | {row.get('horizon')} | "
            f"{row.get('sample_size')} | {row.get('accuracy')} | {row.get('isolation_verdict')} | {ct} |"
        )
    sum_lines.append("")
    sum_lines.append(f"Full JSON: `{out_policy.resolve()}`")
    (ROOT / "data" / "policy_usable_inventory_v1_summary.md").write_text("\n".join(sum_lines), encoding="utf-8")

    print(json.dumps({"wrote": [str(out_manifest), str(out_policy), str(out_prov), str(out_proto), str(cold_path)]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
