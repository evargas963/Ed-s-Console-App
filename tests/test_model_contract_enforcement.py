"""Issue 7 continuation: all model families enforce the same metadata contract."""
from __future__ import annotations

import json

from model_contract import (
    CONTRACT_FIELDS,
    CURRENT_FEATURE_SCHEMA_VERSION,
    CURRENT_PREPROCESSING_VERSION,
    contract_metadata_dict,
    meta_matches_system_contract,
    validate_artifact_contract,
)


def test_meta_matches_requires_all_contract_fields():
    assert not meta_matches_system_contract({})[0]
    d = contract_metadata_dict()
    assert meta_matches_system_contract(d)[0]
    assert not meta_matches_system_contract({**d, "anchor_contract_version": "legacy"})[0]


def test_preprocessing_version_is_a_contract_field():
    """Closeout #1 follow-on: a preprocessing-only change must fail-close serving. The field is in
    the contract, emitted by contract_metadata_dict(), and a missing/stale value is rejected."""
    assert "preprocessing_version" in CONTRACT_FIELDS
    d = contract_metadata_dict()
    assert d["preprocessing_version"] == CURRENT_PREPROCESSING_VERSION
    # Missing -> rejected (a pre-contract bundle without the field cannot load).
    missing = {k: v for k, v in d.items() if k != "preprocessing_version"}
    assert not meta_matches_system_contract(missing)[0]
    # Stale value -> rejected (a bundle trained under an older preprocessing version is fail-closed).
    assert not meta_matches_system_contract({**d, "preprocessing_version": "v3_legacy_stale"})[0]
    # All three families enforce it (no impute_medians required for lstm/transformer).
    assert validate_artifact_contract(d, "lstm")[0]
    assert not validate_artifact_contract(missing, "transformer")[0]


def test_feature_schema_version_fail_closes_serving_on_sentiment_deregister():
    """SENTIMENT/NEWS FEATURE RETIRE: dropping the 6 cols bumps feature_schema_version, which IS a
    contract field — so a bundle trained under the old schema fail-closes until the Stage-2 retrain."""
    assert "feature_schema_version" in CONTRACT_FIELDS
    d = contract_metadata_dict()
    assert d["feature_schema_version"] == CURRENT_FEATURE_SCHEMA_VERSION
    # Stale (pre-de-register) schema -> rejected.
    assert not meta_matches_system_contract({**d, "feature_schema_version": "v4_canonical_1m"})[0]
    # Missing -> rejected.
    missing = {k: v for k, v in d.items() if k != "feature_schema_version"}
    assert not meta_matches_system_contract(missing)[0]


def test_xgb_requires_impute_medians():
    base = contract_metadata_dict()
    ok, msg = validate_artifact_contract({**base, "features": ["a"], "impute_medians": {"a": 0.0}}, "xgb")
    assert ok, msg
    ok2, msg2 = validate_artifact_contract({**base, "features": ["a", "b"], "impute_medians": {"a": 1.0}}, "xgb")
    assert not ok2
    assert "impute" in msg2.lower()


def test_lstm_transformer_no_impute_required():
    base = contract_metadata_dict()
    assert validate_artifact_contract(base, "lstm")[0]
    assert validate_artifact_contract(base, "transformer")[0]


def test_lstm_module_load_rejects_invalid_contract(tmp_path):
    from lstm_model import load_lstm

    t = "XXMOD"
    b = tmp_path
    (b / f"lstm_{t}_1c.pt").write_bytes(b"x")
    (b / f"lstm_{t}_1c_meta.json").write_text(
        json.dumps({"model_type": "dual_stream_lstm"}), encoding="utf-8"
    )
    model, msg = load_lstm(model_path=b / f"lstm_{t}_1c.pt", ticker=t, model_dir=b)
    assert model is None
    assert "contract" in msg.lower()


def test_load_lstm_blocked_when_meta_missing_contract(tmp_path, monkeypatch):
    import ml_predict as mp

    mp._lstm_registry.clear()
    ticker = "ZZLS"
    base = tmp_path / ticker
    base.mkdir(parents=True)
    (base / f"lstm_{ticker}_1c.pt").write_bytes(b"not_torch")
    (base / f"lstm_{ticker}_1c_meta.json").write_text(
        json.dumps({"model_type": "dual_stream_lstm", "ticker": ticker}),
        encoding="utf-8",
    )
    monkeypatch.setattr(mp, "_model_dir_for_ticker", lambda _t: base)
    assert mp._load_lstm(ticker) is False
    mp._lstm_registry.clear()


def test_load_transformer_blocked_when_meta_missing_contract(tmp_path, monkeypatch):
    import ml_predict as mp

    mp._trans_registry.clear()
    ticker = "ZZTR"
    base = tmp_path / ticker
    base.mkdir(parents=True)
    (base / f"transformer_{ticker}_1c.pt").write_bytes(b"not_torch")
    (base / f"transformer_{ticker}_1c_meta.json").write_text(
        json.dumps({"model_type": "transformer_encoder"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(mp, "_model_dir_for_ticker", lambda _t: base)
    assert mp._load_transformer(ticker) is False
    mp._trans_registry.clear()


def test_unknown_family_rejected():
    ok, msg = validate_artifact_contract(contract_metadata_dict(), "gnn")
    assert not ok
    assert "unknown" in msg.lower()
