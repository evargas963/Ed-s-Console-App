"""RC-322 — the pre-open exits must CARRY the canonical snapshot, not recompute it.

`build_live_snapshot` consumes the Phase 2A snapshot when `canonical` is supplied, and every
live serving path supplies it. But it returns early at two guards — session date in the
future, and clock before the RTH open — and both of those called
`build_premarket_snapshot(ticker, bars, session_date, config)` with NO canonical argument.
That builder then ran `get_previous_day_levels` and `get_overnight_levels` itself, so on
those paths the canonical snapshot was built, materialized on /api/levels, and discarded by
the surface standing next to it: a second faucet for overnight and prior-day levels.

These drive the REAL builders on ONE canonical snapshot and require identical values.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from liquidity_value_engine import (  # noqa: E402
    PlaybookConfig,
    build_live_snapshot,
    build_premarket_snapshot,
    build_price_level_snapshot,
)
from time_et import ET  # noqa: E402

from tests.conftest import most_recent_trading_day_et  # noqa: E402

#: canonical level id -> (raw_levels family, key) as the builders publish them.
_PHASE2A_IDS = {
    "PDH": ("prev_day", "pdh"), "PDL": ("prev_day", "pdl"), "PDC": ("prev_day", "pdc"),
    "PD_POC": ("prev_day", "pd_poc"), "PD_VAH": ("prev_day", "pd_vah"),
    "PD_VAL": ("prev_day", "pd_val"),
    "OVERNIGHT_HIGH": ("overnight", "overnight_high"),
    "OVERNIGHT_LOW": ("overnight", "overnight_low"),
}


def _published(out) -> dict:
    """Flatten SnapshotOutput.raw_levels to {canonical_id: value} for the Phase 2A families."""
    raw = out.raw_levels or {}
    got = {}
    for level_id, (fam, key) in _PHASE2A_IDS.items():
        v = (raw.get(fam) or {}).get(key)
        if v is not None:
            got[level_id] = v
    return got


def _bars(session: date, n: int = 120) -> list:
    """A real-shaped RTH series on a real trading day, plus a prior session and overnight."""
    out = []
    for day_off, start_h in ((1, 9), (0, 9)):          # prior session, then this one
        d = session - timedelta(days=day_off)
        for i in range(n):
            ts = datetime(d.year, d.month, d.day, start_h, 30, tzinfo=ET) + timedelta(minutes=i)
            px = 100.0 + (i % 17) * 0.05 + day_off * 0.3
            out.append({"datetime": ts.timestamp(), "open": px, "high": px + 0.08,
                        "low": px - 0.08, "close": px, "volume": 1000.0 + i})
    return out


def _canonical(session: date, bars: list):
    return build_price_level_snapshot(
        "SPY", session, bars, bar_source="test_fixture", config=PlaybookConfig(),
        generation=1)


def test_premarket_carries_every_phase2a_level_unchanged():
    """One computation, two builders, identical values."""
    session = most_recent_trading_day_et()
    bars = _bars(session)
    canon = _canonical(session, bars)

    carried = build_premarket_snapshot("SPY", session, PlaybookConfig(), canonical=canon)
    got = _published(carried)
    for level_id in _PHASE2A_IDS:
        want = canon.price(level_id)
        if want is None:
            assert level_id not in got, (
                f"{level_id} is absent from the canonical snapshot but present on the "
                f"premarket surface — absence was substituted (RC-68)")
        else:
            assert got.get(level_id) == want, (
                f"{level_id}: premarket published {got.get(level_id)!r} while the canonical "
                f"snapshot holds {want!r} — a second faucet (RC-322)")


def test_the_live_builder_before_the_open_carries_the_snapshot():
    """Before the session's open the live builder returns the premarket shape, from the same
    snapshot (ONE-09: no recompute path remains)."""
    session = most_recent_trading_day_et()
    canon = _canonical(session, _bars(session))
    pre_open = datetime(session.year, session.month, session.day, 9, 0, tzinfo=ET)
    out = build_live_snapshot("SPY", PlaybookConfig(), canonical=canon, now=pre_open)
    assert out.snapshot_type.value == "premarket"
    got = _published(out)
    for level_id in _PHASE2A_IDS:
        want = canon.price(level_id)
        if want is not None:
            assert got.get(level_id) == want, (
                f"{level_id} diverged through the pre-open exit: {got.get(level_id)!r} "
                f"vs canonical {want!r}")
