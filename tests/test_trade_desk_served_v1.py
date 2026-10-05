"""The Trade Desk computes nothing (P1-3, PR B): every value it shows is served. Real data only:
Schwab's SPY 1-minute bars (2026-09-24/25), SPY level crosses (2026-09-09..25), a TSLA NASDAQ book
and the SPY 0DTE and CRWD chains (tests/fixtures). Expected values are worked out here from the
fixtures themselves."""
import json
import time
from datetime import datetime
from pathlib import Path

import pytest

import live_market_plane as lmp
import server
import time_et
from app.options.order_flow import streaming as ofs
from calibration.complete_chain_capture import CAPTURE_BASIS
from instrument_identity import ticker_storage_key
from liquidity_value_engine import _MATERIALIZED_SNAPSHOTS
from micro_structure import Candle
from terrain_engine import compute_terrain
from tests.feed_live_helper import mark_feed_live, publish_daemon_rows

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


def _desk_events(monkeypatch, ticker, crosses, now, tf):
    """/api/desk/events on real crosses, at `now`: the stored crosses loaded as the console's
    start loads them (server._load_crosses)."""
    newest_first = sorted(crosses, key=lambda r: r["ts_utc"], reverse=True)       # as db.get_recent_crosses reads
    monkeypatch.setattr(server.get_db(), "get_recent_crosses", lambda ticker, n=20: newest_first[:n])
    monkeypatch.setattr(server, "_crosses", {})
    server._load_crosses([ticker_storage_key(ticker)])
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
    out = _crwd_at(lambda b: b["spot"] + 1.0, pin_clock)
    assert out["dist_to_call_wall"] == pytest.approx(out["call_wall"] - out["spot"])
    assert out["dist_to_put_wall"] == pytest.approx(out["spot"] - out["put_wall"])
    assert out["flip_relation"] == (None if out["gamma_flip"] is None
                                    else "ABOVE" if out["spot"] >= out["gamma_flip"] else "BELOW")


def test_a_breached_wall_says_so_at_the_live_price(pin_clock):
    """Real CRWD chain; stand-in live prices one dollar beyond each wall."""
    out = _crwd_at(lambda b: b["call_wall"] + 1.0, pin_clock)
    assert out["spot"] > out["call_wall"]
    assert out["call_wall_state"] == "breached" and out["call_wall_lean"] == "BREACHED — spot above"
    out = _crwd_at(lambda b: b["put_wall"] - 1.0, pin_clock)
    assert out["spot"] < out["put_wall"]
    assert out["put_wall_state"] == "breached" and out["put_wall_lean"] == "BREACHED — spot below"


def test_a_containing_wall_earns_the_dealer_lean_only_on_a_trusted_flip(pin_clock):
    out = _crwd_at(lambda b: (b["call_wall"] + b["put_wall"]) / 2, pin_clock)
    assert out["call_wall_state"] == out["put_wall_state"] == "contains"
    earned = out["regime"] != "UNAVAILABLE" and out["confidence"] == "TRUSTED"
    assert out["call_wall_lean"] == ("DEALERS SELL" if earned else None)
    assert out["put_wall_lean"] == ("DEALERS BUY" if earned else None)


def test_one_strike_holding_both_walls_is_two_sided():
    from terrain_engine import wall_lean
    assert wall_lean(770.0, 770.0, "contains", "breached", "LONG_GAMMA_CHOP", "TRUSTED") == (
        ("TWO-SIDED — magnet, not a barrier",) * 2)
    assert wall_lean(780.0, 760.0, "contains", "contains", "LONG_GAMMA_CHOP", "TRUSTED") == ("DEALERS SELL", "DEALERS BUY")
    for regime, conf in (("UNAVAILABLE", "TRUSTED"), ("LONG_GAMMA_CHOP", "LEVEL_APPROX_NARROW_SPAN")):
        assert wall_lean(780.0, 760.0, "contains", "contains", regime, conf) == (None, None)


#: Stand-in: ticker ZZDESK carries Schwab's SPY bars and SPY 0DTE chain, ZZDESKEM the CRWD chain
DESK, DESK_EM = "ZZDESK", "ZZDESKEM"
#: the levels are served after Friday 2026-09-25's close
FRIDAY_CLOSE = datetime(2026, 9, 25, 16, 5, tzinfo=time_et.ET)


def _forget(tk):
    server._bars.pop(tk, None)
    ofs._price_rows.pop(tk, None)
    with server._terrain_cache_lock:
        server._terrain_cache.pop(tk, None)
    for key in [k for k in _MATERIALIZED_SNAPSHOTS if k[0] == tk]:
        del _MATERIALIZED_SNAPSHOTS[key]


