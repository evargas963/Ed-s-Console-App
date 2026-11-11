"""The levels and strikes panels: what they serve."""

from __future__ import annotations

from datetime import datetime as _dt

import live_market_plane as lmp
import server as srv
import time_et
from liquidity_value_engine import _MATERIALIZED_SNAPSHOTS, DAILY_CANDLE_BASIS
from math_exposure_core import (
    compute_exposures_by_strike,
    net_gex_dollars_at_strike,
    strike_total_volume,
)
from micro_structure import Candle
from option_contract import read_chain
from tests.feed_live_helper import (
    daemon_bars,
    daemon_status,
    hold_schwab_daily,
    price_history,
    stream_daemon_bars,
)
from tests.page_on_socket import pages
from tests.real_chains import SPY_0DTE as C
from time_et import ET

#: Schwab's SPY and TSLA bars as the capture daemon recorded them, Thu 2026-10-01 and Fri 10-02
#: (sessions Schwab's /markets answers; tests/conftest.py)
_DAEMON_BARS = daemon_bars("real_daemon_bars_spy_tsla_2026_10_01_02.json")
_PAIR = ("SPY", "TSLA")


def _forget(*tickers: str) -> None:
    """No bar in memory or published level of `tickers` is left behind."""
    for tk in tickers:
        srv._bars.pop(tk, None)
        srv._series.pop((tk, "1d"), None)
        for key in [k for k in _MATERIALIZED_SNAPSHOTS if k[0] == tk]:
            del _MATERIALIZED_SNAPSHOTS[key]


def _candle(b: dict) -> Candle:
    return Candle(
        ts=b["timestamp"] / 1000.0,
        open=b["open"],
        high=b["high"],
        low=b["low"],
        close=b["close"],
        volume=b["volume"],
    )


def _newest(rows: list[dict], tk: str) -> list[dict]:
    """Schwab's newest receipt of each minute of `tk`, in time order."""
    out = {}
    for r in sorted(rows, key=lambda r: r["ts_recv"]):
        if r["symbol"] == tk:
            out[r["bar_start_ms"]] = r
    return [out[ms] for ms in sorted(out)]


def _sent_daily(tk: str, day: str) -> dict:
    """Schwab's daily candle of `tk` for `day`, as sent (real_pricehistory_spy_tsla_2026_10_07)."""
    (candle,) = [
        c
        for c in price_history(tk, "1d")["body"]["candles"]
        if _dt.fromtimestamp(c["datetime"] / 1000, ET).date().isoformat() == day
    ]
    return candle


def _rth(rows: list[dict], tk: str, day: str) -> list[dict]:
    at = [(_dt.fromtimestamp(r["bar_start_ms"] / 1000, ET), r) for r in _newest(rows, tk)]
    return [r for d, r in at if d.date().isoformat() == day and 570 <= d.hour * 60 + d.minute < 960]


# ── the levels panel's contract ──────────────────────────────────────────────────────


