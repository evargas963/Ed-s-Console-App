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

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_SPY_CONTRACT = "SPY   260820C00767000"
_QQQ_CONTRACT = "QQQ   260820C00450000"


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

    import app.options.order_flow.state as ofls
    import server as srv

    ofls.clear_all_live_state()
    body = json.loads(srv.api_order_flow_options_microstructure(
        contract="QQQ   260820C00450000").body)
    assert body["contract"] == "QQQ   260820C00450000"
    assert body["status"] == "no_book"


def test_options_microstructure_serves_replayed_content(monkeypatch):
    """Not a synthetic shortcut: pushes the REAL captured OPTIONS_BOOK shape through
    app.options.order_flow.state.push_book (the same producer the daemon-plane feed calls), then
    proves the route serializes it via compute_book_microstructure."""
    import json

    import app.options.order_flow.state as ofls
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

    import app.options.order_flow.streaming as ofs
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
    monkeypatch.setattr("app.options.order_flow.streaming.set_active_option_contract",
                        lambda c, **kw: calls.append(c) or True)
    import server as srv

    resp = asyncio.run(srv.post_streaming_active_option_contract(
        payload={"contract": _SPY_CONTRACT}))
    assert resp.status_code == 200
    body = json.loads(resp.body)
    assert body["ok"] is True and body["contract"] == _SPY_CONTRACT
    assert "streaming_healthy" in body
    assert calls == [_SPY_CONTRACT]


def test_active_option_contract_post_surfaces_setter_failure(monkeypatch):
    """PR214 defect 3: this stub used to be `def _boom(_c)`, but production now calls
    `set_active_option_contract(c, command_generation=...)`. The stub therefore raised
    TypeError on the unexpected keyword BEFORE the intended RuntimeError could run, while
    the broad `500 / ok:false` assertions still passed -- a false-positive oracle that
    would have kept passing even if the real failure path were never reached.

    Fixed at the root: the stub accepts the real production call signature, a sentinel
    proves the intended failure actually executed, and the surfaced error text is pinned
    so a different exception cannot satisfy this test."""
    import asyncio
    import json

    invoked = {}

    def _boom(c, command_generation=None):
        invoked["contract"] = c
        invoked["generation"] = command_generation
        raise RuntimeError("signal write failed")
    monkeypatch.setattr("app.options.order_flow.streaming.set_active_option_contract", _boom)
    import server as srv

    resp = asyncio.run(srv.post_streaming_active_option_contract(
        payload={"contract": _SPY_CONTRACT}))
    assert resp.status_code == 500
    body = json.loads(resp.body)
    assert body["ok"] is False
    assert invoked.get("contract") == _SPY_CONTRACT, (
        "the intended setter failure must actually have been reached")
    assert isinstance(invoked.get("generation"), int), (
        "production must pass a real command_generation — a stub that cannot accept it "
        "would fail for the wrong reason")
    assert "signal write failed" in body.get("error", ""), (
        "the surfaced error must be THE intended failure, not an incidental TypeError")


# ─────────────────────────────────────────────────────────────────────────────
# RC-UI-3 — /api/streaming/active-option-contracts, the plural control surface. Since
# 2026-09-24 each view declares its OWN demand ({client_id, seq, contracts}) and the stream
# carries the union of every live view: one last-writer-wins slot let two views replace
# each other's set on every render, and the daemon swapped ~200 contracts on the shared
# Schwab socket every few seconds until the socket died (measured that day).
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def fresh_demand(monkeypatch):
    """No view demand, nothing held, no remembered rank; the setter records the union."""
    import app.options.order_flow.streaming as ofs
    monkeypatch.setattr(ofs, "_option_demand_by_client", {})
    held = {"now": []}
    calls: list = []

    def _setter(c):
        calls.append(list(c))
        held["now"] = list(c)
        return True
    monkeypatch.setattr(ofs, "set_active_option_contracts", _setter)
    monkeypatch.setattr(ofs, "get_active_option_contracts", lambda: held["now"])
    return calls


def _post(payload):
    import asyncio
    import json

    import server as srv
    resp = asyncio.run(srv.post_streaming_active_option_contracts(payload=payload))
    return resp.status_code, json.loads(resp.body)


