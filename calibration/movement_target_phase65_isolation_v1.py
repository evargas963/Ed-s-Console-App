#!/usr/bin/env python3
"""
Phase 6.5 — Edge isolation for movement targets (binary move head + conditional dir head).

Parallel to calibration/phase65_edge_isolation_v1.py but uses outcome_move / outcome_dir + valid_dir
and pred_move_* / pred_dir_* columns. Writes data/phase65_movement_isolation_v1_report.json.

  python -m calibration.movement_target_phase65_isolation_v1 --db data/ed_console.db
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
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
    pred_dir_keys,
    pred_move_keys,
    rget_float,
)
from calibration.paths import DEFAULT_DB, ensure_artifacts_dir
from calibration.phase6_edge_discovery_governed_v1 import _session_bucket, load_rows

IS_FRAC = 0.70
MIN_N_GLOBAL = 500
MIN_N_SLICE = 200
MIN_N_INT = 100


def _split_is_oos(mem: list[Any], is_frac: float) -> tuple[list[Any], list[Any]]:
    if not mem:
        return [], []
    srt = sorted(mem, key=lambda r: float(r["ts_utc"]))
    k = int(len(srt) * is_frac)
    k = max(1, min(len(srt) - 1, k))
    return srt[:k], srt[k:]


def _median_split(mem: list[Any]) -> tuple[list[Any], list[Any]]:
    if not mem:
        return [], []
    srt = sorted(mem, key=lambda r: float(r["ts_utc"]))
    mid = len(srt) // 2
    return srt[:mid], srt[mid:]


def _eligible_move(mem: list[Any], hz: str) -> list[Any]:
    o_m = col_move(hz)
    pm_c, pn_c, pm_l, pn_l = pred_move_keys(hz)
    out: list[Any] = []
    for r in mem:
        if r[o_m] not in ("move", "no_move"):
            continue
        if rget_float(r, pm_c, pm_l) is None or rget_float(r, pn_c, pn_l) is None:
            continue
        out.append(r)
    return out


def _eligible_dir(mem: list[Any], hz: str) -> list[Any]:
    o_d, v_d = col_dir(hz), col_valid_dir(hz)
    pu_c, pd_c, pu_l, pd_l = pred_dir_keys(hz)
    out: list[Any] = []
    for r in mem:
        try:
            if int(r[v_d]) != 1:
                continue
        except (TypeError, ValueError, KeyError):
            continue
        if r[o_d] not in ("up", "down"):
            continue
        if rget_float(r, pu_c, pu_l) is None or rget_float(r, pd_c, pd_l) is None:
            continue
        out.append(r)
    return out


def _vectors_move(el: list[Any], hz: str) -> tuple[list[int], list[int]]:
    o_m = col_move(hz)
    pm_c, pn_c, pm_l, pn_l = pred_move_keys(hz)
    ys: list[int] = []
    pr: list[int] = []
    for r in el:
        pm = rget_float(r, pm_c, pm_l)
        pn = rget_float(r, pn_c, pn_l)
        assert pm is not None and pn is not None
        sm = pm + pn
        if sm > 0:
            pm = pm / sm
        y = 1 if r[o_m] == "move" else 0
        ys.append(y)
        pr.append(1 if pm >= 0.5 else 0)
    return ys, pr


def _vectors_dir(el: list[Any], hz: str) -> tuple[list[int], list[int]]:
    o_d = col_dir(hz)
    pu_c, pd_c, pu_l, pd_l = pred_dir_keys(hz)
    ys: list[int] = []
    pr: list[int] = []
    for r in el:
        pu = rget_float(r, pu_c, pu_l)
        pd_ = rget_float(r, pd_c, pd_l)
        assert pu is not None and pd_ is not None
        s = pu + pd_
        if s > 0:
            pu, pd_ = pu / s, pd_ / s
        y = 1 if r[o_d] == "up" else 0
        ys.append(y)
        pr.append(1 if pu >= pd_ else 0)
    return ys, pr


def _evaluate_slice(
    mem: list[Any],
    hz: str,
    family: str,
    slice_id: str,
    min_n: int,
) -> dict[str, Any]:
    el = _eligible_move(mem, hz) if family == "move" else _eligible_dir(mem, hz)
    n = len(el)
    out: dict[str, Any] = {"slice_id": slice_id, "horizon": hz, "family": family, "n_eligible": n, "verdict": "INSUFFICIENT"}
    if n < min_n:
        return out
    if family == "move":
        ys, pr = _vectors_move(el, hz)
        b = binary_baselines_move(ys)
        m = binary_classification_report(ys, pr)
        maj_acc = float(b["prior_majority_accuracy"])
    else:
        ys, pr = _vectors_dir(el, hz)
        b = binary_baselines_dir(ys)
        m = binary_classification_report(ys, pr)
        m["recall_up"] = m.pop("recall_positive")
        m["recall_down"] = m.pop("recall_negative")
        maj_acc = float(b["conditional_majority_accuracy"])

    acc_m = float(m["accuracy"])
    is_rows, oos_rows = _split_is_oos(el, IS_FRAC)
    ys_is, pr_is = (
        _vectors_move(is_rows, hz) if family == "move" else _vectors_dir(is_rows, hz)
    )
    ys_oos, pr_oos = (
        _vectors_move(oos_rows, hz) if family == "move" else _vectors_dir(oos_rows, hz)
    )
    oos_prior = Counter(ys_is).most_common(1)[0][0] if ys_is else 0
    oos_prior_acc = sum(1 for y in ys_oos if y == oos_prior) / len(ys_oos) if ys_oos else float("nan")
    oos_model_acc = sum(1 for a, b in zip(ys_oos, pr_oos) if a == b) / len(ys_oos) if ys_oos else float("nan")

    old, recent = _median_split(el)
    ys_o, pr_o = (
        _vectors_move(old, hz) if family == "move" else _vectors_dir(old, hz)
    )
    ys_r, pr_r = (
        _vectors_move(recent, hz) if family == "move" else _vectors_dir(recent, hz)
    )
    acc_o = sum(1 for a, b in zip(ys_o, pr_o) if a == b) / len(ys_o) if ys_o else float("nan")
    acc_r = sum(1 for a, b in zip(ys_r, pr_r) if a == b) / len(ys_r) if ys_r else float("nan")
    stab_fail = (acc_r < acc_o - 0.03) if (len(ys_o) >= 30 and len(ys_r) >= 30) else False

    if family == "move":
        beats = (
            acc_m > maj_acc
            and acc_m > float(b["always_move_accuracy"])
            and acc_m > float(b["always_no_move_accuracy"])
            and acc_m > float(b["random_accuracy_mean"])
            and (not math.isnan(oos_model_acc) and not math.isnan(oos_prior_acc) and oos_model_acc >= oos_prior_acc)
            and not stab_fail
        )
    else:
        beats = (
            acc_m > maj_acc
            and acc_m > float(b["always_up_accuracy"])
            and acc_m > float(b["always_down_accuracy"])
            and acc_m > float(b["random_accuracy_mean"])
            and (not math.isnan(oos_model_acc) and not math.isnan(oos_prior_acc) and oos_model_acc >= oos_prior_acc)
            and not stab_fail
        )

    if len(oos_rows) < 30 or math.isnan(oos_model_acc):
        verdict = "INCONCLUSIVE"
    elif beats:
        verdict = "ACCEPTED"
    else:
        verdict = "REJECTED"

    out.update(
        {
            "verdict": verdict,
            "metrics": m,
            "baselines": b,
            "oos": {
                "n_is": len(is_rows),
                "n_oos": len(oos_rows),
                "oos_model_accuracy": round(oos_model_acc, 6) if oos_model_acc == oos_model_acc else None,
                "oos_prior_from_is_mode_accuracy": round(oos_prior_acc, 6) if oos_prior_acc == oos_prior_acc else None,
            },
            "stability_median_halves": {
                "accuracy_older_half": round(acc_o, 6) if acc_o == acc_o else None,
                "accuracy_recent_half": round(acc_r, 6) if acc_r == acc_r else None,
                "stability_fail_recent_lt_older_minus_0p03": stab_fail,
            },
        }
    )
    return out


def run_phase65_movement(db_path: Path) -> dict[str, Any]:
    rows, meta = load_rows(db_path)
    t0 = time.time()
    out: dict[str, Any] = {
        "frozen_definitions": {
            "population": "same governed anchor set as phase6 load_rows",
            "move_head": "outcome_move in {move,no_move}, preds pred_move_prob / pred_no_move_prob",
            "dir_head": "valid_dir=1 and outcome_dir in {up,down}, preds pred_dir_up/down",
        },
        "meta": {**meta, "elapsed_load_s": round(time.time() - t0, 3)},
        "primary_slices": {"move": {}, "dir": {}},
        "summary_counts": {"move": Counter(), "dir": Counter()},
    }

    by_t: dict[str, list[Any]] = defaultdict(list)
    for r in rows:
        by_t[str(r["ticker"])].append(r)
    by_s: dict[str, list[Any]] = defaultdict(list)
    for r in rows:
        from calibration.phase6_edge_discovery_governed_v1 import _row_market_session

        by_s[_session_bucket(_row_market_session(r), r["session_bucket"])].append(r)
    by_rg: dict[str, list[Any]] = defaultdict(list)
    for r in rows:
        rp = (r["regime_primary"] or "unknown").strip() or "unknown"
        by_rg[rp].append(r)

    for hz in HORIZONS_MV:
        for fam in ("move", "dir"):
            res = _evaluate_slice(rows, hz, fam, f"global|horizon={hz}|family={fam}", MIN_N_GLOBAL)
            out["primary_slices"][fam].setdefault("by_horizon", {})[hz] = res
            out["summary_counts"][fam][res["verdict"]] += 1

        for tkr, mem in by_t.items():
            for fam in ("move", "dir"):
                res = _evaluate_slice(mem, hz, fam, f"ticker={tkr}|horizon={hz}|family={fam}", MIN_N_SLICE)
                out["primary_slices"][fam].setdefault("by_ticker", {}).setdefault(tkr, {})[hz] = res
                out["summary_counts"][fam][res["verdict"]] += 1

        for sname, mem in by_s.items():
            for fam in ("move", "dir"):
                res = _evaluate_slice(mem, hz, fam, f"session={sname}|horizon={hz}|family={fam}", MIN_N_SLICE)
                out["primary_slices"][fam].setdefault("by_session", {}).setdefault(sname, {})[hz] = res
                out["summary_counts"][fam][res["verdict"]] += 1

        for rg, mem in by_rg.items():
            for fam in ("move", "dir"):
                res = _evaluate_slice(mem, hz, fam, f"regime={rg}|horizon={hz}|family={fam}", MIN_N_SLICE)
                out["primary_slices"][fam].setdefault("by_regime", {}).setdefault(rg, {})[hz] = res
                out["summary_counts"][fam][res["verdict"]] += 1

    # Interaction: ticker × horizon (single cell per family)
    inter: dict[str, Any] = {"ticker_x_horizon": {"move": {}, "dir": {}}}
    for tkr, mem in by_t.items():
        for hz in HORIZONS_MV:
            for fam in ("move", "dir"):
                res = _evaluate_slice(mem, hz, fam, f"ticker={tkr}×horizon={hz}|family={fam}", MIN_N_INT)
                inter["ticker_x_horizon"][fam].setdefault(tkr, {})[hz] = res
                out["summary_counts"][fam][res["verdict"]] += 1

    out["interaction_slices"] = inter
    out["summary_counts"] = {k: dict(v) for k, v in out["summary_counts"].items()}

    accepted = []
    for fam in ("move", "dir"):
        for d in out["primary_slices"][fam].values():
            if not isinstance(d, dict):
                continue
            for _k, v in d.items():
                if isinstance(v, dict):
                    for _k2, rec in v.items():
                        if isinstance(rec, dict) and rec.get("verdict") == "ACCEPTED":
                            accepted.append(rec.get("slice_id"))
    out["inventories"] = {"accepted_slice_ids_sample": accepted[:120], "accepted_total": len(accepted)}
    out["phase65_movement_verdict"] = "PASS" if out["primary_slices"]["move"].get("by_horizon") else "FAIL"
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="movement_target_phase65_isolation_v1", write_capable=False)
    db_path = args.db.resolve()
    if not db_path.is_file():
        print(json.dumps({"error": f"missing db {db_path}"}))
        return 2
    rep = run_phase65_movement(db_path)
    ensure_artifacts_dir()
    outp = ROOT / "data" / "phase65_movement_isolation_v1_report.json"
    outp.write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"wrote": str(outp), "accepted_total": rep.get("inventories", {}).get("accepted_total")}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
