"""The Trade Desk computes nothing (P1-3, PR B): every value it shows is served. Real data only:
Schwab's SPY 1-minute bars (2026-09-24/25), SPY level crosses (2026-09-09..25), a TSLA NASDAQ book
and the SPY 0DTE and CRWD chains (tests/fixtures). Expected values are worked out here from the
fixtures themselves."""
import json
import time
from datetime import datetime
from pathlib import Path

import pytest

import server
import time_et
from terrain_engine import compute_terrain

_FX = Path(__file__).resolve().parent / "fixtures"


def _load(name):
    return json.loads((_FX / name).read_text(encoding="utf-8"))


def test_the_book_side_is_served_from_the_real_book():
    from app.options.order_flow.engine import compute_book_microstructure
    fx = _load("real_equity_book.json")
    nat = fx["book"]["native"]
    bid5 = sum(r["TOTAL_VOLUME"] for r in nat["BIDS"][:5])
    ask5 = sum(r["TOTAL_VOLUME"] for r in nat["ASKS"][:5])
    m = compute_book_microstructure({"content": [nat]}, now_ts=fx["book"]["ts_recv"])
    want = "BID" if bid5 > ask5 else "ASK" if ask5 > bid5 else "EVEN"
    assert (m["depth"]["5"]["bid_total"], m["depth"]["5"]["ask_total"]) == (bid5, ask5)
    assert m["depth"]["5"]["side"] == want


def test_the_tape_side_is_served():
    from app.options.order_flow.live_payload import flow_block
    assert [flow_block({"tape_pressure_5m": v})["tape_side_5m"] for v in (0.2, -0.1, 0.0, None)] == \
        ["BUY", "SELL", "EVEN", None]


def test_the_desk_event_feed_numbers_orders_and_counts_the_real_crosses(monkeypatch):
    fx = _load("real_spy_level_crosses.json")["rows"]
    monkeypatch.setattr(server.get_db(), "get_recent_crosses", lambda ticker, n=20: fx[:n])
    monkeypatch.setattr(time_et, "now_et", lambda: datetime(2026, 9, 25, 16, 30, tzinfo=time_et.ET))
    monkeypatch.setattr(server, "now_et", lambda: datetime(2026, 9, 25, 16, 30, tzinfo=time_et.ET))
    monkeypatch.setattr(server, "resolve_spot", lambda t, **k: (None, "none", None))
    body = json.loads(server.get_desk_events(ticker="SPY", tf="30").body)
    start = datetime(2026, 9, 25, 9, 30, tzinfo=time_et.ET).timestamp()
    assert body["window_start_ts_utc"] == start
    # the events: the window's crosses, one per (time, value, direction)
    events = {}
    for r in fx:
        if r["ts_utc"] >= start:
            events.setdefault((r["ts_utc"], r["level_value"], r["direction"]), r)
    crosses = [it for it in body["items"] if it["dom"] == "LEVELS"]
    assert len(crosses) == len(events) > 0
    assert sorted(it["n"] for it in crosses) == list(range(1, len(events) + 1))
    oldest = min(events)[0]
    assert next(it for it in crosses if it["n"] == 1)["ts"] == oldest
    ts = [it["ts"] for it in body["items"] if it["ts"] is not None]
    assert ts == sorted(ts, reverse=True)                             # newest first
    assert sum(it.get("marker", False) for it in crosses) == min(40, len(crosses))
    up = sum(1 for k in events if k[2] == "up")
    assert body["cross_counts"] == {"up": up, "down": len(events) - up}


def test_wall_distances_and_flip_relation_are_served():
    fx = _load("real_crwd_complete_chain_quarter.json")
    snap = compute_terrain("CRWD", [dict(c) for c in fx["chain"]], float(fx["spot"]))
    payload = {**snap.to_dict(), "computed_ts_utc": time.time()}
    live = float(fx["spot"]) + 1.0
    orig = server.resolve_spot
    server.resolve_spot = lambda t, **k: (live, "live_quote", time.time())
    try:
        out = server._reprice_cached_terrain(payload, "CRWD")
    finally:
        server.resolve_spot = orig
    assert out["dist_to_call_wall"] == pytest.approx(payload["call_wall"] - live)
    assert out["dist_to_put_wall"] == pytest.approx(live - payload["put_wall"])
    assert out["flip_relation"] == (None if payload["gamma_flip"] is None
                                    else "ABOVE" if live >= payload["gamma_flip"] else "BELOW")


@pytest.fixture
def spy_levels(monkeypatch, pin_clock):
    bars = _load("real_spy_1m_bars_2026_09_24_25.json")["bars"]
    chain = _load("real_spy_0dte_chain.json")
    pin_clock(2026, 9, 22, 12, 46)                                   # the chain's own capture time
    terrain = {**compute_terrain("SPY", chain["chain"], chain["spot"]).to_dict(), "computed_ts_utc": time.time()}
    spot = bars[-1]["close"]
    monkeypatch.setattr(server, "_liquidity_live_1m_overlay_bars", lambda t: bars)
    monkeypatch.setattr(server, "resolve_spot", lambda t, **k: (spot, "live_quote", time.time()))
    monkeypatch.setattr(server, "terrain_cache_get", lambda t: terrain)
    pin_clock(2026, 9, 25, 16, 5)
    return spot, terrain


def test_levels_carry_the_gamma_family_into_the_one_distance_order(spy_levels):
    spot, terrain = spy_levels
    body = json.loads(server.get_levels(ticker="SPY").body)
    by_id = {r["id"]: r for r in body["levels"]}
    for gid in ("call_wall", "put_wall", "gamma_flip", "max_pain"):
        if terrain.get(gid) is not None:
            assert by_id[gid]["family"] == "gamma" and by_id[gid]["price"] == terrain[gid]
            assert gid in body["by_distance"]
    priced = [r for r in body["levels"] if r["price"] is not None]
    assert body["by_distance"] == [r["id"] for r in sorted(priced, key=lambda r: abs(r["price"] - spot))]
    assert all(r["side"] == ("AT" if round(r["price"] - spot, 2) == 0 else "ABOVE" if r["price"] > spot else "BELOW")
               for r in priced)


def test_vwap_is_served_per_chart_bar(spy_levels):
    one = json.loads(server.get_levels(ticker="SPY", tf="1").body)["vwap_series"]
    fifteen = json.loads(server.get_levels(ticker="SPY", tf="15").body)["vwap_series"]
    buckets = {}
    for r in one:                                                    # first minute stamps, last minute's value
        k = int(r[0] // 900)
        buckets[k] = [buckets[k][0] if k in buckets else r[0]] + list(r[1:])
    assert len(one) > 100 and fifteen == [buckets[k] for k in sorted(buckets)]


def test_every_bar_carries_its_change():
    import live_price_rows
    for b in _load("real_spy_1m_bars_2026_09_24_25.json")["bars"][:50]:
        bar = live_price_rows.with_change({"o": b["open"], "c": b["close"]})
        assert bar["chg"] == pytest.approx(b["close"] - b["open"])
        assert bar["chg_pct"] == pytest.approx((b["close"] - b["open"]) / b["open"] * 100)