def test_api_levels_b1_contract_single_session_prior_day():
    """The B1 read-adapter serves the prior_day family from the RC-153 single-session authority.

    It serves it with per-level provenance naming the window, unique ids, honest
    families_absent — and never the multi-session union values (the RC-213 defect). A tape of
    tiny sessions tests window selection (their prior day is stamped degraded, and still
    served); stand-in: ticker ZZB1.
    """
    tk = "ZZB1"

    def _bar(y, mo, d, h, mi, o, hi, lo, c):
        return {
            "timestamp": int(_dt(y, mo, d, h, mi, tzinfo=ET).timestamp() * 1000),
            "open": o,
            "high": hi,
            "low": lo,
            "close": c,
            "volume": 1000.0,
        }

    tape = [
        _bar(2026, 10, 1, 10, 0, 100, 110, 90, 100),  # older prior session: both extremes
        _bar(2026, 10, 1, 14, 0, 100, 101, 99, 100),
        _bar(2026, 10, 2, 10, 0, 96, 105, 95, 97),  # most recent prior session (a Friday)
        _bar(2026, 10, 2, 15, 59, 101, 103, 100, 102),
        _bar(2026, 10, 5, 9, 35, 103, 104, 102, 103),  # today (Monday) inside ORB window
        _bar(2026, 10, 5, 9, 45, 103, 104, 102, 103),  # today post-ORB
    ]
    now = _dt(2026, 10, 5, 10, 0, tzinfo=ET)
    # the tape's two prior sessions as Schwab's daily candles carry them, dated at midnight ET
    daily = [
        {
            "datetime": b["timestamp"],
            **{k: b[k] for k in ("open", "high", "low", "close", "volume")},
        }
        for b in (
            _bar(2026, 10, 1, 0, 0, 100, 110, 90, 100),
            _bar(2026, 10, 2, 0, 0, 96, 105, 95, 102),
        )
    ]
    _forget(tk)
    try:
        for b in tape:
            srv._keep_bar(tk, _candle(b))
        srv._write_price_history({"symbol": tk, "series": "1d", "answer": {"candles": daily}})
        srv._publish_price_levels(tk, now)  # as the bar writer does
        payload = srv.levels_payload(tk, "1", now)
    finally:
        _forget(tk)

    assert payload["schema_version"] == 1
    assert payload["spot"] is None, (
        "Schwab has sent the stand-in no price: absent, never a stand-in value"
    )

    ids = [lv["id"] for lv in payload["levels"]]
    assert len(ids) == len(set(ids)), "level ids must be UNIQUE per payload (RC-88)"
    by_id = {lv["id"]: lv for lv in payload["levels"]}
    assert by_id["PDH"]["price"] == 105 and by_id["PDL"]["price"] == 95, (
        "prior_day must be the SINGLE most recent prior RTH session"
    )
    assert by_id["PDC"]["price"] == 102
    for lv in payload["levels"]:
        assert lv["price"] not in (110, 90), "multi-session union value served — RC-213 reopened"
        assert "as_of_ts_utc" in lv["staleness"] and "age_sec" in lv["staleness"]
        if lv["family"] == "prior_day":
            assert lv["provenance"]["session_scope"] == "RTH"
            assert "2026-10-02" in lv["provenance"]["window"], (
                "provenance.window must name the literal session used (RC-153)"
            )

    fams = {f["family"] for f in payload["families_absent"]}
    # 2026-09-27: the gamma family is CARRIED from the terrain (one ranked list of levels for the
    # Trade Desk chart), never computed by Tier-B: every gamma row says so in its provenance.
    for lv in payload["levels"]:
        if lv["family"] == "gamma":
            assert lv["provenance"] == {
                "producer": "terrain_engine.compute_terrain",
                "carried": True,
            }
    # Tier-B (levels-tierb-session-collapse-v1): session families are served from the engine
    # when today bars exist — not left as soft B1-absent placeholders.
    assert "VWAP" in by_id and by_id["VWAP"]["family"] == "vwap"
    assert "ORB_HIGH" in by_id and by_id["ORB_HIGH"]["family"] == "opening_range"
    assert "TODAY_POC" in by_id and by_id["TODAY_POC"]["family"] == "value_area"
    assert all(f.get("reason") for f in payload["families_absent"])
    assert "vwap" not in fams, "vwap must be served by Tier-B, not declared absent when bars exist"


# ── RC-227: one-faucet closeout locks (mission one-faucet-closeout-v1) ────────────────


def test_strikes_payload_carries_server_side_sums():
    """STRIP server half: the strikes panel serves today_side_sums against its own spot.

    Computed against the payload's own spot — the one aggregator. SPY's same-day chain
    (tests/real_chains.SPY_0DTE) published by the levels producer at its captured price, the
    price row there with the feed live; each side's sum is its strikes' GEX and volume from the
    same chain's book.
    """
    srv._publish_levels(
        C.ticker, read_chain(C.chain), C.now.timestamp(), chain_spot=(C.spot, 1.0), now=C.now
    )
    lmp.record_feed_heartbeat(
        daemon_status(
            time_et.now(), schwab_socket_open=True, held={"LEVELONE_EQUITIES": [C.ticker]}
        )
    )
    lmp.record_from_level_one_equity(
        C.ticker, {"LAST_PRICE": C.spot, "TRADE_TIME_MILLIS": 1000}, received_ts=time_et.now()
    )
    try:
        body = srv.strikes(C.ticker, time_et.now(), {"scope": "auto", "centre": None, "shift": 0})
        live = srv.resolve_spot(C.ticker, now=time_et.now())[0]
    finally:
        with srv._terrain_cache_lock:
            srv._terrain_cache.pop(C.ticker, None)
        lmp._by_ticker.pop(C.ticker, None)
        lmp._fields_by_ticker.pop(C.ticker, None)
        lmp.record_feed_down()
    book = compute_exposures_by_strike(read_chain(C.chain), spot=C.spot, now=C.now)[0]
    below = [b for k, b in book.items() if k < C.spot]
    above = [b for k, b in book.items() if k > C.spot]
    ss = body["today_side_sums"]
    assert ss["gex_below"] == sum(net_gex_dollars_at_strike(b) for b in below)
    assert ss["gex_above"] == sum(net_gex_dollars_at_strike(b) for b in above)
    drawn = body["today"]["all"]
    assert drawn, "the panel draws strikes of the real chain"
    assert all(r[2] == strike_total_volume(book[r[0]]) for r in drawn)
    assert live == C.spot, "sums must be computed against the one live spot"


