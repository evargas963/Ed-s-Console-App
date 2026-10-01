"""A missing gamma flip says what it means, and a contract past its settlement is in no book.

2026-09-30: 11 of 43 board tickers showed no gamma flip, as a bare dash, and the served read said
their dealer gamma "holds one sign across the whole chain". The flip is looked for only over the
prices its curve is evaluated at (spot +/- 15%); on 10 of the 11 the same curve changes sign
further out. The same morning the 16:15 ET close captures of five tickers still counted the
contracts that had settled at 16:00 ($SPX's regime read short gamma on them).

On Schwab's real 2026-09-29 close captures: MTA's whole chain, and IWM's two nearest expiries
(2026-09-29, settled 16 minutes before the capture, and 2026-09-30).
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import push_changes
import server
from calibration.complete_chain_capture import CAPTURE_BASIS, persist_complete_chain_capture
from db import EdDB
from math_levels import (
    FLIP_FOUND,
    FLIP_INCOMPLETE,
    FLIP_NO_CROSSING,
    FLIP_NO_PRICED_CONTRACT,
    FLIP_UNAVAILABLE,
    GAMMA_PROFILE_SPAN_PCT,
    UNPRICED_NO_VOLATILITY,
    UNPRICED_SETTLED,
    compute_gamma_profile,
    profile_sign_changes,
)
from math_exposure_core import compute_exposures_by_strike
from numeric_contract import schwab_count
from terrain_engine import compute_terrain
from terrain_read import REGIME_LONG_GAMMA, REGIME_UNAVAILABLE
from time_et import ET

_FX = Path(__file__).resolve().parent / "fixtures"


def _capture(name: str) -> tuple[dict, datetime]:
    """A stored capture and the instant it was taken (its valuation time)."""
    doc = json.loads((_FX / name).read_text(encoding="utf-8"))
    return doc, datetime.fromtimestamp(doc["ts_utc"], ET)


def _pcg(day: int) -> tuple[dict, datetime]:
    doc = json.loads((_FX / "real_pcg_two_day_chain.json").read_text(encoding="utf-8"))
    cap = {"ticker": "PCG", **doc["days"][day]}
    cap["chain"] = cap.get("chain") or cap["contracts"]
    return cap, datetime.fromtimestamp(cap["ts_utc"], ET)


def _captures():
    yield _capture("real_mta_close_capture_2026_09_29.json")
    yield _capture("real_iwm_close_capture_2026_09_29_two_expiries.json")
    yield _capture("real_sndk_chain_no_volatility.json")
    yield _pcg(0)
    yield _pcg(1)


def test_no_crossing_names_the_prices_searched_and_claims_nothing_beyond_them():
    cap, now = _capture("real_mta_close_capture_2026_09_29.json")
    snap = compute_terrain("MTA", cap["chain"], cap["spot"], now=now)
    d = snap.flip_diag
    assert snap.gamma_flip is None and d["state"] == FLIP_NO_CROSSING and d["crossings"] == 0
    assert (d["domain_lo"], d["domain_hi"]) == (snap.profile[0][0], snap.profile[-1][0])
    assert snap.gamma_flip_reason == f"none in {d['domain_lo']:.2f}–{d['domain_hi']:.2f}" == "none in 8.18–11.06"
    # no flip is not no regime: Schwab's gamma at spot still reads
    assert snap.regime == REGIME_LONG_GAMMA and snap.flip_relation is None
    # the reason is served once, under the flip's id, and claims nothing about the whole chain
    assert snap.level_absent_reasons["gamma_flip"] == snap.gamma_flip_reason
    assert "whole chain" not in snap.gamma_flip_reason
    # the same chain's curve does change sign, at a price the flip was never looked for at: the
    # absence is a statement about the prices searched, not about the chain
    beyond = profile_sign_changes(compute_gamma_profile(cap["chain"], 5.0, now=now))
    assert len(beyond) == 1 and d["strike_lo"] < beyond[0] < d["domain_lo"]


def test_every_capture_states_its_flip_by_the_same_rule():
    """All tickers: one rule decides the state. A contract of the book that could not be priced
    for a reason other than no usable volatility makes the flip incomplete (one Schwab sent with
    no usable volatility is left out and counted); otherwise the prices searched are spot +/-
    GAMMA_PROFILE_SPAN_PCT, a found flip is one of the curve's sign changes inside them with no
    reason, and a missing one carries its reason. The flip, its reason and the side of it are
    one record's."""
    states, left_out = set(), []
    for cap, now in _captures():
        snap = compute_terrain(cap["ticker"], cap["chain"], cap["spot"], now=now)
        d = snap.flip_diag
        states.add(d["state"])
        if d["unpriced"].get(UNPRICED_NO_VOLATILITY):
            left_out.append(cap["ticker"])
        assert (snap.gamma_flip is None) == bool(snap.gamma_flip_reason) == (snap.flip_relation is None)
        assert snap.gamma_flip == d["price"]
        if any(n for reason, n in d["unpriced"].items() if reason not in (UNPRICED_SETTLED, UNPRICED_NO_VOLATILITY)):
            assert d["state"] == FLIP_INCOMPLETE and d["domain_lo"] is None, cap["ticker"]
            continue
        assert d["domain_lo"] == pytest.approx(cap["spot"] * (1 - GAMMA_PROFILE_SPAN_PCT), abs=1e-4), cap["ticker"]
        assert d["domain_hi"] == pytest.approx(cap["spot"] * (1 + GAMMA_PROFILE_SPAN_PCT), abs=1e-4), cap["ticker"]
        changes = profile_sign_changes(snap.profile)
        assert d["crossings"] == len(changes)
        if d["state"] == FLIP_FOUND:
            assert snap.gamma_flip in changes and d["domain_lo"] <= snap.gamma_flip <= d["domain_hi"]
        else:
            assert d["state"] == FLIP_NO_CROSSING and changes == []
    assert states == {FLIP_FOUND, FLIP_NO_CROSSING}, "the captures cover each outcome they reach"
    # (an incomplete flip, from a contract with no expiry: test_one_faucet_units_v1)
    assert left_out, "a capture with contracts left out for no usable volatility is among them"


