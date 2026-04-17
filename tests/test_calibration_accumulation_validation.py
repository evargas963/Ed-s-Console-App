"""Re-prove deterministic production-path accumulation gates in isolation (tmp DB)."""

from __future__ import annotations

from pathlib import Path

import pytest

import calibration.run_production_accumulation_validation as accum


def test_production_accumulation_harness_passes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = tmp_path / "acc.db"
    rep = tmp_path / "rep.json"
    monkeypatch.setattr(accum, "OUT_DB", db)
    monkeypatch.setattr(accum, "OUT_REPORT", rep)

    import db as db_mod

    monkeypatch.setattr(db_mod, "DB_PATH", db)

    out = accum.run()
    assert out["binary_pass"] is True
    assert out["counts"]["trusted_rows"] == accum.N_ACCUM
    assert accum.N_ACCUM >= 30
    assert out["counts"]["duplicate_key_groups"] == 0
    assert out["outcome_join_first"]["verification_fail"] == 0
    assert out["unsafe_non_exact_join_rows_trusted"] == 0
    assert out["pass_gates"]["anchor_all_trusted_anchored"] is True
