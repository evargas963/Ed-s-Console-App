"""
Full feature-universe inventory for adaptive similarity research (non-authoritative).

Derives candidate features from SnapshotRow, SignalInput, LSTM/ML feature lists, and
similarity_audit baseline contract. Does not change get_similar_setups or production paths.
"""
from __future__ import annotations

from dataclasses import fields
from typing import Any, Optional

from similarity_audit import baseline_feature_contract_v1

SCHEMA = "similarity_feature_universe_inventory_v1"

CURRENT_BASELINE_STRUCTURAL = frozenset(
    {"zone", "vwap_side", "nearest_above_dist", "nearest_below_dist"}
)
POOL_GATE_FIELDS = frozenset({"ticker", "timeframe", "outcome_1c"})

from ml_horizon import PRIMARY_DECISION_HORIZONS

_OUTCOME_BASE = frozenset(f"outcome_{hz}" for hz in PRIMARY_DECISION_HORIZONS)


def _is_outcome_field(name: str) -> bool:
    if name in _OUTCOME_BASE:
        return True
    if name.startswith("outcome_") and name.endswith("_pts"):
        return True
    return False


def _metadata_field(name: str) -> bool:
    return name in frozenset(
        {
            "snapshot_id",
            "created_at",
            "horizon_outcome_schema_version",
            "outcome_filled",
        }
    )


def _infer_data_type(field_name: str) -> str:
    n = field_name.lower()
    if n in ("rules_pred_agree", "validation_passed", "structure_valid", "probability_valid", "risk_valid"):
        return "boolean"
    if n in ("zone_since_bars", "zone_since_bars_1m", "zone_since_bars_5m", "n_sweeps_today"):
        return "continuous"
    if n in ("zone", "vwap_side", "market_session", "session_bucket", "regime_primary"):
        return "categorical"
    if any(
        x in n
        for x in (
            "_direction",
            "_signal",
            "_bucket",
            "_regime",
            "_mode",
            "_label",
            "_summary",
            "_version",
            "_source",
            "_type",
            "_leader",
            "_laggard",
            "_dominant",
            "_confidence",
            "vs_spy",
            "risk_signal",
        )
    ):
        if "zone" in n and "since" not in n and n not in ("vwap_zone",):
            return "categorical"
    if "pred_" in n and ("prob" in n or n.endswith("_direction")):
        return "continuous"
    if n.endswith("_pct") or n.endswith("_pts") or "dist_" in n or n.endswith("_level"):
        return "continuous"
    if n.endswith("_score") or n.endswith("_breadth") or "gamma" in n or "delta" in n:
        return "continuous"
    return "continuous"


def _similarity_suitability(name: str) -> tuple[str, Optional[str]]:
    if _metadata_field(name):
        return "EXCLUDED_WITH_REASON", "metadata / primary key — not a similarity dimension"
    if _is_outcome_field(name):
        return "EXCLUDED_WITH_REASON", "forward label / target — must not filter similarity pool"
    if name in ("ts_utc", "ts_et"):
        return "EXCLUDED_WITH_REASON", "temporal ordering / replay cutoff — handled outside feature matching"
    if name in POOL_GATE_FIELDS:
        return "POOL_MEMBERSHIP", "cohort gate (Issue 19) — not a tiered structural filter"
    if name in CURRENT_BASELINE_STRUCTURAL:
        return "CURRENT_BASELINE_FEATURES", None
    if name.startswith("pred_") or name in (
        "prediction_direction",
        "prediction_dominant_prob",
        "fusion_dominant",
        "fusion_dominant_prob",
        "fusion_prob_down",
        "fusion_prob_flat",
        "fusion_prob_up",
        "xgb_dominant",
        "lstm_dominant",
        "transformer_dominant",
    ):
        return "HISTORICALLY_USABLE_CANDIDATES", (
            "stored at snapshot time; similarity use risks circularity with empirical labels — shadow/exploratory only"
        )
    if name in ("rules_signal", "combined_signal", "rules_entry", "rules_stop", "rules_target", "call_target2"):
        return "HISTORICALLY_USABLE_CANDIDATES", (
            "trade scaffolding; may correlate with outcomes — SOFT_WEIGHT / REGIME_DEPENDENT in shadow only"
        )
    return "HISTORICALLY_USABLE_CANDIDATES", None


def _signal_input_only_fields() -> set[str]:
    from db import SnapshotRow
    from signal_types import SignalInput

    snap = {f.name for f in fields(SnapshotRow)}
    sig = {f.name for f in fields(SignalInput)}
    return sig - snap


def _lstm_feature_rows(snap_names: set[str]) -> list[dict[str, Any]]:
    from lstm_data import FEATURES_1M, FEATURES_5M

    rows = []
    for fname in sorted(set(FEATURES_1M) | set(FEATURES_5M)):
        on_snap = fname in snap_names
        rows.append(
            {
                "feature_name": fname,
                "source_module": "lstm_data",
                "source_field": fname,
                "historically_available_for_similarity": "yes" if on_snap else "no",
                "replay_safe": "yes" if on_snap else "no",
                "data_type": _infer_data_type(fname),
                "currently_used_in_similarity": "yes" if fname in CURRENT_BASELINE_STRUCTURAL else "no",
                "reason_if_excluded_from_search": None
                if on_snap
                else "not persisted on SnapshotRow — live stream / derived offline only unless added to DB",
                "similarity_suitability_caution": None,
                "partition_hint": "HISTORICALLY_USABLE_CANDIDATES"
                if on_snap
                else "LIVE_ONLY_OR_NOT_REPLAY_SAFE",
                "present_in_attached_db": None,
            }
        )
    return rows


