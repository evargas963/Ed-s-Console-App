from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import json
import re
from typing import Any


VALID_CATEGORIES = {
    "price_structure",
    "volume_flow",
    "volatility",
    "time",
    "cross_asset",
    "regime",
    "derived",
    "prediction_output",
    "policy_signal",
    "other",
}
VALID_SOURCES = {
    "canonical_mvp",
    "fusion_overlay",
    "db_snapshot",
    "sequence_encoder",
    "model_output",
    "policy_logic",
    "other",
}
VALID_RAW_DERIVED = {"raw", "engineered", "model_output", "policy_output"}


@dataclass(frozen=True)
class FeatureContractEntry:
    feature_name: str
    layer: str
    category: str
    source: str
    allowed: bool
    reason: str
    raw_or_derived: str
    forbidden_if_applicable: bool
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _category_for_feature(name: str) -> str:
    n = str(name or "")
    if n.startswith("cat_"):
        return "derived"
    if n.startswith("time_") or n in {"et_hour", "et_minute", "minutes_since_open"}:
        return "time"
    if n.startswith(("pred_", "prob_", "up_prob_", "down_prob_", "flat_prob_")):
        return "prediction_output"
    if n.startswith("rules_") or n.startswith("combined_"):
        return "policy_signal"
    if "vix" in n or n in {"iv_level", "iv_rank", "atr"}:
        return "volatility"
    if (
        n.endswith("_chg_pct")
        or n.endswith("_weighted_push")
        or n in {"spy_qqq_align", "spy_iwm_align", "cross_avg_chg", "cross_std_chg"}
    ):
        return "cross_asset"
    if "volume" in n or "imbalance" in n or "flow" in n:
        return "volume_flow"
    if any(
        tok in n
        for tok in (
            "spot",
            "candle_",
            "nearest_",
            "zone",
            "vwap",
            "dist_",
            "pin_",
            "gamma",
            "delta",
            "charm",
            "put_call_oi_ratio",
            "spread",
        )
    ):
        return "price_structure"
    if n.startswith("cf_"):
        return "derived"
    return "other"


def _source_for_layer_feature(layer: str, name: str) -> str:
    if layer in {"lstm", "transformer"}:
        return "sequence_encoder"
    if layer == "xgb":
        return "db_snapshot"
    if layer == "fusion":
        if name.startswith("pred_"):
            return "model_output"
        if name.startswith(("rules_", "combined_")):
            return "policy_logic"
        return "fusion_overlay"
    if layer == "prediction_core":
        if name.startswith(("pred_", "up_prob_", "down_prob_", "flat_prob_")):
            return "model_output"
        return "canonical_mvp"
    if layer == "policy":
        if name.startswith(("pred_", "fusion_", "rules_")):
            return "model_output"
        return "policy_logic"
    return "other"


def _build_entry(
    *,
    feature_name: str,
    layer: str,
    allowed: bool,
    reason: str,
    raw_or_derived: str,
    forbidden_if_applicable: bool,
    notes: str = "",
) -> FeatureContractEntry:
    return FeatureContractEntry(
        feature_name=feature_name,
        layer=layer,
        category=_category_for_feature(feature_name),
        source=_source_for_layer_feature(layer, feature_name),
        allowed=bool(allowed),
        reason=str(reason),
        raw_or_derived=raw_or_derived,
        forbidden_if_applicable=bool(forbidden_if_applicable),
        notes=str(notes),
    )


def load_active_xgb_meta_features(base_dir: Path | None = None) -> set[str]:
    root = Path(base_dir or Path(__file__).resolve().parent)
    patterns = (
        "models/active/**/xgb_*_meta.json",
        "models/active_*/**/xgb_*_meta.json",
    )
    out: set[str] = set()
    for pat in patterns:
        for p in root.glob(pat):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            out.update(d.get("features") or [])
    return out