def test_active_option_contracts_post_requires_a_view_id_and_seq(fresh_demand):
    from fastapi import HTTPException
    for bad in ({}, {"client_id": "", "seq": 1}, {"client_id": "v1"},
                {"client_id": "v1", "seq": "1"}, {"client_id": "v1", "seq": True}):
        with pytest.raises(HTTPException) as e:
            _post(bad)
        assert e.value.status_code == 400
    assert fresh_demand == [], "a malformed declaration never reaches the stream"


def test_active_option_contracts_post_confirms_this_views_demand(fresh_demand):
    status, body = _post({"client_id": "v1", "seq": 1,
                          "contracts": [_SPY_CONTRACT, _QQQ_CONTRACT]})
    assert status == 200 and body["ok"] is True
    assert body["client_id"] == "v1" and body["seq"] == 1
    # `requested` is what the view confirms against; `contracts` is what the stream holds
    assert body["requested"] == sorted([_SPY_CONTRACT, _QQQ_CONTRACT])
    assert sorted(body["contracts"]) == sorted([_SPY_CONTRACT, _QQQ_CONTRACT])
    assert body["requested_count"] == 2 and body["demand_views"] == 1
    assert fresh_demand == [sorted([_SPY_CONTRACT, _QQQ_CONTRACT])]


def test_two_views_never_replace_each_others_contracts(fresh_demand):
    """The defect: view B's declaration used to REPLACE view A's whole set."""
    _post({"client_id": "heatmap-tab", "seq": 1, "contracts": [_SPY_CONTRACT]})
    _post({"client_id": "ladder-tab", "seq": 1, "contracts": [_QQQ_CONTRACT]})
    assert fresh_demand[-1] == sorted([_SPY_CONTRACT, _QQQ_CONTRACT])
    # each view re-declaring its own unchanged set leaves the union unchanged
    _post({"client_id": "heatmap-tab", "seq": 2, "contracts": [_SPY_CONTRACT]})
    _post({"client_id": "ladder-tab", "seq": 2, "contracts": [_QQQ_CONTRACT]})
    assert all(c == sorted([_SPY_CONTRACT, _QQQ_CONTRACT]) for c in fresh_demand[1:])
    # a view releasing its demand removes only its own contracts
    _, body = _post({"client_id": "ladder-tab", "seq": 3, "contracts": []})
    assert fresh_demand[-1] == [_SPY_CONTRACT] and body["demand_views"] == 1


def test_a_views_older_declaration_cannot_overwrite_its_newer_one(fresh_demand):
    _post({"client_id": "v1", "seq": 5, "contracts": [_QQQ_CONTRACT]})
    status, body = _post({"client_id": "v1", "seq": 4, "contracts": [_SPY_CONTRACT]})
    assert status == 409 and body["ok"] is False and body["superseded"] is True
    assert fresh_demand == [[_QQQ_CONTRACT]], "the stale declaration never reached the stream"


def test_an_unrefreshed_views_lease_expires(fresh_demand):
    import app.options.order_flow.streaming as ofs
    ofs.declare_option_contract_demand("closed-tab", [_SPY_CONTRACT], seq=1, now=1000.0)
    ofs.declare_option_contract_demand("live-tab", [_QQQ_CONTRACT], seq=1,
                                       now=1000.0 + ofs.OPTION_DEMAND_LEASE_SEC - 1)
    assert fresh_demand[-1] == sorted([_SPY_CONTRACT, _QQQ_CONTRACT]), "still within the lease"
    out = ofs.declare_option_contract_demand("live-tab", [_QQQ_CONTRACT], seq=2,
                                             now=1000.0 + ofs.OPTION_DEMAND_LEASE_SEC + 1)
    assert fresh_demand[-1] == [_QQQ_CONTRACT] and out["demand_views"] == 1
    assert "closed-tab" not in ofs._option_demand_by_client


def test_active_option_contracts_post_surfaces_setter_failure(monkeypatch, fresh_demand):
    import app.options.order_flow.streaming as ofs

    def _boom(c):
        raise RuntimeError("signal write failed")
    monkeypatch.setattr(ofs, "set_active_option_contracts", _boom)
    status, body = _post({"client_id": "v1", "seq": 1, "contracts": [_SPY_CONTRACT]})
    assert status == 500 and body["ok"] is False
    assert "signal write failed" in body.get("error", "")


