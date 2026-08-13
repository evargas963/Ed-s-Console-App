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


def test_load_lstm_verifies_lstm_meta_before_load_lstm():
    """ML-META-JSON-VERIFICATION-ASYMMETRY: Item-4 lstm_meta verify precedes load_lstm."""
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "ml_predict.py").read_text(encoding="utf-8")
    start = src.index("def _load_lstm")
    end = src.index("def _predict_lstm")
    body = src[start:end]
    meta_i = body.index('_verify_governed_artifact(base, bt, hz, "lstm_meta"')
    load_i = body.index("model, checkpoint = load_lstm(")
    assert meta_i < load_i
    missing_i = body.index("missing meta")
    assert missing_i < meta_i


def test_load_lstm_refuses_when_meta_file_absent(tmp_path, monkeypatch):
    """Serve path must refuse LSTM when lstm_*_meta.json is missing (transformer parity)."""
    import ml_predict as mp

    mp._lstm_registry.clear()
    mp._active_bundle_dir_cache.clear()
    ticker = "ZZLM"
    base = tmp_path / ticker
    base.mkdir(parents=True)
    (base / f"lstm_{ticker}_1c.pt").write_bytes(b"not_torch")
    monkeypatch.setattr(mp, "_model_dir_for_ticker", lambda _t: base)
    monkeypatch.setattr(mp, "get_ml_infer_horizon_slug", lambda: "1c")
    assert mp._load_lstm(ticker) is False
    rk = mp._model_registry_key(ticker, "1c")
    assert mp._lstm_registry.get(rk) is None
    mp._lstm_registry.clear()
    mp._active_bundle_dir_cache.clear()


def test_load_lstm_refuses_when_lstm_meta_hash_mismatches(tmp_path, monkeypatch):
    """Item-4: mutated lstm_meta bytes fail closed before load_lstm reads the JSON."""
    from active_bundle_contract import write_bundle_integrity_manifest

    import ml_predict as mp

    mp._lstm_registry.clear()
    mp._active_bundle_dir_cache.clear()
    ticker, hz = "ZZLH", "1c"
    base = tmp_path / ticker
    base.mkdir(parents=True)
    (base / f"lstm_{ticker}_{hz}.pt").write_bytes(b"pt-bytes")
    meta_p = base / f"lstm_{ticker}_{hz}_meta.json"
    meta_p.write_text('{"model_type":"dual_stream_lstm"}', encoding="utf-8")
    write_bundle_integrity_manifest(base, ticker, hz, allow_missing_required=True)
    meta_p.write_text('{"model_type":"dual_stream_lstm","tampered":true}', encoding="utf-8")
    monkeypatch.setattr(mp, "_model_dir_for_ticker", lambda _t: base)
    monkeypatch.setattr(mp, "get_ml_infer_horizon_slug", lambda: hz)
    assert mp._load_lstm(ticker) is False
    mp._lstm_registry.clear()
    mp._active_bundle_dir_cache.clear()


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


# ── MODEL_SERVING_PROVENANCE_SURFACE_V1 ──────────────────────────────────────

_PROVENANCE_KEYS = {
    "requested_ticker", "bundle_ticker", "guest_anchor", "guest_anchor_ticker",
    "horizon", "bundle_dir", "bundle_complete", "missing_artifacts",
    "trained_at", "feature_schema_version", "preprocessing_version",
    "contract_match", "contract_mismatch_reason", "strict_active_only",
    "relaxation_active", "runtime_class", "model_load_status",
    "fail_closed_reason",
    # ML-PIPE Item 4 — artifact integrity identity (additive)
    "artifact_integrity", "artifact_verification",
}


def _make_complete_bundle(models_root, ticker, hz="1c"):
    """Minimal on-disk bundle whose metas satisfy the CURRENT system contract."""
    import pickle

    from active_bundle_contract import (
        active_bundle_dir,
        bundle_artifact_paths,
        meta_stack_artifact_filename,
    )

    bd = active_bundle_dir(ticker, hz, models_dir=models_root)
    bd.mkdir(parents=True, exist_ok=True)
    meta = {
        **contract_metadata_dict(),
        "trained_at": "2026-07-01 00:00:00",
        "features": ["a"],
        "impute_medians": {"a": 0.0},
    }
    for kind, model_path, meta_path in bundle_artifact_paths(ticker, hz, bd):
        model_path.write_bytes(b"x")
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
    with (bd / meta_stack_artifact_filename(ticker, hz)).open("wb") as fh:
        pickle.dump({"kind": "meta_stack_stub"}, fh)
    return bd


def test_provenance_block_authoritative_ticker(tmp_path, monkeypatch):
    """Required test 1: full-key block for an own-bundle ticker; requested ==
    bundle; guest_anchor False; complete bundle classes STRICT_ACTIVE_SERVABLE."""
    import ml_predict as mp

    monkeypatch.setattr(mp, "MODEL_DIR", tmp_path)
    # Stub .pt bytes cannot satisfy the structural torch-checkpoint inspection;
    # the provenance surface under test consumes the compliance verdict, so the
    # inspector is stubbed to isolate that surface.
    monkeypatch.setattr("lstm_data.sequence_encoder_checkpoint_issues", lambda p: ())
    t = "ZZOWN"
    bd = _make_complete_bundle(tmp_path, t)
    # Item-4 strict default (committed policy): a SERVABLE bundle carries an
    # integrity manifest — stamp it the way the governed promotion path does.
    from active_bundle_contract import write_bundle_integrity_manifest

    write_bundle_integrity_manifest(bd, t, "1c")
    prov = mp.build_model_serving_provenance(t)
    assert set(prov) == _PROVENANCE_KEYS
    assert prov["requested_ticker"] == t
    assert prov["bundle_ticker"] == t
    assert prov["guest_anchor"] is False
    assert prov["bundle_complete"] is True
    assert prov["contract_match"] is True
    assert prov["trained_at"] == "2026-07-01 00:00:00"
    assert prov["feature_schema_version"] == CURRENT_FEATURE_SCHEMA_VERSION
    assert prov["runtime_class"] == "STRICT_ACTIVE_SERVABLE"


