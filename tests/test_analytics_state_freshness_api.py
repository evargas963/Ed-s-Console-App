"""S2A/S2B — Tier C /api/analytics/state card_freshness_v1 + operator mirror contract tests."""

from __future__ import annotations

import json
import time
from copy import deepcopy

import pytest

_CARD_FRESHNESS_V1_REQUIRED_KEYS = frozenset(
    {
        "card_trust_state",
        "card_actionable",
        "analytics_age_sec",
        "quote_age_sec",
        "bundle_age_sec",
        "analytics_ttl_sec",
        "quote_stale_sec",
        "bundle_trust_sec",
        "fallback_status",
        "carry_forward_status",
        "source_freshness",
        "stale_reason_codes",
        "quote_ts",
        "bundle_ts",
        "mhap_bundle_ts",
        "tier_c_cache_revalidated",
        "tier_c_cache_gate_ok",
        "analytics_stale",
        "analytics_generated_at",
        "analytics_refresh_in_progress",
        "quote_source_detail.carried_forward",
        "quote_source_detail.schwab_auth_degraded",
    }
)

_OPERATOR_MIRROR_KEYS = frozenset(
    {
        "operator_card_actionable",
        "operator_card_trust_state",
        "operator_stale_reason_codes",
        "operator_actionability_reason",
    }
)

_RAW_TRADE_FIELDS = (
    "final_tradeable",
    "call_signal",
    "call_state",
    "validation_passed",
    "analytics_stale",
)


def _mhap_four() -> list[dict]:
    return [{"horizon": h, "call": {"dir": "flat"}} for h in ("1c", "5c", "15c", "60c")]


def _trusted_ms_dict(*, ticker: str = "ZZZ_CF1", bundle_ts: float | None = None) -> dict:
    now = time.time()
    ts = bundle_ts if bundle_ts is not None else now - 1.0
    return {
        "ticker": ticker,
        "selected_exp": "2099-12-01",
        "final_tradeable": True,
        "call_signal": "wait",
        "call_state": "WATCH",
        "validation_passed": True,
        "fusion_available": True,
        "mhap_rows": _mhap_four(),
        "_server_build_ts": ts,
        "spot": 500.0,
    }


@pytest.fixture()
def tier_c_cache_spy(monkeypatch):
    import server as srv

    monkeypatch.setattr(srv, "_schedule_analytics_recompute", lambda *a, **k: None)
    monkeypatch.setattr(srv, "_attach_db_contention_operator_surface", lambda md: None)
    monkeypatch.setattr(srv, "_touch_tracked_ticker_view", lambda *a, **k: None)
    try:
        import market_state as ms

        monkeypatch.setattr(ms, "attach_operator_visible_field_lineage", lambda md: None)
    except ImportError:
        pass
    keys_before = set(srv._state_cache.keys())
    yield srv
    for key in list(srv._state_cache.keys()):
        if key not in keys_before:
            srv._state_cache.pop(key, None)


def _seed_cache(srv, ticker: str, expiry: str, ms_dict: dict, *, age_sec: float = 1.0) -> tuple:
    now = time.time()
    gen = now - age_sec
    key = (ticker, expiry)
    ms = dict(ms_dict)
    ms.setdefault("_server_build_ts", gen)
    srv._state_cache[key] = {
        "ms_dict": ms,
        "ts": gen,
        "generated_at": gen,
        "analytics_version": 2,
    }
    return key


def _response_body(resp) -> dict:
    return json.loads(resp.body)


def _operator_mirrors(body: dict) -> dict:
    return {k: body.get(k) for k in _OPERATOR_MIRROR_KEYS}


def _assert_operator_mirrors_nested(body: dict) -> None:
    block = body["card_freshness_v1"]
    assert body["operator_card_actionable"] is block["card_actionable"]
    assert body["operator_card_trust_state"] == block["card_trust_state"]
    assert body["operator_stale_reason_codes"] == block["stale_reason_codes"]
    if block["card_actionable"]:
        assert body["operator_actionability_reason"] is None
    else:
        assert body["operator_actionability_reason"] is not None


def test_operator_mirror_fields_present_on_analytics_state(tier_c_cache_spy):
    srv = tier_c_cache_spy
    ticker = "ZZZ_OP_PRESENT"
    expiry = "2099-12-10"
    _seed_cache(srv, ticker, expiry, _trusted_ms_dict(ticker=ticker), age_sec=1.0)
    body = _response_body(srv._tier_c_analytics_json_response(ticker, expiry, False, "test_s2b1"))
    assert _OPERATOR_MIRROR_KEYS <= set(body.keys())
    _assert_operator_mirrors_nested(body)


