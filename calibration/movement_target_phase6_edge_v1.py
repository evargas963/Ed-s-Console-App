#!/usr/bin/env python3
"""
Phase 6 — Edge discovery for movement-target strategy: gate on pred_move, direction from dir head.

Uses same governed population as phase6 (anchor-filtered). PnL uses outcome_{H} (3-class) +
outcome_{H}_pts when the model elects a directional trade (pred_move >= 0.5); flat when no trade.

  python -m calibration.movement_target_phase6_edge_v1 --db data/ed_console.db
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from calibration.analyze_phase4 import _directional_pnl
from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from calibration.movement_target_eval_common_v1 import HORIZONS_MV, pred_dir_keys, pred_move_keys, rget_float
from calibration.paths import DEFAULT_DB, ensure_artifacts_dir
from calibration.phase6_edge_discovery_governed_v1 import (
    _bootstrap_mean_diff,
    _mean,
    _win_rate,
    load_rows,
)

RNG_SEED = 42


def _pred_signal_movement(r: Any, hz: str) -> str | None:
    pm_c, pn_c, pm_l, pn_l = pred_move_keys(hz)
    pu_c, pd_c, pu_l, pd_l = pred_dir_keys(hz)
    pm = rget_float(r, pm_c, pm_l)
    pn = rget_float(r, pn_c, pn_l)
    if pm is None or pn is None:
        return None
    sm = pm + pn
    if sm > 0:
        pm = pm / sm
    if pm < 0.5:
        return "flat"
    pu = rget_float(r, pu_c, pu_l)
    pd_ = rget_float(r, pd_c, pd_l)
    if pu is None or pd_ is None:
        return None
    if pu >= pd_:
        return "long"
    return "short"


def horizon_metrics_movement(
    members: list[Any],
    ocol: str,
    pcol: str,
    hz: str,
) -> dict[str, Any]:
    act: list[float] = []
    long_b: list[float] = []
    short_b: list[float] = []
    rnd_b: list[float] = []
    correct = 0
    n_dir_pred = 0
    for idx, r in enumerate(members):
        oc = r[ocol]
        pt = r[pcol]
        if pt is None or oc is None:
            continue
        sig = _pred_signal_movement(r, hz)
        if sig is None:
            continue
        p_a = _directional_pnl(sig if sig != "flat" else "flat", oc, float(pt))
        p_l = _directional_pnl("long", oc, float(pt))
        p_s = _directional_pnl("short", oc, float(pt))
        if p_a is None or p_l is None or p_s is None:
            continue
        rng_i = random.Random(RNG_SEED + idx + hash(ocol) % 100000)
        rnd = float(p_l) if rng_i.random() < 0.5 else float(p_s)
        act.append(float(p_a))
        long_b.append(float(p_l))
        short_b.append(float(p_s))
        rnd_b.append(float(rnd))
        if sig in ("long", "short"):
            n_dir_pred += 1
            y = (oc or "").strip().lower()
            if sig == "long" and y == "up":
                correct += 1
            elif sig == "short" and y == "down":
                correct += 1

    n = len(act)
    boot_vs_long = _bootstrap_mean_diff(act, long_b) if n >= 2 else {}
    boot_vs_rnd = _bootstrap_mean_diff(act, rnd_b) if n >= 2 else {}
    acc = correct / n_dir_pred if n_dir_pred else float("nan")

    def _r6(x: float) -> float | None:
        return None if x != x or x is None else round(x, 6)

    def _r8(x: float) -> float | None:
        return None if x != x or x is None else round(x, 8)

    return {
        "n": n,
        "n_directional_trades": n_dir_pred,
        "win_rate_model": _r6(_win_rate(act)),
        "win_rate_always_long": _r6(_win_rate(long_b)),
        "mean_ev_model": _r8(_mean(act)),
        "mean_ev_always_long": _r8(_mean(long_b)),
        "directional_accuracy_when_trade": _r6(acc),
        "bootstrap_model_minus_long": boot_vs_long,
        "bootstrap_model_minus_random": boot_vs_rnd,
        "note": "no_trades_or_no_predictions" if n == 0 and n_dir_pred == 0 else None,
    }


def run(db_path: Path) -> dict[str, Any]:
    rows, meta = load_rows(db_path)
    out: dict[str, Any] = {"meta": meta, "strategy_note": "Trade only when pred_move>=0.5; direction from pred_dir_*.", "horizons": {}}
    for hz in HORIZONS_MV:
        ocol, pcol = f"outcome_{hz}", f"outcome_{hz}_pts"
        out["horizons"][hz] = horizon_metrics_movement(rows, ocol, pcol, hz)

    # 5c confidence curve by fusion_dominant_prob (same as phase6)
    ref_h = "5c"
    ocol, pcol = f"outcome_{ref_h}", f"outcome_{ref_h}_pts"
    conf_rows: list[tuple[Any, float]] = []
    for r in rows:
        fp = r["fusion_dominant_prob"]
        if fp is None:
            continue
        conf_rows.append((r, float(fp)))
    conf_rows.sort(key=lambda x: -x[1])
    n_c = len(conf_rows)
    conf_curve: list[dict[str, Any]] = []
    if n_c >= 50:
        for pct in (10, 20, 30, 40, 50, 60, 70, 80, 90, 100):
            k = max(1, int(n_c * pct / 100))
            chunk = [x[0] for x in conf_rows[:k]]
            hm = horizon_metrics_movement(chunk, ocol, pcol, ref_h)
            conf_curve.append({"top_pct": pct, "n": hm["n"], **{x: hm[x] for x in hm if x != "n"}})
    out["confidence_curves_fusion_dominant_top_pct"] = conf_curve

    # max pred_move probability deciles for 5c
    scored: list[tuple[Any, float]] = []
    pm_c, _, pm_l, _ = pred_move_keys(ref_h)
    for r in rows:
        pm = rget_float(r, pm_c, pm_l)
        if pm is None:
            continue
        scored.append((r, pm))
    scored.sort(key=lambda x: -x[1])
    n_s = len(scored)
    move_conf: list[dict[str, Any]] = []
    if n_s >= 50:
        for pct in (10, 20, 30, 50, 70, 100):
            k = max(1, int(n_s * pct / 100))
            ch = [x[0] for x in scored[:k]]
            hm = horizon_metrics_movement(ch, ocol, pcol, ref_h)
            move_conf.append({"top_pct": pct, "n": hm["n"], "mean_ev_model": hm.get("mean_ev_model")})
    out["confidence_curves_pred_move_top_pct_5c"] = move_conf

    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="movement_target_phase6_edge_v1", write_capable=False)
    db_path = args.db.resolve()
    if not db_path.is_file():
        print(json.dumps({"error": f"missing db {db_path}"}))
        return 2
    rep = run(db_path)
    ensure_artifacts_dir()
    outp = ROOT / "data" / "movement_target_phase6_edge_v1.json"
    outp.write_text(json.dumps(rep, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"wrote": str(outp)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
