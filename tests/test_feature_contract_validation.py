"""feature_contract_validation.validate_feature_contracts and the layer-registry
shape validator must reject a malformed feature registry, not let a bad contract
silently reach the model input pipeline."""
from __future__ import annotations

import json
from pathlib import Path

from feature_contracts import build_all_layer_registries, validate_registry_shape
from feature_contract_validation import validate_feature_contracts


def test_registry_shape_has_required_fields():
    regs = build_all_layer_registries(Path(__file__).resolve().parents[1])
    errs = validate_registry_shape(regs)
    assert errs == []
    for layer in ("xgb", "lstm", "transformer", "fusion", "prediction_core", "policy"):
        assert layer in regs
        assert len(regs[layer]) > 0


def test_validator_flags_rules_in_active_meta(tmp_path: Path):
    # Minimal project scaffold with one active meta file containing forbidden rules_ feature.
    mdir = tmp_path / "models" / "active" / "SPY"
    mdir.mkdir(parents=True, exist_ok=True)
    (mdir / "xgb_SPY_1c_meta.json").write_text(
        json.dumps({"features": ["candle_body_pct", "rules_5c_up"]}),
        encoding="utf-8",
    )
    report = validate_feature_contracts(tmp_path)
    assert report.passed is False
    flat = "\n".join(report.failures)
    assert "forbidden ^rules_" in flat


def test_lstm_registry_tags_structure_micro_cross_asset_streams():
    regs = build_all_layer_registries(Path(__file__).resolve().parents[1])
    lstm = {e.feature_name: e for e in regs["lstm"]}
    assert "stream=structure_5m" in lstm["candle_body_pct"].notes
    assert "stream=cross_asset" in lstm["qqq_weighted_push"].notes
    assert "stream=derived_confluence" in lstm["cf_momentum_5m"].notes


def test_lstm_registry_covers_encoded_sequence_width():
    from lstm_data import ENCODED_FEATURES_5M, ENCODED_FEATURES_1M, encoded_width_5m, encoded_width_1m

    regs = build_all_layer_registries(Path(__file__).resolve().parents[1])
    lstm_names = {e.feature_name for e in regs["lstm"]}
    for f in ENCODED_FEATURES_5M:
        assert f in lstm_names
    for f in ENCODED_FEATURES_1M:
        assert f in lstm_names
    trans = {e.feature_name for e in regs["transformer"]}
    for f in ENCODED_FEATURES_5M:
        assert f in trans
    assert encoded_width_5m() == len(ENCODED_FEATURES_5M)
    assert encoded_width_1m() == len(ENCODED_FEATURES_1M)


def test_validator_returns_structured_details():
    report = validate_feature_contracts(Path(__file__).resolve().parents[1])
    payload = report.to_dict()
    assert "passed" in payload
    assert "layer_results" in payload
    assert "details" in payload