# ─────────────────────────────────────────────────────────────────────────────
# PR214_FINAL_MERGE_BLOCKERS_V2 — Blocker 1A: CONTRACT-BOUND HEALTH.
# The route computed the book for the QUERIED contract but attached streaming
# diagnostics read from the GLOBALLY ACTIVE contract, so one response could carry
# `contract: A` beside a `streaming_healthy: true` belonging entirely to B. Health
# is now bound to the contract actually asked about and fails closed on mismatch;
# the truthful replayed book for A is still served (that is the existing API
# contract) -- only the LIVE HEALTH claim is refused.
# ─────────────────────────────────────────────────────────────────────────────


def _force_live_option_plane(ofs, active_contract):
    """Make the plane maximally healthy on its own terms, so anything failing closed
    below is doing so on contract identity and nothing else. NOTE this sets only the
    SERVER-REQUESTED contract; producer identity is seeded separately by
    _seed_producer_epochs (PR214 premerge gap 1A -- requested state is not proof)."""
    import time as _t
    ofs._feed_running = True
    ofs._active_option_contract = ofs.ticker_storage_key(active_contract)
    ofs._option_streaming_last_update_ts = _t.time()
    ofs._option_last_subscribe_completed_ts = _t.time()


def _seed_producer_epochs(ofs, monkeypatch, tmp_path, *, l1=None, book=None):
    """A live daemon's status saying what Schwab holds: `l1` on LEVELONE_OPTIONS, `book` on
    OPTIONS_BOOK (None = not held). Producer truth arrives only this way now."""
    held = {"LEVELONE_OPTIONS": [ofs.ticker_storage_key(l1)] if l1 else [],
            "OPTIONS_BOOK": [ofs.ticker_storage_key(book)] if book else []}
    monkeypatch.setattr(ofs, "_daemon_status", None)
    ofs._note_daemon_status({"schwab_socket_open": True, "held": held, "health": {}})


def _seed_multi_contract_producer_epochs(ofs, monkeypatch, tmp_path, *,
                                         primary=None, primary_book=True, extra=None):
    """Multi-contract variant: `primary` held on LEVELONE_OPTIONS (+ OPTIONS_BOOK unless
    primary_book=False); every symbol in `extra` held on LEVELONE_OPTIONS only."""
    l1 = ([ofs.ticker_storage_key(primary)] if primary else []) +         [ofs.ticker_storage_key(s) for s in (extra or [])]
    book = [ofs.ticker_storage_key(primary)] if primary and primary_book else []
    monkeypatch.setattr(ofs, "_daemon_status", None)
    ofs._note_daemon_status({"schwab_socket_open": True, "health": {},
                             "held": {"LEVELONE_OPTIONS": l1, "OPTIONS_BOOK": book}})


def _reset_option_plane(ofs):
    ofs._feed_running = False
    ofs._active_option_contract = None
    ofs._active_option_contracts = []
    ofs._option_streaming_last_update_ts = None
    ofs._option_last_subscribe_completed_ts = None
    ofs._option_contract_last_update_ts = {}


# ─────────────────────────────────────────────────────────────────────────────
# RC-UI-3 (2026-09-12) — an ADDITIONAL (not primary) contract as a valid diagnostics
# subject. Independent-review finding, REPRODUCED: `requested_ok` only ever checked the
# primary slot, so a genuinely requested and producer-confirmed additional contract was
# rejected outright.
# ─────────────────────────────────────────────────────────────────────────────

def test_additional_contract_confirms_on_levelone_options_alone(monkeypatch, tmp_path):
    """QQQ is the primary (both services); SPY is additional-only, confirmed on
    LEVELONE_OPTIONS alone (book was never subscribed for it). Querying SPY must
    recognize it as requested AND confirmed, healthy end to end."""
    import json

    import app.options.order_flow.streaming as ofs
    import server as srv

    _force_live_option_plane(ofs, _QQQ_CONTRACT)
    ofs._active_option_contracts = [ofs.ticker_storage_key(_SPY_CONTRACT)]
    _seed_multi_contract_producer_epochs(
        ofs, monkeypatch, tmp_path, primary=_QQQ_CONTRACT, extra=[_SPY_CONTRACT])
    try:
        plane = json.loads(srv.api_order_flow_options_microstructure(
            contract=_SPY_CONTRACT).body)["streaming_plane"]
        assert plane["contract_match"] is True, (
            "an additional-only contract, confirmed on its one required service, must "
            f"read as matched: {plane}")
        assert plane["streaming_healthy"] is True
    finally:
        _reset_option_plane(ofs)


