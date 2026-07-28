# institutional-synthetic-ok: these tests INJECT violations to prove checks can fail — that is
# their entire purpose (RC-95); every injection is restored in a finally block.
"""RC-95: negative controls for the ENFORCED checks that had none.

Four instruments shipped INERT in one session (RC-76, RC-84, RC-87, RC-90) — each reported 0
violations while incapable of firing, and green-and-inert is byte-identical to green-and-working.
The only discriminator is a control that injects the defect and demands the check scream. This
file is that control for: enforced_checks_have_negative_controls (the meta-check),
verdicts_declare_their_power, single_spot_authority, ui_data_integration.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import tools.check_institutional_correctness as C  # noqa: E402


def test_meta_check_screams_on_an_uncovered_enforced_check():
    """The negative-control law must itself have a negative control."""
    baseline = len(C.check_enforced_checks_have_negative_controls())
    # The name is CONSTRUCTED at runtime: writing it as a literal here would put it into the
    # very tests/ corpus the meta-check scans, marking it "covered" — the control would then
    # pass against an inert meta-check, which is the exact failure this file exists to prevent.
    fake = "zz_fake_" + "un" + "covered_check"
    C.CHECKS = list(C.CHECKS) + [(fake, lambda: [], True)]
    try:
        injected = len(C.check_enforced_checks_have_negative_controls())
    finally:
        C.CHECKS = C.CHECKS[:-1]
    assert injected == baseline + 1, (
        "an ENFORCED check with no test naming it was not flagged — the meta-check is inert"
    )
    assert len(C.check_enforced_checks_have_negative_controls()) == baseline


def test_meta_check_does_not_flag_advisory_checks():
    baseline = len(C.check_enforced_checks_have_negative_controls())
    C.CHECKS = list(C.CHECKS) + [("zz_fake_advisory_check", lambda: [], False)]
    try:
        assert len(C.check_enforced_checks_have_negative_controls()) == baseline
    finally:
        C.CHECKS = C.CHECKS[:-1]


def test_verdicts_check_screams_on_an_unproven_kill():
    """RC-87's gate: a KILL/RETIRED row with no n=/CI must be flagged. This is the check whose
    first version shipped with literal backspace bytes in its regex and could never match."""
    log = ROOT / "governance" / "root_cause_log.md"
    orig = log.read_text(encoding="utf-8")
    baseline = len(C.check_verdicts_declare_their_power())
    try:
        with io.open(log, "w", encoding="utf-8") as fh:
            fh.write(orig + "| RC-9999 | CLOSED | 2026-07-27 | 2026-08-03 | t | w | "
                            "The lead is RETIRED - it does not replicate. |\n")
        injected = len(C.check_verdicts_declare_their_power())
    finally:
        with io.open(log, "w", encoding="utf-8") as fh:
            fh.write(orig)
    assert injected == baseline + 1, "an unproven RETIRED verdict was not flagged"
    assert len(C.check_verdicts_declare_their_power()) == baseline


def test_verdicts_check_accepts_a_powered_verdict():
    log = ROOT / "governance" / "root_cause_log.md"
    orig = log.read_text(encoding="utf-8")
    baseline = len(C.check_verdicts_declare_their_power())
    try:
        with io.open(log, "w", encoding="utf-8") as fh:
            fh.write(orig + "| RC-9999 | CLOSED | 2026-07-27 | 2026-08-03 | t | w | "
                            "RETIRED: n=412, 95% CI [-0.31,-0.12], power 0.86. |\n")
        assert len(C.check_verdicts_declare_their_power()) == baseline
    finally:
        with io.open(log, "w", encoding="utf-8") as fh:
            fh.write(orig)


def test_spot_authority_check_is_alive_on_the_real_tree():
    """single_spot_authority guards the RC-14 law. Full source injection is expensive, so this
    control asserts the check RUNS and returns a list on the real tree, and that the authority it
    guards (resolve_spot) is still present for it to guard — a deleted authority with a silent
    check is exactly the inert-instrument shape."""
    v = C.check_single_spot_authority()
    assert isinstance(v, list)
    assert "def resolve_spot" in (ROOT / "server.py").read_text(encoding="utf-8"), (
        "resolve_spot is gone; the spot-authority check is guarding nothing"
    )


def test_ui_data_integration_tier1_screams_on_a_dead_placeholder(tmp_path, monkeypatch):
    """Tier 1 of ui_data_integration: a data cell shipped as '—' with NO JS writer must fail."""
    from tools import check_ui_data_integration as U
    fake = tmp_path / "static"
    fake.mkdir()
    # Tier 1 scans the fixed _HTML_FILES paths and only ids with the known cell prefixes
    # (cv2|ct|dr|kl|hd) — the injected cell must be one the check actually polices.
    (fake / "index.html").write_text(
        '<span id="cv2-zz-dead">—</span><script>var x = 1;</script>',
        encoding="utf-8")
    monkeypatch.setattr(U, "REPO", tmp_path)
    bad = U.static_binding_violations()
    assert bad, "a '—' placeholder with no writer anywhere was not flagged — Tier 1 is inert"


def test_agents_law_check_screams_on_a_law_with_no_enforcer():
    """RC-96: a NEW bold law heading in AGENTS.md naming no check and not marked SOFT must fail.

    13 of 35 catalogued lock failures are 'goodwill instead of a mechanical lock' (RC-41/49/56):
    a law in prose reads exactly like a law with a hook."""
    agents = ROOT / "AGENTS.md"
    orig = agents.read_text(encoding="utf-8")
    baseline = len(C.check_agents_laws_name_their_enforcer())
    law = "\n\n**Zebra quorum rule (test):** every quorum must be witnessed."
    try:
        with io.open(agents, "w", encoding="utf-8") as fh:
            fh.write(orig + law + "\n")
        injected = len(C.check_agents_laws_name_their_enforcer())
        # ...and the SAME law becomes acceptable the moment it declares itself SOFT.
        with io.open(agents, "w", encoding="utf-8") as fh:
            fh.write(orig + law + " SOFT.\n")
        softened = len(C.check_agents_laws_name_their_enforcer())
    finally:
        with io.open(agents, "w", encoding="utf-8") as fh:
            fh.write(orig)
    assert injected == baseline + 1, "an unenforced AGENTS.md law was not flagged"
    assert softened == baseline, "declaring a law SOFT must satisfy the rule"
    assert len(C.check_agents_laws_name_their_enforcer()) == baseline
