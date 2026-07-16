"""Stage 1 expanded golden dataset (Objective G): DST / session-boundary / holiday
/ half-day / missing-minute / duplicate / synthetic-provenance / barrier cases.

Expectations are hand-specified in golden_cases_v2.json and independent of the
implementation under test; the Python tz database materializes each CT wall time.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from research.stage1_target_foundation.causal_label_contract import (
    Bar,
    CausalLabelError,
    realized_mfe_mae,
    reconstruct_fixed_horizon_label,
)
from research.stage1_target_foundation.ct_session import classify_session, ct_clock
from research.stage1_target_foundation.target_registry import load_registry

CT = ZoneInfo("America/Chicago")
GOLDEN = Path(__file__).resolve().parents[1] / "research" / "stage1_target_foundation" / "golden"


def _cases() -> dict:
    return json.loads((GOLDEN / "golden_cases_v2.json").read_text(encoding="utf-8"))


def _ct_epoch(iso_min: str) -> float:
    dt = datetime.strptime(iso_min, "%Y-%m-%dT%H:%M").replace(tzinfo=CT)
    return dt.timestamp()


@pytest.mark.parametrize("case", _cases()["session_cases"], ids=lambda c: c["label"])
def test_golden_session_cases(case):
    ts = _ct_epoch(case["ct"])
    assert classify_session(ts) == case["expected_session"], case["label"]
    if "expected_tz" in case:
        assert ct_clock(ts).strftime("%Z") == case["expected_tz"], case["label"]


# ---- label edge cases from a self-contained contiguous bar set ----
_A = 1767623700  # aligned RTH anchor bar start


def _path(drop: int | None = None, synthetic_at: int | None = None):
    out = [Bar("SPY", _A, 500.0, 500.0, 500.0, 500.00)]
    for k in range(1, 7):
        s = _A + k * 60
        if s == drop:
            continue
        out.append(Bar("SPY", s, 500.0, 500.0 + 0.1 * k, 500.0 - 0.05 * k,
                       500.0 + 0.10 * k, synthetic=(s == synthetic_at)))
    return out


def test_missing_forward_bar_is_null_reconstructable():
    # anchor bar completes at _A (end _A); 1c forward is _A+60, which is absent
    bars = [Bar("SPY", _A - 60, 500.0, 500.0, 500.0, 500.0)]
    got = reconstruct_fixed_horizon_label(bars, "SPY", _A, "1c", 0.1, now_ts_utc=_A + 3600)
    assert got["outcome"] is None and got["reconstructable"] is True


def test_missing_interior_bar_mfe_fails_closed():
    got = realized_mfe_mae(_path(drop=_A + 180), "SPY", _A + 60, "5c", now_ts_utc=_A + 3600)
    assert got["reconstructable"] is False and got["mfe"] is None


def test_duplicate_anchor_raises():
    bars = _path() + [Bar("SPY", _A, 9, 9, 9, 9)]
    with pytest.raises(CausalLabelError, match="duplicate anchor"):
        reconstruct_fixed_horizon_label(bars, "SPY", _A + 30, "1c", 0.1, now_ts_utc=_A + 3600)


def test_synthetic_provenance_reported_but_label_unchanged():
    c = _cases()["synthetic_provenance_case"]
    # anchor bar completes at _A; 1c forward is _A+60 (flagged synthetic)
    bars = [
        Bar("SPY", _A - 60, 500.0, 500.0, 500.0, c["anchor_close"]),
        Bar("SPY", _A + 60, 500.0, 500.6, 500.0, c["forward_close"], synthetic=True),
    ]
    got = reconstruct_fixed_horizon_label(bars, "SPY", _A, "1c",
                                          c["threshold_pts"], now_ts_utc=_A + 3600)
    assert got["pts"] == c["expected_pts"]
    assert got["outcome"] == c["expected_outcome"]
    assert got["forward_synthetic"] is True
    assert got["synthetic_involved"] is c["expected_synthetic_involved"]


def test_barrier_idealized_fill_marked_research_assumption():
    b = _cases()["barrier_research_assumption"]
    reg = load_registry()
    t = next(t for t in reg["targets"] if t["target_id"] == b["registry_target_id"])
    assert t["promotion_status"] == b["expected_registry_status"]
    assert any(b["expected_limitation_substring"] in lim for lim in t["known_limitations"])