def test_additional_contract_not_yet_producer_confirmed_fails_closed(monkeypatch, tmp_path):
    """The mirror control: SPY is DESIRED as additional but the producer has not (yet)
    confirmed its LEVELONE_OPTIONS epoch -- must fail closed, not read matched merely
    because it is present in the desired set."""
    import json

    import app.options.order_flow.streaming as ofs
    import server as srv

    _force_live_option_plane(ofs, _QQQ_CONTRACT)
    ofs._active_option_contracts = [ofs.ticker_storage_key(_SPY_CONTRACT)]
    # Only QQQ (primary) is producer-confirmed; SPY has no open epoch at all.
    _seed_multi_contract_producer_epochs(ofs, monkeypatch, tmp_path, primary=_QQQ_CONTRACT)
    try:
        plane = json.loads(srv.api_order_flow_options_microstructure(
            contract=_SPY_CONTRACT).body)["streaming_plane"]
        assert plane["contract_match"] is False
        assert plane["streaming_healthy"] is False
    finally:
        _reset_option_plane(ofs)


def test_additional_contract_never_requires_options_book(monkeypatch, tmp_path):
    """Negative control on the OLD (still-primary-shaped) requirement: an additional
    contract that will NEVER have an OPTIONS_BOOK epoch (extras don't subscribe it) must
    still confirm as soon as LEVELONE_OPTIONS does -- proving `contract_match` for an
    extra does not silently fall back to requiring both services."""
    import json

    import app.options.order_flow.streaming as ofs
    import server as srv

    _force_live_option_plane(ofs, _QQQ_CONTRACT)
    ofs._active_option_contracts = [ofs.ticker_storage_key(_SPY_CONTRACT)]
    _seed_multi_contract_producer_epochs(
        ofs, monkeypatch, tmp_path, primary=_QQQ_CONTRACT, extra=[_SPY_CONTRACT])
    # Sanity: Schwab genuinely holds no OPTIONS_BOOK for SPY.
    assert ofs.ticker_storage_key(_SPY_CONTRACT) not in ofs.daemon_status()["held"]["OPTIONS_BOOK"]
    try:
        plane = json.loads(srv.api_order_flow_options_microstructure(
            contract=_SPY_CONTRACT).body)["streaming_plane"]
        assert plane["contract_match"] is True
    finally:
        _reset_option_plane(ofs)


def test_additional_only_contract_healthy_with_no_primary_at_all(monkeypatch, tmp_path):
    """Independent-review finding #4 (2026-09-12), REPRODUCED: _option_streaming_healthy()
    used to unconditionally require the PRIMARY slot (_active_option_contract) to be set
    -- `if not (_feed_running and _active_option_contract): return False` -- even when the
    caller queried a genuinely requested and producer-confirmed ADDITIONAL-only contract
    with NO primary requested at all. get_option_contract_streaming_diagnostics never
    overrode that False back to True on a real per-contract match (contract_match only
    ever forced healthy -> False on a mismatch). Reproduced exactly: no primary, SPY
    requested and producer-confirmed as an additional contract, SPY's own feed genuinely
    fresh -- must read healthy end to end."""
    import json
    import time as _t

    import app.options.order_flow.streaming as ofs
    import server as srv

    _reset_option_plane(ofs)
    ofs._feed_running = True
    ofs._active_option_contract = None                       # NO primary requested at all
    ofs._active_option_contracts = [ofs.ticker_storage_key(_SPY_CONTRACT)]
    ofs._option_contract_last_update_ts = {ofs.ticker_storage_key(_SPY_CONTRACT): _t.time()}
    _seed_multi_contract_producer_epochs(ofs, monkeypatch, tmp_path, extra=[_SPY_CONTRACT])
    try:
        plane = json.loads(srv.api_order_flow_options_microstructure(
            contract=_SPY_CONTRACT).body)["streaming_plane"]
        assert plane["contract_match"] is True
        assert plane["streaming_healthy"] is True, (
            f"an additional-only contract with no primary at all, requested and "
            f"producer-confirmed, with a genuinely fresh per-contract feed, must read "
            f"healthy: {plane}")
    finally:
        _reset_option_plane(ofs)


