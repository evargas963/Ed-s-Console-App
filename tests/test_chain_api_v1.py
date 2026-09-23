"""OPTIONS_ORDER_FLOW_V1 — GET /api/chain, the contract-selection surface.

COMPLETE, live, single-expiry-scoped chain (round 2 completeness repair, 2026-08-30): a
fixed strike_count is NEVER proof of completeness. MEASURED live: SPY's near expiry at
strike_count=250 returned 388 contracts (194 strikes); the SAME expiry via schwab-py's
`strike_range=Options.StrikeRange.ALL` — a DIFFERENT vendor selection dimension, not a
wider count — returned 526 contracts (263 strikes): 69 real strikes strike_count=250
silently missed. `strike_range="ALL"` is independently confirmed to be the vendor's true
complete set by a saturation check (an unrelated strike_count=500 request on the same
expiry converged to the IDENTICAL strike set). This file's tests use the REAL committed
evidence of both: tests/fixtures/real_tsla_complete_chain_strike_range_all.json (236
contracts, 54 fractional-strike rows, captured live via strike_range=ALL, saturation-
verified) and tests/fixtures/real_spy_strike_count_vs_strike_range_all_evidence.json (the
smoking-gun proof that a bounded strike_count under-counts).

Every test here MUST mock the live-fetch entry points (get_client / _gated_safe_get_chain)
explicitly — never rely on real credentials happening to be absent in the test environment
to fall through to the stored-snapshot path. A prior version of this file only mocked
_latest_chain_and_spot and, once real Schwab credentials existed on disk in this worktree
(added for the live vendor probes behind these fixtures), the unmocked live path made a
REAL network call during collection and hung the test run — caught and fixed here, and the
same discipline is kept for every test added since.

Uses the REAL captured chain in tests/fixtures/real_spy_0dte_chain_with_poison.json for the
fallback-tier tests (unchanged from the prior round) — institutional_correctness's
no_synthetic_domain_fixtures_in_tests gate requires real chain data for this domain.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import calibration.complete_chain_capture as ccc_mod  # noqa: E402
import app.api.routes.chain
import stored_chain

_FIXTURES = Path(__file__).parent / "fixtures"

_SPY_POISON = json.loads(
    (_FIXTURES / "real_spy_0dte_chain_with_poison.json").read_text(encoding="utf-8")
)
_REAL_CONTRACTS = _SPY_POISON["chain"]
_REAL_SPOT = _SPY_POISON["spot"]
_REAL_EXPIRY = _REAL_CONTRACTS[0]["expirationDate"][:10]

_TSLA_COMPLETE = json.loads(
    (_FIXTURES / "real_tsla_complete_chain_strike_range_all.json").read_text(encoding="utf-8")
)
_TSLA_CONTRACTS = _TSLA_COMPLETE["chain"]
_TSLA_EXPIRY = _TSLA_COMPLETE["expiry"]
_TSLA_N_FRACTIONAL = _TSLA_COMPLETE["n_fractional_strikes"]

_SPY_VS_ALL = json.loads(
    (_FIXTURES / "real_spy_strike_count_vs_strike_range_all_evidence.json").read_text(encoding="utf-8")
)


def _no_live_client(monkeypatch, srv):
    """Force the live-fetch branch to fail immediately (simulating 'no Schwab client
    available') so a test can exercise the fallback path deterministically, without
    depending on whatever credentials happen to exist on disk in this environment."""
    def _raise(*a, **k):
        raise RuntimeError("no live Schwab client in this test")
    monkeypatch.setattr(srv, "get_client", _raise)


def _fake_db(monkeypatch, srv, tmp_path):
    """A real sqlite file, not a mock — persist_complete_chain_capture/
    latest_complete_chain_capture do real sqlite3 I/O, so this proves the actual round
    trip, not a stubbed one."""
    db_path = str(tmp_path / "test_ed_console.db")
    monkeypatch.setattr(srv, "get_db", lambda: SimpleNamespace(db_path=db_path))
    return db_path


class _FakeResp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def _chain_json_for(contracts):
    """Build a minimal Schwab-shaped callExpDateMap/putExpDateMap payload from a flat
    contract list, keyed the way flatten_chain_contracts expects to read it back."""
    out = {"callExpDateMap": {}, "putExpDateMap": {}}
    for c in contracts:
        side = "callExpDateMap" if c.get("putCall") == "CALL" else "putExpDateMap"
        exp_key = f"{c['expirationDate'][:10]}:1"
        strike_key = str(c["strikePrice"])
        out[side].setdefault(exp_key, {}).setdefault(strike_key, []).append(c)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Fallback tier (unchanged shape from round 1, still real-fixture-backed)
# ─────────────────────────────────────────────────────────────────────────────

# TEST_SYSTEM_REHAB_V2 final remediation: every TestClient call in this file below
# was replaced with a direct call to server.get_chain -- a plain sync handler with
# no auth/middleware/serialization-shaping dependency, monkeypatched through the
# exact same fixtures (_no_live_client/_fake_db/_gated_safe_get_chain/etc.) that
# apply identically whether reached via HTTP or a direct call. get_chain returns a
# JSONResponse in every branch, so each call site unwraps via json.loads(resp.body).

def test_chain_fails_closed_with_no_stored_chain(monkeypatch, tmp_path):
    import json

    import server as srv

    _no_live_client(monkeypatch, srv)
    _fake_db(monkeypatch, srv, tmp_path)
    monkeypatch.setattr(stored_chain, "_latest_chain_and_spot", lambda t: (None, None, None))
    body = json.loads(app.api.routes.chain.get_chain(ticker="ZZZZ", expiry=None).body)
    assert body["ticker"] == "ZZZZ"
    assert body["contracts"] == []
    assert body["status"] == "no_chain"
    assert body["expiry"] is None
    assert body["scope"]["kind"] == "stored_analytical_snapshot_fallback"


def test_chain_falls_back_to_stored_contracts_verbatim_on_live_failure(monkeypatch, tmp_path):
    import json

    import server as srv

    _no_live_client(monkeypatch, srv)
    _fake_db(monkeypatch, srv, tmp_path)
    monkeypatch.setattr(stored_chain, "_latest_chain_and_spot",
                        lambda t: (_REAL_CONTRACTS, _REAL_SPOT, 1_700_000_000.0))
    body = json.loads(app.api.routes.chain.get_chain(ticker="SPY", expiry=None).body)
    assert body["contracts"] == _REAL_CONTRACTS   # byte-for-byte pass-through
    assert body["scope"]["kind"] == "stored_analytical_snapshot_fallback"


def test_chain_uppercases_and_strips_ticker(monkeypatch, tmp_path):
    import json

    import server as srv

    _no_live_client(monkeypatch, srv)
    _fake_db(monkeypatch, srv, tmp_path)
    seen = []

    def _spy(t):
        seen.append(t)
        return None, None, None
    monkeypatch.setattr(stored_chain, "_latest_chain_and_spot", _spy)
    body = json.loads(app.api.routes.chain.get_chain(ticker=" spy ", expiry=None).body)
    assert body["ticker"] == "SPY"
    assert seen == ["SPY"]


# ─────────────────────────────────────────────────────────────────────────────
# Complete-chain live path: strike_range="ALL", real TSLA fixture, fractional strikes
# ─────────────────────────────────────────────────────────────────────────────

def _fake_gated_isolating_ALL(c_json, calls):
    """Filters out the running app's own concurrent background chain-fetch traffic
    (terrain/analytics bg workers also call _gated_safe_get_chain once TestClient boots
    the real app) by only serving the real fixture to a strike_range='ALL' call — every
    other shape gets an empty chain, isolating THIS endpoint's own call deterministically."""
    def _fake_gated(client, ticker, *, strike_count=None, strike_range=None,
                    from_date=None, to_date=None, priority=False):
        calls.append(dict(ticker=ticker, strike_count=strike_count, strike_range=strike_range,
                          from_date=from_date, to_date=to_date, priority=priority))
        if strike_range == "ALL":
            return _FakeResp(200, c_json), 0.0, 0.1
        return _FakeResp(200, {"callExpDateMap": {}, "putExpDateMap": {}}), 0.0, 0.1
    return _fake_gated


def test_chain_live_fetch_uses_strike_range_all_never_a_bare_count(monkeypatch, tmp_path):
    """The completeness mechanism itself: the live call must use strike_range='ALL', not
    a strike_count bound — MEASURED live proof (fixtures) that a bound alone under-counts."""
    import json

    import server as srv

    monkeypatch.setattr(srv, "get_client", lambda: object())
    monkeypatch.setattr(srv, "_fetch_expiries_light", lambda t: [_TSLA_EXPIRY])
    _fake_db(monkeypatch, srv, tmp_path)
    c_json = _chain_json_for(_TSLA_CONTRACTS)
    c_json["underlying"] = {"last": _TSLA_COMPLETE.get("spot")}
    calls = []
    monkeypatch.setattr(srv, "_gated_safe_get_chain", _fake_gated_isolating_ALL(c_json, calls))
    body = json.loads(app.api.routes.chain.get_chain(ticker="TSLA", expiry=None).body)
    assert body["status"] == "ok"
    assert body["scope"]["kind"] == "complete_single_expiry"
    assert body["scope"]["completeness_basis"] == ccc_mod.COMPLETENESS_BASIS_STRIKE_RANGE_ALL
    assert len(body["contracts"]) == len(_TSLA_CONTRACTS)
    all_calls = [c for c in calls if c["strike_range"] == "ALL"]
    assert len(all_calls) >= 1
    assert all_calls[0]["strike_count"] is None, "strike_count must be OMITTED when strike_range=ALL is used, exactly as proven live"
    assert all_calls[0]["from_date"] == all_calls[0]["to_date"], "budget-safety: bounded to exactly one expiry"


def test_chain_fractional_strikes_survive_vendor_to_api_unchanged(monkeypatch, tmp_path):
    """VENDOR -> API set equivalence for the real TSLA capture: every native contract
    field, every fractional strike, survives byte-for-byte — no rounding, no coercion,
    no dropped rows."""
    import json

    import server as srv

    monkeypatch.setattr(srv, "get_client", lambda: object())
    monkeypatch.setattr(srv, "_fetch_expiries_light", lambda t: [_TSLA_EXPIRY])
    _fake_db(monkeypatch, srv, tmp_path)
    c_json = _chain_json_for(_TSLA_CONTRACTS)
    c_json["underlying"] = {"last": _TSLA_COMPLETE.get("spot")}
    monkeypatch.setattr(srv, "_gated_safe_get_chain",
                        _fake_gated_isolating_ALL(c_json, []))
    body = json.loads(app.api.routes.chain.get_chain(ticker="TSLA", expiry=None).body)

    vendor_symbols = {c["symbol"] for c in _TSLA_CONTRACTS}
    api_symbols = {c["symbol"] for c in body["contracts"]}
    assert api_symbols == vendor_symbols, "exact contract-symbol set equality, vendor -> API"
    assert len(api_symbols) == len(_TSLA_CONTRACTS), "no duplicate symbols"

    api_frac = [c for c in body["contracts"] if c.get("strikePrice") is not None
               and c["strikePrice"] % 1 != 0]
    assert len(api_frac) == _TSLA_N_FRACTIONAL, "every real fractional-strike row survives"
    # Byte-for-byte: pick one real fractional contract and confirm every field is untouched.
    vendor_frac_symbol = next(c["symbol"] for c in _TSLA_CONTRACTS
                              if c["strikePrice"] % 1 != 0)
    vendor_row = next(c for c in _TSLA_CONTRACTS if c["symbol"] == vendor_frac_symbol)
    api_row = next(c for c in body["contracts"] if c["symbol"] == vendor_frac_symbol)
    assert api_row == vendor_row, "no rounding, no coercion, no field loss on a real fractional strike"


# ─────────────────────────────────────────────────────────────────────────────
# Streamed-volume overlay (independent review, 2026-09-13)
# ─────────────────────────────────────────────────────────────────────────────

def _tsla_contracts_with_target_quote_time(native_ts):
    """Deep-copy `_TSLA_CONTRACTS` with the target (first) contract's own `quoteTimeInLong`
    pinned to `native_ts` (seconds; converted to the vendor's epoch-ms convention).

    A FIFTH independent review (2026-09-13), REPRODUCED: overlay_streamed_contract_fields's
    ordering guard now keys off each CONTRACT's own native `quoteTimeInLong`, never a
    single shared REST-fetch instant (see that function's own fifth-review docstring
    finding) -- so a test that wants to exercise "is a streamed value newer/older than the
    REST baseline" must control THIS SPECIFIC contract's native quote time, not rely on
    the fixture's own real (and irrelevantly ~16-day-old) captured value, and never resort
    to an impossible future `ts_recv` to manufacture "newer" artificially. Returns
    (contracts, target_contract) so callers compare unrelated fields against the actual
    served base contract, not the unmodified fixture original."""
    contracts = [dict(c) for c in _TSLA_CONTRACTS]
    contracts[0]["quoteTimeInLong"] = native_ts * 1000.0
    return contracts, contracts[0]


def _push_streamed_volume(ofs_mod, target_symbol, underlying, streamed_volume, ts_recv):
    """Shared setup: make `target_symbol` the currently-desired contract and push a real
    TOTAL_VOLUME observation through push_level_one -> OrderFlowState with an EXPLICIT
    ts_recv, so ordering relative to a REST fetch's own timestamp is deterministic (no
    wall-clock races). Returns the (prior_contract, prior_contracts) to restore."""
    from app.options.order_flow.state import push_level_one
    prior_contract, prior_contracts = ofs_mod._active_option_contract, ofs_mod._active_option_contracts
    ofs_mod._active_option_contract = target_symbol
    ofs_mod._active_option_contracts = []
    push_level_one(target_symbol, {
        "key": target_symbol, "assetMainType": "OPTION", "UNDERLYING": underlying,
        "TOTAL_VOLUME": streamed_volume,
    }, ts_recv=ts_recv)
    return prior_contract, prior_contracts


def test_chain_overlays_streamed_volume_onto_the_rest_snapshot(monkeypatch, tmp_path):
    """Independent-review finding (2026-09-13), REPRODUCED then FIXED: a controlled test
    wrote a streamed TOTAL_VOLUME observation into SQLite, ran it through the REAL replay
    path (push_level_one -> OrderFlowState), confirmed the in-memory state correctly
    advanced, then hit the actual /api/chain route and got the REST-only volume back
    unchanged -- the streamed value never reached this response at all. This route now
    calls the SAME overlay faucet (_gamma_surface_contracts_with_stream_overlay ->
    overlay_streamed_contract_fields) refresh_gamma_surface_from_stream already uses for
    the terrain/gamma-surface path, so a genuinely fresher streamed volume overrides the
    REST snapshot's own value for the exact contract it belongs to -- and only that one.

    Uses the REAL TSLA fixture and the REAL push_level_one ingestion write (not a
    reimplementation of the merge/freshness logic), exactly like
    tests/test_streamed_greeks_hook_v1.py already does for the gamma-surface path.

    A FOURTH independent review (2026-09-13): the ordering fix below (newer_than_ts is now
    THIS fetch's own instant, not None) means a streamed observation must be newer than the
    REST baseline it would override to legitimately overlay.

    A FIFTH independent review (2026-09-13), REPRODUCED then repaired: this test used to
    push with an impossible future-dated `ts_recv` (`time.time() + 10`) purely to dodge the
    ordering guard. No future timestamp is needed: the target contract's own native
    `quoteTimeInLong` is pinned to a REALISTIC 20-second-stale value (an illiquid strike
    Schwab had not re-quoted recently, inside an otherwise-fresh chain response) via
    `_tsla_contracts_with_target_quote_time`, so a plain, real, present-moment push is
    already unambiguously newer than THIS contract's own last quote.
    """
    import json
    import time

    import app.options.order_flow.streaming as ofs
    import server as srv

    now = time.time()
    contracts, target = _tsla_contracts_with_target_quote_time(now - 20.0)
    target_symbol = target["symbol"]
    rest_volume = target["totalVolume"]
    streamed_volume = (rest_volume or 0) + 4321   # unambiguously different from the REST value
    assert streamed_volume != rest_volume

    prior_contract, prior_contracts = _push_streamed_volume(
        ofs, target_symbol, "TSLA", streamed_volume, now)
    try:
        monkeypatch.setattr(srv, "get_client", lambda: object())
        monkeypatch.setattr(srv, "_fetch_expiries_light", lambda t: [_TSLA_EXPIRY])
        _fake_db(monkeypatch, srv, tmp_path)
        c_json = _chain_json_for(contracts)
        c_json["underlying"] = {"last": _TSLA_COMPLETE.get("spot")}
        monkeypatch.setattr(srv, "_gated_safe_get_chain", _fake_gated_isolating_ALL(c_json, []))

        body = json.loads(app.api.routes.chain.get_chain(ticker="TSLA", expiry=None).body)
    finally:
        ofs._active_option_contract, ofs._active_option_contracts = prior_contract, prior_contracts
        from app.options.order_flow.state import clear_symbol
        clear_symbol(target_symbol)

    assert body["scope"]["kind"] == "complete_single_expiry"
    assert body["stream_overlay_contracts"] >= 1, "the response must disclose that a streamed field actually overlaid something"
    overlaid = next(c for c in body["contracts"] if c["symbol"] == target_symbol)
    assert overlaid["totalVolume"] == streamed_volume, (
        f"streamed volume ({streamed_volume}) never reached /api/chain -- "
        f"still serving the REST snapshot's own value ({overlaid['totalVolume']})"
    )
    # Every OTHER field on this exact contract, and every OTHER contract entirely, must be
    # untouched -- this is a sparse overlay of one field on one contract, never a second
    # exposure/formula path and never collateral change to unrelated rows.
    for k, v in target.items():
        if k == "totalVolume":
            continue
        assert overlaid[k] == v, f"unrelated field {k!r} was changed by the volume overlay"
    other_symbol = next(c["symbol"] for c in _TSLA_CONTRACTS if c["symbol"] != target_symbol)
    other_vendor = next(c for c in _TSLA_CONTRACTS if c["symbol"] == other_symbol)
    other_api = next(c for c in body["contracts"] if c["symbol"] == other_symbol)
    assert other_api == other_vendor, "a contract with no streamed data must be byte-for-byte untouched"


def test_chain_does_not_let_an_older_streamed_volume_replace_a_newer_rest_value(monkeypatch, tmp_path):
    """A FOURTH independent review (2026-09-13), REPRODUCED: `_gamma_surface_contracts_with_
    stream_overlay` was called from this route with `newer_than_ts=None`, disabling the
    ordering guard entirely -- a streamed TOTAL_VOLUME observed BEFORE this exact REST fetch
    (concretely reported: streamed 111/gamma .01, four seconds old, replacing a newer REST
    333/gamma .03) still overlaid onto the fresher REST snapshot, because only the absolute
    `max_staleness_sec` bound was checked, never "is this actually newer than the specific
    REST baseline it would replace." Fixed by capturing this fetch's own instant
    (`_rest_fetch_ts`) and passing it as `newer_than_ts`.

    A FIFTH independent review (2026-09-13), REPRODUCED: this test's original `time.time() -
    10` push was a TEST ESCAPE, not a proof -- at ~10 seconds old it is rejected by the
    PRE-EXISTING absolute `GAMMA_SURFACE_STREAM_STALENESS_SEC = 10.0` filter regardless of
    whether the ordering guard does anything at all (independently confirmed: the identical
    input produces the identical rejection against the pre-fix `445a464d` route). Repaired
    to isolate the ordering guard specifically: the target contract's own native
    `quoteTimeInLong` is pinned to "right now" (this REST response's own fresh quote for the
    contract), and the streamed push is only 1 second older than THAT -- comfortably inside
    the 10-second absolute-staleness window (so that filter alone would NOT reject it), yet
    still genuinely older than this contract's own REST-reported observation, so a rejection
    here can only be the ordering guard doing its job.
    """
    import json
    import time

    import app.options.order_flow.streaming as ofs
    import server as srv

    now = time.time()
    contracts, target = _tsla_contracts_with_target_quote_time(now)
    target_symbol = target["symbol"]
    rest_volume = target["totalVolume"]
    stale_streamed_volume = (rest_volume or 0) + 4321
    assert stale_streamed_volume != rest_volume

    prior_contract, prior_contracts = _push_streamed_volume(
        ofs, target_symbol, "TSLA", stale_streamed_volume, now - 1.0)
    try:
        monkeypatch.setattr(srv, "get_client", lambda: object())
        monkeypatch.setattr(srv, "_fetch_expiries_light", lambda t: [_TSLA_EXPIRY])
        _fake_db(monkeypatch, srv, tmp_path)
        c_json = _chain_json_for(contracts)
        c_json["underlying"] = {"last": _TSLA_COMPLETE.get("spot")}
        monkeypatch.setattr(srv, "_gated_safe_get_chain", _fake_gated_isolating_ALL(c_json, []))

        body = json.loads(app.api.routes.chain.get_chain(ticker="TSLA", expiry=None).body)
    finally:
        ofs._active_option_contract, ofs._active_option_contracts = prior_contract, prior_contracts
        from app.options.order_flow.state import clear_symbol
        clear_symbol(target_symbol)

    assert body["scope"]["kind"] == "complete_single_expiry"
    overlaid = next(c for c in body["contracts"] if c["symbol"] == target_symbol)
    assert overlaid["totalVolume"] == rest_volume, (
        f"a streamed volume OLDER than this fetch's own REST read ({stale_streamed_volume}) "
        f"incorrectly replaced the newer REST value ({rest_volume}) -- got {overlaid['totalVolume']}"
    )
    assert body["stream_overlay_contracts"] == 0, (
        "no contract should be counted as overlaid when the only streamed value available "
        "predates this fetch's own REST baseline"
    )


def test_chain_persists_the_pre_overlay_rest_capture_not_the_blended_response(monkeypatch, tmp_path):
    """A FOURTH independent review (2026-09-13), REPRODUCED: the persisted
    complete_chain_captures row is this route's own durable "proven-complete, live
    strike_range=ALL REST capture" record (see the module docstring's tier-1 definition) --
    but persist_complete_chain_capture was called with the OVERLAID contracts, silently
    blending a streamed field into a table whose whole contract is being a pure REST
    snapshot, with no per-field provenance or streamed-timestamp column to tell a later
    reader which value came from where. Fixed: the route persists the contracts exactly as
    the vendor returned them; the overlay applies only to the JSON response.

    A FIFTH independent review (2026-09-13): no impossible future `ts_recv` needed here --
    see `_tsla_contracts_with_target_quote_time`'s docstring for why a realistically-stale
    pinned native quote time makes a plain, present-moment push unambiguously newer.
    """
    import time

    import app.options.order_flow.streaming as ofs
    import server as srv
    from calibration.complete_chain_capture import latest_complete_chain_capture

    now = time.time()
    contracts, target = _tsla_contracts_with_target_quote_time(now - 20.0)
    target_symbol = target["symbol"]
    rest_volume = target["totalVolume"]
    streamed_volume = (rest_volume or 0) + 4321

    prior_contract, prior_contracts = _push_streamed_volume(
        ofs, target_symbol, "TSLA", streamed_volume, now)
    try:
        monkeypatch.setattr(srv, "get_client", lambda: object())
        monkeypatch.setattr(srv, "_fetch_expiries_light", lambda t: [_TSLA_EXPIRY])
        db_path = _fake_db(monkeypatch, srv, tmp_path)
        c_json = _chain_json_for(contracts)
        c_json["underlying"] = {"last": _TSLA_COMPLETE.get("spot")}
        monkeypatch.setattr(srv, "_gated_safe_get_chain", _fake_gated_isolating_ALL(c_json, []))

        app.api.routes.chain.get_chain(ticker="TSLA", expiry=None)
    finally:
        ofs._active_option_contract, ofs._active_option_contracts = prior_contract, prior_contracts
        from app.options.order_flow.state import clear_symbol
        clear_symbol(target_symbol)

    cap = latest_complete_chain_capture(db_path, "TSLA", _TSLA_EXPIRY)
    assert cap is not None
    persisted = next(c for c in cap["contracts"] if c["symbol"] == target_symbol)
    assert persisted["totalVolume"] == rest_volume, (
        f"the persisted capture must be the PURE REST value ({rest_volume}), not the "
        f"response's own streamed-overlaid value ({persisted['totalVolume']}) -- the "
        f"streamed overlay belongs to the response only, never to this durable REST record"
    )


def test_chain_streamed_overlay_reaches_the_route_over_real_http(monkeypatch, tmp_path):
    """V04 (test-quality review, 2026-09-13): every other test in this section calls
    server.get_chain directly. This one goes through the REAL FastAPI route registration
    and HTTP/JSON round trip (TestClient), so a break in the route's own wiring (path,
    Query() binding, response serialization) -- not just the handler body -- would be
    caught, closing the specific "real HTTP" gap named in the fourth independent review.

    A FIFTH independent review (2026-09-13): no impossible future `ts_recv` needed here --
    see `_tsla_contracts_with_target_quote_time`'s docstring for why a realistically-stale
    pinned native quote time makes a plain, present-moment push unambiguously newer.
    """
    import time

    import app.options.order_flow.streaming as ofs
    import server as srv
    from starlette.testclient import TestClient

    now = time.time()
    contracts, target = _tsla_contracts_with_target_quote_time(now - 20.0)
    target_symbol = target["symbol"]
    rest_volume = target["totalVolume"]
    streamed_volume = (rest_volume or 0) + 4321

    monkeypatch.setattr(srv, "get_client", lambda: object())
    monkeypatch.setattr(srv, "_fetch_expiries_light", lambda t: [_TSLA_EXPIRY])
    _fake_db(monkeypatch, srv, tmp_path)
    c_json = _chain_json_for(contracts)
    c_json["underlying"] = {"last": _TSLA_COMPLETE.get("spot")}
    monkeypatch.setattr(srv, "_gated_safe_get_chain", _fake_gated_isolating_ALL(c_json, []))

    prior_contract = prior_contracts = None
    try:
        # The app's OWN startup (background stream resubscribe, logger threads, etc.) must
        # run and settle BEFORE this test pushes its streamed observation and pins the
        # active contract -- entering that startup sequence can otherwise clear
        # _active_option_contract as "foreign" to whatever ticker context it initializes
        # with, wiping this test's own setup before the request ever fires.
        with TestClient(srv.app) as client:
            prior_contract, prior_contracts = _push_streamed_volume(
                ofs, target_symbol, "TSLA", streamed_volume, now)
            r = client.get("/api/chain", params={"ticker": "TSLA"})  # caps-ok: scanner false positive: HTTP GET via TestClient (path + query params), not a dict read with a default
    finally:
        if prior_contract is not None or prior_contracts is not None:
            ofs._active_option_contract, ofs._active_option_contracts = prior_contract, prior_contracts
        from app.options.order_flow.state import clear_symbol
        clear_symbol(target_symbol)

    assert r.status_code == 200
    body = r.json()
    assert body["scope"]["kind"] == "complete_single_expiry"
    overlaid = next(c for c in body["contracts"] if c["symbol"] == target_symbol)
    assert overlaid["totalVolume"] == streamed_volume, (
        "the streamed overlay must reach the client over the REAL HTTP route, "
        f"not just the handler called directly -- got {overlaid['totalVolume']}"
    )


def test_chain_overlay_does_not_let_one_fresh_field_borrow_another_fields_freshness(monkeypatch, tmp_path):
    """A FOURTH independent review (2026-09-13): "keep unrelated fields from borrowing
    another field's freshness." overlay_streamed_contract_fields already checks each of
    gamma/delta/open_interest/total_volume against ITS OWN ts_key independently (see
    math_exposure_core.py's per-field loop) -- proven here at the route level with a
    contract whose streamed GAMMA is fresh but whose streamed TOTAL_VOLUME is stale: gamma
    must overlay, volume must not, on the SAME contract, SAME response.

    A FIFTH independent review (2026-09-13): no impossible future `ts_recv` needed for the
    "fresh" push. The target contract's own native `quoteTimeInLong` is pinned to `now - 5`
    (this REST response's own contract quote, 5s stale) -- the stale volume push at
    `now - 8` is genuinely older than that baseline (and still comfortably inside the
    10-second absolute-staleness window, so that filter alone does not explain the
    rejection); the fresh gamma push at plain `now` is genuinely newer than that same
    baseline. Both pushes use real, already-elapsed wall-clock instants -- never a value
    that has not happened yet.
    """
    import time

    import app.options.order_flow.streaming as ofs
    import server as srv
    from app.options.order_flow.state import push_level_one, clear_symbol

    now = time.time()
    contracts, target = _tsla_contracts_with_target_quote_time(now - 5.0)
    target_symbol = target["symbol"]
    rest_volume = target["totalVolume"]
    rest_gamma = target["gamma"]
    fresh_gamma = round((rest_gamma or 0) + 0.05, 4)
    stale_volume = (rest_volume or 0) + 4321

    prior_contract, prior_contracts = ofs._active_option_contract, ofs._active_option_contracts
    ofs._active_option_contract = target_symbol
    ofs._active_option_contracts = []
    try:
        # One push with a volume timestamp OLDER than this contract's own native quote
        # time (now - 5)...
        push_level_one(target_symbol, {
            "key": target_symbol, "assetMainType": "OPTION", "UNDERLYING": "TSLA",
            "TOTAL_VOLUME": stale_volume,
        }, ts_recv=now - 8)
        # ...then a SECOND push adding a gamma NEWER than that same native quote time --
        # the two fields' own ts_recv values are genuinely independent, not a single shared
        # one, and neither is a future timestamp.
        push_level_one(target_symbol, {
            "key": target_symbol, "assetMainType": "OPTION", "UNDERLYING": "TSLA",
            "GAMMA": fresh_gamma,
        }, ts_recv=now)

        monkeypatch.setattr(srv, "get_client", lambda: object())
        monkeypatch.setattr(srv, "_fetch_expiries_light", lambda t: [_TSLA_EXPIRY])
        _fake_db(monkeypatch, srv, tmp_path)
        c_json = _chain_json_for(contracts)
        c_json["underlying"] = {"last": _TSLA_COMPLETE.get("spot")}
        monkeypatch.setattr(srv, "_gated_safe_get_chain", _fake_gated_isolating_ALL(c_json, []))

        import json
        body = json.loads(app.api.routes.chain.get_chain(ticker="TSLA", expiry=None).body)
    finally:
        ofs._active_option_contract, ofs._active_option_contracts = prior_contract, prior_contracts
        clear_symbol(target_symbol)

    overlaid = next(c for c in body["contracts"] if c["symbol"] == target_symbol)
    assert overlaid["gamma"] == fresh_gamma, "the genuinely fresh gamma must overlay"
    assert overlaid["totalVolume"] == rest_volume, (
        "the stale volume must NOT overlay just because gamma on the SAME contract did -- "
        f"got {overlaid['totalVolume']}, expected the REST value {rest_volume}"
    )
    for k, v in target.items():
        if k in ("totalVolume", "gamma"):
            continue
        assert overlaid[k] == v, f"unrelated field {k!r} was changed by the overlay"


def test_chain_live_fetch_persists_the_complete_capture(monkeypatch, tmp_path):
    """VENDOR -> PERSISTED set equivalence: a successful complete_single_expiry response
    durably writes the exact contract set to complete_chain_captures — proven by reading
    the REAL sqlite row back, not by asserting the persist function was merely called."""
    import server as srv
    from calibration.complete_chain_capture import latest_complete_chain_capture

    monkeypatch.setattr(srv, "get_client", lambda: object())
    monkeypatch.setattr(srv, "_fetch_expiries_light", lambda t: [_TSLA_EXPIRY])
    db_path = _fake_db(monkeypatch, srv, tmp_path)
    c_json = _chain_json_for(_TSLA_CONTRACTS)
    c_json["underlying"] = {"last": _TSLA_COMPLETE.get("spot")}
    monkeypatch.setattr(srv, "_gated_safe_get_chain",
                        _fake_gated_isolating_ALL(c_json, []))
    app.api.routes.chain.get_chain(ticker="TSLA", expiry=None)

    cap = latest_complete_chain_capture(db_path, "TSLA", _TSLA_EXPIRY)
    assert cap is not None, "the complete capture must be durably persisted, not merely served"
    assert cap["completeness_basis"] == ccc_mod.COMPLETENESS_BASIS_STRIKE_RANGE_ALL
    persisted_symbols = {c["symbol"] for c in cap["contracts"]}
    vendor_symbols = {c["symbol"] for c in _TSLA_CONTRACTS}
    assert persisted_symbols == vendor_symbols, "exact contract-symbol set equality, vendor -> PERSISTED"


def test_chain_persisted_capture_serves_as_fallback_when_live_fails(monkeypatch, tmp_path):
    """PERSISTED -> API set equivalence on the fallback path: a prior complete capture
    survives a live-fetch failure and is served with its staleness stated."""
    import json

    import server as srv
    from calibration.complete_chain_capture import persist_complete_chain_capture

    db_path = _fake_db(monkeypatch, srv, tmp_path)
    persist_complete_chain_capture(
        db_path, ticker="TSLA", expiry=_TSLA_EXPIRY, contracts=_TSLA_CONTRACTS,
        spot=_TSLA_COMPLETE.get("spot"), completeness_basis="strike_range=ALL",
        ts_utc=1000.0)

    monkeypatch.setattr(srv, "get_client", lambda: object())
    monkeypatch.setattr(srv, "_fetch_expiries_light", lambda t: [_TSLA_EXPIRY])

    def _boom(*a, **k):
        raise RuntimeError("simulated live-fetch outage")
    monkeypatch.setattr(srv, "_gated_safe_get_chain", _boom)
    body = json.loads(app.api.routes.chain.get_chain(ticker="TSLA", expiry=None).body)
    assert body["scope"]["kind"] == "persisted_complete_capture_fallback"
    assert body["scope"]["completeness_basis"] == "strike_range=ALL"
    assert body["scope"]["captured_age_sec"] is not None
    api_symbols = {c["symbol"] for c in body["contracts"]}
    vendor_symbols = {c["symbol"] for c in _TSLA_CONTRACTS}
    assert api_symbols == vendor_symbols, "exact contract-symbol set equality, PERSISTED -> API fallback"


def test_chain_expiry_mismatch_never_claims_complete_single_expiry(monkeypatch, tmp_path):
    """NEGATIVE CONTROL (item #4): requested expiry A, vendor response carries expiry B
    -> scope.kind must NOT be 'complete_single_expiry'. Real contracts, real drift
    (constructed from a real fixture contract with only its expirationDate altered — the
    field a scope check must react to, not a hand-built synthetic chain)."""
    import json

    import server as srv

    monkeypatch.setattr(srv, "get_client", lambda: object())
    monkeypatch.setattr(srv, "_fetch_expiries_light", lambda t: [_TSLA_EXPIRY])
    _fake_db(monkeypatch, srv, tmp_path)
    drifted = dict(_TSLA_CONTRACTS[0])
    drifted["expirationDate"] = "2099-01-01T00:00:00.000+00:00"
    c_json = _chain_json_for([drifted])
    c_json["underlying"] = {"last": _TSLA_COMPLETE.get("spot")}
    monkeypatch.setattr(srv, "_gated_safe_get_chain",
                        lambda *a, **k: (_FakeResp(200, c_json), 0.0, 0.1))
    body = json.loads(app.api.routes.chain.get_chain(ticker="TSLA", expiry=None).body)
    assert body["scope"]["kind"] != "complete_single_expiry"
    assert body["scope"]["kind"] == "expiry_scope_mismatch"
    assert body["scope"]["requested_expiry"] == _TSLA_EXPIRY
    assert body["scope"]["returned_expiries"] == ["2099-01-01"]
    # Real data, still served — never silently dropped — just not claimed complete.
    assert len(body["contracts"]) == 1
    assert body["status"] == "ok"


def test_chain_expiry_mismatch_does_not_persist_a_complete_capture(monkeypatch, tmp_path):
    """A mismatched response must never be banked as if it were a proven-complete
    capture for the REQUESTED expiry — the persisted table stays empty."""
    import server as srv
    from calibration.complete_chain_capture import latest_complete_chain_capture

    monkeypatch.setattr(srv, "get_client", lambda: object())
    monkeypatch.setattr(srv, "_fetch_expiries_light", lambda t: [_TSLA_EXPIRY])
    db_path = _fake_db(monkeypatch, srv, tmp_path)
    drifted = dict(_TSLA_CONTRACTS[0])
    drifted["expirationDate"] = "2099-01-01T00:00:00.000+00:00"
    c_json = _chain_json_for([drifted])
    c_json["underlying"] = {"last": _TSLA_COMPLETE.get("spot")}
    monkeypatch.setattr(srv, "_gated_safe_get_chain",
                        lambda *a, **k: (_FakeResp(200, c_json), 0.0, 0.1))
    app.api.routes.chain.get_chain(ticker="TSLA", expiry=None)
    assert latest_complete_chain_capture(db_path, "TSLA", _TSLA_EXPIRY) is None


def test_chain_live_fetch_accepts_explicit_expiry_param(monkeypatch, tmp_path):
    import json

    import server as srv

    monkeypatch.setattr(srv, "get_client", lambda: object())
    _fake_db(monkeypatch, srv, tmp_path)
    fetch_expiries_called = []
    monkeypatch.setattr(srv, "_fetch_expiries_light",
                        lambda t: fetch_expiries_called.append(t) or ["9999-01-01"])
    c_json = _chain_json_for(_TSLA_CONTRACTS)
    c_json["underlying"] = {"last": _TSLA_COMPLETE.get("spot")}
    monkeypatch.setattr(srv, "_gated_safe_get_chain",
                        lambda *a, **k: (_FakeResp(200, c_json), 0.0, 0.1))
    body = json.loads(app.api.routes.chain.get_chain(ticker="TSLA", expiry=_TSLA_EXPIRY).body)
    assert body["expiry"] == _TSLA_EXPIRY
    # An explicit expiry must skip the nearest-expiry lookup entirely.
    assert fetch_expiries_called == []


def test_chain_live_fetch_non_200_falls_back_to_stored_snapshot(monkeypatch, tmp_path):
    import json

    import server as srv

    monkeypatch.setattr(srv, "get_client", lambda: object())
    _fake_db(monkeypatch, srv, tmp_path)
    monkeypatch.setattr(srv, "_fetch_expiries_light", lambda t: [_REAL_EXPIRY])
    monkeypatch.setattr(srv, "_gated_safe_get_chain",
                        lambda *a, **k: (_FakeResp(502, {}), 0.0, 0.1))
    monkeypatch.setattr(stored_chain, "_latest_chain_and_spot",
                        lambda t: (_REAL_CONTRACTS, _REAL_SPOT, 1_700_000_000.0))
    body = json.loads(app.api.routes.chain.get_chain(ticker="SPY", expiry=None).body)
    assert body["scope"]["kind"] == "stored_analytical_snapshot_fallback"
    assert body["status"] == "ok"
    assert len(body["contracts"]) == 40


def test_chain_live_fetch_exception_falls_back_to_stored_snapshot(monkeypatch, tmp_path):
    import json

    import server as srv

    monkeypatch.setattr(srv, "get_client", lambda: object())
    _fake_db(monkeypatch, srv, tmp_path)
    monkeypatch.setattr(srv, "_fetch_expiries_light", lambda t: [_REAL_EXPIRY])

    def _boom(*a, **k):
        raise RuntimeError("simulated vendor error")
    monkeypatch.setattr(srv, "_gated_safe_get_chain", _boom)
    monkeypatch.setattr(stored_chain, "_latest_chain_and_spot",
                        lambda t: (_REAL_CONTRACTS, _REAL_SPOT, 1_700_000_000.0))
    body = json.loads(app.api.routes.chain.get_chain(ticker="SPY", expiry=None).body)
    assert body["scope"]["kind"] == "stored_analytical_snapshot_fallback"


def test_real_vendor_evidence_strike_count_alone_undercounts_spy():
    """Durable machine evidence (item #3): the smoking-gun proof, read directly from the
    committed fixture — strike_count=250 alone missed 69 real SPY strikes that
    strike_range=ALL correctly returned on the SAME live request. This test does not
    exercise the endpoint; it pins the evidence itself so a future edit cannot silently
    invalidate the claim the architecture comment in server.py depends on."""
    missed = _SPY_VS_ALL["strikes_missed_by_strike_count_250"]
    assert len(missed) == 69
    assert _SPY_VS_ALL["converged_all_vs_500"] is True
    all_n = _SPY_VS_ALL["strike_range_all"]["n_contracts"]
    count250_n = _SPY_VS_ALL["strike_count_250"]["n_contracts"]
    assert all_n > count250_n
