#!/usr/bin/env python3
"""
Phase-style quick eval for movement-target v1 labels + optional XGB head columns.

Uses snapshots (governed 1m) — same anchor population as phase6 when columns exist.

  python -m calibration.eval_movement_targets_phase_style_v1 --db data/ed_console.db --horizon 5c
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from calibration.db_guard import register_allow_noncanonical_flag, require_canonical_db_target
from calibration.phase6_edge_discovery_governed_v1 import load_rows
from calibration.paths import DEFAULT_DB, ensure_artifacts_dir
def _logloss_bin(y: int, p: float) -> float:
    p = min(1.0 - 1e-9, max(1e-9, float(p)))
    if y == 1:
        return -math.log(p)
    return -math.log(1.0 - p)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--horizon", type=str, default="5c")
    register_allow_noncanonical_flag(ap)
    args = ap.parse_args()
    require_canonical_db_target(args, tool_name="eval_movement_targets_phase_style_v1", write_capable=True)

    raw = str(args.horizon).strip().lower()
    hz = raw if raw.endswith("c") else raw + "c"
    from ml_horizon import PRIMARY_DECISION_HORIZONS

    if hz not in PRIMARY_DECISION_HORIZONS:
        raise SystemExit("horizon must be one of primary slugs: 1c, 5c, 15c, 60c")

    rows, meta = load_rows(args.db.resolve())
    o_move = f"outcome_move_{hz}"
    o_dir = f"outcome_dir_{hz}"
    # Policy evaluation: fusion-derived columns (stack → MC → fuse)
    pu_c = f"fused_dir_up_prob_{hz}"
    pm_c = f"fused_move_prob_{hz}"
    pu_l = f"pred_{hz}_dir_up_prob"
    pm_l = f"pred_{hz}_move_prob"

    def _rget(row, *names):
        for k in names:
            try:
                v = row[k]
            except (KeyError, IndexError, TypeError):
                continue
            if v is not None:
                return float(v)
        return None

    n = len(rows)
    move_labels = [r[o_move] for r in rows if r[o_move] in ("move", "no_move")]
    cov_move = len(move_labels) / n if n else 0.0
    mc = Counter(move_labels)

    vdir = f"valid_dir_{hz}"
    dir_rows = [r for r in rows if r[o_dir] in ("up", "down")]
    dc = Counter(r[o_dir] for r in dir_rows)
    try:
        vd_ones = sum(1 for r in rows if r[vdir] == 1)
    except (KeyError, IndexError, TypeError):
        vd_ones = 0

    out: dict = {
        "meta": meta,
        "horizon": hz,
        "n_snapshots": n,
        "outcome_move_coverage": round(cov_move, 6),
        "outcome_move_counts": dict(mc),
        "outcome_dir_conditional_n": len(dir_rows),
        "outcome_dir_balance": dict(dc),
        "valid_dir_count_1": vd_ones,
    }

    # Move head metrics if predictions present
    ll_m = []
    acc_m = 0
    nm = 0
    for r in rows:
        if r[o_move] not in ("move", "no_move"):
            continue
        p_move = _rget(r, pm_c, pm_l)
        if p_move is None:
            continue
        y = 1 if r[o_move] == "move" else 0
        pred = 1 if p_move >= 0.5 else 0
        if pred == y:
            acc_m += 1
        ll_m.append(_logloss_bin(y, p_move))
        nm += 1
    if nm:
        out["move_head"] = {
            "n_scored": nm,
            "accuracy": round(acc_m / nm, 6),
            "mean_logloss": round(sum(ll_m) / len(ll_m), 6),
        }

    # Dir head on conditional sample
    ll_d = []
    acc_d = 0
    nd = 0
    for r in dir_rows:
        p_up = _rget(r, pu_c, pu_l)
        if p_up is None:
            continue
        y_up = 1 if r[o_dir] == "up" else 0
        pred = 1 if p_up >= 0.5 else 0
        if pred == y_up:
            acc_d += 1
        ll_d.append(_logloss_bin(y_up, p_up))
        nd += 1
    if nd:
        out["dir_head"] = {
            "n_scored": nd,
            "accuracy": round(acc_d / nd, 6),
            "mean_logloss": round(sum(ll_d) / len(ll_d), 6),
        }

    ensure_artifacts_dir()
    outp = ROOT / "data" / f"eval_movement_targets_{hz}_v1.json"
    with open(outp, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(json.dumps(out, indent=2))
    print(f"Wrote {outp}")


if __name__ == "__main__":
    main()
