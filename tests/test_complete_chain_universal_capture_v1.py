"""OPTIONS_ORDER_FLOW_V1 round 4 (material-defect-lifecycle review) — the SYSTEMATIC
near-term complete-chain capture.

Round 3 built a PROVEN-complete strike_range=ALL fetch, but wired it only to the
operator-triggered GET /api/chain endpoint — an expiry only ever earned a proven-
complete record in `complete_chain_captures` if a human happened to click it in
/options. This closes that gap: `server._persist_universal_complete_chain` rides the
SAME once-daily universal-capture window every other ticker's wide fetch already uses,
iterates this ticker's near-term LISTED expiries (the same MAX_DTE_DAYS horizon
`option_chain_morning_full` already uses), and fetches+persists each one through the
existing single-expiry strike_range=ALL faucet.

Uses REAL vendor-captured contracts from two distinct real expiries — TSLA's
2026-08-31 capture (tests/fixtures/real_tsla_complete_chain_strike_range_all.json) and
SPY's 2026-07-17 0DTE capture (tests/fixtures/real_spy_0dte_chain_with_poison.json) —
combined only as TEST HARNESS INPUT (both are unmodified real vendor rows; nothing here
invents a strike, greek, or OI value). institutional_correctness's
no_synthetic_domain_fixtures_in_tests gate requires real chain data for this domain.
"""

from __future__ import annotations

import copy
import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from calibration.complete_chain_capture import (
    eligible_near_term_expiries,
    has_complete_chain_capture_today,
    persist_complete_chain_capture,
)
from tests.test_chain_api_v1 import _chain_json_for, _FakeResp

_FIXTURES = Path(__file__).parent / "fixtures"

_TSLA = json.loads(
    (_FIXTURES / "real_tsla_complete_chain_strike_range_all.json").read_text(encoding="utf-8")
)
_TSLA_CONTRACTS = _TSLA["chain"]
_TSLA_EXPIRY = _TSLA["expiry"]  # 2026-08-31, real

_SPY_POISON = json.loads(
    (_FIXTURES / "real_spy_0dte_chain_with_poison.json").read_text(encoding="utf-8")
)
_SPY_CONTRACTS = _SPY_POISON["chain"]
_SPY_EXPIRY = _SPY_CONTRACTS[0]["expirationDate"][:10]  # 2026-07-17, real


# ─────────────────────────────────────────────────────────────────────────────
# eligible_near_term_expiries — pure date-window logic, no contract data at all
# ─────────────────────────────────────────────────────────────────────────────

def test_eligible_expiries_keeps_the_declared_horizon_only():
    exps = {"2026-06-20", "2026-06-30", "2026-07-27", "2026-08-15", "2026-06-19"}
    kept = eligible_near_term_expiries(exps, max_dte_days=37.0, now_et_date="2026-06-20")
    # today (dte=0) and 37 days out are both boundary-inclusive; 38d out and any
    # already-past date are excluded.
    assert kept == ["2026-06-20", "2026-06-30", "2026-07-27"]


def test_eligible_expiries_sorted_and_deduped_and_tolerates_junk():
    exps = ["2026-07-01", "2026-06-25", "2026-06-25", "", None, "not-a-date"]
    kept = eligible_near_term_expiries(exps, max_dte_days=37.0, now_et_date="2026-06-20")
    assert kept == ["2026-06-25", "2026-07-01"]


# ─────────────────────────────────────────────────────────────────────────────
# has_complete_chain_capture_today — DB-backed idempotency, survives a restart
# ─────────────────────────────────────────────────────────────────────────────

