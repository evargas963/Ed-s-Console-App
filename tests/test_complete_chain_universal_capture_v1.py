"""OPTIONS_ORDER_FLOW_V1 round 4 (material-defect-lifecycle review) — the SYSTEMATIC
near-term complete-chain capture.

Round 3 built a PROVEN-complete strike_range=ALL fetch, but wired it only to the
operator-triggered GET /api/chain endpoint — an expiry only ever earned a proven-
complete record in `complete_chain_captures` if a human happened to click it in
/options. `server._persist_universal_complete_chain` closes that gap: it rides the
SAME once-daily universal-capture WINDOW every ticker's wide fetch already uses,
discovers this ticker's near-term LISTED expiries (the same MAX_DTE_DAYS horizon
`option_chain_morning_full` already uses) from the regular per-cycle chain fetch, and
iterates them through the existing single-expiry strike_range=ALL faucet.

OPERATOR-CAUGHT DEFECT (2026-08-31, same day as the round-4 landing): the first
version sliced `eligible[:CAP]` BEFORE filtering out already-captured expiries. Once
the first CAP were captured, every later cycle kept re-selecting that SAME first-CAP
slice (all already done, so the loop no-opped) — expiry #(CAP+1) and beyond were NEVER
attempted, on ANY cycle, ANY day: a bounded per-cycle vendor budget had silently become
a PERMANENT completeness ceiling. This also required decoupling the function from the
sibling `_persist_universal_capture`'s once-per-day "done" gate, since piggybacking on
it meant "successive cycles" never actually happened in production regardless of the
slice bug. Both are fixed here and both are proven not to regress.

Uses REAL vendor-captured contracts from two distinct real expiries — TSLA's
2026-08-31 capture (tests/fixtures/real_tsla_complete_chain_strike_range_all.json) and
SPY's 2026-07-17 0DTE capture (tests/fixtures/real_spy_0dte_chain_with_poison.json) —
combined only as TEST HARNESS INPUT (both are unmodified real vendor rows; nothing here
invents a strike, greek, or OI value), plus real-contract-shaped rows with only
`expirationDate` mutated at runtime (never an inline hand-built contract dict) where a
scenario needs more than two distinct expiries. institutional_correctness's
no_synthetic_domain_fixtures_in_tests gate requires real chain data for this domain.
"""

from __future__ import annotations

import copy
import json
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from calibration.complete_chain_capture import (
    eligible_near_term_expiries,
    has_complete_chain_capture_today,
    next_capture_batch,
    persist_complete_chain_capture,
)
from tests.conftest import most_recent_trading_day_et
from tests.test_chain_api_v1 import _chain_json_for, _FakeResp
from time_et import ET

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

# A real trading day (drawn from the actual calendar authority, never a hardcoded
# literal that could rot) at a fixed, deterministic minute INSIDE the systematic
# capture window (10:00-11:30 ET) every test in this file needs, now that the
# function self-gates on window + trading day.
_DAY = most_recent_trading_day_et(on_or_before=date(2026, 6, 22))
_DAY_STR = _DAY.isoformat()
_TS_IN_WINDOW = datetime(_DAY.year, _DAY.month, _DAY.day, 10, 15, tzinfo=ET).astimezone(
    timezone.utc
).timestamp()


def _ts_at(day: date, hour: int, minute: int) -> float:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=ET).astimezone(
        timezone.utc
    ).timestamp()


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
# next_capture_batch — the per-cycle work-selection policy in isolation, and the
# literal mutation control (G) proving the round-4 slice-order regression is caught
# ─────────────────────────────────────────────────────────────────────────────

def test_next_capture_batch_filters_before_slicing():
    eligible = [f"2026-06-{20 + i:02d}" for i in range(11)]  # 11 items, cap 8
    already_captured = set(eligible[:8])  # the first 8 already done
    batch = next_capture_batch(eligible, already_captured=already_captured, given_up=set(), batch_size=8)
    assert batch == eligible[8:], (
        "once the first 8 are captured, the batch must advance to the remaining 3 -- "
        "not re-select the already-done first 8"
    )


def test_next_capture_batch_skips_given_up_expiries():
    eligible = ["2026-06-20", "2026-06-21", "2026-06-22"]
    batch = next_capture_batch(
        eligible, already_captured=set(), given_up={"2026-06-20"}, batch_size=8)
    assert batch == ["2026-06-21", "2026-06-22"]


