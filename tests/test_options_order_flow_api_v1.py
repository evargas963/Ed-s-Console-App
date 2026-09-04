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
    monkeypatch.setattr("order_flow_streaming.set_active_option_contract", _boom)
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
# PR214_FINAL_MERGE_BLOCKERS_V2 — Blocker 1A: CONTRACT-BOUND HEALTH.
# The route computed the book for the QUERIED contract but attached streaming
# diagnostics read from the GLOBALLY ACTIVE contract, so one response could carry
# `contract: A` beside a `streaming_healthy: true` belonging entirely to B. Health
# is now bound to the contract actually asked about and fails closed on mismatch;
# the truthful replayed book for A is still served (that is the existing API
# contract) -- only the LIVE HEALTH claim is refused.
# ─────────────────────────────────────────────────────────────────────────────

_QQQ_CONTRACT = "QQQ   260820C00450000"


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
    """Point the diagnostics at a real stream DB and write REAL open coverage epochs --
    producer-side subscription truth, exactly as the daemon records it after a confirmed
    vendor subscribe. Fresh heartbeat too, so identity/liveness is not the thing failing.
    Passing None for a service leaves it with no open epoch (not subscribed)."""
    import time as _t

    from stream_spine import CaptureWriter

    db = tmp_path / "producer_stream.db"
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    try:
        claim = {"LEVELONE_OPTIONS": None, "OPTIONS_BOOK": None}
        if l1:
            claim["LEVELONE_OPTIONS"] = w.open_coverage_epoch(
                ofs.ticker_storage_key(l1), "LEVELONE_OPTIONS", reason="active_contract_set")
        if book:
            claim["OPTIONS_BOOK"] = w.open_coverage_epoch(
                ofs.ticker_storage_key(book), "OPTIONS_BOOK", reason="active_contract_set")
        # A live daemon publishes WHICH epoch it currently claims alongside its heartbeat.
        # An open row on its own is history, not an assertion -- a failed durable close
        # leaves one open on a subscription already surrendered. Seeding the claim is what
        # makes this fixture a LIVE producer rather than a ledger that merely has rows.
        w.write_heartbeat(ts=_t.time(), claimed_coverage=claim)
    finally:
        w.close()
    monkeypatch.setattr(ofs, "STREAM_DB_DEFAULT", db)
    monkeypatch.delenv("STREAM_CAPTURE_DB_PATH", raising=False)
    return db


def _reset_option_plane(ofs):
    ofs._feed_running = False
    ofs._active_option_contract = None
    ofs._option_streaming_last_update_ts = None
    ofs._option_last_subscribe_completed_ts = None


def test_blocker1a_query_a_while_active_b_fails_closed():
    """REQUIRED 1: API A while active B -> mismatch fails closed."""
    import json

    import order_flow_streaming as ofs
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

    import order_flow_streaming as ofs
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

    import order_flow_streaming as ofs
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

    import order_flow_streaming as ofs
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