def test_per_contract_freshness_not_borrowed_between_primary_and_additional(monkeypatch, tmp_path):
    """Independent-review finding #4 (2026-09-12), second half ("inspect contract-
    specific freshness as well as membership"), REPRODUCED: `streaming_staleness_ms`/
    `streaming_healthy` used to read the ONE global `_option_streaming_last_update_ts`,
    which every contract's rows -- primary OR any additional one -- all bump together.
    Here QQQ (primary) has gone genuinely STALE on its OWN feed while SPY (additional)
    remains genuinely fresh, but the shared global clock was last touched by SPY's own
    recent tick. A query for QQQ must not borrow SPY's freshness through that shared
    clock -- it must read unhealthy on its own per-contract staleness, while SPY still
    correctly reads healthy."""
    import json
    import time as _t

    import app.options.order_flow.streaming as ofs
    import server as srv

    _reset_option_plane(ofs)
    ofs._feed_running = True
    ofs._active_option_contract = ofs.ticker_storage_key(_QQQ_CONTRACT)
    ofs._active_option_contracts = [ofs.ticker_storage_key(_SPY_CONTRACT)]
    # The shared global clock reads FRESH (SPY's own recent tick last touched it) --
    # the exact condition that used to let a stale primary borrow an additional
    # contract's freshness (or vice versa) before per-contract tracking existed.
    ofs._option_streaming_last_update_ts = _t.time()
    ofs._option_contract_last_update_ts = {
        ofs.ticker_storage_key(_QQQ_CONTRACT): _t.time() - 30.0,   # QQQ: genuinely stale
        ofs.ticker_storage_key(_SPY_CONTRACT): _t.time(),          # SPY: genuinely fresh
    }
    _seed_multi_contract_producer_epochs(
        ofs, monkeypatch, tmp_path, primary=_QQQ_CONTRACT, extra=[_SPY_CONTRACT])
    try:
        primary_plane = json.loads(srv.api_order_flow_options_microstructure(
            contract=_QQQ_CONTRACT).body)["streaming_plane"]
        assert primary_plane["contract_match"] is True    # requested + producer-confirmed
        assert primary_plane["streaming_healthy"] is False, (
            f"QQQ's own feed is 30s stale -- it must not read healthy by borrowing "
            f"SPY's fresher tick through a shared clock: {primary_plane}")
        assert primary_plane["streaming_staleness_ms"] >= 30_000.0

        extra_plane = json.loads(srv.api_order_flow_options_microstructure(
            contract=_SPY_CONTRACT).body)["streaming_plane"]
        assert extra_plane["contract_match"] is True
        assert extra_plane["streaming_healthy"] is True, (
            f"SPY's own feed is genuinely fresh; QQQ's staleness must not drag it down: "
            f"{extra_plane}")
        assert extra_plane["streaming_staleness_ms"] < 1000.0
    finally:
        _reset_option_plane(ofs)


def test_blocker1a_query_a_while_active_b_fails_closed():
    """REQUIRED 1: API A while active B -> mismatch fails closed."""
    import json

    import app.options.order_flow.streaming as ofs
    import server as srv

    _force_live_option_plane(ofs, _QQQ_CONTRACT)          # plane is bound to B
    try:
        body = json.loads(srv.api_order_flow_options_microstructure(
            contract=_SPY_CONTRACT).body)                  # ...but A is queried
        plane = body["streaming_plane"]
        assert body["contract"] == _SPY_CONTRACT, "payload must still identify A"
        assert plane["option_contract"] == ofs.ticker_storage_key(_QQQ_CONTRACT), (
            "the plane must truthfully report the contract it IS streaming (B)")
        assert plane["queried_contract"] == ofs.ticker_storage_key(_SPY_CONTRACT)
        assert plane["contract_match"] is False
        assert plane["streaming_healthy"] is False, (
            "B's health must never be reported as healthy for A")
    finally:
        _reset_option_plane(ofs)


