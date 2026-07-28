"""RC-78: the coach scorecard fails closed on STALE, not only on ABSENT.

The endpoint's docstring claimed it "never" served a stale rate while it was serving hold-rates
111.6 hours (4.6 days) old under the coach's "Measured on our own history". It validated that the
report PARSED, never that it was RECENT — age was displayed as a footnote instead of being a
precondition to serve, and a date printed beside a number does not stop the number being read.

The budget counts TRADING days on purpose: a wall-clock budget would condemn every scorecard each
weekend and teach the operator to ignore the warning.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("PYTEST_CURRENT_TEST", "boot")

import server  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CHART = ROOT / "static" / "chart.html"


def _age(s: str | None) -> int | None:
    return server.scorecard_trading_day_age(s)


def test_weekend_does_not_age_a_scorecard():
    """Friday's run is still the latest run on Monday — a weekend adds ZERO trading days.

    REPAIRED 2026-07-28: the first version hard-coded 2026-07-24 and asserted == 1, which was
    only true ON Monday 07-27 — a date-frozen test rots one day later (it failed Tuesday at
    HEAD, proven by swap-test). The invariant is calendar-relative: the age of the most recent
    Friday equals the count of trading days after it, and the Saturday/Sunday between never
    add to it. Computed against the SAME trading-day authority the function uses, over a
    window that always contains a weekend."""
    import datetime
    from time_et import is_trading_day_et
    today = datetime.datetime.now(server.ET_ZONE).date() if hasattr(server, "ET_ZONE") else (
        datetime.datetime.now(datetime.timezone.utc).astimezone(
            __import__("zoneinfo").ZoneInfo("America/New_York")).date())
    # walk back to the most recent Friday strictly before today
    d = today - datetime.timedelta(days=1)
    while d.weekday() != 4:
        d -= datetime.timedelta(days=1)
    expected = sum(1 for k in range(1, (today - d).days + 1)
                   if is_trading_day_et(d + datetime.timedelta(days=k)))
    got = _age(d.isoformat())
    assert got == expected, (
        f"Friday {d} -> today {today}: expected {expected} trading day(s), got {got} — "
        f"the weekend between them must add nothing"
    )
    assert (today - d).days > expected, "the window must actually contain non-trading days"


def test_unusable_stamps_are_never_fresh():
    """Absence of a readable age must not resolve to age zero."""
    for bad in (None, "", "not-a-date", "2099-01-01"):
        assert _age(bad) is None, f"{bad!r} produced a usable age"


def test_stale_report_withholds_the_numbers_and_says_why():
    """The failure the operator actually suffers: a present, parseable, OUT-OF-DATE report."""
    body = json.loads(bytes(server.get_terrain_scorecard().body).decode())
    if not body:
        return                                  # no report on disk — covered by the absent case
    if body.get("stale"):
        assert "wall_hold_trusted" not in body, "stale hold-rates were served anyway"
        assert "weighting_scorecard" not in body, "stale weighting numbers were served anyway"
        assert body.get("stale_reason"), "withheld the numbers without saying why"
        assert body.get("age_trading_days") != 0
    else:
        assert body.get("age_trading_days") is not None
        assert body["age_trading_days"] <= server.SCORECARD_MAX_TRADING_DAY_AGE


def test_budget_is_one_trading_day():
    """A daily job older than one session means a run was MISSED — exactly when it must stop
    speaking. If this constant grows, the reason must grow with it."""
    assert server.SCORECARD_MAX_TRADING_DAY_AGE == 1


def test_client_refuses_a_stale_scorecard_and_states_the_reason():
    src = CHART.read_text(encoding="utf-8")
    assert "sc.generated_utc && !sc.stale" in src, (
        "the client accepts any parseable scorecard again — a stale one would render as measured"
    )
    assert "scorecardStale" in src and "stale_reason" in src, (
        "staleness is not surfaced, so the coach silently goes quiet with no explanation"
    )


# ── RC-108: Schwab token death is calendar-predictable; the console must warn BEFORE it ──────

def test_schwab_token_countdown_urgency_tiers():
    """7-day hard limit: quiet before day 5, warn at 5, red at 6, honest unknown on no file."""
    import time
    now = time.time()
    ok = server.schwab_token_countdown(now - 2 * 86400)
    assert ok["schwab_token_urgency"] == "ok" and ok["schwab_token_note"] == ""
    warn = server.schwab_token_countdown(now - 5.5 * 86400)
    assert warn["schwab_token_urgency"] == "warn"
    assert "reauth_schwab.py" in warn["schwab_token_note"], "the warning must carry the remedy"
    red = server.schwab_token_countdown(now - 6.5 * 86400)
    assert red["schwab_token_urgency"] == "red"
    assert "reauth_schwab.py" in red["schwab_token_note"]
    unknown = server.schwab_token_countdown(None)
    assert unknown["schwab_token_urgency"] == "unknown"
    assert unknown["schwab_token_age_days"] is None, "an unreadable file must never fake an age"


def test_terrain_staleness_carries_the_token_countdown():
    """The countdown rides the SAME payload the levels ride — one faucet, every terrain reply,
    including the no-snapshot stub (which is exactly the state a dead token produces)."""
    stub = server.terrain_staleness(None)
    assert "schwab_token_urgency" in stub and "schwab_token_note" in stub
    import time
    live = server.terrain_staleness(time.time())
    assert "schwab_token_urgency" in live


def test_visible_token_chip_binds_the_urgency_field():
    """Surface-bound (RC-106 contract): #sb-token-warn must be painted FROM schwab_token_urgency
    by one writer, and both terrain receive sites must call that writer."""
    import re
    src = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    assert 'id="sb-token-warn"' in src, "the visible chip markup is gone"
    i = src.find("function edPaintTokenWarn")
    assert i > 0, "the one token-chip writer is gone"
    body = re.sub(r"//.*$", "", src[i:i + 1600], flags=re.M)
    assert "sb-token-warn" in body and "schwab_token_urgency" in body
    assert src.count("edPaintTokenWarn(") >= 3, (
        "both terrain receive sites must feed the chip (definition + 2 call sites)"
    )