def test_provenance_block_guest_routed_ticker(tmp_path, monkeypatch):
    """Required test 2: under the guest scopes, requested != bundle and the
    block reports the anchor as bundle_ticker."""
    import ml_predict as mp
    from governed_stack_contract import (
        guest_anchor_context_scope,
        resolve_guest_anchor_for_ticker,
    )

    monkeypatch.setattr(mp, "MODEL_DIR", tmp_path)
    monkeypatch.setattr("lstm_data.sequence_encoder_checkpoint_issues", lambda p: ())
    guest = "ZZGUEST"
    ctx = resolve_guest_anchor_for_ticker(guest)
    assert ctx is not None  # non-authoritative symbols always route to an anchor
    _make_complete_bundle(tmp_path, ctx.anchor_ticker)
    with guest_anchor_context_scope(ctx), mp.ml_bundle_ticker_scope(ctx.anchor_ticker):
        prov = mp.build_model_serving_provenance(guest)
    assert prov["requested_ticker"] == guest
    assert prov["bundle_ticker"] == ctx.anchor_ticker
    assert prov["requested_ticker"] != prov["bundle_ticker"]
    assert prov["guest_anchor"] is True
    assert prov["guest_anchor_ticker"] == ctx.anchor_ticker


def test_provenance_surfaces_relaxation_active(tmp_path, monkeypatch):
    """Required test 3: relaxation env visible in the block."""
    import ml_predict as mp
    from arch_competition.stack_bundle_eval_v1 import ABLATION_SCORING_PASS_ENV

    monkeypatch.setattr(mp, "MODEL_DIR", tmp_path)
    monkeypatch.setenv(ABLATION_SCORING_PASS_ENV, "1")
    prov = mp.build_model_serving_provenance("ZZRLX")
    assert prov["relaxation_active"] is True
    assert prov["runtime_class"] == "RELAXATION_ACTIVE"


def test_provenance_surfaces_strict_active_only(tmp_path, monkeypatch):
    """Required test 4: strict gate state visible; default on, env off -> off."""
    import ml_predict as mp

    monkeypatch.setattr(mp, "MODEL_DIR", tmp_path)
    monkeypatch.delenv("ED_XGB_STRICT_ACTIVE_ONLY", raising=False)
    prov = mp.build_model_serving_provenance("ZZSTR")
    assert prov["strict_active_only"] is True
    assert prov["runtime_class"] == "STRICT_ACTIVE_FAIL_CLOSED"  # empty models root
    assert prov["model_load_status"] == "fail_closed"
    assert "FileNotFoundError" in (prov["fail_closed_reason"] or "")
    monkeypatch.setenv("ED_XGB_STRICT_ACTIVE_ONLY", "0")
    prov_off = mp.build_model_serving_provenance("ZZSTR")
    assert prov_off["strict_active_only"] is False
    assert prov_off["runtime_class"] == "RELAXED_RESOLUTION"


def test_provenance_contract_rejection_behavior_unchanged():
    """Required test 5: the v4 rejection and loader call sites are intact."""
    from pathlib import Path

    d = contract_metadata_dict()
    assert not meta_matches_system_contract({**d, "feature_schema_version": "v4_canonical_1m"})[0]
    root = Path(__file__).resolve().parent.parent
    mp_src = (root / "ml_predict.py").read_text(encoding="utf-8")
    assert mp_src.count('validate_artifact_contract(meta, "xgb")') >= 2
    assert 'validate_artifact_contract(tr_meta, "transformer")' in mp_src
    lstm_src = (root / "lstm_model.py").read_text(encoding="utf-8")
    assert 'validate_artifact_contract(meta, "lstm")' in lstm_src


def test_provenance_guest_routing_behavior_unchanged():
    """Required test 6: routing outcomes unchanged and the builder never
    mutates the routing/bundle contextvars (read-only AST)."""
    import ast
    from pathlib import Path

    from governed_stack_contract import (
        ML_AUTHORITATIVE_TICKERS,
        resolve_guest_anchor_for_ticker,
    )

    for t in ML_AUTHORITATIVE_TICKERS:
        assert resolve_guest_anchor_for_ticker(t) is None
    ctx = resolve_guest_anchor_for_ticker("ZZGUEST")
    assert ctx is not None and ctx.anchor_ticker in ML_AUTHORITATIVE_TICKERS

    root = Path(__file__).resolve().parent.parent
    tree = ast.parse((root / "ml_predict.py").read_text(encoding="utf-8"))
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "build_model_serving_provenance"
    )
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in ("set", "reset"), (
                f"contextvar mutation {node.func.attr} in provenance builder"
            )


