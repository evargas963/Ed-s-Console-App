"""Stage 1 causal label reconstruction + adversarial/mutation guards.

Proves the production fixed-horizon label reconstructs deterministically from
immutable source bars, and that the causal contract fails closed on lookahead,
timestamp aliasing, duplicate anchors, cross-ticker attachment, horizon
confusion, and source-row mutation. Research-only; no production effect.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from research.stage1_target_foundation.causal_label_contract import (
    BAR_SECONDS,
    Bar,
    CausalLabelError,
    anchor_bar_for,
    realized_mfe_mae,
    reconstruct_fixed_horizon_label,
)

GOLDEN = Path(__file__).resolve().parents[1] / "research" / "stage1_target_foundation" / "golden"


def _load(name: str) -> dict:
    return json.loads((GOLDEN / name).read_text(encoding="utf-8"))


def _bars() -> list[Bar]:
    return [Bar(**b) for b in _load("golden_bars_v1.json")["bars"]]


def test_fixed_horizon_labels_reconstruct_from_golden():
    """Module output must equal the INDEPENDENTLY computed golden labels."""
    bars = _bars()
    for c in _load("golden_labels_v1.json")["fixed_horizon_cases"]:
        got = reconstruct_fixed_horizon_label(
            bars, c["ticker"], c["anchor_ts_utc"], c["horizon"],
            c["threshold_pts"], now_ts_utc=c["now_ts_utc"],
        )
        assert got["outcome"] == c["expected_outcome"], (c["horizon"], got)
        assert got["pts"] == c["expected_pts"], (c["horizon"], got)
        assert got["forward_bar_start"] == c["expected_forward_bar_start"]


def test_realized_mfe_mae_reconstructs_from_golden():
    bars = _bars()
    m = _load("golden_labels_v1.json")["mfe_mae_case"]
    got = realized_mfe_mae(bars, m["ticker"], m["anchor_ts_utc"], m["horizon"],
                           now_ts_utc=m["now_ts_utc"])
    assert got["mfe"] == m["expected_mfe"]
    assert got["mae"] == m["expected_mae"]


def test_lookahead_guard_fails_closed():
    """Requesting a label before its forward bar completes is a lookahead error."""
    bars = _bars()
    anchor = 1767623700
    # 60c forward completes at anchor+3600+60; observing at anchor+100 is lookahead
    with pytest.raises(CausalLabelError, match="lookahead"):
        reconstruct_fixed_horizon_label(bars, "SPY", anchor, "60c", 0.65,
                                        now_ts_utc=anchor + 100)


def test_timestamp_aliasing_fails_closed():
    bars = _bars() + [Bar("SPY", 1767623701, 1, 1, 1, 1)]  # not aligned to 60s
    with pytest.raises(CausalLabelError, match="aliasing"):
        anchor_bar_for(bars, "SPY", 1767623700)


def test_duplicate_anchor_fails_closed():
    bars = _bars()
    dup = bars[0]
    bars2 = bars + [Bar(dup.ticker, dup.bar_start_ts_utc, 9, 9, 9, 9)]
    with pytest.raises(CausalLabelError, match="duplicate anchor"):
        anchor_bar_for(bars2, "SPY", 1767623700)


def test_horizon_confusion_fails_closed():
    bars = _bars()
    with pytest.raises(CausalLabelError, match="unknown horizon"):
        reconstruct_fixed_horizon_label(bars, "SPY", 1767623700, "7c", 0.1,
                                        now_ts_utc=1767630000)


def test_cross_ticker_isolation():
    """The QQQ bar at the same start must not become SPY's anchor, and a ticker
    with no bars is not reconstructable."""
    bars = _bars()
    spy_anchor = anchor_bar_for(bars, "SPY", 1767623700)
    assert spy_anchor is not None and spy_anchor.ticker == "SPY"
    got = reconstruct_fixed_horizon_label(bars, "IWM", 1767623700, "1c", 0.1,
                                          now_ts_utc=1767630000)
    assert got["reconstructable"] is False


def test_source_row_mutation_changes_label():
    """The label is bound to the specific forward source row; mutating that row's
    close must change the outcome (no order-invariance / no stale reuse)."""
    bars = _bars()
    base = reconstruct_fixed_horizon_label(bars, "SPY", 1767623700, "1c", 0.10,
                                           now_ts_utc=1767630000)
    assert base["outcome"] == "up"
    mutated = []
    for b in bars:
        if b.ticker == "SPY" and b.bar_start_ts_utc == base["forward_bar_start"]:
            mutated.append(Bar(b.ticker, b.bar_start_ts_utc, b.open, b.high, b.low, 499.00))
        else:
            mutated.append(b)
    after = reconstruct_fixed_horizon_label(mutated, "SPY", 1767623700, "1c", 0.10,
                                            now_ts_utc=1767630000)
    assert after["outcome"] == "down", after
    assert after["pts"] != base["pts"]


def test_session_authority_is_ts_utc_not_stored_clock():
    """The golden premarket bar (08:00 ET) must classify NON-RTH via the canonical
    ts_utc->DST-ET authority — never a stored et_hour column."""
    from time_et import is_rth_ts_utc
    assert is_rth_ts_utc(1767618000) is False  # 08:00 ET premarket
    assert is_rth_ts_utc(1767623700) is True   # 09:35 ET RTH


def test_missing_forward_bar_yields_null_not_error():
    """A missing forward bar is a NULL label (reconstructable), not a crash."""
    bars = [b for b in _bars() if not (b.ticker == "SPY" and b.bar_start_ts_utc == 1767623760)]
    got = reconstruct_fixed_horizon_label(bars, "SPY", 1767623700, "1c", 0.10,
                                          now_ts_utc=1767630000)
    assert got["outcome"] is None and got["reconstructable"] is True


def test_threshold_zero_fails_closed_to_flat():
    bars = _bars()
    got = reconstruct_fixed_horizon_label(bars, "SPY", 1767623700, "1c", 0.0,
                                          now_ts_utc=1767630000)
    assert got["outcome"] == "flat"
