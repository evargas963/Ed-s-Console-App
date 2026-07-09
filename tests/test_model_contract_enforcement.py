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


# ── MODEL_SERVING_PROVENANCE_SURFACE_V1 ──────────────────────────────────────

_PROVENANCE_KEYS = {
    "requested_ticker", "bundle_ticker", "guest_anchor", "guest_anchor_ticker",
    "horizon", "bundle_dir", "bundle_complete", "missing_artifacts",
    "trained_at", "feature_schema_version", "preprocessing_version",
    "contract_match", "contract_mismatch_reason", "strict_active_only",
    "relaxation_active", "runtime_class", "model_load_status",
    "fail_closed_reason",
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
    _make_complete_bundle(tmp_path, t)
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