def test_next_capture_batch_mutation_control_slice_before_filter_would_stall(monkeypatch=None):
    """G — the round-4 regression, reproduced literally: slicing BEFORE filtering
    versus filtering BEFORE slicing (the real, shipped policy), on the exact scenario
    that exposed it. The broken ordering returns an EMPTY batch forever once the first
    `cap` are captured, even though 3 real expiries still need work -- this is the
    assertion that would fail if next_capture_batch ever regresses to the old order."""
    eligible = [f"2026-06-{20 + i:02d}" for i in range(11)]
    already_captured = set(eligible[:8])

    def _broken_slice_before_filter(eligible, already_captured, batch_size):
        return [e for e in eligible[:batch_size] if e not in already_captured]

    broken_batch = _broken_slice_before_filter(eligible, already_captured, 8)
    correct_batch = next_capture_batch(
        eligible, already_captured=already_captured, given_up=set(), batch_size=8)

    assert broken_batch == [], "the broken ordering stalls: nothing left in its own truncated slice"
    assert correct_batch == eligible[8:], "the shipped ordering keeps making forward progress"
    assert broken_batch != correct_batch, (
        "if these ever agree, the shipped function has regressed to the broken ordering"
    )


# ─────────────────────────────────────────────────────────────────────────────
# has_complete_chain_capture_today — DB-backed idempotency, survives a restart
# ─────────────────────────────────────────────────────────────────────────────

def test_has_complete_capture_today_false_until_written_then_day_scoped(tmp_path):
    db = tmp_path / "cap.db"
    assert has_complete_chain_capture_today(db, "TSLA", _TSLA_EXPIRY, _DAY_STR) is False

    persist_complete_chain_capture(
        db, ticker="TSLA", expiry=_TSLA_EXPIRY, contracts=_TSLA_CONTRACTS,
        spot=350.0, completeness_basis="strike_range=ALL", ts_utc=_TS_IN_WINDOW)

    assert has_complete_chain_capture_today(db, "TSLA", _TSLA_EXPIRY, _DAY_STR) is True
    from calibration.option_chain_morning_full import et_date_and_mins
    next_day = et_date_and_mins(_TS_IN_WINDOW + 86400)[0]
    assert has_complete_chain_capture_today(db, "TSLA", _TSLA_EXPIRY, next_day) is False, (
        "a capture from a prior ET day must not silently satisfy a later day's idempotency check"
    )
    assert has_complete_chain_capture_today(db, "TSLA", "2099-01-01", _DAY_STR) is False
    assert has_complete_chain_capture_today(db, "SPY", _TSLA_EXPIRY, _DAY_STR) is False


# ─────────────────────────────────────────────────────────────────────────────
# server._persist_universal_complete_chain — the systematic iteration itself
# ─────────────────────────────────────────────────────────────────────────────

def _fake_db(monkeypatch, srv, tmp_path):
    db_path = str(tmp_path / "test_ed_console.db")
    monkeypatch.setattr(srv, "get_db", lambda: SimpleNamespace(db_path=db_path))
    return db_path


def _reset_module_state(srv):
    srv._complete_chain_capture_attempts.clear()


def _wide_contracts_spanning_both_real_expiries():
    """The chain contracts _terrain_refresh_one already has in hand this cycle -- real
    TSLA rows at their real 2026-08-31 expiry plus real SPY rows at their real
    2026-07-17 expiry, combined only so ONE simulated ticker's fetch is shown to span
    two distinct real expiries."""
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


def _n_contracts_at_distinct_expiries(n: int, start_day: date = None):
    """n real-contract-shaped rows (one real TSLA row's fields, deep-copied), each at
    its own distinct real-calendar date -- never a hand-built contract literal."""
    start_day = start_day or _DAY
    template = _TSLA_CONTRACTS[0]
    out = []
    d = start_day
    for _ in range(n):
        row = copy.deepcopy(template)
        row["expirationDate"] = f"{d.isoformat()}T20:00:00.000+00:00"
        out.append(row)
        d = date.fromordinal(d.toordinal() + 1)
    return out


def test_universal_complete_chain_iterates_both_eligible_expiries_and_persists_each(
    monkeypatch, tmp_path
):
    import server as srv

    db_path = _fake_db(monkeypatch, srv, tmp_path)
    _reset_module_state(srv)
    # Both real expiries (2026-07-17, 2026-08-31) are 45 days apart -- wider than the
    # declared 37-day near-term horizon can admit together. Widening the horizon for
    # THIS test only proves the ITERATION mechanism across >1 expiry; the horizon
    # boundary itself is proven separately and exactly above with plain date strings.
    monkeypatch.setattr(srv, "COMPLETE_CHAIN_NEAR_TERM_MAX_DTE_DAYS", 30000.0)
    calls: list[dict] = []
    _gated_by_requested_expiry(monkeypatch, srv, calls)

    srv._persist_universal_complete_chain(
        "ZZTEST", client=object(), contracts=_wide_contracts_spanning_both_real_expiries(),
        ts_utc=_TS_IN_WINDOW)

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


