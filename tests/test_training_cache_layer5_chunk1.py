"""Layer 5 training_cache.py chunk-1: artifact SHA map + manifest fail-closed locks."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from training_cache import (
    _meta_required_positive_int,
    compute_artifact_sha256_map,
    file_sha256_hex,
    parallel_artifact_basenames,
    trained_at_age_days,
    validate_manifest_artifact_hashes,
)


def test_compute_artifact_sha256_map_present_file_returns_hex(tmp_path: Path):
    artifact = tmp_path / "xgb_SPY_5c.pkl"
    artifact.write_bytes(b"model-bytes")
    names = ["xgb_SPY_5c.pkl"]
    out = compute_artifact_sha256_map(tmp_path, names)
    assert set(out.keys()) == set(names)
    assert out["xgb_SPY_5c.pkl"] == file_sha256_hex(artifact)
    assert not out["xgb_SPY_5c.pkl"].startswith("MISSING:")


def test_compute_artifact_sha256_map_missing_file_returns_missing_marker(tmp_path: Path):
    missing = tmp_path / "xgb_SPY_5c_meta.json"
    out = compute_artifact_sha256_map(tmp_path, ["xgb_SPY_5c_meta.json"])
    assert out["xgb_SPY_5c_meta.json"] == f"MISSING:{missing.resolve()}"


def test_validate_manifest_artifact_hashes_rejects_missing_marker(tmp_path: Path):
    ticker = "SPY"
    names = parallel_artifact_basenames(ticker, horizon_suffix="5c")
    present = tmp_path / names[0]
    present.write_bytes(b"x")
    missing = tmp_path / names[1]
    artifact_sha256 = compute_artifact_sha256_map(tmp_path, names)
    assert artifact_sha256[names[1]] == f"MISSING:{missing.resolve()}"

    manifest = {"artifact_sha256": artifact_sha256}
    ok, reason = validate_manifest_artifact_hashes(
        manifest, tmp_path, ticker, "parallel", horizon_suffix="5c"
    )
    assert ok is False
    assert reason.startswith("missing_file:") or reason.startswith("hash_mismatch:")


def test_trained_at_age_days_empty_string_fail_closed_stale():
    assert trained_at_age_days("") == pytest.approx(1e9)


def test_meta_required_positive_int_rejects_missing_non_int_non_positive():
    assert _meta_required_positive_int({}, "n_features_5m") is None
    assert _meta_required_positive_int({"n_features_5m": "bad"}, "n_features_5m") is None
    assert _meta_required_positive_int({"n_features_5m": 0}, "n_features_5m") is None
    assert _meta_required_positive_int({"n_features_5m": -1}, "n_features_5m") is None
    assert _meta_required_positive_int({"n_features_5m": 3}, "n_features_5m") == 3


def test_trained_at_age_days_parses_iso():
    now = datetime(2026, 5, 19, 12, 0, 0, tzinfo=timezone.utc)
    age = trained_at_age_days("2026-05-18T12:00:00Z", now=now)
    assert 0.9 < age < 1.1