def test_a_chain_with_no_priceable_contract_has_no_curve_and_says_so():
    """Stand-in clock: MTA's capture valued after its last expiry, so no contract can be priced.
    That is 'unavailable', never 'no crossing'."""
    cap, _now = _capture("real_mta_close_capture_2026_09_29.json")
    last_expiry = max(c["expirationDate"][:10] for c in cap["chain"])
    after = datetime.fromisoformat(last_expiry).replace(tzinfo=ET) + timedelta(days=1)
    snap = compute_terrain("MTA", cap["chain"], cap["spot"], now=after)
    d = snap.flip_diag
    assert (d["state"], d["reason"]) == (FLIP_UNAVAILABLE, FLIP_NO_PRICED_CONTRACT)
    assert d["domain_lo"] is None and snap.gamma_flip is None
    assert snap.gamma_flip_reason == "no contract could be priced"
    assert snap.regime == REGIME_UNAVAILABLE and snap.net_gex_at_spot is None


def _oi(contracts) -> float:
    return sum(schwab_count(c.get("openInterest")) or 0 for c in contracts)


def _session_volume(snap) -> float:
    return sum(r[2] or 0 for r in snap.per_strike["all"])


_BOOK_FIELDS = ("regime", "net_gex_at_spot", "call_wall", "put_wall", "absolute_gamma_strike",
                "net_gex_peak", "max_pain", "max_pain_dte", "book_oi_total", "gamma_flip",
                "contracts_used", "hvp", "lvp", "pcr_all")