def test_universal_complete_chain_self_gates_outside_the_capture_window(monkeypatch, tmp_path):
    """Outside 10:00-11:30 ET, or on a non-trading day, the function must make ZERO
    vendor calls -- it is called every terrain cycle now, so this gate is what keeps
    it from spending budget outside the deliberately-chosen post-open window."""
    import server as srv

    _fake_db(monkeypatch, srv, tmp_path)
    _reset_module_state(srv)
    calls: list[dict] = []
    _gated_by_requested_expiry(monkeypatch, srv, calls)

    # 09:00 ET -- before the window opens.
    srv._persist_universal_complete_chain(
        "ZZTEST", client=object(), contracts=_wide_contracts_spanning_both_real_expiries(),
        ts_utc=_ts_at(_DAY, 9, 0))
    assert calls == [], "must not fetch before the capture window opens"

    # A real Saturday: pick the day after _DAY that the calendar rejects, if _DAY+2 is
    # a weekend; if not (a holiday-adjacent week), fall back to a known Saturday far
    # from any exchange holiday.
    from time_et import is_trading_day_et
    probe = date.fromordinal(_DAY.toordinal() + 5)
    while is_trading_day_et(probe.isoformat()):
        probe = date.fromordinal(probe.toordinal() + 1)
    srv._persist_universal_complete_chain(
        "ZZTEST", client=object(), contracts=_wide_contracts_spanning_both_real_expiries(),
        ts_utc=_ts_at(probe, 10, 15))
    assert calls == [], "must not fetch on a non-trading day even at an in-window minute"


def test_universal_complete_chain_is_idempotent_within_the_same_et_day(monkeypatch, tmp_path):
    """F — a second cycle the same day must not re-fetch what is already proven
    complete for today -- vendor budget is not spent twice for the same fact."""
    import server as srv

    _fake_db(monkeypatch, srv, tmp_path)
    _reset_module_state(srv)
    monkeypatch.setattr(srv, "COMPLETE_CHAIN_NEAR_TERM_MAX_DTE_DAYS", 30000.0)
    calls: list[dict] = []
    _gated_by_requested_expiry(monkeypatch, srv, calls)

    contracts = _wide_contracts_spanning_both_real_expiries()
    srv._persist_universal_complete_chain(
        "ZZTEST", client=object(), contracts=contracts, ts_utc=_TS_IN_WINDOW)
    assert len([c for c in calls if c["strike_range"] == "ALL"]) == 2

    srv._persist_universal_complete_chain(
        "ZZTEST", client=object(), contracts=contracts, ts_utc=_TS_IN_WINDOW)
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
    _reset_module_state(srv)
    monkeypatch.setattr(srv, "COMPLETE_CHAIN_NEAR_TERM_MAX_DTE_DAYS", 30000.0)

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
        ts_utc=_TS_IN_WINDOW)

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
    _reset_module_state(srv)
    monkeypatch.setattr(srv, "COMPLETE_CHAIN_NEAR_TERM_MAX_DTE_DAYS", 30000.0)

    def _fake_gated(client, ticker, *, strike_count=None, strike_range=None,
                    from_date=None, to_date=None, priority=False):
        # Always answers with TSLA's real expiry, regardless of what was requested.
        return _FakeResp(200, _chain_json_for(_TSLA_CONTRACTS)), 0.0, 0.1
    monkeypatch.setattr(srv, "_gated_safe_get_chain", _fake_gated)

    srv._persist_universal_complete_chain(
        "ZZTEST", client=object(), contracts=_wide_contracts_spanning_both_real_expiries(),
        ts_utc=_TS_IN_WINDOW)

    assert srv.latest_complete_chain_capture(db_path, "ZZTEST", _SPY_EXPIRY) is None, (
        "vendor answering with the wrong expiry must never be banked as that expiry's proof"
    )


# ─────────────────────────────────────────────────────────────────────────────
# A/B/C/D/E — forward progress across successive cycles (the operator's own
# required controls for the round-4 defect)
# ─────────────────────────────────────────────────────────────────────────────