def test_has_complete_capture_today_false_until_written_then_day_scoped(tmp_path):
    db = tmp_path / "cap.db"
    assert has_complete_chain_capture_today(db, "TSLA", _TSLA_EXPIRY, "2026-06-20") is False

    # ts_utc 12:00 ET on 2026-06-20 (well inside that ET calendar day either side of DST)
    from calibration.option_chain_morning_full import et_date_and_mins
    from time_et import ET
    from datetime import datetime, timezone
    ts = datetime(2026, 6, 20, 12, 0, tzinfo=ET).astimezone(timezone.utc).timestamp()
    assert et_date_and_mins(ts)[0] == "2026-06-20"

    persist_complete_chain_capture(
        db, ticker="TSLA", expiry=_TSLA_EXPIRY, contracts=_TSLA_CONTRACTS,
        spot=350.0, completeness_basis="strike_range=ALL", ts_utc=ts)

    assert has_complete_chain_capture_today(db, "TSLA", _TSLA_EXPIRY, "2026-06-20") is True
    assert has_complete_chain_capture_today(db, "TSLA", _TSLA_EXPIRY, "2026-06-21") is False, (
        "a capture from a prior ET day must not silently satisfy today's idempotency check"
    )
    assert has_complete_chain_capture_today(db, "TSLA", "2099-01-01", "2026-06-20") is False
    assert has_complete_chain_capture_today(db, "SPY", _TSLA_EXPIRY, "2026-06-20") is False


# ─────────────────────────────────────────────────────────────────────────────
# server._persist_universal_complete_chain — the systematic iteration itself
# ─────────────────────────────────────────────────────────────────────────────

def _fake_db(monkeypatch, srv, tmp_path):
    db_path = str(tmp_path / "test_ed_console.db")
    monkeypatch.setattr(srv, "get_db", lambda: SimpleNamespace(db_path=db_path))
    return db_path


def _ts_utc_for_et_date(day_str: str) -> float:
    """A fixed, deterministic UTC timestamp at noon ET on `day_str` -- so the
    persisted row's own et_date and the caller's `et_date` argument are guaranteed to
    agree, independent of whatever the real wall clock reads when the test runs."""
    from datetime import datetime, timezone
    from time_et import ET
    y, m, d = (int(x) for x in day_str.split("-"))
    return datetime(y, m, d, 12, 0, tzinfo=ET).astimezone(timezone.utc).timestamp()


_TS_2026_06_20 = _ts_utc_for_et_date("2026-06-20")


def _wide_contracts_spanning_both_real_expiries():
    """The wide-fetch contracts list _terrain_refresh_one already has in hand this
    cycle -- real TSLA rows at their real 2026-08-31 expiry plus real SPY rows at
    their real 2026-07-17 expiry, combined only so ONE simulated ticker's wide fetch
    is shown to span two distinct real expiries."""
    return list(_TSLA_CONTRACTS) + list(_SPY_CONTRACTS)


def _gated_by_requested_expiry(monkeypatch, srv, calls):
    """Route each single-expiry strike_range=ALL request to whichever real fixture's
    expiry it asked for; anything else gets an empty chain, isolating the systematic
    call's own shape deterministically."""
    def _fake_gated(client, ticker, *, strike_count=None, strike_range=None,
                    from_date=None, to_date=None, priority=False):
        calls.append(dict(ticker=ticker, strike_count=strike_count, strike_range=strike_range,
                          from_date=from_date, to_date=to_date, priority=priority))
        req = str(to_date) if to_date else ""
        if strike_range == "ALL" and req == _TSLA_EXPIRY:
            return _FakeResp(200, _chain_json_for(_TSLA_CONTRACTS)), 0.0, 0.1
        if strike_range == "ALL" and req == _SPY_EXPIRY:
            return _FakeResp(200, _chain_json_for(_SPY_CONTRACTS)), 0.0, 0.1
        return _FakeResp(200, {"callExpDateMap": {}, "putExpDateMap": {}}), 0.0, 0.1
    monkeypatch.setattr(srv, "_gated_safe_get_chain", _fake_gated)