def test_a_contract_past_its_settlement_is_in_no_book_and_keeps_its_volume():
    cap, now = _capture("real_iwm_close_capture_2026_09_29_two_expiries.json")     # 16:16 ET
    settled = [c for c in cap["chain"] if c["expirationDate"][:10] == "2026-09-29"]
    still_open = [c for c in cap["chain"] if c["expirationDate"][:10] != "2026-09-29"]
    assert _oi(settled) > 0 and still_open, "the capture carries open interest on the settled expiry"
    snap = compute_terrain("IWM", cap["chain"], cap["spot"], now=now)
    open_only = compute_terrain("IWM", still_open, cap["spot"], now=now)
    for k in _BOOK_FIELDS:
        assert getattr(snap, k) == getattr(open_only, k), k
    assert snap.book_oi_total == _oi(still_open)
    assert snap.max_pain is not None and snap.max_pain_dte == 1      # the front expiry still open
    # settled contracts are out of the book, so leaving them out of the curve is not incomplete
    assert snap.flip_diag["unpriced"] == {
        UNPRICED_SETTLED: sum(1 for c in settled if schwab_count(c.get("openInterest")))}
    assert snap.flip_diag["state"] == FLIP_FOUND and snap.gamma_flip is not None
    # what traded that day still shows: the settled expiry's volume stays in the per-strike rows
    assert _session_volume(snap) > _session_volume(open_only) > 0
    assert "2026-09-29" in snap.expiries
    # the heatmap's column for that expiry carries the settlement time it is labelled expired by
    settles = {e["expiry"]: e["settles_ts_utc"]
               for e in server.project_gamma_surface(cap["chain"], snap.books)["expirations"]}
    assert settles["2026-09-29"] == datetime(2026, 9, 29, 16, 0, tzinfo=ET).timestamp() < cap["ts_utc"]
    assert settles["2026-09-30"] == datetime(2026, 9, 30, 16, 0, tzinfo=ET).timestamp()

    # Stand-in clock: the same chain valued at 15:30 ET, before the 16:00 settlement -- the
    # 2026-09-29 contracts are open exposure then
    before = compute_terrain("IWM", cap["chain"], cap["spot"], now=now.replace(hour=15, minute=30))
    assert before.book_oi_total == _oi(cap["chain"]) and before.max_pain_dte == 0


def test_a_contract_whose_settlement_cannot_be_determined_is_counted_wherever_its_book_is_served(monkeypatch):
    """A contract with no readable expiry was dropped from the exposure book with no count. It is
    in no book and is counted beside `oi_unreported` / `volume_unreported`: per strike, in the
    book's diagnostics, and in what the gamma surface, the per-strike rows (today's and the prior
    day's) and the forces serve. Real Schwab chain: MTA's 2026-09-29 close capture, its front
    expiry (2026-10-16) relabelled 2026-11-26 (Thanksgiving, no session close), a stand-in for an
    expiry the calendar cannot settle; the older capture for the forces and prior rows is the
    same chain as Schwab sent it, a day earlier (stand-in)."""
    cap, now = _capture("real_mta_close_capture_2026_09_29.json")
    unknown = [dict(c, expirationDate="2026-11-26T20:00:00.000+00:00")
               for c in cap["chain"] if c["expirationDate"][:10] == "2026-10-16"]
    chain = unknown + [c for c in cap["chain"] if c["expirationDate"][:10] != "2026-10-16"]
    n = len(unknown)
    assert n == 16

    exposures, diag = compute_exposures_by_strike(chain, spot=cap["spot"], now=now)
    assert diag.expiry_unknown == n and sum(b["expiry_unknown"] for b in exposures.values()) == n
    snap = compute_terrain("MTA", chain, cap["spot"], now=now)
    assert server.project_gamma_surface(chain, snap.books)["contracts_expiry_unknown"] == n
    assert snap.per_strike["expiry_unknown"] == n

    monkeypatch.setattr(server, "terrain_cache_get", lambda tk, t: {
        "_per_strike": snap.per_strike, "computed_ts_utc": cap["ts_utc"], "spot": cap["spot"]})
    monkeypatch.setattr(server, "resolve_spot", lambda tk, **k: (cap["spot"], server.SPOT_SOURCE_PLANE, cap["ts_utc"]))
    assert json.loads(server.get_terrain_strikes(ticker="MTA").body)["today"]["expiry_unknown"] == n

    newer = {"et_date": "2026-09-29", "spot": cap["spot"], "contracts": chain, "ts_utc": cap["ts_utc"]}
    older = {"et_date": "2026-09-28", "spot": cap["spot"], "contracts": cap["chain"], "ts_utc": cap["ts_utc"] - 86400}
    forces = server._forces_from_captures("MTA", [newer, older])
    assert forces["available"] is True and forces["contracts_expiry_unknown"] == {"newer": n, "older": 0}
    prior, _src = server._prior_strikes([newer | {"et_date": "2026-09-28"}], cap["ts_utc"])
    assert prior["expiry_unknown"] == n


