"""The price levels: one snapshot per bar generation, and /api/levels and
/api/liquidity-snapshot serve its values under the same ids."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from liquidity_value_engine import (
    PHASE2A_LEVEL_IDS,
    _bars_to_list,
    build_price_level_snapshot,
    compute_session_vwap_series,
    materialize_price_level_snapshot,
)
from time_et import ET

ROOT = Path(__file__).resolve().parent.parent
#: a Monday whose prior session (Friday 2026-10-02) and the one before it (Thursday 10-01) are
#: sessions Schwab's /markets sent (tests/conftest.py)
SESSION = datetime(2026, 10, 5, 12, 0, tzinfo=ET).date()


def _bar(y, mo, d, h, mi, o, hi, lo, c, v=1000.0):
    # institutional-synthetic-ok: window selection needs bars placed in known sessions
    return {"timestamp": int(datetime(y, mo, d, h, mi, tzinfo=ET).timestamp() * 1000),
            "open": o, "high": hi, "low": lo, "close": c, "volume": v}


def _tape():
    """Two prior sessions plus a today session, so window selection is observable."""
    bars = [
        _bar(2026, 10, 1, 10, 0, 100, 110, 90, 100),     # older prior session
        _bar(2026, 10, 1, 14, 0, 100, 101, 99, 100),
        _bar(2026, 10, 2, 10, 0, 96, 105, 95, 97),       # most recent prior session
        _bar(2026, 10, 2, 15, 59, 101, 103, 100, 102),
        _bar(2026, 10, 5, 4, 0, 102, 104, 101, 103),     # overnight (pre-open)
        _bar(2026, 10, 5, 9, 31, 103, 106, 102, 105),    # today, inside ORB
        _bar(2026, 10, 5, 9, 50, 105, 107, 104, 106),    # today, post-ORB
        _bar(2026, 10, 5, 11, 0, 106, 108, 105, 107),
    ]
    return bars


def _daemon_bars(name: str, tk: str) -> list:
    """The capture daemon's newest receipt of each of `tk`'s minutes in fixture `name`, as bars."""
    from tests.feed_live_helper import daemon_bars
    newest = {}
    for r in sorted(daemon_bars(name, tk), key=lambda r: r["ts_recv"]):
        newest[r["bar_start_ms"]] = r
    return [{"timestamp": ms, "open": r["open"], "high": r["high"], "low": r["low"], "close": r["close"],
             "volume": r["volume"]} for ms, r in sorted(newest.items())]


@pytest.fixture(autouse=True)
def _clean_snapshots():
    import liquidity_value_engine as lve
    lve._MATERIALIZED_SNAPSHOTS.clear()
    yield
    lve._MATERIALIZED_SNAPSHOTS.clear()




# ── the materialized snapshot ────────────────────────────────────────────────


def test_snapshot_carries_value_scope_generation_provenance_and_as_of():
    snap = build_price_level_snapshot(
        "SPY", SESSION, _bars_to_list(_tape()), bar_source="unit_tape", generation=7)
    for lid, value in snap.levels.items():
        assert lid in PHASE2A_LEVEL_IDS, f"{lid} is not a declared Phase 2A id"
        assert value.generation == 7
        assert value.semantic_scope == PHASE2A_LEVEL_IDS[lid][1]
        assert value.producer.startswith("liquidity_value_engine.")
        assert value.as_of_ts_utc is not None
    assert snap.price("PDH") == 105 and snap.price("PDL") == 95, (
        "prior_day must be the SINGLE most recent prior RTH session, never the union"
    )
    assert snap.price("PDC") == 102
    for lid in ("PDH", "PDL", "PDC"):
        assert snap.price(lid) not in (110, 90), "multi-session union value materialized"


def test_one_materialization_per_generation_returns_the_same_object():
    """A new generation may invoke the producer once; re-asking is a READ."""
    tape = _bars_to_list(_tape())
    a = materialize_price_level_snapshot("SPY", SESSION, tape, bar_source="unit_tape")
    b = materialize_price_level_snapshot("SPY", SESSION, tape, bar_source="unit_tape")
    assert a is b, "the same generation re-materialized — that is a second result"
    assert a.generation == 1

    moved = _bars_to_list(_tape() + [_bar(2026, 8, 4, 11, 1, 107, 112, 106, 111)])
    c = materialize_price_level_snapshot("SPY", SESSION, moved, bar_source="unit_tape")
    assert c is not a and c.generation == 2, "a new bar input must bump the generation"
    assert all(v.generation == 2 for v in c.levels.values())


def test_an_index_has_no_volume_levels_and_says_so_an_etf_has_them():
    """All tickers, one rule; the instrument's data decides. Schwab's $SPX 1-minute bars carry no
    traded volume (the daemon's record of 2026-10-01/02: every bar volume 0), so VWAP and the value
    area cannot exist for it and are absent with that reason; the value area said "no today RTH
    bars" over 278 RTH bars (2026-09-28, the running app). SPY's real bars of the same days have
    volume and get both. The prior day (Thursday 10-01) is price-only and present for both."""
    friday = datetime(2026, 10, 2, tzinfo=ET).date()
    for name, tk, has_volume in (("real_daemon_bars_spx_2026_10_01_02.json", "$SPX", False),
                                 ("real_daemon_bars_spy_tsla_2026_10_01_02.json", "SPY", True)):
        snap = build_price_level_snapshot(tk, friday, _bars_to_list(_daemon_bars(name, tk)), bar_source=name)
        absent = {f["family"]: f["reason"] for f in snap.families_absent}
        assert snap.price("PDH") is not None and "prior_day" not in absent, tk
        if has_volume:
            assert snap.price("VWAP") is not None and "value_area" not in absent, tk
        else:
            assert absent["vwap"] == "no RTH volume for session VWAP in available bars"
            assert absent["value_area"] == "no RTH volume for the volume profile in available bars"


def test_absent_input_stays_absent_and_is_declared():
    snap = build_price_level_snapshot("SPY", SESSION, [], bar_source="empty")
    assert snap.levels == {}, "no bars must produce no levels, not zeros or spot"
    fams = {f["family"] for f in snap.families_absent}
    assert {"prior_day", "vwap", "opening_range", "overnight", "value_area"} <= fams
    assert all(f.get("reason") for f in snap.families_absent)
    assert snap.price("VWAP") is None




def test_one_vwap_accumulation_feeds_the_scalar_and_the_curve():
    """The drawn line must END on the served level — one accumulation, one number."""
    tape = _bars_to_list(_tape())
    assert compute_session_vwap_series(tape, SESSION), "no VWAP series for a session with RTH volume"

    snap = build_price_level_snapshot("SPY", SESSION, tape, bar_source="unit_tape")
    assert snap.price("VWAP") == snap.vwap_series[-1][1]
    for lid, idx in (("VWAP_P1", 2), ("VWAP_M1", 3), ("VWAP_P2", 4), ("VWAP_M2", 5)):
        assert snap.price(lid) == snap.vwap_series[-1][idx], (
            f"{lid} differs from the last point of the curve the browser draws"
        )




# ── the surfaces ─────────────────────────────────────────────────────────────


def _published(tk: str, now: datetime) -> None:
    """The tape in the console's memory under stand-in ticker `tk`, published as the bar writer
    publishes it (its tiny prior session is stamped degraded, and still served)."""
    import server as srv
    from micro_structure import Candle

    srv._bars.pop(tk, None)
    for b in _tape():
        srv._keep_bar(tk, Candle(ts=b["timestamp"] / 1000, open=b["open"], high=b["high"], low=b["low"],
                                 close=b["close"], volume=b["volume"]))
    srv._publish_price_levels(tk, now)


def test_api_levels_serializes_the_snapshot_and_does_not_compute():
    """Stand-in: ticker ZZP2A carries the tape."""
    import server as srv

    noon = datetime(2026, 10, 5, 12, 0, tzinfo=ET)
    try:
        _published("ZZP2A", noon)
        payload = srv.levels_payload("ZZP2A", "1", noon)
    finally:
        srv._bars.pop("ZZP2A", None)
    by_id = {lv["id"]: lv for lv in payload["levels"]}
    ids = [lv["id"] for lv in payload["levels"]]
    assert len(ids) == len(set(ids)), "level ids must be UNIQUE per payload"
    assert payload["generation"] >= 1
    assert by_id["PDH"]["price"] == 105 and by_id["PDL"]["price"] == 95
    for lv in payload["levels"]:
        assert lv["generation"] == payload["generation"], (
            "every served level must name the generation it came out of")
        assert lv["semantic_scope"] == PHASE2A_LEVEL_IDS[lv["id"]][1]
    assert payload["vwap_series"], "the carried VWAP curve is missing"
    assert by_id["VWAP"]["price"] == payload["vwap_series"][-1][1]


def test_the_liquidity_route_serves_the_levels_snapshots_values_under_the_same_ids():
    """ONE-09 (2026-09-28 audit): /api/liquidity-snapshot kept its own path -- checkpoint
    snapshots (premarket, opening, midday, afternoon) and a past-date replay that recomputed the
    prior day, overnight, VWAP and value area from bars, and a default ("premarket") that served
    those under "@checkpoint" ids. It serves the one snapshot now: every level it shows is the
    /api/levels value under the same id. Stand-in: ticker ZZP2B carries the tape."""
    import server as srv

    noon = datetime(2026, 10, 5, 12, 0, tzinfo=ET)
    try:
        _published("ZZP2B", noon)
        levels = {lv["id"]: lv["price"] for lv in srv.levels_payload("ZZP2B", "1", noon)["levels"]}
        liq = srv.liquidity_snapshot("ZZP2B", noon)
    finally:
        srv._bars.pop("ZZP2B", None)
    used = {i["tag"]: i["value"] for i in liq["raw_levels_used"]}
    assert used and set(used) <= set(PHASE2A_LEVEL_IDS), used
    for tag, value in used.items():
        assert levels[tag] == value, tag
