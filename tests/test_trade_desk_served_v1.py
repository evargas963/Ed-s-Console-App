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
    # the percent the Desk card prints is served text, not page arithmetic
    assert m["depth"]["5"]["imbalance_disp"] == f"{(bid5 - ask5) / (bid5 + ask5) * 100:+.1f}%"


def _desk_events(monkeypatch, ticker, crosses, now, tf):
    """/api/desk/events on real crosses, at `now`."""
    newest_first = sorted(crosses, key=lambda r: r["ts_utc"], reverse=True)       # as db.get_crosses_since reads
    monkeypatch.setattr(server.get_db(), "get_crosses_since",
                        lambda ticker, since: [r for r in newest_first if r["ts_utc"] >= since])
    monkeypatch.setattr(time_et, "now_et", lambda: now)
    monkeypatch.setattr(server, "now_et", lambda: now)
    monkeypatch.setattr(server, "resolve_spot", lambda t, **k: (None, "none", None))
    return json.loads(server.get_desk_events(ticker=ticker, venue="NYSE_BOOK", tf=tf).body)


@pytest.mark.parametrize("ticker,crosses,now", [
    ("SPY", "real_spy_level_crosses.json", datetime(2026, 9, 25, 18, 0, tzinfo=time_et.ET)),
    ("$SPX", "real_spx_level_crosses_2026_09_25_28.json", datetime(2026, 9, 28, 12, 0, tzinfo=time_et.ET)),
])
def test_each_cross_is_served_as_recorded_and_the_chart_draws_the_newest_at_each_level(monkeypatch, ticker, crosses, now):
    """Each level cross is the queue's entry as recorded -- its level's price, direction and
    time -- and the chart's few are the newest cross at each level, for the newest DESK_MARKERS
    levels; a marker and its queue entry are one served item (real SPY and $SPX crosses)."""
    rows = _load(crosses)["rows"]
    body = _desk_events(monkeypatch, ticker, rows, now, "D")
    items = [it for it in body["items"] if it["dom"] == "LEVELS"]
    assert items
    by_key = {f"x{r['cross_id']}": r for r in rows}
    for it in items:
        r = by_key[it["key"]]
        assert (it["price"], it["dir"], it["ts"]) == (r["level_value"], r["direction"], r["ts_utc"])
    newest_at = {}
    for it in sorted(items, key=lambda it: it["ts"]):
        newest_at[it["price"]] = it
    want = {it["key"] for it in sorted(newest_at.values(), key=lambda it: it["ts"])[-server.DESK_MARKERS:]}
    assert {it["key"] for it in items if it["marker"]} == want


def test_the_window_holds_every_cross_in_it_not_the_newest_two_hundred(monkeypatch):
    """The queue and its up/down counts were cut at the newest 200 crosses whatever the window:
    SPY's real rows hold 243 crossings in the daily chart's 20 days (on 2026-09-30 QQQ had 294,
    SPY 260, TSLA 212). The window is read whole."""
    rows = _load("real_spy_level_crosses.json")["rows"]
    now = datetime(2026, 9, 25, 18, 0, tzinfo=time_et.ET)
    assert min(r["ts_utc"] for r in rows) >= now.timestamp() - server.DESK_LOOKBACK["D"][0]
    body = _desk_events(monkeypatch, "SPY", rows, now, "D")
    events = {(r["ts_utc"], r["level_value"], r["direction"]) for r in rows}
    assert len(events) == 243
    assert len([it for it in body["items"] if it["dom"] == "LEVELS"]) == 243
    assert sum(body["cross_counts"].values()) == 243
    # a shorter window holds only its own
    hour = _desk_events(monkeypatch, "SPY", rows, now, "1")
    start = now.timestamp() - server.DESK_LOOKBACK["1"][0]
    assert len([it for it in hour["items"] if it["dom"] == "LEVELS"]) == len({e for e in events if e[0] >= start})


