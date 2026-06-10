#!/usr/bin/env python3
"""
Directional diagnostics, failure analysis, candidate row filters, and edge re-evaluation.

  python -m calibration.signal_engineering --db data/calibration_accumulation_validation.db

Writes data/calibration_signal_engineering_report.json and docs/calibration_signal_engineering_v1.md
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from arch_competition.atomic_io import write_json_file_atomically
from numeric_contract import direction_from_normalized_triplet
from calibration.analyze_phase4 import _directional_pnl
from calibration.db_guard import enforce_resolved_path, register_allow_noncanonical_flag
from calibration.edge_discovery import (
    SignalFn,
    aggregate_slice,
    load_labeled_rows,
    pick_db_path,
    run_discovery_rows,
)
from calibration.edge_validation import _effective_directional_signal
from calibration.json_utils import parse_json_mapping
from calibration.v2_a1_calibration import axis_reliability_bucket_value


def _lj(s: str | None, *, context: str = "signal_engineering") -> dict[str, Any]:
    return parse_json_mapping(s, context=context)


def _features(r: dict[str, Any]) -> dict[str, Any]:
    f = r.get("_features")
    return f if isinstance(f, dict) else {}


# --- Alternative directional policies (break canonical tie → long) ---


def signal_canonical_effective(r: dict[str, Any]) -> str:
    return _effective_directional_signal(r)


def signal_fusion_argmax(r: dict[str, Any]) -> str:
    """Map fusion posterior argmax to long/short/wait (no margin)."""
    fj = _lj(r.get("fusion_json"))
    pu, pd, pf = fj.get("prob_up"), fj.get("prob_down"), fj.get("prob_flat")
    if pu is None or pd is None or pf is None:
        return "wait"
    best = max(
        [("up", float(pu)), ("down", float(pd)), ("flat", float(pf))],
        key=lambda x: x[1],
    )
    return {"up": "long", "down": "short", "flat": "wait"}[best[0]]


def signal_fusion_margin_factory(margin: float) -> SignalFn:
    """Require top−second >= margin else wait (reduces false long from ties)."""

    def _fn(r: dict[str, Any]) -> str:
        fj = _lj(r.get("fusion_json"))
        pu, pd, pf = fj.get("prob_up"), fj.get("prob_down"), fj.get("prob_flat")
        if pu is None or pd is None or pf is None:
            return "wait"
        probs = [float(pu), float(pd), float(pf)]
        srt = sorted(probs, reverse=True)
        if srt[0] - srt[1] < margin:
            return "wait"
        best_lab = direction_from_normalized_triplet(float(pu), float(pd), float(pf))
        return {"up": "long", "down": "short", "flat": "wait"}[best_lab]

    _fn.__name__ = f"fusion_margin_{margin}"
    return _fn


def signal_fusion_dominant_outcome(r: dict[str, Any]) -> str:
    """
    Prefer `dominant_direction` (up/down/flat); `dominant_outcome` may be a regime label (e.g. pinning).
    """
    fj = _lj(r.get("fusion_json"))
    dd = str(fj.get("dominant_direction") or "").strip().lower()
    if dd in ("up", "u"):
        return "long"
    if dd in ("down", "d"):
        return "short"
    if dd in ("flat", "f", "neutral"):
        return "wait"
    dom = str(fj.get("dominant_outcome") or "").strip().lower()
    if dom in ("up", "down", "flat"):
        return {"up": "long", "down": "short", "flat": "wait"}[dom]
    return "wait"


def signal_model_stack_vote(r: dict[str, Any]) -> str:
    """Majority vote of xgb/lstm/transformer dominant_class toward long/short/wait."""
    mo = _lj(r.get("model_outputs_json"))
    votes: list[str] = []
    for name in ("xgb", "lstm", "transformer"):
        blk = mo.get(name)
        if isinstance(blk, str):
            blk = _lj(blk, context=f"signal_engineering:model_outputs.{name}")
        if not isinstance(blk, dict):
            continue
        dc = (blk.get("dominant_class") or blk.get("direction") or "").strip().lower()
        if dc in ("up", "long"):
            votes.append("long")
        elif dc in ("down", "short"):
            votes.append("short")
        else:
            votes.append("wait")
    if not votes:
        return "wait"
    lc = sum(1 for v in votes if v == "long")
    sc = sum(1 for v in votes if v == "short")
    wc = sum(1 for v in votes if v == "wait")
    m = max((lc, "long"), (sc, "short"), (wc, "wait"), key=lambda x: x[0])
    return m[1]


def directional_diagnostics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts and EV by logged final_signal vs canonical-effective vs fusion-argmax."""
    out: dict[str, Any] = {}

    def dist(key_fn: Callable[[dict[str, Any]], str]) -> dict[str, int]:
        d: dict[str, int] = {}
        for r in rows:
            k = key_fn(r)
            d[k] = d.get(k, 0) + 1
        return dict(sorted(d.items(), key=lambda x: -x[1]))

    out["pct_final_signal"] = dist(lambda r: (r.get("final_signal") or "wait").strip().lower())
    out["pct_canonical_effective"] = dist(signal_canonical_effective)
    out["pct_fusion_argmax"] = dist(signal_fusion_argmax)
    out["pct_fusion_margin_0.04"] = dist(signal_fusion_margin_factory(0.04))
    out["pct_fusion_margin_0.006"] = dist(signal_fusion_margin_factory(0.006))
    out["pct_fusion_dominant_outcome"] = dist(signal_fusion_dominant_outcome)

    def ev_by_direction(sig_fn: SignalFn) -> dict[str, Any]:
        by_dir: dict[str, list[float]] = {}
        wr: dict[str, list[int]] = {}
        for r in rows:
            oc = r["outcome_5c"]
            pts = r["outcome_5c_pts"]
            p = float(pts) if pts is not None else None
            d = sig_fn(r)
            pnl = _directional_pnl(d, oc, p)
            if pnl is None:
                continue
            by_dir.setdefault(d, []).append(float(pnl))
            wr.setdefault(d, []).append(1 if pnl > 0 else 0)
        ev: dict[str, float | None] = {}
        winr: dict[str, float | None] = {}
        for k, v in by_dir.items():
            ev[k] = round(statistics.mean(v), 6) if v else None
            winr[k] = round(sum(wr[k]) / len(wr[k]), 6) if wr.get(k) else None
        return {"mean_ev_by_direction": ev, "win_rate_by_direction": winr}

    out["ev_by_direction_canonical_effective"] = ev_by_direction(signal_canonical_effective)
    out["ev_by_direction_fusion_argmax"] = ev_by_direction(signal_fusion_argmax)
    out["ev_by_direction_fusion_margin_0.04"] = ev_by_direction(signal_fusion_margin_factory(0.04))
    out["ev_by_direction_fusion_margin_0.006"] = ev_by_direction(signal_fusion_margin_factory(0.006))
    out["ev_by_direction_fusion_dominant_outcome"] = ev_by_direction(signal_fusion_dominant_outcome)

    fus_pu: list[float] = []
    fus_pd: list[float] = []
    fus_pf: list[float] = []
    spreads: list[float] = []
    for r in rows:
        fj = _lj(r.get("fusion_json"))
        pu, pd, pf = fj.get("prob_up"), fj.get("prob_down"), fj.get("prob_flat")
        if pu is None or pd is None or pf is None:
            continue
        a, b, c = float(pu), float(pd), float(pf)
        fus_pu.append(a)
        fus_pd.append(b)
        fus_pf.append(c)
        srt = sorted([a, b, c], reverse=True)
        spreads.append(srt[0] - srt[1])

    def ms(xs: list[float]) -> dict[str, float | None]:
        if not xs:
            return {"min": None, "mean": None, "max": None}
        return {"min": round(min(xs), 6), "mean": round(statistics.mean(xs), 6), "max": round(max(xs), 6)}

    out["fusion_prob_distribution"] = {
        "prob_up": ms(fus_pu),
        "prob_down": ms(fus_pd),
        "prob_flat": ms(fus_pf),
        "top_minus_second": ms(spreads),
    }

    mo_spreads: list[float] = []
    for r in rows:
        mo = _lj(r.get("model_outputs_json"))
        for name in ("xgb", "lstm", "transformer"):
            blk = mo.get(name)
            if isinstance(blk, str):
                blk = _lj(blk, context=f"signal_engineering:model_outputs.{name}")
            if not isinstance(blk, dict):
                continue
            pu, pd, pf = blk.get("prob_up"), blk.get("prob_down"), blk.get("prob_flat")
            if pu is None or pd is None or pf is None:
                continue
            a, b, c = float(pu), float(pd), float(pf)
            srt = sorted([a, b, c], reverse=True)
            mo_spreads.append(srt[0] - srt[1])
    out["model_output_prob_separation"] = {
        "top_minus_second_per_model_row": ms(mo_spreads),
        "note": "Flattened x3 models × rows; stub uses identical probs → separation ~0.",
    }
    return out