def _priced(tk, chain, spot, ts_utc):
    """The chain priced as the console prices a stored capture (at its own time and spot)."""
    server._publish_levels(tk, captures=[{"et_date": datetime.fromtimestamp(ts_utc, time_et.ET).date().isoformat(),
                                          "ts_utc": ts_utc, "spot": spot, "basis": CAPTURE_BASIS,
                                          "contracts": [dict(c) for c in chain]}])
    return server.terrain_cache_get(tk)


def _live_price(tk, last):
    """Schwab's LAST_PRICE through the daemon's price row, its feed live (the daemon beats every
    second, so each read is marked live again)."""
    mark_feed_live(tk)
    lmp.record_from_level_one_equity(tk, {"LAST_PRICE": last}, received_ts=time.time())
    publish_daemon_rows(tk)


@pytest.fixture
def spy_levels():
    """ZZDESK's levels served after Friday's close: the SPY 0DTE chain priced at its capture
    time, the SPY bars published by the bar writer, and the last bar's close as Schwab's
    LAST_PRICE (stand-in). Returns (spot, terrain, serve(tf))."""
    bars = _load("real_spy_1m_bars_2026_09_24_25.json")["bars"]
    chain = _load("real_spy_0dte_chain.json")
    _forget(DESK)
    terrain = _priced(DESK, chain["chain"], chain["spot"], chain["ts_utc"])
    spot = bars[-1]["close"]
    for b in bars:
        server._keep_bar(DESK, Candle(ts=b["timestamp"] / 1000, open=b["open"], high=b["high"], low=b["low"],
                                      close=b["close"], volume=b["volume"]))
    server._publish_price_levels(DESK, FRIDAY_CLOSE)                  # as the bar writer does

    def serve(tf="1"):
        _live_price(DESK, spot)
        return server.levels_payload(DESK, tf, FRIDAY_CLOSE)
    yield spot, terrain, serve
    _forget(DESK)


def test_levels_carry_the_gamma_family_into_the_one_distance_order(spy_levels):
    spot, terrain, serve = spy_levels
    body = serve()
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
    _spot, terrain, serve = spy_levels
    assert terrain.get("implied_1d_move") is None
    body = serve()
    assert not {"em_up", "em_dn"} & {r["id"] for r in body["levels"]}
    assert {"family": "expected_move", "reason": "the terrain has no implied 1-day move"} in body["families_absent"]


def test_the_expected_move_is_the_live_price_plus_and_minus_the_terrain_move():
    """Real CRWD chain (expiries a day and more out), priced at 2026-09-02 12:00 ET, the capture
    day its source names (stand-in: the hour). Stand-in: its capture spot as Schwab's LAST_PRICE."""
    fx = _load("real_crwd_complete_chain_quarter.json")
    spot = float(fx["spot"])
    _forget(DESK_EM)
    try:
        terrain = _priced(DESK_EM, fx["chain"], spot, datetime(2026, 9, 2, 12, 0, tzinfo=time_et.ET).timestamp())
        _live_price(DESK_EM, spot)
        body = server.levels_payload(DESK_EM, "1", FRIDAY_CLOSE)
    finally:
        _forget(DESK_EM)
    by_id = {r["id"]: r for r in body["levels"]}
    em = terrain["implied_1d_move"]["points"]
    assert by_id["em_up"]["price"] == spot + em and by_id["em_dn"]["price"] == spot - em
    assert by_id["em_up"]["family"] == by_id["em_dn"]["family"] == "expected_move"
    assert "expected_move" not in {f["family"] for f in body["families_absent"]}


def test_every_level_is_served_with_its_name_and_short_tag(spy_levels):
    """The proximity strip printed raw ids (OVERNIGHT_HIGH, PD_VAH) and the chart kept its own
    short-name table; both names are served now, from one table (LEVEL_NAMES)."""
    from liquidity_value_engine import LEVEL_NAMES
    _spot, _terrain, serve = spy_levels
    body = serve()
    snap = [r for r in body["levels"] if r["id"] in LEVEL_NAMES]
    assert len(snap) >= 8                                    # the real SPY bars price most of them
    for r in body["levels"]:
        assert r["label"] and r["short"], r["id"]
        if r["id"] in LEVEL_NAMES:
            assert (r["label"], r["short"]) == LEVEL_NAMES[r["id"]]