def test_provenance_output_shape_backward_compatible():
    """Required test 7: additive-only — SignalOutput and MarketState carry the
    new field with a None default; the market_state copy is ungated."""
    import dataclasses

    from market_state import MarketState
    from signal_types import SignalOutput

    so_fields = {f.name: f for f in dataclasses.fields(SignalOutput)}
    assert "model_serving_provenance" in so_fields
    assert so_fields["model_serving_provenance"].default is None
    ms_fields = {f.name: f for f in dataclasses.fields(MarketState)}
    assert "model_serving_provenance_v1" in ms_fields
    assert ms_fields["model_serving_provenance_v1"].default is None

    from pathlib import Path

    ms_src = (Path(__file__).resolve().parent.parent / "market_state.py").read_text(encoding="utf-8")
    i_copy = ms_src.index(
        'ms.model_serving_provenance_v1 = getattr(_sig_out, "model_serving_provenance", None)'
    )
    i_mhb_gate = ms_src.index('_mhb = getattr(_sig_out, "multi_horizon_bundle", None)')
    assert i_copy < i_mhb_gate, "provenance copy must precede (sit outside) the MH gate"


def test_provenance_no_ticker_literals():
    """Required test 8: no ticker-literal-shaped constants in the builder."""
    import ast
    from pathlib import Path

    tree = ast.parse((Path(__file__).resolve().parent.parent / "ml_predict.py").read_text(encoding="utf-8"))
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "build_model_serving_provenance"
    )
    for node in ast.walk(fn):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert not (node.value.isalpha() and node.value.isupper() and len(node.value) <= 5), (
                f"ticker-literal-shaped constant {node.value!r} in provenance builder"
            )


# ── ML-PIPE Item 4 — artifact-manifest load verification (adversarial) ───────
#
# Independent reference: expected hashes are recomputed here with hashlib
# directly — never through the implementation under test.

import hashlib
import os
import pickle as _pickle

import pytest

from active_bundle_contract import (
    ARTIFACT_INTEGRITY_STRICT_ENV,
    ARTIFACT_VERIFICATION_FAILURE_REASONS,
    ArtifactVerificationError,
    BUNDLE_INTEGRITY_MANIFEST_FILENAME,
    bundle_integrity_manifest_path,
    classify_legacy_absent_manifest,
    load_bundle_integrity_manifest,
    refresh_bundle_integrity_manifest,
    verify_artifact_against_manifest,
    write_bundle_integrity_manifest,
)


