"""spot_used_for_scoring must never silently carry a VWAP value (RC-close-2026-09-11), and a
HTTPException raised on the route's path must propagate as its own status code, not a blanket
500 -- both found by independent review of /api/liquidity-snapshot. Real data through the real
route: Schwab's SPY 1-minute bars of Thursday 2026-10-01 and Friday 10-02 as the capture daemon
recorded them (each minute's newest receipt), the levels published as the bar writer publishes
them, valued on Friday 2026-10-02 at 15:00 ET. Stand-in: ticker ZZLIQ carries the SPY bars."""
from __future__ import annotations

import json
import time
from datetime import datetime

import pytest

import live_market_plane as lmp
import server as srv
import liquidity_value_engine as lve
from app.options.order_flow import streaming as ofs
from liquidity_models import ZONE_DISPLAY, SnapshotType, ZoneType
from micro_structure import Candle
from tests.feed_live_helper import daemon_bars, mark_feed_live, publish_daemon_rows
from time_et import ET

TK = "ZZLIQ"
FRIDAY = datetime(2026, 10, 2, 15, 0, tzinfo=ET)


def _newest_per_minute() -> list:
    newest = {}
    for r in sorted(daemon_bars("real_daemon_bars_spy_tsla_2026_10_01_02.json", "SPY"), key=lambda r: r["ts_recv"]):
        newest[r["bar_start_ms"]] = r
    return [{"timestamp": ms, "open": r["open"], "high": r["high"], "low": r["low"], "close": r["close"],
             "volume": r["volume"]} for ms, r in sorted(newest.items())]


_BARS = [b for b in _newest_per_minute() if b["timestamp"] / 1000 < FRIDAY.timestamp()]


@pytest.fixture
def published():
    """The SPY bars to 15:00 ET on Friday in the console's memory and the levels published from
    them; nothing of the stand-in ticker is left behind."""
    def forget():
        srv._bars.pop(TK, None)
        ofs._price_rows.pop(TK, None)
        for key in [k for k in lve._MATERIALIZED_SNAPSHOTS if k[0] == TK]:
            del lve._MATERIALIZED_SNAPSHOTS[key]
    forget()
    for b in _BARS:
        if b["timestamp"] / 1000 < FRIDAY.timestamp():
            srv._keep_bar(TK, Candle(ts=b["timestamp"] / 1000, open=b["open"], high=b["high"], low=b["low"],
                                     close=b["close"], volume=b["volume"]))
    srv._publish_price_levels(TK, FRIDAY)
    yield
    forget()


def _body(resp):
    return json.loads(resp.body) if hasattr(resp, "body") else resp


def test_spot_used_for_scoring_is_null_not_vwap_when_no_live_spot_is_cached(published):
    """MEASURED 2026-09-11: with no live spot, spot_used_for_scoring used to be silently
    backfilled with the VWAP number and reported under the "spot" name. It must report null --
    absence stays absence. Schwab has sent no price for the ticker here."""
    body = _body(srv.liquidity_snapshot(TK, FRIDAY))
    assert body["raw_levels"]["vwap"] is not None, "the session's VWAP exists to be misused"
    assert body["spot_used_for_scoring"] is None
    assert "spot_estimate_vwap_fallback" not in body, "VWAP is never a stand-in for spot"


def test_missing_spot_produces_honest_null_distance_and_neutral_score_through_the_real_zone_path(published):
    """MEASURED 2026-09-11: the VWAP-as-spot value was also fed into the zone distance and sort.
    The real zones of the real levels: with no spot, distance and inside-zone are absent and the
    score is neutral -- not a crash, not a fabricated distance."""
    body = _body(srv.liquidity_snapshot(TK, FRIDAY))
    assert body["zones"]
    for z in body["zones"]:
        assert z["distance_to_spot"] is None
        assert z["spot_inside_zone"] is None
        assert isinstance(z["tradeable_score"], (int, float))
        # the pages named every zone that was not support_liquidity "Resistance": each zone's name
        # and side are served from its type
        assert (z["zone_label"], z["zone_side"]) == ZONE_DISPLAY[ZoneType(z["zone_type"])]


def test_spot_used_for_scoring_reports_the_real_live_spot_when_available(published):
    """The positive control: Schwab's LAST_PRICE, through the daemon's price row to the console
    (resolve_spot, the one spot authority), is reported as spot_used_for_scoring. Stand-in: the
    last bar's close as the LAST_PRICE Schwab sent."""
    last = _BARS[-1]["close"]
    mark_feed_live(TK)
    lmp.record_from_level_one_equity(TK, {"LAST_PRICE": last}, received_ts=time.time())
    publish_daemon_rows(TK)
    body = _body(srv.liquidity_snapshot(TK, FRIDAY))
    assert body["spot_used_for_scoring"] == last
    assert "spot_estimate_vwap_fallback" not in body
    assert body["snapshot_type"] == SnapshotType.LIVE.value


def test_an_http_exception_on_the_route_path_keeps_its_status_not_a_generic_500():
    """MEASURED 2026-09-11: an HTTPException on this route's path was re-issued as a bare 500. It
    must propagate as its own status: a blank ticker is refused by the snapshot read with 400."""
    resp = srv.liquidity_snapshot("", FRIDAY)
    assert resp.status_code == 400
    assert json.loads(resp.body)["error"] == "ticker is required"


class _FakeSnapshotOutput:
    def __init__(self, ticker, session_date, raw_levels, zones=None):
        self.ticker = ticker
        self.session_date = session_date
        self.snapshot_type = SnapshotType.LIVE
        self.zones = zones or []
        self.summary = None
        self.raw_levels = raw_levels


class _FakeCanon:
    generation, as_of_ts_utc, bar_source = 1, 0.0, "test"


def _wire_common(monkeypatch, *, raw_levels, zones=None, resolved_spot=None):
    monkeypatch.setattr(srv, "_liquidity_option_levels", lambda *a, **k: ([], "n/a"))
    monkeypatch.setattr(srv, "resolve_spot", lambda *a, **k: (resolved_spot, None, None))
    # the route's one level input: the materialized price-level snapshot
    monkeypatch.setattr(srv, "canonical_price_level_snapshot", lambda t: _FakeCanon())
    fake_out = _FakeSnapshotOutput("SPY", "2020-01-02", raw_levels, zones=zones)
    monkeypatch.setattr(lve, "build_live_snapshot", lambda *a, **k: fake_out)
    return fake_out


def test_an_unrelated_crash_still_reports_500(monkeypatch):
    """Negative control: a genuine unexpected error still reports 500."""
    _wire_common(monkeypatch, raw_levels={})

    def _boom(*a, **k):
        raise RuntimeError("something actually broke")
    monkeypatch.setattr(srv, "canonical_price_level_snapshot", _boom)
    resp = srv.get_liquidity_snapshot(ticker="SPY")
    assert resp.status_code == 500
    assert "something actually broke" in json.loads(resp.body)["error"]
