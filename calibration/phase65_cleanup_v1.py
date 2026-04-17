#!/usr/bin/env python3
"""
Phase 6.5 cleanup: filter/deduplicate phase65 JSON — no recomputation of grid.

  python -m calibration.phase65_cleanup_v1
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "data" / "phase65_edge_isolation_v1_report.json"
OUT = ROOT / "data" / "phase65_cleanup_v1_result.json"

MIN_N_PRIMARY = 200
MIN_N_INTERACTION = 100
MIN_OOS_N = 50
MIN_EFFECT_VS_PRIOR = 0.01
MATERIAL_GAIN_VS_PARENT = 0.005
FLAT_SHARE_DOM = 0.55
FLAT_DOM_MAX_UPLIFT = 0.02


def _walk(obj: Any, out: list[dict]) -> None:
    if isinstance(obj, dict):
        if "slice_id" in obj and "verdict" in obj:
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
    return float(rec["baselines"]["prior_majority_accuracy"])


def _flat_share(rec: dict) -> float:
    bal = rec.get("metrics", {}).get("class_balance") or {}
    n = _n(rec)
    if n <= 0:
        return 0.0
    return float(bal.get("flat", 0)) / n


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
    if acc <= float(b.get("prior_majority_accuracy", 0)):
        return False, "FAIL_BASELINE"
    if acc <= float(b.get("always_up_accuracy", 0)):
        return False, "FAIL_BASELINE"
    if acc <= float(b.get("always_down_accuracy", 0)):
        return False, "FAIL_BASELINE"
    if acc <= float(b.get("random_uniform_accuracy_mean", 0)):
        return False, "FAIL_BASELINE"

    if acc - prior < MIN_EFFECT_VS_PRIOR:
        return False, "FAIL_EFFECT_SIZE"

    if (b.get("prior_majority_class") == "flat") and _flat_share(rec) >= FLAT_SHARE_DOM and (acc - prior) < FLAT_DOM_MAX_UPLIFT:
        return False, "FAIL_FLAT_DOMINANCE"

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
    _walk(rep.get("primary_slices"), all_slices)
    _walk(rep.get("interaction_slices"), all_slices)

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

    after_hard = len(survivors)

    for rec in survivors:
        rec["_dims"] = _parse_dims(rec["slice_id"])

    # Subsumption: drop narrow slice if a broader same-horizon slice exists with >= accuracy - margin
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

    after_sub = len(kept_sub)

    single_by_h: dict[str, list[dict]] = defaultdict(list)
    for rec in kept_sub:
        if _is_interaction(rec["slice_id"]):
            continue
        h = rec["_dims"].get("horizon")
        if h:
            single_by_h[h].append(rec)

    kept_inter: list[dict] = []
    for rec in kept_sub:
        if not _is_interaction(rec["slice_id"]):
            kept_inter.append(rec)
            continue
        h = rec["_dims"].get("horizon")
        if not h or not single_by_h.get(h):
            kept_inter.append(rec)
            continue
        best = max(_acc(x) for x in single_by_h[h])
        if _acc(rec) <= best + 0.002:
            removal_log.append({"slice_id": rec["slice_id"], "reason": "NO_INTERACTION_GAIN"})
        else:
            kept_inter.append(rec)

    after_inter = len(kept_inter)

    stab2: list[dict] = []
    for rec in kept_inter:
        st = rec.get("stability_median_halves") or {}
        ao, ar = st.get("accuracy_older_half"), st.get("accuracy_recent_half")
        if ao is not None and ar is not None:
            if float(ar) < float(ao) - 0.02:
                removal_log.append({"slice_id": rec["slice_id"], "reason": "UNSTABLE"})
                continue
        stab2.append(rec)

    after_stab = len(stab2)

    conf_fail = (rep.get("confidence_ranking_validation") or {}).get("verdict") == "FAIL"

    confidence_dependent: list[str] = []
    for rec in stab2:
        if "confidence" in rec["_dims"]:
            confidence_dependent.append(rec["slice_id"])

    clusters: dict[str, list[dict]] = defaultdict(list)
    for rec in stab2:
        d = rec["_dims"]
        h = d.get("horizon", "?")
        rg = d.get("regime", "_none")
        key = f"H={h}|regime={rg}"
        clusters[key].append(rec)

    cluster_summ: list[dict[str, Any]] = []
    for key, members in clusters.items():
        if not members:
            continue
        tn = sum(_n(m) for m in members)
        w_acc = sum(_n(m) * _acc(m) for m in members) / tn if tn else 0.0
        priors = [_prior(m) for m in members]
        cluster_summ.append(
            {
                "cluster_id": key,
                "member_slice_ids": sorted({m["slice_id"] for m in members}),
                "n_total_sum_member_n_overlap_not_distinct_rows": tn,
                "weighted_accuracy": round(w_acc, 6),
                "mean_prior_majority": round(sum(priors) / len(priors), 6),
                "members": len(members),
            }
        )

    cluster_summ.sort(key=lambda x: -x["n_total_sum_member_n_overlap_not_distinct_rows"])

    policy: list[dict] = []
    research_clusters: list[dict] = []
    for c in cluster_summ:
        uplift = c["weighted_accuracy"] - c["mean_prior_majority"]
        tn = c["n_total_sum_member_n_overlap_not_distinct_rows"]
        usable = (
            (not conf_fail)
            and tn >= 8000
            and uplift >= 0.02
            and not any(x in confidence_dependent for x in c["member_slice_ids"])
        )
        row = {**c, "classification": "POLICY_USABLE" if usable else "RESEARCH_ONLY"}
        if usable:
            policy.append(row)
        else:
            research_clusters.append(row)

    if conf_fail:
        policy = []
        for c in cluster_summ:
            c["classification"] = "RESEARCH_ONLY"
            c["policy_blocker"] = "CONFIDENCE_RANKING_FAIL"
        research_clusters = [{**c, "classification": "RESEARCH_ONLY"} for c in cluster_summ]

    reason_counts: dict[str, int] = defaultdict(int)
    for x in removal_log:
        reason_counts[x["reason"]] += 1

    rejected_automated = [sid for sid, r in by_id.items() if r.get("verdict") == "REJECTED"]
    inconclusive = [sid for sid, r in by_id.items() if r.get("verdict") == "INCONCLUSIVE"]
    insufficient = [sid for sid, r in by_id.items() if r.get("verdict") == "INSUFFICIENT"]

    result = {
        "source_artifact": str(ART),
        "initial_automated_accepted": init_accepted,
        "after_hard_filter": after_hard,
        "after_subsumption": after_sub,
        "after_interaction_collapse": after_inter,
        "after_stability_recheck": after_stab,
        "final_cluster_count": len(cluster_summ),
        "removal_reason_counts": dict(sorted(reason_counts.items(), key=lambda x: -x[1])),
        "accepted_edge_clusters": cluster_summ,
        "policy_usable_clusters": policy,
        "research_only_clusters": research_clusters if not conf_fail else cluster_summ,
        "surviving_slice_ids": sorted({r["slice_id"] for r in stab2}),
        "confidence_dependent_survivors": sorted(set(confidence_dependent)),
        "removal_log_sample": removal_log[:100],
        "rejected_verdict_count": len(rejected_automated),
        "inconclusive_verdict_count": len(inconclusive),
        "insufficient_verdict_count": len(insufficient),
        "confidence_ranking_global": rep.get("confidence_ranking_validation"),
    }
    OUT.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    print(
        json.dumps(
            {
                "wrote": str(OUT),
                "initial_automated_accepted": init_accepted,
                "after_hard_filter": after_hard,
                "after_subsumption": after_sub,
                "after_interaction_collapse": after_inter,
                "after_stability_recheck": after_stab,
                "final_cluster_count": len(cluster_summ),
                "policy_usable_n": len(policy),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
