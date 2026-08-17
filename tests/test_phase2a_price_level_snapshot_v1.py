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

from datetime import datetime
from pathlib import Path

import pytest

from liquidity_value_engine import (
    PHASE2A_LEVEL_IDS,
    LevelCarrierConflict,
    PriceLevelValue,
    build_price_level_snapshot,
    carry_snapshot_levels,
    clear_materialized_snapshots,
    compute_session_vwap,
    compute_session_vwap_series,
    materialize_price_level_snapshot,
    register_level_carrier,
    reset_level_carrier_ledger,
    scoped_level_id,
)
from time_et import ET
from tools.phase2a_level_lock import (
    client_level_reconstruction_violations,
    level_alias_value_violations,
    level_computation_violations,
    scan_repo,
)

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
    clear_materialized_snapshots()
    reset_level_carrier_ledger()
    yield
    clear_materialized_snapshots()
    reset_level_carrier_ledger()


# ── the materialized snapshot ────────────────────────────────────────────────


def test_snapshot_carries_value_scope_generation_provenance_and_as_of():
    snap = build_price_level_snapshot(
        "SPY", SESSION, _tape(), bar_source="unit_tape", generation=7)
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
    tape = _tape()
    a = materialize_price_level_snapshot("SPY", SESSION, tape, bar_source="unit_tape")
    b = materialize_price_level_snapshot("SPY", SESSION, tape, bar_source="unit_tape")
    assert a is b, "the same generation re-materialized — that is a second result"
    assert a.generation == 1

    moved = tape + [_bar(2026, 8, 4, 11, 1, 107, 112, 106, 111)]
    c = materialize_price_level_snapshot("SPY", SESSION, moved, bar_source="unit_tape")
    assert c is not a and c.generation == 2, "a new bar input must bump the generation"
    assert all(v.generation == 2 for v in c.levels.values())


def test_absent_input_stays_absent_and_is_declared():
    snap = build_price_level_snapshot("SPY", SESSION, [], bar_source="empty")
    assert snap.levels == {}, "no bars must produce no levels, not zeros or spot"
    fams = {f["family"] for f in snap.families_absent}
    assert {"prior_day", "vwap", "opening_range", "overnight", "value_area"} <= fams
    assert all(f.get("reason") for f in snap.families_absent)
    assert snap.price("VWAP") is None


def test_distinct_scopes_never_share_an_id():
    assert scoped_level_id("VWAP", "session_rth") == "VWAP"
    assert scoped_level_id("VWAP", "checkpoint:midday") == "VWAP@checkpoint:midday"
    assert scoped_level_id("PDH", "checkpoint:premarket") == "PDH@checkpoint:premarket"


def test_one_vwap_accumulation_feeds_the_scalar_and_the_curve():
    """The drawn line must END on the served level — one accumulation, one number."""
    tape = _tape()
    series = compute_session_vwap_series(tape, SESSION)
    assert series, "no VWAP series for a session with RTH volume"
    assert compute_session_vwap(tape, SESSION) == series[-1][1]

    snap = build_price_level_snapshot("SPY", SESSION, tape, bar_source="unit_tape")
    assert snap.price("VWAP") == snap.vwap_series[-1][1]
    for lid, idx in (("VWAP_P1", 2), ("VWAP_M1", 3), ("VWAP_P2", 4), ("VWAP_M2", 5)):
        assert snap.price(lid) == snap.vwap_series[-1][idx], (
            f"{lid} differs from the last point of the curve the browser draws"
        )


# ── the runtime carrier contract ─────────────────────────────────────────────


def test_two_carriers_of_the_same_generation_agree():
    snap = build_price_level_snapshot(
        "SPY", SESSION, _tape(), bar_source="unit_tape", generation=3)
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
        "SPY", SESSION, _tape(), bar_source="unit_tape", generation=3)
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


# ── the static computation guard ─────────────────────────────────────────────


def test_repository_has_exactly_one_phase2a_computation():
    findings = scan_repo(ROOT)
    assert findings == [], (
        "Phase 2A single-computation lock failed:\n  " + "\n  ".join(findings))


def test_negative_control_second_endpoint_computation_is_caught():
    """(a) another endpoint invoking the canonical helper directly."""
    injected = (
        "from liquidity_value_engine import compute_session_vwap\n"
        "def get_some_other_endpoint(ticker):\n"
        "    return {'vwap': compute_session_vwap(bars, session_date)}\n"
    )
    bad = level_computation_violations("server.py", injected)
    assert bad and "compute_session_vwap" in bad[0], (
        "a second endpoint computation went undetected — the lock is inert")
    assert "get_some_other_endpoint" in bad[0]