def failure_identification(rows: list[dict[str, Any]]) -> dict[str, Any]:
    fj0 = _lj(rows[0].get("fusion_json")) if rows else {}
    cj0 = _lj(rows[0].get("canonical_json")) if rows else {}
    return {
        "why_canonical_defaults_long": [
            "_effective_directional_signal uses canonical triplet; tie-break order is p_up >= p_dn >= p_fl → 'long' when equal or up wins.",
            "Stub fusion + canonical stack produce max class 'up' with small positive spread over 'down' in logged JSON.",
        ],
        "why_short_signals_absent_in_log": [
            "call.signal / final_signal from compute_signals path is 'wait' under test harness (no directional trade from decision engine).",
            "Canonical/fusion still encode direction probabilities but execution layer does not emit short without policy change.",
        ],
        "model_output_separation": [
            "Fake run_unified_stack_ml_once returns identical 0.34/0.33/0.33 per model → no cross-model disagreement for stack vote.",
        ],
        "sample_fusion_keys": list(fj0.keys())[:25],
        "sample_canonical_keys": list(cj0.keys())[:25],
    }


# --- Row filters (candidate gates) ---


def filter_high_confidence_or_fusion(r: dict[str, Any]) -> bool:
    ccb = _features(r).get("canonical_confidence_bucket") or "low"
    if ccb == "high":
        return True
    fj = _lj(r.get("fusion_json"))
    pu, pd, pf = fj.get("prob_up"), fj.get("prob_down"), fj.get("prob_flat")
    if pu is None or pd is None or pf is None:
        return False
    return max(float(pu), float(pd), float(pf)) >= 0.45