def build_current_xgb_engineered_features() -> tuple[set[str], set[str], set[str]]:
    """
    Returns (training_features, inference_features, mismatches_between_train_infer).
    """
    import pandas as pd
    from ml_train import (
        CATEGORICALS,
        M5_SCALE_INVARIANT_EXTRA,
        M5_WALL_DISTANCE_COLS,
        SCALE_INVARIANT_COLS,
        WALL_DISTANCE_COLS,
        engineer_features,
        engineer_single_snapshot,
    )

    row: dict[str, Any] = {
        "ticker": "SPY",
        "spot": 100.0,
        "outcome_1c": "up",
        "et_hour": 10,
        "et_minute": 15,
    }
    for c in WALL_DISTANCE_COLS:
        row[c] = 1.0
    for c in SCALE_INVARIANT_COLS:
        row[c] = 1.0
    for c in M5_WALL_DISTANCE_COLS:
        row[c] = 1.0
    for c in M5_SCALE_INVARIANT_EXTRA:
        row[c] = 1.0
    row["candle_body_pts"] = 0.5
    row["candle_range_pts"] = 1.0
    row["nearest_above_dist"] = 1.0
    row["nearest_below_dist"] = 1.0
    row["vwap_dist_pts"] = 0.25
    row["flow_imbalance"] = 0.5
    row["bid_ask_imbalance"] = 0.5
    row["candle_volume"] = 1000.0
    for c in CATEGORICALS:
        row[c] = "neutral"
    row["zone"] = "pin_neutral"
    row["vwap_side"] = "above"
    row["combined_signal"] = "wait"
    row["combined_conviction"] = "low"

    df = pd.DataFrame([row, {**row, "et_hour": 10, "et_minute": 16, "candle_volume": 1100.0}])
    x_train, _, _, _ = engineer_features(df)
    train_feats = set(map(str, list(x_train.columns)))
    snap = dict(df.iloc[0].to_dict())
    x_row = engineer_single_snapshot(
        snap,
        {},
        list(x_train.columns),
        {},
        "SPY",
    )
    infer_feats = set(map(str, list(x_row.columns))) if x_row is not None else set()
    return train_feats, infer_feats, (train_feats ^ infer_feats)


def build_xgb_registry(active_meta_features: set[str] | None = None) -> list[FeatureContractEntry]:
    train_feats, _, _ = build_current_xgb_engineered_features()
    active_feats = set(active_meta_features or set())
    union = sorted(train_feats | active_feats)
    rows: list[FeatureContractEntry] = []
    for f in union:
        in_train = f in train_feats
        forbidden_family = bool(
            f.startswith("rules_")
            or f.startswith("pred_")
            or f.startswith("combined_")
            or f.startswith("policy_")
        )
        allowed = bool(in_train and not forbidden_family)
        if forbidden_family:
            reason = "forbidden family for XGB inputs (prediction/policy/circular)."
        elif in_train:
            reason = "present in current XGB engineering path."
        else:
            reason = "active artifact feature not present in current XGB engineering path."
        raw_kind = "engineered"
        if f.startswith(("pred_", "rules_")):
            raw_kind = "model_output"
        if f.startswith("combined_"):
            raw_kind = "policy_output"
        notes = ""
        if (f in active_feats) and (f not in train_feats):
            notes = "active-artifact-only; requires retrain or explicit waiver."
        rows.append(
            _build_entry(
                feature_name=f,
                layer="xgb",
                allowed=allowed,
                reason=reason,
                raw_or_derived=raw_kind,
                forbidden_if_applicable=forbidden_family,
                notes=notes,
            )
        )
    return rows


def build_lstm_registry() -> list[FeatureContractEntry]:
    from lstm_data import CONFLUENCE_FEATURES, FEATURES_1M, FEATURES_5M

    out: list[FeatureContractEntry] = []
    for f in sorted(set(FEATURES_5M) | set(FEATURES_1M) | set(CONFLUENCE_FEATURES)):
        out.append(
            _build_entry(
                feature_name=f,
                layer="lstm",
                allowed=True,
                reason="declared sequence encoder feature for LSTM training/inference path.",
                raw_or_derived=("engineered" if f.startswith("cf_") else "raw"),
                forbidden_if_applicable=False,
            )
        )
    return out


