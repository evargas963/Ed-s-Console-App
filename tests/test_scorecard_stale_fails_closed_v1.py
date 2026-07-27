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
    """Friday's run is still the latest run on Monday. Counting hours would call it 3 days old."""
    assert _age("2026-07-24") == 1, "Friday -> Monday must be ONE trading day"
    assert _age("2026-07-22") == 3, "Wednesday -> Monday must be THREE trading days"


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
