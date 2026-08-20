#!/usr/bin/env python3
"""RC-436 / RC-435 consequence: measure live abstain reach across active artifacts.

Reproduce:
  python ./tools/measure_rc435_abstain_impact.py

Prints counts only — does not mutate artifacts. Exit 0 always when measurement completes.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

WITHHELD_PCT = {
    "dist_call_oi_wall_pct",
    "dist_put_oi_wall_pct",
    "dist_call_vanna_wall_pct",
    "dist_put_vanna_wall_pct",
}


def _triclass_xgb_metas(active: Path) -> list[Path]:
    out: list[Path] = []
    for p in sorted(active.rglob("xgb_*_meta.json")):
        if "_dir_" in p.name or "_move_" in p.name:
            continue
        out.append(p)
    return out


def main() -> int:
    from lstm_data import (
        FEATURES_5M,
        LEGACY_ENCODER_SCHEMA_VERSION,
        LEGACY_V2_FEATURES_5M,
        checkpoint_encoder_schema_version,
    )
    from ml_train import (
        model_feature_wall_distance_cols,
        snapshot_missing_structurally_withheld_wall_distances,
        STRUCTURALLY_WITHHELD_WALL_DISTANCE_COLS,
    )

    active = ROOT / "models" / "active"
    live = {
        "dist_call_oi_wall": None,
        "dist_put_oi_wall": None,
        "dist_call_vanna_wall": None,
        "dist_put_vanna_wall": None,
    }

    xgb_tri = _triclass_xgb_metas(active)
    by_hz: dict[str, int] = defaultdict(int)
    require = 0
    gate_true = 0
    for p in xgb_tri:
        feats = json.loads(p.read_text(encoding="utf-8")).get("features") or []
        if set(feats) & WITHHELD_PCT:
            require += 1
            stem_parts = p.stem.split("_")
            # xgb_SPY_1c_meta -> hz = 1c
            hz = stem_parts[-2] if stem_parts[-1] == "meta" else "unknown"
            by_hz[hz] += 1
        if snapshot_missing_structurally_withheld_wall_distances(live, feats):
            gate_true += 1

    print(
        f"xgb_triclass_active={len(xgb_tri)} require_withheld={require} "
        f"live_gate_true={gate_true} by_hz={dict(sorted(by_hz.items()))}"
    )

    try:
        import torch
    except ImportError:
        print("lstm_transformer=SKIP (torch missing)")
        print(
            "model_feature_wall_distance_cols="
            f"{model_feature_wall_distance_cols()}"
        )
        print(
            "structurally_withheld="
            f"{list(STRUCTURALLY_WITHHELD_WALL_DISTANCE_COLS)}"
        )
        return 0

    serveable_lstm = 0
    lstm_gate = 0
    for pt in sorted(active.rglob("lstm_*.pt")):
        ck = torch.load(pt, map_location="cpu", weights_only=False)
        ver = checkpoint_encoder_schema_version(ck)
        if ver < LEGACY_ENCODER_SCHEMA_VERSION:
            continue
        serveable_lstm += 1
        feats = (
            LEGACY_V2_FEATURES_5M
            if ver == LEGACY_ENCODER_SCHEMA_VERSION
            else FEATURES_5M
        )
        if snapshot_missing_structurally_withheld_wall_distances(live, feats):
            lstm_gate += 1

    serveable_tr = 0
    tr_gate = 0
    for pt in sorted(active.rglob("transformer_*.pt")):
        ck = torch.load(pt, map_location="cpu", weights_only=False)
        ver = checkpoint_encoder_schema_version(ck)
        if ver < LEGACY_ENCODER_SCHEMA_VERSION:
            continue
        serveable_tr += 1
        feats = (
            LEGACY_V2_FEATURES_5M
            if ver == LEGACY_ENCODER_SCHEMA_VERSION
            else FEATURES_5M
        )
        if snapshot_missing_structurally_withheld_wall_distances(live, feats):
            tr_gate += 1

    print(
        f"serveable_lstm={serveable_lstm} live_gate_true={lstm_gate} "
        f"serveable_transformer={serveable_tr} live_gate_true={tr_gate}"
    )
    print(
        "model_feature_wall_distance_cols="
        f"{model_feature_wall_distance_cols()}"
    )
    print(
        "structurally_withheld="
        f"{list(STRUCTURALLY_WITHHELD_WALL_DISTANCE_COLS)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
