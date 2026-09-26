"""The near-term complete-chain capture: each near-term expiry of the full chain the terrain
loop already fetched is saved to complete_chain_captures once per ET day, inside the capture
window, with no vendor call of its own.

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

import json
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from calibration.complete_chain_capture import (
    eligible_near_term_expiries,
    has_complete_chain_capture_today,
    latest_complete_chain_capture,
    persist_complete_chain_capture,
)
from tests.conftest import most_recent_trading_day_et
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
# server._persist_universal_complete_chain — saves from the chain already in hand
# ─────────────────────────────────────────────────────────────────────────────

def _fake_db(monkeypatch, srv, tmp_path):
    db_path = str(tmp_path / "test_ed_console.db")
    monkeypatch.setattr(srv, "get_db", lambda: SimpleNamespace(db_path=db_path))
    return db_path


def _no_vendor_calls(monkeypatch, srv):
    """The capture must never call Schwab: the contracts are already in hand."""
    def _boom(*a, **k):
        raise AssertionError("the complete-chain capture made a vendor call")
    monkeypatch.setattr(srv, "_gated_safe_get_chain", _boom)


def _chain_in_hand():
    """The full chain _terrain_refresh_one already fetched: real TSLA rows at their real
    2026-08-31 expiry plus real SPY rows at their real 2026-07-17 expiry."""
    return list(_TSLA_CONTRACTS) + list(_SPY_CONTRACTS)


def test_each_eligible_expiry_is_saved_from_the_chain_in_hand_with_no_vendor_call(monkeypatch, tmp_path):
    import server as srv
    db_path = _fake_db(monkeypatch, srv, tmp_path)
    _no_vendor_calls(monkeypatch, srv)
    monkeypatch.setattr(srv, "resolve_spot", lambda tk, **k: (123.0, "test", 0.0))
    # the two real expiries are 45 days apart: widen the horizon so both are eligible here
    monkeypatch.setattr(srv, "COMPLETE_CHAIN_NEAR_TERM_MAX_DTE_DAYS", 30000.0)

    srv._persist_universal_complete_chain("ZZTEST", _chain_in_hand(), ts_utc=_TS_IN_WINDOW)

    tsla = latest_complete_chain_capture(db_path, "ZZTEST", _TSLA_EXPIRY)
    spy = latest_complete_chain_capture(db_path, "ZZTEST", _SPY_EXPIRY)
    assert {c["symbol"] for c in tsla["contracts"]} == {c["symbol"] for c in _TSLA_CONTRACTS}
    assert {c["symbol"] for c in spy["contracts"]} == {c["symbol"] for c in _SPY_CONTRACTS}
    assert tsla["completeness_basis"] == spy["completeness_basis"] == srv.COMPLETENESS_BASIS_STRIKE_RANGE_ALL


def test_nothing_is_saved_outside_the_capture_window_or_on_a_non_trading_day(monkeypatch, tmp_path):
    import server as srv
    from time_et import is_trading_day_et
    db_path = _fake_db(monkeypatch, srv, tmp_path)
    _no_vendor_calls(monkeypatch, srv)
    monkeypatch.setattr(srv, "COMPLETE_CHAIN_NEAR_TERM_MAX_DTE_DAYS", 30000.0)
    srv._persist_universal_complete_chain("ZZTEST", _chain_in_hand(), ts_utc=_ts_at(_DAY, 9, 0))
    probe = date.fromordinal(_DAY.toordinal() + 5)
    while is_trading_day_et(probe.isoformat()):
        probe = date.fromordinal(probe.toordinal() + 1)
    srv._persist_universal_complete_chain("ZZTEST", _chain_in_hand(), ts_utc=_ts_at(probe, 10, 15))
    assert latest_complete_chain_capture(db_path, "ZZTEST", _TSLA_EXPIRY) is None


def test_an_expiry_already_saved_today_is_not_saved_again(monkeypatch, tmp_path):
    import server as srv
    _fake_db(monkeypatch, srv, tmp_path)
    _no_vendor_calls(monkeypatch, srv)
    monkeypatch.setattr(srv, "resolve_spot", lambda tk, **k: (123.0, "test", 0.0))
    monkeypatch.setattr(srv, "COMPLETE_CHAIN_NEAR_TERM_MAX_DTE_DAYS", 30000.0)
    writes = []
    real = srv.persist_complete_chain_capture
    monkeypatch.setattr(srv, "persist_complete_chain_capture",
                        lambda *a, **k: writes.append(k["expiry"]) or real(*a, **k))
    srv._persist_universal_complete_chain("ZZTEST", _chain_in_hand(), ts_utc=_TS_IN_WINDOW)
    srv._persist_universal_complete_chain("ZZTEST", _chain_in_hand(), ts_utc=_TS_IN_WINDOW + 60)
    assert sorted(writes) == sorted([_TSLA_EXPIRY, _SPY_EXPIRY]), "each expiry written once per ET day"