def test_ambiguous_open_ledger_fails_closed_not_newest_row_wins(monkeypatch, tmp_path):
    """PR214 defect 1F. A corrupted/hand-edited ledger with TWO open epochs on one option
    service must fail CLOSED, not silently resolve to the newer row.

    read_open_coverage_symbols previously used `ORDER BY id DESC LIMIT 1`, which answered
    "B" for an A-open/B-open pair purely because B had the larger id -- inventing a
    confident producer identity from a ledger that cannot support one, and greening
    health on it. Seeded here by direct SQL because the writer's service-wide uniqueness
    guard (1E) now makes this state unreachable through the normal path."""
    import json

    import order_flow_streaming as ofs
    import server as srv
    from stream_spine import CaptureWriter, read_open_coverage_symbols

    db = tmp_path / "ambiguous.db"
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    try:
        # Direct SQL: bypass the uniqueness guard to simulate a corrupted ledger.
        w._conn.execute(
            "INSERT INTO stream_coverage_epochs(symbol,service,started_ts,reason) "
            "VALUES(?,?,1.0,'seed'),(?,?,2.0,'seed'),(?,?,1.0,'seed')",
            (ofs.ticker_storage_key(_SPY_CONTRACT), "LEVELONE_OPTIONS",
             ofs.ticker_storage_key(_QQQ_CONTRACT), "LEVELONE_OPTIONS",   # newer id
             ofs.ticker_storage_key(_QQQ_CONTRACT), "OPTIONS_BOOK"))
        w._conn.commit()
        # A LIVE producer claiming all three forged rows: the ambiguity must be refused on
        # its own terms, not merely because the claim happens not to cover them.
        w.write_heartbeat(ts=__import__("time").time(),
                          claimed_coverage={"LEVELONE_OPTIONS": 2, "OPTIONS_BOOK": 3})
    finally:
        w.close()

    import sqlite3
    con = sqlite3.connect(db)
    try:
        got = read_open_coverage_symbols(
            con, ("LEVELONE_OPTIONS", "OPTIONS_BOOK"),
            stale_sec=ofs.STREAM_PRODUCER_HEARTBEAT_STALE_SEC)
    finally:
        con.close()
    assert got["LEVELONE_OPTIONS"] is None, (
        "two open symbols on one service is AMBIGUOUS -- it must not resolve to the "
        "newest row")
    assert got["OPTIONS_BOOK"] == ofs.ticker_storage_key(_QQQ_CONTRACT), (
        "the unambiguous service is still answered normally")

    monkeypatch.setattr(ofs, "STREAM_DB_DEFAULT", db)
    monkeypatch.delenv("STREAM_CAPTURE_DB_PATH", raising=False)
    _force_live_option_plane(ofs, _QQQ_CONTRACT)
    try:
        plane = json.loads(srv.api_order_flow_options_microstructure(
            contract=_QQQ_CONTRACT).body)["streaming_plane"]
        assert plane["producer_l1_contract"] is None
        assert plane["contract_match"] is False, (
            "contract_match must not become true from an ambiguous ledger")
        assert plane["streaming_healthy"] is False, (
            "health must not become true from an ambiguous ledger")
    finally:
        _reset_option_plane(ofs)


def test_gap1a_partial_producer_state_is_not_a_fully_healthy_plane(monkeypatch, tmp_path):
    """REQUIRED: partial producer state (L1=B, BOOK=A or absent) must NOT become a fully
    healthy B plane -- both option services are required for a full contract match."""
    import json

    import order_flow_streaming as ofs
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