def test_operator_mirrors_equal_nested_card_freshness_v1(tier_c_cache_spy):
    srv = tier_c_cache_spy
    ticker = "ZZZ_OP_MIRROR"
    expiry = "2099-12-11"
    _seed_cache(srv, ticker, expiry, _trusted_ms_dict(ticker=ticker), age_sec=1.0)
    body = _response_body(srv._tier_c_analytics_json_response(ticker, expiry, False, "test_s2b1"))
    _assert_operator_mirrors_nested(body)


def test_operator_card_actionable_true_on_trusted_payload(tier_c_cache_spy, monkeypatch):
    srv = tier_c_cache_spy
    ticker = "ZZZ_OP_TRUE"
    expiry = "2099-12-12"
    now = time.time()
    _seed_cache(
        srv,
        ticker,
        expiry,
        _trusted_ms_dict(ticker=ticker, bundle_ts=now - 2.0),
        age_sec=1.0,
    )
    monkeypatch.setattr(
        srv._lmp,
        "get_quote",
        lambda t: {
            "fast_server_ts": now - 3.0,
            "quote_source_detail": {"carried_forward": False, "schwab_auth_degraded": False},
        },
    )
    body = _response_body(srv._tier_c_analytics_json_response(ticker, expiry, False, "test_s2b1"))
    assert body["operator_card_actionable"] is True
    assert body["operator_actionability_reason"] is None
    _assert_operator_mirrors_nested(body)


def test_operator_card_actionable_false_on_analytics_stale(tier_c_cache_spy):
    srv = tier_c_cache_spy
    ticker = "ZZZ_OP_ASTALE"
    expiry = "2099-12-13"
    md = _trusted_ms_dict(ticker=ticker)
    md["analytics_stale"] = True
    # Step 2 honest staleness: analytics_stale is recomputed from age — seed past the
    # missed-cycle grace window (TTL × ANALYTICS_STALE_GRACE_CYCLES), not one beat.
    _seed_cache(
        srv,
        ticker,
        expiry,
        md,
        age_sec=srv.CACHE_TTL * srv.ANALYTICS_STALE_GRACE_CYCLES + 2.0,
    )
    body = _response_body(srv._tier_c_analytics_json_response(ticker, expiry, False, "test_s2b1"))
    assert body["operator_card_actionable"] is False
    assert body["operator_actionability_reason"] is not None
    assert "analytics_stale" in body["operator_stale_reason_codes"]
    _assert_operator_mirrors_nested(body)


def test_operator_card_actionable_false_on_revalidate_quarantine(tier_c_cache_spy, monkeypatch):
    srv = tier_c_cache_spy
    ticker = "ZZZ_OP_RQ"
    expiry = "2099-12-14"
    now = time.time()
    md = _trusted_ms_dict(ticker=ticker, bundle_ts=now - 2.0)
    _seed_cache(srv, ticker, expiry, md, age_sec=1.0)
    monkeypatch.setattr(
        srv._lmp,
        "get_quote",
        lambda t: {
            "fast_server_ts": now - 1.0,
            "quote_source_detail": {"carried_forward": False, "schwab_auth_degraded": False},
        },
    )

    import trade_impacting_gate as tig

    def _quarantine(ms_dict, *, route, stale):
        out = dict(ms_dict)
        out["tier_c_cache_gate_ok"] = False
        return out

    monkeypatch.setattr(tig, "revalidate_cached_decision", _quarantine)
    body = _response_body(srv._tier_c_analytics_json_response(ticker, expiry, False, "test_s2b1"))
    assert body["operator_card_actionable"] is False
    assert "revalidate_quarantine" in body["operator_stale_reason_codes"]
    _assert_operator_mirrors_nested(body)


def test_operator_card_actionable_false_on_quote_newer_than_signal(tier_c_cache_spy, monkeypatch):
    srv = tier_c_cache_spy
    ticker = "ZZZ_OP_QN"
    expiry = "2099-12-15"
    now = time.time()
    _seed_cache(
        srv,
        ticker,
        expiry,
        _trusted_ms_dict(ticker=ticker, bundle_ts=now - 120.0),
        age_sec=1.0,
    )
    monkeypatch.setattr(
        srv._lmp,
        "get_quote",
        lambda t: {"fast_server_ts": now - 5.0, "quote_source_detail": {"carried_forward": False}},
    )
    body = _response_body(srv._tier_c_analytics_json_response(ticker, expiry, False, "test_s2b1"))
    assert body["operator_card_actionable"] is False
    assert "quote_newer_than_signal" in body["operator_stale_reason_codes"]
    _assert_operator_mirrors_nested(body)


