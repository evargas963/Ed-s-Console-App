"""
Universal horizon outcome standard (Issue 3 forward + Issue 4 anchor — bar-based, reproducible).

Contract (schema version 3, BAR_ANCHOR_V1):
- Anchor at snapshot time T: **close** of the last fully completed canonical 1m bar such that
  bar_end_ts_utc <= T (from price_bars_1m only; never snapshots.spot or quote-derived values).
- Forward reference at T + N minutes: **close** of the canonical 1m bar whose period
  **starts** at floor((T + N*60) / 60) * 60 (UTC epoch seconds) — unchanged from Issue 3.
- Bar length: 60 seconds (canonical 1m timeframe only).
- Classification: outcome_Nc = classify_direction(forward_close - anchor_close, anchor_close).

Authoritative price series: persisted rows in price_bars_1m (Schwab 1m history + live accumulator).
"""
from __future__ import annotations

import math

# Bump if the mathematical contract changes (never mix semantics under same version).
# 2 = Issue 3 bar-forward + spot anchor (invalidated — do not use).
HORIZON_OUTCOME_SCHEMA_BAR_V1: int = 2
# 3 = Issue 4 bar-forward + bar close anchor (last completed bar end <= ts_utc).
HORIZON_OUTCOME_SCHEMA_BAR_ANCHOR_V1: int = 3

# Source tag stored on price_bars_1m rows.
AUTHORITATIVE_1M_SOURCE: str = "schwab_1m_accumulator_sqlite"
# Interior gap repair: linear interpolation between real Schwab bars on the 60s grid (canonical_1m_grid closure).
SYNTHETIC_INTERIOR_GRID_REPAIR_V1: str = "synthetic_interior_grid_repair_v1"
SYNTHETIC_EDGE_CARRY_V1: str = "synthetic_edge_carry_v1"
# One bar per ticker: bar_end = floor(min(ts_utc)/60)*60 so BAR_ANCHOR exists for pre-history snapshots.
SYNTHETIC_ANCHOR_COVERAGE_PAD_V1: str = "synthetic_anchor_coverage_pad_v1"

# outcome column -> exact forward offset in minutes (canonical 1m clock).
OUTCOME_HORIZON_MINUTES: dict[str, int] = {
    "outcome_1c": 1,
    "outcome_5c": 5,
    "outcome_15c": 15,
    "outcome_60c": 60,
}

# (direction column, points column, forward minutes) — primary product horizons only (Phase 3 C2).
OUTCOME_BAR_SPECS: tuple[tuple[str, str, int], ...] = (
    ("outcome_1c", "outcome_1c_pts", 1),
    ("outcome_5c", "outcome_5c_pts", 5),
    ("outcome_15c", "outcome_15c_pts", 15),
    ("outcome_60c", "outcome_60c_pts", 60),
)

def _outcome_slug(odir: str) -> str:
    return odir[8:] if odir.startswith("outcome_") else odir


# Movement-target v2: dir, move, valid_dir mask, canonical threshold_move, legacy thr_pts duplicate, minutes, slug
OUTCOME_MOVEMENT_V1_SPECS: tuple[tuple[str, str, str, str, str, int, str], ...] = tuple(
    (
        f"outcome_dir_{_outcome_slug(odir)}",
        f"outcome_move_{_outcome_slug(odir)}",
        f"valid_dir_{_outcome_slug(odir)}",
        f"threshold_move_{_outcome_slug(odir)}",
        f"outcome_move_thr_pts_{_outcome_slug(odir)}",
        int(n_min),
        _outcome_slug(odir),
    )
    for odir, _opt, n_min in OUTCOME_BAR_SPECS
)

MOVEMENT_TARGET_SLUGS: tuple[str, ...] = tuple(s[6] for s in OUTCOME_MOVEMENT_V1_SPECS)

# Back-compat: (outcome_dir, outcome_move, legacy_thr_pts_col, n_min)
OUTCOME_DIRECTIONAL_SPECS: tuple[tuple[str, str, str, int], ...] = tuple(
    (s[0], s[1], s[4], s[5]) for s in OUTCOME_MOVEMENT_V1_SPECS
)

OUTCOME_DIR_HORIZON_MINUTES: dict[str, int] = {s[0]: s[5] for s in OUTCOME_MOVEMENT_V1_SPECS}
OUTCOME_MOVE_HORIZON_MINUTES: dict[str, int] = {s[1]: s[5] for s in OUTCOME_MOVEMENT_V1_SPECS}
VALID_DIR_HORIZON_MINUTES: dict[str, int] = {s[2]: s[5] for s in OUTCOME_MOVEMENT_V1_SPECS}
THRESHOLD_MOVE_HORIZON_MINUTES: dict[str, int] = {s[3]: s[5] for s in OUTCOME_MOVEMENT_V1_SPECS}


def forward_bar_start_utc(ts_snapshot: float, n_minutes: int) -> float:
    """UTC start (epoch seconds) of the 1m bar whose close labels the T+N horizon."""
    target_ts = float(ts_snapshot) + n_minutes * 60.0
    return math.floor(target_ts / 60.0) * 60.0


def bar_complete_by_utc(bar_start_ts_utc: float, ts_now_utc: float) -> bool:
    """True iff the 1m bar that starts at bar_start_ts_utc has finished."""
    return float(ts_now_utc) >= float(bar_start_ts_utc) + 60.0


def expected_bar_end_utc(bar_start_ts_utc: float) -> float:
    return float(bar_start_ts_utc) + 60.0


def pts_move_anchor_close_to_forward_close(anchor_close: float, forward_close: float) -> float:
    return float(forward_close) - float(anchor_close)
