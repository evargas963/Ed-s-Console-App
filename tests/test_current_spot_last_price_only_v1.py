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


def test_parser_rejects_mark_close_and_midpoint() -> None:
    parsed = server._parse_quote_node_session_fields({
        "quote": {"mark": 111.11, "closePrice": 110.0, "bidPrice": 110.9, "askPrice": 111.2},
        "regular": {"regularMarketLastPrice": 110.0},
    })
    assert parsed["spot"] is None
    assert parsed["spot_source"] is None
    assert parsed["mark"] == 111.11
    assert parsed["regular_close"] == 110.0


def test_resolve_spot_rejects_mark_close_chain_and_snapshot(monkeypatch) -> None:
    monkeypatch.setattr(server, "get_client", lambda: object())
    monkeypatch.setattr(server, "safe_get_quote", lambda _c, tk, **_k: _no_last_price_quote(tk))
    monkeypatch.setattr(server, "_spot_from_stored", lambda _tk: (742.48, 1.0))
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
    )
    assert L.record_from_level_one_equity(
        "KEEPLAST",
        {"key": "KEEPLAST", "MARK": 99.99, "BID_PRICE": 99.9, "ASK_PRICE": 100.1},
    )
    row = L.get_quote("KEEPLAST")
    assert row is not None
    assert row["spot"] == 50.0
    assert row["quote_source_detail"]["spot"] == "LAST_PRICE"
    L._by_ticker.pop("KEEPLAST", None)


def test_stale_plane_last_price_beats_mark_but_is_labelled_stale(monkeypatch) -> None:
    tk = "STALELAST"
    L._by_ticker[tk] = {
        "spot": 700.42,
        "server_received_ts": time.time() - (L.PLANE_QUOTE_STALE_SEC + 5.0),
        "exchange_quote_ts": 1_800_000_000.0,
        "quote_source_detail": {"spot": "LAST_PRICE"},
    }
    try:
        monkeypatch.setattr(server, "get_client", lambda: object())
        monkeypatch.setattr(server, "safe_get_quote", lambda _c, _tk, **_k: _no_last_price_quote(_tk))
        spot, source, _ts = server.resolve_spot(tk)
        assert spot == 700.42
        assert source == server.SPOT_SOURCE_PLANE
        assert server.current_spot_state(source, tk) == "stale"
    finally:
        L._by_ticker.pop(tk, None)


def test_merge_and_l1_overlay_ignore_mark_plane_spot() -> None:
    tk = "MARKPLANE"
    L._by_ticker[tk] = {
        "spot": 999.0,
        "spot_disp": "999.00",
        "server_received_ts": time.time(),
        "quote_source_detail": {"spot": "MARK"},
    }
    try:
        ms = {"spot": 700.42, "ticker": tk}
        L.merge_into_state(ms, tk)
        assert ms["spot"] == 700.42
        l1 = {"spot": 700.42}
        L.apply_l1_live_quote_overlay(l1, tk)
        assert l1["spot"] == 700.42
        assert "l1_live_overlay_applied" not in l1
    finally:
        L._by_ticker.pop(tk, None)