def test_a_book_wall_carries_its_books_time_and_says_when_the_book_is_not_live(monkeypatch):
    """Operator 2026-09-29: a stale or premarket book item shows its actual observation time and
    never appears live. The queue's size walls were stamped with the console's receive time and
    read the same whether or not the book was live. Real TSLA NASDAQ book (its own BOOK_TIME)."""
    from fastapi.responses import JSONResponse
    from app.options.order_flow.engine import compute_book_microstructure
    fx = _load("real_equity_book.json")
    nat = fx["book"]["native"]
    micro = compute_book_microstructure({"content": [nat], "book_live": False}, now_ts=fx["book"]["ts_recv"])
    assert micro["wall_candidates"] and micro["ages"]["book_stale"] is True
    monkeypatch.setattr(server, "api_order_flow_microstructure", lambda ticker, venue: JSONResponse(micro))
    body = _desk_events(monkeypatch, "SPY", [], datetime(2026, 9, 25, 18, 0, tzinfo=time_et.ET), "30")
    walls = [it for it in body["items"] if it["key"].startswith("wall")]
    assert walls
    for it in walls:
        assert it["ts"] == nat["BOOK_TIME"] / 1000.0
        assert it["title"].endswith("(not live)") and it["warn"] is True


def test_the_desk_event_feed_numbers_orders_and_counts_the_real_crosses(monkeypatch):
    fx = _load("real_spy_level_crosses.json")["rows"]
    body = _desk_events(monkeypatch, "SPY", fx, datetime(2026, 9, 25, 18, 0, tzinfo=time_et.ET), "30")
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
    up = sum(1 for k in events if k[2] == "up")
    assert body["cross_counts"] == {"up": up, "down": len(events) - up}


def _crwd_at(live, pin_clock):
    """The levels producer's snapshot on the real CRWD chain, priced at `live(base)` where base
    is the snapshot at the chain's own price (stand-in live prices, named by each test)."""
    pin_clock(2026, 9, 2, 12, 0)
    fx = _load("real_crwd_complete_chain_quarter.json")
    base = compute_terrain("CRWD", [dict(c) for c in fx["chain"]], float(fx["spot"])).to_dict()
    return compute_terrain("CRWD", [dict(c) for c in fx["chain"]], live(base)).to_dict()


def test_wall_distances_and_flip_relation_are_served(pin_clock):
    out = _crwd_at(lambda b: (b["call_wall"] + b["put_wall"]) / 2, pin_clock)
    assert out["dist_to_call_wall"] == pytest.approx(out["call_wall"] - out["spot"])
    assert out["dist_to_put_wall"] == pytest.approx(out["spot"] - out["put_wall"])
    assert (out["call_wall_relation"], out["put_wall_relation"]) == ("BELOW", "ABOVE")
    assert out["flip_relation"] == (None if out["gamma_flip"] is None
                                    else "ABOVE" if out["spot"] >= out["gamma_flip"] else "BELOW")


def test_a_breached_wall_says_so_at_the_live_price(pin_clock):
    """Real CRWD chain; stand-in live prices one dollar beyond each wall, then at it. The
    distance is never negative: the side spot is on is served beside it (2026-09-30: Right Now
    printed a put wall spot had fallen through as a negative distance "above put wall")."""
    out = _crwd_at(lambda b: b["call_wall"] + 1.0, pin_clock)
    assert out["spot"] > out["call_wall"]
    assert out["call_wall_state"] == "breached" and out["call_wall_lean"] == "BREACHED — spot at or above"
    assert out["dist_to_call_wall"] == pytest.approx(1.0) and out["call_wall_relation"] == "ABOVE"
    out = _crwd_at(lambda b: b["put_wall"] - 1.0, pin_clock)
    assert out["spot"] < out["put_wall"]
    assert out["put_wall_state"] == "breached" and out["put_wall_lean"] == "BREACHED — spot at or below"
    assert out["dist_to_put_wall"] == pytest.approx(1.0) and out["put_wall_relation"] == "BELOW"
    out = _crwd_at(lambda b: b["put_wall"], pin_clock)
    assert out["put_wall_state"] == "breached" and out["put_wall_relation"] == "AT"
    assert out["dist_to_put_wall"] == 0


def test_a_containing_wall_earns_the_dealer_lean_only_in_long_gamma_on_trusted_coverage(pin_clock):
    out = _crwd_at(lambda b: (b["call_wall"] + b["put_wall"]) / 2, pin_clock)
    assert out["call_wall_state"] == out["put_wall_state"] == "contains"
    earned = out["regime"] == "LONG_GAMMA_CHOP" and out["confidence"] == "TRUSTED"
    assert out["call_wall_lean"] == ("DEALERS SELL" if earned else None)
    assert out["put_wall_lean"] == ("DEALERS BUY" if earned else None)


