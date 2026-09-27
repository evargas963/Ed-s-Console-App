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
                     vendor retry with the evidence gone. (P2-1: the daemon fetches the
                     chain; the console's quarantine and its tests are deleted.)
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




# ── the mission-scope wildcard control was removed with governance/pm_mission.json
#    (2026-08-24 Architecture A teardown): there is no mission file left to widen.