def test_universal_complete_chain_iterates_both_eligible_expiries_and_persists_each(
    monkeypatch, tmp_path
):
    import server as srv

    db_path = _fake_db(monkeypatch, srv, tmp_path)
    # Both real expiries (2026-07-17, 2026-08-31) are 45 days apart -- wider than the
    # declared 37-day near-term horizon can admit together. Widening the horizon for
    # THIS test only proves the ITERATION mechanism across >1 expiry; the horizon
    # boundary itself is proven separately and exactly above with plain date strings.
    monkeypatch.setattr(srv, "COMPLETE_CHAIN_NEAR_TERM_MAX_DTE_DAYS", 80.0)
    calls: list[dict] = []
    _gated_by_requested_expiry(monkeypatch, srv, calls)

    srv._persist_universal_complete_chain(
        "ZZTEST", client=object(), contracts=_wide_contracts_spanning_both_real_expiries(),
        et_date="2026-06-20")

    all_calls = [c for c in calls if c["strike_range"] == "ALL"]
    assert len(all_calls) == 2, "one strike_range=ALL fetch per eligible expiry, not a bulk multi-expiry request"
    for c in all_calls:
        assert c["strike_count"] is None, "never a bare strike_count bound for this capture"
        assert c["from_date"] == c["to_date"], "budget-safety: each fetch bounded to exactly one expiry"
        assert c["priority"] is False, "background systematic capture must never jump the priority queue"

    tsla_cap = srv.latest_complete_chain_capture(db_path, "ZZTEST", _TSLA_EXPIRY)
    spy_cap = srv.latest_complete_chain_capture(db_path, "ZZTEST", _SPY_EXPIRY)
    assert tsla_cap is not None and spy_cap is not None
    assert {c["symbol"] for c in tsla_cap["contracts"]} == {c["symbol"] for c in _TSLA_CONTRACTS}, (
        "exact vendor -> persisted contract-symbol set equality for expiry 1"
    )
    assert {c["symbol"] for c in spy_cap["contracts"]} == {c["symbol"] for c in _SPY_CONTRACTS}, (
        "exact vendor -> persisted contract-symbol set equality for expiry 2"
    )
    assert tsla_cap["completeness_basis"] == srv.COMPLETENESS_BASIS_STRIKE_RANGE_ALL
    assert spy_cap["completeness_basis"] == srv.COMPLETENESS_BASIS_STRIKE_RANGE_ALL


def test_universal_complete_chain_is_idempotent_within_the_same_et_day(monkeypatch, tmp_path):
    """Attack: a second call the same day must not re-fetch what is already proven
    complete for today -- vendor budget is not spent twice for the same fact."""
    import server as srv

    _fake_db(monkeypatch, srv, tmp_path)
    monkeypatch.setattr(srv, "COMPLETE_CHAIN_NEAR_TERM_MAX_DTE_DAYS", 80.0)
    calls: list[dict] = []
    _gated_by_requested_expiry(monkeypatch, srv, calls)

    contracts = _wide_contracts_spanning_both_real_expiries()
    srv._persist_universal_complete_chain(
        "ZZTEST", client=object(), contracts=contracts, et_date="2026-06-20",
        ts_utc=_TS_2026_06_20)
    assert len([c for c in calls if c["strike_range"] == "ALL"]) == 2

    srv._persist_universal_complete_chain(
        "ZZTEST", client=object(), contracts=contracts, et_date="2026-06-20",
        ts_utc=_TS_2026_06_20)
    assert len([c for c in calls if c["strike_range"] == "ALL"]) == 2, (
        "same-day re-entry must make zero additional vendor calls -- already proven complete today"
    )


def test_universal_complete_chain_one_expiry_failing_does_not_block_its_sibling(
    monkeypatch, tmp_path
):
    """Attack: one expiry's vendor fetch fails (non-200) -- the failure must not stop
    the sibling expiry from being attempted and persisted in the same cycle."""
    import server as srv

    db_path = _fake_db(monkeypatch, srv, tmp_path)
    monkeypatch.setattr(srv, "COMPLETE_CHAIN_NEAR_TERM_MAX_DTE_DAYS", 80.0)

    def _fake_gated(client, ticker, *, strike_count=None, strike_range=None,
                    from_date=None, to_date=None, priority=False):
        req = str(to_date) if to_date else ""
        if req == _TSLA_EXPIRY:
            return _FakeResp(502, {}), 0.0, 0.1  # vendor failure for expiry 1
        if req == _SPY_EXPIRY:
            return _FakeResp(200, _chain_json_for(_SPY_CONTRACTS)), 0.0, 0.1
        return _FakeResp(200, {"callExpDateMap": {}, "putExpDateMap": {}}), 0.0, 0.1
    monkeypatch.setattr(srv, "_gated_safe_get_chain", _fake_gated)

    srv._persist_universal_complete_chain(
        "ZZTEST", client=object(), contracts=_wide_contracts_spanning_both_real_expiries(),
        et_date="2026-06-20")

    assert srv.latest_complete_chain_capture(db_path, "ZZTEST", _TSLA_EXPIRY) is None, (
        "a failed fetch must never persist a partial/absent capture"
    )
    spy_cap = srv.latest_complete_chain_capture(db_path, "ZZTEST", _SPY_EXPIRY)
    assert spy_cap is not None, "the sibling expiry's fetch must still be attempted and persisted"