def _sha256_independent(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stamped_bundle(models_root, ticker, hz="1c"):
    """Complete bundle with a loadable xgb pickle + integrity manifest."""
    bd = _make_complete_bundle(models_root, ticker, hz)
    with (bd / f"xgb_{ticker}_{hz}.pkl").open("wb") as fh:
        _pickle.dump({"kind": "xgb_stub", "ticker": ticker}, fh)
    write_bundle_integrity_manifest(bd, ticker, hz)
    return bd


def _reset_ml_predict_state(mp):
    for reg in (
        mp._xgb_registry, mp._meta_registry, mp._lstm_registry,
        mp._trans_registry, mp._xgb_movehead_registry,
    ):
        reg.clear()
    mp._artifact_verification_registry.clear()
    mp._active_bundle_dir_cache.clear()
    mp._strict_bundle_warned.clear()


@pytest.fixture()
def mp_bundle(tmp_path, monkeypatch):
    """ml_predict module wired to a stamped tmp bundle for ZZIN4 (hz=1c)."""
    import ml_predict as mp

    t = "ZZIN4"
    bd = _stamped_bundle(tmp_path, t)
    monkeypatch.setattr(mp, "MODEL_DIR", tmp_path)
    monkeypatch.setattr(mp, "_model_dir_for_ticker", lambda _t: bd)
    monkeypatch.delenv(ARTIFACT_INTEGRITY_STRICT_ENV, raising=False)
    _reset_ml_predict_state(mp)
    yield mp, t, bd
    _reset_ml_predict_state(mp)


def test_item4_valid_manifest_and_artifact_verify(tmp_path):
    t, hz = "ZZOK", "1c"
    bd = _stamped_bundle(tmp_path, t)
    name = f"xgb_{t}_{hz}.pkl"
    prov = verify_artifact_against_manifest(bd, t, hz, "xgb", name)
    assert prov["verified"] is True
    assert prov["legacy"] is False
    assert prov["integrity_class"] == "VERIFIED_AGAINST_BUNDLE_MANIFEST"
    # Independent hash reference (hashlib, not the implementation).
    assert prov["actual_sha256"] == _sha256_independent(bd / name)
    assert prov["expected_sha256"] == prov["actual_sha256"]
    assert prov["manifest_sha256"] == _sha256_independent(
        bd / BUNDLE_INTEGRITY_MANIFEST_FILENAME
    )
    assert prov["ticker"] == t and prov["horizon"] == hz
    assert prov["artifact_role"] == "xgb"


def test_item4_one_byte_artifact_mutation_fails(tmp_path):
    t, hz = "ZZMUT", "1c"
    bd = _stamped_bundle(tmp_path, t)
    name = f"xgb_{t}_{hz}.pkl"
    p = bd / name
    raw = bytearray(p.read_bytes())
    raw[0] ^= 0xFF
    p.write_bytes(bytes(raw))
    with pytest.raises(ArtifactVerificationError) as ei:
        verify_artifact_against_manifest(bd, t, hz, "xgb", name)
    assert ei.value.reason_code == "ARTIFACT_HASH_MISMATCH"


def test_item4_manifest_expected_hash_mutation_fails(tmp_path):
    t, hz = "ZZMH", "1c"
    bd = _stamped_bundle(tmp_path, t)
    name = f"xgb_{t}_{hz}.pkl"
    mf_path = bundle_integrity_manifest_path(bd)
    mf = json.loads(mf_path.read_text(encoding="utf-8"))
    mf["artifacts"][name]["sha256"] = "0" * 64
    mf_path.write_text(json.dumps(mf), encoding="utf-8")
    with pytest.raises(ArtifactVerificationError) as ei:
        verify_artifact_against_manifest(bd, t, hz, "xgb", name)
    assert ei.value.reason_code == "ARTIFACT_HASH_MISMATCH"


def _open_legacy_allowance(tmp_path, monkeypatch):
    """Point the module at a policy whose legacy allowance is OPEN (tests of the
    historical pre-migration behavior; the COMMITTED policy is strict)."""
    import active_bundle_contract as abc_mod

    pol = tmp_path / "policy_open_allowance.json"
    pol.write_text(json.dumps({
        "schema_version": 1,
        "strict_default": False,
        "legacy_allowance": {"enabled": True, "expires_at_utc": "2099-01-01T00:00:00+00:00"},
    }), encoding="utf-8")
    monkeypatch.setattr(abc_mod, "MIGRATION_POLICY_PATH", pol)


def test_item4_absent_manifest_explicit_legacy_never_verified(tmp_path, monkeypatch):
    t, hz = "ZZLEG", "1c"
    bd = _make_complete_bundle(tmp_path, t, hz)  # NO integrity manifest
    name = f"xgb_{t}_{hz}.pkl"
    monkeypatch.delenv(ARTIFACT_INTEGRITY_STRICT_ENV, raising=False)
    _open_legacy_allowance(tmp_path, monkeypatch)
    assert load_bundle_integrity_manifest(bd) is None
    with pytest.raises(ArtifactVerificationError) as ei:
        verify_artifact_against_manifest(bd, t, hz, "xgb", name)
    assert ei.value.reason_code == "MANIFEST_MISSING"
    prov = classify_legacy_absent_manifest(bd, t, hz, "xgb", name)
    # Legacy can never masquerade as verified.
    assert prov["verified"] is False
    assert prov["legacy"] is True
    assert prov["integrity_class"] == "LEGACY_UNVERIFIED_NO_BUNDLE_MANIFEST"
    assert prov["reason_code"] == "MANIFEST_MISSING"
    # Operator strict lever: absence fails closed.
    monkeypatch.setenv(ARTIFACT_INTEGRITY_STRICT_ENV, "1")
    with pytest.raises(ArtifactVerificationError) as ei2:
        classify_legacy_absent_manifest(bd, t, hz, "xgb", name)
    assert ei2.value.reason_code == "MANIFEST_MISSING"


def test_item4_malformed_and_unsupported_manifest_fail(tmp_path):
    t, hz = "ZZBAD", "1c"
    bd = _stamped_bundle(tmp_path, t)
    mf_path = bundle_integrity_manifest_path(bd)
    original = mf_path.read_text(encoding="utf-8")

    mf_path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ArtifactVerificationError) as ei:
        load_bundle_integrity_manifest(bd)
    assert ei.value.reason_code == "MANIFEST_MALFORMED"

    mf_path.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
    with pytest.raises(ArtifactVerificationError) as ei2:
        load_bundle_integrity_manifest(bd)
    assert ei2.value.reason_code == "MANIFEST_MALFORMED"

    mf = json.loads(original)
    mf["schema_version"] = 999
    mf_path.write_text(json.dumps(mf), encoding="utf-8")
    with pytest.raises(ArtifactVerificationError) as ei3:
        load_bundle_integrity_manifest(bd)
    assert ei3.value.reason_code == "MANIFEST_VERSION_UNSUPPORTED"


def test_item4_missing_entry_missing_file_invalid_hash(tmp_path):
    t, hz = "ZZENT", "1c"
    bd = _stamped_bundle(tmp_path, t)
    name = f"xgb_{t}_{hz}.pkl"
    mf_path = bundle_integrity_manifest_path(bd)
    mf = json.loads(mf_path.read_text(encoding="utf-8"))

    # Missing artifact entry.
    entry = mf["artifacts"].pop(name)
    mf_path.write_text(json.dumps(mf), encoding="utf-8")
    with pytest.raises(ArtifactVerificationError) as ei:
        verify_artifact_against_manifest(bd, t, hz, "xgb", name)
    assert ei.value.reason_code == "ARTIFACT_ENTRY_MISSING"

    # Invalid expected-hash syntax.
    entry["sha256"] = "NOT-A-HASH"
    mf["artifacts"][name] = entry
    mf_path.write_text(json.dumps(mf), encoding="utf-8")
    with pytest.raises(ArtifactVerificationError) as ei2:
        verify_artifact_against_manifest(bd, t, hz, "xgb", name)
    assert ei2.value.reason_code == "EXPECTED_HASH_INVALID"

    # Missing artifact file.
    entry["sha256"] = "a" * 64
    mf_path.write_text(json.dumps(mf), encoding="utf-8")
    (bd / name).unlink()
    with pytest.raises(ArtifactVerificationError) as ei3:
        verify_artifact_against_manifest(bd, t, hz, "xgb", name)
    assert ei3.value.reason_code == "ARTIFACT_FILE_MISSING"


