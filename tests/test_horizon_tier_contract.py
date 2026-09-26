"""Hard contract: primary vs secondary governed horizons (authoritative vs diagnostics-only)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_partition_and_constants():
    from ml_horizon import (
        ALL_GOVERNED_HORIZONS,
        ML_HORIZON_SLUGS,
        PRIMARY_DECISION_HORIZONS,
        SECONDARY_SUPPORT_HORIZONS,
    )

    assert ALL_GOVERNED_HORIZONS == ML_HORIZON_SLUGS
    assert ALL_GOVERNED_HORIZONS == PRIMARY_DECISION_HORIZONS
    assert PRIMARY_DECISION_HORIZONS == ("1c", "5c", "15c", "60c")
    assert SECONDARY_SUPPORT_HORIZONS == ()
    assert set(ALL_GOVERNED_HORIZONS) == set(PRIMARY_DECISION_HORIZONS) | set(
        SECONDARY_SUPPORT_HORIZONS
    )
    assert not (set(PRIMARY_DECISION_HORIZONS) & set(SECONDARY_SUPPORT_HORIZONS))








def test_live_stack_skips_missing_secondary_active_bundles(monkeypatch):
    import ml_horizon
    import signals
    import ml_predict

    governed = ("1c", "3c", "5c", "8c")
    primary = ("1c", "5c")
    secondary = ("3c", "8c")
    monkeypatch.setattr(ml_horizon, "ALL_GOVERNED_HORIZONS", governed)
    monkeypatch.setattr(ml_horizon, "ML_HORIZON_SLUGS", governed)
    monkeypatch.setattr(ml_horizon, "PRIMARY_DECISION_HORIZONS", primary)
    monkeypatch.setattr(ml_horizon, "SECONDARY_SUPPORT_HORIZONS", secondary)
    monkeypatch.setattr(signals, "ALL_GOVERNED_HORIZONS", governed)
    monkeypatch.setattr(signals, "PRIMARY_DECISION_HORIZONS", primary)
    monkeypatch.setattr(signals, "SECONDARY_SUPPORT_HORIZONS", secondary)

    def _fake_model_dir_for_ticker(_ticker: str):
        hz = ml_predict.get_ml_infer_horizon_slug()
        if hz in ("3c", "8c"):
            raise FileNotFoundError(f"no active {hz} bundle")
        return ROOT

    monkeypatch.setattr(ml_predict, "_model_dir_for_ticker", _fake_model_dir_for_ticker)

    horizons, skipped = signals._live_model_stack_horizons("SPY")

    assert horizons == ("1c", "5c")
    assert set(skipped) == {"3c", "8c"}
    assert skipped["3c"]["provenance"] == "skipped_missing_active_bundle"
    assert skipped["3c"]["non_authoritative"] is True


@pytest.mark.parametrize("slug", ("3c", "8c", "13c"))
def test_normalize_ml_horizon_slug_rejects_retired_secondary(slug: str):
    from ml_horizon import normalize_ml_horizon_slug

    with pytest.raises(ValueError, match="invalid slug"):
        normalize_ml_horizon_slug(slug)


def test_predict_all_horizons_keys_match_primary_only(monkeypatch):
    from ml_horizon import PRIMARY_DECISION_HORIZONS
    import ml_predict

    monkeypatch.setattr(ml_predict, "live_inference_horizon_slug", lambda: "1c")
    monkeypatch.setattr(
        ml_predict,
        "predict_direction",
        lambda *args, **kwargs: {"direction": "up"},
    )

    out = ml_predict.predict_all_horizons({})

    assert set(out.keys()) == set(PRIMARY_DECISION_HORIZONS)


def test_outcome_bar_specs_four_primary_slugs():
    from horizon_outcomes import OUTCOME_BAR_SPECS

    assert len(OUTCOME_BAR_SPECS) == 4
    slugs = tuple(odir[len("outcome_") :] for odir, _opt, _n in OUTCOME_BAR_SPECS)
    assert slugs == ("1c", "5c", "15c", "60c")




