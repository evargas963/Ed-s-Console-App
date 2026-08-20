#!/usr/bin/env python3
"""RC-436 / RC-437 — ENFORCEMENT prove: Path A ML fleet restore is LIVE.

Unlike ``measure_rc435_abstain_impact.py`` (REPORT-ONLY, exit 0 always), this
script exits **1** until the active fleet no longer requires structurally
withheld OI/vanna wall-distance features.

Host Path A acceptance (all must hold before closing RC-436):

  python ./tools/prove_path_a_ml_restore.py
  # exit 0 + RESTORED=1

Optional live stack probe (operator host with running console)::

  python ./tools/prove_path_a_ml_restore.py --require-stack-probs

Do **not** close RC-436 on artifact creation alone — this prove must pass, and
stack probabilities must return on a live withheld-OI tick.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _triclass_xgb_metas(active: Path) -> list[Path]:
    out: list[Path] = []
    for p in sorted(active.rglob("xgb_*_meta.json")):
        if "_dir_" in p.name or "_move_" in p.name:
            continue
        out.append(p)
    return out


def _artifact_gate() -> tuple[bool, list[str]]:
    """True when no active triclass/sequence contract requires withheld distances."""
    from lstm_data import (
        FEATURES_5M,
        LEGACY_ENCODER_SCHEMA_VERSION,
        LEGACY_V2_FEATURES_5M,
        checkpoint_encoder_schema_version,
    )
    from ml_train import (
        STRUCTURALLY_WITHHELD_WALL_DISTANCE_COLS,
        snapshot_missing_structurally_withheld_wall_distances,
        structurally_withheld_wall_distance_feature_names,
        WALL_DISTANCE_COLS,
    )

    lines: list[str] = []
    active = ROOT / "models" / "active"
    live = {c: None for c in STRUCTURALLY_WITHHELD_WALL_DISTANCE_COLS}
    withheld_names = structurally_withheld_wall_distance_feature_names()

    # Contract: live WALL_DISTANCE_COLS must already exclude the four bases.
    still_in_contract = [
        c for c in STRUCTURALLY_WITHHELD_WALL_DISTANCE_COLS if c in WALL_DISTANCE_COLS
    ]
    if still_in_contract:
        lines.append(
            f"WALL_DISTANCE_COLS still includes withheld bases: {still_in_contract}"
        )

    xgb_tri = _triclass_xgb_metas(active)
    require = 0
    gate_true = 0
    for p in xgb_tri:
        feats = json.loads(p.read_text(encoding="utf-8")).get("features") or []
        if set(feats) & withheld_names:
            require += 1
        if snapshot_missing_structurally_withheld_wall_distances(live, feats):
            gate_true += 1
    lines.append(
        f"xgb_triclass_active={len(xgb_tri)} require_withheld={require} "
        f"live_gate_true={gate_true}"
    )

    try:
        import torch
    except ImportError:
        lines.append("lstm_transformer=SKIP (torch missing)")
        ok = (
            not still_in_contract
            and len(xgb_tri) > 0
            and require == 0
            and gate_true == 0
        )
        return ok, lines

    seq_require = 0
    seq_gate = 0
    seq_n = 0
    for pattern in ("lstm_*.pt", "transformer_*.pt"):
        for pt in sorted(active.rglob(pattern)):
            ck = torch.load(pt, map_location="cpu", weights_only=False)
            ver = checkpoint_encoder_schema_version(ck)
            if ver < LEGACY_ENCODER_SCHEMA_VERSION:
                continue
            seq_n += 1
            feats = (
                LEGACY_V2_FEATURES_5M
                if ver == LEGACY_ENCODER_SCHEMA_VERSION
                else FEATURES_5M
            )
            if set(feats) & withheld_names:
                seq_require += 1
            if snapshot_missing_structurally_withheld_wall_distances(live, feats):
                seq_gate += 1
    lines.append(
        f"serveable_seq={seq_n} require_withheld={seq_require} live_gate_true={seq_gate}"
    )

    ok = (
        not still_in_contract
        and len(xgb_tri) > 0
        and require == 0
        and gate_true == 0
        and seq_n > 0
        and seq_require == 0
        and seq_gate == 0
    )
    return ok, lines


def _stack_probs_probe(ticker: str = "SPY") -> tuple[bool, str]:
    """Best-effort live stack probe; fails closed when stack_probs absent."""
    try:
        import ml_predict
    except Exception as exc:  # noqa: BLE001
        return False, f"ml_predict import failed: {type(exc).__name__}: {exc}"

    # Prefer a documented helper if present; otherwise refuse rather than invent.
    probe = getattr(ml_predict, "probe_unified_stack_probs", None)
    if probe is None:
        return False, (
            "no ml_predict.probe_unified_stack_probs — host must prove stack_probs "
            "via the live console /api path or extend this probe; refusing soft-pass"
        )
    try:
        probs = probe(ticker)
    except Exception as exc:  # noqa: BLE001
        return False, f"probe raised {type(exc).__name__}: {exc}"
    if probs is None:
        return False, "stack_probs=None (fleet still dark or rules-only)"
    return True, f"stack_probs keys={list(probs)[:8] if isinstance(probs, dict) else type(probs)}"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--require-stack-probs",
        action="store_true",
        help="Also require a live unified-stack probability probe (host console).",
    )
    p.add_argument("--ticker", default="SPY", help="Ticker for optional stack probe")
    args = p.parse_args(argv)

    ok, lines = _artifact_gate()
    for line in lines:
        print(line)

    if not ok:
        print("NOT_RESTORED=1  # active fleet still requires withheld OI/vanna distances")
        print("RC-436 must remain OPEN. See reports/rc437_oi_vanna_wall_adjudication.md Path A.")
        return 1

    print("ARTIFACTS_RESTORED=1  # no active contract requires withheld *_pct")

    if args.require_stack_probs:
        stack_ok, detail = _stack_probs_probe(args.ticker)
        print(f"stack_probe: {detail}")
        if not stack_ok:
            print("NOT_RESTORED=1  # artifacts clean but live stack_probs not proven")
            return 1
        print("STACK_PROBS_RESTORED=1")

    print("RESTORED=1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
