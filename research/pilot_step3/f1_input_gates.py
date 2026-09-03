"""F1 S3 — input gates and label-quality reporting for the v2 triple-barrier labeler.

Three gates, all fail-closed, all by EXPLICIT membership (never complement —
drift-audit classification rule, learned from the F-4 miscount):

1. Bar-source gate: the ATR window, the entry bar, and every bar the walk can
   touch must carry a KNOWN-REAL source tag. Known-synthetic tags withhold the
   candidate; UNKNOWN tags also withhold (a bar of unproven provenance is not
   evidence). Rates are reported, never silently dropped.
2. Greeks era floor: any greeks-derived feature must postdate epoch
   1784502281 (2026-07-19T23:04:41Z, commit f6efeebe — charm sign + spot
   authority + gamma sanitization all landed there) unless explicitly rebuilt
   from the archived chain JSON through the modern sanitizer.
3. Two-sided permutation verdict: a shuffled-label control must land WITHIN
   ±tol of chance. Above = leakage STOP; below = anti-signal STOP (the
   one-sided verdict that blessed anti-signal is the Round-2 F-finding).

Plus `build_label_quality_report`: per-ticker class balance, withheld-reason
histogram, cost-floor and synthetic-withhold rates — runs BEFORE any model
ingests a label.
"""

from __future__ import annotations

import random
from typing import Sequence

from .data_loader import Bar1m
from .event_generation import PilotEvent
from .labeling import (
    F1_COST_FLOOR_BP_DEFAULT,
    TripleBarrierResult,
    _f1_withheld,
    force_flat_ts_utc_f1_v2,
    label_event_cell_f1_v2,
)

# Epoch 1784502281 = 2026-07-19T23:04:41Z, commit f6efeebe ("Land terrain
# pipeline, single spot authority, and institutional gate ratchet"): charm
# sign fix (RC-2/3), spot authority (RC-14/15/16), and greek sanitization
# (gamma_is_plausible) in ONE commit. Rows before it carry point-in-time
# corrupted greeks forever unless rebuilt from option_chain_json.
F1_GREEKS_ERA_FLOOR_TS_UTC: float = 1784502281.0

F1_REAL_BAR_SOURCES: frozenset[str] = frozenset(
    {"schwab_1m_accumulator_sqlite", "schwab_pricehistory"}
)
F1_SYNTHETIC_BAR_SOURCES: frozenset[str] = frozenset(
    {
        "synthetic_interior_grid_repair_v1",
        "synthetic_edge_carry_v1",
        "gap_fill_canonical_1m_grid_v1",
    }
)

# ATR-14 warm-up: Wilder needs 14 completed true ranges before T-1.
_ATR_WINDOW_BARS = 15

# Withheld reasons attributable to the bar-source gate (for report rates).
_BAR_SOURCE_WITHHELD_REASONS: tuple[str, str] = (
    "synthetic_bar_in_window",
    "unknown_bar_source_in_window",
)


def classify_bar_source(source: str | None) -> str:
    """'real' | 'synthetic' | 'unknown' — explicit membership on BOTH sets."""
    if source in F1_REAL_BAR_SOURCES:
        return "real"
    if source in F1_SYNTHETIC_BAR_SOURCES:
        return "synthetic"
    return "unknown"


def _candidate_window_indices(bars: list[Bar1m], ev: PilotEvent) -> tuple[int, int] | None:
    """[lo, hi) index span the labeler can read for this event: the ATR window
    through the last same-session bar at/after the force-flat instant."""
    i_ent = ev.signal_bar_index + 1
    if i_ent >= len(bars):
        return None
    lo = max(0, ev.signal_bar_index - _ATR_WINDOW_BARS)
    entry_ts = float(bars[i_ent].bar_start_ts_utc)
    ff_ts = force_flat_ts_utc_f1_v2(entry_ts)
    hi = i_ent
    while hi < len(bars):
        b_start = float(bars[hi].bar_start_ts_utc)
        hi += 1
        if ff_ts is not None and b_start >= ff_ts:
            break
    return lo, hi


