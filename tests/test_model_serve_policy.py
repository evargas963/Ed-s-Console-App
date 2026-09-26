"""MODEL-04 serve-eligibility policy locks (operator-approved 2026-07-10)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest















def _bundle(tmp_path: Path, ticker: str, hz: str, trained_at) -> Path:
    d = tmp_path / ticker
    d.mkdir(parents=True, exist_ok=True)
    meta = {"trained_at": trained_at} if trained_at is not None else {}
    (d / f"xgb_{ticker}_{hz}_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return d










def test_strict_serve_path_blocks_withheld_bundle(monkeypatch, tmp_path):
    """Direct load of a withheld-vintage bundle fails closed with the policy
    reason; no fallback dir is returned (no silent substitute)."""
    import ml_predict as mp

    d = _bundle(tmp_path, "NVDA", mp.get_ml_infer_horizon_slug(), "2026-04-15 17:51:21")
    monkeypatch.setenv("ED_XGB_STRICT_ACTIVE_ONLY", "1")
    monkeypatch.setattr(mp, "_bundle_ticker_for_artifacts", lambda t: "NVDA")
    import active_bundle_contract as abc_mod

    monkeypatch.setattr(abc_mod, "active_bundle_dir", lambda t, h, models_dir=None: d)
    monkeypatch.setattr(
        abc_mod, "check_active_bundle_complete",
        lambda t, h, bundle_dir=None, models_dir=None: {"compliant": True},
    )
    with pytest.raises(FileNotFoundError) as ei:
        mp._model_dir_for_ticker("NVDA")
    msg = str(ei.value)
    assert "MODEL_SERVE_POLICY" in msg
    assert "SERVE_TEMPORARILY_WITHHELD" in msg
    assert "must not be directly served" in msg


def test_strict_serve_path_allows_approved_and_revalidation_band(monkeypatch, tmp_path):
    import ml_predict as mp
    import active_bundle_contract as abc_mod

    hz = mp.get_ml_infer_horizon_slug()
    monkeypatch.setenv("ED_XGB_STRICT_ACTIVE_ONLY", "1")
    monkeypatch.setattr(
        abc_mod, "check_active_bundle_complete",
        lambda t, h, bundle_dir=None, models_dir=None: {"compliant": True},
    )
    d_spy = _bundle(tmp_path, "SPY", hz, "2026-06-04 04:29:57")
    monkeypatch.setattr(mp, "_bundle_ticker_for_artifacts", lambda t: "SPY")
    monkeypatch.setattr(abc_mod, "active_bundle_dir", lambda t, h, models_dir=None: d_spy)
    assert mp._model_dir_for_ticker("SPY") == d_spy

    d_pltr = _bundle(tmp_path, "PLTR", hz, "2026-05-28 20:16:40")
    monkeypatch.setattr(mp, "_bundle_ticker_for_artifacts", lambda t: "PLTR")
    monkeypatch.setattr(abc_mod, "active_bundle_dir", lambda t, h, models_dir=None: d_pltr)
    assert mp._model_dir_for_ticker("PLTR") == d_pltr  # explicit-status serve