def filter_alignment_not_unusable(r: dict[str, Any]) -> bool:
    st = (_features(r).get("alignment_state") or "").upper()
    if "UNUSABLE" in st:
        return False
    if st in ("", "UNKNOWN", "__MISSING__"):
        return False
    return True


def filter_regime_not_pinning(r: dict[str, Any]) -> bool:
    return (r.get("regime_primary") or "").strip().lower() != "pinning"


def filter_vol_known(r: dict[str, Any]) -> bool:
    v = axis_reliability_bucket_value(r.get("vol_regime")).strip().lower()
    return v not in ("", "unknown", "__missing__")


def filter_vix_bucket_set(r: dict[str, Any]) -> bool:
    v = axis_reliability_bucket_value(r.get("vix_bucket")).strip().lower()
    return v not in ("", "unknown", "__missing__")


def filter_utc_us_cash_hours(r: dict[str, Any]) -> bool:
    """Rough US equity session in UTC (not holiday-aware)."""
    h = int(_features(r).get("utc_hour") or 0)
    return 13 <= h <= 21


def filter_utc_hour_0_5(r: dict[str, Any]) -> bool:
    """Matches harness DB where decision_ts maps to utc_hour==3."""
    h = int(_features(r).get("utc_hour") or 0)
    return 0 <= h <= 5