def test_negative_control_same_helper_under_another_name_is_caught():
    """(a2) alias + wrapper: the same helper called under another function name."""
    aliased = (
        "from liquidity_value_engine import compute_session_vwap as _vw\n"
        "def get_endpoint_two(ticker):\n"
        "    return {'vwap': _vw(bars, session_date)}\n"
    )
    assert level_computation_violations("server.py", aliased), (
        "an IMPORT-aliased helper call went undetected")

    wrapped = (
        "from liquidity_value_engine import compute_opening_range\n"
        "def _orb_for(bars, sd, cfg):\n"
        "    return compute_opening_range(bars, sd, cfg)\n"
        "def get_endpoint_three(ticker):\n"
        "    return _orb_for(bars, sd, cfg)\n"
    )
    found = level_computation_violations("server.py", wrapped)
    assert any("get_endpoint_three" in f for f in found), (
        "a WRAPPER forwarding to the helper went undetected — renaming the function is "
        "the cheapest way around a name-based lock")

    rebound = (
        "from liquidity_value_engine import get_overnight_levels\n"
        "def get_endpoint_four(ticker):\n"
        "    f = get_overnight_levels\n"
        "    return f(bars, session_date)\n"
    )
    assert level_computation_violations("server.py", rebound), (
        "a variable-rebound helper call went undetected")


def test_negative_control_alias_inside_levels_list_is_caught():
    """(b) an aliased id and a produced value inside `levels: [{id, price}]`."""
    literal = (
        "def get_levels(ticker):\n"
        "    return {'levels': [{'id': 'OVERNIGHT_HIGH', 'price': 773.40,\n"
        "                        'family': 'overnight'}]}\n"
    )
    bad = level_alias_value_violations("server.py", literal)
    assert bad and "OVERNIGHT_HIGH" in bad[0], (
        "a hardcoded price inside levels[] went undetected")

    aliased_id = (
        "from liquidity_value_engine import compute_session_vwap\n"
        "VWAP_ID = 'VWAP'\n"
        "def get_levels(ticker):\n"
        "    return {'levels': [{'id': VWAP_ID,\n"
        "                        'price': compute_session_vwap(bars, sd)}]}\n"
    )
    bad2 = level_alias_value_violations("server.py", aliased_id)
    assert bad2 and "VWAP" in bad2[0], (
        "an ALIASED level id inside levels[] hid a live computation from the lock")


def test_legal_carriage_forms_stay_silent():
    """A lock that fires on the fix forces people to delete the fix."""
    carried = (
        "def get_levels(ticker):\n"
        "    snap = canonical_price_level_snapshot(ticker)\n"
        "    return {'levels': [{'id': 'VWAP', 'price': snap.price('VWAP')}]}\n"
    )
    assert level_alias_value_violations("server.py", carried) == []
    assert level_computation_violations("server.py", carried) == []


def test_negative_control_browser_reconstruction_is_caught():
    """(c) an in-page VWAP accumulation."""
    page = (
        "let pv = 0, vv = 0;\n"
        "for (const b of rth) { const tp = (b.h + b.l + b.c) / 3; pv += tp * b.v; }\n"
    )
    bad = client_level_reconstruction_violations("static/mine.html", page)
    assert bad and "in-page VWAP" in bad[0], (
        "a browser-side VWAP reconstruction went undetected")
    assert client_level_reconstruction_violations(
        "static/mine.html", "const w = ls.vwap_series[0][1];\n") == []


# ── the surfaces ─────────────────────────────────────────────────────────────


def test_api_levels_serializes_the_snapshot_and_does_not_compute(monkeypatch):
    import json

    import server as srv
    import time_et as te

    tape = _tape()
    monkeypatch.setattr(srv, "_liquidity_live_1m_overlay_bars", lambda t: tape)
    monkeypatch.setattr(srv, "LEVELS_PRIOR_SESSION_MIN_BARS", 2)
    monkeypatch.setattr(srv, "resolve_spot", lambda t, **kw: (106.0, "schwab_quote_last", 1.0))
    monkeypatch.setattr(te, "now_et", lambda: datetime(2026, 8, 4, 12, 0, tzinfo=ET))

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

    # the endpoint is a serializer: it must reach the engine only through the snapshot
    src = level_computation_violations("server.py", (ROOT / "server.py").read_text(
        encoding="utf-8", errors="replace"))
    assert src == [], src


def test_market_context_carries_and_never_recomputes(monkeypatch):
    """fetch_price_levels must make NO vendor fetch and NO helper call of its own.

    The first version of this control read the function's SOURCE and asserted that six
    helper names and `get_price_history` do not appear in it. That is a spelling check:
    reaching the same helper through an alias, a getattr, or a re-export leaves the
    source clean and the second materialization back. The helpers are real functions in
    liquidity_value_engine, so they are replaced with traps here — any route to them,
    however spelled, raises — and the carriage is then asserted to still be correct.
    """
    import liquidity_value_engine as lve
    from market_context import fetch_price_levels

    recompute: list[str] = []

    # Materialize FIRST: the canonical producer is the one place these helpers are
    # legitimately called. The traps go in afterwards, so they can only observe a
    # second, non-canonical call — which is the whole defect.
    snap = materialize_price_level_snapshot(
        "SPY", SESSION, _tape(), bar_source="unit_tape")

    for name in ("compute_session_vwap", "compute_vwap_bands", "compute_opening_range",
                 "get_overnight_levels", "compute_volume_profile_levels",
                 "get_previous_day_levels"):
        assert hasattr(lve, name), f"{name} left the canonical producer; re-derive this trap"

        def trap(*a, _n=name, **k):
            recompute.append(_n)
            raise AssertionError(f"fetch_price_levels recomputed {_n}")

        monkeypatch.setattr(lve, name, trap)

    pl = fetch_price_levels(None, symbol="SPY", quote_raw=None, level_snapshot=snap)

    assert recompute == [], f"fetch_price_levels recomputed {recompute} instead of carrying"
    # …and it carried, so the silence above is carriage, not a swallowed failure.
    assert pl.error is None or "no canonical snapshot" not in (pl.error or "")
    assert pl.vwap == snap.price("VWAP")
    assert pl.orb_high == snap.price("ORB_HIGH")
    assert pl.pd_poc == snap.price("PD_POC")
    assert pl.level_generation == snap.generation


