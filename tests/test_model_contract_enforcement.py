"""Issue 7 continuation: all model families enforce the same metadata contract."""
from __future__ import annotations

import json













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


def test_load_lstm_verifies_lstm_meta_before_load_lstm(tmp_path, monkeypatch):
    """RC-376 (a107412 port): Item-4 lstm_meta verify precedes load_lstm — the same
    pre-deserialization boundary xgb_meta / transformer_meta already have.

    The first version of this control read ml_predict.py and compared three
    `str.index` offsets. That proves LAYOUT, not control flow: hoisting the verify
    call into a branch that never executes, or returning early between the two, leaves
    every offset in the same order and the boundary gone. The ordering is a sequence of
    EVENTS, so the events are recorded here — the verifier and the deserializing
    `load_lstm` both report into one list and the list is asserted.
    """
    import sys
    import types

    import ml_predict as mp

    seq: list[str] = []
    fake = types.ModuleType("lstm_model")
    fake.load_lstm = lambda **kw: seq.append("load_lstm") or (None, "sentinel")
    monkeypatch.setitem(sys.modules, "lstm_model", fake)

    ticker, hz = "ZZLO", "1c"
    base = tmp_path / ticker
    base.mkdir(parents=True)
    mpath = base / f"lstm_{ticker}_{hz}.pt"
    mtpath = base / f"lstm_{ticker}_{hz}_meta.json"
    mpath.write_bytes(b"pt-bytes")
    monkeypatch.setattr(mp, "_model_dir_for_ticker", lambda _t: base)
    monkeypatch.setattr(mp, "get_ml_infer_horizon_slug", lambda: hz)

    def verifier(result):
        def _v(_base, _bt, _hz, role, _fn):
            seq.append(f"verify:{role}")
            return result
        return _v

    def reset():
        mp._lstm_registry.clear()
        mp._active_bundle_dir_cache.clear()
        seq.clear()

    # 1. missing meta refuses BEFORE any verification is attempted (missing_i < meta_i)
    reset()
    monkeypatch.setattr(mp, "_verify_governed_artifact", verifier({"verified": True}))
    assert mp._load_lstm(ticker) is False
    assert seq == [], f"a refusal for absent meta ran the verifier or the loader: {seq}"

    # 2. a refusing verifier stops the load (meta_i < load_i)
    reset()
    mtpath.write_text('{"model_type":"dual_stream_lstm"}', encoding="utf-8")
    monkeypatch.setattr(mp, "_verify_governed_artifact", verifier(None))
    assert mp._load_lstm(ticker) is False
    assert "load_lstm" not in seq, f"load_lstm was entered on a refused artifact: {seq}"
    assert seq and seq[0].startswith("verify:"), seq

    # 3. control: on a verified bundle BOTH roles verify, strictly before load_lstm
    reset()
    monkeypatch.setattr(mp, "_verify_governed_artifact", verifier({"verified": True}))
    assert mp._load_lstm(ticker) is False  # sentinel model=None -> load reports failure
    assert seq == ["verify:lstm", "verify:lstm_meta", "load_lstm"], seq

    reset()


def test_load_lstm_refuses_when_meta_file_absent(tmp_path, monkeypatch):
    """RC-376: serve path refuses LSTM when lstm_*_meta.json is missing (transformer parity)."""
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




















# ── ML-PIPE Item 4 — artifact-manifest load verification (adversarial) ───────
#
# Independent reference: expected hashes are recomputed here with hashlib
# directly — never through the implementation under test.

import hashlib




def _sha256_independent(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()




def _reset_ml_predict_state(mp):
    for reg in (
        mp._xgb_registry, mp._meta_registry, mp._lstm_registry,
        mp._trans_registry, mp._xgb_movehead_registry,
    ):
        reg.clear()
    mp._artifact_verification_registry.clear()
    mp._active_bundle_dir_cache.clear()
    mp._strict_bundle_warned.clear()










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