def filter_all_rows(_r: dict[str, Any]) -> bool:
    return True


def filter_combined(*preds: Callable[[dict[str, Any]], bool]) -> Callable[[dict[str, Any]], bool]:
    return lambda r: all(p(r) for p in preds)


FILTER_PRESETS: dict[str, Callable[[dict[str, Any]], bool]] = {
    "all_rows_control": filter_all_rows,
    "high_confidence_or_strong_fusion_max": filter_high_confidence_or_fusion,
    "alignment_not_unusable": filter_alignment_not_unusable,
    "regime_not_pinning": filter_regime_not_pinning,
    "vol_regime_known": filter_vol_known,
    "vix_bucket_populated": filter_vix_bucket_set,
    "utc_13_21_us_proxy": filter_utc_us_cash_hours,
    "utc_00_05_harness_overlap": filter_utc_hour_0_5,
    "strict_stack": filter_combined(
        filter_high_confidence_or_fusion,
        filter_alignment_not_unusable,
        filter_utc_us_cash_hours,
    ),
}


def run_engineering(db_path: Path) -> dict[str, Any]:
    rows, meta = load_labeled_rows(db_path)
    diag = directional_diagnostics(rows)
    fail = failure_identification(rows)

    before_pop = aggregate_slice(
        "population|before|canonical_effective",
        "population",
        rows,
        signal_canonical_effective,
    )

    scenarios: list[dict[str, Any]] = [
        {
            "name": "after_policy_fusion_margin_0.04_full_pop",
            "signal": "fusion_margin_0.04",
            "population": aggregate_slice(
                "population|after|fusion_margin_0.04",
                "population",
                rows,
                signal_fusion_margin_factory(0.04),
            ),
            "marginal_edge_any": False,
        },
        {
            "name": "after_policy_fusion_margin_0.006_full_pop",
            "signal": "fusion_margin_0.006",
            "population": aggregate_slice(
                "population|after|fusion_margin_0.006",
                "population",
                rows,
                signal_fusion_margin_factory(0.006),
            ),
            "marginal_edge_any": False,
        },
        {
            "name": "after_policy_fusion_argmax_full_pop",
            "signal": "fusion_argmax",
            "population": aggregate_slice(
                "population|after|fusion_argmax",
                "population",
                rows,
                signal_fusion_argmax,
            ),
            "marginal_edge_any": False,
        },
        {
            "name": "after_policy_fusion_dominant_outcome_full_pop",
            "signal": "fusion_dominant_outcome",
            "population": aggregate_slice(
                "population|after|fusion_dominant_outcome",
                "population",
                rows,
                signal_fusion_dominant_outcome,
            ),
            "marginal_edge_any": False,
        },
    ]

    filtered_runs: list[dict[str, Any]] = []
    for fname, pred in FILTER_PRESETS.items():
        sub = [r for r in rows if pred(r)]
        if len(sub) < 5:
            continue
        rep = run_discovery_rows(
            sub,
            {**meta, "filter": fname, "subset_n": len(sub)},
            signal_fn=signal_fusion_margin_factory(0.04),
        )
        edge_m = [s for s in rep["slices_all"] if s["classification"] == "EDGE" and "marginal" in s["slice_kind"]]
        filtered_runs.append(
            {
                "filter_name": fname,
                "n": len(sub),
                "population": aggregate_slice(
                    f"population|filtered|{fname}|fusion_margin_0.04",
                    "population+filter",
                    sub,
                    signal_fusion_margin_factory(0.04),
                ),
                "marginal_EDGE_slices": edge_m,
                "FINAL_FILTER_EDGE": "EDGE" if edge_m else "NO_EDGE",
                "top_slices_by_delta_long": sorted(
                    rep["slices_all"],
                    key=lambda s: (s.get("delta_ev_actual_minus_long") or -1e9),
                    reverse=True,
                )[:8],
            }
        )

    any_edge = any(fr["FINAL_FILTER_EDGE"] == "EDGE" for fr in filtered_runs)
    pop_edge_any_policy = any(s["population"]["classification"] == "EDGE" for s in scenarios)

    return {
        "meta": meta,
        "diagnostics": diag,
        "failure_analysis": fail,
        "before": {"population_slice": before_pop},
        "after_policies": scenarios,
        "filtered_runs": filtered_runs,
        "FINAL_SYSTEM": {
            "population_EDGE_any_policy": pop_edge_any_policy,
            "any_marginal_EDGE_on_filtered_sets": any_edge,
            "FINAL_RESULT": "EDGE" if (pop_edge_any_policy or any_edge) else "NO_EDGE",
        },
    }


