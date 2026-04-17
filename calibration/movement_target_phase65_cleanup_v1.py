#!/usr/bin/env python3
"""
Phase 6.5 cleanup for movement-target isolation report (binary heads).

Reads data/phase65_movement_isolation_v1_report.json — no 3-class flat-dominance rule.

  python -m calibration.movement_target_phase65_cleanup_v1
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "data" / "phase65_movement_isolation_v1_report.json"
OUT = ROOT / "data" / "phase65_movement_cleanup_v1_result.json"

MIN_N_PRIMARY = 200
MIN_N_INTERACTION = 100
MIN_OOS_N = 50
MIN_EFFECT_VS_PRIOR = 0.01
MATERIAL_GAIN_VS_PARENT = 0.005


def _walk(obj: Any, out: list[dict]) -> None:
    if isinstance(obj, dict):
        if "slice_id" in obj and "verdict" in obj and "metrics" in obj:
            out.append(obj)
        for v in obj.values():
            _walk(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _walk(v, out)


def _is_interaction(sid: str) -> bool:
    return "×" in sid


def _parse_dims(sid: str) -> dict[str, str]:
    d: dict[str, str] = {}
    for p in re.split(r"[\|×]", sid):
        p = p.strip()
        if "=" not in p:
            continue
        k, v = p.split("=", 1)
        k = k.strip().lower()
        v = v.strip()
        if k in ("h",):
            k = "horizon"
        d[k] = v
    return d


def _proper_subset_dims(d_broad: dict[str, str], d_narrow: dict[str, str]) -> bool:
    if d_broad.get("horizon") != d_narrow.get("horizon"):
        return False
    if len(d_broad) >= len(d_narrow):
        return False
    for k, v in d_broad.items():
        if d_narrow.get(k) != v:
            return False
    return True


def _n(rec: dict) -> int:
    return int(rec.get("metrics", {}).get("n") or rec.get("n_eligible") or 0)


def _acc(rec: dict) -> float:
    return float(rec["metrics"]["accuracy"])


def _prior(rec: dict) -> float:
    b = rec.get("baselines") or {}
    if "prior_majority_accuracy" in b:
        return float(b["prior_majority_accuracy"])
    return float(b.get("conditional_majority_accuracy", 0))


def hard_filter(rec: dict) -> tuple[bool, str | None]:
    if rec.get("verdict") != "ACCEPTED":
        return False, None
    sid = rec["slice_id"]
    n = _n(rec)
    min_n = MIN_N_INTERACTION if _is_interaction(sid) else MIN_N_PRIMARY
    if n < min_n:
        return False, "FAIL_SAMPLE"

    b = rec.get("baselines") or {}
    acc = _acc(rec)
    prior = _prior(rec)
    if acc <= prior:
        return False, "FAIL_BASELINE"
    fam = rec.get("family") or ""
    if fam == "move":
        if acc <= float(b.get("always_move_accuracy", 0)) or acc <= float(b.get("always_no_move_accuracy", 0)):
            return False, "FAIL_BASELINE"
    else:
        if acc <= float(b.get("always_up_accuracy", 0)) or acc <= float(b.get("always_down_accuracy", 0)):
            return False, "FAIL_BASELINE"
    if acc <= float(b.get("random_accuracy_mean", 0)):
        return False, "FAIL_BASELINE"

    if acc - prior < MIN_EFFECT_VS_PRIOR:
        return False, "FAIL_EFFECT_SIZE"

    oos = rec.get("oos") or {}
    n_oos = int(oos.get("n_oos") or 0)
    oa = oos.get("oos_model_accuracy")
    op = oos.get("oos_prior_from_is_mode_accuracy")
    if n_oos < MIN_OOS_N:
        return False, "FAIL_OOS_STRICT"
    if oa is None or op is None or float(oa) < float(op):
        return False, "FAIL_OOS"

    stab = rec.get("stability_median_halves") or {}
    if stab.get("stability_fail_recent_lt_older_minus_0p03"):
        return False, "FAIL_STABILITY"

    return True, None


def main() -> int:
    if not ART.is_file():
        print(json.dumps({"error": f"missing {ART}"}))
        return 2
    rep = json.loads(ART.read_text(encoding="utf-8"))

    all_slices: list[dict] = []
    for block in ("primary_slices", "interaction_slices"):
        _walk(rep.get(block), all_slices)

    by_id: dict[str, dict] = {}
    for rec in all_slices:
        sid = rec["slice_id"]
        if sid not in by_id:
            by_id[sid] = rec

    init_accepted = sum(1 for r in by_id.values() if r.get("verdict") == "ACCEPTED")

    removal_log: list[dict[str, Any]] = []
    survivors: list[dict] = []
    for sid, rec in by_id.items():
        if rec.get("verdict") != "ACCEPTED":
            continue
        ok, reason = hard_filter(rec)
        if ok:
            survivors.append(rec)
        else:
            removal_log.append({"slice_id": sid, "reason": reason or "FAIL_UNKNOWN", "phase": "hard_filter"})

    for rec in survivors:
        rec["_dims"] = _parse_dims(rec["slice_id"])

    kept_sub: list[dict] = []
    for rec in survivors:
        d_c = rec["_dims"]
        acc_c = _acc(rec)
        sub = False
        for other in survivors:
            if other["slice_id"] == rec["slice_id"]:
                continue
            d_o = other["_dims"]
            if _proper_subset_dims(d_o, d_c) and _acc(other) >= acc_c - MATERIAL_GAIN_VS_PARENT:
                removal_log.append(
                    {"slice_id": rec["slice_id"], "reason": "SUBSUMED_BY_PARENT", "parent": other["slice_id"]}
                )
                sub = True
                break
        if not sub:
            kept_sub.append(rec)

    policy_usable = [
        {
            "slice_id": r["slice_id"],
            "horizon": r.get("horizon"),
            "family": r.get("family"),
            "n": _n(r),
            "accuracy": _acc(r),
            "verdict": "POLICY_USABLE",
        }
        for r in kept_sub
    ]

    out = {
        "source_report": str(ART),
        "initial_accepted": init_accepted,
        "after_hard_filter": len(survivors),
        "after_subsumption": len(kept_sub),
        "policy_usable": policy_usable,
        "removal_log": removal_log,
    }
    OUT.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"wrote": str(OUT), "policy_usable_count": len(policy_usable)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
