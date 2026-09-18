"""No-fallback inventory items 2-6: unknown-selector / missing-identity fallbacks that
silently substituted a valid-looking default instead of failing closed.

Each producer here has exactly one real caller path in the repo, and that path always
supplies a value drawn from the same enumerated set the lookup dict defines -- so the old
default branch was dead in production but still a live hazard: any future caller (or a
typo, or drift between two independently-maintained lists) would have silently gotten
wrong behavior mislabeled as a known case, instead of a visible failure.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# --- Item 2: unknown similarity ordering preset must fail, not silently mean "none relaxed" ---

def test_run_order_variant_rejects_unknown_preset():
    from adaptive_similarity_engine import run_order_variant

    with pytest.raises(ValueError, match="unknown ordering preset"):
        run_order_variant(
            db=None,
            preset="not_a_real_preset",
            ticker="SPY",
            timeframe="1c",
            zone="above",
            vwap_side="above",
            nearest_above_dist=1.0,
            nearest_below_dist=1.0,
        )


def test_run_order_variant_accepts_known_presets():
    from adaptive_similarity_engine import ORDERING_PRESETS

    # every known preset must still resolve to its own relaxed-feature set, not raise
    for preset, expected in ORDERING_PRESETS.items():
        assert ORDERING_PRESETS[preset] == expected


# --- Items 3-4: bucket label out of sync with _BUCKET_INDEX must fail, not silently score
# as maximally-distant (-99) ---

def test_bucket_adjacency_score_rejects_out_of_sync_label(monkeypatch):
    import adaptive_similarity_engine as sim

    # simulate drift: dist_bucket() returns labels _BUCKET_INDEX doesn't know about
    # (different per input, so the rb == ab exact-match short-circuit doesn't hide it)
    monkeypatch.setattr(sim, "dist_bucket", lambda d: f"unknown_bucket_{d}")
    with pytest.raises(ValueError, match="out of sync"):
        sim._bucket_adjacency_score(1.5, 3.0)


def test_bucket_adjacency_score_known_buckets_still_work():
    import adaptive_similarity_engine as sim

    # same bucket => exact match
    assert sim._bucket_adjacency_score(0.5, 0.7) == 1.0
    # adjacent buckets ("0-1" idx 0, "1-2" idx 1) => adjacent credit
    assert sim._bucket_adjacency_score(0.5, 1.5) == 0.5
    # both missing => match
    assert sim._bucket_adjacency_score(None, None) == 1.0
    # one missing => no match
    assert sim._bucket_adjacency_score(None, 1.5) == 0.0


# --- Item 5: unknown weight band must fail, not silently get weight 1.0 (MEDIUM's weight) ---

def test_weights_for_band_rejects_unknown_band():
    from similarity_feature_search import weights_for_band

    with pytest.raises(ValueError, match="unknown weight band"):
        weights_for_band("NOT_A_REAL_BAND")


def test_weights_for_band_known_bands_still_work():
    from similarity_feature_search import WEIGHT_BAND_SCALARS, weights_for_band

    for band, scalar in WEIGHT_BAND_SCALARS.items():
        w = weights_for_band(band)
        assert w and all(v == scalar for v in w.values())


# --- Item 6: missing endpoint identity must fail, not silently become "api" ---

def test_record_schwab_http_response_rejects_empty_endpoint():
    from api_pressure import record_schwab_http_response

    class _Resp:
        status_code = 429

    with pytest.raises(ValueError, match="non-empty identity label"):
        record_schwab_http_response(_Resp(), "")


def test_record_schwab_http_response_records_real_endpoint():
    import api_pressure

    class _Resp:
        status_code = 429

    api_pressure._events.clear()
    api_pressure.record_schwab_http_response(_Resp(), "quote:SPY")
    assert api_pressure._events[-1][2] == "quote:SPY"


def test_signals_pred_override_rejects_missing_source():
    """The /api/prediction/override writer (server.py) always stamps a 'source' key
    (client-supplied or its own 'user' default) before storing an override. A dict
    reaching signals.py without one is a producer-contract violation, not something to
    paper over with a second, inconsistent 'api' default."""
    from signals import _require_pred_override_source

    with pytest.raises(ValueError, match="missing its source provenance"):
        _require_pred_override_source({"direction": "up", "source": None})
    with pytest.raises(ValueError, match="missing its source provenance"):
        _require_pred_override_source({"direction": "up", "source": ""})


def test_signals_pred_override_accepts_real_source():
    from signals import _require_pred_override_source

    assert _require_pred_override_source({"direction": "up", "source": "user"}) == "user"
    assert _require_pred_override_source({"direction": "up", "source": "manual"}) == "manual"