def _write_md(rep: dict[str, Any], path: Path) -> None:
    lines = [
        "# Calibration signal engineering (v1)",
        "",
        "## Before vs after (population aggregates)",
        "",
        "```json",
        json.dumps(
            {
                "before_canonical_effective": rep["before"]["population_slice"],
                "after_policies": {s["name"]: s["population"] for s in rep["after_policies"]},
            },
            indent=2,
        ),
        "```",
        "",
        "## Directional diagnostics",
        "",
        "```json",
        json.dumps(rep["diagnostics"], indent=2),
        "```",
        "",
        "## Failure identification",
        "",
        "```json",
        json.dumps(rep["failure_analysis"], indent=2),
        "```",
        "",
        "## Filtered runs (fusion_margin=0.04 + row filter)",
        "",
    ]
    for fr in rep["filtered_runs"]:
        lines.append(f"### {fr['filter_name']} (n={fr['n']})")
        lines.append("")
        lines.append(f"- **FINAL_FILTER_EDGE:** `{fr['FINAL_FILTER_EDGE']}`")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(fr["population"], indent=2))
        lines.append("```")
        lines.append("")

    lines.extend(
        [
            "## Best filtered marginal slices (by delta_vs_long, top from each run)",
            "",
            "```json",
            json.dumps(
                [
                    {
                        "filter": fr["filter_name"],
                        "slices": fr["top_slices_by_delta_long"][:3],
                    }
                    for fr in rep["filtered_runs"]
                ],
                indent=2,
            ),
            "```",
            "",
            "## FINAL",
            "",
            f"- **FINAL_RESULT:** `{rep['FINAL_SYSTEM']['FINAL_RESULT']}`",
            f"- population EDGE (any policy in after_policies): `{rep['FINAL_SYSTEM']['population_EDGE_any_policy']}`",
            f"- any filtered marginal EDGE: `{rep['FINAL_SYSTEM']['any_marginal_EDGE_on_filtered_sets']}`",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=None)
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    db = pick_db_path(args.db)
    enforce_resolved_path(
        db,
        allow_noncanonical=bool(getattr(args, "allow_noncanonical_db", False)),
        tool_name="calibration.signal_engineering",
        write_capable=False,
    )
    if not db.is_file():
        print(json.dumps({"error": str(db)}))
        return 2
    rep = run_engineering(db)
    outp = ROOT / "data" / "calibration_signal_engineering_report.json"
    outp.parent.mkdir(parents=True, exist_ok=True)
    write_json_file_atomically(outp, rep, indent=2)
    md = ROOT / "docs" / "calibration_signal_engineering_v1.md"
    _write_md(rep, md)
    final = rep["FINAL_SYSTEM"]["FINAL_RESULT"]
    print(json.dumps({"wrote": str(outp), "FINAL": final}, indent=2))
    return 0 if final == "EDGE" else 1


if __name__ == "__main__":
    sys.exit(main())
