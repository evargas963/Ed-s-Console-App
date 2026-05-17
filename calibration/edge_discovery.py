#!/usr/bin/env python3
"""
Enumerate marginal and key 2D slices on trusted+anchored+labeled calibration rows.

  python -m calibration.edge_discovery
  python -m calibration.edge_discovery --db data/calibration_accumulation_validation.db

Writes data/calibration_edge_discovery_report.json (full tables, no summarization).
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import random
import sqlite3
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

SignalFn = Callable[[dict[str, Any]], str]

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from calibration.anchor_audit import snapshot_has_bar_anchor
from calibration.analyze_phase3 import _brier_triplet, _canonical_prob_triplet, _load_json_col
from calibration.analyze_phase4 import _directional_pnl
from calibration.edge_validation import _effective_directional_signal
from arch_competition.atomic_io import write_json_file_atomically, write_text_atomically
from calibration.canonical_enforcement import CANONICAL_TIMEFRAME, enforce_calibration_decision_log_only_1m
from calibration.db_guard import enforce_resolved_path, register_allow_noncanonical_flag
from calibration.json_utils import parse_json_mapping
from calibration.paths import DEFAULT_DB
from calibration.schema import ensure_calibration_schema
from calibration.statistical_integrity import (
    MIN_SAMPLES_STATISTICAL,
    bucket_gate,
    verify_edge_discovery_no_numeric_leak,
)
from calibration.trust import TRUSTED_PREDICATE_SQL
from calibration.v2_a1_calibration import axis_reliability_bucket_value
from db_authority import canonical_console_db_path

log = logging.getLogger(__name__)

try:
    from db import configure_sqlite_connection
except ImportError as e:
    log.warning(
        "db.configure_sqlite_connection not available — using no-op stub: %s",
        e,
    )

    def configure_sqlite_connection(conn, **kwargs):
        pass

MIN_N = MIN_SAMPLES_STATISTICAL
AXIS_INVALID = "__invalid__"


def _parse_json_field(value: Any, *, context: str) -> dict[str, Any]:
    return parse_json_mapping(value, context=context)


def _canonical_confidence_bucket(raw: Any) -> str:
    if raw is None:
        return axis_reliability_bucket_value(None)
    text = str(raw).strip().lower()
    if not text:
        return axis_reliability_bucket_value(None)
    if text not in ("high", "medium", "low"):
        return AXIS_INVALID
    return text


def _alignment_state_bucket(raw: Any) -> str:
    if raw is None:
        return axis_reliability_bucket_value(None)
    text = str(raw).strip().upper()
    return text if text else axis_reliability_bucket_value(None)


def _axis_field(row: dict[str, Any], field: str) -> str:
    return axis_reliability_bucket_value(row.get(field))


def _axis_field_lower(row: dict[str, Any], field: str) -> str:
    raw = row.get(field)
    if raw is None:
        return axis_reliability_bucket_value(None)
    text = str(raw).strip().lower()
    return text if text else axis_reliability_bucket_value(None)


def _gated_round(val: float | None, gate_ok: bool) -> float | None:
    return round(val, 6) if (val is not None and gate_ok) else None


def _bootstrap_gated(
    actual: list[float], baseline: list[float], *, gate_ok: bool
) -> dict[str, Any]:
    boot = _bootstrap_delta(actual, baseline) if len(actual) >= 2 else {"n": len(actual)}
    if gate_ok:
        return boot
    return {
        "n": boot.get("n", len(actual)),
        "mean_delta": None,
        "ci95_low": None,
        "ci95_high": None,
    }


def _fusion_top_probs(fj: dict[str, Any]) -> dict[str, float | None]:
    out: dict[str, float | None] = {"fusion_prob_up": None, "fusion_prob_down": None, "fusion_prob_flat": None}
    for k, name in (("prob_up", "fusion_prob_up"), ("prob_down", "fusion_prob_down"), ("prob_flat", "fusion_prob_flat")):
        v = fj.get(k)
        if v is not None:
            try:
                out[name] = float(v)
            except (TypeError, ValueError):
                pass
    return out


def _model_stack_summary(mo: dict[str, Any], *, context: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name in ("xgb", "lstm", "transformer"):
        blk = mo.get(name) or {}
        if isinstance(blk, str):
            blk = _parse_json_field(blk, context=f"{context}:model_outputs.{name}")
        out[f"mo_{name}_prob_up"] = None
        try:
            if blk.get("prob_up") is not None:
                out[f"mo_{name}_prob_up"] = float(blk["prob_up"])
        except (TypeError, ValueError):
            pass
    return out


def _utc_hour(decision_ts_utc: float) -> int:
    return int((float(decision_ts_utc) % 86400.0) // 3600) % 24


def _utc_bucket(h: int) -> str:
    q = h // 6
    lo = q * 6
    return f"utc_{lo:02d}_{lo+5:02d}"


def _session_rth_label(session_bucket: str | None, session_label: str | None) -> str:
    s = (session_bucket or session_label or "").strip().lower()
    if "rth" in s or s == "regular":
        return "rth"
    if "after" in s or "pre" in s or "closed" in s or s:
        return "non_rth_or_unknown"
    return "unknown_session"


def _bootstrap_delta(
    actual: list[float], baseline: list[float], *, n_boot: int = 4000, seed: int = 42
) -> dict[str, Any]:
    if len(actual) != len(baseline) or len(actual) < 2:
        return {"n": len(actual), "mean_delta": None, "ci95_low": None, "ci95_high": None}
    rng = random.Random(seed)
    diffs = [a - b for a, b in zip(actual, baseline)]
    obs = float(statistics.mean(diffs))
    boot: list[float] = []
    n = len(diffs)
    for _ in range(n_boot):
        samp = [diffs[rng.randrange(n)] for _ in range(n)]
        boot.append(float(statistics.mean(samp)))
    boot.sort()
    return {
        "n": n,
        "mean_delta": round(obs, 6),
        "ci95_low": round(boot[int(0.025 * n_boot)], 6),
        "ci95_high": round(boot[int(0.975 * n_boot)], 6),
    }


def load_labeled_rows(db_path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    configure_sqlite_connection(conn)
    ensure_calibration_schema(conn)
    enforce_calibration_decision_log_only_1m(conn)

    rows_raw = conn.execute(
        f"""
        SELECT
          id, decision_ts_utc, ticker,
          session_label, session_bucket,
          zone, vwap_side, nearest_above_dist, nearest_below_dist,
          regime_primary, regime_confidence, vol_regime, vix_bucket,
          model_outputs_json, fusion_json, canonical_json, multi_horizon_json,
          final_signal, call_conviction,
          outcome_5c, outcome_5c_pts
        FROM calibration_decision_log
        WHERE outcome_5c IS NOT NULL AND canonical_timeframe=? AND ({TRUSTED_PREDICATE_SQL})
        """,
        (CANONICAL_TIMEFRAME,),
    ).fetchall()

    rows: list[dict[str, Any]] = []
    excl_anchor = 0
    for r in rows_raw:
        if snapshot_has_bar_anchor(conn, r["ticker"], float(r["decision_ts_utc"])):
            d = dict(r)
            row_id = d.get("id")
            fj = _parse_json_field(
                d.get("fusion_json"), context=f"edge_discovery:row_{row_id}:fusion_json"
            )
            mo = _parse_json_field(
                d.get("model_outputs_json"),
                context=f"edge_discovery:row_{row_id}:model_outputs_json",
            )
            mh = _parse_json_field(
                d.get("multi_horizon_json"),
                context=f"edge_discovery:row_{row_id}:multi_horizon_json",
            )
            cj = _parse_json_field(
                d.get("canonical_json"), context=f"edge_discovery:row_{row_id}:canonical_json"
            )
            align = _alignment_state_bucket(mh.get("alignment_state"))
            fusion_probs = _fusion_top_probs(fj)
            mos = _model_stack_summary(mo, context=f"edge_discovery:row_{row_id}")
            uh = _utc_hour(float(d["decision_ts_utc"]))
            trip = _canonical_prob_triplet(d.get("canonical_json"))
            brier = None
            if trip is not None:
                y5 = (d.get("outcome_5c") or "").strip().lower()
                brier = _brier_triplet(trip[0], trip[1], trip[2], y5)
            ccb = _canonical_confidence_bucket(cj.get("confidence"))

            d["_features"] = {
                **fusion_probs,
                **mos,
                "alignment_state": align,
                "canonical_confidence_bucket": ccb,
                "utc_hour": uh,
                "utc_hour_bucket_6h": _utc_bucket(uh),
                "session_rth_derived": _session_rth_label(d.get("session_bucket"), d.get("session_label")),
                "brier_row": brier,
            }
            rows.append(d)
        else:
            excl_anchor += 1

    conn.close()
    meta = {
        "db": str(db_path.resolve()),
        "ts": time.time(),
        "raw_labeled_trusted": len(rows_raw),
        "labeled_anchored_count": len(rows),
        "excluded_no_bar_anchor": excl_anchor,
    }
    return rows, meta


def row_metrics(d: dict[str, Any], signal_fn: SignalFn | None = None) -> dict[str, Any]:
    oc = d["outcome_5c"]
    pts = d["outcome_5c_pts"]
    fn = signal_fn or _effective_directional_signal
    fs = fn(d)
    p = float(pts) if pts is not None else None
    pnl_a = _directional_pnl(fs, oc, p)
    pnl_l = _directional_pnl("long", oc, p)
    pnl_s = _directional_pnl("short", oc, p)
    pnl_r = None
    if pnl_l is not None and pnl_s is not None:
        pnl_r = 0.5 * (pnl_l + pnl_s)
    win = None
    if pnl_a is not None:
        win = 1 if pnl_a > 0 else 0
    return {
        "outcome_5c_pts": p,
        "effective_signal_for_ev": fs,
        "pnl_actual": pnl_a,
        "pnl_long": pnl_l,
        "pnl_short": pnl_s,
        "pnl_random": pnl_r,
        "win_indicator": win,
        "brier": d["_features"].get("brier_row"),
    }


def aggregate_slice(
    slice_id: str,
    slice_kind: str,
    members: list[dict[str, Any]],
    signal_fn: SignalFn | None = None,
) -> dict[str, Any]:
    mets = [row_metrics(x, signal_fn) for x in members]
    pnls_a = [m["pnl_actual"] for m in mets if m["pnl_actual"] is not None]
    pnls_l = [m["pnl_long"] for m in mets if m["pnl_long"] is not None]
    pnls_s = [m["pnl_short"] for m in mets if m["pnl_short"] is not None]
    pnls_r = [m["pnl_random"] for m in mets if m["pnl_random"] is not None]
    pts = [m["outcome_5c_pts"] for m in mets if m["outcome_5c_pts"] is not None]
    brs = [m["brier"] for m in mets if m["brier"] is not None]
    n = len(members)

    def mean(xs: list[float]) -> float | None:
        return float(statistics.mean(xs)) if xs else None

    ma, ml, mr = mean(pnls_a), mean(pnls_l), mean(pnls_r)
    mb = float(statistics.mean(brs)) if brs else None
    wr = None
    if pnls_a:
        wr = round(sum(1 for x in pnls_a if x > 0) / len(pnls_a), 6)

    paired_a = []
    paired_l = []
    paired_r = []
    for m in mets:
        if m["pnl_actual"] is not None and m["pnl_long"] is not None and m["pnl_random"] is not None:
            paired_a.append(float(m["pnl_actual"]))
            paired_l.append(float(m["pnl_long"]))
            paired_r.append(float(m["pnl_random"]))

    gate_ok = n >= MIN_N
    boot_vs_long = _bootstrap_gated(paired_a, paired_l, gate_ok=gate_ok)
    boot_vs_rnd = _bootstrap_gated(paired_a, paired_r, gate_ok=gate_ok)
    edge_vs_long = (
        gate_ok
        and ma is not None
        and ml is not None
        and ma > ml + 1e-12
        and (boot_vs_long.get("ci95_low") is not None and boot_vs_long["ci95_low"] > 0)
    )
    edge_vs_random = (
        gate_ok
        and ma is not None
        and mr is not None
        and ma > mr + 1e-12
        and (boot_vs_rnd.get("ci95_low") is not None and boot_vs_rnd["ci95_low"] > 0)
    )
    classification = "EDGE" if (edge_vs_long and edge_vs_random) else "NO_EDGE"

    return {
        "slice_id": slice_id,
        "slice_kind": slice_kind,
        "n": n,
        "min_n_gate": MIN_N,
        "gate_sufficient": gate_ok,
        "mean_outcome_5c_pts": _gated_round(mean(pts), gate_ok),
        "mean_ev_actual_final_signal": _gated_round(ma, gate_ok),
        "mean_ev_always_long": _gated_round(ml, gate_ok),
        "mean_ev_always_short": _gated_round(mean(pnls_s), gate_ok),
        "mean_ev_random_long_short": _gated_round(mr, gate_ok),
        "delta_ev_actual_minus_long": _gated_round(
            (ma - ml) if ma is not None and ml is not None else None, gate_ok
        ),
        "delta_ev_actual_minus_random": _gated_round(
            (ma - mr) if ma is not None and mr is not None else None, gate_ok
        ),
        "win_rate_strict_positive": _gated_round(wr, gate_ok) if wr is not None else None,
        "mean_brier": _gated_round(mb, gate_ok),
        "bootstrap_actual_minus_long": boot_vs_long,
        "bootstrap_actual_minus_random": boot_vs_rnd,
        "edge_vs_always_long": edge_vs_long,
        "edge_vs_random": edge_vs_random,
        "classification": classification,
    }


def build_marginal_slices(rows: list[dict[str, Any]], signal_fn: SignalFn | None = None) -> list[dict[str, Any]]:
    dims: list[tuple[str, Callable[[dict[str, Any]], str]]] = [
        ("ticker", lambda r: str(r["ticker"])),
        ("regime_primary", lambda r: _axis_field(r, "regime_primary")),
        ("vol_regime", lambda r: _axis_field(r, "vol_regime")),
        ("vix_bucket", lambda r: _axis_field(r, "vix_bucket")),
        ("session_bucket", lambda r: _axis_field(r, "session_bucket")),
        ("session_rth_derived", lambda r: str(r["_features"]["session_rth_derived"])),
        ("utc_hour_bucket_6h", lambda r: str(r["_features"]["utc_hour_bucket_6h"])),
        ("zone", lambda r: _axis_field(r, "zone")),
        ("vwap_side", lambda r: _axis_field(r, "vwap_side")),
        ("final_signal", lambda r: _axis_field_lower(r, "final_signal")),
        ("call_conviction", lambda r: _axis_field_lower(r, "call_conviction")),
        ("canonical_confidence_bucket", lambda r: str(r["_features"]["canonical_confidence_bucket"])),
        ("alignment_state", lambda r: str(r["_features"]["alignment_state"])),
    ]

    out: list[dict[str, Any]] = []
    for dim_name, fn in dims:
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in rows:
            groups[fn(r)].append(r)
        for val, mem in sorted(groups.items(), key=lambda x: (-len(x[1]), x[0])):
            sid = f"marginal|{dim_name}={val}"
            out.append(aggregate_slice(sid, f"marginal:{dim_name}", mem, signal_fn))
    return out


def build_2d_slices(rows: list[dict[str, Any]], signal_fn: SignalFn | None = None) -> list[dict[str, Any]]:
    pairs = [
        ("ticker", "regime_primary", lambda r: str(r["ticker"]), lambda r: _axis_field(r, "regime_primary")),
        ("ticker", "final_signal", lambda r: str(r["ticker"]), lambda r: _axis_field_lower(r, "final_signal")),
        ("ticker", "alignment_state", lambda r: str(r["ticker"]), lambda r: str(r["_features"]["alignment_state"])),
        (
            "call_conviction",
            "alignment_state",
            lambda r: _axis_field_lower(r, "call_conviction"),
            lambda r: str(r["_features"]["alignment_state"]),
        ),
        ("vol_regime", "vwap_side", lambda r: _axis_field(r, "vol_regime"), lambda r: _axis_field(r, "vwap_side")),
        ("session_rth_derived", "utc_hour_bucket_6h", lambda r: str(r["_features"]["session_rth_derived"]), lambda r: str(r["_features"]["utc_hour_bucket_6h"])),
    ]
    out: list[dict[str, Any]] = []
    for a, b, fa, fb in pairs:
        groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for r in rows:
            groups[(fa(r), fb(r))].append(r)
        for (va, vb), mem in sorted(groups.items(), key=lambda x: (-len(x[1]), x[0])):
            sid = f"2d|{a}={va}|{b}={vb}"
            out.append(aggregate_slice(sid, f"2d:{a}×{b}", mem, signal_fn))
    return out


def feature_importance_naive(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Correlation-style diagnostics: fusion_prob_up vs outcome pts; per-final_signal mean pts."""
    pts_list: list[float] = []
    fp_list: list[float] = []
    for r in rows:
        p = r.get("outcome_5c_pts")
        if p is None:
            continue
        fj = _parse_json_field(
            r.get("fusion_json"), context=f"edge_discovery:row_{r.get('id')}:fusion_json"
        )
        pu = fj.get("prob_up")
        if pu is not None:
            try:
                fp_list.append(float(pu))
                pts_list.append(float(p))
            except (TypeError, ValueError):
                pass
    pearson_n = len(fp_list)
    pearson_gate = bucket_gate(pearson_n, MIN_N)
    corr = None
    if pearson_n >= MIN_N:
        mx = statistics.mean(fp_list)
        my = statistics.mean(pts_list)
        num = sum((a - mx) * (b - my) for a, b in zip(fp_list, pts_list))
        denx = math.sqrt(sum((a - mx) ** 2 for a in fp_list))
        deny = math.sqrt(sum((b - my) ** 2 for b in pts_list))
        if denx > 1e-12 and deny > 1e-12:
            corr = round(num / (denx * deny), 6)

    by_sig: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        p = r.get("outcome_5c_pts")
        if p is None:
            continue
        by_sig[_axis_field_lower(r, "final_signal")].append(float(p))

    return {
        "pearson_n": pearson_n,
        "pearson_sample_gate": pearson_gate,
        "pearson_fusion_prob_up_vs_outcome_5c_pts": corr,
        "mean_outcome_pts_by_final_signal": {k: round(statistics.mean(v), 6) for k, v in sorted(by_sig.items())},
        "note": "Descriptive only; not causal. MHAP/fusion from logged JSON.",
    }


