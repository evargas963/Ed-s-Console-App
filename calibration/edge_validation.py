#!/usr/bin/env python3
"""
Same-sample edge metrics vs naive baselines (trusted, anchored, labeled calibration rows).

Unlike phase4 snapshot baselines (different population), all baselines here use the **same rows**
as the decision log for apples-to-apples EV comparison.

  python -m calibration.edge_validation --db data/calibration_accumulation_validation.db
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sqlite3
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from calibration.anchor_audit import snapshot_has_bar_anchor
from calibration.analyze_phase3 import (
    _brier_triplet,
    _canonical_prob_triplet,
    _confidence_bucket,
    _load_json_col,
)
from calibration.analyze_phase4 import _directional_pnl, _load_json
from calibration.canonical_enforcement import CANONICAL_TIMEFRAME, enforce_calibration_decision_log_only_1m
from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from calibration.paths import DEFAULT_DB
from calibration.schema import ensure_calibration_schema
from calibration.statistical_integrity import MIN_SAMPLES_STATISTICAL, bucket_gate
from calibration.trust import TRUSTED_PREDICATE_SQL

try:
    from db import configure_sqlite_connection
except Exception:

    def configure_sqlite_connection(conn, **kwargs):
        pass


def _effective_directional_signal(r: dict[str, Any]) -> str:
    """
    Production may emit `wait` while canonical probabilities still encode a view.
    For same-sample EV vs baselines, use explicit long/short when present; else map
    dominant canonical class to long/up, short/down, else wait.
    """
    fs = (r.get("final_signal") or "wait").strip().lower()
    if fs in ("long", "short"):
        return fs
    trip = _canonical_prob_triplet(r.get("canonical_json"))
    if trip is None:
        return "wait"
    p_up, p_dn, p_fl = trip
    if p_up >= p_dn and p_up >= p_fl:
        return "long"
    if p_dn >= p_fl:
        return "short"
    return "wait"


def _mean(vals: list[float]) -> float:
    return float(sum(vals) / len(vals)) if vals else float("nan")


def _bootstrap_mean_diff(
    actual: list[float], baseline: list[float], *, n_boot: int = 2000, seed: int = 42
) -> dict[str, Any]:
    """Paired rows: same length, difference per index."""
    if len(actual) != len(baseline) or len(actual) < 2:
        return {"n": len(actual), "ci95_low": None, "ci95_high": None, "mean_diff": None}
    rng = random.Random(seed)
    diffs = [a - b for a, b in zip(actual, baseline)]
    obs = _mean(diffs)
    boot: list[float] = []
    n = len(diffs)
    for _ in range(n_boot):
        samp = [diffs[rng.randrange(n)] for _ in range(n)]
        boot.append(_mean(samp))
    boot.sort()
    lo = boot[int(0.025 * n_boot)]
    hi = boot[int(0.975 * n_boot)]
    return {
        "n": n,
        "mean_diff_actual_minus_baseline": round(obs, 6),
        "ci95_low": round(lo, 6),
        "ci95_high": round(hi, 6),
    }


def _quartile_slices(
    rows: list[dict[str, Any]], key: str = "decision_ts_utc"
) -> dict[str, list[dict[str, Any]]]:
    if not rows:
        return {}
    ts = sorted(float(r[key]) for r in rows)
    q1, q2, q3 = ts[len(ts) // 4], ts[len(ts) // 2], ts[3 * len(ts) // 4]

    def bucket(t: float) -> str:
        if t <= q1:
            return "q1_time"
        if t <= q2:
            return "q2_time"
        if t <= q3:
            return "q3_time"
        return "q4_time"

    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        out[bucket(float(r[key]))].append(r)
    return dict(out)


def analyze_edge(db_path: Path) -> dict[str, Any]:
    out: dict[str, Any] = {
        "meta": {"db": str(db_path), "ts": time.time()},
        "same_sample_baselines": {},
        "paired_bootstrap": {},
        "by_ticker": {},
        "by_regime_primary": {},
        "by_time_quartile": {},
        "brier": {},
        "confidence_reliability": {},
        "pass_gates": {},
        "binary_pass": False,
    }
    if not db_path.is_file():
        out["error"] = "db missing"
        return out

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    configure_sqlite_connection(conn)
    ensure_calibration_schema(conn)
    enforce_calibration_decision_log_only_1m(conn)

    rows_raw = conn.execute(
        f"""
        SELECT final_signal, call_conviction, outcome_5c, outcome_5c_pts, canonical_json,
               fusion_json, regime_primary, vol_regime, ticker, decision_ts_utc
        FROM calibration_decision_log
        WHERE outcome_5c IS NOT NULL AND canonical_timeframe=? AND ({TRUSTED_PREDICATE_SQL})
        """,
        (CANONICAL_TIMEFRAME,),
    ).fetchall()

    rows: list[dict[str, Any]] = []
    for r in rows_raw:
        if snapshot_has_bar_anchor(conn, r["ticker"], float(r["decision_ts_utc"])):
            rows.append(dict(r))

    conn.close()

    n = len(rows)
    gate_n = bucket_gate(n, MIN_SAMPLES_STATISTICAL)

    # Per-row PnL components (same outcome path for all baselines)
    actual_pnls: list[float | None] = []
    long_pnls: list[float] = []
    short_pnls: list[float] = []
    random_pnls: list[float] = []
    always_up_pts: list[float] = []  # raw outcome pts (long buy-and-hold proxy)
    brier_terms: list[float] = []
    bucket_hits: dict[str, list[int]] = defaultdict(list)

    recs: list[dict[str, Any]] = []
    for r in rows:
        pts = r["outcome_5c_pts"]
        oc = r["outcome_5c"]
        sig = _effective_directional_signal(r)
        pnl_a = _directional_pnl(sig, oc, float(pts) if pts is not None else None)
        pnl_l = _directional_pnl("long", oc, float(pts) if pts is not None else None)
        pnl_s = _directional_pnl("short", oc, float(pts) if pts is not None else None)
        if pts is not None:
            always_up_pts.append(float(pts))
        if pnl_l is not None and pnl_s is not None:
            random_pnls.append(0.5 * (pnl_l + pnl_s))
        else:
            random_pnls.append(float("nan"))
        long_pnls.append(pnl_l if pnl_l is not None else float("nan"))
        short_pnls.append(pnl_s if pnl_s is not None else float("nan"))
        actual_pnls.append(pnl_a)

        trip = _canonical_prob_triplet(r.get("canonical_json"))
        if trip is not None:
            y5 = (oc or "").strip().lower()
            brier_terms.append(_brier_triplet(trip[0], trip[1], trip[2], y5))
            p_up, p_dn, p_fl = trip
            dom = "up" if p_up >= p_dn and p_up >= p_fl else ("down" if p_dn >= p_fl else "flat")
            hit = 1 if dom == y5 else 0
            cj = _load_json_col(r.get("canonical_json"))
            bkt = _confidence_bucket(cj.get("confidence"))
            bucket_hits[bkt].append(hit)

        recs.append(
            {
                "ticker": r["ticker"],
                "regime_primary": r["regime_primary"] or "unknown",
                "decision_ts_utc": float(r["decision_ts_utc"]),
                "final_signal": r.get("final_signal"),
                "effective_signal_for_ev": sig,
                "pnl_actual": pnl_a,
                "pnl_long": pnl_l,
                "pnl_short": pnl_s,
                "pnl_random": random_pnls[-1],
            }
        )

    # Filter paired lists for bootstrap (exclude rows where actual is None — still compare to random where defined)
    paired_idx = [i for i in range(n) if actual_pnls[i] is not None and not math.isnan(random_pnls[i])]
    act_v = [float(actual_pnls[i]) for i in paired_idx]
    rnd_v = [float(random_pnls[i]) for i in paired_idx]
    paired_long = [i for i in paired_idx if not math.isnan(long_pnls[i])]
    act_pl = [float(actual_pnls[i]) for i in paired_long]
    long_pl = [float(long_pnls[i]) for i in paired_long]
    short_pl = [float(short_pnls[i]) for i in paired_long if not math.isnan(short_pnls[i])]
    mean_dn = _mean(short_pl) if short_pl else float("nan")

    mean_act = _mean(act_v) if act_v else float("nan")
    mean_rnd = _mean(rnd_v) if rnd_v else float("nan")
    mean_long = _mean(long_pl) if long_pl else float("nan")
    mean_raw_up = _mean(always_up_pts) if always_up_pts else float("nan")

    out["same_sample_baselines"] = {
        "labeled_sample_count": n,
        "signal_convention": (
            "EV uses effective_signal_for_ev: final_signal when long/short; else dominant canonical class "
            "→ long/up, short/down, wait/flat."
        ),
        "aggregate_sample_gate": gate_n,
        "mean_pnl_proxy_actual_signal": round(mean_act, 6) if not math.isnan(mean_act) else None,
        "mean_pnl_proxy_always_long_directional": round(mean_long, 6) if not math.isnan(mean_long) else None,
        "mean_outcome_5c_pts_raw_always_long_litmus": round(mean_raw_up, 6)
        if not math.isnan(mean_raw_up)
        else None,
        "mean_pnl_proxy_random_long_short_mix": round(mean_rnd, 6) if not math.isnan(mean_rnd) else None,
        "mean_pnl_proxy_always_short_directional": round(mean_dn, 6) if not math.isnan(mean_dn) else None,
        "note": (
            "random baseline = per-row 0.5*(pnl_if_long + pnl_if_short) from same outcome; "
            "always_long = directional long PnL; raw pts = outcome_5c_pts mean (buy-and-hold signed move)."
        ),
    }

    out["paired_bootstrap"] = {
        "actual_minus_random": _bootstrap_mean_diff(act_v, rnd_v),
        "actual_minus_always_long": _bootstrap_mean_diff(act_pl, long_pl),
    }

    # Brier
    br_g = bucket_gate(len(brier_terms), MIN_SAMPLES_STATISTICAL)
    mean_brier = round(sum(brier_terms) / len(brier_terms), 6) if brier_terms and br_g["sufficient_sample"] else None
    out["brier"] = {
        "mean_brier_canonical_vs_outcome_5c": mean_brier,
        "n": len(brier_terms),
        "brier_sample_gate": br_g,
        "uninformative_3class_reference": 0.666667,
        "note": "Reference ~2/3 is max-prob 1/3 on each class (uninformative); lower is better calibration.",
    }

    rel: dict[str, Any] = {}
    for bkt, hits in sorted(bucket_hits.items()):
        g = bucket_gate(len(hits), MIN_SAMPLES_STATISTICAL)
        rate = round(sum(hits) / len(hits), 6) if g["sufficient_sample"] and hits else None
        rel[bkt] = {"n": len(hits), "sample_gate": g, "empirical_hit_rate_dom_class": rate}
    out["confidence_reliability"] = rel

    def slice_metrics(label: str, group: list[dict[str, Any]]) -> dict[str, Any]:
        av: list[float] = []
        rv: list[float] = []
        for r in group:
            es = _effective_directional_signal(r)
            pnl_a = _directional_pnl(
                es,
                r["outcome_5c"],
                float(r["outcome_5c_pts"]) if r["outcome_5c_pts"] is not None else None,
            )
            pnl_l = _directional_pnl(
                "long", r["outcome_5c"], float(r["outcome_5c_pts"]) if r["outcome_5c_pts"] is not None else None
            )
            pnl_s = _directional_pnl(
                "short", r["outcome_5c"], float(r["outcome_5c_pts"]) if r["outcome_5c_pts"] is not None else None
            )
            if pnl_a is None or pnl_l is None or pnl_s is None:
                continue
            rnd = 0.5 * (pnl_l + pnl_s)
            av.append(float(pnl_a))
            rv.append(float(rnd))
        gm = bucket_gate(len(av), MIN_SAMPLES_STATISTICAL)
        m_a = round(_mean(av), 6) if gm["sufficient_sample"] and av else None
        m_r = round(_mean(rv), 6) if gm["sufficient_sample"] and rv else None
        edge = round(m_a - m_r, 6) if m_a is not None and m_r is not None else None
        return {
            "label": label,
            "n_rows": len(group),
            "paired_n": len(av),
            "sample_gate": gm,
            "mean_actual": m_a,
            "mean_random_baseline": m_r,
            "edge_vs_random": edge,
        }

    by_tk: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_tk[r["ticker"]].append(r)
    for tk, lst in sorted(by_tk.items()):
        out["by_ticker"][tk] = slice_metrics(f"ticker:{tk}", lst)

    by_rg: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_rg[r["regime_primary"] or "unknown"].append(r)
    for rg, lst in sorted(by_rg.items()):
        out["by_regime_primary"][rg] = slice_metrics(f"regime:{rg}", lst)

    for qk, lst in _quartile_slices(rows).items():
        out["by_time_quartile"][qk] = slice_metrics(qk, lst)

    # PASS gates (strict — "real edge" must beat naive policies, not only the random long/short mix)
    ev_ok = gate_n["sufficient_sample"] and not math.isnan(mean_act) and not math.isnan(mean_rnd) and mean_act > mean_rnd
    ev_gt_long = (
        gate_n["sufficient_sample"]
        and not math.isnan(mean_act)
        and not math.isnan(mean_long)
        and mean_act > mean_long + 1e-9
    )
    # Informational only: always-short is trivially worse when 5c outcomes skew one way.
    ev_gt_short_info = (
        gate_n["sufficient_sample"]
        and not math.isnan(mean_act)
        and not math.isnan(mean_dn)
        and mean_act > mean_dn + 1e-9
    )
    brier_ok = (
        mean_brier is not None
        and br_g["sufficient_sample"]
        and mean_brier < out["brier"]["uninformative_3class_reference"]
    )
    boot = out["paired_bootstrap"]["actual_minus_random"]
    boot_ok = boot.get("ci95_low") is not None and boot["ci95_low"] > 0.0
    boot_l = out["paired_bootstrap"]["actual_minus_always_long"]
    boot_gt_long_ok = boot_l.get("ci95_low") is not None and boot_l["ci95_low"] > 0.0

    # Slices: every slice with sufficient sample must have edge_vs_random > 0 (or None if insufficient)
    slice_consistency_ok = True
    slice_failures: list[str] = []
    for name, d in list(out["by_ticker"].items()) + list(out["by_regime_primary"].items()):
        sg = d.get("sample_gate") or {}
        if not sg.get("sufficient_sample"):
            continue
        ev = d.get("edge_vs_random")
        if ev is None or ev <= 0:
            slice_consistency_ok = False
            slice_failures.append(f"{name}: edge_vs_random={ev}")

    # At least two slice dimensions with independent n>=30 (e.g. two tickers or ticker+time)
    slice_dims_ok = sum(
        1
        for d in list(out["by_ticker"].values()) + list(out["by_time_quartile"].values())
        if (d.get("sample_gate") or {}).get("sufficient_sample")
    ) >= 2

    pass_gates = {
        "aggregate_n_sufficient": gate_n["sufficient_sample"],
        "ev_mean_actual_gt_mean_random_mix": ev_ok,
        "ev_mean_actual_strictly_gt_always_long": ev_gt_long,
        "brier_better_than_uninformative_reference": brier_ok,
        "bootstrap_actual_minus_random_ci95_exclude_zero": boot_ok,
        "bootstrap_actual_minus_always_long_ci95_exclude_zero": boot_gt_long_ok,
        "all_sufficient_slices_edge_positive": slice_consistency_ok,
        "at_least_two_independent_slices_n_ge_min": slice_dims_ok,
    }
    out["pass_gates"] = pass_gates
    out["informational_only"] = {
        "ev_gt_always_short_directional": ev_gt_short_info,
        "note": "Always-short baseline is not a required gate (often trivial vs one-sided outcomes).",
    }
    out["slice_failures"] = slice_failures
    out["binary_pass"] = bool(
        all(
            [
                pass_gates["aggregate_n_sufficient"],
                pass_gates["ev_mean_actual_gt_mean_random_mix"],
                pass_gates["ev_mean_actual_strictly_gt_always_long"],
                pass_gates["brier_better_than_uninformative_reference"],
                pass_gates["bootstrap_actual_minus_random_ci95_exclude_zero"],
                pass_gates["bootstrap_actual_minus_always_long_ci95_exclude_zero"],
                pass_gates["all_sufficient_slices_edge_positive"],
                pass_gates["at_least_two_independent_slices_n_ge_min"],
            ]
        )
    )

    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="calibration.edge_validation", write_capable=False)
    data = analyze_edge(args.db)
    outp = Path(__file__).resolve().parent.parent / "data" / "calibration_edge_validation_report.json"
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(json.dumps({"wrote": str(outp), "binary_pass": data.get("binary_pass")}, indent=2))
    return 0 if data.get("binary_pass") else 3


if __name__ == "__main__":
    sys.exit(main())
