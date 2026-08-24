#!/usr/bin/env python3
"""
Phase 6.5 — Edge isolation (governed snapshots, frozen protocol, JSON report).

Population matches phase6 anchor-governed rows with full outcomes + pts.
Per-horizon analysis uses rows with non-null pred_{H}_* triple and valid probabilities.

  python -m calibration.phase65_edge_isolation_v1 --db data/ed_console.db
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from calibration.paths import DEFAULT_DB, ensure_artifacts_dir

# Import governed loader from phase6 (same population contract)
from calibration.phase6_edge_discovery_governed_v1 import HORIZONS, load_rows, _session_bucket


# ── Frozen protocol (Phase 6.5) ─────────────────────────────────────────────
FROZEN = {
    "governed_predicate": (
        "timeframe='1m' AND COALESCE(horizon_outcome_schema_version,3)=3 AND "
        "outcome_1c..outcome_60c AND outcome_*_pts all NOT NULL AND "
        "EXISTS price_bars_1m bar anchor at ts_utc (same as phase6 load_rows)"
    ),
    "label_definitions": "outcome_{H} in {up,down,flat} — canonical BAR_ANCHOR_V1 bar-close labels",
    "horizons_analyzed": [h[3] for h in HORIZONS],
    "prediction_surface": "pred_{H}_up_prob, pred_{H}_down_prob, pred_{H}_flat_prob all NOT NULL, finite, non-negative",
    "prob_sanity": "sum(pred_u+pred_d+pred_f) within [0.998, 1.002] OR empirical 3dp rounding tolerance",
    "baselines": [
        "always_up — predict class up",
        "always_down — predict class down",
        "always_flat — predict class flat",
        "random_uniform — per-row uniform draw over {up,down,flat} seed derived from row index + horizon",
        "prior_majority — predict modal class of y_true in the evaluated row set (in-slice; optimistic control)",
        "flat_majority_alias — identical to always_flat for 3-class directional accuracy",
    ],
    "metrics": [
        "n",
        "class_balance",
        "accuracy",
        "balanced_accuracy",
        "per_class_precision_recall_f1",
        "confusion_matrix",
        "log_loss",
        "brier_multiclass",
        "mean_max_prob",
        "entropy_mean",
        "directional_hit_long_proxy",
        "directional_hit_short_proxy",
        "delta_accuracy_vs_always_up",
        "delta_accuracy_vs_always_down",
        "delta_accuracy_vs_random",
        "delta_accuracy_vs_prior_majority",
    ],
    "min_n_global": 500,
    "min_n_slice": 200,
    "min_n_interaction": 100,
    "min_n_ticker_thin": 50,
    "is_fraction": 0.70,
    "oos_fraction": 0.30,
    "stability": "compare accuracy older_half vs recent_half by median ts_utc within slice; flag if recent < older - 0.03",
    "multiple_comparison": "Bonferroni alpha=0.05 on slice-level primary tests (one-sided acc > prior); m = counted eligible slice-horizon cells",
    "confidence_buckets": "pred_confidence TEXT: low | medium | high | NULL→unknown",
    "session_buckets": "derived from market_session + session_bucket via phase6 _session_bucket",
    "regime_buckets": "regime_primary or 'unknown'",
    "vol_buckets": "tertiles of realized_vol among non-null in analyzed population per horizon",
    "time_windows": ["full", "older_median_half", "recent_median_half", "is_train", "oos_test"],
    "accept_slice_requires": [
        "n >= min_n_slice",
        "accuracy_model > accuracy_prior_majority",
        "accuracy_model > accuracy_always_up",
        "accuracy_model > accuracy_always_down",
        "accuracy_model > mean(random_accuracy over 20 seeds)",
        "oos_accuracy_model >= oos_accuracy_prior_is_majority",
        "not stability_fail",
    ],
    "reject_if": "any acceptance rule fails",
    "insufficient_if": "n below applicable min_n",
}


def _safe_float(x: Any) -> float | None:
    try:
        v = float(x)
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    except (TypeError, ValueError):
        return None


def _pred_triple_ok(pu: Any, pd: Any, pf: Any) -> bool:
    a, b, c = _safe_float(pu), _safe_float(pd), _safe_float(pf)
    if a is None or b is None or c is None:
        return False
    if a < 0 or b < 0 or c < 0:
        return False
    s = a + b + c
    return 0.997 <= s <= 1.003


def _argmax_class(pu: float, pd: float, pf: float) -> str:
    m = max(pu, pd, pf)
    if pu == m:
        return "up"
    if pd == m:
        return "down"
    return "flat"


def _log_loss(y: str, pu: float, pd: float, pf: float) -> float:
    mp = {"up": pu, "down": pd, "flat": pf}.get(y, 0.0)
    return -math.log(max(mp, 1e-15))


def _brier(y: str, pu: float, pd: float, pf: float) -> float:
    return (1.0 - pu) ** 2 + (0.0 - pd) ** 2 + (0.0 - pf) ** 2 if y == "up" else (
        (0.0 - pu) ** 2 + (1.0 - pd) ** 2 + (0.0 - pf) ** 2 if y == "down" else (0.0 - pu) ** 2 + (0.0 - pd) ** 2 + (1.0 - pf) ** 2
    )


def _multiclass_metrics(
    ys: list[str],
    pred_class: list[str],
    probs: list[tuple[float, float, float]],
) -> dict[str, Any]:
    n = len(ys)
    if n == 0:
        return {"n": 0}
    acc = sum(1 for a, b in zip(ys, pred_class) if a == b) / n
    classes = ["up", "down", "flat"]
    cm = {t: {p: 0 for p in classes} for t in classes}
    for yt, yp in zip(ys, pred_class):
        if yt in cm and yp in cm[yt]:
            cm[yt][yp] += 1
    # per-class recall = diag/col true
    recs = []
    precs = []
    for c in classes:
        tp = cm[c][c]
        fn = sum(cm[c][cc] for cc in classes if cc != c)
        fp = sum(cm[cc][c] for cc in classes if cc != c)
        rec = tp / (tp + fn) if (tp + fn) else float("nan")
        pr = tp / (tp + fp) if (tp + fp) else float("nan")
        recs.append(rec)
        precs.append(pr)
    ba = sum(r for r in recs if r == r) / 3 if recs else float("nan")
    ll = sum(_log_loss(y, *p) for y, p in zip(ys, probs)) / n
    br = sum(_brier(y, *p) for y, p in zip(ys, probs)) / n
    max_probs = [max(p) for p in probs]
    ent = []
    for pu, pd, pf in probs:
        e = 0.0
        for x in (pu, pd, pf):
            if x > 1e-15:
                e -= x * math.log(x)
        ent.append(e)
    # long/short decision proxy: argmax up ≡ long, down ≡ short, flat ≡ no directional bet
    long_hits = sum(1 for y, p in zip(ys, pred_class) if p == "up" and y == "up")
    long_n = sum(1 for p in pred_class if p == "up")
    short_hits = sum(1 for y, p in zip(ys, pred_class) if p == "down" and y == "down")
    short_n = sum(1 for p in pred_class if p == "down")
    return {
        "n": n,
        "accuracy": round(acc, 6),
        "balanced_accuracy": round(ba, 6),
        "confusion_matrix": cm,
        "log_loss_mean": round(ll, 6),
        "brier_mean": round(br, 6),
        "mean_max_prob": round(sum(max_probs) / n, 6),
        "entropy_mean": round(sum(ent) / n, 6),
        "long_proxy_hit_rate": round(long_hits / long_n, 6) if long_n else None,
        "long_proxy_n": long_n,
        "short_proxy_hit_rate": round(short_hits / short_n, 6) if short_n else None,
        "short_proxy_n": short_n,
        "class_balance": dict(Counter(ys)),
    }


def _baseline_accuracies(ys: list[str], n_random_trials: int = 20) -> dict[str, Any]:
    n = len(ys)
    ctr = Counter(ys)
    mode = ctr.most_common(1)[0][0]
    acc_up = sum(1 for y in ys if y == "up") / n
    acc_dn = sum(1 for y in ys if y == "down") / n
    acc_fl = sum(1 for y in ys if y == "flat") / n
    acc_prior = sum(1 for y in ys if y == mode) / n
    rnd_accs = []
    for t in range(n_random_trials):
        rng = random.Random(42 + t * 9973)
        hit = 0
        for y in ys:
            if rng.choice(["up", "down", "flat"]) == y:
                hit += 1
        rnd_accs.append(hit / n)
    return {
        "always_up_accuracy": round(acc_up, 6),
        "always_down_accuracy": round(acc_dn, 6),
        "always_flat_accuracy": round(acc_fl, 6),
        "prior_majority_accuracy": round(acc_prior, 6),
        "prior_majority_class": mode,
        "random_uniform_accuracy_mean": round(sum(rnd_accs) / len(rnd_accs), 6),
        "random_uniform_accuracy_min": round(min(rnd_accs), 6),
    }


def _horizon_spec(hid: str) -> tuple[str, str, str]:
    for ocol, pcol, prefix, h in HORIZONS:
        if h == hid:
            return ocol, pcol, prefix
    raise KeyError(hid)


def _eligible_rows_for_horizon(rows: list[sqlite3.Row], hid: str) -> list[sqlite3.Row]:
    ocol, _pcol, prefix = _horizon_spec(hid)
    pu_k = prefix + "up_prob"
    pd_k = prefix + "down_prob"
    pf_k = prefix + "flat_prob"
    out: list[sqlite3.Row] = []
    for r in rows:
        oc = (r[ocol] or "").strip().lower()
        if oc not in ("up", "down", "flat"):
            continue
        if not _pred_triple_ok(r[pu_k], r[pd_k], r[pf_k]):
            continue
        out.append(r)
    return out


def _build_vectors(mem: list[sqlite3.Row], hid: str) -> tuple[list[str], list[str], list[tuple[float, float, float]]]:
    ocol, _pcol, prefix = _horizon_spec(hid)
    pu_k, pd_k, pf_k = prefix + "up_prob", prefix + "down_prob", prefix + "flat_prob"
    ys: list[str] = []
    pcs: list[str] = []
    probs: list[tuple[float, float, float]] = []
    for r in mem:
        oc = (r[ocol] or "").strip().lower()
        pu, pd, pf = float(r[pu_k]), float(r[pd_k]), float(r[pf_k])
        ys.append(oc)
        pcs.append(_argmax_class(pu, pd, pf))
        probs.append((pu, pd, pf))
    return ys, pcs, probs


def _split_is_oos(mem: list[sqlite3.Row], is_frac: float) -> tuple[list[sqlite3.Row], list[sqlite3.Row]]:
    if not mem:
        return [], []
    srt = sorted(mem, key=lambda r: float(r["ts_utc"]))
    k = int(len(srt) * is_frac)
    k = max(1, min(len(srt) - 1, k))
    return srt[:k], srt[k:]


def _median_split(mem: list[sqlite3.Row]) -> tuple[list[sqlite3.Row], list[sqlite3.Row]]:
    if not mem:
        return [], []
    srt = sorted(mem, key=lambda r: float(r["ts_utc"]))
    mid = len(srt) // 2
    return srt[:mid], srt[mid:]


def _evaluate_slice(
    mem: list[sqlite3.Row],
    hid: str,
    *,
    min_n: int,
    slice_id: str,
) -> dict[str, Any]:
    el = _eligible_rows_for_horizon(mem, hid)
    n = len(el)
    out: dict[str, Any] = {"slice_id": slice_id, "horizon": hid, "n_eligible": n, "verdict": "INSUFFICIENT"}
    if n < min_n:
        return out

    ys, pcs, probs = _build_vectors(el, hid)
    m = _multiclass_metrics(ys, pcs, probs)
    b = _baseline_accuracies(ys)
    is_rows, oos_rows = _split_is_oos(el, FROZEN["is_fraction"])
    ys_is, pcs_is, _ = _build_vectors(is_rows, hid)
    ys_oos, pcs_oos, _ = _build_vectors(oos_rows, hid)
    oos_prior = Counter(ys_is).most_common(1)[0][0] if ys_is else "up"
    oos_prior_acc = sum(1 for y in ys_oos if y == oos_prior) / len(ys_oos) if ys_oos else float("nan")
    oos_model_acc = sum(1 for a, b in zip(ys_oos, pcs_oos) if a == b) / len(ys_oos) if ys_oos else float("nan")

    old, recent = _median_split(el)
    ys_o, pcs_o, _ = _build_vectors(old, hid)
    ys_r, pcs_r, _ = _build_vectors(recent, hid)
    acc_o = sum(1 for a, b in zip(ys_o, pcs_o) if a == b) / len(ys_o) if ys_o else float("nan")
    acc_r = sum(1 for a, b in zip(ys_r, pcs_r) if a == b) / len(ys_r) if ys_r else float("nan")
    stab_fail = (acc_r < acc_o - 0.03) if (len(ys_o) >= 30 and len(ys_r) >= 30) else False

    acc_m = m["accuracy"]
    beats = (
        acc_m > b["prior_majority_accuracy"]
        and acc_m > b["always_up_accuracy"]
        and acc_m > b["always_down_accuracy"]
        and acc_m > b["random_uniform_accuracy_mean"]
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
            "deltas": {
                "acc_minus_prior": round(acc_m - b["prior_majority_accuracy"], 6),
                "acc_minus_always_up": round(acc_m - b["always_up_accuracy"], 6),
                "acc_minus_always_down": round(acc_m - b["always_down_accuracy"], 6),
                "acc_minus_random_mean": round(acc_m - b["random_uniform_accuracy_mean"], 6),
            },
            "oos": {
                "n_is": len(is_rows),
                "n_oos": len(oos_rows),
                "oos_model_accuracy": round(oos_model_acc, 6) if oos_model_acc == oos_model_acc else None,
                "oos_prior_from_is_mode_accuracy": round(oos_prior_acc, 6) if oos_prior_acc == oos_prior_acc else None,
                "oos_prior_class": oos_prior,
            },
            "stability_median_halves": {
                "accuracy_older_half": round(acc_o, 6) if acc_o == acc_o else None,
                "accuracy_recent_half": round(acc_r, 6) if acc_r == acc_r else None,
                "stability_fail_recent_lt_older_minus_0p03": stab_fail,
            },
        }
    )
    return out


def _vol_tertile_bounds(rows: list[sqlite3.Row]) -> tuple[float | None, float | None]:
    xs = sorted(_safe_float(r["realized_vol"]) for r in rows)
    xs = [x for x in xs if x is not None]
    if len(xs) < 30:
        return None, None
    lo = xs[len(xs) // 3]
    hi = xs[(2 * len(xs)) // 3]
    return lo, hi


def _vol_bucket(r: sqlite3.Row, lo: float | None, hi: float | None) -> str:
    v = _safe_float(r["realized_vol"])
    if v is None or lo is None or hi is None:
        return "vol_unknown"
    if v <= lo:
        return "vol_low"
    if v <= hi:
        return "vol_mid"
    return "vol_high"


def _confidence_bucket(r: sqlite3.Row) -> str:
    c = (r["pred_confidence"] or "").strip().lower()
    if c in ("low", "medium", "high"):
        return c
    return "unknown"


def _zone_bucket(r: sqlite3.Row) -> str:
    z = (r["zone"] or "").strip().lower()
    return z if z else "unknown"


def _vwap_bucket(r: sqlite3.Row) -> str:
    v = (r["vwap_side"] or "").strip().lower()
    if v in ("above", "below"):
        return v
    if v:
        return v
    return "unknown"


def _regime_bucket(r: sqlite3.Row) -> str:
    x = (r["regime_primary"] or "").strip().lower()
    return x if x else "unknown"


def run_phase65(db_path: Path) -> dict[str, Any]:
    rows, meta = load_rows(db_path)
    t0 = time.time()

    # duplicate check
    keys = [(str(r["ticker"]), float(r["ts_utc"])) for r in rows]
    dup = len(keys) - len(set(keys))

    out: dict[str, Any] = {
        "frozen_definitions": FROZEN,
        "meta": {**meta, "elapsed_load_s": round(time.time() - t0, 3)},
        "integrity": {
            "governed_rows": len(rows),
            "duplicate_ticker_ts_pairs": dup,
        },
        "population_counts": {},
        "primary_slices": {},
        "interaction_slices": {},
        "summary_counts": {
            "primary_cells_tested": 0,
            "interaction_cells_tested": 0,
            "accepted": 0,
            "rejected": 0,
            "insufficient": 0,
            "inconclusive": 0,
        },
    }

    # Per-horizon global eligible
    pop_h: dict[str, int] = {}
    for hid in FROZEN["horizons_analyzed"]:
        el = _eligible_rows_for_horizon(rows, hid)
        pop_h[hid] = len(el)
    out["population_counts"]["per_horizon_eligible_pred_nonnull"] = pop_h
    out["population_counts"]["global_governed"] = len(rows)

    # Ticker counts (governed)
    by_t: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for r in rows:
        by_t[str(r["ticker"])].append(r)
    out["population_counts"]["per_ticker_governed"] = {k: len(v) for k, v in sorted(by_t.items(), key=lambda x: -len(x[1]))}

    # --- Primary grid ---
    primary: dict[str, Any] = {"by_horizon": {}, "by_ticker": {}, "by_pred_class": {}, "by_session": {}, "by_zone": {}, "by_vwap": {}, "by_regime": {}, "by_vol": {}, "by_confidence": {}, "by_time_window": {}}

    m_slice = FROZEN["min_n_slice"]
    m_int = FROZEN["min_n_interaction"]

    for hid in FROZEN["horizons_analyzed"]:
        res = _evaluate_slice(rows, hid, min_n=FROZEN["min_n_global"], slice_id=f"global|horizon={hid}")
        primary["by_horizon"][hid] = res
        out["summary_counts"]["primary_cells_tested"] += 1
        _bump_verdict(out["summary_counts"], res["verdict"])

    for tkr, mem in by_t.items():
        thin = len(mem) < FROZEN["min_n_ticker_thin"]
        for hid in FROZEN["horizons_analyzed"]:
            res = _evaluate_slice(mem, hid, min_n=m_slice, slice_id=f"ticker={tkr}|horizon={hid}")
            primary["by_ticker"].setdefault(tkr, {})[hid] = {**res, "thin_ticker_governed": thin}

    # predicted class slices (global per horizon)
    for hid in FROZEN["horizons_analyzed"]:
        el = _eligible_rows_for_horizon(rows, hid)
        by_pc: dict[str, list[sqlite3.Row]] = defaultdict(list)
        ocol, _, prefix = _horizon_spec(hid)
        pu_k = prefix + "up_prob"
        pd_k = prefix + "down_prob"
        pf_k = prefix + "flat_prob"
        for r in el:
            pu, pd, pf = float(r[pu_k]), float(r[pd_k]), float(r[pf_k])
            by_pc[_argmax_class(pu, pd, pf)].append(r)
        for pc, mem in by_pc.items():
            sid = f"pred_argmax={pc}|horizon={hid}"
            primary["by_pred_class"].setdefault(hid, {})[pc] = _evaluate_slice(mem, hid, min_n=m_slice, slice_id=sid)

    # session
    by_s: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for r in rows:
        from calibration.phase6_edge_discovery_governed_v1 import _row_market_session

        by_s[_session_bucket(_row_market_session(r), r["session_bucket"])].append(r)
    for sname, mem in by_s.items():
        for hid in FROZEN["horizons_analyzed"]:
            primary["by_session"].setdefault(sname, {})[hid] = _evaluate_slice(
                mem, hid, min_n=m_slice, slice_id=f"session={sname}|horizon={hid}"
            )

    # zone / vwap / regime
    for r in rows:
        pass
    by_z: dict[str, list[sqlite3.Row]] = defaultdict(list)
    by_v: dict[str, list[sqlite3.Row]] = defaultdict(list)
    by_rg: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for r in rows:
        by_z[_zone_bucket(r)].append(r)
        by_v[_vwap_bucket(r)].append(r)
        by_rg[_regime_bucket(r)].append(r)
    for z, mem in by_z.items():
        for hid in FROZEN["horizons_analyzed"]:
            primary["by_zone"].setdefault(z, {})[hid] = _evaluate_slice(mem, hid, min_n=m_slice, slice_id=f"zone={z}|horizon={hid}")
    for v, mem in by_v.items():
        for hid in FROZEN["horizons_analyzed"]:
            primary["by_vwap"].setdefault(v, {})[hid] = _evaluate_slice(mem, hid, min_n=m_slice, slice_id=f"vwap={v}|horizon={hid}")
    for rg, mem in by_rg.items():
        for hid in FROZEN["horizons_analyzed"]:
            primary["by_regime"].setdefault(rg, {})[hid] = _evaluate_slice(mem, hid, min_n=m_slice, slice_id=f"regime={rg}|horizon={hid}")

    # vol tertiles on global eligible per horizon
    for hid in FROZEN["horizons_analyzed"]:
        el = _eligible_rows_for_horizon(rows, hid)
        lo, hi = _vol_tertile_bounds(el)
        by_vol: dict[str, list[sqlite3.Row]] = defaultdict(list)
        for r in el:
            by_vol[_vol_bucket(r, lo, hi)].append(r)
        for vb, mem in by_vol.items():
            primary["by_vol"].setdefault(hid, {})[vb] = _evaluate_slice(
                mem, hid, min_n=m_slice, slice_id=f"vol={vb}|horizon={hid}"
            )

    # confidence
    by_c: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for r in rows:
        by_c[_confidence_bucket(r)].append(r)
    for cname, mem in by_c.items():
        for hid in FROZEN["horizons_analyzed"]:
            primary["by_confidence"].setdefault(cname, {})[hid] = _evaluate_slice(
                mem, hid, min_n=m_slice, slice_id=f"pred_confidence={cname}|horizon={hid}"
            )

    # time windows (median split of governed rows)
    older, recent = _median_split(rows)
    for hid in FROZEN["horizons_analyzed"]:
        primary["by_time_window"].setdefault("older_median_half", {})[hid] = _evaluate_slice(
            older, hid, min_n=m_slice, slice_id=f"time=older_half|horizon={hid}"
        )
        primary["by_time_window"].setdefault("recent_median_half", {})[hid] = _evaluate_slice(
            recent, hid, min_n=m_slice, slice_id=f"time=recent_half|horizon={hid}"
        )

    out["primary_slices"] = primary

    # Count verdicts in primary (excluding nested ticker thin)
    def walk(d: Any, depth: int = 0) -> None:
        if depth > 6:
            return
        if isinstance(d, dict):
            if "verdict" in d and "slice_id" in d:
                v = d["verdict"]
                if v == "ACCEPTED":
                    out["summary_counts"]["accepted"] += 1
                elif v == "REJECTED":
                    out["summary_counts"]["rejected"] += 1
                elif v == "INSUFFICIENT":
                    out["summary_counts"]["insufficient"] += 1
                elif v == "INCONCLUSIVE":
                    out["summary_counts"]["inconclusive"] += 1
            for v in d.values():
                walk(v, depth + 1)

    # reset and recount properly (primary + interaction leaves)
    sc = out["summary_counts"]
    sc.update({"accepted": 0, "rejected": 0, "insufficient": 0, "inconclusive": 0})
    walk(primary)

    # --- Interaction slices (subset) ---
    inter: dict[str, Any] = {
        "ticker_x_horizon": {},
        "ticker_x_regime": {},
        "ticker_x_zone": {},
        "horizon_x_regime": {},
        "direction_x_regime": {},
        "zone_x_vwap": {},
        "session_x_regime": {},
        "session_x_ticker": {},
        "confidence_x_regime": {},
    }

    for tkr, mem in by_t.items():
        for hid in FROZEN["horizons_analyzed"]:
            inter["ticker_x_horizon"].setdefault(tkr, {})[hid] = _evaluate_slice(
                mem, hid, min_n=m_int, slice_id=f"ticker={tkr}×horizon={hid}"
            )
    for tkr, mem in by_t.items():
        for rg, mem2 in _group_by(mem, _regime_bucket).items():
            inter["ticker_x_regime"].setdefault(tkr, {})[rg] = {}
            for hid in FROZEN["horizons_analyzed"]:
                inter["ticker_x_regime"][tkr][rg][hid] = _evaluate_slice(
                    mem2, hid, min_n=m_int, slice_id=f"ticker={tkr}×regime={rg}×H={hid}"
                )
    for tkr, mem in by_t.items():
        for z, mem2 in _group_by(mem, _zone_bucket).items():
            inter["ticker_x_zone"].setdefault(tkr, {})[z] = {}
            for hid in FROZEN["horizons_analyzed"]:
                inter["ticker_x_zone"][tkr][z][hid] = _evaluate_slice(
                    mem2, hid, min_n=m_int, slice_id=f"ticker={tkr}×zone={z}×H={hid}"
                )

    for rg, mem in by_rg.items():
        for hid in FROZEN["horizons_analyzed"]:
            inter["horizon_x_regime"].setdefault(hid, {})[rg] = _evaluate_slice(
                mem, hid, min_n=m_int, slice_id=f"horizon={hid}×regime={rg}"
            )

    for rg, mem in by_rg.items():
        el5 = _eligible_rows_for_horizon(mem, "5c")
        by_pred: dict[str, list[sqlite3.Row]] = defaultdict(list)
        _, _, pfx = _horizon_spec("5c")
        for r in el5:
            pu, pd, pf = float(r[pfx + "up_prob"]), float(r[pfx + "down_prob"]), float(r[pfx + "flat_prob"])
            by_pred[_argmax_class(pu, pd, pf)].append(r)
        for dname, mem2 in by_pred.items():
            inter["direction_x_regime"].setdefault(dname, {})[rg] = _evaluate_slice(
                mem2, "5c", min_n=m_int, slice_id=f"pred_argmax={dname}×regime={rg}×H=5c"
            )

    for z, mem in by_z.items():
        for v, mem2 in _group_by(mem, _vwap_bucket).items():
            inter["zone_x_vwap"].setdefault(z, {})[v] = {}
            for hid in FROZEN["horizons_analyzed"]:
                inter["zone_x_vwap"][z][v][hid] = _evaluate_slice(
                    mem2, hid, min_n=m_int, slice_id=f"zone={z}×vwap={v}×H={hid}"
                )

    for sname, mem in by_s.items():
        for rg, mem2 in _group_by(mem, _regime_bucket).items():
            inter["session_x_regime"].setdefault(sname, {})[rg] = {}
            for hid in FROZEN["horizons_analyzed"]:
                inter["session_x_regime"][sname][rg][hid] = _evaluate_slice(
                    mem2, hid, min_n=m_int, slice_id=f"session={sname}×regime={rg}×H={hid}"
                )

    for sname, mem in by_s.items():
        for tkr, mem2 in _group_by(mem, lambda r: str(r["ticker"])).items():
            inter["session_x_ticker"].setdefault(sname, {})[tkr] = {}
            for hid in FROZEN["horizons_analyzed"]:
                inter["session_x_ticker"][sname][tkr][hid] = _evaluate_slice(
                    mem2, hid, min_n=m_int, slice_id=f"session={sname}×ticker={tkr}×H={hid}"
                )

    for cname, mem in by_c.items():
        for rg, mem2 in _group_by(mem, _regime_bucket).items():
            inter["confidence_x_regime"].setdefault(cname, {})[rg] = {}
            for hid in FROZEN["horizons_analyzed"]:
                inter["confidence_x_regime"][cname][rg][hid] = _evaluate_slice(
                    mem2, hid, min_n=m_int, slice_id=f"confidence={cname}×regime={rg}×H={hid}"
                )

    out["interaction_slices"] = inter
    walk(inter)

    # Bonferroni m = primary slice cells with n>=min_n_slice (approx)
    m_tests = 0
    for hid in FROZEN["horizons_analyzed"]:
        for _tkr, mem in by_t.items():
            if len(_eligible_rows_for_horizon(mem, hid)) >= m_slice:
                m_tests += 1
    alpha_bonf = 0.05 / m_tests if m_tests else None
    out["multiple_comparison"] = {
        "approx_slice_horizon_tests_counted": m_tests,
        "bonferroni_alpha": round(alpha_bonf, 8) if alpha_bonf else None,
        "note": "Automated acceptance uses rule-based accuracy ordering, not raw p-values; Bonferroni alpha shown for reference.",
    }

    # Confidence monotonicity: high > med > low accuracy per 5c
    hid5 = "5c"
    conf_order = ["high", "medium", "low"]
    accs = []
    for c in conf_order:
        cell = primary["by_confidence"].get(c, {}).get(hid5, {})
        accs.append(cell.get("metrics", {}).get("accuracy") if cell.get("verdict") != "INSUFFICIENT" else None)
    mono = None
    if all(a is not None for a in accs):
        mono = accs[0] >= accs[1] >= accs[2]
    out["confidence_ranking_validation"] = {
        "horizon": hid5,
        "accuracy_high_medium_low": accs,
        "weak_monotonic_high_ge_med_ge_low": mono,
        "verdict": "PASS" if mono else ("FAIL" if mono is False else "INSUFFICIENT"),
    }

    # Lists
    accepted, rejected, inconc = [], [], []

    def collect(d: Any) -> None:
        if isinstance(d, dict) and "slice_id" in d and "verdict" in d:
            ent = {"slice_id": d["slice_id"], "horizon": d.get("horizon"), "verdict": d["verdict"], "n": d.get("n_eligible")}
            if d["verdict"] == "ACCEPTED":
                accepted.append(ent)
            elif d["verdict"] == "REJECTED":
                rejected.append(ent)
            elif d["verdict"] == "INCONCLUSIVE":
                inconc.append(ent)
        elif isinstance(d, dict):
            for v in d.values():
                collect(v)

    collect(primary)
    collect(inter)
    out["inventories"] = {
        "accepted": sorted(accepted, key=lambda x: (x.get("horizon") or "", x["slice_id"]))[:200],
        "rejected_sample": sorted(rejected, key=lambda x: (x.get("horizon") or "", x["slice_id"]))[:200],
        "inconclusive_sample": sorted(inconc, key=lambda x: (x.get("horizon") or "", x["slice_id"]))[:200],
        "accepted_total": len(accepted),
        "rejected_total": len(rejected),
        "inconclusive_total": len(inconc),
    }

    # Phase 6.5 binary
    grid_ok = bool(primary["by_horizon"])
    out["phase65_verdict"] = "PASS" if grid_ok else "FAIL"

    return out


def _group_by(mem: list[sqlite3.Row], fn: Callable[[sqlite3.Row], str]) -> dict[str, list[sqlite3.Row]]:
    d: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for r in mem:
        d[fn(r)].append(r)
    return dict(d)


def _bump_verdict(sc: dict[str, int], v: str) -> None:
    if v == "ACCEPTED":
        sc["accepted"] += 1
    elif v == "REJECTED":
        sc["rejected"] += 1
    elif v == "INSUFFICIENT":
        sc["insufficient"] += 1
    elif v == "INCONCLUSIVE":
        sc["inconclusive"] += 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="phase65_edge_isolation_v1", write_capable=False)
    db_path = args.db.resolve()
    if not db_path.is_file():
        print(json.dumps({"error": f"missing db {db_path}"}))
        return 2
    rep = run_phase65(db_path)
    ensure_artifacts_dir()
    outp = ROOT / "data" / "phase65_edge_isolation_v1_report.json"
    outp.write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"wrote": str(outp), "phase65_verdict": rep.get("phase65_verdict"), "inventories": rep.get("inventories", {}).get("accepted_total")}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