def test_blocker1a_query_a_while_active_a_is_normal_health(monkeypatch, tmp_path):
    """REQUIRED 2: API A while active A -> normal health, no synthetic penalty.

    PR214 premerge gap 1A: this now requires PRODUCER confirmation too -- both option
    services must hold an open coverage epoch for A -- not merely that the server
    requested A."""
    import json

    import app.options.order_flow.streaming as ofs
    import server as srv

    _force_live_option_plane(ofs, _SPY_CONTRACT)
    _seed_producer_epochs(ofs, monkeypatch, tmp_path, l1=_SPY_CONTRACT, book=_SPY_CONTRACT)
    try:
        body = json.loads(srv.api_order_flow_options_microstructure(
            contract=_SPY_CONTRACT).body)
        plane = body["streaming_plane"]
        assert plane["server_requested_contract"] == ofs.ticker_storage_key(_SPY_CONTRACT)
        assert plane["producer_l1_contract"] == ofs.ticker_storage_key(_SPY_CONTRACT)
        assert plane["producer_book_contract"] == ofs.ticker_storage_key(_SPY_CONTRACT)
        assert plane["contract_match"] is True
        assert plane["streaming_healthy"] is True, (
            "a fully producer-confirmed, fresh plane must still read healthy")
    finally:
        _reset_option_plane(ofs)


def test_gap1a_requested_b_while_producer_still_a_is_not_confirmed(monkeypatch, tmp_path):
    """REQUIRED gap-1A attack: server requested B, producer/open epochs STILL A, query B.

    The signal file is DESIRED state; the open coverage epoch is PRODUCER state. During
    the window between the operator's request and the daemon's next poll they disagree,
    and binding health to requested state alone would green B while the producer is
    physically still subscribed to A."""
    import json

    import app.options.order_flow.streaming as ofs
    import server as srv

    _force_live_option_plane(ofs, _QQQ_CONTRACT)          # server REQUESTED B
    _seed_producer_epochs(ofs, monkeypatch, tmp_path,     # producer still holds A
                          l1=_SPY_CONTRACT, book=_SPY_CONTRACT)
    try:
        plane = json.loads(srv.api_order_flow_options_microstructure(
            contract=_QQQ_CONTRACT).body)["streaming_plane"]
        assert plane["server_requested_contract"] == ofs.ticker_storage_key(_QQQ_CONTRACT)
        assert plane["producer_l1_contract"] == ofs.ticker_storage_key(_SPY_CONTRACT)
        assert plane["producer_book_contract"] == ofs.ticker_storage_key(_SPY_CONTRACT)
        assert plane["contract_match"] is not True, (
            "queried == server-requested must NOT be sufficient while the producer "
            "still holds another contract")
        assert plane["streaming_healthy"] is False
    finally:
        _reset_option_plane(ofs)


def test_gap1a_producer_switches_to_b_then_identity_is_confirmed(monkeypatch, tmp_path):
    """...and once the producer's open epochs DO switch to B, identity is confirmed."""
    import json

    import app.options.order_flow.streaming as ofs
    import server as srv

    _force_live_option_plane(ofs, _QQQ_CONTRACT)
    _seed_producer_epochs(ofs, monkeypatch, tmp_path, l1=_QQQ_CONTRACT, book=_QQQ_CONTRACT)
    try:
        plane = json.loads(srv.api_order_flow_options_microstructure(
            contract=_QQQ_CONTRACT).body)["streaming_plane"]
        assert plane["contract_match"] is True
        assert plane["streaming_healthy"] is True
    finally:
        _reset_option_plane(ofs)