def test_vwap_is_served_per_chart_bar(spy_levels):
    _spot, _terrain, serve = spy_levels
    one = serve("1")["vwap_series"]
    fifteen = serve("15")["vwap_series"]
    buckets = {}
    for r in one:                                                    # first minute stamps, last minute's value
        k = int(r[0] // 900)
        buckets[k] = [buckets[k][0] if k in buckets else r[0]] + list(r[1:])
    assert len(one) > 100 and fifteen == [buckets[k] for k in sorted(buckets)]


def test_levels_are_served_in_ladder_order_with_distance(spy_levels):
    """The levels panel and the Trade Desk used to sort levels, measure distance to spot and apply
    the 0.15% near-spot rule in the page. Real SPY 1-minute bars (2026-09-24 and 25)."""
    spot, _terrain, serve = spy_levels
    body = serve()
    priced = [r for r in body["levels"] if r["price"] is not None]
    assert len(priced) > 5
    assert [r["price"] for r in priced] == sorted((r["price"] for r in priced), reverse=True)
    for r in priced:
        assert r["distance"] == pytest.approx(r["price"] - spot)
        assert "near_spot" not in r          # no proximity flag (operator 2026-09-29)
    assert body["by_distance"] == [r["id"] for r in sorted(priced, key=lambda r: abs(r["price"] - spot))]


def test_the_volume_profile_the_value_area_is_read_from_is_served(spy_levels):
    """The Trade Desk reference draws the session's volume profile at the chart's left edge
    (2026-09-28). The profile was built for the value area and dropped; /api/levels serves that
    same profile: its POC/VAH/VAL are the served TODAY_ levels, its bins hold every RTH bar's
    volume, and each bin says whether it is inside the value area. Real SPY 1-minute bars."""
    _spot, _terrain, serve = spy_levels
    body = serve()
    vp = body["volume_profile"]
    by_id = {r["id"]: r["price"] for r in body["levels"]}
    assert (vp["poc"], vp["vah"], vp["val"]) == (by_id["TODAY_POC"], by_id["TODAY_VAH"], by_id["TODAY_VAL"])
    prices = [b[0] for b in vp["bins"]]
    assert prices == sorted(prices) and len(prices) > 100
    assert all(b[2] == (vp["val"] <= b[0] <= vp["vah"]) for b in vp["bins"])
    # the profile's scale is served: the POC bin's volume, the largest
    assert vp["max_volume"] == max(b[1] for b in vp["bins"]) == next(b[1] for b in vp["bins"] if b[0] == vp["poc"])
    at = [(datetime.fromtimestamp(b["timestamp"] / 1000, time_et.ET), b)
          for b in _load("real_spy_1m_bars_2026_09_24_25.json")["bars"]]
    rth = [b for d, b in at if d.date().isoformat() == "2026-09-25" and time_et.session_label(d) == "RTH"]
    # every RTH bar's volume is in the profile; the 15:59 bar sent no volume, cannot be placed, and
    # is counted and served (operator 2026-09-29: accounted for, not silently dropped)
    assert sum(b[1] for b in vp["bins"]) == pytest.approx(sum(b["volume"] for b in rth if b["volume"] is not None), rel=1e-9)
    assert (vp["bars"], vp["bars_without_volume"]) == (len(rth), sum(1 for b in rth if b["volume"] is None)) == (390, 1)
    assert vp["basis"].startswith("Estimated volume by price")


def test_after_the_close_the_levels_are_measured_from_schwabs_last_trade(spy_levels):
    """Monday 2026-09-28 21:40 ET: the Trade Desk chart drew no key level at all after the close --
    /api/levels served 30 SPY levels and an empty by_distance, because it was measured only from a
    live price. The spot is Schwab's last trade at any hour (operator 2026-10-01: "we use what
    schwab gives us and we display it"): the levels are ordered, and their distance measured, from
    it, carrying its trade time. Real SPY 1-minute bars (2026-09-24 and 25); the last trade is the
    one the daemon captured."""
    mark_feed_live(DESK)
    lmp.record_from_level_one_equity(DESK, {"LAST_PRICE": 772.04, "TRADE_TIME_MILLIS": 1790380799830},
                                     received_ts=time.time())
    publish_daemon_rows(DESK)
    body = server.levels_payload(DESK, "1", FRIDAY_CLOSE)
    priced = [r for r in body["levels"] if r["price"] is not None]
    assert len(priced) > 5 and body["spot"] == 772.04 and body["spot_as_of_ts_utc"] == 1790380799.83
    assert body["by_distance"] == [r["id"] for r in sorted(priced, key=lambda r: abs(r["price"] - 772.04))]
    assert all(r["distance"] == r["price"] - 772.04 for r in priced)


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
