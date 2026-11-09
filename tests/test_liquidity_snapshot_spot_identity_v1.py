"""/api/liquidity-snapshot: spot_used_for_scoring never carries a VWAP value, and an
HTTPException raised on the route's path keeps its own status code. Real data through the real
route: Schwab's SPY 1-minute bars of Thursday 2026-10-01 and Friday 10-02 as the capture daemon
recorded them (each minute's newest receipt), the levels published as the bar writer publishes
them, valued on Friday 2026-10-02 at 15:00 ET. Stand-in: ticker ZZLIQ carries the SPY bars.
"""

from __future__ import annotations

import json

import pytest

import live_market_plane as lmp
import server as srv
from liquidity_models import ZONE_DISPLAY, SnapshotType, ZoneType
from tests.feed_live_helper import daemon_status
from tests.liquidity_friday import FRIDAY, TK, friday_bars


def _body(resp):
    return json.loads(resp.body) if hasattr(resp, "body") else resp


@pytest.mark.usefixtures("published")
def test_spot_used_for_scoring_is_null_not_vwap_when_no_live_spot_is_cached():
    """With no live spot, spot_used_for_scoring is null, never the VWAP under the "spot" name:
    absence stays absence. Schwab has sent no price for the ticker here.
    """
    body = _body(srv.liquidity_snapshot(TK, FRIDAY))
    vwap = srv.canonical_price_level_snapshot(TK, FRIDAY).price("VWAP")
    assert vwap is not None, "the session's VWAP exists to be misused"
    assert body["spot_used_for_scoring"] is None
    assert "spot_estimate_vwap_fallback" not in body, "VWAP is never a stand-in for spot"


@pytest.mark.usefixtures("published")
def test_missing_spot_produces_honest_null_distance_through_the_real_zone_path():
    """The real zones of the real levels: with no spot, distance and inside-zone are absent --
    not a crash, not a fabricated distance, never VWAP standing in for the spot.
    """
    body = _body(srv.liquidity_snapshot(TK, FRIDAY))
    assert body["zones"]
    lows = [z["zone_low"] for z in body["zones"]]
    assert lows == sorted(lows), "with no spot the zones are listed by price, lowest first"
    for z in body["zones"]:
        assert z["distance_to_spot"] is None
        assert z["spot_inside_zone"] is None
        assert "tradeable_score" not in z, "a score no page reads is not served"
        # the pages named every zone that was not support_liquidity "Resistance": each zone's name
        # and side are served from its type
        assert (z["zone_label"], z["zone_side"]) == ZONE_DISPLAY[ZoneType(z["zone_type"])]


@pytest.mark.usefixtures("published")
def test_spot_used_for_scoring_reports_the_real_live_spot_when_available():
    """The positive control: Schwab's LAST_PRICE, through the daemon's price row to the console
    (resolve_spot, the one spot authority), is reported as spot_used_for_scoring. Stand-in: the
    last bar's close as the LAST_PRICE Schwab sent.
    """
    last, at = friday_bars()[-1]["close"], FRIDAY.timestamp()
    lmp.record_feed_heartbeat(
        daemon_status(at, schwab_socket_open=True, held={"LEVELONE_EQUITIES": [TK]})
    )
    lmp.record_from_level_one_equity(TK, {"LAST_PRICE": last}, received_ts=at)
    body = _body(srv.liquidity_snapshot(TK, FRIDAY))
    assert body["spot_used_for_scoring"] == last
    assert "spot_estimate_vwap_fallback" not in body
    assert body["snapshot_type"] == SnapshotType.LIVE.value


def test_an_http_exception_on_the_route_path_keeps_its_status_not_a_generic_500():
    """An HTTPException on this route's path keeps its own status, not a bare 500: a blank
    ticker is refused by the snapshot read with 400.
    """
    resp = srv.liquidity_snapshot("", FRIDAY)
    assert resp.status_code == 400
    assert json.loads(resp.body)["error"] == "ticker is required"
