"""RC-281 — three `# silent-zero-ok:` reasons I wrote by hand were FALSE.

Cursor's adversarial audit of `20800292..bd9a9604` executed the code instead of reading my
comments, and each of these tests re-runs one of its probes and asserts the OPPOSITE result
to the one it measured.

    l1_pipeline_ms   my reason: "the caller gates on ms > 0". There is no such gate. The
                     value was accumulated into l1_build_ms_sum and published as
                     l1_build_ms, so absent timing was a measured zero.
    quarantine       my reason: "no recorded expiry means no cooldown is in force". Probe:
                     blocks=False, state_after={} — the hold RELEASED and the entry was
                     erased. Every constructor supplies until_ts, so absence is malformed
                     state, and the exemption turned an invariant failure into an immediate
                     vendor retry with the evidence gone.
    market_session   et_date was optional for one commit; market_session(10, 0) still
                     returned "rth" on a Saturday.

THE ROOT THESE LOCK. The escape marker validates that a reason EXISTS, never that it is
TRUE. RC-276 replaced a file-level exemption with a line-level one and I called it a fix;
an unverifiable reason is the same hole at finer grain. These tests are the machine the
prose lacked.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


# ───────────────────────────────────── l1_pipeline_ms: absent is not zero ms ────

def test_absent_pipeline_timing_is_not_published_as_zero_milliseconds():
    """A missing gauge reading must not enter the latency average as a fast one."""
    import inspect

    import server as srv

    # TEST_SYSTEM_REHAB_V2: this used to also compute `i = src.find('out["l1_pipeline_ms"]')`
    # from a separate, unused `src = inspect.getsource(srv)` call, then end with
    # `assert i or True` -- vacuous regardless of `i` (str.find returns -1, which is
    # truthy, on a miss; `-1 or True` and `n or True` are both always True). Removed:
    # the three real assertions below already cover the property directly.
    blk = inspect.getsource(srv)  # whole module; assert on the specific repaired lines
    assert 'ms = _fin_ms(out.get("l1_pipeline_ms"))' in blk, (
        "l1_pipeline_ms is being coerced again instead of read as optional")
    assert 'if ms is not None:' in blk, (
        "absent timing is accumulated into l1_build_ms_sum again")
    assert '"l1_build_ms": None if ms is None else round(ms, 3)' in blk, (
        "absent timing is published as 0.0 ms again — it depresses the average silently")


def test_no_active_exemption_claims_the_nonexistent_pipeline_guard():
    """The untrue sentence must not come back as a LIVE exemption.

    It survives deliberately in the RC-281 comment that records what was wrong — deleting
    the record of a false justification is how the next author writes it again. What must
    never return is the claim attached to a working `# silent-zero-ok:` marker.
    """
    src = (REPO / "server.py").read_text(encoding="utf-8", errors="replace")
    offenders = [
        ln.strip() for ln in src.splitlines()
        if "silent-zero-ok:" in ln and "caller gates on ms > 0" in ln
    ]
    assert not offenders, (
        f"an exemption claims a guard that does not exist: {offenders}")


# ─────────────────────────────── quarantine: a malformed hold must fail CLOSED ────

def _fresh_quarantine(monkeypatch, entry: dict):
    import server as srv

    monkeypatch.setattr(srv, "_terrain_quarantine", {"ZZQ": entry}, raising=False)
    monkeypatch.setattr(srv, "_terrain_quarantine_skips", {}, raising=False)
    return srv


def test_a_hold_with_no_expiry_still_blocks(monkeypatch):
    """Cursor's probe returned blocks=False and an ERASED entry. Both must invert.

    Every constructor supplies until_ts, so an entry without one is malformed state. The
    old reading released the hold AND popped the record, so the vendor was retried
    immediately and the evidence of why was gone.
    """
    srv = _fresh_quarantine(monkeypatch, {"failures": 3, "reason": "boom"})
    assert srv._terrain_quarantine_blocks("ZZQ") is True, (
        "a malformed quarantine entry released the hold — fail-open on missing state")
    assert "ZZQ" in srv._terrain_quarantine, (
        "the entry was erased, destroying the evidence of the malformed hold")


def test_a_real_expiry_still_releases_when_it_passes(monkeypatch):
    """Failing closed must not mean failing forever."""
    import time

    srv = _fresh_quarantine(monkeypatch, {"failures": 1, "reason": "x",
                                          "until_ts": time.time() - 60.0})
    assert srv._terrain_quarantine_blocks("ZZQ") is False
    assert "ZZQ" not in srv._terrain_quarantine, "an expired soft hold must self-release"


def test_a_future_expiry_still_blocks(monkeypatch):
    import time

    srv = _fresh_quarantine(monkeypatch, {"failures": 1, "reason": "x",
                                          "until_ts": time.time() + 600.0})
    assert srv._terrain_quarantine_blocks("ZZQ") is True


def test_the_reason_string_admits_a_malformed_hold(monkeypatch):
    """The operator-facing line must say the hold has no expiry, not 'next attempt in 0s'."""
    srv = _fresh_quarantine(monkeypatch, {"failures": 3, "reason": "boom"})
    # TEST_SYSTEM_REHAB_V2: was `if msg: assert ...` -- if `_terrain_quarantine_reason`
    # were removed/renamed, or returned an empty string for a malformed hold, `msg`
    # would be falsy and the assert line never ran at all: zero coverage instead of a
    # failure. The function's existence and a non-empty message are now required.
    assert hasattr(srv, "_terrain_quarantine_reason"), (
        "_terrain_quarantine_reason is gone; the malformed-hold message can't be checked")
    msg = srv._terrain_quarantine_reason("ZZQ")
    assert msg, "a malformed hold (no until_ts) must produce a non-empty reason string"
    assert "NO expiry recorded" in msg or "malformed" in msg, msg


# ──────────────────────────── market_session: the date is REQUIRED, not optional ────

def test_market_session_refuses_to_guess_without_a_date():
    """Optional meant the next caller could silently reintroduce weekend RTH labels."""
    from db import market_session

    with pytest.raises(TypeError):
        market_session(10, 0)          # type: ignore[call-arg]


def test_market_session_is_calendar_first():
    from db import market_session

    assert market_session(10, 0, et_date="2026-08-01") == "closed"   # Saturday
    assert market_session(10, 0, et_date="2026-08-02") == "closed"   # Sunday
    assert market_session(10, 0, et_date="2026-07-31") == "rth"      # Friday


def test_the_timestamp_path_supplies_the_date_itself():
    """market_session_from_ts_utc has the date; withholding it was the whole defect."""
    import datetime

    from ml_data_common import market_session_from_ts_utc

    sat = datetime.datetime(2026, 8, 1, 14, 0, tzinfo=datetime.timezone.utc).timestamp()
    fri = datetime.datetime(2026, 7, 31, 14, 0, tzinfo=datetime.timezone.utc).timestamp()
    assert market_session_from_ts_utc(sat) == "closed"
    assert market_session_from_ts_utc(fri) == "rth"


# ── the mission-scope wildcard control was removed with governance/pm_mission.json
#    (2026-08-24 Architecture A teardown): there is no mission file left to widen.
