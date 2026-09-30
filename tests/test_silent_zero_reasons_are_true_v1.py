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

THE ROOT THESE LOCK. The escape marker validates that a reason EXISTS, never that it is
TRUE. RC-276 replaced a file-level exemption with a line-level one and I called it a fix;
an unverifiable reason is the same hole at finer grain. These tests are the machine the
prose lacked.
"""

from __future__ import annotations

import sys
from pathlib import Path


REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


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
    assert srv._terrain_quarantine_blocks("ZZQ", 1_790_000_000.0) is True, (
        "a malformed quarantine entry released the hold — fail-open on missing state")
    assert "ZZQ" in srv._terrain_quarantine, (
        "the entry was erased, destroying the evidence of the malformed hold")


def test_a_real_expiry_still_releases_when_it_passes(monkeypatch):
    """Failing closed must not mean failing forever."""
    now = 1_790_000_000.0
    srv = _fresh_quarantine(monkeypatch, {"failures": 1, "reason": "x", "until_ts": now - 60.0})
    assert srv._terrain_quarantine_blocks("ZZQ", now) is False
    assert "ZZQ" not in srv._terrain_quarantine, "an expired soft hold must self-release"


def test_a_future_expiry_still_blocks(monkeypatch):
    now = 1_790_000_000.0
    srv = _fresh_quarantine(monkeypatch, {"failures": 1, "reason": "x", "until_ts": now + 600.0})
    assert srv._terrain_quarantine_blocks("ZZQ", now) is True
    assert srv.terrain_quarantine_reason("ZZQ", now).endswith("next attempt in 600s")


def test_the_reason_string_admits_a_malformed_hold(monkeypatch):
    """The operator-facing line must say the hold has no expiry, not 'next attempt in 0s'."""
    srv = _fresh_quarantine(monkeypatch, {"failures": 3, "reason": "boom"})
    # TEST_SYSTEM_REHAB_V2: was `if msg: assert ...` where msg came from a call to
    # `_terrain_quarantine_reason` (with a leading underscore) -- a name that has
    # NEVER existed in server.py; the real function is `terrain_quarantine_reason`
    # (no underscore). `if msg:` made this silently skip its own assertion forever
    # (hasattr was always False, msg was always "") instead of failing on the typo --
    # zero coverage, not a passing check. Found only once the freshness/presence gap
    # itself was fixed and this line finally ran for real; corrected to the real name.
    assert hasattr(srv, "terrain_quarantine_reason"), (
        "terrain_quarantine_reason is gone; the malformed-hold message can't be checked")
    msg = srv.terrain_quarantine_reason("ZZQ", 1_790_000_000.0)
    assert msg, "a malformed hold (no until_ts) must produce a non-empty reason string"
    assert "NO expiry recorded" in msg or "malformed" in msg, msg




# ── the mission-scope wildcard control was removed with governance/pm_mission.json
#    (2026-08-24 Architecture A teardown): there is no mission file left to widen.
