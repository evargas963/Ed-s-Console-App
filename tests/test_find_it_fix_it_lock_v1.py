"""FIND IT → FIX IT lock (operator law 2026-08-21; corrected RC-473) — disposition-driven controls.

Enforcer: tools/check_institutional_correctness.check_find_it_fix_it, backed by the shared
`active_defect_offenders` authority that tools/stop_guard.py also calls. Every active material
defect (status FAIL/NOT_PROVEN in governance/active_defects.json) must be terminally disposed
REMEDIATED (resolvable rc + cited command) or BLOCKED (valid blocker TYPE bound to an EXACT
snake_case assertion WITH the machine-resolvable evidence that type requires). Anything else BLOCKS.

The lock is NOT proven by its positive path passing; these controls prove it fails as designed.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.check_institutional_correctness import (  # noqa: E402
    active_defect_offenders,
    check_find_it_fix_it,
)

# A real RC id that resolves in the live log with a FIXED row (used for the PASS controls).
_REAL_FIXED_RC = "RC-448"
_RC_LOG = (ROOT / "governance" / "root_cause_log.md").read_text(encoding="utf-8", errors="ignore")


def _ledger(defect: dict) -> dict:
    return {"mission": "TEST", "defects": [defect]}


def _off(defect: dict):
    return active_defect_offenders(_ledger(defect), _RC_LOG)


def test_bare_active_FAIL_no_words_no_blocker_blocks():
    # DEFECT 1/2: a bare FAIL with NO laundering vocabulary and NO blocker must BLOCK.
    assert _off({"id": "D1", "status": "FAIL", "disposition": "OPEN",
                 "concept": "material defect remains unresolved"}), "bare FAIL must block"


def test_bare_active_NOT_PROVEN_blocks():
    assert _off({"id": "D2", "status": "NOT_PROVEN", "disposition": "OPEN"}), "NOT_PROVEN must block"


def test_defect_opened_yesterday_still_blocks():
    # DEFECT 3: no date window — an old undisposed active defect still blocks.
    assert _off({"id": "D3", "status": "FAIL", "disposition": "OPEN",
                 "opened": "2026-01-01"}), "an earlier-day active defect must still block"


def test_missing_or_malformed_ledger_fails_closed():
    # DEFECT 4/9: a missing/malformed ledger cannot prove absence of defects → BLOCK.
    assert active_defect_offenders({}, _RC_LOG)
    assert active_defect_offenders({"defects": "not a list"}, _RC_LOG)


def test_FIXED_word_without_evidence_blocks():
    # DEFECT 6: REMEDIATED needs a resolvable rc + a cited command — a word is not proof.
    assert _off({"id": "D5", "status": "FAIL", "disposition": "REMEDIATED"}), "no evidence must block"
    assert _off({"id": "D5", "status": "FAIL", "disposition": "REMEDIATED",
                 "remediation": {"rc": "RC-999999", "command": "pytest"}}), "unresolvable rc must block"
    assert _off({"id": "D5", "status": "FAIL", "disposition": "REMEDIATED",
                 "remediation": {"rc": _REAL_FIXED_RC, "command": ""}}), "no command must block"


def test_fake_exact_looking_RTH_blocker_with_nonexistent_probe_blocks():
    # DEFECT 5: a pretty sentence is not proof — the RTH probe file must EXIST on disk.
    assert _off({"id": "D6", "status": "FAIL", "disposition": "BLOCKED",
                 "blocker": {"type": "RTH_ONLY", "assertion": "same_ms_collision_frequency",
                             "probe": "tools/does_not_exist_probe.py",
                             "non_rth_remediation_complete": True}}), "nonexistent probe must block"


def test_RTH_blocker_with_probe_but_unfinished_remediation_blocks():
    # DEFECT 5: non-RTH remediation must be complete before RTH_ONLY is accepted.
    assert _off({"id": "D7", "status": "FAIL", "disposition": "BLOCKED",
                 "blocker": {"type": "RTH_ONLY", "assertion": "same_ms_collision_frequency",
                             "probe": "tools/stop_guard.py",  # a real file, standing in for the probe
                             "non_rth_remediation_complete": False}}), "unfinished non-RTH work must block"


def test_subsystem_wide_blocker_blocks():
    # DEFECT 3-scope: a subsystem-wide assertion launders a whole area.
    assert _off({"id": "D8", "status": "FAIL", "disposition": "BLOCKED",
                 "blocker": {"type": "EXTERNAL_DATA_UNAVAILABLE", "assertion": "order_flow",
                             "capability": "x"}}), "subsystem-wide blocker must block"


def test_valid_completed_remediation_passes():
    # PASS: REMEDIATED with a resolvable rc + a cited command.
    assert _off({"id": "D9", "status": "FAIL", "disposition": "REMEDIATED",
                 "remediation": {"rc": _REAL_FIXED_RC,
                                 "command": ".venv/Scripts/python.exe -m pytest -q"}}) == []


def test_genuinely_validated_exact_blocker_passes_for_that_assertion_only():
    # PASS: an exact assertion that genuinely needs RTH, probe exists, non-RTH work complete.
    assert _off({"id": "D10", "status": "FAIL", "disposition": "BLOCKED",
                 "blocker": {"type": "RTH_ONLY", "assertion": "same_ms_collision_frequency",
                             "probe": "tools/stop_guard.py",
                             "non_rth_remediation_complete": True}}) == []
    # EXTERNAL with a named capability passes.
    assert _off({"id": "D11", "status": "NOT_PROVEN", "disposition": "BLOCKED",
                 "blocker": {"type": "EXTERNAL_DATA_UNAVAILABLE", "assertion": "oos_outcome_labels",
                             "capability": "labeled forward-outcome dataset not present in repo"}}) == []


def test_live_repo_is_clean_so_the_check_is_enforceable():
    # An ENFORCED check must be zero on the current repo.
    assert check_find_it_fix_it() == [], f"live active_defects must be all-disposed to enforce: {check_find_it_fix_it()}"


def test_stop_guard_uses_the_same_authority_as_the_gate():
    # DEFECT 8-parity: Claude-time (Stop) and CI must enforce ONE definition.
    import tools.stop_guard as sg

    src = Path(sg.__file__).read_text(encoding="utf-8")
    assert "active_defect_offenders" in src
    assert "load_active_defects" in src
    # DEFECT 8: repeat Stop still evaluates fix-law (not exempted by stop_hook_active).
    assert "if stop_active:" in src and "fix_law_blockers()" in src
    # DEFECT 9: unreadable payload does not wave through.
    assert "payload = {}" in src


def test_mutation_removing_a_status_check_is_detected():
    # If the authority stopped treating OPEN FAIL as an offender, this would go empty — it must not.
    assert active_defect_offenders(
        {"defects": [{"id": "M", "status": "FAIL", "disposition": "OPEN"}]}, _RC_LOG)
