"""The price levels: one snapshot per bar generation.

The levels and liquidity panels serve its values under the same ids.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

import server as srv
from calc.liquidity_value_engine import (
    PHASE2A_LEVEL_IDS,
    bars_from_candles,
    build_price_level_snapshot,
    compute_session_vwap_series,
    prior_session,
)
from calc.micro_structure import Candle
from push import levels as push_levels
from push import liquidity as push_liquidity
from server import _schwab_bar
from state import bar_store, price_level_store
from state.price_level_store import materialize_price_level_snapshot
from tests.feed_live_helper import daemon_bars, schwab_daily
from time_et import ET, sessions

ROOT = Path(__file__).resolve().parent.parent
#: a Monday whose prior session (Friday 2026-10-02) and the one before it (Thursday 10-01) are
#: sessions Schwab's /markets sent (tests/conftest.py)
SESSION = datetime(2026, 10, 5, 12, 0, tzinfo=ET).date()


def _bar(y, mo, d, h, mi, o, hi, lo, c, v=1000.0):
    # window selection needs bars placed in known sessions
    return Candle(
        ts=datetime(y, mo, d, h, mi, tzinfo=ET).timestamp(),
        open=o,
        high=hi,
        low=lo,
        close=c,
        volume=v,
    )


def _tape():
    """Two prior sessions plus a today session, so window selection is observable."""
    return [
        _bar(2026, 10, 1, 10, 0, 100, 110, 90, 100),  # older prior session
        _bar(2026, 10, 1, 14, 0, 100, 101, 99, 100),
        _bar(2026, 10, 2, 10, 0, 96, 105, 95, 97),  # most recent prior session
        _bar(2026, 10, 2, 15, 59, 101, 103, 100, 102),
        _bar(2026, 10, 5, 4, 0, 102, 104, 101, 103),  # overnight (pre-open)
        _bar(2026, 10, 5, 9, 31, 103, 106, 102, 105),  # today, inside ORB
        _bar(2026, 10, 5, 9, 50, 105, 107, 104, 106),  # today, post-ORB
        _bar(2026, 10, 5, 11, 0, 106, 108, 105, 107),
    ]


#: the tape's two prior sessions as Schwab's daily candles carry them (high, low, close of each
#: session's regular bars above), dated at midnight ET as Schwab dates a daily candle
_DAILY_SENT = [
    {
        "datetime": int(datetime(2026, 10, d, tzinfo=ET).timestamp() * 1000),
        "open": o,
        "high": h,
        "low": lo,
        "close": c,
        "volume": 2000,
    }
    for d, o, h, lo, c in ((1, 100, 110, 90, 100), (2, 96, 105, 95, 102))
]


def _daily_msg(tk: str) -> dict:
    """Return the tape's daily candles as the daemon pushes a /pricehistory daily answer."""
    return {"symbol": tk, "series": "1d", "answer": {"symbol": tk, "candles": _DAILY_SENT}}


def _daily(tk: str) -> list:
    """`tk`'s daily candles as the bar writer holds them (server._write_price_history)."""
    srv._write_price_history(_daily_msg(tk))
    try:
        return list(bar_store._series[(tk, "1d")])
    finally:
        bar_store._series.pop((tk, "1d"), None)


def _prior(tk: str, session):
    return prior_session(_daily(tk), session)


def _daemon_bars(name: str, tk: str) -> list:
    """Return the capture daemon's newest receipt of each of `tk`'s minutes in fixture `name`.

    Each is taken in by the bar writer's own check (server._schwab_bar).
    """
    newest = {}
    for r in sorted(daemon_bars(name, tk), key=lambda r: r["ts_recv"]):
        newest[r["bar_start_ms"]] = r
    taken = [
        _schwab_bar(ms, r["open"], r["high"], r["low"], r["close"], r["volume"])
        for ms, r in sorted(newest.items())
    ]
    return [b for b in taken if b is not None]


@pytest.fixture(autouse=True)
def _clean_snapshots():
    price_level_store._MATERIALIZED_SNAPSHOTS.clear()
    yield
    price_level_store._MATERIALIZED_SNAPSHOTS.clear()