def gated_label_event_cell_f1(
    bars: list[Bar1m],
    atr_series: Sequence[float | None],
    ev: PilotEvent,
    *,
    stop_atr: float,
    target_atr: float,
    vertical_minutes: int,
    cost_round_trip_bp: float,
    cost_floor_bp: float | None = None,
) -> TripleBarrierResult:
    """Bar-source gate, then delegate to label_event_cell_f1_v2 unchanged."""
    span = _candidate_window_indices(bars, ev)
    if span is not None:
        lo, hi = span
        n_synth = 0
        n_unknown = 0
        for b in bars[lo:hi]:
            kind = classify_bar_source(b.source)
            if kind == "synthetic":
                n_synth += 1
            elif kind == "unknown":
                n_unknown += 1
        if n_synth:
            return _f1_withheld("synthetic_bar_in_window")
        if n_unknown:
            return _f1_withheld("unknown_bar_source_in_window")
    floor = F1_COST_FLOOR_BP_DEFAULT if cost_floor_bp is None else float(cost_floor_bp)
    return label_event_cell_f1_v2(
        bars,
        list(atr_series),
        ev,
        stop_atr=stop_atr,
        target_atr=target_atr,
        vertical_minutes=vertical_minutes,
        cost_round_trip_bp=cost_round_trip_bp,
        cost_floor_bp=floor,
    )


def greeks_era_ok(ts_utc: float, *, rebuilt_from_chain_archive: bool = False) -> bool:
    """True when a greeks-derived value from a row at ts_utc is admissible:
    at/after the era floor, or explicitly rebuilt from the archived chain
    through the modern sanitizer. Pre-floor stored values are NEVER admissible."""
    if rebuilt_from_chain_archive:
        return True
    return float(ts_utc) >= F1_GREEKS_ERA_FLOOR_TS_UTC


# ── Display/explains lane (GEX retirement, commit 9bfea2d5) ──────────────────
# Greeks exposure analytics are DISPLAY/EXPLAINS ONLY: the founding GEX lead
# failed replication on certified greeks (Spearman -0.02, p=0.88) and every
# conditioning translation nulled. A predictive ingest may consume these names
# ONLY under a frozen prereg that explicitly binds the certified greeks channel
# (era floor + recomputed_greeks_ready read gate). Register:
# docs/DERIVED_ANALYTICS_REGISTRY.md "Lane Classification".
DISPLAY_ONLY_GREEKS_FEATURES: frozenset[str] = frozenset(
    {
        "net_gamma", "net_gamma_prev", "net_gamma_rc", "net_delta", "charm_net",
        "vanna_proxy", "gamma_flip", "gex_z",
        "dist_call_gamma_wall", "dist_put_gamma_wall",
        "dist_call_delta_wall", "dist_put_delta_wall",
        "dist_gamma_inflection", "dist_delta_inflection",
        "dist_call_vanna_wall", "dist_put_vanna_wall",
    }
)


def assert_features_off_display_lane(
    feature_names: Sequence[str], *, certified_prereg_id: str | None = None
) -> None:
    """Refuse display-lane greeks names in a predictive feature set unless the
    caller names the frozen prereg that binds the certified greeks channel."""
    hits = sorted(set(feature_names) & DISPLAY_ONLY_GREEKS_FEATURES)
    if hits and not certified_prereg_id:
        raise ValueError(
            "display-lane greeks features in a predictive ingest without a "
            f"certified prereg binding: {hits}"
        )


PERMUTATION_TOL_DEFAULT = 0.06


def permutation_control_verdict(
    observed_balanced_acc: float,
    *,
    chance: float = 1.0 / 3.0,
    tol: float = PERMUTATION_TOL_DEFAULT,
) -> dict[str, bool]:
    """Two-sided shuffled-label verdict. Either STOP is a defect finding, not a FAIL."""
    obs = float(observed_balanced_acc)
    leak = obs > chance + tol
    anti = obs < chance - tol
    return {
        "collapsed_to_chance": (not leak) and (not anti),
        "leakage_stop": leak,
        "anti_signal_stop": anti,
    }


