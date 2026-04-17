from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import inspect
import json
import re
from typing import Any

from feature_contracts import (
    build_all_layer_registries,
    build_current_xgb_engineered_features,
    detect_forbidden_family_reappearance,
    load_active_xgb_meta_features,
    validate_registry_shape,
)


@dataclass
class ContractValidationReport:
    passed: bool
    layer_results: dict[str, bool] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "layer_results": dict(self.layer_results),
            "failures": list(self.failures),
            "warnings": list(self.warnings),
            "details": dict(self.details),
        }


def _active_xgb_meta_files(base_dir: Path) -> list[Path]:
    out: list[Path] = []
    out.extend(base_dir.glob("models/active/**/xgb_*_meta.json"))
    out.extend(base_dir.glob("models/active_*/**/xgb_*_meta.json"))
    return sorted({p.resolve() for p in out})


def _validate_xgb_train_infer_meta_parity(base_dir: Path) -> tuple[list[str], dict[str, Any]]:
    fails: list[str] = []
    details: dict[str, Any] = {}
    train_feats, infer_feats, mismatch = build_current_xgb_engineered_features()
    details["xgb_train_feature_count"] = len(train_feats)
    details["xgb_infer_feature_count"] = len(infer_feats)
    details["xgb_train_infer_mismatch"] = sorted(mismatch)
    if mismatch:
        fails.append(f"XGB train/infer feature mismatch: {sorted(mismatch)}")

    active_files = _active_xgb_meta_files(base_dir)
    details["xgb_active_meta_file_count"] = len(active_files)
    meta_mismatch: dict[str, dict[str, list[str]]] = {}
    rules_hits: dict[str, list[str]] = {}
    for p in active_files:
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            fails.append(f"XGB meta unreadable: {p}: {e}")
            continue
        fs = set(map(str, d.get("features") or []))
        missing = sorted(train_feats - fs)
        extra = sorted(fs - train_feats)
        bad_rules = sorted(f for f in fs if re.match(r"^rules_", f))
        if missing or extra:
            meta_mismatch[str(p)] = {"missing_vs_train": missing, "extra_vs_train": extra}
        if bad_rules:
            rules_hits[str(p)] = bad_rules
    if meta_mismatch:
        fails.append("XGB active meta mismatch vs current engineered feature contract.")
    if rules_hits:
        fails.append("XGB active meta contains forbidden ^rules_ features.")
    details["xgb_meta_mismatch"] = meta_mismatch
    details["xgb_meta_forbidden_rules"] = rules_hits
    return fails, details


def _validate_registry_policy(registries) -> tuple[list[str], dict[str, Any]]:
    fails: list[str] = []
    details: dict[str, Any] = {}
    shape_errs = validate_registry_shape(registries)
    if shape_errs:
        fails.extend(shape_errs)
    details["registry_shape_errors"] = shape_errs

    xgb_rows = registries.get("xgb", [])
    bad_allowed: list[str] = []
    for e in xgb_rows:
        if e.raw_or_derived in {"model_output", "policy_output"} and e.allowed:
            if "waiver" not in (e.notes or "").lower():
                bad_allowed.append(e.feature_name)
    if bad_allowed:
        fails.append(
            "XGB registry allows model_output/policy_output without explicit waiver: "
            + ", ".join(sorted(set(bad_allowed)))
        )
    details["xgb_registry_bad_allowed_model_or_policy"] = sorted(set(bad_allowed))
    return fails, details


def _validate_forbidden_reappearance_in_engineering_path() -> tuple[list[str], dict[str, Any]]:
    import ml_train

    fails: list[str] = []
    details: dict[str, Any] = {}
    src_bulk = inspect.getsource(ml_train.engineer_features)
    src_one = inspect.getsource(ml_train.engineer_single_snapshot)
    # Guard both family names and obvious assignment targets.
    patterns = [
        (r"feats\[\s*f?[\"']rules_", "engineer_features assigns rules_*"),
        (r"row\[\s*f?[\"']rules_", "engineer_single_snapshot assigns rules_*"),
        (r"feats\[\s*f?[\"']pred_", "engineer_features assigns pred_*"),
        (r"row\[\s*f?[\"']pred_", "engineer_single_snapshot assigns pred_*"),
    ]
    hits: list[str] = []
    for pat, label in patterns:
        if re.search(pat, src_bulk) or re.search(pat, src_one):
            hits.append(label)
    if hits:
        fails.append("Forbidden family reappeared in XGB engineering path: " + ", ".join(hits))
    details["engineering_forbidden_path_hits"] = hits
    return fails, details