def test_item4_identity_substitution_fails(tmp_path):
    t, hz = "ZZIDA", "1c"
    bd = _stamped_bundle(tmp_path, t)

    # Cross-ticker substitution at request level.
    with pytest.raises(ArtifactVerificationError) as ei:
        verify_artifact_against_manifest(bd, t, hz, "xgb", "xgb_ZZIDB_1c.pkl")
    assert ei.value.reason_code == "TICKER_IDENTITY_MISMATCH"

    # Cross-horizon substitution.
    with pytest.raises(ArtifactVerificationError) as ei2:
        verify_artifact_against_manifest(bd, t, hz, "xgb", f"xgb_{t}_5c.pkl")
    assert ei2.value.reason_code == "HORIZON_IDENTITY_MISMATCH"

    # Cross-model substitution (lstm file requested under the xgb role).
    with pytest.raises(ArtifactVerificationError) as ei3:
        verify_artifact_against_manifest(bd, t, hz, "xgb", f"lstm_{t}_{hz}.pt")
    assert ei3.value.reason_code == "MODEL_IDENTITY_MISMATCH"

    # Unknown / wrong artifact role.
    with pytest.raises(ArtifactVerificationError) as ei4:
        verify_artifact_against_manifest(bd, t, hz, "nonsense_role", f"xgb_{t}_{hz}.pkl")
    assert ei4.value.reason_code == "ARTIFACT_ROLE_MISMATCH"

    # Manifest role mismatch (entry role edited).
    name = f"xgb_{t}_{hz}.pkl"
    mf_path = bundle_integrity_manifest_path(bd)
    mf = json.loads(mf_path.read_text(encoding="utf-8"))
    mf["artifacts"][name]["role"] = "lstm"
    mf_path.write_text(json.dumps(mf), encoding="utf-8")
    with pytest.raises(ArtifactVerificationError) as ei5:
        verify_artifact_against_manifest(bd, t, hz, "xgb", name)
    assert ei5.value.reason_code == "ARTIFACT_ROLE_MISMATCH"


def test_item4_ticker_horizon_bundle_identity_of_manifest(tmp_path):
    t, hz = "ZZIDC", "1c"
    bd = _stamped_bundle(tmp_path, t)
    name = f"xgb_{t}_{hz}.pkl"
    mf_path = bundle_integrity_manifest_path(bd)
    original = json.loads(mf_path.read_text(encoding="utf-8"))

    for field, value, reason in (
        ("ticker", "ZZOTH", "TICKER_IDENTITY_MISMATCH"),
        ("ml_horizon_slug", "5c", "HORIZON_IDENTITY_MISMATCH"),
        ("bundle_key", f"{t}:60c", "BUNDLE_IDENTITY_MISMATCH"),
    ):
        mf = dict(original)
        mf[field] = value
        mf_path.write_text(json.dumps(mf), encoding="utf-8")
        with pytest.raises(ArtifactVerificationError) as ei:
            verify_artifact_against_manifest(bd, t, hz, "xgb", name)
        assert ei.value.reason_code == reason, field


def test_item4_path_traversal_and_bundle_escape_fail(tmp_path):
    t, hz = "ZZTRV", "1c"
    bd = _stamped_bundle(tmp_path, t)
    outside = tmp_path / f"xgb_{t}_{hz}.pkl"
    outside.write_bytes(b"outside")
    for evil in (f"..\\{outside.name}", f"../{outside.name}", str(outside), ""):
        with pytest.raises(ArtifactVerificationError) as ei:
            verify_artifact_against_manifest(bd, t, hz, "xgb", evil)
        assert ei.value.reason_code in (
            "ARTIFACT_PATH_OUTSIDE_BUNDLE",
            # request-level filename identity fires first for non-basename shapes
            "TICKER_IDENTITY_MISMATCH",
            "MODEL_IDENTITY_MISMATCH",
        )
    # The pure containment helper rejects traversal outright.
    from active_bundle_contract import _contained_artifact_path

    with pytest.raises(ArtifactVerificationError) as ei2:
        _contained_artifact_path(bd, f"..\\{outside.name}", {})
    assert ei2.value.reason_code == "ARTIFACT_PATH_OUTSIDE_BUNDLE"


