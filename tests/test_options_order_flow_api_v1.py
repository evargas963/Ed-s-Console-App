"""OPTIONS_ORDER_FLOW_V1 — options order-flow API contract.

/api/order-flow/options-microstructure and /api/streaming/active-option-contract mirror
the EXISTING equity endpoints (/api/order-flow/microstructure,
/api/streaming/active-ticker) exactly — same delegation pattern, same producer
(order_flow_engine.compute_book_microstructure), just keyed by an option contract symbol
instead of a ticker.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_SPY_CONTRACT = "SPY   260820C00767000"


def test_options_microstructure_requires_contract_param():
    import server as srv
    from starlette.testclient import TestClient

    with TestClient(srv.app) as client:
        r = client.get("/api/order-flow/options-microstructure")
        assert r.status_code == 422   # FastAPI Query(...) required-param rejection


# TEST_SYSTEM_REHAB_V2_RESIDUAL_CLOSURE (TestClient adjudication): the six tests below
# were rewritten off TestClient onto direct handler calls. api_order_flow_options_
# microstructure and post_streaming_active_option_contract carry no auth, no middleware,
# no Request dependency and no response_model reshaping -- every status code they return
# is one the handler CONSTRUCTS ITSELF (JSONResponse(..., status_code=400/500)), so the
# HTTP round trip re-proved nothing. The one genuinely framework-owned behavior on this
# surface, FastAPI's Query(...) required-param -> 422, is still proven over real HTTP by
# test_options_microstructure_requires_contract_param above, which is deliberately KEPT.
# Both handlers return JSONResponse, hence json.loads(resp.body).

def test_options_microstructure_fails_closed_with_no_replayed_content(monkeypatch):
    import json

    import order_flow_live_state as ofls
    import server as srv

    ofls.clear_all_live_state()
    body = json.loads(srv.api_order_flow_options_microstructure(
        contract="QQQ   260820C00450000").body)
    assert body["contract"] == "QQQ   260820C00450000"
    assert body["status"] == "no_book"


def test_options_microstructure_serves_replayed_content(monkeypatch):
    """Not a synthetic shortcut: pushes the REAL captured OPTIONS_BOOK shape through
    order_flow_live_state.push_book (the same producer the daemon-plane feed calls), then
    proves the route serializes it via compute_book_microstructure."""
    import json

    import order_flow_live_state as ofls
    import server as srv

    ofls.clear_all_live_state()
    content = {"key": _SPY_CONTRACT, "BOOK_TIME": 1787234093764,
              "BIDS": [{"BID_PRICE": 1.28, "TOTAL_VOLUME": 1746}],
              "ASKS": [{"ASK_PRICE": 1.30, "TOTAL_VOLUME": 1533}]}
    ofls.push_book(_SPY_CONTRACT, content)

    body = json.loads(srv.api_order_flow_options_microstructure(contract=_SPY_CONTRACT).body)
    assert body["contract"] == _SPY_CONTRACT
    assert body["status"] == "ok"
    assert body["depth"]["1"]["imbalance"] is not None
    assert "streaming_plane" in body
    assert "streaming_healthy" in body["streaming_plane"]
    ofls.clear_all_live_state()


def test_options_microstructure_streaming_plane_reflects_real_diagnostics(monkeypatch):
    """The inlined streaming_plane block is NOT a stub — it must carry the real, live
    get_option_contract_streaming_diagnostics() state for the contract being served."""
    import json

    import order_flow_streaming as ofs
    import server as srv

    ofs._feed_running = True
    ofs._active_option_contract = _SPY_CONTRACT
    ofs._option_streaming_last_update_ts = None
    ofs._option_last_subscribe_completed_ts = None
    try:
        plane = json.loads(srv.api_order_flow_options_microstructure(
            contract=_SPY_CONTRACT).body)["streaming_plane"]
        assert plane["option_contract"] == _SPY_CONTRACT
        assert plane["streaming_connected"] is True
        assert plane["streaming_healthy"] is False   # no tick, no fresh subscribe grace
    finally:
        ofs._feed_running = False
        ofs._active_option_contract = None


def test_active_option_contract_post_requires_contract(monkeypatch):
    import asyncio
    import json

    import server as srv

    resp = asyncio.run(srv.post_streaming_active_option_contract(payload={}))
    assert resp.status_code == 400
    assert json.loads(resp.body)["ok"] is False


def test_active_option_contract_post_calls_the_real_setter(monkeypatch):
    import asyncio
    import json

    calls = []
    monkeypatch.setattr("order_flow_streaming.set_active_option_contract",
                        lambda c: calls.append(c) or True)
    import server as srv

    resp = asyncio.run(srv.post_streaming_active_option_contract(
        payload={"contract": _SPY_CONTRACT}))
    assert resp.status_code == 200
    body = json.loads(resp.body)
    assert body["ok"] is True and body["contract"] == _SPY_CONTRACT
    assert "streaming_healthy" in body
    assert calls == [_SPY_CONTRACT]


def test_active_option_contract_post_surfaces_setter_failure(monkeypatch):
    import asyncio
    import json

    def _boom(_c):
        raise RuntimeError("signal write failed")
    monkeypatch.setattr("order_flow_streaming.set_active_option_contract", _boom)
    import server as srv

    resp = asyncio.run(srv.post_streaming_active_option_contract(
        payload={"contract": _SPY_CONTRACT}))
    assert resp.status_code == 500
    assert json.loads(resp.body)["ok"] is False