def _validate_lstm_transformer_contracts(registries) -> tuple[list[str], dict[str, Any]]:
    fails: list[str] = []
    details: dict[str, Any] = {}
    from lstm_data import CONFLUENCE_FEATURES, FEATURES_1M, FEATURES_5M
    import transformer_train

    lstm_expected = set(FEATURES_5M) | set(FEATURES_1M) | set(CONFLUENCE_FEATURES)
    lstm_registry = {e.feature_name for e in registries.get("lstm", [])}
    miss_lstm = sorted(lstm_expected - lstm_registry)
    extra_lstm = sorted(lstm_registry - lstm_expected)
    if miss_lstm or extra_lstm:
        fails.append("LSTM registry drift vs lstm_data feature definitions.")
    details["lstm_registry_missing"] = miss_lstm
    details["lstm_registry_extra"] = extra_lstm

    tr_expected = set(FEATURES_5M) | {
        "cascade_xgb_prob_up",
        "cascade_xgb_prob_down",
        "cascade_xgb_prob_flat",
        "cascade_lstm_prob_up",
        "cascade_lstm_prob_down",
        "cascade_lstm_prob_flat",
    }
    tr_registry = {e.feature_name for e in registries.get("transformer", [])}
    miss_tr = sorted(tr_expected - tr_registry)
    extra_tr = sorted(tr_registry - tr_expected)
    if miss_tr or extra_tr:
        fails.append("Transformer registry drift vs declared transformer feature design.")
    details["transformer_registry_missing"] = miss_tr
    details["transformer_registry_extra"] = extra_tr

    # Inference/training linkage guard: transformer data path must still call encode_snapshot_5m.
    src = inspect.getsource(transformer_train.prepare_transformer_data)
    if "encode_snapshot_5m" not in src:
        fails.append("Transformer prepare_transformer_data no longer uses encode_snapshot_5m.")
    details["transformer_uses_encode_snapshot_5m"] = ("encode_snapshot_5m" in src)
    return fails, details


def _validate_fusion_prediction_policy(registries) -> tuple[list[str], dict[str, Any]]:
    fails: list[str] = []
    details: dict[str, Any] = {}
    xgb_allowed = {e.feature_name for e in registries.get("xgb", []) if e.allowed}
    forbidden_hits = detect_forbidden_family_reappearance(xgb_allowed)
    if forbidden_hits:
        fails.append("Forbidden families found in XGB allowed feature set.")
    details["xgb_allowed_forbidden_family_hits"] = forbidden_hits
    return fails, details


def validate_feature_contracts(base_dir: Path | None = None) -> ContractValidationReport:
    root = Path(base_dir or Path(__file__).resolve().parent)
    regs = build_all_layer_registries(base_dir=root)

    failures: list[str] = []
    warnings: list[str] = []
    details: dict[str, Any] = {"active_xgb_feature_count": len(load_active_xgb_meta_features(root))}
    layer_results: dict[str, bool] = {}

    checks = {
        "registry_policy": _validate_registry_policy(regs),
        "xgb_parity": _validate_xgb_train_infer_meta_parity(root),
        "engineering_forbidden_path": _validate_forbidden_reappearance_in_engineering_path(),
        "lstm_transformer": _validate_lstm_transformer_contracts(regs),
        "fusion_prediction_policy": _validate_fusion_prediction_policy(regs),
    }
    for name, (errs, d) in checks.items():
        details[name] = d
        ok = len(errs) == 0
        layer_results[name] = ok
        if not ok:
            failures.extend(errs)

    # Registry entries marked uncertain should be surfaced, not hidden.
    uncertain = []
    for layer, rows in regs.items():
        for e in rows:
            if "uncertain" in (e.notes or "").lower():
                uncertain.append(f"{layer}:{e.feature_name}:{e.notes}")
    if uncertain:
        warnings.append(f"{len(uncertain)} uncertain registry entries declared.")
    details["uncertain_entries"] = uncertain

    return ContractValidationReport(
        passed=(len(failures) == 0),
        layer_results=layer_results,
        failures=failures,
        warnings=warnings,
        details=details,
    )