@pytest.fixture
def _stored_mta(monkeypatch, tmp_path):
    """MTA's capture in a chain-history database, as the daemon writes it, on a closed market."""
    cap, _now = _capture("real_mta_close_capture_2026_09_29.json")
    db = tmp_path / "ed_console.db"
    by_expiry: dict = {}
    for ct in cap["chain"]:
        by_expiry.setdefault(ct["expirationDate"][:10], []).append(ct)
    for expiry, cts in by_expiry.items():
        persist_complete_chain_capture(db, ticker="MTA", expiry=expiry, contracts=cts, spot=cap["spot"],
                                       completeness_basis=CAPTURE_BASIS, ts_utc=cap["ts_utc"])
    edb = EdDB(db)
    tk = server.ticker_storage_key("MTA")
    monkeypatch.setattr(server, "get_db", lambda: edb)
    monkeypatch.setattr(server, "_logger_tickers", [tk])
    monkeypatch.setattr(server, "_terrain_cache", {})
    monkeypatch.setattr(server, "_is_loggable_session", lambda now: False)
    monkeypatch.setattr(server, "resolve_spot", lambda t, **kw: (None, "none", None))
    monkeypatch.setattr(push_changes, "_clients", {})
    monkeypatch.setattr(push_changes, "_loop", None)
    return cap, tk


def test_the_stored_capture_the_endpoints_and_the_producer_agree_on_the_missing_flip(_stored_mta):
    cap, tk = _stored_mta
    assert server._load_stored_levels() == 1
    expected = compute_terrain(tk, cap["chain"], cap["spot"],
                               now=datetime.fromtimestamp(cap["ts_utc"], ET))
    client = TestClient(server.app)
    body = client.get(f"/api/terrain?ticker={tk}").json()
    assert body["gamma_flip"] is None and body["gamma_flip_reason"] == expected.gamma_flip_reason != ""
    assert body["flip_relation"] is None
    for k in ("state", "domain_lo", "domain_hi", "crossings", "coverage", "curve_gamma_at_spot"):
        assert body["flip_diag"][k] == expected.flip_diag[k], k
    assert body["flip_diag"]["state"] == FLIP_NO_CROSSING
    assert "lines" not in body                       # no second rendering of the reason in prose
    assert body["gamma_flip_caveat"] == expected.gamma_flip_caveat
    # no surface gets a flip from anywhere else, and the chart's levels carry the same reason
    levels = client.get(f"/api/levels?ticker={tk}").json()
    assert "gamma_flip" not in {r["id"] for r in levels["levels"]}
    assert "call_wall" in {r["id"] for r in levels["levels"]}, "the other gamma levels are still carried"
    assert {"family": "gamma_flip", "reason": expected.gamma_flip_reason} in levels["families_absent"]
    # every gamma level published without a value carries the reason it was published with
    absent = {f["family"]: f["reason"] for f in levels["families_absent"]}
    assert expected.pin_candidate is None and expected.pin_candidate_blockers
    assert absent["pin_candidate"] == "not qualified: " + ", ".join(expected.pin_candidate_blockers)
    for gid, why in expected.level_absent_reasons.items():
        assert absent[gid] == why and gid not in {r["id"] for r in levels["levels"]}
    assert "GAMMA_FLIP" not in {tag for _price, tag in server._liquidity_option_levels(server.terrain_cache_get(tk, time.time()))}


def test_a_ticker_with_no_chain_carries_the_flips_own_reason():
    """The terrain of a ticker with nothing to price is the flip's 'no input' state, with the
    reason the screens print: never an empty reason beside a missing flip."""
    snap = compute_terrain("MTA", None, 9.62)
    assert snap.gamma_flip is None and snap.gamma_flip_reason == "no option chain or price"
    assert snap.flip_diag["state"] == FLIP_UNAVAILABLE and snap.flip_relation is None


def test_the_side_of_the_flip_has_one_rule():
    """The served flip_relation comes from terrain_read.flip_side; at the flip itself spot is on
    neither side (the served relation said ABOVE there)."""
    from terrain_read import FLIP_SIDE_ABOVE, FLIP_SIDE_AT, FLIP_SIDE_BELOW, flip_side
    assert [flip_side(s, 100.0) for s in (101.0, 100.0, 99.0)] == [FLIP_SIDE_ABOVE, FLIP_SIDE_AT, FLIP_SIDE_BELOW]
    assert flip_side(100.0, None) is None and flip_side(None, 100.0) is None
    cap, now = _capture("real_iwm_close_capture_2026_09_29_two_expiries.json")
    snap = compute_terrain("IWM", cap["chain"], cap["spot"], now=now)
    assert snap.flip_relation == flip_side(cap["spot"], snap.gamma_flip) == FLIP_SIDE_BELOW
