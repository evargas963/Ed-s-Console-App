"""Stage 1 causal label reconstruction + adversarial/mutation guards.

Proves the production fixed-horizon label reconstructs deterministically from
immutable source bars, and that the causal contract fails closed on lookahead,
timestamp aliasing, duplicate anchors, cross-ticker attachment, horizon
confusion, and source-row mutation. Research-only; no production effect.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from research.stage1_target_foundation.causal_label_contract import (
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


# ---- Objective B: session crossover is ADVISORY, never a silent guard ----

# 2026-01-05 (CST). RTH close 15:00 CT = 21:00 UTC. A 14:59 CT anchor bar with a
# 1c forward bar at 15:01 CT crosses RTH -> afterhours.
_ANCHOR_1459_CT = 1767646740   # 20:59 UTC = 14:59 CT bar start (RTH)
_T_1500_CT = 1767646800        # 21:00 UTC = observation just past anchor close
_FWD_1501_CT = 1767646860      # 21:01 UTC = 15:01 CT forward bar (afterhours)


def _crossover_bars():
    return [
        Bar("SPY", _ANCHOR_1459_CT, 500.0, 500.2, 499.9, 500.00),
        Bar("SPY", _FWD_1501_CT, 500.1, 500.6, 500.0, 500.50),
    ]


def test_session_crossover_reported_but_label_formula_unchanged():
    """A forward bar in after-hours must STILL produce the production label
    (forward_close - anchor_close), and the crossover is reported advisory-only."""
    bars = _crossover_bars()
    got = reconstruct_fixed_horizon_label(bars, "SPY", _T_1500_CT, "1c", 0.10,
                                          now_ts_utc=1767650000)
    # production formula is untouched by session: pts = 500.50 - 500.00
    assert got["pts"] == 0.50
    assert got["outcome"] == "up"
    # advisory crossover is surfaced, not guarded
    assert got["anchor_session"] == "rth"
    assert got["forward_session"] == "afterhours"
    assert got["session_crossover"] is True


def test_advisory_crossover_never_nulls_the_label():
    """The advisory must not change reconstructability or null the outcome."""
    bars = _crossover_bars()
    got = reconstruct_fixed_horizon_label(bars, "SPY", _T_1500_CT, "1c", 0.10,
                                          now_ts_utc=1767650000)
    assert got["reconstructable"] is True
    assert got["outcome"] is not None


# ---- Objective H: MFE/MAE fails closed on an incomplete path ----

_A = 1767623700  # aligned anchor bar start (RTH)


def _contiguous_path(drop: int | None = None):
    """Anchor bar at _A plus 6 contiguous 1m bars (covers a 5c window)."""
    out = [Bar("SPY", _A, 500.0, 500.0, 500.0, 500.00)]
    for k in range(1, 7):
        s = _A + k * 60
        if s == drop:
            continue
        out.append(Bar("SPY", s, 500.0, 500.0 + 0.1 * k, 500.0 - 0.05 * k, 500.0 + 0.02 * k))
    return out


def test_mfe_mae_complete_path_reconstructs():
    got = realized_mfe_mae(_contiguous_path(), "SPY", _A + 60, "5c", now_ts_utc=_A + 3600)
    assert got["reconstructable"] is True
    assert got["mfe"] is not None and got["mae"] is not None
    assert got["window_bars"] == 6


def test_mfe_mae_fails_closed_on_missing_interior_bar():
    """Dropping an interior 1m bar must NULL the excursion (no partial path)."""
    got = realized_mfe_mae(_contiguous_path(drop=_A + 180), "SPY", _A + 60, "5c",
                           now_ts_utc=_A + 3600)
    assert got["mfe"] is None and got["mae"] is None
    assert got["reconstructable"] is False
    assert got["missing_bar_count"] >= 1
