"""MODEL-04 serve-eligibility policy locks (operator-approved 2026-07-10)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from model_serve_policy import (
    DIRECT_SERVE_BLOCKING_STATUSES,
    MODEL_SERVE_POLICY_VERSION,
    NOT_PROVEN,
    REVALIDATION_REQUIRED,
    SERVE_APPROVED,
    SERVE_TEMPORARILY_WITHHELD,
    bundle_serve_eligibility,
    classify_trained_at,
    parse_trained_at,
)


def test_policy_version_and_blocking_set():
    assert MODEL_SERVE_POLICY_VERSION == "1.0.0"
    assert DIRECT_SERVE_BLOCKING_STATUSES == {SERVE_TEMPORARILY_WITHHELD, NOT_PROVEN}
    assert REVALIDATION_REQUIRED not in DIRECT_SERVE_BLOCKING_STATUSES
    assert SERVE_APPROVED not in DIRECT_SERVE_BLOCKING_STATUSES


def test_pre_correctness_vintages_withheld():
    """April-era manifests (the ten pre-correctness bundles) must be withheld."""
    for t, d in (("NVDA", date(2026, 4, 15)), ("META", date(2026, 4, 15)),
                 ("AAPL", date(2026, 4, 30)), ("SPY", date(2026, 5, 27))):
        status, reason = classify_trained_at(t, d)
        assert status == SERVE_TEMPORARILY_WITHHELD, (t, d)
        assert "must not be directly served" in reason


def test_revalidation_band_serves_with_explicit_status():
    for t, d in (("PLTR", date(2026, 5, 28)), ("AVGO", date(2026, 5, 30)),
                 ("GOOG", date(2026, 5, 30)), ("SMCI", date(2026, 5, 31))):
        status, reason = classify_trained_at(t, d)
        assert status == REVALIDATION_REQUIRED, (t, d)
        assert "revalidation" in reason


def test_approved_base_bundles_serve():
    for t, d in (("SPY", date(2026, 6, 4)), ("QQQ", date(2026, 6, 4)),
                 ("IWM", date(2026, 6, 9))):
        status, _ = classify_trained_at(t, d)
        assert status == SERVE_APPROVED, (t, d)


def test_post_correctness_non_base_requires_revalidation():
    status, reason = classify_trained_at("NVDA", date(2026, 6, 20))
    assert status == REVALIDATION_REQUIRED
    assert "no operator serve approval" in reason


def test_missing_or_malformed_provenance_not_proven():
    assert classify_trained_at("SPY", None)[0] == NOT_PROVEN
    assert parse_trained_at(None) is None
    assert parse_trained_at("not-a-date") is None
    assert parse_trained_at("2026-06-04 07:51:43") == date(2026, 6, 4)
    assert parse_trained_at("2026-06-04T07:51:43") == date(2026, 6, 4)
    assert parse_trained_at("2026-06-04") == date(2026, 6, 4)


def _bundle(tmp_path: Path, ticker: str, hz: str, trained_at) -> Path:
    d = tmp_path / ticker
    d.mkdir(parents=True, exist_ok=True)
    meta = {"trained_at": trained_at} if trained_at is not None else {}
    (d / f"xgb_{ticker}_{hz}_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return d


def test_bundle_eligibility_reads_manifest(tmp_path):
    d = _bundle(tmp_path, "SPY", "1c", "2026-06-04 04:29:57")
    e = bundle_serve_eligibility("SPY", "1c", d)
    assert e["status"] == SERVE_APPROVED
    assert e["direct_serve_blocked"] is False
    assert e["trained_at"] == "2026-06-04"
    assert e["provenance_source"] == "xgb_meta_manifest"


def test_bundle_eligibility_missing_manifest_fails_closed(tmp_path):
    d = tmp_path / "NVDA"
    d.mkdir()
    e = bundle_serve_eligibility("NVDA", "1c", d)
    assert e["status"] == NOT_PROVEN
    assert e["direct_serve_blocked"] is True
    assert e["provenance_source"] == "xgb_meta_manifest_missing"


def test_bundle_eligibility_malformed_manifest_fails_closed(tmp_path):
    d = tmp_path / "NVDA"
    d.mkdir()
    (d / "xgb_NVDA_1c_meta.json").write_text("{not json", encoding="utf-8")
    e = bundle_serve_eligibility("NVDA", "1c", d)
    assert e["status"] == NOT_PROVEN
    assert e["direct_serve_blocked"] is True
    assert e["provenance_source"] == "xgb_meta_manifest_unreadable"


def test_bundle_eligibility_malformed_timestamp_fails_closed(tmp_path):
    d = _bundle(tmp_path, "NVDA", "1c", "sometime in spring")
    e = bundle_serve_eligibility("NVDA", "1c", d)
    assert e["status"] == NOT_PROVEN
    assert e["direct_serve_blocked"] is True


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