def test_reprice_and_api_spot_do_not_use_bar_close_or_snapshot(monkeypatch) -> None:
    monkeypatch.setattr(server, "get_client", lambda: object())
    monkeypatch.setattr(server, "safe_get_quote", lambda _c, tk, **_k: _no_last_price_quote(tk))
    monkeypatch.setattr(server, "_spot_from_stored", lambda _tk: (745.10, 1.0))
    cached = {
        "ticker": "SPY",
        "spot": 745.10,
        "spot_source": server.SPOT_SOURCE_SNAPSHOT,
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


def test_rest_last_price_without_matching_trade_time_is_unavailable() -> None:
    parsed = server._parse_quote_node_session_fields({
        "quote": {"lastPrice": 760.40, "mark": 760.41},
        "regular": {"regularMarketTradeTime": 1_784_491_628_000, "regularMarketLastPrice": 758.0},
    })
    assert parsed["spot"] == 760.40
    assert parsed["trade_time"] is None
    assert parsed["last_price_session"] == "quote"
    assert server.current_spot_state(server.SPOT_SOURCE_QUOTE, "SPY") == "unavailable"
    assert server.current_spot_state(server.SPOT_SOURCE_QUOTE, "SPY", as_of_ts=None) == "unavailable"


def test_rest_fast_quote_refuses_unbound_last_price(monkeypatch) -> None:
    class _Resp:
        status_code = 200

        def json(self):
            return {"UNBOUND": {"quote": {"lastPrice": 12.34, "mark": 12.35, "bidPrice": 12.3, "askPrice": 12.4}}}

    monkeypatch.setattr(server, "get_client", lambda: object())
    monkeypatch.setattr(server, "_safe_get_quote_with_retry", lambda *_a, **_k: _Resp())
    payload = server._build_rest_fast_quote_payload("UNBOUND", "rest_fast_quote")
    assert payload["spot"] is None
    assert payload["last_price_native_ts"] is None
    assert payload["quote_source_detail"]["spot"] == "unavailable_missing_last_price"


def test_bid_ask_only_tick_does_not_refresh_last_price_clocks() -> None:
    tk = "CLOCKHOLD"
    L._by_ticker.pop(tk, None)
    assert L.record_from_level_one_equity(
        tk,
        {"key": tk, "LAST_PRICE": 50.0, "TRADE_TIME_MILLIS": 1_800_000_000_000,
         "BID_PRICE": 49.9, "ASK_PRICE": 50.1},
    )
    first = L.get_quote(tk)
    assert first is not None
    native = first["last_price_native_ts"]
    received = first["last_price_received_ts"]
    generation = first["last_price_generation"]
    assert L.record_from_level_one_equity(
        tk,
        {"key": tk, "BID_PRICE": 49.8, "ASK_PRICE": 50.2, "QUOTE_TIME_MILLIS": 1_800_000_100_000},
    )
    second = L.get_quote(tk)
    assert second is not None
    assert second["spot"] == 50.0
    assert second["last_price_native_ts"] == native
    assert second["last_price_received_ts"] == received
    assert second["last_price_generation"] == generation
    assert second["quote_source_detail"]["carried_forward"] is True
    L._by_ticker.pop(tk, None)


def test_gamma_current_spot_is_separate_from_computed_from_spot(monkeypatch) -> None:
    L._by_ticker["CURSPOT"] = {
        "spot": 760.40,
        "last_price_native_ts": time.time(),
        "last_price_received_ts": time.time(),
        "last_price_generation": 3,
        "server_received_ts": time.time(),
        "quote_source_detail": {"spot": "LAST_PRICE"},
    }
    try:
        monkeypatch.setattr(server, "get_client", lambda: object())
        monkeypatch.setattr(server, "safe_get_quote", lambda *_a, **_k: _no_last_price_quote("CURSPOT"))
        fields = server._gamma_current_spot_fields("CURSPOT", 757.47)
        assert fields["current_spot"] == 760.40
        assert fields["spot_is_current"] is False
        assert fields["current_spot_state"] == "live"
        same = server._gamma_current_spot_fields("CURSPOT", 760.40)
        assert same["spot_is_current"] is True
    finally:
        L._by_ticker.pop("CURSPOT", None)


def test_institutional_check_bans_mark_or_stored_current_spot() -> None:
    from tools.check_institutional_correctness import check_single_spot_authority

    assert check_single_spot_authority() == []


_QUOTE_TT = 1_800_000_111.0
_EXT_TT = 1_800_000_222.0
_REG_TT_MS = 1_800_000_333_000


def test_quote_last_price_binds_only_quote_trade_time() -> None:
    parsed = server._parse_quote_node_session_fields({
        "quote": {"lastPrice": 10.0, "tradeTime": _QUOTE_TT},
        "extended": {"tradeTime": _EXT_TT},
        "regular": {"regularMarketTradeTime": _REG_TT_MS, "regularMarketLastPrice": 9.0},
    })
    ident = server._rest_last_price_identity("BINDQ", parsed)
    assert parsed["last_price_session"] == "quote"
    assert parsed["trade_time"] == _QUOTE_TT
    assert ident["last_price_ok"] is True
    assert ident["last_price_native_ts"] == _QUOTE_TT
    assert ident["spot"] == 10.0


def test_extended_last_price_binds_only_extended_trade_time() -> None:
    parsed = server._parse_quote_node_session_fields({
        "quote": {"tradeTime": _QUOTE_TT},
        "extended": {"lastPrice": 11.5, "tradeTime": _EXT_TT},
        "regular": {"regularMarketTradeTime": _REG_TT_MS},
    })
    ident = server._rest_last_price_identity("BINDE", parsed)
    assert parsed["last_price_session"] == "extended"
    assert parsed["trade_time"] == _EXT_TT
    assert ident["last_price_ok"] is True
    assert ident["last_price_native_ts"] == _EXT_TT
    assert ident["spot"] == 11.5


def test_quote_last_price_does_not_bind_extended_or_regular_trade_time() -> None:
    parsed = server._parse_quote_node_session_fields({
        "quote": {"lastPrice": 10.0},
        "extended": {"tradeTime": _EXT_TT},
        "regular": {"regularMarketTradeTime": _REG_TT_MS, "regularMarketLastPrice": 9.0},
    })
    ident = server._rest_last_price_identity("XBIND", parsed)
    assert parsed["spot"] == 10.0
    assert parsed["trade_time"] is None
    assert ident["last_price_ok"] is False
    assert ident["last_price_native_ts"] is None
    assert ident["spot"] is None


def test_extended_last_price_does_not_bind_quote_or_regular_trade_time() -> None:
    parsed = server._parse_quote_node_session_fields({
        "quote": {"tradeTime": _QUOTE_TT},
        "extended": {"lastPrice": 11.5},
        "regular": {"regularMarketTradeTime": _REG_TT_MS},
    })
    ident = server._rest_last_price_identity("XBINDE", parsed)
    assert parsed["last_price_session"] == "extended"
    assert parsed["trade_time"] is None
    assert ident["last_price_ok"] is False
    assert ident["spot"] is None


def test_regular_market_last_price_is_not_admitted_as_current_spot() -> None:
    parsed = server._parse_quote_node_session_fields({
        "regular": {
            "regularMarketLastPrice": 758.0,
            "regularMarketTradeTime": _REG_TT_MS,
        }
    })
    ident = server._rest_last_price_identity("REGONLY", parsed)
    assert parsed["regular_close"] == 758.0
    assert parsed["spot"] is None
    assert parsed["spot_source"] is None
    assert ident["last_price_ok"] is False
    assert ident["spot"] is None


def test_quote_time_cannot_timestamp_last_price() -> None:
    parsed = server._parse_quote_node_session_fields({
        "quote": {"lastPrice": 10.0, "quoteTime": 1_800_000_444.0},
    })
    ident = server._rest_last_price_identity("QTIME", parsed)
    assert parsed["quote_time"] == 1_800_000_444.0
    assert parsed["trade_time"] is None
    assert ident["last_price_ok"] is False
    assert ident["last_price_native_ts"] is None


def test_same_rest_last_price_observation_does_not_bump_generation_or_dispatch(monkeypatch) -> None:
    tk = "SAMEOBS"
    L._by_ticker.pop(tk, None)
    dispatched: list[str] = []
    monkeypatch.setattr(server, "_dispatch_spot_gamma_refresh", lambda t: dispatched.append(t))
    pq = server._parse_quote_node_session_fields({
        "quote": {"lastPrice": 42.25, "tradeTime": _QUOTE_TT, "bidPrice": 42.2, "askPrice": 42.3},
    })
    first = server._ingest_rest_last_price_observation(
        tk, pq, quote_ingestion="rest_watchlist_batch", extra={"chg_pct": 0.1}
    )
    second = server._ingest_rest_last_price_observation(
        tk, pq, quote_ingestion="rest_tier_a", extra={"chg_pct": 0.1}
    )
    try:
        assert first["last_price_generation"] == second["last_price_generation"]
        assert first["last_price_native_ts"] == second["last_price_native_ts"] == _QUOTE_TT
        assert dispatched == [tk]
    finally:
        L._by_ticker.pop(tk, None)


def test_watchlist_fast_quote_and_tier_a_share_one_rest_last_price_owner() -> None:
    import inspect

    identity = inspect.getsource(server._rest_last_price_identity)
    ingest = inspect.getsource(server._ingest_rest_last_price_observation)
    commit = inspect.getsource(server._commit_rest_last_price_row)
    build = inspect.getsource(server._build_rest_fast_quote_payload)
    record = inspect.getsource(server._record_rest_fast_quote_with_auth_fallback)
    tier = inspect.getsource(server._tier_a_live_state_dict)
    watch = inspect.getsource(server.api_watchlist_quotes)
    assert "quote.lastPrice binds only quote.tradeTime" in identity
    assert "_rest_last_price_identity" in ingest
    assert "_commit_rest_last_price_row" in ingest
    assert "_rest_last_price_identity" in build
    assert "_apply_rest_last_price_identity" in build
    assert "_commit_rest_last_price_row" in record
    assert record.count("_lmp.record_quote") == 0
    assert record.count("_dispatch_spot_gamma_refresh") == 0
    assert "_ingest_rest_last_price_observation" in tier
    assert "_ingest_rest_last_price_observation" in watch
    assert "_lmp.record_quote" not in watch
    assert "_dispatch_spot_gamma_refresh" not in watch
    assert "next_fast_generation" not in watch
    assert "next_fast_generation" not in tier
    assert "next_fast_generation" not in identity
    assert "commit_last_price_observation" in commit
    assert "_lmp.record_quote" not in commit
    assert "_dispatch_spot_gamma_refresh" not in commit


def test_stream_and_rest_share_one_plane_commit() -> None:
    import inspect

    stream = inspect.getsource(L.record_from_level_one_equity)
    rest = inspect.getsource(server._commit_rest_last_price_row)
    commit = inspect.getsource(L.commit_last_price_observation)
    assert "commit_last_price_observation" in stream
    assert "LastPriceObservation" in stream
    assert "commit_last_price_observation" in rest
    assert "LastPriceObservation" in rest
    assert "next_fast_generation" not in stream
    assert "notify_quote_updated" not in stream
    assert "next_fast_generation" in commit
    assert "notify_quote_updated" in commit
    assert "_on_last_price_committed" in commit