def pick_db_path(explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit
    candidates = [
        canonical_console_db_path(),
        ROOT / "data" / "calibration_accumulation_validation.db",
    ]
    for p in candidates:
        if not p.is_file():
            continue
        conn = sqlite3.connect(str(p))
        n = int(
            conn.execute(
                f"SELECT COUNT(*) FROM calibration_decision_log WHERE outcome_5c IS NOT NULL AND ({TRUSTED_PREDICATE_SQL})"
            ).fetchone()[0]
        )
        conn.close()
        if n >= MIN_N:
            return p
    return ROOT / "data" / "calibration_accumulation_validation.db"


def _row_export(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in rows:
        m = row_metrics(r)
        f = r["_features"]
        row_id = r.get("id")
        fj = _parse_json_field(
            r.get("fusion_json"), context=f"edge_discovery:row_{row_id}:fusion_json"
        )
        mo = _parse_json_field(
            r.get("model_outputs_json"),
            context=f"edge_discovery:row_{row_id}:model_outputs_json",
        )
        xgb = mo.get("xgb")
        lstm = mo.get("lstm")
        trn = mo.get("transformer")
        if isinstance(xgb, str):
            xgb = _parse_json_field(xgb, context=f"edge_discovery:row_{row_id}:model_outputs.xgb")
        if isinstance(lstm, str):
            lstm = _parse_json_field(lstm, context=f"edge_discovery:row_{row_id}:model_outputs.lstm")
        if isinstance(trn, str):
            trn = _parse_json_field(trn, context=f"edge_discovery:row_{row_id}:model_outputs.transformer")
        out.append(
            {
                "id": r.get("id"),
                "ticker": r.get("ticker"),
                "decision_ts_utc": r.get("decision_ts_utc"),
                "outcome_5c": r.get("outcome_5c"),
                "outcome_5c_pts": m.get("outcome_5c_pts"),
                "final_signal_logged": _axis_field_lower(r, "final_signal"),
                "effective_signal_for_ev": m.get("effective_signal_for_ev"),
                "fusion_prob_up": fj.get("prob_up"),
                "fusion_prob_down": fj.get("prob_down"),
                "fusion_prob_flat": fj.get("prob_flat"),
                "mo_xgb_prob_up": xgb.get("prob_up") if isinstance(xgb, dict) else None,
                "mo_lstm_prob_up": lstm.get("prob_up") if isinstance(lstm, dict) else None,
                "mo_transformer_prob_up": trn.get("prob_up") if isinstance(trn, dict) else None,
                "regime_primary": r.get("regime_primary"),
                "vol_regime": r.get("vol_regime"),
                "vix_bucket": r.get("vix_bucket"),
                "session_bucket": r.get("session_bucket"),
                "session_label": r.get("session_label"),
                "session_rth_derived": f.get("session_rth_derived"),
                "utc_hour": f.get("utc_hour"),
                "utc_hour_bucket_6h": f.get("utc_hour_bucket_6h"),
                "zone": r.get("zone"),
                "vwap_side": r.get("vwap_side"),
                "alignment_state": f.get("alignment_state"),
                "canonical_confidence_bucket": f.get("canonical_confidence_bucket"),
                "call_conviction": r.get("call_conviction"),
                "brier_row": m.get("brier"),
                "pnl_actual_effective": m.get("pnl_actual"),
                "pnl_always_long": m.get("pnl_long"),
                "pnl_always_short": m.get("pnl_short"),
                "pnl_random_mix": m.get("pnl_random"),
            }
        )
    return out


def run_discovery(db_path: Path, signal_fn: SignalFn | None = None) -> dict[str, Any]:
    rows, meta = load_labeled_rows(db_path)
    return run_discovery_rows(rows, meta, signal_fn=signal_fn)


def run_discovery_rows(
    rows: list[dict[str, Any]], meta: dict[str, Any], signal_fn: SignalFn | None = None
) -> dict[str, Any]:
    marginal = build_marginal_slices(rows, signal_fn)
    two_d = build_2d_slices(rows, signal_fn)
    all_slices = marginal + two_d

    edge_slices = [s for s in all_slices if s["classification"] == "EDGE"]
    no_edge = [s for s in all_slices if s["classification"] == "NO_EDGE"]

    def sort_ev(s: dict[str, Any]) -> float:
        x = s.get("delta_ev_actual_minus_long")
        return float(x) if x is not None else float("-inf")

    edge_sorted = sorted(edge_slices, key=sort_ev, reverse=True)
    worst = sorted(no_edge, key=sort_ev)[:50]

    marginal_ids = {s["slice_id"] for s in marginal}
    marginal_edge = [s for s in edge_slices if s["slice_id"] in marginal_ids]

    report = {
        "meta": meta,
        "per_row_feature_extract": _row_export(rows),
        "population_notes": {
            "filters": "trusted + canonical 1m + outcome_5c NOT NULL + BAR_ANCHOR_V1",
            "rows_used": len(rows),
            "signal_fn": getattr(signal_fn, "__name__", str(signal_fn)) if signal_fn else "canonical_effective_default",
        },
        "marginal_slice_count": len(marginal),
        "two_d_slice_count": len(two_d),
        "total_slices": len(all_slices),
        "slices_all": all_slices,
        "slices_edge_only": edge_sorted,
        "slices_ranked_worst_delta_vs_long": worst[:20],
        "feature_importance_naive": feature_importance_naive(rows),
        "system_level": {
            "marginal_EDGE_slice_count": len(marginal_edge),
            "any_marginal_EDGE": len(marginal_edge) > 0,
            "count_EDGE": len(edge_slices),
            "count_NO_EDGE": len(no_edge),
            "FINAL_SYSTEM_EDGE": "EDGE" if marginal_edge else "NO_EDGE",
        },
        "marginal_edge_slices": marginal_edge,
    }
    leak_ok = verify_edge_discovery_no_numeric_leak(report)
    report["statistical_integrity"] = {
        "binary_pass": leak_ok,
        "thresholds_reference": (
            "math_probabilities.MIN_SAMPLES_STATISTICAL (30) via calibration.statistical_integrity"
        ),
    }
    return report


def _markdown_table(slices: list[dict[str, Any]], max_rows: int | None = None) -> str:
    lines = [
        "| slice_id | kind | n | mean_ev_actual | mean_ev_long | mean_ev_random | delta_vs_long | delta_vs_random | Brier | class |",
        "|---|---|--:|---:|---:|---:|---:|---:|---|---|",
    ]
    for s in slices[: max_rows or len(slices)]:
        lines.append(
            "| {sid} | {k} | {n} | {a} | {l} | {r} | {dl} | {dr} | {b} | {c} |".format(
                sid=s["slice_id"].replace("|", "\\|")[:80],
                k=s["slice_kind"][:24],
                n=s["n"],
                a=s.get("mean_ev_actual_final_signal"),
                l=s.get("mean_ev_always_long"),
                r=s.get("mean_ev_random_long_short"),
                dl=s.get("delta_ev_actual_minus_long"),
                dr=s.get("delta_ev_actual_minus_random"),
                b=s.get("mean_brier"),
                c=s["classification"],
            )
        )
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=None)
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    db_path = pick_db_path(args.db)
    enforce_resolved_path(
        db_path,
        allow_noncanonical=bool(getattr(args, "allow_noncanonical_db", False)),
        tool_name="calibration.edge_discovery",
        write_capable=False,
    )
    if not db_path.is_file():
        print(json.dumps({"error": f"db not found: {db_path}", "hint": "run python -m calibration.run_production_accumulation_validation"}))
        return 2

    rep = run_discovery(db_path)
    outp = ROOT / "data" / "calibration_edge_discovery_report.json"
    outp.parent.mkdir(parents=True, exist_ok=True)
    # Strip slices_all from stdout copy if huge — write full to json
    to_write = {k: v for k, v in rep.items() if k != "slices_all"}
    to_write["slices_all"] = rep["slices_all"]
    write_json_file_atomically(outp, to_write, indent=2)

    md_path = ROOT / "docs" / "calibration_edge_discovery_v1.md"
    nrows = len(rep.get("per_row_feature_extract") or [])
    md_lines = [
        "# Calibration edge discovery (v1)",
        "",
        "## A. Dataset description",
        "",
        f"- **db:** `{db_path}`",
        f"- **labeled+trusted raw:** {rep['meta'].get('raw_labeled_trusted')}",
        f"- **after anchor filter:** {rep['meta'].get('labeled_anchored_count')}",
        f"- **excluded (no anchor):** {rep['meta'].get('excluded_no_bar_anchor')}",
        f"- **per-row feature rows written:** {nrows} (see JSON `per_row_feature_extract`)",
        "",
        "## B. Full slice table (all slices)",
        "",
        _markdown_table(rep["slices_all"]),
        "",
        "## C. Top EDGE slices (ranked by delta_vs_long; may be empty)",
        "",
        _markdown_table(rep["slices_edge_only"][:5], max_rows=5),
        "",
        "## D. Bottom slices (lowest delta_vs_long, full set)",
        "",
        _markdown_table(
            sorted(
                [s for s in rep["slices_all"] if s.get("delta_ev_actual_minus_long") is not None],
                key=lambda s: float(s["delta_ev_actual_minus_long"]),
            )[:5],
            max_rows=5,
        ),
        "",
        "## E. All slices classified EDGE (full ranked list)",
        "",
        _markdown_table(rep["slices_edge_only"]),
        "",
        "## F. Worst NO_EDGE sample (low delta_vs_long)",
        "",
        _markdown_table(rep["slices_ranked_worst_delta_vs_long"]),
        "",
        "## G. Feature importance (naive)",
        "",
        "```json",
        json.dumps(rep["feature_importance_naive"], indent=2),
        "```",
        "",
        "## H. Failure modes",
        "",
        "- **Effective EV** uses `effective_signal_for_ev` (canonical dominant class when `final_signal=wait`).",
        "- **Dominant class is always `up` in this build** (fusion probs ~0.36/0.35/0.28) → effective policy matches **always-long** on every row → `delta_vs_long=0` for all slices.",
        "- **EDGE classification** additionally requires bootstrap CI of (actual−long) > 0 — never satisfied when means are identical.",
        "- **Random baseline** mean is 0 while outcome mix varies → positive `delta_vs_random` without incremental alpha vs long.",
        "",
        "## I. FINAL (system-level)",
        "",
        f"- **FINAL:** `{rep['system_level']['FINAL_SYSTEM_EDGE']}`",
        f"- **marginal EDGE slices found:** {rep['system_level']['any_marginal_EDGE']}",
        "",
    ]
    write_text_atomically(md_path, "\n".join(md_lines))

    final = rep["system_level"]["FINAL_SYSTEM_EDGE"]
    leak_ok = bool((rep.get("statistical_integrity") or {}).get("binary_pass"))
    print(
        json.dumps(
            {
                "wrote_json": str(outp),
                "wrote_md": str(md_path),
                "FINAL": final,
                "statistical_integrity_pass": leak_ok,
            },
            indent=2,
        )
    )
    if not leak_ok:
        return 3
    return 0 if final == "EDGE" else 1


if __name__ == "__main__":
    sys.exit(main())