def _partition_entries(entries: list[dict[str, Any]]) -> dict[str, Any]:
    historic: set[str] = set()
    live_only: set[str] = set()
    excluded: set[str] = set()

    for e in entries:
        name = e["feature_name"]
        ph = e.get("partition_hint") or ""

        if ph == "EXCLUDED_WITH_REASON" or _metadata_field(name) or _is_outcome_field(name):
            excluded.add(name)
            continue
        if name in ("ts_utc", "ts_et"):
            excluded.add(name)
            continue
        if ph in ("POOL_MEMBERSHIP", "CURRENT_BASELINE_FEATURES"):
            continue
        if ph == "LIVE_ONLY_OR_NOT_REPLAY_SAFE":
            live_only.add(name)
            continue
        if e["historically_available_for_similarity"] == "no":
            live_only.add(name)
            continue
        if name in CURRENT_BASELINE_STRUCTURAL:
            continue
        historic.add(name)

    return {
        "CURRENT_BASELINE_FEATURES": sorted(
            set(CURRENT_BASELINE_STRUCTURAL) | POOL_GATE_FIELDS
        ),
        "HISTORICALLY_USABLE_CANDIDATES": sorted(historic),
        "LIVE_ONLY_OR_NOT_REPLAY_SAFE": sorted(live_only),
        "EXCLUDED_WITH_REASON": sorted(excluded),
        "notes": (
            "Pool gates (ticker, timeframe, outcome_1c) define the cohort, not tiered SQL relaxations. "
            "See baseline_feature_contract_v1 tier_progression for strict structural tiers."
        ),
    }


def build_feature_universe_inventory_v1(
    *,
    sqlite_columns: Optional[list[str]] = None,
) -> dict[str, Any]:
    """
    Machine-readable inventory. If sqlite_columns is provided (PRAGMA table_info), set
    `present_in_attached_db` for migration drift visibility.
    """
    from db import SnapshotRow

    contract = baseline_feature_contract_v1()
    entries: list[dict[str, Any]] = []
    snap_field_names = {f.name for f in fields(SnapshotRow)}
    col_set = set(sqlite_columns) if sqlite_columns else None

    for f in fields(SnapshotRow):
        name = f.name
        part, caution = _similarity_suitability(name)
        hist = not (
            _metadata_field(name) or _is_outcome_field(name) or name in ("ts_utc", "ts_et")
        )
        replay = hist and name not in ("created_at",)
        reason_excl = None
        if part == "EXCLUDED_WITH_REASON":
            _, reason_excl = _similarity_suitability(name)
        if name in CURRENT_BASELINE_STRUCTURAL:
            cu, cu_role = "yes", "tier_structural"
        elif name in POOL_GATE_FIELDS:
            cu, cu_role = "yes", "pool_gate"
        else:
            cu, cu_role = "no", None
        entry = {
            "feature_name": name,
            "source_module": "db.SnapshotRow",
            "source_field": name,
            "historically_available_for_similarity": "yes" if hist else "no",
            "replay_safe": "yes" if replay else "no",
            "data_type": _infer_data_type(name),
            "currently_used_in_similarity": cu,
            "currently_used_in_similarity_role": cu_role,
            "reason_if_excluded_from_search": reason_excl,
            "similarity_suitability_caution": caution,
            "partition_hint": part,
            "present_in_attached_db": (name in col_set) if col_set is not None else None,
        }
        entries.append(entry)

    for name in sorted(_signal_input_only_fields()):
        entries.append(
            {
                "feature_name": name,
                "source_module": "signal_types.SignalInput",
                "source_field": name,
                "historically_available_for_similarity": "no",
                "replay_safe": "no",
                "data_type": _infer_data_type(name),
                "currently_used_in_similarity": "no",
                "reason_if_excluded_from_search": "not a column on persisted SnapshotRow in this codebase",
                "similarity_suitability_caution": None,
                "partition_hint": "LIVE_ONLY_OR_NOT_REPLAY_SAFE",
                "present_in_attached_db": False,
            }
        )

    lstm_rows = _lstm_feature_rows(snap_field_names)
    for r in lstm_rows:
        if r["feature_name"] in snap_field_names:
            continue
        entries.append(r)

    partitions = _partition_entries(entries)
    return {
        "schema": SCHEMA,
        "baseline_contract_ref": contract["schema"],
        "production_authority_note": contract.get("production_authority"),
        "entries": entries,
        "partitions": partitions,
        "search_space_roles": [
            "OMIT",
            "EARLY_STRICT",
            "MID_STRICT",
            "LATE_STRICT",
            "SOFT_WEIGHT",
            "REGIME_DEPENDENT",
        ],
        "search_space_weight_bands": ["HIGH", "MEDIUM", "LOW", "EXPLORATORY"],
    }


def sqlite_snapshot_column_names(db: Any) -> list[str]:
    """PRAGMA table_info(snapshots) names — attached DB only, no mutations."""
    with db._connect() as conn:
        cur = conn.execute("PRAGMA table_info(snapshots)")
        return [str(r[1]) for r in cur.fetchall()]
