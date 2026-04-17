#!/usr/bin/env python3
"""
Phase 5 — Discrimination audit for movement-target v1 (binary move + conditional dir).

Outputs JSON with baselines, recalls, effect size vs majority, decile monotonicity,
confidence-bucket analysis, and explicit gates.

  python -m calibration.movement_target_phase5_discrimination_v1 --db data/ed_console.db
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from calibration.movement_target_eval_common_v1 import (
    HORIZONS_MV,
    binary_baselines_dir,
    binary_baselines_move,
    binary_classification_report,
    col_dir,
    col_move,
    col_valid_dir,
    decile_accuracy_monotonicity,
    logloss_bin,
    pred_dir_keys,
    pred_move_keys,
    rget_float,
)
from calibration.paths import DEFAULT_DB, ensure_artifacts_dir
from calibration.phase6_edge_discovery_governed_v1 import load_rows


def _confidence_bucket(r: Any) -> str:
    c = (r["pred_confidence"] or "").strip().lower()
    if c in ("low", "medium", "high"):
        return c
    return "unknown"


def _gates_move(acc: float, maj: float) -> dict[str, Any]:
    delta = acc - maj
    if delta < 0.01:
        effect = "FAIL"
    elif delta < 0.02:
        effect = "WEAK"
    else:
        effect = "ACCEPTABLE"
    return {"delta_vs_majority": round(delta, 6), "effect_size_verdict": effect}


def _gates_dir(rec_up: float, rec_dn: float, acc: float, maj: float) -> dict[str, Any]:
    delta = acc - maj
    if delta < 0.01:
        effect = "FAIL"
    elif delta < 0.02:
        effect = "WEAK"
    else:
        effect = "ACCEPTABLE"
    low_recall = (rec_up < 0.35 or rec_dn < 0.35) if (rec_up == rec_up and rec_dn == rec_dn) else True
    return {
        "delta_vs_conditional_majority": round(delta, 6),
        "effect_size_verdict": effect,
        "recall_gate_fail_under_0p35": low_recall,
    }


def run(db_path: Path) -> dict[str, Any]:
    rows, meta = load_rows(db_path)
    out: dict[str, Any] = {
        "meta": meta,
        "inference_contract": (
            "Option 1: pred_dir_* probabilities are emitted for all rows when movement XGB heads "
            "are present; evaluation of outcome_dir uses rows with valid_dir=1 only."
        ),
        "horizons": {},
        "original_target_snippet": "See tools/_phase5_discrimination_audit_v1.py for 3-class outcome_* metrics (unchanged).",
    }

    for hz in HORIZONS_MV:
        o_m, o_d, v_d = col_move(hz), col_dir(hz), col_valid_dir(hz)
        pm_c, pn_c, pm_l, pn_l = pred_move_keys(hz)
        pu_c, pd_c, pu_l, pd_l = pred_dir_keys(hz)

        # --- Labels only (no predictions required): coverage & balance vs governed ---
        n_gov = len(rows)
        move_labeled = [r for r in rows if r[o_m] in ("move", "no_move")]
        mc = Counter(r[o_m] for r in move_labeled)
        vd1: list[Any] = []
        for r in rows:
            try:
                vd = int(r[v_d])
            except (TypeError, ValueError, KeyError):
                continue
            if vd != 1:
                continue
            od = r[o_d]
            if od in ("up", "down"):
                vd1.append(r)
        dc = Counter(r[o_d] for r in vd1)
        label_stats = {
            "governed_n": n_gov,
            "outcome_move_labeled_n": len(move_labeled),
            "outcome_move_coverage_vs_governed": round(len(move_labeled) / n_gov, 6) if n_gov else 0.0,
            "outcome_move_counts": dict(mc),
            "valid_dir_conditional_n": len(vd1),
            "valid_dir_up_down_balance": dict(dc),
        }

        # --- Move head (full labeled population) ---
        ys_m: list[int] = []
        pr_m: list[int] = []
        scores_m: list[float] = []
        corr_m: list[int] = []
        ll_m: list[float] = []
        for r in rows:
            om = r[o_m]
            if om not in ("move", "no_move"):
                continue
            p_move = rget_float(r, pm_c, pm_l)
            p_no = rget_float(r, pn_c, pn_l)
            if p_move is None or p_no is None:
                continue
            sm = p_move + p_no
            if sm > 0:
                p_move = p_move / sm
            y = 1 if om == "move" else 0
            pred = 1 if p_move >= 0.5 else 0
            ys_m.append(y)
            pr_m.append(pred)
            scores_m.append(p_move)
            corr_m.append(1 if pred == y else 0)
            ll_m.append(logloss_bin(y, p_move))

        move_block: dict[str, Any] = {}
        if ys_m:
            br = binary_baselines_move(ys_m)
            rep = binary_classification_report(ys_m, pr_m)
            rep["mean_logloss"] = round(sum(ll_m) / len(ll_m), 6)
            move_block = {
                "n": len(ys_m),
                "metrics": rep,
                "baselines": br,
                "gates": _gates_move(float(rep["accuracy"]), float(br["prior_majority_accuracy"])),
                "decile_ranking": decile_accuracy_monotonicity(scores_m, corr_m),
            }
        else:
            move_block = {"n": 0, "note": "no_rows_with_move_labels_and_predictions"}

        # --- Dir head (valid_dir=1 only) ---
        ys_u: list[int] = []
        pr_u: list[int] = []
        scores_u: list[float] = []
        corr_u: list[int] = []
        ll_u: list[float] = []
        for r in rows:
            try:
                vd = int(r[v_d])
            except (TypeError, ValueError, KeyError):
                continue
            if vd != 1:
                continue
            od = r[o_d]
            if od not in ("up", "down"):
                continue
            pu = rget_float(r, pu_c, pu_l)
            pd_ = rget_float(r, pd_c, pd_l)
            if pu is None or pd_ is None:
                continue
            s = pu + pd_
            if s > 0:
                pu, pd_ = pu / s, pd_ / s
            y = 1 if od == "up" else 0
            pred = 1 if pu >= pd_ else 0
            ys_u.append(y)
            pr_u.append(pred)
            scores_u.append(max(pu, pd_))
            corr_u.append(1 if pred == y else 0)
            ll_u.append(logloss_bin(y, pu))

        dir_block: dict[str, Any] = {}
        if ys_u:
            bd = binary_baselines_dir(ys_u)
            repd = binary_classification_report(ys_u, pr_u)
            repd["mean_logloss"] = round(sum(ll_u) / len(ll_u), 6)
            repd["recall_up"] = repd.pop("recall_positive")
            repd["recall_down"] = repd.pop("recall_negative")
            dir_block = {
                "n": len(ys_u),
                "metrics": repd,
                "baselines": bd,
                "gates": _gates_dir(
                    float(repd["recall_up"]),
                    float(repd["recall_down"]),
                    float(repd["accuracy"]),
                    float(bd["conditional_majority_accuracy"]),
                ),
                "decile_ranking": decile_accuracy_monotonicity(scores_u, corr_u),
            }
        else:
            dir_block = {"n": 0, "note": "no_valid_dir_rows_with_predictions"}

        # --- Confidence buckets (move accuracy by pred_confidence) ---
        by_c: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for r in rows:
            om = r[o_m]
            if om not in ("move", "no_move"):
                continue
            p_move = rget_float(r, pm_c, pm_l)
            p_no = rget_float(r, pn_c, pn_l)
            if p_move is None or p_no is None:
                continue
            sm = p_move + p_no
            if sm > 0:
                p_move = p_move / sm
            y = 1 if om == "move" else 0
            pred = 1 if p_move >= 0.5 else 0
            by_c[_confidence_bucket(r)].append((y, 1 if pred == y else 0))
        conf_acc: dict[str, Any] = {}
        for cname, pairs in by_c.items():
            if len(pairs) < 30:
                conf_acc[cname] = {"n": len(pairs), "accuracy": None}
            else:
                conf_acc[cname] = {
                    "n": len(pairs),
                    "accuracy": round(sum(p[1] for p in pairs) / len(pairs), 6),
                }
        mono = None
        for order in (["high", "medium", "low"],):
            accs = [conf_acc.get(c, {}).get("accuracy") for c in order]
            if all(a is not None for a in accs):
                mono = accs[0] >= accs[1] >= accs[2]
                break

        out["horizons"][hz] = {
            "label_statistics": label_stats,
            "move_head": move_block,
            "dir_head": dir_block,
            "confidence_bucket_accuracy_move": conf_acc,
            "confidence_monotonicity_high_ge_med_ge_low": mono,
        }

    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="movement_target_phase5_discrimination_v1", write_capable=False)
    db_path = args.db.resolve()
    if not db_path.is_file():
        print(json.dumps({"error": f"missing db {db_path}"}))
        return 2
    rep = run(db_path)
    ensure_artifacts_dir()
    outp = ROOT / "data" / "movement_target_phase5_discrimination_v1.json"
    outp.write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"wrote": str(outp)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
