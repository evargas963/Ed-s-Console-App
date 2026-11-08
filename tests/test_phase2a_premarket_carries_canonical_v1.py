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

from datetime import date, datetime, timedelta
from pathlib import Path

from liquidity_value_engine import (
    PlaybookConfig,
    bars_from_candles,
    build_live_snapshot,
    build_premarket_snapshot,
    build_price_level_snapshot,
)
from micro_structure import Candle
from tests.conftest import most_recent_trading_day_et
from time_et import ET

REPO = Path(__file__).resolve().parent.parent

#: the canonical level ids the premarket zones carry
_PHASE2A_IDS = (
    "PDH",
    "PDL",
    "PDC",
    "PD_POC",
    "PD_VAH",
    "PD_VAL",
    "OVERNIGHT_HIGH",
    "OVERNIGHT_LOW",
)


def _published(out) -> dict:
    """{canonical id: value} of every level the snapshot's zones carry."""
    return {s["label"]: s["value"] for z in out.zones for s in z.source_levels}


def _bars(session: date, n: int = 120) -> list:
    """A real-shaped RTH series on a real trading day, plus a prior session and overnight."""
    out = []
    for day_off, start_h in ((1, 9), (0, 9)):  # prior session, then this one
        d = session - timedelta(days=day_off)
        for i in range(n):
            ts = datetime(d.year, d.month, d.day, start_h, 30, tzinfo=ET) + timedelta(minutes=i)
            px = 100.0 + (i % 17) * 0.05 + day_off * 0.3
            out.append(
                Candle(
                    ts=ts.timestamp(),
                    open=px,
                    high=px + 0.08,
                    low=px - 0.08,
                    close=px,
                    volume=1000.0 + i,
                )
            )
    return out


def _canonical(session: date, bars: list):
    prior_day = session - timedelta(days=1)
    held = [b for b in bars if datetime.fromtimestamp(b.ts, ET).date() == prior_day]
    # the prior session's daily candle as Schwab dates it (midnight ET), of the bars placed in it
    prior = Candle(
        ts=datetime(prior_day.year, prior_day.month, prior_day.day, tzinfo=ET).timestamp(),
        open=held[0].open,
        high=max(b.high for b in held),
        low=min(b.low for b in held),
        close=held[-1].close,
        volume=sum(b.volume for b in held),
    )
    return build_price_level_snapshot(
        "SPY",
        session,
        bars_from_candles(bars),
        prior=prior,
        bar_source="test_fixture",
        config=PlaybookConfig(),
        generation=1,
    )


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
                f"premarket surface — absence was substituted (RC-68)"
            )
        else:
            assert got.get(level_id) == want, (
                f"{level_id}: premarket published {got.get(level_id)!r} while the canonical "
                f"snapshot holds {want!r} — a second faucet (RC-322)"
            )


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
                f"vs canonical {want!r}"
            )