def test_operator_card_actionable_false_on_quote_carried_forward(tier_c_cache_spy, monkeypatch):
    srv = tier_c_cache_spy
    ticker = "ZZZ_OP_CFW"
    expiry = "2099-12-16"
    now = time.time()
    _seed_cache(srv, ticker, expiry, _trusted_ms_dict(ticker=ticker, bundle_ts=now - 2.0), age_sec=1.0)
    monkeypatch.setattr(
        srv._lmp,
        "get_quote",
        lambda t: {
            "fast_server_ts": now - 1.0,
            "quote_source_detail": {"carried_forward": True, "schwab_auth_degraded": False},
        },
    )
    body = _response_body(srv._tier_c_analytics_json_response(ticker, expiry, False, "test_s2b1"))
    assert body["operator_card_actionable"] is False
    assert "quote_carried_forward" in body["operator_stale_reason_codes"]
    _assert_operator_mirrors_nested(body)


def test_regression_raw_trade_fields_unchanged_via_tier_c_response(tier_c_cache_spy, monkeypatch):
    srv = tier_c_cache_spy
    ticker = "ZZZ_OP_RAW"
    expiry = "2099-12-17"
    now = time.time()
    md = {
        "ticker": ticker,
        "final_tradeable": True,
        "call_signal": "wait",
        "call_state": "WATCH",
        "validation_passed": True,
        "analytics_stale": False,
        "fusion_available": True,
        "mhap_rows": _mhap_four(),
        "_server_build_ts": now - 2.0,
    }
    expected_raw = {k: md[k] for k in _RAW_TRADE_FIELDS}
    _seed_cache(srv, ticker, expiry, md, age_sec=1.0)
    monkeypatch.setattr(
        srv._lmp,
        "get_quote",
        lambda t: {
            "fast_server_ts": now - 1.0,
            "quote_source_detail": {"carried_forward": False, "schwab_auth_degraded": False},
        },
    )
    body = _response_body(srv._tier_c_analytics_json_response(ticker, expiry, False, "test_s2b1"))
    for key in _RAW_TRADE_FIELDS:
        assert body[key] == expected_raw[key]
    assert _OPERATOR_MIRROR_KEYS <= set(body.keys())


def test_card_freshness_v1_block_present_on_analytics_state(tier_c_cache_spy):
    srv = tier_c_cache_spy
    ticker = "ZZZ_CF_PRESENT"
    expiry = "2099-12-01"
    _seed_cache(srv, ticker, expiry, _trusted_ms_dict(ticker=ticker), age_sec=1.0)
    resp = srv._tier_c_analytics_json_response(ticker, expiry, False, "test_s2a")
    body = _response_body(resp)
    block = body.get("card_freshness_v1")
    assert isinstance(block, dict)
    assert _CARD_FRESHNESS_V1_REQUIRED_KEYS <= set(block.keys())


def test_analytics_age_exceeded_reason_code(tier_c_cache_spy):
    srv = tier_c_cache_spy
    ticker = "ZZZ_CF_AGE"
    expiry = "2099-12-02"
    _seed_cache(
        srv,
        ticker,
        expiry,
        _trusted_ms_dict(ticker=ticker),
        age_sec=srv.CACHE_TTL + 10.0,
    )
    resp = srv._tier_c_analytics_json_response(ticker, expiry, False, "test_s2a")
    codes = _response_body(resp)["card_freshness_v1"]["stale_reason_codes"]
    assert "analytics_age_exceeded" in codes
    assert "analytics_stale" in codes


def test_tier_c_stale_cache_serve_reason_codes(tier_c_cache_spy):
    srv = tier_c_cache_spy
    ticker = "ZZZ_CF_STALE"
    expiry = "2099-12-03"
    _seed_cache(
        srv,
        ticker,
        expiry,
        _trusted_ms_dict(ticker=ticker),
        age_sec=srv.CACHE_TTL + 5.0,
    )
    resp = srv._tier_c_analytics_json_response(ticker, expiry, False, "test_s2a")
    block = _response_body(resp)["card_freshness_v1"]
    assert "tier_c_cache_stale_serve" in block["stale_reason_codes"]
    assert block["card_trust_state"] in ("STALE", "DEGRADED", "UNAVAILABLE")


