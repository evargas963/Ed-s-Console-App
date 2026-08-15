"""
Movement-target v2: per-horizon thresholds from empirical percentiles (JSON contract).

Canonical file: calibration/movement_target_thresholds_by_horizon_v1.json

Generate / refresh with:
  python tools/select_movement_thresholds_percentile_v1.py --db data/ed_console.db

Legacy ATR blend (movement_target_threshold_v1.json) is used only as fallback when
a horizon is missing from the by-horizon file.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent
BY_HORIZON_PATH = _ROOT / "calibration" / "movement_target_thresholds_by_horizon_v1.json"
LEGACY_ATR_PATH = _ROOT / "calibration" / "movement_target_threshold_v1.json"


def load_movement_thresholds_by_horizon_v1(path: Path | None = None) -> dict[str, Any]:
    p = path or BY_HORIZON_PATH
    if not p.is_file():
        return {"version": 2, "horizons": {}}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def load_legacy_atr_params(path: Path | None = None) -> dict[str, Any]:
    p = path or LEGACY_ATR_PATH
    if not p.is_file():
        return {
            "atr_multiplier": 0.55,
            "min_fraction_of_anchor": 0.0008,
        }
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def movement_threshold_pts_v1(
    anchor_close: float,
    atr: float | None,
    params: dict[str, Any] | None = None,
) -> float:
    """Fallback row-wise threshold when per-horizon JSON missing (ATR × fraction blend)."""
    pr = params or load_legacy_atr_params()
    ac = float(anchor_close)
    if ac <= 0:
        return 1e-9
    floor_frac = float(pr.get("min_fraction_of_anchor", 0.0005))
    k_atr = float(pr.get("atr_multiplier", 0.5))  # fake-default-ok: config parameter (ATR multiplier from the threshold policy), not data absence
    t_pct = ac * floor_frac
    t_atr = 0.0
    if atr is not None:
        try:
            a = float(atr)
            if a > 0:
                t_atr = a * k_atr
        except (TypeError, ValueError):
            pass
    return max(t_pct, t_atr, 1e-9)


def threshold_move_pts_for_slug(
    slug: str,
    *,
    anchor_close: float,
    atr: float | None,
    cfg: dict[str, Any] | None = None,
) -> float:
    """
    Per-horizon threshold (points) for |Δclose|. Uses JSON horizons[slug].threshold_move_pts
    when set; else legacy ATR fallback for that row.
    """
    cfg = cfg or load_movement_thresholds_by_horizon_v1()
    hz = (cfg.get("horizons") or {}).get(slug) or {}
    raw = hz.get("threshold_move_pts")
    if raw is not None:
        try:
            v = float(raw)
            if v > 0:
                return v
        except (TypeError, ValueError):
            pass
    return movement_threshold_pts_v1(anchor_close, atr, load_legacy_atr_params())


def invalid_for_dir_target(slug: str, cfg: dict[str, Any] | None = None) -> bool:
    cfg = cfg or load_movement_thresholds_by_horizon_v1()
    hz = (cfg.get("horizons") or {}).get(slug) or {}
    return bool(hz.get("invalid_for_dir_target", False))


def directional_and_move_labels_v2(
    pts_move: float,
    threshold_pts: float,
    *,
    dir_allowed: bool,
) -> tuple[str | None, str, int]:
    """
    Returns (outcome_dir, outcome_move, valid_dir) with valid_dir ∈ {0,1}.
    When invalid_for_dir_target for horizon: valid_dir always 0, outcome_dir always None.
    """
    thr = max(float(threshold_pts), 1e-9)
    pm = float(pts_move)
    omove = "move" if abs(pm) >= thr else "no_move"
    if not dir_allowed:
        return None, omove, 0
    if abs(pm) < thr:
        return None, omove, 0
    if pm > 0:
        return "up", omove, 1
    if pm < 0:
        return "down", omove, 1
    return None, omove, 0


# Back-compat aliases (tests / older imports)
def directional_and_move_labels_v1(
    pts_move: float,
    threshold_pts: float,
) -> tuple[str | None, str]:
    d, m, v = directional_and_move_labels_v2(
        pts_move, threshold_pts, dir_allowed=True
    )
    return d, m


def load_movement_threshold_params_v1(path: Path | None = None) -> dict[str, Any]:
    return load_legacy_atr_params(path)

