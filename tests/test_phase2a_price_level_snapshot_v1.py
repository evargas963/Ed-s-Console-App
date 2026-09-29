"""Phase 2A: one computation, one materialization, carried everywhere.

THE DEFECT THIS LOCKS (operator, 2026-08-08 — measured on the live console, one ticker,
one instant):

    /api/levels             OVERNIGHT_HIGH 773.3975   OVERNIGHT_LOW 773.3975
    /api/liquidity-snapshot overnight_high 773.40     overnight_low  772.55

and the prior-day value area (PD_POC/PD_VAH/PD_VAL) disagreed between the two
intermittently. Neither endpoint's arithmetic was wrong. They ran the SAME engine
helpers over DIFFERENT bar inputs — the levels endpoint over the live accumulator (or
banked 1m bars), the liquidity endpoint over a synchronous Schwab fetch — so the
duplication was in the MATERIALIZATION, not the formula. Collapsing formulas, which
earlier missions did, could never have fixed it.

`tests/test_levels_single_producer_v1.py` was green the whole time: it enforces one
WRITER per payload key, and no forbidden key was written. That is the blind spot these
tests close — they read the call graph and the carried identity, not the field names.

Every guard here ships with a NEGATIVE CONTROL that injects the failure and proves the
guard screams; a guard that has never failed has never been tested.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from liquidity_value_engine import (
    PHASE2A_LEVEL_IDS,
    LevelCarrierConflict,
    PriceLevelValue,
    _bars_to_list,
    build_price_level_snapshot,
    carry_snapshot_levels,
    compute_session_vwap_series,
    materialize_price_level_snapshot,
    register_level_carrier,
)
from time_et import ET

ROOT = Path(__file__).resolve().parent.parent
SESSION = datetime(2026, 8, 4, 12, 0, tzinfo=ET).date()


def _bar(y, mo, d, h, mi, o, hi, lo, c, v=1000.0):
    return {"timestamp": int(datetime(y, mo, d, h, mi, tzinfo=ET).timestamp() * 1000),
            "open": o, "high": hi, "low": lo, "close": c, "volume": v}


def _tape():
    """Two prior sessions plus a today session, so window selection is observable."""
    bars = [
        _bar(2026, 7, 31, 10, 0, 100, 110, 90, 100),     # older prior session
        _bar(2026, 7, 31, 14, 0, 100, 101, 99, 100),
        _bar(2026, 8, 3, 10, 0, 96, 105, 95, 97),        # most recent prior session
        _bar(2026, 8, 3, 15, 59, 101, 103, 100, 102),
        _bar(2026, 8, 4, 4, 0, 102, 104, 101, 103),      # overnight (pre-open)
        _bar(2026, 8, 4, 9, 31, 103, 106, 102, 105),     # today, inside ORB
        _bar(2026, 8, 4, 9, 50, 105, 107, 104, 106),     # today, post-ORB
        _bar(2026, 8, 4, 11, 0, 106, 108, 105, 107),
    ]
    return bars


@pytest.fixture(autouse=True)
def _clean_ledgers():
    import liquidity_value_engine as lve
    lve._MATERIALIZED_SNAPSHOTS.clear()
    lve._CARRIER_LEDGER.clear()
    yield
    lve._MATERIALIZED_SNAPSHOTS.clear()
    lve._CARRIER_LEDGER.clear()




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


def test_an_index_has_no_volume_levels_and_says_so_an_etf_has_them(pin_clock):
    """All tickers, one rule; the instrument's data decides. Schwab's $SPX 1-minute bars carry no
    traded volume (real bars 2026-09-25/28: 501 with volume 0, 12 without the field), so VWAP and
    the value area cannot exist for it and are absent with that reason; the value area said "no
    today RTH bars" over 278 RTH bars (2026-09-28, the running app). SPY's real bars have volume and
    get both. The prior day is price-only and present for both."""
    fx = ROOT / "tests" / "fixtures"
    for name, tk, session, has_volume in (
            ("real_spx_1m_bars_2026_09_25_28.json", "$SPX", (2026, 9, 28), False),
            ("real_spy_1m_bars_2026_09_24_25.json", "SPY", (2026, 9, 25), True)):
        pin_clock(*session, 16, 30)
        bars = json.loads((fx / name).read_text(encoding="utf-8"))["bars"]
        snap = build_price_level_snapshot(tk, datetime(*session, tzinfo=ET).date(), _bars_to_list(bars), bar_source=name)
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


# ── the runtime carrier contract ─────────────────────────────────────────────


def test_two_carriers_of_the_same_generation_agree():
    snap = build_price_level_snapshot(
        "SPY", SESSION, _bars_to_list(_tape()), bar_source="unit_tape", generation=3)
    a = carry_snapshot_levels(snap, "api.levels")
    b = carry_snapshot_levels(snap, "api.liquidity_snapshot")
    assert a == b and a["OVERNIGHT_HIGH"] is not None


@pytest.mark.parametrize("field,mutation", [
    ("price", 773.40),
    ("generation", 99),
    ("producer", "some.other.producer"),
    ("as_of_ts_utc", 1.0),
])
def test_negative_control_disagreeing_carrier_raises(field, mutation):
    """NEGATIVE CONTROL: value, generation, provenance and as-of identity each fire.

    773.40 is the literal number /api/liquidity-snapshot served while /api/levels
    served 773.3975 — the disagreement that used to reach two screens silently.
    """
    snap = build_price_level_snapshot(
        "SPY", SESSION, _bars_to_list(_tape()), bar_source="unit_tape", generation=3)
    carry_snapshot_levels(snap, "api.levels")

    good = snap.levels["OVERNIGHT_HIGH"]
    kwargs = {
        "level_id": good.level_id, "price": good.price, "family": good.family,
        "semantic_scope": good.semantic_scope, "evidence_tier": good.evidence_tier,
        "producer": good.producer, "window": good.window,
        "vendor_basis": good.vendor_basis, "as_of_ts_utc": good.as_of_ts_utc,
        "generation": good.generation, "session_date": good.session_date,
    }
    kwargs[field] = mutation
    rogue = PriceLevelValue(**kwargs)

    if field == "generation":
        # a different generation is a different key, so it must NOT collide...
        register_level_carrier("api.liquidity_snapshot", "SPY", rogue)
        # ...but the SAME generation carrying a different value must.
        kwargs["generation"] = good.generation
        kwargs["price"] = 773.40
        with pytest.raises(LevelCarrierConflict):
            register_level_carrier("api.liquidity_snapshot", "SPY",
                                   PriceLevelValue(**kwargs))
        return

    with pytest.raises(LevelCarrierConflict) as excinfo:
        register_level_carrier("api.liquidity_snapshot", "SPY", rogue)
    assert "OVERNIGHT_HIGH" in str(excinfo.value)
    assert "api.liquidity_snapshot" in str(excinfo.value)


# ── the surfaces ─────────────────────────────────────────────────────────────


def test_api_levels_serializes_the_snapshot_and_does_not_compute(monkeypatch):
    import json

    import server as srv
    import time_et as te

    import liquidity_value_engine as lve

    tape = _tape()
    monkeypatch.setattr(srv, "_liquidity_1m_bars", lambda t: tape)
    monkeypatch.setattr(lve, "LEVELS_PRIOR_SESSION_MIN_BARS", 2)
    monkeypatch.setattr(srv, "resolve_spot", lambda t, **kw: (106.0, "schwab_quote_last", 1.0))
    monkeypatch.setattr(te, "now_et", lambda: datetime(2026, 8, 4, 12, 0, tzinfo=ET))

    srv._publish_price_levels("SPY")                  # as the bar writer does
    payload = json.loads(bytes(srv.get_levels(ticker="SPY").body))
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


def test_the_liquidity_route_serves_the_levels_snapshots_values_under_the_same_ids(monkeypatch):
    """ONE-09 (2026-09-28 audit): /api/liquidity-snapshot kept its own path -- checkpoint
    snapshots (premarket, opening, midday, afternoon) and a past-date replay that recomputed the
    prior day, overnight, VWAP and value area from bars, and a default ("premarket") that served
    those under "@checkpoint" ids. It serves the one snapshot now: every level it shows is the
    /api/levels value under the same id."""
    import json

    import server as srv
    import time_et as te

    import liquidity_value_engine as lve

    tape = _tape()
    noon = datetime(2026, 8, 4, 12, 0, tzinfo=ET)
    monkeypatch.setattr(srv, "_liquidity_1m_bars", lambda t: tape)
    monkeypatch.setattr(lve, "LEVELS_PRIOR_SESSION_MIN_BARS", 2)
    monkeypatch.setattr(srv, "resolve_spot", lambda t, **kw: (106.0, "schwab_quote_last", 1.0))
    monkeypatch.setattr(srv, "_liquidity_option_levels", lambda t: ([], "n/a"))
    monkeypatch.setattr(te, "now_et", lambda: noon)
    monkeypatch.setattr(srv, "now_et", lambda: noon)

    srv._publish_price_levels("SPY")                  # as the bar writer does
    levels = {lv["id"]: lv["price"] for lv in json.loads(bytes(srv.get_levels(ticker="SPY").body))["levels"]}
    liq = srv.get_liquidity_snapshot(ticker="SPY")
    used = {i["tag"]: i["value"] for i in liq["raw_levels_used"]}
    assert used and set(used) <= set(PHASE2A_LEVEL_IDS), used
    for tag, value in used.items():
        assert levels[tag] == value, tag