def test_quote_carried_forward_reason_code(tier_c_cache_spy, monkeypatch):
    srv = tier_c_cache_spy
    ticker = "ZZZ_CF_CFW"
    expiry = "2099-12-04"
    now = time.time()
    _seed_cache(srv, ticker, expiry, _trusted_ms_dict(ticker=ticker, bundle_ts=now - 2.0), age_sec=1.0)

    def _carried_quote(t):
        return {
            "ticker": t,
            "spot": 501.0,
            "fast_server_ts": now - 1.0,
            "quote_source_detail": {
                "carried_forward": True,
                "schwab_auth_degraded": True,
            },
        }

    monkeypatch.setattr(srv._lmp, "get_quote", _carried_quote)
    resp = srv._tier_c_analytics_json_response(ticker, expiry, False, "test_s2a")
    block = _response_body(resp)["card_freshness_v1"]
    assert block["quote_source_detail.carried_forward"] is True
    assert "quote_carried_forward" in block["stale_reason_codes"]
    assert "auth_fallback" in block["stale_reason_codes"]
    assert block["card_actionable"] is False


def test_auth_degraded_reason_code(tier_c_cache_spy, monkeypatch):
    srv = tier_c_cache_spy
    ticker = "ZZZ_CF_AUTH"
    expiry = "2099-12-05"
    now = time.time()
    _seed_cache(srv, ticker, expiry, _trusted_ms_dict(ticker=ticker), age_sec=1.0)

    monkeypatch.setattr(
        srv._lmp,
        "get_quote",
        lambda t: {
            "fast_server_ts": now - 1.0,
            "quote_source_detail": {
                "carried_forward": False,
                "schwab_auth_degraded": True,
            },
        },
    )
    block = _response_body(
        srv._tier_c_analytics_json_response(ticker, expiry, False, "test_s2a")
    )["card_freshness_v1"]
    assert block["quote_source_detail.schwab_auth_degraded"] is True
    assert "auth_degraded" in block["stale_reason_codes"]


def test_quote_newer_than_signal_simulated(tier_c_cache_spy, monkeypatch):
    srv = tier_c_cache_spy
    ticker = "ZZZ_CF_QN"
    expiry = "2099-12-06"
    now = time.time()
    bundle_ts = now - 120.0
    quote_ts = now - 5.0
    _seed_cache(
        srv,
        ticker,
        expiry,
        _trusted_ms_dict(ticker=ticker, bundle_ts=bundle_ts),
        age_sec=1.0,
    )
    monkeypatch.setattr(
        srv._lmp,
        "get_quote",
        lambda t: {"fast_server_ts": quote_ts, "quote_source_detail": {"carried_forward": False}},
    )
    codes = _response_body(
        srv._tier_c_analytics_json_response(ticker, expiry, False, "test_s2a")
    )["card_freshness_v1"]["stale_reason_codes"]
    assert "quote_newer_than_signal" in codes
    assert "mhap_older_than_quote" in codes


def test_card_actionable_false_when_trust_withheld(tier_c_cache_spy):
    srv = tier_c_cache_spy
    ticker = "ZZZ_CF_NA"
    expiry = "2099-12-07"
    md = _trusted_ms_dict(ticker=ticker)
    md["analytics_stale"] = True
    _seed_cache(srv, ticker, expiry, md, age_sec=srv.CACHE_TTL + 2.0)
    block = _response_body(
        srv._tier_c_analytics_json_response(ticker, expiry, False, "test_s2a")
    )["card_freshness_v1"]
    assert block["card_actionable"] is False
    assert block["card_trust_state"] == "STALE"


def test_regression_existing_trade_fields_unchanged(tier_c_cache_spy):
    srv = tier_c_cache_spy
    now = time.time()
    md = {
        "ticker": "SPY",
        "final_tradeable": True,
        "call_signal": "wait",
        "call_state": "WATCH",
        "validation_passed": True,
        "analytics_stale": False,
        "analytics_age_sec": 1.0,
        "analytics_generated_at": "2026-01-01T00:00:00+00:00",
        "analytics_refresh_in_progress": False,
        "mhap_rows": _mhap_four(),
        "fusion_available": True,
        "_server_build_ts": now - 2.0,
        "fast_server_ts": now - 1.0,
    }
    before = deepcopy(md)
    srv._attach_card_freshness_v1_block(
        md,
        ticker="SPY",
        now=now,
        analytics_ttl_sec=5.0,
        tier_c_cache_stale_serve=False,
        plane_quote={
            "fast_server_ts": now - 1.0,
            "quote_source_detail": {"carried_forward": False, "schwab_auth_degraded": False},
        },
    )
    for key, value in before.items():
        assert md[key] == value
    assert isinstance(md.get("card_freshness_v1"), dict)
