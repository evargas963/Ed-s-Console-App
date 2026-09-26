"""GET /api/chain: one expiry of the full chain the levels loop downloaded (strike_range=ALL),
every Schwab field as sent, with streamed option updates newer than a contract's own quote
overlaid. Tests put a real captured chain into the levels cache -- the store the route reads."""
from __future__ import annotations

import json
import time
from contextlib import contextmanager
from pathlib import Path

import app.options.order_flow.streaming as ofs
import server as srv
from app.options.order_flow.state import clear_symbol, push_level_one

_FIXTURES = Path(__file__).parent / "fixtures"
_TSLA = json.loads((_FIXTURES / "real_tsla_complete_chain_strike_range_all.json").read_text(encoding="utf-8"))
_TSLA_CONTRACTS = _TSLA["chain"]
_TSLA_EXPIRY = _TSLA["expiry"]
_SPY_VS_ALL = json.loads(
    (_FIXTURES / "real_spy_strike_count_vs_strike_range_all_evidence.json").read_text(encoding="utf-8"))


@contextmanager
def _held_chain(tk, contracts, fetched_ts, spot=None):
    """`contracts` as the chain the levels loop holds for `tk`."""
    with srv._terrain_cache_lock:
        prior = srv._terrain_cache.get(tk)
        srv._terrain_cache[tk] = {
            "_chain": contracts, "_chain_fetched_ts": fetched_ts, "spot": spot,
            "expiries": sorted({c["expirationDate"][:10] for c in contracts}),
            "computed_ts_utc": time.time(),
        }
    try:
        yield
    finally:
        with srv._terrain_cache_lock:
            if prior is None:
                srv._terrain_cache.pop(tk, None)
            else:
                srv._terrain_cache[tk] = prior


@contextmanager
def _streamed(symbol, fields_by_ts):
    """Stream `fields` for `symbol` at each ts, as the capture daemon's push would."""
    prior = ofs._active_option_contract, ofs._active_option_contracts
    ofs._active_option_contract, ofs._active_option_contracts = symbol, []
    try:
        for ts, fields in fields_by_ts:
            push_level_one(symbol, {"key": symbol, "assetMainType": "OPTION", "UNDERLYING": "TSLA",
                                    **fields}, ts_recv=ts)
        yield
    finally:
        ofs._active_option_contract, ofs._active_option_contracts = prior
        clear_symbol(symbol)


def _get(**kw):
    return json.loads(srv.get_chain(**{"expiry": None, **kw}).body)


def _with_quote_time(native_ts):
    contracts = [dict(c) for c in _TSLA_CONTRACTS]
    contracts[0]["quoteTimeInLong"] = native_ts * 1000.0
    return contracts, contracts[0]


def test_no_held_chain_is_unavailable_with_its_reason():
    body = _get(ticker="ZZNOCHAIN")
    assert body["status"] == "unavailable" and body["contracts"] == []
    assert body["scope"]["reason"]


def test_every_contract_of_the_expiry_is_served_exactly_as_schwab_sent_it():
    with _held_chain("TSLA", _TSLA_CONTRACTS, time.time(), spot=_TSLA.get("spot")):
        body = _get(ticker="tsla")
    assert body["status"] == "ok" and body["expiry"] == _TSLA_EXPIRY
    assert body["scope"]["kind"] == "complete_single_expiry"
    assert {c["symbol"] for c in body["contracts"]} == {c["symbol"] for c in _TSLA_CONTRACTS}
    fractional = [c for c in body["contracts"] if c["strikePrice"] != int(c["strikePrice"])]
    assert len(fractional) == _TSLA["n_fractional_strikes"]


def test_only_the_requested_expiry_is_served():
    later = [dict(c, expirationDate="2099-01-16T21:00:00.000+00:00") for c in _TSLA_CONTRACTS[:4]]
    with _held_chain("TSLA", _TSLA_CONTRACTS + later, time.time()):
        first = _get(ticker="TSLA")
        other = _get(ticker="TSLA", expiry="2099-01-16")
        missing = _get(ticker="TSLA", expiry="2031-01-17")
    assert first["expiry"] == _TSLA_EXPIRY and len(first["contracts"]) == len(_TSLA_CONTRACTS)
    assert len(other["contracts"]) == 4
    assert missing["status"] == "unavailable" and "2031-01-17" in missing["scope"]["reason"]


def test_a_streamed_volume_newer_than_the_contracts_quote_is_overlaid():
    now = time.time()
    contracts, target = _with_quote_time(now - 20.0)
    streamed = (target["totalVolume"] or 0) + 4321
    with _held_chain("TSLA", contracts, now - 20.0), \
            _streamed(target["symbol"], [(now, {"TOTAL_VOLUME": streamed})]):
        body = _get(ticker="TSLA")
    overlaid = next(c for c in body["contracts"] if c["symbol"] == target["symbol"])
    assert overlaid["totalVolume"] == streamed and body["stream_overlay_contracts"] >= 1
    assert all(overlaid[k] == v for k, v in target.items() if k != "totalVolume")
    other = next(c for c in _TSLA_CONTRACTS if c["symbol"] != target["symbol"])
    assert next(c for c in body["contracts"] if c["symbol"] == other["symbol"]) == other


def test_an_older_streamed_volume_never_replaces_the_chains_value():
    now = time.time()
    contracts, target = _with_quote_time(now)
    stale = (target["totalVolume"] or 0) + 4321
    with _held_chain("TSLA", contracts, now), \
            _streamed(target["symbol"], [(now - 1.0, {"TOTAL_VOLUME": stale})]):
        body = _get(ticker="TSLA")
    overlaid = next(c for c in body["contracts"] if c["symbol"] == target["symbol"])
    assert overlaid["totalVolume"] == target["totalVolume"] and body["stream_overlay_contracts"] == 0


def test_one_fresh_field_does_not_lend_its_freshness_to_another():
    now = time.time()
    contracts, target = _with_quote_time(now - 5.0)
    fresh_gamma = round((target["gamma"] or 0) + 0.05, 4)
    stale_volume = (target["totalVolume"] or 0) + 4321
    with _held_chain("TSLA", contracts, now - 5.0), _streamed(
            target["symbol"], [(now - 8, {"TOTAL_VOLUME": stale_volume}), (now, {"GAMMA": fresh_gamma})]):
        body = _get(ticker="TSLA")
    overlaid = next(c for c in body["contracts"] if c["symbol"] == target["symbol"])
    assert overlaid["gamma"] == fresh_gamma
    assert overlaid["totalVolume"] == target["totalVolume"]


def test_the_route_answers_over_real_http():
    from starlette.testclient import TestClient
    with TestClient(srv.app) as client, _held_chain("TSLA", _TSLA_CONTRACTS, time.time()):
        r = client.get("/api/chain", params={"ticker": "TSLA"})
    assert r.status_code == 200 and r.json()["expiry"] == _TSLA_EXPIRY


def test_real_vendor_evidence_strike_count_alone_undercounts_spy():
    """strike_count=250 missed 69 real SPY strikes that strike_range=ALL returned on the same
    request -- why the levels loop downloads strike_range=ALL."""
    assert len(_SPY_VS_ALL["strikes_missed_by_strike_count_250"]) == 69
    assert _SPY_VS_ALL["converged_all_vs_500"] is True
    assert _SPY_VS_ALL["strike_range_all"]["n_contracts"] > _SPY_VS_ALL["strike_count_250"]["n_contracts"]