def test_item4_duplicate_filenames_in_separate_bundles_do_not_cross_resolve(tmp_path):
    """Same filename in two bundle dirs: each dir verifies only its own bytes."""
    t, hz = "ZZDUP", "1c"
    bd_a = _stamped_bundle(tmp_path / "rootA", t)
    bd_b = _stamped_bundle(tmp_path / "rootB", t)
    name = f"xgb_{t}_{hz}.pkl"
    # Divergent bytes in B under the same filename, manifest copied from A.
    with (bd_b / name).open("wb") as fh:
        _pickle.dump({"kind": "divergent"}, fh)
    (bd_b / BUNDLE_INTEGRITY_MANIFEST_FILENAME).write_text(
        (bd_a / BUNDLE_INTEGRITY_MANIFEST_FILENAME).read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    assert verify_artifact_against_manifest(bd_a, t, hz, "xgb", name)["verified"] is True
    with pytest.raises(ArtifactVerificationError) as ei:
        verify_artifact_against_manifest(bd_b, t, hz, "xgb", name)
    assert ei.value.reason_code == "ARTIFACT_HASH_MISMATCH"


def test_item4_reason_codes_are_the_governed_enum():
    """Every raise site uses the single governed vocabulary (constructor-enforced)."""
    with pytest.raises(ValueError):
        ArtifactVerificationError("NOT_A_GOVERNED_REASON", "x")
    assert "ARTIFACT_HASH_MISMATCH" in ARTIFACT_VERIFICATION_FAILURE_REASONS
    assert "MANIFEST_MISSING" in ARTIFACT_VERIFICATION_FAILURE_REASONS
    assert len(set(ARTIFACT_VERIFICATION_FAILURE_REASONS)) == len(
        ARTIFACT_VERIFICATION_FAILURE_REASONS
    )


def test_item4_load_xgb_verifies_before_pickle_load(mp_bundle, monkeypatch):
    """PRE-deserialization proof: with a corrupted artifact, pickle.load is never reached."""
    mp, t, bd = mp_bundle
    hz = "1c"
    name = f"xgb_{t}_{hz}.pkl"
    (bd / name).write_bytes(b"corrupted-bytes")

    def _poison(*a, **k):
        raise AssertionError("pickle.load reached with unverified artifact bytes")

    monkeypatch.setattr(mp.pickle, "load", _poison)
    assert mp._load_xgb(t) is False
    prov = mp.get_artifact_verification_provenance(t, hz)
    assert prov["xgb"]["integrity_class"] == "VERIFICATION_FAILED_CLOSED"
    assert prov["xgb"]["reason_code"] == "ARTIFACT_HASH_MISMATCH"
    assert prov["xgb"]["inference_blocked"] is True


def test_item4_load_xgb_success_records_provenance(mp_bundle):
    mp, t, bd = mp_bundle
    assert mp._load_xgb(t) is True
    prov = mp.get_artifact_verification_provenance(t, "1c")
    assert prov["xgb"]["verified"] is True
    assert prov["xgb"]["integrity_class"] == "VERIFIED_AGAINST_BUNDLE_MANIFEST"
    assert prov["xgb_meta"]["verified"] is True
    # Independent recompute of the recorded hash.
    assert prov["xgb"]["actual_sha256"] == _sha256_independent(bd / f"xgb_{t}_1c.pkl")


def test_item4_load_meta_verifies_with_governed_meta_stack_role(mp_bundle):
    """Regression (2026-07-16): _load_meta must request the governed
    META_STACK_KIND role ('meta_stack') — the role the manifest stamper writes
    for meta_{t}_{hz}.pkl. Requesting 'meta' was rejected as an unknown role
    (ARTIFACT_ROLE_MISMATCH) and failed the meta layer closed fleet-wide."""
    from active_bundle_contract import META_STACK_KIND

    mp, t, _bd = mp_bundle
    assert mp._load_meta(t) is True
    prov = mp.get_artifact_verification_provenance(t, "1c")
    assert prov[META_STACK_KIND]["verified"] is True
    assert prov[META_STACK_KIND]["integrity_class"] == "VERIFIED_AGAINST_BUNDLE_MANIFEST"
    assert "meta" not in prov  # the ungoverned role string must never be recorded


def test_item4_cache_invalidates_on_artifact_mutation(mp_bundle):
    """A verified cached model cannot outlive artifact-byte mutation."""
    mp, t, bd = mp_bundle
    name = f"xgb_{t}_1c.pkl"
    assert mp._load_xgb(t) is True
    # Mutate artifact bytes on disk (stat identity changes).
    p = bd / name
    with p.open("wb") as fh:
        _pickle.dump({"kind": "tampered"}, fh)
    os.utime(p, ns=(p.stat().st_atime_ns, p.stat().st_mtime_ns + 1_000_000))
    assert mp._load_xgb(t) is False  # evicted + re-verified -> hash mismatch
    prov = mp.get_artifact_verification_provenance(t, "1c")
    assert prov["xgb"]["reason_code"] == "ARTIFACT_HASH_MISMATCH"
    # Negative result is sticky (not replaced by the older positive entry).
    assert mp._load_xgb(t) is False


def test_item4_cache_invalidates_on_manifest_mutation(mp_bundle):
    mp, t, bd = mp_bundle
    assert mp._load_xgb(t) is True
    mf_path = bundle_integrity_manifest_path(bd)
    mf = json.loads(mf_path.read_text(encoding="utf-8"))
    mf["artifacts"][f"xgb_{t}_1c.pkl"]["sha256"] = "f" * 64
    mf_path.write_text(json.dumps(mf), encoding="utf-8")
    os.utime(mf_path, ns=(mf_path.stat().st_atime_ns, mf_path.stat().st_mtime_ns + 1_000_000))
    assert mp._load_xgb(t) is False
    prov = mp.get_artifact_verification_provenance(t, "1c")
    assert prov["xgb"]["reason_code"] == "ARTIFACT_HASH_MISMATCH"


def test_item4_legacy_bundle_gaining_manifest_reverifies(tmp_path, monkeypatch):
    import ml_predict as mp

    t = "ZZLG2"
    bd = _make_complete_bundle(tmp_path, t)  # legacy: no manifest
    with (bd / f"xgb_{t}_1c.pkl").open("wb") as fh:
        _pickle.dump({"kind": "legacy"}, fh)
    monkeypatch.setattr(mp, "MODEL_DIR", tmp_path)
    monkeypatch.setattr(mp, "_model_dir_for_ticker", lambda _t: bd)
    monkeypatch.delenv(ARTIFACT_INTEGRITY_STRICT_ENV, raising=False)
    _open_legacy_allowance(tmp_path, monkeypatch)
    _reset_ml_predict_state(mp)
    try:
        assert mp._load_xgb(t) is True
        prov = mp.get_artifact_verification_provenance(t, "1c")
        assert prov["xgb"]["legacy"] is True
        assert prov["xgb"]["integrity_class"] == "LEGACY_UNVERIFIED_NO_BUNDLE_MANIFEST"
        # Bundle gains an integrity manifest -> cached legacy entry re-verifies.
        write_bundle_integrity_manifest(bd, t, "1c")
        assert mp._load_xgb(t) is True
        prov2 = mp.get_artifact_verification_provenance(t, "1c")
        assert prov2["xgb"]["verified"] is True
        assert prov2["xgb"]["legacy"] is False
    finally:
        _reset_ml_predict_state(mp)


def test_item4_cross_ticker_and_cross_horizon_cache_isolation(mp_bundle):
    """Registry keys carry (ticker, horizon) identity by construction."""
    mp, t, _bd = mp_bundle
    k1 = mp._model_registry_key(t, "1c")
    # Key embeds ticker + horizon identity (arch prefix included).
    assert f"{t}:1c" in k1
    k_hz = mp._model_registry_key(t, "5c")
    k_tk = mp._model_registry_key("ZZOTH", "1c")
    assert k_hz != k1 and f"{t}:5c" in k_hz
    assert k_tk != k1 and "ZZOTH:1c" in k_tk
    # Eviction of one key never touches another ticker's entries.
    mp._xgb_registry[k_tk] = {"model": "other"}
    mp.invalidate_model_registry_key(k1)
    assert mp._xgb_registry[k_tk] == {"model": "other"}
    del mp._xgb_registry[k_tk]


def test_item4_strict_absence_blocks_serving(tmp_path, monkeypatch):
    """ED_ARTIFACT_INTEGRITY_STRICT=1: manifest-absent bundle refuses to load."""
    import ml_predict as mp

    t = "ZZSTRICT"[:5]
    bd = _make_complete_bundle(tmp_path, t)
    with (bd / f"xgb_{t}_1c.pkl").open("wb") as fh:
        _pickle.dump({"kind": "legacy"}, fh)
    monkeypatch.setattr(mp, "MODEL_DIR", tmp_path)
    monkeypatch.setattr(mp, "_model_dir_for_ticker", lambda _t: bd)
    monkeypatch.setenv(ARTIFACT_INTEGRITY_STRICT_ENV, "1")
    _reset_ml_predict_state(mp)
    try:
        assert mp._load_xgb(t) is False
        prov = mp.get_artifact_verification_provenance(t, "1c")
        assert prov["xgb"]["reason_code"] == "MANIFEST_MISSING"
        assert prov["xgb"]["integrity_class"] == "VERIFICATION_FAILED_CLOSED"
    finally:
        _reset_ml_predict_state(mp)


def test_item4_promotion_stamps_manifest(tmp_path):
    """promote_horizon_bundle_from_candidate writes the integrity manifest with lineage."""
    from active_bundle_contract import promote_horizon_bundle_from_candidate

    t, hz = "ZZPRM", "1c"
    src = tmp_path / "candidate"
    src.mkdir()
    _make_complete_bundle(tmp_path / "candidate_root", t)  # shape only
    # Build candidate files directly in src (flat candidate dir layout).
    from active_bundle_contract import horizon_bundle_filenames

    for name in horizon_bundle_filenames(t, hz):
        if name.endswith(".json"):
            (src / name).write_text(json.dumps({**contract_metadata_dict(), "features": ["a"], "impute_medians": {"a": 0.0}}), encoding="utf-8")
        else:
            with (src / name).open("wb") as fh:
                _pickle.dump({"n": name}, fh)
    (src / "scheduler_run_manifest.json").write_text(
        json.dumps({
            "schema_version": 1,
            "trained_at": "2026-07-11T00:00:00Z",
            "data_end": "2026-07-10",
            "scheduler_cache_key": "cachekey123",
        }),
        encoding="utf-8",
    )
    active = promote_horizon_bundle_from_candidate(
        src, ticker=t, hz=hz, models_dir=tmp_path / "models"
    )
    mf = load_bundle_integrity_manifest(active)
    assert mf is not None
    assert mf["ticker"] == t and mf["ml_horizon_slug"] == hz
    assert mf["source_lineage"].get("trained_at") == "2026-07-11T00:00:00Z"
    assert mf["source_lineage"].get("scheduler_cache_key") == "cachekey123"
    # Every promoted artifact byte-verifies immediately (independent hashlib check).
    for name, entry in mf["artifacts"].items():
        assert entry["sha256"] == _sha256_independent(active / name), name
        verify_artifact_against_manifest(active, t, hz, entry["role"], name)


def test_item4_refresh_preserves_lineage_and_is_noop_for_legacy(tmp_path):
    t, hz = "ZZRF", "1c"
    # Legacy bundle: refresh is a no-op (never launders unverified artifacts).
    legacy = _make_complete_bundle(tmp_path / "legacy_root", t)
    assert refresh_bundle_integrity_manifest(legacy) is None
    assert not bundle_integrity_manifest_path(legacy).is_file()
    # Stamped bundle: in-place write then refresh -> re-verifies, lineage kept.
    bd = _stamped_bundle(tmp_path, t)
    original_lineage = load_bundle_integrity_manifest(bd)["source_lineage"]
    name = f"xgb_{t}_{hz}.pkl"
    with (bd / name).open("wb") as fh:
        _pickle.dump({"kind": "retrained-in-place"}, fh)
    with pytest.raises(ArtifactVerificationError):
        verify_artifact_against_manifest(bd, t, hz, "xgb", name)
    refreshed = refresh_bundle_integrity_manifest(bd)
    assert refreshed is not None
    assert refreshed["source_lineage"] == original_lineage
    assert verify_artifact_against_manifest(bd, t, hz, "xgb", name)["verified"] is True


def test_item4_provenance_surface_reports_integrity(mp_bundle):
    mp, t, _bd = mp_bundle
    prov0 = mp.build_model_serving_provenance(t)
    assert prov0["artifact_integrity"] == "NOT_LOADED"
    assert mp._load_xgb(t) is True
    prov1 = mp.build_model_serving_provenance(t)
    assert prov1["artifact_integrity"] == "VERIFIED_AGAINST_BUNDLE_MANIFEST"
    assert prov1["artifact_verification"]["xgb"]["verified"] is True
    assert prov1["artifact_verification"]["xgb"]["artifact_sha256"] is None or isinstance(
        prov1["artifact_verification"]["xgb"]["artifact_sha256"], str
    )


@pytest.mark.parametrize("ticker", ["SPY", "QQQ", "IWM", "ZZGST"])
@pytest.mark.parametrize("hz", ["1c", "5c", "15c", "60c"])
def test_item4_universal_ticker_horizon_matrix(tmp_path, ticker, hz):
    """Universality: verify + fail-closed mutation across anchors, a guest
    fixture, and all four governed horizons (verifier is parameterized —
    ticker/horizon enter only as identity inputs)."""
    bd = _make_complete_bundle(tmp_path, ticker, hz)
    name = f"xgb_{ticker}_{hz}.pkl"
    with (bd / name).open("wb") as fh:
        _pickle.dump({"t": ticker, "hz": hz}, fh)
    write_bundle_integrity_manifest(bd, ticker, hz)
    prov = verify_artifact_against_manifest(bd, ticker, hz, "xgb", name)
    assert prov["verified"] is True
    assert prov["ticker"] == ticker and prov["horizon"] == hz
    raw = bytearray((bd / name).read_bytes())
    raw[-1] ^= 0x01
    (bd / name).write_bytes(bytes(raw))
    with pytest.raises(ArtifactVerificationError) as ei:
        verify_artifact_against_manifest(bd, ticker, hz, "xgb", name)
    assert ei.value.reason_code == "ARTIFACT_HASH_MISMATCH"


def test_item4_all_governed_loaders_call_verifier_before_deserialization():
    """AST lock: every pickle.load/torch.load in ml_predict serve loaders is
    preceded by a _verify_governed_artifact call in the same function."""
    import ast
    from pathlib import Path

    src = (Path(__file__).resolve().parent.parent / "ml_predict.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    governed = {
        "_load_xgb", "_load_meta", "_load_transformer", "_load_lstm",
        "_predict_xgb_movement_heads",
    }
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.FunctionDef) or fn.name not in governed:
            continue
        verify_line = None
        deser_line = None
        for node in ast.walk(fn):
            if isinstance(node, ast.Call):
                f = node.func
                if isinstance(f, ast.Name) and f.id == "_verify_governed_artifact":
                    if verify_line is None or node.lineno < verify_line:
                        verify_line = node.lineno
                if isinstance(f, ast.Attribute) and f.attr == "load" and isinstance(
                    f.value, ast.Name
                ) and f.value.id in ("pickle", "torch"):
                    if deser_line is None or node.lineno < deser_line:
                        deser_line = node.lineno
        assert verify_line is not None, f"{fn.name}: no _verify_governed_artifact call"
        if deser_line is not None:
            assert verify_line < deser_line, (
                f"{fn.name}: deserialization at line {deser_line} precedes "
                f"verification at line {verify_line}"
            )


def test_provenance_no_serving_behavior_change():
    """Required test 9: the builder is read-only — no registry writes, no model
    load calls; signals builds it as the first statement inside the scopes."""
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    tree = ast.parse((root / "ml_predict.py").read_text(encoding="utf-8"))
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "build_model_serving_provenance"
    )
    for node in ast.walk(fn):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            assert "_registry" not in node.id
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert not node.func.id.startswith("_load_"), (
                f"model load call {node.func.id} in provenance builder"
            )
    sig_src = (root / "signals.py").read_text(encoding="utf-8")
    i_scope = sig_src.index("with guest_anchor_context_scope(_guest_anchor), ml_bundle_ticker_scope(")
    i_build = sig_src.index("model_serving_provenance = build_model_serving_provenance(ticker)")
    i_seq = sig_src.index("shared_sequence_context = None")
    assert i_scope < i_build < i_seq