def test_no_lean_contradicts_the_read_in_short_gamma():
    """2026-09-30 audit: in the short-gamma regime the put wall read DEALERS BUY while the same
    publication's read was the trend regime (dealers buy strength and sell weakness: follow
    breaks). The lean is stated only where the read agrees with it."""
    from terrain_engine import wall_lean
    from terrain_read import POSTURE_FOLLOW, build_terrain_read
    read = build_terrain_read(spot=770.0, flip=775.0, flip_confidence="TRUSTED", gamma_at_spot=-1.0e9)
    assert read.regime == "SHORT_GAMMA_TREND" and read.posture == POSTURE_FOLLOW
    assert wall_lean(780.0, 760.0, "contains", "contains", read.regime, read.confidence) == (None, None)
    # a breached wall still says so, whatever the regime
    assert wall_lean(780.0, 760.0, "breached", "contains", read.regime, read.confidence) == (
        "BREACHED — spot at or above", None)


def test_one_strike_holding_both_walls_is_two_sided():
    from terrain_engine import wall_lean
    assert wall_lean(770.0, 770.0, "contains", "breached", "LONG_GAMMA_CHOP", "TRUSTED") == (
        ("TWO-SIDED — magnet, not a barrier",) * 2)
    assert wall_lean(780.0, 760.0, "contains", "contains", "LONG_GAMMA_CHOP", "TRUSTED") == ("DEALERS SELL", "DEALERS BUY")
    for regime, conf in (("UNAVAILABLE", "TRUSTED"), ("LONG_GAMMA_CHOP", "LEVEL_APPROX_NARROW_SPAN")):
        assert wall_lean(780.0, 760.0, "contains", "contains", regime, conf) == (None, None)


@pytest.fixture
def spy_levels(monkeypatch, pin_clock):
    bars = _load("real_spy_1m_bars_2026_09_24_25.json")["bars"]
    chain = _load("real_spy_0dte_chain.json")
    pin_clock(2026, 9, 22, 12, 46)                                   # the chain's own capture time
    terrain = {**compute_terrain("SPY", chain["chain"], chain["spot"]).to_dict(), "computed_ts_utc": time.time()}
    spot = bars[-1]["close"]
    monkeypatch.setattr(server, "_liquidity_1m_bars", lambda t: bars)
    monkeypatch.setattr(server, "resolve_spot", lambda t, **k: (spot, "live_quote", time.time()))
    monkeypatch.setattr(server, "terrain_cache_get", lambda t, now: terrain)
    pin_clock(2026, 9, 25, 16, 5)
    server._publish_price_levels("SPY")                              # as the bar writer does
    return spot, terrain


def test_levels_carry_the_gamma_family_into_the_one_distance_order(spy_levels):
    spot, terrain = spy_levels
    body = json.loads(server.get_levels(ticker="SPY").body)
    by_id = {r["id"]: r for r in body["levels"]}
    assert sum(terrain.get(gid) is not None for gid, _ in server.GAMMA_LEVELS) >= 8   # the real chain prices most
    for gid, _label in server.GAMMA_LEVELS:
        if terrain.get(gid) is not None:
            assert by_id[gid]["family"] == "gamma" and by_id[gid]["price"] == terrain[gid]
            assert gid in body["by_distance"]
    priced = [r for r in body["levels"] if r["price"] is not None]
    assert body["by_distance"] == [r["id"] for r in sorted(priced, key=lambda r: abs(r["price"] - spot))]
    assert all(r["side"] == ("AT" if round(r["price"] - spot, 2) == 0 else "ABOVE" if r["price"] > spot else "BELOW")
               for r in priced)


def test_a_same_day_chain_has_no_expected_move_and_says_why(spy_levels):
    """The SPY capture lists only the 0DTE expiry; the terrain's one-day move needs one a day out."""
    _spot, terrain = spy_levels
    assert terrain.get("implied_1d_move") is None
    body = json.loads(server.get_levels(ticker="SPY").body)
    assert not {"em_up", "em_dn"} & {r["id"] for r in body["levels"]}
    assert {"family": "expected_move", "reason": "the terrain has no implied 1-day move"} in body["families_absent"]