def placebo_permuted_labels(labels: Sequence[str], seed: int) -> list[str]:
    """Seeded multiset-preserving permutation for the placebo arm."""
    out = list(labels)
    random.Random(int(seed)).shuffle(out)
    return out


def placebo_shuffle_train_only(
    labels: Sequence[str], is_train: Sequence[bool], seed: int
) -> list[str]:
    """Placebo shuffle confined to the TRAINING partition (S4 isolation law).

    Labels at holdout/validation positions are returned byte-identical; only
    train-position labels are permuted among themselves (multiset preserved
    within the train slice). Length mismatch raises — a mask that does not
    cover every label is not a partition.
    """
    if len(labels) != len(is_train):
        raise ValueError(
            f"placebo_shuffle_train_only: {len(labels)} labels vs {len(is_train)} mask entries"
        )
    out = list(labels)
    train_idx = [i for i, t in enumerate(is_train) if t]
    permuted = placebo_permuted_labels([out[i] for i in train_idx], seed)
    for i, v in zip(train_idx, permuted, strict=True):
        out[i] = v
    return out


def run_gated_battery(
    bars: list[Bar1m],
    atr_series: Sequence[float | None],
    events: Sequence[PilotEvent],
    *,
    ticker: str,
    stop_atr: float,
    target_atr: float,
    vertical_minutes: int,
    cost_round_trip_bp: float,
    cost_floor_bp: float | None = None,
) -> tuple[list[TripleBarrierResult], dict[str, dict[str, object]]]:
    """S4 battery: every event through the GATED labeler (gate wraps core —
    no path to label_event_cell_f1_v2 exists here), plus the quality report."""
    results = [
        gated_label_event_cell_f1(
            bars,
            atr_series,
            ev,
            stop_atr=stop_atr,
            target_atr=target_atr,
            vertical_minutes=vertical_minutes,
            cost_round_trip_bp=cost_round_trip_bp,
            cost_floor_bp=cost_floor_bp,
        )
        for ev in events
    ]
    return results, build_label_quality_report({ticker: results})


def build_label_quality_report(
    results_by_ticker: dict[str, Sequence[TripleBarrierResult]],
) -> dict[str, dict[str, object]]:
    """Per-ticker class balance + gate-rate report; runs BEFORE model ingestion."""
    report: dict[str, dict[str, object]] = {}
    for ticker, results in sorted(results_by_ticker.items()):
        n = len(results)
        labeled = [r for r in results if r.withheld_reason is None]
        withheld: dict[str, int] = {}
        classes: dict[str, int] = {"WIN": 0, "LOSS": 0, "TIMEOUT": 0, "FORCE_FLAT": 0}
        n_floor = 0
        for r in results:
            if r.withheld_reason is not None:
                withheld[r.withheld_reason] = withheld.get(r.withheld_reason, 0) + 1
                continue
            classes[r.barrier_hit] = classes.get(r.barrier_hit, 0) + 1
            if r.cost_floor_binding:
                n_floor += 1
        n_lab = len(labeled)
        n_synth_wh = sum(
            v for k, v in withheld.items() if k in _BAR_SOURCE_WITHHELD_REASONS
        )
        report[ticker] = {
            "n_candidates": n,
            "n_labeled": n_lab,
            "n_withheld": n - n_lab,
            "class_counts": classes,
            "class_rates": {
                k: (v / n_lab if n_lab else None) for k, v in classes.items()
            },
            "withheld_reasons": dict(sorted(withheld.items())),
            "cost_floor_binding_rate": (n_floor / n_lab) if n_lab else None,
            "bar_source_withheld_rate": (n_synth_wh / n) if n else None,
        }
    return report