def test_universal_complete_chain_rejects_an_expiry_scope_mismatch(monkeypatch, tmp_path):
    """Attack: the vendor returns a different expiry than requested -- must not be
    persisted as a proven-complete capture for the REQUESTED expiry (mirrors the same
    honesty guard /api/chain already proves for the on-demand path)."""
    import server as srv

    db_path = _fake_db(monkeypatch, srv, tmp_path)
    monkeypatch.setattr(srv, "COMPLETE_CHAIN_NEAR_TERM_MAX_DTE_DAYS", 80.0)

    def _fake_gated(client, ticker, *, strike_count=None, strike_range=None,
                    from_date=None, to_date=None, priority=False):
        # Always answers with TSLA's real expiry, regardless of what was requested.
        return _FakeResp(200, _chain_json_for(_TSLA_CONTRACTS)), 0.0, 0.1
    monkeypatch.setattr(srv, "_gated_safe_get_chain", _fake_gated)

    srv._persist_universal_complete_chain(
        "ZZTEST", client=object(), contracts=_wide_contracts_spanning_both_real_expiries(),
        et_date="2026-06-20")

    assert srv.latest_complete_chain_capture(db_path, "ZZTEST", _SPY_EXPIRY) is None, (
        "vendor answering with the wrong expiry must never be banked as that expiry's proof"
    )


def test_universal_complete_chain_truncates_and_logs_beyond_the_per_cycle_cap(
    monkeypatch, tmp_path
):
    """Attack: an unusually weekly-heavy ticker must not unboundedly inflate one
    cycle's vendor cost -- only up to the declared per-cycle cap is fetched, and the
    truncation is logged, never silent."""
    import server as srv

    _fake_db(monkeypatch, srv, tmp_path)
    monkeypatch.setattr(srv, "COMPLETE_CHAIN_NEAR_TERM_MAX_DTE_DAYS", 400.0)
    cap = srv._COMPLETE_CAPTURE_MAX_EXPIRIES_PER_TICKER
    n_eligible = cap + 3
    # Real contract shape, mutated only on expirationDate -- one real TSLA row per
    # synthetic date, never a hand-built contract dict.
    template = _TSLA_CONTRACTS[0]
    wide_contracts = []
    for i in range(n_eligible):
        row = copy.deepcopy(template)
        d = date(2026, 6, 20 + i, ) if i < 10 else date(2026, 7, 20 + (i - 10))
        row["expirationDate"] = f"{d.isoformat()}T20:00:00.000+00:00"
        wide_contracts.append(row)

    calls: list[dict] = []

    def _fake_gated(client, ticker, *, strike_count=None, strike_range=None,
                    from_date=None, to_date=None, priority=False):
        calls.append({"to_date": to_date})
        return _FakeResp(200, {"callExpDateMap": {}, "putExpDateMap": {}}), 0.0, 0.1
    monkeypatch.setattr(srv, "_gated_safe_get_chain", _fake_gated)

    logged = []
    monkeypatch.setattr(srv.log, "warning", lambda msg, *a: logged.append(msg % a if a else msg))

    srv._persist_universal_complete_chain(
        "ZZTEST", client=object(), contracts=wide_contracts, et_date="2026-06-20")

    assert len(calls) == cap, f"must fetch at most the declared cap ({cap}), not all {n_eligible} eligible expiries"
    assert any("truncated" in m for m in logged), "truncation beyond the cap must be logged, never silent"
