"""Adversarial lock: MARK / close / chain / snapshot / bar-close cannot become current live spot."""

from __future__ import annotations

import time

import live_market_plane as L
import server


class _FakeResp:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _no_last_price_quote(tk: str) -> _FakeResp:
    return _FakeResp({
        tk: {
            "quote": {"mark": 111.11, "closePrice": 110.0, "bidPrice": 110.9, "askPrice": 111.2},
            "regular": {"regularMarketLastPrice": 110.0},
            "extended": {"mark": 111.05},
        }
    })


def test_resolve_spot_rejects_mark_close_chain_and_snapshot(monkeypatch) -> None:
    monkeypatch.setattr(server, "get_client", lambda: object())
    L._by_ticker.pop("SPY", None)
    spot, source, _ts = server.resolve_spot(
        "SPY",
        allow_stored=True,
        chain_json={"underlying": {"last": 743.29, "mark": 743.20, "close": 743.10}},
    )
    assert spot is None
    assert source == "none"
    assert server.current_spot_state(source, "SPY") == "unavailable"


def test_plane_mark_only_tick_never_creates_current_spot() -> None:
    L._by_ticker.pop("MARKNEVER", None)
    ok = L.record_from_level_one_equity(
        "MARKNEVER",
        {"key": "MARKNEVER", "MARK": 20.95, "BID_PRICE": 20.9, "ASK_PRICE": 21.1},
        received_ts=time.time(),
    )
    assert ok is False
    assert L.get_quote("MARKNEVER") is None
    spot, source, _ts = server.resolve_spot("MARKNEVER")
    assert spot is None
    assert source == "none"


def test_plane_mark_cannot_replace_prior_last_price() -> None:
    L._by_ticker.pop("KEEPLAST", None)
    assert L.record_from_level_one_equity(
        "KEEPLAST",
        {"key": "KEEPLAST", "LAST_PRICE": 50.0, "MARK": 50.2, "BID_PRICE": 49.9, "ASK_PRICE": 50.1},
        received_ts=time.time(),
    )
    assert L.record_from_level_one_equity(
        "KEEPLAST",
        {"key": "KEEPLAST", "MARK": 99.99, "BID_PRICE": 99.9, "ASK_PRICE": 100.1},
        received_ts=time.time(),
    )
    row = L.get_quote("KEEPLAST")
    assert row is not None
    assert row["spot"] == 50.0
    assert row["quote_source_detail"]["spot"] == "LAST_PRICE"
    L._by_ticker.pop("KEEPLAST", None)






def test_reprice_and_api_spot_do_not_use_bar_close_or_snapshot(monkeypatch) -> None:
    monkeypatch.setattr(server, "get_client", lambda: object())
    cached = {
        "ticker": "SPY",
        "spot": 745.10,
        "spot_source": server.SPOT_SOURCE_PLANE,  # the terrain loop's own stamp on a cached spot
        "regime": "LONG_GAMMA_CHOP",
        "call_wall": 750.0,
        "put_wall": 740.0,
    }
    out = server._reprice_cached_terrain(cached, "SPY")
    assert out["spot"] is None
    assert out["spot_state"] == "unavailable"
    assert out["call_wall"] == 750.0

    spot, source, _ts = server.resolve_spot("SPY")
    assert spot is None
    assert source == "none"


def test_institutional_check_bans_mark_or_stored_current_spot() -> None:
    from tools.check_institutional_correctness import check_single_spot_authority

    assert check_single_spot_authority() == []