# ── the materialized snapshot ────────────────────────────────────────────────


def test_snapshot_carries_value_scope_provenance_and_as_of():
    snap = build_price_level_snapshot(
        SESSION,
        bars_from_candles(_tape()),
        prior=_prior("SPY", SESSION),
        bar_source="unit_tape",
        sessions=sessions(),
    )
    for lid, value in snap.levels.items():
        assert lid in PHASE2A_LEVEL_IDS, f"{lid} is not a declared Phase 2A id"
        assert value.semantic_scope == PHASE2A_LEVEL_IDS[lid][1]
        assert value.producer.startswith("calc.liquidity_value_engine.")
        assert value.as_of_ts_utc is not None
    assert snap.price("PDH") == 105 and snap.price("PDL") == 95, (
        "prior_day must be the SINGLE most recent prior RTH session, never the union"
    )
    assert snap.price("PDC") == 102
    for lid in ("PDH", "PDL", "PDC"):
        assert snap.price(lid) not in (110, 90), "multi-session union value materialized"


def test_one_materialization_per_input_returns_the_same_object():
    """A new input may invoke the producer once; re-asking is a READ."""
    tape, daily = bars_from_candles(_tape()), _daily("SPY")
    a = materialize_price_level_snapshot("SPY", SESSION, tape, daily=daily, bar_source="unit_tape")
    b = materialize_price_level_snapshot("SPY", SESSION, tape, daily=daily, bar_source="unit_tape")
    assert a is b, "the same input re-materialized — that is a second result"

    moved = bars_from_candles(_tape() + [_bar(2026, 8, 4, 11, 1, 107, 112, 106, 111)])
    c = materialize_price_level_snapshot("SPY", SESSION, moved, daily=daily, bar_source="unit_tape")
    assert c is not a, "a new bar input must be built again"
    assert c.bars_used == a.bars_used + 1


def test_an_index_has_no_volume_levels_and_says_so_an_etf_has_them():
    """All tickers, one rule; the instrument's data decides.

    Schwab's $SPX 1-minute bars carry no traded volume (the daemon's record of 2026-10-01/02:
    every bar volume 0), so VWAP and the value area cannot exist for it and are absent with
    that reason; the value area said "no today RTH bars" over 278 RTH bars (2026-09-28, the
    running app). SPY's real bars of the same days have volume and get both. The prior day
    (Thursday 10-01) is Schwab's daily candle, present for both
    (fixtures/real_schwab_daily_spx_2026_10.json, real_pricehistory_spy_tsla_2026_10_07.json);
    its value area, from its bars, is $SPX's absent too, declared with why.
    """
    friday = datetime(2026, 10, 2, tzinfo=ET).date()
    for name, tk, has_volume in (
        ("real_daemon_bars_spx_2026_10_01_02.json", "$SPX", False),
        ("real_daemon_bars_spy_tsla_2026_10_01_02.json", "SPY", True),
    ):
        snap = build_price_level_snapshot(
            friday,
            bars_from_candles(_daemon_bars(name, tk)),
            prior=prior_session(schwab_daily(tk), friday),
            bar_source=name,
            sessions=sessions(),
        )
        absent = {f["family"]: f["reason"] for f in snap.families_absent}
        assert snap.price("PDH") is not None and "prior_day" not in absent, tk
        if has_volume:
            assert snap.price("VWAP") is not None and "value_area" not in absent, tk
            assert snap.price("PD_POC") is not None and "prior_value_area" not in absent, tk
        else:
            assert absent["vwap"] == "no RTH volume for session VWAP in available bars"
            assert absent["value_area"] == "no RTH volume for the volume profile in available bars"
            # Thursday's $SPX bars carry no volume either: its value area is declared absent
            assert absent["prior_value_area"] == (
                "no RTH volume in the prior session 2026-10-01's bars for its volume profile"
            )
            assert {"PD_POC", "PD_VAH", "PD_VAL"}.isdisjoint(snap.levels)


