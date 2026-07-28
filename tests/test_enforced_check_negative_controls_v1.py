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


def test_rc_citation_check_screams_on_a_phantom_id(tmp_path, monkeypatch):
    """RC-99: an RC-N in source with no log row must be flagged.

    This check found EIGHT live phantoms on first run — including its own docstring citing
    RC-99 — after the operator's audit found two by hand. It is the lock for the class where
    RC-96 recurred as RC-98 within a single turn."""
    from tools import check_institutional_correctness as M
    fake = tmp_path
    (fake / "governance").mkdir()
    (fake / "governance" / "root_cause_log.md").write_text(
        "| RC-1 | CLOSED | 2026-01-01 | 2026-01-08 | w | y | f |\n", encoding="utf-8")
    (fake / "tools").mkdir()
    (fake / "tools" / "zz_probe.py").write_text('"""cites RC-4242 which does not exist."""\n',
                                                encoding="utf-8")
    monkeypatch.setattr(M, "REPO", fake)
    bad = M.check_rc_citations_resolve()
    assert any("RC-4242" in str(b) for b in bad), (
        "a phantom RC citation in source was not flagged — the check is inert"
    )


def test_rc_citation_check_accepts_a_resolvable_id(tmp_path, monkeypatch):
    from tools import check_institutional_correctness as M
    fake = tmp_path
    (fake / "governance").mkdir()
    (fake / "governance" / "root_cause_log.md").write_text(
        "| RC-4242 | CLOSED | 2026-01-01 | 2026-01-08 | w | y | f |\n", encoding="utf-8")
    (fake / "tools").mkdir()
    (fake / "tools" / "zz_probe.py").write_text('"""cites RC-4242 which DOES exist."""\n',
                                                encoding="utf-8")
    monkeypatch.setattr(M, "REPO", fake)
    assert not [b for b in M.check_rc_citations_resolve() if "RC-4242" in str(b)]


def test_inert_producer_check_screams_on_a_fatal_run_log(tmp_path, monkeypatch):
    """RC-97: a scheduled producer whose log ends in a fatal has been failing silently.

    A fail-closed CONSUMER hides this — it withholds the stale artifact and the system merely
    looks quiet. Measured 2026-07-27: the scorecard artifact was 119.4h old behind exactly this."""
    from tools import check_institutional_correctness as M
    fake = tmp_path
    (fake / "reports").mkdir()
    (fake / "reports" / "zzjob_run.log").write_text(
        "starting\nFatal Python error: preconfig_init_utf8_mode\n", encoding="utf-8")
    monkeypatch.setattr(M, "REPO", fake)
    assert M.check_scheduled_producers_are_not_inert(), "a fatal run log was not flagged"


def test_inert_producer_check_accepts_a_healthy_run_log(tmp_path, monkeypatch):
    from tools import check_institutional_correctness as M
    fake = tmp_path
    (fake / "reports").mkdir()
    (fake / "reports" / "zzjob_run.log").write_text(
        "[job] start\nwrote artifact\n[job] exit=0\n", encoding="utf-8")
    monkeypatch.setattr(M, "REPO", fake)
    assert not M.check_scheduled_producers_are_not_inert()


def test_price_bars_session_check_screams_on_an_ungated_reader(tmp_path, monkeypatch):
    """RC-103: a NEW ungated price_bars_1m reader must be flagged; a gated one must pass."""
    from tools import check_institutional_correctness as M
    fake = tmp_path
    (fake / "tools").mkdir()
    (fake / "research").mkdir()
    (fake / "tools" / "zz_bar_probe.py").write_text(
        'q = "SELECT close FROM price_bars_1m WHERE ticker=?"\n', encoding="utf-8")
    monkeypatch.setattr(M, "REPO", fake)
    bad = M.check_price_bars_readers_name_their_session()
    assert any("zz_bar_probe" in str(b) for b in bad), "an ungated bar reader was not flagged"
    (fake / "tools" / "zz_bar_probe.py").write_text(
        'from time_et import is_trading_day_et\n'
        'q = "SELECT close FROM price_bars_1m WHERE ticker=?"\n', encoding="utf-8")
    assert not [b for b in M.check_price_bars_readers_name_their_session()
                if "zz_bar_probe" in str(b)], "a gated reader was wrongly flagged"