def _fake_gated_by_symbol_list(monkeypatch, srv, contracts_by_expiry, calls):
    def _fake_gated(client, ticker, *, strike_count=None, strike_range=None,
                    from_date=None, to_date=None, priority=False):
        req = str(to_date) if to_date else ""
        calls.append(req)
        rows = contracts_by_expiry.get(req)
        if rows is None:
            return _FakeResp(200, {"callExpDateMap": {}, "putExpDateMap": {}}), 0.0, 0.1
        return _FakeResp(200, _chain_json_for(rows)), 0.0, 0.1
    monkeypatch.setattr(srv, "_gated_safe_get_chain", _fake_gated)


def _real_contracts_at(expiry_str: str, n: int):
    """n real-contract-shaped rows (deep-copied from the real TSLA fixture, only
    `expirationDate`/`symbol` mutated) all sharing one distinct real-calendar expiry,
    so `_persist_universal_complete_chain`'s own scope-check (returned_exps == [expiry])
    passes for a fabricated-date expiry the same way it would for a real vendor date."""
    out = []
    for i, template in enumerate(_TSLA_CONTRACTS[:n] if n <= len(_TSLA_CONTRACTS) else
                                 [_TSLA_CONTRACTS[i % len(_TSLA_CONTRACTS)] for i in range(n)]):
        row = copy.deepcopy(template)
        row["expirationDate"] = f"{expiry_str}T20:00:00.000+00:00"
        row["symbol"] = f"{row.get('symbol', 'X')}_{expiry_str}_{i}"
        out.append(row)
    return out


def test_A_cap_plus_3_eligible_cycle_one_performs_at_most_cap_calls(monkeypatch, tmp_path):
    import server as srv

    _fake_db(monkeypatch, srv, tmp_path)
    _reset_module_state(srv)
    monkeypatch.setattr(srv, "COMPLETE_CHAIN_NEAR_TERM_MAX_DTE_DAYS", 400.0)
    cap = srv._COMPLETE_CAPTURE_MAX_EXPIRIES_PER_TICKER
    n_eligible = cap + 3
    wide_contracts = _n_contracts_at_distinct_expiries(n_eligible)

    calls: list[str] = []
    _fake_gated_by_symbol_list(monkeypatch, srv, {}, calls)

    srv._persist_universal_complete_chain(
        "ZZTEST", client=object(), contracts=wide_contracts, ts_utc=_TS_IN_WINDOW)

    assert len(calls) == cap, f"cycle 1 must attempt at most the cap ({cap}), not all {n_eligible} eligible"


def test_B_cycle_two_same_day_advances_past_already_complete_expiries(monkeypatch, tmp_path):
    import server as srv

    db_path = _fake_db(monkeypatch, srv, tmp_path)
    _reset_module_state(srv)
    monkeypatch.setattr(srv, "COMPLETE_CHAIN_NEAR_TERM_MAX_DTE_DAYS", 400.0)
    cap = srv._COMPLETE_CAPTURE_MAX_EXPIRIES_PER_TICKER
    n_eligible = cap + 3
    wide_contracts = _n_contracts_at_distinct_expiries(n_eligible)
    all_expiries = sorted({c["expirationDate"][:10] for c in wide_contracts})

    contracts_by_expiry = {e: _real_contracts_at(e, 5) for e in all_expiries}
    calls: list[str] = []
    _fake_gated_by_symbol_list(monkeypatch, srv, contracts_by_expiry, calls)

    srv._persist_universal_complete_chain(
        "ZZTEST", client=object(), contracts=wide_contracts, ts_utc=_TS_IN_WINDOW)
    cycle1_calls = list(calls)
    assert len(cycle1_calls) == cap

    calls.clear()
    srv._persist_universal_complete_chain(
        "ZZTEST", client=object(), contracts=wide_contracts, ts_utc=_TS_IN_WINDOW)

    assert set(calls).isdisjoint(cycle1_calls), (
        "cycle 2 must not re-request any expiry cycle 1 already captured"
    )
    assert set(calls) == set(all_expiries) - set(cycle1_calls), (
        "cycle 2 must attempt exactly the remaining not-yet-captured expiries"
    )
    for e in all_expiries[:cap]:
        assert srv.latest_complete_chain_capture(db_path, "ZZTEST", e) is not None


