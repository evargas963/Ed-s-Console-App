"""FIND-GAMMA-FULLCHAIN-STRIKES-V1 — wide morning capture helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from calibration.option_chain_morning_full import (
    GEX_FULL_CHAIN_STRIKE_COUNT,
    SOURCE_WIDE,
    et_date_and_mins,
    filter_near_term_contracts,
    has_morning_full_capture,
    maybe_persist_morning_full_chain,
)
from time_et import ET


def test_gex_full_chain_strike_count_is_wide_not_ui_20() -> None:
    assert GEX_FULL_CHAIN_STRIKE_COUNT == 100
    import server as srv

    assert srv.CHAIN_STRIKE_COUNT == 20
    assert srv.GEX_FULL_CHAIN_STRIKE_COUNT == 100


def test_has_morning_full_capture_false_then_true(tmp_path: Path) -> None:
    # institutional-synthetic-ok: near-term-filter/capture test needs controlled DTEs
    # (incl. 120 to prove the <=37 boundary) and exact strike counts to prove no thinning;
    # this exercises the DTE filter + persistence, not gamma/GEX correctness.
    db = tmp_path / "gex.db"
    # Morning ET window: build a UTC ts that is 09:40 America/Chicago
    local = datetime(2026, 7, 20, 9, 40, tzinfo=ET)
    ts = local.astimezone(timezone.utc).timestamp()
    et_date, mins = et_date_and_mins(ts)
    assert 570 <= mins <= 600
    assert has_morning_full_capture(db, "SPY", et_date) is False

    contracts = []
    for exp_off, dte in ((0, 0), (7, 7), (21, 21)):
        day = f"2026-07-{20 + exp_off:02d}" if exp_off < 11 else "2026-08-10"
        for i in range(40):
            strike = 700.0 + i
            contracts.append(
                {
                    "putCall": "CALL" if i % 2 == 0 else "PUT",
                    "strikePrice": strike,
                    "expirationDate": f"{day}T20:00:00.000+00:00",
                    "daysToExpiration": dte,
                    "gamma": 0.01,
                    "openInterest": 10,
                    "delta": 0.5 if i % 2 == 0 else -0.5,
                    "multiplier": 100,
                }
            )
    # ensure near-term filter keeps far calendar within 37d
    contracts.append(
        {
            "putCall": "PUT",
            "strikePrice": 600.0,
            "expirationDate": "2026-08-15T20:00:00.000+00:00",
            "daysToExpiration": 26,
            "gamma": 0.02,
            "openInterest": 50,
            "delta": -0.2,
            "multiplier": 100,
        }
    )
    contracts.append(
        {
            "putCall": "PUT",
            "strikePrice": 500.0,
            "expirationDate": "2026-12-01T20:00:00.000+00:00",
            "daysToExpiration": 120,
            "gamma": 0.01,
            "openInterest": 99,
            "delta": -0.1,
            "multiplier": 100,
        }
    )

    near = filter_near_term_contracts(contracts)
    assert all(c["daysToExpiration"] <= 37 for c in near)
    assert not any(c.get("daysToExpiration") == 120 for c in near)
    # all strikes on kept expiries retained (not strike-thinned by filter)
    strikes_dte0 = {c["strikePrice"] for c in near if c["daysToExpiration"] == 0}
    assert len(strikes_dte0) == 40

    res = maybe_persist_morning_full_chain(
        db,
        ticker="SPY",
        contracts=contracts,
        spot=720.0,
        ts_utc=ts,
        source=SOURCE_WIDE,
    )
    assert res["status"] == "ok"
    assert has_morning_full_capture(db, "SPY", et_date) is True
    # second call skips without needing another fetch
    res2 = maybe_persist_morning_full_chain(
        db,
        ticker="SPY",
        contracts=contracts,
        spot=720.0,
        ts_utc=ts,
        source=SOURCE_WIDE,
    )
    assert res2["status"] == "idempotent_skip"


# ── UNIVERSAL CAPTURE SPAN (Bugbot 2026-07-20, HIGH — confirmed) ────────────
# The persist gate rejected everything after MORNING_END_MINS while the terrain loop's
# universal capture calls it ONLY after MORNING_END_MINS — every universal capture was
# fetched wide, silently discarded, and logged as success. These drive the REAL persist
# function across the span boundaries so that mismatch can never ship silently again.

from datetime import datetime as _dt

from calibration.option_chain_morning_full import (  # noqa: F811 — span constants only
    MORNING_END_MINS,
    UNIVERSAL_CAPTURE_END_MINS,
)
from time_et import ET as _ET


def _ts_at_et_minutes(mins: int) -> float:
    """A weekday timestamp at exactly `mins` past midnight ET (today's ET date)."""
    now = _dt.now(_ET)
    t = now.replace(hour=mins // 60, minute=mins % 60, second=0, microsecond=0)
    return t.timestamp()


def _real_contracts():
    import json as _json
    from pathlib import Path as _Path
    fx = _Path(__file__).parent / "fixtures" / "real_spy_0dte_chain_with_poison.json"
    return _json.loads(fx.read_text(encoding="utf-8"))["chain"]


def test_persist_accepts_the_universal_span(tmp_path):
    """10:01-11:30 ET is where EVERY universal capture lands — it must persist."""
    db = tmp_path / "t.db"
    res = maybe_persist_morning_full_chain(
        db, ticker="SPY", contracts=_real_contracts(), spot=745.0,
        ts_utc=_ts_at_et_minutes(MORNING_END_MINS + 30),
    )
    assert res["status"] == "ok", (
        f"post-window persist must succeed, got {res} — this exact rejection made the "
        "entire universal capture a silent no-op"
    )


def test_persist_rejects_beyond_the_span_and_is_idempotent(tmp_path):
    db = tmp_path / "t.db"
    late = maybe_persist_morning_full_chain(
        db, ticker="SPY", contracts=_real_contracts(), spot=745.0,
        ts_utc=_ts_at_et_minutes(UNIVERSAL_CAPTURE_END_MINS + 1),
    )
    assert late["status"] == "skipped" and late["reason"] == "outside_capture_span"
    ts = _ts_at_et_minutes(MORNING_END_MINS + 5)
    first = maybe_persist_morning_full_chain(
        db, ticker="SPY", contracts=_real_contracts(), spot=745.0, ts_utc=ts)
    second = maybe_persist_morning_full_chain(
        db, ticker="SPY", contracts=_real_contracts(), spot=745.0, ts_utc=ts)
    assert first["status"] == "ok" and second["status"] == "idempotent_skip"


def test_server_helper_honours_the_persist_verdict(monkeypatch, tmp_path):
    """Bugbot HIGH #2: memo+success-log on ANY non-exception. The dict is the arbiter."""
    import server

    class _Db:  # minimal stand-in for get_db()
        db_path = tmp_path / "t.db"

    monkeypatch.setattr(server, "get_db", lambda: _Db())
    server._morning_capture_done.clear()

    # a persist that reports NOTHING WRITTEN must not memoise
    monkeypatch.setattr(server, "maybe_persist_morning_full_chain",
                        lambda *_a, **_k: {"status": "skipped", "reason": "outside_capture_span"})
    server._persist_universal_capture("SPY", ("SPY", "2026-07-20"), 100, [{}], 745.0)
    assert ("SPY", "2026-07-20") not in server._morning_capture_done, (
        "a skipped persist was memoised as done — the silent-suppression defect"
    )

    # a persist that reports ok MUST memoise
    monkeypatch.setattr(server, "maybe_persist_morning_full_chain",
                        lambda *_a, **_k: {"status": "ok", "n_contracts": 40})
    server._persist_universal_capture("SPY", ("SPY", "2026-07-20"), 100, [{}], 745.0)
    assert ("SPY", "2026-07-20") in server._morning_capture_done


def test_capture_attempts_are_bounded(monkeypatch, tmp_path):
    """Bugbot MEDIUM: empty results re-forced wide fetches every cycle for 90 minutes."""
    import server

    class _Db:
        db_path = tmp_path / "t.db"

    monkeypatch.setattr(server, "get_db", lambda: _Db())
    monkeypatch.setattr(server, "gex_et_date_and_mins",
                        lambda _ts=None: ("2026-07-20", MORNING_END_MINS + 10))
    monkeypatch.setattr(server, "has_morning_full_capture", lambda *_a: False)
    server._morning_capture_done.clear()
    server._morning_capture_attempts.clear()

    wants = [server._universal_capture_wanted("ZZZT")[0] for _ in range(6)]
    assert wants[:3] == [True, True, True], "first attempts must proceed"
    assert wants[3:] == [False, False, False], (
        "after the cap the loop must stop paying for wide fetches"
    )
    assert ("ZZZT", "2026-07-20") in server._morning_capture_done
