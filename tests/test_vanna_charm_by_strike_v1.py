"""/api/options/vanna-by-strike and /api/options/charm-by-strike (operator field-inventory
audit, 2026-09-13): both wrap ALREADY-canonical, already-tested faucets --
math_exposure_core.compute_exposures_by_strike's own call_vanna/put_vanna (RC-211's exact
BS-vanna faucet) and math_levels.compute_charm_by_strike (the same function /api/forces's
charm_below/charm_above already sum) -- read off the snapshot _publish_levels last
published (the _vanna_rows/_charm_rows _publish_levels writes into the cached payload),
zero extra vendor calls or pricing. These tests
prove the wiring, not the math (bs_vanna/bs_charm/compute_charm_by_strike are proven
elsewhere: test_charm_by_strike_v1.py, test_charm_sign_finite_difference.py).

Real data: CRWD's 2026-10-16 chain captured 2026-10-07 10:38:40 ET (tests/real_chains.py), priced
at its capture instant, and CRWD's LEVELONE_EQUITIES message the daemon received at 10:38:00 ET
(tests/fixtures/real_crwd_quote_2026_10_07.json), the live price the routes serve beside it."""
from __future__ import annotations

import json
import time
from pathlib import Path

import live_market_plane as lmp
import server
from app.options.order_flow import streaming as ofs
from terrain_engine import compute_terrain
from tests.feed_live_helper import mark_feed_live, publish_daemon_rows
from tests.real_chains import CRWD

_SPOT = CRWD.spot
_CONTRACTS = [dict(ct) for ct in CRWD.chain]
_QUOTE = json.loads((Path(__file__).resolve().parent / "fixtures" / "real_crwd_quote_2026_10_07.json")
                    .read_text(encoding="utf-8"))
TK = server.ticker_storage_key("CRWD")


def _clear():
    with server._terrain_cache_lock:
        server._terrain_cache.pop(TK, None)
    ofs._price_rows.pop(TK, None)
    lmp._by_ticker.pop(TK, None)
    lmp._fields_by_ticker.pop(TK, None)


def _put_live_chain():
    snap = compute_terrain(TK, _CONTRACTS, _SPOT, now=CRWD.now)
    with server._terrain_cache_lock:
        server._terrain_cache[TK] = {"ticker": TK, "spot": snap.spot, "computed_ts_utc": time.time(),
                                     "_vanna_rows": server._vanna_rows(snap),
                                     "_charm_rows": server._charm_rows(snap)}


def setup_function(_fn):
    _clear()


def teardown_function(_fn):
    _clear()


def test_vanna_by_strike_unavailable_with_no_cached_chain():
    body = json.loads(server.get_vanna_by_strike(ticker="CRWD").body)
    assert body["available"] is False
    assert "reason" in body


def test_charm_by_strike_unavailable_with_no_cached_chain():
    body = json.loads(server.get_charm_by_strike(ticker="CRWD").body)
    assert body["available"] is False
    assert "reason" in body


def test_vanna_by_strike_matches_the_same_canonical_faucet_call_vanna_minus_put_vanna():
    _put_live_chain()
    from math_exposure_core import bucket_metric, compute_exposures_by_strike as cebs
    # Schwab's CRWD quote reaches the console as the daemon pushes it: its price row
    lmp.record_from_level_one_equity(TK, _QUOTE["native"], received_ts=time.time())
    mark_feed_live(TK)
    publish_daemon_rows(TK)

    body = json.loads(server.get_vanna_by_strike(ticker="CRWD", scope="all").body)
    assert body["available"] is True
    # spot is the live price (the header's own); the rows were computed at priced_at_spot
    assert body["spot"] == _QUOTE["native"]["LAST_PRICE"] and body["priced_at_spot"] == _SPOT
    rows = {r[0]: r[1] for r in body["rows"]}
    assert rows, "a real chain must yield at least one vanna row"

    # the same chain at the same instant: the published rows are the faucet's own values
    exposures, _ = cebs(_CONTRACTS, spot=_SPOT, now=CRWD.now)
    checked = 0
    for k, b in exposures.items():
        expected = bucket_metric(b, "net_vanna")
        if expected is None:            # a leg's vanna input Schwab did not send: no row
            assert float(k) not in rows
            continue
        assert rows[float(k)] == expected
        checked += 1
    assert checked > 5


def test_charm_by_strike_matches_the_same_canonical_faucet_compute_charm_by_strike():
    _put_live_chain()
    from math_levels import compute_charm_by_strike as ccs

    body = json.loads(server.get_charm_by_strike(ticker="CRWD", scope="all").body)
    assert body["available"] is True
    rows = {r[0]: r[1] for r in body["rows"]}
    assert rows, "a real chain must yield at least one charm row"

    # the same chain at the same instant: the published rows are the faucet's own values
    per_ch = ccs(_CONTRACTS, _SPOT, now=CRWD.now)
    checked = 0
    for k, b in per_ch.items():
        if b.get("net_charm") is None:
            continue
        assert rows[float(k)] == float(b["net_charm"])
        checked += 1
    assert checked > 5


def test_vanna_and_charm_rows_are_sorted_by_strike_ascending():
    _put_live_chain()
    v_rows = json.loads(server.get_vanna_by_strike(ticker="CRWD").body)["rows"]
    c_rows = json.loads(server.get_charm_by_strike(ticker="CRWD").body)["rows"]
    assert [r[0] for r in v_rows] == sorted(r[0] for r in v_rows)
    assert [r[0] for r in c_rows] == sorted(r[0] for r in c_rows)