def test_the_expected_move_is_the_live_price_plus_and_minus_the_terrain_move(spy_levels, monkeypatch, pin_clock):
    """Real CRWD chain (expiries a day and more out). Stand-in: its capture spot as the live price;
    the SPY bars behind the other levels are not asserted here."""
    fx = _load("real_crwd_complete_chain_quarter.json")
    pin_clock(2026, 9, 2, 12, 0)
    terrain = {**compute_terrain("CRWD", [dict(c) for c in fx["chain"]], float(fx["spot"])).to_dict(),
               "computed_ts_utc": time.time()}
    spot = float(fx["spot"])
    monkeypatch.setattr(server, "terrain_cache_get", lambda t, now: terrain)
    monkeypatch.setattr(server, "resolve_spot", lambda t, **k: (spot, "live_quote", time.time()))
    body = json.loads(server.get_levels(ticker="SPY").body)
    by_id = {r["id"]: r for r in body["levels"]}
    em = terrain["implied_1d_move"]["points"]
    assert by_id["em_up"]["price"] == spot + em and by_id["em_dn"]["price"] == spot - em
    assert by_id["em_up"]["family"] == by_id["em_dn"]["family"] == "expected_move"
    assert "expected_move" not in {f["family"] for f in body["families_absent"]}


def test_every_level_is_served_with_its_name_and_short_tag(spy_levels):
    """The proximity strip printed raw ids (OVERNIGHT_HIGH, PD_VAH) and the chart kept its own
    short-name table; both names are served now, from one table (LEVEL_NAMES)."""
    from liquidity_value_engine import LEVEL_NAMES
    body = json.loads(server.get_levels(ticker="SPY").body)
    snap = [r for r in body["levels"] if r["id"] in LEVEL_NAMES]
    assert len(snap) >= 8                                    # the real SPY bars price most of them
    for r in body["levels"]:
        assert r["label"] and r["short"], r["id"]
        if r["id"] in LEVEL_NAMES:
            assert (r["label"], r["short"]) == LEVEL_NAMES[r["id"]]


def test_vwap_is_served_per_chart_bar(spy_levels):
    one = json.loads(server.get_levels(ticker="SPY", tf="1").body)["vwap_series"]
    fifteen = json.loads(server.get_levels(ticker="SPY", tf="15").body)["vwap_series"]
    buckets = {}
    for r in one:                                                    # first minute stamps, last minute's value
        k = int(r[0] // 900)
        buckets[k] = [buckets[k][0] if k in buckets else r[0]] + list(r[1:])
    assert len(one) > 100 and fifteen == [buckets[k] for k in sorted(buckets)]


def test_the_desk_window_is_the_calendars_last_session_open_and_its_words_are_served():
    """Register P-15: the page kept its own copy of the lookback words; the window's session start
    was a hard-coded 9:30 with a 24-hour stand-in when no session was found."""
    from time_et import ET
    sat = datetime(2026, 9, 26, 11, 0, tzinfo=ET)                    # Saturday: Friday's open
    assert server._desk_window_start("30", sat) == datetime(2026, 9, 25, 9, 30, tzinfo=ET).timestamp()
    mon = datetime(2026, 9, 28, 10, 0, tzinfo=ET)
    assert server._desk_window_start("30", mon) == datetime(2026, 9, 28, 9, 30, tzinfo=ET).timestamp()
    assert server._desk_window_start("1", mon) == mon.timestamp() - 900
    # the reference's 5-minute Market Map lists the session's events (its queue: "since open")
    assert server._desk_window_start("5", mon) == datetime(2026, 9, 28, 9, 30, tzinfo=ET).timestamp()
    words = {tf: words for tf, (_lb, words) in server.DESK_LOOKBACK.items()}
    assert words["30"] == words["5"] == "this session"


def test_every_bar_carries_its_change():
    import live_price_rows
    for b in _load("real_spy_1m_bars_2026_09_24_25.json")["bars"][:50]:
        bar = live_price_rows.with_change({"o": b["open"], "c": b["close"]})
        assert bar["chg"] == pytest.approx(b["close"] - b["open"])
        assert bar["chg_pct"] == pytest.approx((b["close"] - b["open"]) / b["open"] * 100)
