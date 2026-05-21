"""Re-prove deterministic production-path accumulation gates in isolation (tmp DB)."""

from __future__ import annotations

from pathlib import Path

import pytest

import calibration.run_production_accumulation_validation as accum


def test_production_accumulation_harness_passes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Production _TICKERS_ROT is (SPY*30 + QQQ*30 + IWM*30 + DIA*30) = 120.
    # In environments that don't have every ticker trained (e.g. DIA model bundle
    # absent in local dev), restrict the rotation to whatever tickers ARE trained
    # — the harness mechanism is what's being verified, not coverage of every
    # production ticker. At least 1 ticker present is required; if zero, real fail.
    repo_root = Path(__file__).resolve().parents[1]
    full_set = set(accum._TICKERS_ROT)
    model_roots = (repo_root / "models" / "active_1c", repo_root / "models" / "active")
    present = sorted(
        ticker for ticker in full_set
        if any((root / ticker).is_dir() for root in model_roots)
    )
    assert present, (
        f"accumulation harness needs at least one trained 1c model bundle from "
        f"{sorted(full_set)} present under {[str(r) for r in model_roots]}"
    )

    per_ticker = 30
    restricted_rot = []
    for tk in present:
        restricted_rot.extend([tk] * per_ticker)
    monkeypatch.setattr(accum, "_TICKERS_ROT", restricted_rot)
    monkeypatch.setattr(accum, "N_ACCUM", len(restricted_rot))

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
