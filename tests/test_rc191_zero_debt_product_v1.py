"""RC-191 / zero-debt clear: session-safe thresholds, calendar session label, vol gap reset."""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _ts(y, m, d, hh, mm) -> float:
    return datetime.datetime(y, m, d, hh, mm, tzinfo=datetime.timezone.utc).timestamp()


def test_session_safe_abs_price_moves_drops_weekend_gap():
    from research.tcn_eval_v1.runner import session_safe_abs_price_moves

    # Fri 15:58/15:59 then Mon 09:31/09:32 — weekend gap must not enter the median basis.
    ends = np.array([
        _ts(2026, 7, 24, 19, 58),  # 15:58 ET
        _ts(2026, 7, 24, 19, 59),
        _ts(2026, 7, 27, 13, 31),  # 09:31 ET Mon
        _ts(2026, 7, 27, 13, 32),
    ])
    closes = np.array([100.0, 100.1, 105.0, 105.05])  # +4.9 Fri->Mon gap
    safe = session_safe_abs_price_moves(ends, closes)
    assert len(safe) == 2
    assert np.isclose(safe[0], 0.1)
    assert np.isclose(safe[1], 0.05)
    raw = np.abs(np.diff(closes))
    assert float(np.max(raw)) > 4.0, "raw series still contains the weekend gap"
    assert 4.9 not in set(np.round(safe, 6)), "session-safe must drop the Fri->Mon step"
    assert float(np.median(safe)) < 0.2, "session-safe median excludes the gap"


def test_market_session_saturday_is_closed_not_rth():
    from db import market_session
    from ml_data_common import market_session_from_ts_utc

    # Saturday 2026-08-01 10:00 ET = 14:00 UTC
    assert market_session(10, 0, et_date="2026-08-01") == "closed"
    assert market_session(10, 0, et_date="2026-07-31") == "rth"  # Friday
    sat = datetime.datetime(2026, 8, 1, 14, 0, tzinfo=datetime.timezone.utc).timestamp()
    assert market_session_from_ts_utc(sat) == "closed"
    fri = datetime.datetime(2026, 7, 31, 14, 0, tzinfo=datetime.timezone.utc).timestamp()
    assert market_session_from_ts_utc(fri) == "rth"


def test_bar_accumulator_gap_resets_volume_delta():
    from server import _CandleAccumulator

    acc = _CandleAccumulator(bar_seconds=60, max_bars=10)
    t0 = _ts(2026, 7, 31, 14, 0)  # 10:00 ET
    acc.tick("MSFT", 500.0, t0, total_volume=1_000_000.0)
    # Same minute, +5k shares — should accumulate
    acc.tick("MSFT", 500.1, t0 + 10, total_volume=1_005_000.0)
    assert acc._current["MSFT"]["v"] == pytest.approx(5_000.0)
    # 5-minute gap with +25M shares — must NOT land on the next bar
    t_gap = t0 + 300
    acc.tick("MSFT", 501.0, t_gap, total_volume=26_005_000.0)
    cur = acc._current["MSFT"]
    assert cur["ts"] == acc._bar_start(t_gap)
    assert cur.get("v") is None
    assert cur.get("volume_source") == "schwab_quote_totalVolume_gap_reset"


def test_cost_aware_and_survival_fallback_not_raw_npdiff():
    """Structural lock: the RC-107 fallback sites must not use raw np.diff(closes)."""
    import re

    for rel in (
        "research/cost_aware_eval_v1/runner.py",
        "research/survival_eval_v1/runner.py",
    ):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "session_safe_abs_price_moves" in text, f"{rel} missing session-safe fallback"
        assert not re.search(r"np\.median\(np\.abs\(np\.diff\(closes\)\)\)", text), (
            f"{rel} still has raw np.diff fallback"
        )