def test_blocker1a_whole_plane_query_keeps_historical_unbound_answer():
    """No caller-specified subject -> contract_match is None (not fabricated), and the
    historical whole-plane answer is unchanged for existing callers."""
    import order_flow_streaming as ofs

    _force_live_option_plane(ofs, _QQQ_CONTRACT)
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

    import order_flow_streaming as ofs
    import server as srv

    _force_live_option_plane(ofs, _QQQ_CONTRACT)
    # Setter stubbed to a no-op FAILURE so the active contract stays on B while the
    # request asks for A -- exactly the unbound-acknowledgement shape.
    monkeypatch.setattr("order_flow_streaming.set_active_option_contract",
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

def test_gap2_delayed_older_command_cannot_overwrite_newer_desired_state(monkeypatch, tmp_path):
    """REQUIRED attack: command A generation N, command B generation N+1, execute B's
    write FIRST, then let the delayed A write proceed. Final server desired state and
    signal file must both be B, and A must report as superseded — not as the successful
    current authority."""
    import order_flow_streaming as ofs
    from stream_spine import read_active_option_contract_signal

    signal = tmp_path / "stream_active_option_contract.json"
    monkeypatch.setattr("stream_spine.ACTIVE_OPTION_CONTRACT_SIGNAL_DEFAULT", signal)
    monkeypatch.setattr(ofs, "write_active_option_contract_signal",
                        lambda c: __import__("stream_spine").write_active_option_contract_signal(
                            c, path=signal))
    ofs._active_option_contract = None
    try:
        gen_a = ofs.begin_option_contract_command()      # A admitted first...
        gen_b = ofs.begin_option_contract_command()      # ...B admitted second
        assert gen_b > gen_a

        # B's write completes FIRST (its thread-pool body finished sooner).
        assert ofs.set_active_option_contract(_QQQ_CONTRACT, command_generation=gen_b) is True
        assert ofs._active_option_contract == ofs.ticker_storage_key(_QQQ_CONTRACT)

        # Now the DELAYED A write resumes. It must be refused, not applied.
        with pytest.raises(ofs.StaleOptionCommandError) as exc:
            ofs.set_active_option_contract(_SPY_CONTRACT, command_generation=gen_a)
        assert "superseded" in str(exc.value)

        # FINAL desired state and the daemon-facing signal file are both B.
        assert ofs._active_option_contract == ofs.ticker_storage_key(_QQQ_CONTRACT)
        assert read_active_option_contract_signal(path=signal) == ofs.ticker_storage_key(_QQQ_CONTRACT)
    finally:
        ofs._active_option_contract = None


def test_gap2_superseded_command_endpoint_reports_conflict_not_success(monkeypatch, tmp_path):
    """The superseded command's HTTP response must not read as a successful subscription
    of its own contract — a client validating the ack must reject it."""
    import asyncio
    import json

    import order_flow_streaming as ofs
    import server as srv

    signal = tmp_path / "stream_active_option_contract.json"
    monkeypatch.setattr(ofs, "write_active_option_contract_signal",
                        lambda c: __import__("stream_spine").write_active_option_contract_signal(
                            c, path=signal))
    ofs._active_option_contract = None
    try:
        # A newer command has already been admitted and written B.
        gen_b = ofs.begin_option_contract_command()
        ofs.set_active_option_contract(_QQQ_CONTRACT, command_generation=gen_b)

        # A stale command body then runs: force its generation below the newest.
        monkeypatch.setattr(ofs, "begin_option_contract_command", lambda: 1)
        resp = asyncio.run(srv.post_streaming_active_option_contract(
            payload={"contract": _SPY_CONTRACT}))
        assert resp.status_code == 409
        body = json.loads(resp.body)
        assert body["ok"] is False and body["superseded"] is True
        assert ofs._active_option_contract == ofs.ticker_storage_key(_QQQ_CONTRACT), (
            "the superseded command must not have moved desired state")
    finally:
        ofs._active_option_contract = None


def test_gap2_a_command_with_no_generation_keeps_historical_behavior():
    """Internal/test callers that pass no generation are unaffected (single-caller
    assumption, encoded explicitly rather than silently)."""
    import order_flow_streaming as ofs

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
# ─────────────────────────────────────────────────────────────────────────────


def _surrendered_but_unclosed_db(tmp_path, monkeypatch, ofs, contract):
    """The exact durable state a FAILED close leaves behind, produced by driving the REAL
    daemon helpers — not hand-written rows. Returns (db, epoch ids still open)."""
    from stream_spine import CaptureWriter, CoverageWriteError
    import app.market_data.schwab.streaming.capture as d

    db = tmp_path / "surrendered.db"
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    try:
        epoch_state = {"l1": None, "book": None}
        for key, service in d.COVERAGE_CLAIM_SERVICES.items():
            d._open_coverage_epoch_tracked(w, epoch_state, key,
                                           ofs.ticker_storage_key(contract), service,
                                           reason="active_contract_set")
        open_ids = {k: epoch_state[k] for k in ("l1", "book")}

        def _failing(*a, **k):
            raise CoverageWriteError("durable-write failure during surrender")
        monkeypatch.setattr(w, "close_coverage_epoch", _failing)
        for key in ("l1", "book"):
            d._close_coverage_epoch_tracked(w, epoch_state, key, reason="stream_recycle",
                                            surrendered_ts=200.0)
        assert epoch_state["l1"] is None and epoch_state["book"] is None
    finally:
        w.close()
    monkeypatch.setattr(ofs, "STREAM_DB_DEFAULT", db)
    monkeypatch.delenv("STREAM_CAPTURE_DB_PATH", raising=False)
    return db, open_ids


def test_durable_truth_surrendered_epoch_is_never_producer_confirmation(tmp_path, monkeypatch):
    """A KNOWINGLY SURRENDERED epoch whose durable close failed must never confirm.

    The rows are still `ended_ts IS NULL` — that is the whole point. What must stop
    confirming them is that the live producer no longer CLAIMS those epoch ids."""
    import sqlite3

    import order_flow_streaming as ofs

    db, open_ids = _surrendered_but_unclosed_db(tmp_path, monkeypatch, ofs, _SPY_CONTRACT)

    con = sqlite3.connect(db)
    try:
        still_open = con.execute(
            "SELECT id, service FROM stream_coverage_epochs WHERE ended_ts IS NULL"
        ).fetchall()
    finally:
        con.close()
    assert len(still_open) == 2, (
        f"the attack requires the rows to REMAIN OPEN; got {still_open}")

    _reset_option_plane(ofs)
    _force_live_option_plane(ofs, _SPY_CONTRACT)
    plane = ofs.get_option_contract_streaming_diagnostics(for_contract=_SPY_CONTRACT)

    assert plane["producer_l1_contract"] is None, (
        f"a surrendered epoch was reported as producer identity: {plane}")
    assert plane["producer_book_contract"] is None
    assert plane["contract_match"] is not True, (
        "contract_match=true over a surrendered subscription is the false positive this "
        f"exists to prevent: {plane}")
    assert plane["streaming_healthy"] is False


def test_durable_truth_repeated_ticks_during_the_write_failure_stay_fail_closed(
        tmp_path, monkeypatch):
    """The failure was RE-ENTRANT, so one tick is not a sufficient proof. Every tick the
    daemon re-subscribes, is refused a durable epoch and unsubscribes again; producer
    identity must read UNKNOWN throughout rather than naming the contract."""
    import asyncio

    import order_flow_streaming as ofs
    import app.market_data.schwab.streaming.capture as d
    from stream_spine import CaptureWriter, CoverageWriteError

    db = tmp_path / "reentrant.db"
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    monkeypatch.setattr(ofs, "STREAM_DB_DEFAULT", db)
    monkeypatch.delenv("STREAM_CAPTURE_DB_PATH", raising=False)
    _reset_option_plane(ofs)
    _force_live_option_plane(ofs, _SPY_CONTRACT)

    calls = []

    class _V:
        async def sub(self, syms):
            calls.append("SUB")

        async def unsub(self, syms):
            calls.append("UNSUB")

    try:
        epoch_state = {"l1": None, "book": None}
        d._open_coverage_epoch_tracked(w, epoch_state, "l1",
                                       ofs.ticker_storage_key(_SPY_CONTRACT),
                                       "LEVELONE_OPTIONS", reason="active_contract_set")

        def _failing(*a, **k):
            raise CoverageWriteError("persistent durable-write failure")
        monkeypatch.setattr(w, "close_coverage_epoch", _failing)
        d._close_coverage_epoch_tracked(w, epoch_state, "l1", reason="stream_recycle",
                                        surrendered_ts=200.0)

        v = _V()
        held = None
        for tick in range(5):
            held = asyncio.run(d._reconcile_option_service(
                None, held, ofs.ticker_storage_key(_SPY_CONTRACT),
                subs_fn=v.sub, unsubs_fn=v.unsub, writer=w, epoch_state=epoch_state,
                epoch_key="l1", service_name="LEVELONE_OPTIONS"))
            reported = ofs.get_option_contract_streaming_diagnostics(
                for_contract=_SPY_CONTRACT)["producer_l1_contract"]
            assert reported is None, (
                f"tick {tick}: producer identity re-confirmed a surrendered epoch "
                f"({reported!r}) while the vendor held {held!r}")
    finally:
        w.close()
    assert calls, "the attack must actually have driven vendor operations"


def test_durable_truth_a_producer_that_cannot_write_goes_unknown_not_confirmed(
        tmp_path, monkeypatch):
    """The other direction. If the daemon cannot write AT ALL it also cannot republish its
    claim, so the claim it left behind still names the open epochs. Staleness of the
    heartbeat is what must make that unknown — otherwise the last claim stands forever."""
    import time as _t

    import order_flow_streaming as ofs
    from stream_spine import CaptureWriter

    db = tmp_path / "stale_producer.db"
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    try:
        l1 = w.open_coverage_epoch(ofs.ticker_storage_key(_SPY_CONTRACT),
                                   "LEVELONE_OPTIONS", reason="active_contract_set")
        book = w.open_coverage_epoch(ofs.ticker_storage_key(_SPY_CONTRACT),
                                     "OPTIONS_BOOK", reason="active_contract_set")
        # Its LAST heartbeat still claims both epochs; the daemon then stopped writing.
        w.write_heartbeat(ts=_t.time() - (ofs.STREAM_PRODUCER_HEARTBEAT_STALE_SEC + 5.0),
                          claimed_coverage={"LEVELONE_OPTIONS": l1, "OPTIONS_BOOK": book})
    finally:
        w.close()
    monkeypatch.setattr(ofs, "STREAM_DB_DEFAULT", db)
    monkeypatch.delenv("STREAM_CAPTURE_DB_PATH", raising=False)
    _reset_option_plane(ofs)
    _force_live_option_plane(ofs, _SPY_CONTRACT)

    plane = ofs.get_option_contract_streaming_diagnostics(for_contract=_SPY_CONTRACT)
    assert plane["producer_l1_contract"] is None, (
        f"a stale producer's standing claim was treated as confirmation: {plane}")
    assert plane["contract_match"] is not True


def test_durable_truth_recovery_still_records_the_original_surrender_timestamp(tmp_path,
                                                                               monkeypatch):
    """The new gate must not disturb the existing law: when persistence recovers, the
    deferred close records the instant coverage was SURRENDERED, not the repair time."""
    import sqlite3

    import order_flow_streaming as ofs
    import app.market_data.schwab.streaming.capture as d
    from stream_spine import CaptureWriter, CoverageWriteError

    db = tmp_path / "recover.db"
    w = CaptureWriter(db, batch_rows=1, batch_sec=10.0)
    try:
        epoch_state = {"l1": None, "book": None}
        d._open_coverage_epoch_tracked(w, epoch_state, "l1",
                                       ofs.ticker_storage_key(_SPY_CONTRACT),
                                       "LEVELONE_OPTIONS", reason="active_contract_set")
        real_close = w.close_coverage_epoch

        def _failing(*a, **k):
            raise CoverageWriteError("outage")
        monkeypatch.setattr(w, "close_coverage_epoch", _failing)
        d._close_coverage_epoch_tracked(w, epoch_state, "l1", reason="stream_recycle",
                                        surrendered_ts=200.0)
        monkeypatch.setattr(w, "close_coverage_epoch", real_close)
        d._retry_pending_epoch_closes(w, epoch_state, "l1", reason="retry_pending_close")
    finally:
        w.close()

    con = sqlite3.connect(db)
    try:
        ended = con.execute("SELECT ended_ts FROM stream_coverage_epochs").fetchone()[0]
    finally:
        con.close()
    assert ended == 200.0, (
        f"the repair must replay the ORIGINAL surrender instant, got {ended}")