def test_absent_input_stays_absent_and_is_declared():
    snap = build_price_level_snapshot(
        SESSION, [], prior=None, bar_source="empty", sessions=sessions()
    )
    assert snap.levels == {}, "no bars must produce no levels, not zeros or spot"
    assert (snap.vwap_series, snap.volume_profile) == ([], None), "no curve and no profile"
    fams = {f["family"] for f in snap.families_absent}
    assert {"prior_day", "vwap", "opening_range", "extended_hours", "value_area"} <= fams
    assert all(f.get("reason") for f in snap.families_absent)
    assert snap.price("VWAP") is None


def test_one_vwap_accumulation_feeds_the_scalar_and_the_curve():
    """The drawn line must END on the served level — one accumulation, one number."""
    tape = bars_from_candles(_tape())
    assert compute_session_vwap_series(tape, SESSION, sessions=sessions()), (
        "no VWAP series for a session with RTH volume"
    )

    snap = build_price_level_snapshot(
        SESSION,
        tape,
        prior=_prior("SPY", SESSION),
        bar_source="unit_tape",
        sessions=sessions(),
    )
    assert snap.price("VWAP") == snap.vwap_series[-1][1]


# ── the surfaces ─────────────────────────────────────────────────────────────


def _published(tk: str, now: datetime) -> None:
    """Publish the tape in the console's memory under stand-in ticker `tk`.

    It is published as the bar writer publishes it (its tiny prior session is stamped degraded,
    and still served).
    """
    bar_store._bars.pop(tk, None)
    for b in _tape():
        bar_store.keep_bar(tk, b)
    srv._write_price_history(_daily_msg(tk))  # the tape's sessions as Schwab's daily candles
    srv._publish_price_levels(tk, now)


def test_api_levels_serializes_the_snapshot_and_does_not_compute():
    """Stand-in: ticker ZZP2A carries the tape."""
    noon = datetime(2026, 10, 5, 12, 0, tzinfo=ET)
    try:
        _published("ZZP2A", noon)
        payload = push_levels.levels_payload("ZZP2A", "1", noon)
    finally:
        bar_store._bars.pop("ZZP2A", None)
        bar_store._series.pop(("ZZP2A", "1d"), None)
    by_id = {lv["id"]: lv for lv in payload["levels"]}
    ids = [lv["id"] for lv in payload["levels"]]
    assert len(ids) == len(set(ids)), "level ids must be UNIQUE per payload"
    assert by_id["PDH"]["price"] == 105 and by_id["PDL"]["price"] == 95
    for lv in payload["levels"]:
        assert lv["semantic_scope"] == PHASE2A_LEVEL_IDS[lv["id"]][1]
    assert payload["vwap_series"], "the carried VWAP curve is missing"
    assert by_id["VWAP"]["price"] == payload["vwap_series"][-1][1]


def test_the_liquidity_route_serves_the_levels_snapshots_values_under_the_same_ids():
    """The liquidity panel serves the one snapshot.

    Every level it shows is the levels panel's value under the same id. Stand-in: ticker ZZP2B
    carries the tape.
    """
    noon = datetime(2026, 10, 5, 12, 0, tzinfo=ET)
    try:
        _published("ZZP2B", noon)
        levels = {
            lv["id"]: lv["price"] for lv in push_levels.levels_payload("ZZP2B", "1", noon)["levels"]
        }
        liq = push_liquidity.liquidity_snapshot("ZZP2B", noon)
    finally:
        bar_store._bars.pop("ZZP2B", None)
        bar_store._series.pop(("ZZP2B", "1d"), None)
    copies = {"raw_levels", "raw_levels_used", "as_of_cutoff_et", "level_semantic_scope"}
    assert not copies & set(liq), "the snapshot's values are served once, by the levels panel"
    used = {s["id"]: s["value"] for z in liq["zones"] for s in z["source_levels"]}
    assert used and set(used) <= set(PHASE2A_LEVEL_IDS), used
    for tag, value in used.items():
        assert levels[tag] == value, tag