def build_transformer_registry() -> list[FeatureContractEntry]:
    from lstm_data import FEATURES_5M

    rows: list[FeatureContractEntry] = []
    for f in sorted(set(FEATURES_5M)):
        rows.append(
            _build_entry(
                feature_name=f,
                layer="transformer",
                allowed=True,
                reason="Transformer base sequence feature via encode_snapshot_5m.",
                raw_or_derived="raw",
                forbidden_if_applicable=False,
            )
        )
    for f in (
        "cascade_xgb_prob_up",
        "cascade_xgb_prob_down",
        "cascade_xgb_prob_flat",
        "cascade_lstm_prob_up",
        "cascade_lstm_prob_down",
        "cascade_lstm_prob_flat",
    ):
        rows.append(
            _build_entry(
                feature_name=f,
                layer="transformer",
                allowed=True,
                reason="explicitly approved cascade design input.",
                raw_or_derived="model_output",
                forbidden_if_applicable=False,
                notes="approved_cascade_waiver",
            )
        )
    return rows


FUSION_OVERLAY_KEYS = [
    "ticker",
    "et_hour",
    "et_minute",
    "candle_body_pts",
    "candle_range_pts",
    "zone_since_bars",
    "dist_call_gamma_wall",
    "dist_put_gamma_wall",
    "dist_call_delta_wall",
    "dist_put_delta_wall",
    "dist_gamma_inflection",
    "dist_delta_inflection",
    "dist_call_oi_wall",
    "dist_put_oi_wall",
    "dist_call_vanna_wall",
    "dist_put_vanna_wall",
    "pin_width_pts",
    "net_delta",
    "net_vanna",
    "charm_net",
    "iv_level",
    "put_call_oi_ratio",
    "spy_chg_pct",
    "qqq_chg_pct",
    "iwm_chg_pct",
    "spy_weighted_push",
    "qqq_weighted_push",
    "iwm_weighted_push",
    "vix_level",
    "vix_vs_prev",
    "prev_zone",
    "candle_direction",
    "session_bucket",
    "vix_bucket",
    "charm_direction",
    "charm_magnitude",
    "iv_direction",
    "qqq_vs_spy",
    "iwm_risk_signal",
    "candle_volume",
    "bid_ask_imbalance",
    "combined_signal",
    "combined_conviction",
    "atr",
    "iv_rank",
    "smart_money_score",
    "breakout_score",
    "pin_score",
    "minutes_since_open",
    "pred_1c_up_prob",
    "pred_1c_down_prob",
    "pred_1c_flat_prob",
    "pred_5c_up_prob",
    "pred_5c_down_prob",
    "pred_5c_flat_prob",
    "pred_15c_up_prob",
    "pred_15c_down_prob",
    "pred_15c_flat_prob",
    "pred_60c_up_prob",
    "pred_60c_down_prob",
    "pred_60c_flat_prob",
]


def build_fusion_registry() -> list[FeatureContractEntry]:
    out: list[FeatureContractEntry] = []
    for f in sorted(set(FUSION_OVERLAY_KEYS)):
        out.append(
            _build_entry(
                feature_name=f,
                layer="fusion",
                allowed=True,
                reason="feature appears in fusion overlay/model fusion path.",
                raw_or_derived=("model_output" if f.startswith("pred_") else "engineered"),
                forbidden_if_applicable=False,
            )
        )
    return out


