"""RC-387 — the delta gate must FAIL a regression, or it is decoration.

The tool exists because tests an author writes only encode failure modes that author
already imagined. It would be self-refuting to ship it without a lock, and it was: the
Stop supervisor's ownership resolution found no owning suite for
tools/check_delta_adds_no_debt.py, which is what these controls repair.

The load-bearing property is asymmetry. A comparison that cannot fail is a rubber stamp —
the exact defect that produced four bad ledger closes earlier in the same session — so the
first control plants a regression and demands a FAIL.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# RC-368: declared direct owner of the tool under test.
TURN_AUDIT_OWNS = [
    "tools/check_delta_adds_no_debt.py",
    "tools/precommit_institutional.py",
]


def _load():
    spec = importlib.util.spec_from_file_location(
        "delta_gate", REPO / "tools" / "check_delta_adds_no_debt.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


GATE = _load()

BASE = {"root_cause_log": 71, "open_item_cap": 1}


def test_a_new_violation_fails_and_is_named():
    """THE PROPERTY: a check that appears on HEAD and not on base must fail, by name."""
    head = dict(BASE, checks_are_justified=1)
    added, improved = GATE.compare(BASE, head)
    assert added, "a brand-new enforced violation did not fail the delta gate"
    assert any("checks_are_justified" in a for a in added), added
    assert "0 -> 1" in added[0], added


def test_a_rise_in_an_existing_violation_also_fails():
    """Regressions arrive as +1 on an existing check as often as a new one."""
    added, _ = GATE.compare(BASE, dict(BASE, root_cause_log=72))
    assert added and "71 -> 72" in added[0], added


def test_unchanged_passes_and_improvement_passes():
    """It must not block ordinary work, or it gets switched off."""
    assert GATE.compare(BASE, dict(BASE)) == ([], [])
    added, improved = GATE.compare(BASE, dict(BASE, root_cause_log=27))
    assert added == []
    assert improved and "71 -> 27" in improved[0]


def test_a_preexisting_backlog_never_masks_a_fresh_regression():
    """The design decision that decides whether this tool survives contact.

    Base carries 72 violations; HEAD pays 44 of them AND adds one new check. A
    whole-number comparison would report a big net improvement and wave the regression
    through. Added must be reported on its own terms.
    """
    head = {"root_cause_log": 27, "open_item_cap": 1, "checks_are_justified": 1}
    added, improved = GATE.compare(BASE, head)
    assert sum(head.values()) < sum(BASE.values()), "precondition: HEAD is numerically better"
    assert added, "a regression was masked by a net-improved total"
    assert any("checks_are_justified" in a for a in added), added


def test_parser_reads_the_real_gate_output_shape():
    """Parsed from --enforced-only stdout; the separator glyph varies by console encoding."""
    for dash in ("-", "—"):
        text = (f"FAIL [root_cause_log] (ENFORCED) {dash} 71 violation(s):\n"
                f"FAIL [open_item_cap] (ENFORCED) {dash} 1 violation(s):\n"
                f"INSTITUTIONAL CORRECTNESS GATE: FAIL (72 enforced violation(s))")
        assert GATE.parse_counts(text) == {"root_cause_log": 71, "open_item_cap": 1}


def test_parser_ignores_passing_checks_and_summary_lines():
    text = ("PASS [venv_parity] (ENFORCED)\n"
            "INSTITUTIONAL CORRECTNESS GATE: FAIL (5 enforced violation(s))")
    assert GATE.parse_counts(text) == {}


def test_a_silent_or_crashed_gate_must_raise_not_report_zero(monkeypatch):
    """H1, the hole Cursor found: as first shipped this tool was FAIL-OPEN.

    enforced_counts ignored the return code and parse_counts("") is {}, so a crashed gate,
    an import error, or a changed output format rendered that side as ZERO violations —
    printing PASS and a fabricated 'PAID DOWN'. A lock that cannot tell CLEAN from SILENT
    is the RC-90 class. Each case below reproduces one way the gate can go quiet.
    """
    import subprocess as sp

    class FakeProc:
        def __init__(self, rc, out): self.returncode, self.stdout, self.stderr = rc, out, ""

    good = ("FAIL [root_cause_log] (ENFORCED) - 71 violation(s):\n"
            "INSTITUTIONAL CORRECTNESS GATE: FAIL (71 enforced violation(s))")
    cases = {
        "empty stdout (process died)": FakeProc(1, ""),
        "traceback, no banner": FakeProc(1, "Traceback (most recent call last):\nImportError"),
        "hard crash exit code": FakeProc(2, good),
        "output format changed": FakeProc(0, "FAIL [root_cause_log] 71 problems"),
    }
    for label, proc in cases.items():
        def fake_run(args, cwd=None, timeout=3600, _p=proc):
            if args[:2] == ["git", "worktree"] or args[:2] == ["git", "rev-parse"]:
                return sp.CompletedProcess(args, 0, "deadbeef\n", "")
            return _p
        monkeypatch.setattr(GATE, "_run", fake_run)
        try:
            GATE.enforced_counts("HEAD")
        except RuntimeError as exc:
            assert "silence is not cleanliness" in str(exc), (label, str(exc)[:200])
        else:
            raise AssertionError(f"{label}: a silent gate was reported as a clean count")


def test_a_completed_gate_with_zero_violations_is_still_accepted(monkeypatch):
    """Fail-closed must not mean fail-always: a genuinely clean run has the banner."""
    import subprocess as sp

    class FakeProc:
        def __init__(self): self.returncode, self.stdout, self.stderr = 0, (
            "INSTITUTIONAL CORRECTNESS GATE: PASS (enforced checks clean)"), ""

    def fake_run(args, cwd=None, timeout=3600):
        if args[:2] == ["git", "worktree"] or args[:2] == ["git", "rev-parse"]:
            return sp.CompletedProcess(args, 0, "deadbeef\n", "")
        return FakeProc()

    monkeypatch.setattr(GATE, "_run", fake_run)
    counts, sha = GATE.enforced_counts("HEAD")
    assert counts == {} and sha == "deadbeef"


def test_the_tool_measures_in_a_clean_worktree_not_the_dirty_tree():
    """A dirty tree carries scratch that is not the change — the source of the
    filtered-count error this tool exists to prevent."""
    src = (REPO / "tools" / "check_delta_adds_no_debt.py").read_text(encoding="utf-8")
    assert "worktree" in src and "--detach" in src, (
        "the gate must materialise both sides in clean detached worktrees")
    assert "worktree\", \"remove\"" in src or "'worktree', 'remove'" in src, (
        "the temporary worktree must be removed again")


def test_fail_banner_with_no_parseable_lines_is_not_clean():
    """Residual H1: banner FAIL (N) + empty parse used to compare as PAID DOWN."""
    text = "INSTITUTIONAL CORRECTNESS GATE: FAIL (4 enforced violation(s))"
    try:
        GATE.interpret_gate_output(1, text, "", "HEAD")
    except RuntimeError as exc:
        assert "no parseable" in str(exc), str(exc)
    else:
        raise AssertionError("FAIL banner with empty parse was treated as a clean count")


def test_fail_banner_empty_parse_does_not_compare_as_paid_down():
    """The exact hole: compare({root_cause_log:71}, {}) looked like 71→0 paid down."""
    try:
        empty = GATE.interpret_gate_output(
            1, "INSTITUTIONAL CORRECTNESS GATE: FAIL (71 enforced violation(s))",
            "", "HEAD")
    except RuntimeError:
        empty = None
    else:
        raise AssertionError(f"empty parse returned {empty} and would fake a pay-down")
    added, improved = GATE.compare({"root_cause_log": 71}, {})
    assert improved and "71 -> 0" in improved[0]
    # The compare itself is not the lock — interpret must refuse to produce {}.
    assert empty is None


def test_gate_shrink_is_not_an_improvement():
    """H3: dropping an ENFORCED check must be visible as a named removal."""
    assert GATE.parse_enforced_names(
        "CHECKS = [('keep', fn, True), ('drop', fn, True)]"
    ) == {"keep", "drop"}
    assert GATE.parse_enforced_names(
        "CHECKS = [('keep', fn, True), ('drop', fn, False)]"
    ) == {"keep"}
    assert GATE.parse_enforced_names("syntax error ((") == set()


def test_docstring_tokens_are_not_a_precommit_bind(tmp_path):
    """F4: a return-0 hook whose docstring names the tokens must still fail."""
    (tmp_path / "tools").mkdir()
    (tmp_path / "governance").mkdir()
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / "tools" / "precommit_institutional.py").write_text(
        '"""check_delta_adds_no_debt.py --staged origin/main return 2"""\n'
        "def main():\n    return 0\n",
        encoding="utf-8",
    )
    (tmp_path / "tools" / "check_delta_adds_no_debt.py").write_text(
        "def interpret_gate_output():\n    raise RuntimeError('no parseable')\n",
        encoding="utf-8",
    )
    (tmp_path / "governance" / "operator_grants.json").write_text(
        '{"grants":{"claude_no_verify_checkpoints":{"granted":false}}}',
        encoding="utf-8",
    )
    (tmp_path / ".github" / "workflows" / "delta-debt.yml").write_text(
        "run: python tools/check_delta_adds_no_debt.py\n# git show BASE\n",
        encoding="utf-8",
    )
    v = GATE.wiring_violations(tmp_path)
    assert any("does not invoke check_delta_adds_no_debt.py" in m for m in v), v
    assert any("does not pass --staged" in m for m in v), v


def test_relocated_script_still_grades_cwd_repo(tmp_path):
    """CI copies the grader out of tree; __file__ must not become the repo root."""
    import importlib.util
    src = (REPO / "tools" / "check_delta_adds_no_debt.py").read_text(encoding="utf-8")
    relocated = tmp_path / "delta_gate.py"
    relocated.write_text(src, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("relocated_delta", relocated)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.REPO.resolve() == REPO.resolve(), (
        f"relocated grader used {mod.REPO} instead of cwd toplevel {REPO}"
    )


def test_wiring_fails_a_true_grant_and_an_unwired_precommit(tmp_path):
    """Negative control for no_verify_cannot_hide_delta: inject the two escapes."""
    (tmp_path / "tools").mkdir()
    (tmp_path / "governance").mkdir()
    (tmp_path / "tools" / "precommit_institutional.py").write_text(
        "print('no delta')\n", encoding="utf-8")
    (tmp_path / "tools" / "check_delta_adds_no_debt.py").write_text(
        "print('no interpret')\n", encoding="utf-8")
    (tmp_path / "governance" / "operator_grants.json").write_text(
        '{"grants":{"claude_no_verify_checkpoints":{"granted":true}}}',
        encoding="utf-8")
    v = GATE.wiring_violations(tmp_path)
    assert v, "injected grant + unwired precommit produced no wiring violation"
    assert any("granted is true" in m for m in v), v
    assert any("does not invoke check_delta_adds_no_debt.py" in m for m in v), v


def test_wiring_is_clean_on_this_tree():
    """The live bind must currently hold, or the lock is already broken."""
    v = GATE.wiring_violations(REPO)
    assert v == [], v


def test_no_verify_cannot_hide_delta_fires_on_injected_grant(monkeypatch):
    """ENFORCED check name + injection: green-and-inert is the RC-95 class."""
    from tools.check_institutional_correctness import check_no_verify_cannot_hide_delta

    monkeypatch.setattr(
        "tools.check_delta_adds_no_debt.wiring_violations",
        lambda root: [
            "claude_no_verify_checkpoints.granted is true — --no-verify hides "
            "new enforced violations inside standing red (RC-389)"
        ],
    )
    v = check_no_verify_cannot_hide_delta()
    assert len(v) >= 1, v
    assert any("granted is true" in x.msg for x in v), v
    assert check_no_verify_cannot_hide_delta.__name__ == "check_no_verify_cannot_hide_delta"


def test_precommit_uses_delta_staged_and_fails_closed_without_origin_main(monkeypatch):
    """The hook must not be the absolute-zero path that forced --no-verify."""
    import tools.precommit_institutional as pc

    calls: list[list[str]] = []

    class Proc:
        def __init__(self, rc=0):
            self.returncode = rc
            self.stdout = "deadbeef\n"
            self.stderr = ""

    def fake_run(args, **_kw):
        calls.append(list(args))
        if args[:3] == ["git", "rev-parse", "--verify"]:
            return Proc(1)
        return Proc(0)

    monkeypatch.setattr(pc.subprocess, "run", fake_run)
    assert pc.main() == 2, "missing origin/main must be exit 2, not a pass"
    assert calls and calls[0][:3] == ["git", "rev-parse", "--verify"]


def test_precommit_invokes_delta_tool_when_origin_main_exists(monkeypatch):
    import tools.precommit_institutional as pc

    class Proc:
        def __init__(self, rc=0):
            self.returncode = rc
            self.stdout = "ok\n"
            self.stderr = ""

    seen = {}

    def fake_run(args, **_kw):
        if args[:3] == ["git", "rev-parse", "--verify"]:
            return Proc(0)
        seen["delta"] = list(args)
        return Proc(0)

    monkeypatch.setattr(pc.subprocess, "run", fake_run)
    assert pc.main() == 0
    joined = " ".join(seen["delta"])
    assert "check_delta_adds_no_debt.py" in joined
    assert "--staged" in seen["delta"]
    assert "--base" in seen["delta"] and "origin/main" in seen["delta"]