def test_api_levels_prior_day_is_the_whole_recorded_prior_session():
    """t12 (RC-227 residual): the PDL must be the min of the WHOLE prior session.

    Measured live: a truncated in-memory tape served PDL 756.84 vs the true 749.59 while PDH/PDC
    matched. The prior day's high, low and close are Schwab's daily candle for it, as sent: its
    high and low are the whole session's 1-minute extremes, and its close is the official close,
    which the last 1-minute bar's is not. Schwab's SPY and TSLA bars of Thu 2026-10-01 as recorded
    and their daily candles (real_pricehistory_spy_tsla_2026_10_07.json), the levels of Fri 10-02
    at 10:00 ET.
    """
    now = _dt(2026, 10, 2, 10, 0, tzinfo=ET)
    _forget(*_PAIR)
    try:
        stream_daemon_bars(_DAEMON_BARS)
        for tk in _PAIR:
            hold_schwab_daily(tk)
        payloads = {}
        for tk in _PAIR:
            srv._publish_price_levels(tk, now)  # as the bar writer does
            payloads[tk] = srv.levels_payload(tk, "1", now)
    finally:
        _forget(*_PAIR)
    for tk in _PAIR:
        monday = _rth(_DAEMON_BARS, tk, "2026-10-01")
        assert len(monday) == 390, tk
        by_id = {lv["id"]: lv for lv in payloads[tk]["levels"]}
        assert by_id["PDL"]["price"] == min(r["low"] for r in monday), (
            tk,
            "PDL is not the whole prior session's min",
        )
        assert by_id["PDH"]["price"] == max(r["high"] for r in monday), tk
        thursday = _sent_daily(tk, "2026-10-01")
        assert by_id["PDC"]["price"] == thursday["close"] != monday[-1]["close"], tk
        assert by_id["PDL"]["provenance"]["vendor_basis"] == DAILY_CANDLE_BASIS, (
            "provenance names Schwab's daily candle"
        )


def test_the_bar_writer_publishes_the_levels_and_the_route_only_serves_them():
    """The bar writer publishes a ticker's price levels after each of its bars.

    Every ticker, viewed or not, so a page switching to it finds them current; a new session is
    built by the levels loop; the route serves what was published and reads no bar. Schwab's SPY
    and TSLA bars of 2026-10-01/02 as the capture daemon recorded them: each ticker's newest
    receipt arrives as a pushed bar, valued at Fri 10-02 19:59:30 ET, the rest streamed before
    it.
    """
    tk, other = _PAIR
    now = _dt(2026, 10, 2, 19, 59, 30, tzinfo=ET)
    pushed = {t: _newest(_DAEMON_BARS, t)[-1] for t in _PAIR}
    loaded = [r for r in _DAEMON_BARS if r not in pushed.values()]
    _forget(*_PAIR)
    try:
        stream_daemon_bars(loaded)
        for t in _PAIR:
            hold_schwab_daily(t)

        # nothing published yet: the levels are absent with their reason
        none_yet = srv.levels_payload(tk, "1", now)
        assert none_yet["generation"] is None
        assert {"family": "price_levels", "reason": srv.NO_PRICE_LEVELS_REASON} in none_yet[
            "families_absent"
        ]

        # a minute's bars arrive together (SPY and TSLA): each write is pushed as `liquidity` and
        # each ticker's levels published from its bars as `levels`, to the page open on it (the
        # push itself, on the socket server's loop)
        with pages() as served:
            shown = {t: served.open(t, "liquidity", "levels") for t in (tk, other)}
            elsewhere = served.open("ZZELSE", "liquidity", "levels")
            srv._write_streamed_bars([pushed[t] for t in (tk, other)], now)
            told = {t: served.told(page, 5) for t, page in shown.items()}
            assert served.told(elsewhere) == set(), "a page on another ticker is told nothing"
        assert told == {tk: {"liquidity", "levels"}, other: {"liquidity", "levels"}}
        served = srv.levels_payload(tk, "1", now)
        assert served["generation"] is not None
        assert served["snapshot_as_of_ts_utc"] == pushed[tk]["bar_start_ms"] / 1000.0
        assert (
            srv.canonical_price_level_snapshot(other, now).as_of_ts_utc
            == pushed[other]["bar_start_ms"] / 1000.0
        )
        # the route reads no bar: with the ticker's bars gone from memory it serves the same levels
        kept = srv._bars.pop(tk)
        again = srv.levels_payload(tk, "15", now)
        assert again["generation"] == served["generation"]
        assert [(r["id"], r["price"]) for r in again["levels"]] == [
            (r["id"], r["price"]) for r in served["levels"]
        ]
        srv._bars[tk] = kept

        # a new session: the levels loop builds its levels (10-02 is its prior day: Schwab's daily
        # high 772.65, which the recorded stream's bars, topping at 772.49, missed)
        monday = _dt(2026, 10, 5, 7, 30, tzinfo=ET)  # pre-market (Schwab's: 07:00)
        srv._publish_missing_price_levels([tk], monday)
        nextday = srv.levels_payload(tk, "1", monday)
        assert {lv["id"]: lv["price"] for lv in nextday["levels"]}["PDH"] == _sent_daily(
            tk, "2026-10-02"
        )["high"]
    finally:
        _forget(*_PAIR)