def test_C_eventual_full_coverage_across_successive_cycles(monkeypatch, tmp_path):
    """The direct behavioral proof of the fix: keep calling the function (as
    successive real terrain cycles would) until every eligible expiry is captured, and
    prove EXACT set equality against the declared eligible set -- no more, no fewer.
    If _persist_universal_complete_chain regresses to slicing eligible[:cap] BEFORE
    filtering already-captured expiries (the round-4 defect), this loop would run
    forever without ever reaching full coverage, and the bounded `for _ in range(...)`
    below turns that into a failing assertion rather than a hang."""
    import server as srv

    db_path = _fake_db(monkeypatch, srv, tmp_path)
    _reset_module_state(srv)
    monkeypatch.setattr(srv, "COMPLETE_CHAIN_NEAR_TERM_MAX_DTE_DAYS", 400.0)
    cap = srv._COMPLETE_CAPTURE_MAX_EXPIRIES_PER_TICKER
    n_eligible = cap + 5
    wide_contracts = _n_contracts_at_distinct_expiries(n_eligible)
    all_expiries = sorted({c["expirationDate"][:10] for c in wide_contracts})
    contracts_by_expiry = {e: _real_contracts_at(e, 3) for e in all_expiries}
    calls: list[str] = []
    _fake_gated_by_symbol_list(monkeypatch, srv, contracts_by_expiry, calls)

    max_cycles = (n_eligible // cap) + 2  # generous bound, not a tight timing assumption
    for _ in range(max_cycles):
        srv._persist_universal_complete_chain(
            "ZZTEST", client=object(), contracts=wide_contracts, ts_utc=_TS_IN_WINDOW)
        captured = {
            e for e in all_expiries
            if srv.latest_complete_chain_capture(db_path, "ZZTEST", e) is not None
        }
        if captured == set(all_expiries):
            break

    captured = {
        e for e in all_expiries
        if srv.latest_complete_chain_capture(db_path, "ZZTEST", e) is not None
    }
    assert captured == set(all_expiries), (
        f"eventual coverage must reach EXACT set equality with the declared eligible "
        f"set within {max_cycles} cycles; missing {set(all_expiries) - captured}"
    )
    for e in all_expiries:
        cap_row = srv.latest_complete_chain_capture(db_path, "ZZTEST", e)
        assert {c["symbol"] for c in cap_row["contracts"]} == {c["symbol"] for c in contracts_by_expiry[e]}


def test_D_restart_re_entry_advances_from_durable_db_state(monkeypatch, tmp_path):
    """D — clearing the in-process attempt bookkeeping (modeling a process restart;
    only completion, in the DB, is required to be durable) must not cause already-
    captured expiries to be re-fetched, and must not prevent the remaining ones from
    being attempted."""
    import server as srv

    db_path = _fake_db(monkeypatch, srv, tmp_path)
    _reset_module_state(srv)
    monkeypatch.setattr(srv, "COMPLETE_CHAIN_NEAR_TERM_MAX_DTE_DAYS", 400.0)
    cap = srv._COMPLETE_CAPTURE_MAX_EXPIRIES_PER_TICKER
    n_eligible = cap + 2
    wide_contracts = _n_contracts_at_distinct_expiries(n_eligible)
    all_expiries = sorted({c["expirationDate"][:10] for c in wide_contracts})
    contracts_by_expiry = {e: _real_contracts_at(e, 2) for e in all_expiries}
    calls: list[str] = []
    _fake_gated_by_symbol_list(monkeypatch, srv, contracts_by_expiry, calls)

    srv._persist_universal_complete_chain(
        "ZZTEST", client=object(), contracts=wide_contracts, ts_utc=_TS_IN_WINDOW)
    captured_before_restart = {
        e for e in all_expiries
        if srv.latest_complete_chain_capture(db_path, "ZZTEST", e) is not None
    }
    assert captured_before_restart, "precondition: cycle 1 must have captured something"

    # Simulate a process restart: the in-memory attempt map is gone, the DB is not.
    srv._complete_chain_capture_attempts.clear()
    calls.clear()

    srv._persist_universal_complete_chain(
        "ZZTEST", client=object(), contracts=wide_contracts, ts_utc=_TS_IN_WINDOW)

    assert set(calls).isdisjoint(captured_before_restart), (
        "post-restart, already-durably-captured expiries must not be re-fetched"
    )
    captured_after = {
        e for e in all_expiries
        if srv.latest_complete_chain_capture(db_path, "ZZTEST", e) is not None
    }
    assert captured_after > captured_before_restart, (
        "post-restart, the remaining expiries must still be attempted and captured"
    )


def test_E_one_chronically_failing_expiry_does_not_starve_later_ones(monkeypatch, tmp_path):
    """E — the earliest-sorted eligible expiry fails on EVERY cycle forever. It must
    give up after its own attempt cap (not consume a budget slot indefinitely) so
    later eligible expiries still reach full coverage within a bounded number of
    cycles."""
    import server as srv

    db_path = _fake_db(monkeypatch, srv, tmp_path)
    _reset_module_state(srv)
    monkeypatch.setattr(srv, "COMPLETE_CHAIN_NEAR_TERM_MAX_DTE_DAYS", 400.0)
    cap = srv._COMPLETE_CAPTURE_MAX_EXPIRIES_PER_TICKER
    n_eligible = cap + 3
    wide_contracts = _n_contracts_at_distinct_expiries(n_eligible)
    all_expiries = sorted({c["expirationDate"][:10] for c in wide_contracts})
    chronic_failer = all_expiries[0]  # sorts first -> always the earliest candidate
    healthy = [e for e in all_expiries if e != chronic_failer]
    contracts_by_expiry = {e: _real_contracts_at(e, 2) for e in healthy}

    def _fake_gated(client, ticker, *, strike_count=None, strike_range=None,
                    from_date=None, to_date=None, priority=False):
        req = str(to_date) if to_date else ""
        if req == chronic_failer:
            return _FakeResp(502, {}), 0.0, 0.1
        rows = contracts_by_expiry.get(req)
        if rows is None:
            return _FakeResp(200, {"callExpDateMap": {}, "putExpDateMap": {}}), 0.0, 0.1
        return _FakeResp(200, _chain_json_for(rows)), 0.0, 0.1
    monkeypatch.setattr(srv, "_gated_safe_get_chain", _fake_gated)

    # Run the FULL bounded cycle count (never break early on partial success) -- this
    # test must observe both outcomes: healthy expiries fully captured, AND the
    # chronic failer actually reaching its own give-up threshold, not just whichever
    # comes first.
    max_cycles = srv._COMPLETE_CAPTURE_EXPIRY_MAX_ATTEMPTS + (n_eligible // cap) + 2
    for _ in range(max_cycles):
        srv._persist_universal_complete_chain(
            "ZZTEST", client=object(), contracts=wide_contracts, ts_utc=_TS_IN_WINDOW)

    captured = {
        e for e in healthy
        if srv.latest_complete_chain_capture(db_path, "ZZTEST", e) is not None
    }
    assert captured == set(healthy), (
        f"every healthy expiry must eventually be captured despite one chronic "
        f"failure hogging a budget slot each cycle; missing {set(healthy) - captured}"
    )
    assert srv.latest_complete_chain_capture(db_path, "ZZTEST", chronic_failer) is None, (
        "the chronically-failing expiry itself must never be falsely marked complete"
    )
    assert (
        srv._complete_chain_capture_attempts.get(("ZZTEST", chronic_failer, _DAY_STR), 0)
        >= srv._COMPLETE_CAPTURE_EXPIRY_MAX_ATTEMPTS
    ), "the chronic failer must have hit its own give-up cap, not been retried forever"


def test_universal_complete_chain_truncates_and_logs_beyond_the_per_cycle_cap(
    monkeypatch, tmp_path
):
    """Attack: an unusually weekly-heavy ticker must not unboundedly inflate one
    cycle's vendor cost -- only up to the declared per-cycle cap is fetched, and the
    truncation is logged, never silent."""
    import server as srv

    _fake_db(monkeypatch, srv, tmp_path)
    _reset_module_state(srv)
    monkeypatch.setattr(srv, "COMPLETE_CHAIN_NEAR_TERM_MAX_DTE_DAYS", 30000.0)
    cap = srv._COMPLETE_CAPTURE_MAX_EXPIRIES_PER_TICKER
    n_eligible = cap + 3
    wide_contracts = _n_contracts_at_distinct_expiries(n_eligible)

    calls: list[str] = []
    _fake_gated_by_symbol_list(monkeypatch, srv, {}, calls)

    logged = []
    monkeypatch.setattr(srv.log, "warning", lambda msg, *a: logged.append(msg % a if a else msg))

    srv._persist_universal_complete_chain(
        "ZZTEST", client=object(), contracts=wide_contracts, ts_utc=_TS_IN_WINDOW)

    assert len(calls) == cap, f"must fetch at most the declared cap ({cap}), not all {n_eligible} eligible expiries"
    assert any("truncated" in m for m in logged), "truncation beyond the cap must be logged, never silent"
