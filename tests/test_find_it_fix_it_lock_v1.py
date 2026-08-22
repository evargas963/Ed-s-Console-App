"""FIND IT → FIX IT lock (operator law 2026-08-21) — negative/positive controls + parity.

Enforcer: tools/check_institutional_correctness.check_find_it_fix_it, backed by the shared
`fix_law_offenders` authority that tools/stop_guard.py also calls. A fixable material defect
discovered this session must be REMEDIATED or attached to a VALID hard blocker on an EXACT
assertion — never queued/recorded/TODO/next/pending/pre-existing/out-of-scope or left unfinished.

The lock is NOT proven by its positive path passing; these controls prove it fails as designed.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.check_institutional_correctness import (  # noqa: E402
    check_find_it_fix_it,
    fix_law_offenders,
)

TODAY = "2026-08-21"


def _row(fix: str, *, status: str = "OPEN", opened: str = TODAY, rc: str = "RC-999"):
    return [(rc, status, opened, fix)]


def test_control_A_fail_with_no_blocker_blocks():
    # A material defect disposed as fixable-but-unfixed with blocker = NONE → BLOCK.
    offs = fix_law_offenders(_row("defect found; queued for the next mission"), TODAY)
    assert offs, "a fixable defect with no hard blocker must be an offender"
    assert "no valid hard blocker" in offs[0][1].lower()


def test_control_B_broad_fake_RTH_blocks():
    # Same item laundered with a broad subsystem-wide RTH_ONLY while non-RTH work remains → BLOCK.
    offs = fix_law_offenders(_row("blocked: ORDER_FLOW = RTH_ONLY"), TODAY)
    assert offs, "a subsystem-wide blocker must not launder a fixable defect"
    assert "exact assertion" in offs[0][1].lower()


def test_control_C_exact_assertion_blocker_accepted():
    # A precise assertion that genuinely needs RTH, after non-RTH work is complete → accepted.
    offs = fix_law_offenders(
        _row("all non-RTH remediation done; same_ms_collision_frequency = RTH_ONLY "
             "with prepared probe tools/rth_probe.py"), TODAY)
    assert offs == [], f"an exact-assertion hard blocker must be accepted, got {offs}"


def test_control_D_discovery_only_log_entry_blocks():
    # A newly discovered defect with only a tracking/log word and no remediation → BLOCK.
    for word in ("recorded for follow-up", "TODO fix later", "left for next turn", "pre-existing"):
        offs = fix_law_offenders(_row(f"new material defect; {word}"), TODAY)
        assert offs, f"discovery-only disposition {word!r} must block"


def test_control_E_completed_remediation_passes():
    # The same defect with complete remediation evidence → accepted for this law.
    offs = fix_law_offenders(
        _row("FIXED: removed the leg; VERIFIED 462 tests pass, ruff clean"), TODAY)
    assert offs == [], f"a FIXED+evidence row must pass this law, got {offs}"


def test_only_todays_open_rows_are_in_scope():
    # Earlier-day rows are a dated backlog governed by check_open_item_cap, not this session lock.
    assert fix_law_offenders(_row("queued", opened="2026-01-01"), TODAY) == []
    assert fix_law_offenders(_row("queued", status="CLOSED"), TODAY) == []


def test_next_depth_field_is_not_laundering():
    # NEXT-DEPTH is the RC log's legitimate successor-bet field; a FIXED row that names it must pass.
    offs = fix_law_offenders(
        _row("FIXED: collapsed authority; VERIFIED. NEXT-DEPTH: UI wiring is the next mission slice"),
        TODAY)
    assert offs == [], f"NEXT-DEPTH on a FIXED row must not trip the lock, got {offs}"


def test_live_repo_is_clean_so_the_check_is_enforceable():
    # An ENFORCED check must be zero on the current repo; this pins that invariant.
    assert check_find_it_fix_it() == [], "the live RC log must satisfy FIND IT → FIX IT to enforce"


def test_mutation_of_the_authority_is_detected():
    # Planting a genuine offender into the parsed rows must be caught — the lock has teeth.
    planted = fix_law_offenders(_row("material FAIL; will fix in a later mission"), TODAY)
    assert planted, "mutation: a fixable defect declared for 'a later mission' must be caught"


def test_stop_guard_uses_the_same_authority_as_the_gate():
    # Claude-time (Stop) and CI must enforce ONE definition: stop_guard imports fix_law_offenders.
    import tools.stop_guard as sg

    src = Path(sg.__file__).read_text(encoding="utf-8")
    assert "fix_law_offenders" in src, "stop_guard must call the shared fix_law_offenders authority"
    assert "fix_law_blockers" in src