PREDICTION_CORE_KEYS = [
    "price.spot",
    "structure.zone",
    "anchor.vwap_side",
    "structure.nearest_above_dist",
    "structure.nearest_below_dist",
    "ticker",
    "timeframe",
    "outcome_1c",
    "outcome_5c",
    "outcome_15c",
    "outcome_60c",
    "up_prob_1c",
    "down_prob_1c",
    "flat_prob_1c",
    "up_prob_5c",
    "down_prob_5c",
    "flat_prob_5c",
    "up_prob_15c",
    "down_prob_15c",
    "flat_prob_15c",
    "up_prob_60c",
    "down_prob_60c",
    "flat_prob_60c",
]


def build_prediction_core_registry() -> list[FeatureContractEntry]:
    out: list[FeatureContractEntry] = []
    for f in sorted(set(PREDICTION_CORE_KEYS)):
        out.append(
            _build_entry(
                feature_name=f,
                layer="prediction_core",
                allowed=True,
                reason="required for prediction core empirical + MH synthesis path.",
                raw_or_derived=("model_output" if "prob_" in f else "raw"),
                forbidden_if_applicable=False,
                notes=(
                    "uncertain: partial list grounded to code paths; additional runtime-only fields may exist."
                    if f in {"ticker", "timeframe"}
                    else ""
                ),
            )
        )
    return out


POLICY_KEYS = [
    "rules.signal",
    "rules.conviction",
    "pred.forward_direction",
    "pred.forward_confidence",
    "fusion.model_agreement",
    "fusion.reversal_posterior",
    "fusion.continuation_posterior",
    "fusion.breakout_posterior",
    "fusion.mc_eae",
    "canonical.direction",
    "canonical.confidence",
    "canonical.probability_up",
    "canonical.probability_down",
    "inp.spot",
    "inp.vix_level",
]


def build_policy_registry() -> list[FeatureContractEntry]:
    out: list[FeatureContractEntry] = []
    for f in sorted(set(POLICY_KEYS)):
        out.append(
            _build_entry(
                feature_name=f,
                layer="policy",
                allowed=True,
                reason="consumed by compute_call / trade validation path.",
                raw_or_derived=("policy_output" if f.startswith("rules.") else "engineered"),
                forbidden_if_applicable=False,
                notes="uncertain: extracted from direct code paths; not a full AST walk of call_engine.",
            )
        )
    return out


def build_all_layer_registries(base_dir: Path | None = None) -> dict[str, list[FeatureContractEntry]]:
    active_xgb = load_active_xgb_meta_features(base_dir=base_dir)
    return {
        "xgb": build_xgb_registry(active_xgb),
        "lstm": build_lstm_registry(),
        "transformer": build_transformer_registry(),
        "fusion": build_fusion_registry(),
        "prediction_core": build_prediction_core_registry(),
        "policy": build_policy_registry(),
    }


def validate_registry_shape(registries: dict[str, list[FeatureContractEntry]]) -> list[str]:
    errs: list[str] = []
    for layer, entries in registries.items():
        seen: set[str] = set()
        for e in entries:
            if e.feature_name in seen:
                errs.append(f"{layer}: duplicate feature entry {e.feature_name}")
            seen.add(e.feature_name)
            if e.category not in VALID_CATEGORIES:
                errs.append(f"{layer}:{e.feature_name}: invalid category {e.category}")
            if e.source not in VALID_SOURCES:
                errs.append(f"{layer}:{e.feature_name}: invalid source {e.source}")
            if e.raw_or_derived not in VALID_RAW_DERIVED:
                errs.append(f"{layer}:{e.feature_name}: invalid raw_or_derived {e.raw_or_derived}")
    return errs


def detect_forbidden_family_reappearance(feature_names: set[str]) -> list[str]:
    violations: list[str] = []
    rules = [
        (re.compile(r"^rules_", re.I), "rules_*"),
        (re.compile(r"^pred_", re.I), "pred_*"),
        (re.compile(r".*policy.*", re.I), "*policy*"),
    ]
    for f in sorted(feature_names):
        for pat, label in rules:
            if pat.match(f):
                violations.append(f"{f} matches forbidden family {label}")
                break
    return violations