def test_gap1a_partial_producer_state_is_not_a_fully_healthy_plane(monkeypatch, tmp_path):
    """REQUIRED: partial producer state (L1=B, BOOK=A or absent) must NOT become a fully
    healthy B plane -- both option services are required for a full contract match."""
    import json

    import app.options.order_flow.streaming as ofs
    import server as srv

    for i, book_state in enumerate((_SPY_CONTRACT, None)):  # BOOK on the OLD contract, or absent
        # A fresh DB per case: reusing one would hit the 2B duplicate-open guard on the
        # second iteration (correctly), which is a different property than the one here.
        case_dir = tmp_path / f"case{i}"
        case_dir.mkdir()
        _force_live_option_plane(ofs, _QQQ_CONTRACT)
        _seed_producer_epochs(ofs, monkeypatch, case_dir,
                              l1=_QQQ_CONTRACT, book=book_state)
        try:
            plane = json.loads(srv.api_order_flow_options_microstructure(
                contract=_QQQ_CONTRACT).body)["streaming_plane"]
            assert plane["producer_l1_contract"] == ofs.ticker_storage_key(_QQQ_CONTRACT)
            assert plane["contract_match"] is False, (
                f"L1=B with BOOK={book_state!r} must not be a full contract match")
            assert plane["streaming_healthy"] is False
        finally:
            _reset_option_plane(ofs)


def test_blocker1a_whole_plane_query_keeps_historical_unbound_answer(monkeypatch, tmp_path):
    """No caller-specified subject -> contract_match is None (not fabricated), and the
    historical whole-plane answer is unchanged for existing callers."""
    import app.options.order_flow.streaming as ofs

    _force_live_option_plane(ofs, _QQQ_CONTRACT)
    _seed_producer_epochs(ofs, monkeypatch, tmp_path, l1=_QQQ_CONTRACT, book=_QQQ_CONTRACT)
    try:
        diag = ofs.get_option_contract_streaming_diagnostics()
        assert diag["contract_match"] is None
        assert diag["queried_contract"] is None
        assert diag["streaming_healthy"] is True
    finally:
        _reset_option_plane(ofs)


def test_blocker1a_post_ack_health_is_bound_to_the_requested_contract(monkeypatch):
    """The POST acknowledgement a client validates must itself be contract-bound, so a
    client cannot commit on a healthy-looking ack belonging to another contract."""
    import asyncio
    import json

    import app.options.order_flow.streaming as ofs
    import server as srv

    _force_live_option_plane(ofs, _QQQ_CONTRACT)
    # Setter stubbed to a no-op FAILURE so the active contract stays on B while the
    # request asks for A -- exactly the unbound-acknowledgement shape.
    monkeypatch.setattr("app.options.order_flow.streaming.set_active_option_contract",
                        lambda _c, **kw: False)
    try:
        resp = asyncio.run(srv.post_streaming_active_option_contract(
            payload={"contract": _SPY_CONTRACT}))
        body = json.loads(resp.body)
        assert body["contract"] == _SPY_CONTRACT
        assert body["contract_match"] is False
        assert body["streaming_healthy"] is False
    finally:
        _reset_option_plane(ofs)


# ─────────────────────────────────────────────────────────────────────────────
# PR214 premerge gap 2 — SERVER-SIDE A->B COMMAND RACE.
# The browser token stops a late A RESPONSE from repainting B. It cannot stop a late
# A WRITE from landing: an older A command, delayed before its setter commit, would
# otherwise overwrite the signal file and _active_option_contract back to A after the
# newer B already wrote — leaving the daemon subscribed to the contract the operator
# had already moved off. Ordering is now enforced at the writer itself.
# ─────────────────────────────────────────────────────────────────────────────


def test_gap2_a_command_with_no_generation_keeps_historical_behavior():
    """Internal/test callers that pass no generation are unaffected (single-caller
    assumption, encoded explicitly rather than silently)."""
    import app.options.order_flow.streaming as ofs

    ofs._active_option_contract = None
    try:
        assert ofs.set_active_option_contract(_SPY_CONTRACT) is True
        assert ofs._active_option_contract == ofs.ticker_storage_key(_SPY_CONTRACT)
    finally:
        ofs._active_option_contract = None


# ─────────────────────────────────────────────────────────────────────────────
# PR214 DURABLE PRODUCER TRUTH — an OPEN coverage row is history, not a claim.
#
# Reproduced at this seam before the fix: a durable CLOSE that fails leaves
# `ended_ts IS NULL` on an epoch the daemon has ALREADY KNOWINGLY SURRENDERED, the
# server read that row as producer identity and returned contract_match=true, and the
# shipped UI rendered the contract as "subscribed". It was re-entrant: every tick the
# daemon subscribed, was refused a durable epoch, and unsubscribed again, capturing
# nothing, while the ledger kept naming the contract.
