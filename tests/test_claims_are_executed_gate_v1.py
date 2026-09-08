"""RC-298 — negative control for the `test_claims_are_executed` enforced check.

THE DEFECT IT GUARDS. tests/test_charm_docstring_states_the_physics_v1.py, as shipped under
RC-294, contained eight assertions and every one read `assert "<a sentence I wrote>" in
DOC`. It confirmed only that the text had been written. The claim it locked — "calls sell,
puts buy" — was FALSE and the suite was green, because a string match cannot disagree with
the string. One call refuted it: `math_levels.bs_charm` takes no call/put argument, and its
sign tracks moneyness. RC-281 and RC-290 are the same shape.

WHAT THIS FILE PROVES. That the checker FIRES on the defect and does not fire on a healthy
file. A gate nobody has attacked is green-and-inert; these are the injected violations.

Note the shape of these tests: every one CALLS `analyse`/`violations` and asserts on the
returned value. A prose-only negative control for a prose-only checker would be the joke
that writes itself.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import check_test_claims_are_executed as C  # noqa: E402

# The RC-294 file, reconstructed: assertions about text, nothing executed.
PROSE_ONLY = '''
import inspect
from foo import bar
DOC = inspect.getdoc(bar)
def test_a():
    assert "SHORT call" in DOC
def test_b():
    assert "SELL stock" in DOC
def test_c():
    assert "BUY stock" in DOC
'''

# The RC-296 replacement: reads text AND runs the subject.
MIXED = '''
import inspect
from math_levels import bs_charm
DOC = inspect.getdoc(bs_charm)
def test_a():
    assert "moneyness" in DOC
def test_b():
    assert "side-independent" in DOC
def test_c():
    assert "OI IMBALANCE" in DOC
def test_runs_it():
    below = bs_charm(100.0, 90.0, 0.08, 0.20, 0.0)
    above = bs_charm(100.0, 105.0, 0.08, 0.20, 0.0)
    assert below > 0 > above
'''


def test_the_checker_fires_on_a_prose_only_file():
    """The injected violation. If this passes silently the gate is inert."""
    prose, calls = C.analyse(ast.parse(PROSE_ONLY))
    assert prose >= 3, f"the prose assertions were not counted: {prose}"
    assert calls == 0, f"a subject call was miscounted in a prose-only file: {calls}"


def test_the_checker_accepts_a_file_that_runs_the_subject():
    """The positive control: text assertions stay legal when the file also executes."""
    prose, calls = C.analyse(ast.parse(MIXED))
    assert prose >= 3
    assert calls > 0, "calling bs_charm was not recognised as exercising the subject"


def test_a_call_outside_the_assert_still_counts():
    """The false positive the first prototype produced, pinned so it cannot return.

    tests/test_pred_1c_horizon_persistence_v1.py calls the subject and THEN asserts on the
    result. Requiring the call inside the assert expression flagged five healthy files.
    """
    src = '''
import inspect
from foo import build
DOC = inspect.getdoc(build)
def test_a():
    assert "x" in DOC
def test_b():
    assert "y" in DOC
def test_c():
    assert "z" in DOC
def test_d():
    d = build(1, 2)
    assert d["k"] == 3
'''
    prose, calls = C.analyse(ast.parse(src))
    assert calls > 0, "a subject call placed before the assertion was not counted"


def test_a_prose_only_file_cannot_hide_behind_a_local_name_or_helper():
    """RC-317 (independent audit, fixed 2026-08-25): the gate's founding bypass.

    Text bound to a local the fixed name list never heard of, through a helper call,
    scored (0 prose, 1 subject) and PASSED the enforced lane — the exact shape RC-317
    recorded and re-executed. Taint now follows the assignment (`blob` is file text) and
    a helper whose arguments carry that taint is a text transform, not subject execution.
    """
    src = '''
import inspect
import math_levels
def _norm(s):
    return " ".join(s.split())
def test_a():
    blob = _norm(inspect.getdoc(math_levels.bs_charm))
    assert "calls sell" in blob
    assert "puts buy" in blob
    assert "sign" in blob
'''
    prose, calls = C.analyse(ast.parse(src))
    assert prose >= 3, f"tainted-local prose assertions were not counted: {prose}"
    assert calls == 0, f"a text-transform helper was miscounted as subject execution: {calls}"


def test_builtins_do_not_count_as_exercising_the_subject():
    """`len(...)` in an assertion is not evidence the code under test ran."""
    src = '''
import inspect
from foo import bar
SRC = inspect.getsource(bar)
def test_a():
    assert "a" in SRC
def test_b():
    assert "b" in SRC
def test_c():
    assert len(SRC) > 0
'''
    prose, calls = C.analyse(ast.parse(src))
    assert calls == 0, "a builtin was mistaken for exercising the subject"


def test_the_live_repository_passes_on_merit():
    """Zero offenders and zero exemptions consumed — the reason this is ENFORCED, not ratcheted."""
    assert C.violations() == [], f"prose-only test files present: {C.violations()}"
    assert len(C.TEXT_ONLY_ALLOWED) <= 3, (
        "the text-only allowlist is growing; each entry silences a file that cannot detect "
        "a false claim, which is the RC-276 file-exemption habit returning")


def test_every_allowlist_entry_states_a_reason():
    for path, reason in C.TEXT_ONLY_ALLOWED:
        assert path and reason and len(reason) > 20, (
            f"{path} is exempt without a real reason — RC-281 is what unverified reasons do")


def test_the_gate_is_registered_as_enforced():
    """A rule nobody calls is a comment."""
    src = (REPO / "tools" / "check_institutional_correctness.py").read_text(
        encoding="utf-8", errors="replace")
    # BEDROCK PR B (2026-09-06): the eight test-hygiene lints are ONE registered check,
    # `test_hygiene`; this predicate runs inside it, unchanged.
    assert '("test_hygiene", check_test_hygiene, True)' in src, (
        "test_hygiene is not registered ENFORCED in the institutional gate")
    import tools.check_institutional_correctness as gate
    import inspect
    assert "check_test_claims_are_executed" in inspect.getsource(gate.check_test_hygiene), (
        "test_hygiene no longer runs the claims-are-executed predicate")