def test_state_and_levels_carry_one_generation(monkeypatch):
    """/api/state's price levels and /api/levels come out of the SAME object."""
    from market_context import fetch_price_levels

    snap = materialize_price_level_snapshot(
        "SPY", SESSION, _tape(), bar_source="unit_tape")
    carry_snapshot_levels(snap, "api.levels")
    pl = fetch_price_levels(None, symbol="SPY", quote_raw=None, level_snapshot=snap)
    assert pl.pdh == snap.price("PDH")
    assert pl.pdc == snap.price("PDC")
    assert pl.vwap == snap.price("VWAP")
    assert pl.overnight_high == snap.price("OVERNIGHT_HIGH")
    assert pl.level_generation == snap.generation


def test_market_context_absence_is_absence_not_substitution():
    from market_context import fetch_price_levels

    clear_materialized_snapshots()
    pl = fetch_price_levels(None, symbol="ZZZZ", quote_raw=None)
    for field in ("pdh", "pdl", "vwap", "orb_high", "overnight_high", "today_poc"):
        assert getattr(pl, field) is None, f"{field} was substituted when absent"
    assert "no canonical snapshot" in pl.error


def test_chart_and_exposure_draw_carried_values_only():
    chart = (ROOT / "static" / "chart.html").read_text(encoding="utf-8", errors="replace")
    exposure = (ROOT / "static" / "exposure.html").read_text(
        encoding="utf-8", errors="replace")

    assert "/api/levels?ticker=" in chart, "the chart no longer reads the canonical contract"
    assert "vwap.push(" not in chart, "the in-page VWAP accumulation is back in the chart"
    assert "ls.vwap_series" in chart, "the chart no longer carries the server VWAP curve"
    assert "computeVwapSeries" not in exposure, (
        "the exposure tab's own VWAP/σ accumulation is back")
    assert "lv.vwap_series" in exposure, (
        "the exposure tab no longer carries the server VWAP curve")
    for page, name in ((chart, "chart.html"), (exposure, "exposure.html")):
        assert client_level_reconstruction_violations(name, page) == []


def test_liquidity_snapshot_scopes_checkpoint_ids_away_from_canonical():
    """A checkpoint cutoff is a different measurement, so it gets a different id."""
    import server as srv

    raw = {"prev": {"pdh": 105.0}, "overnight": {"overnight_high": 104.0},
           "orb": {"orb_high": 106.0}, "vwap": 105.5,
           "vwap_bands": {"plus1": 106.0, "minus1": 105.0},
           "poc": 105.2, "vah": 106.1, "val": 104.4}
    live = {i["tag"] for i in srv._build_raw_levels_used(raw, "live")}
    mid = {i["tag"] for i in srv._build_raw_levels_used(raw, "midday")}
    assert "PDH" in live and "VWAP" in live
    assert "PDH" not in mid and "PDH@checkpoint:midday" in mid
    assert not (live & mid), "a checkpoint scope shares ids with the canonical scope"


def test_live_one_faucet_check_sees_level_rows_inside_lists():
    """The live check compared nothing inside levels[] — the payload shape it must read."""
    from tools.check_one_faucet_live import numeric_leaves

    levels_payload = {"levels": [{"id": "OVERNIGHT_HIGH", "price": 773.3975},
                                 {"id": "PDL", "price": 749.59}]}
    liq_payload = {"raw_levels_used": [{"tag": "OVERNIGHT_HIGH", "value": 773.40}]}
    a = numeric_leaves(levels_payload)
    b = numeric_leaves(liq_payload)
    assert a["level:overnight_high"] == 773.3975
    assert b["level:overnight_high"] == 773.40
    assert a["level:overnight_high"] != b["level:overnight_high"], (
        "the fixture that reproduces the measured divergence must be visible to the "
        "live check — before this it descended into no list at all")

    radar = {"rows": [{"gex": 1.0}, {"gex": 2.0}]}
    assert not any(k.startswith("level:") for k in numeric_leaves(radar)), (
        "anonymous collection rows must stay excluded — comparing row zero of two "
        "different collections manufactures failures")


def test_phase2a_check_is_registered_enforced():
    from tools.check_institutional_correctness import CHECKS

    wired = {name: enforced for name, _fn, enforced in CHECKS}
    assert wired.get("phase2a_single_level_computation") is True, (
        "a proven-but-unwired lock reads as enforced to anyone who only runs the tests")
