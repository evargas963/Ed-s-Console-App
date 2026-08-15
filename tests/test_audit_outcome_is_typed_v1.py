"""RC-284 — the audit must be able to say "I did not measure".

WHAT CURSOR MEASURED. `tools/turn_self_audit.py:_run` wrapped every subprocess in
`except (OSError, subprocess.SubprocessError)` and returned `1, "RUN FAILED: ..."`.
`subprocess.TimeoutExpired` IS a `SubprocessError`, so a timed-out run and a failed test
run both arrived as exit 1, and both became the single string `attack suites failed`.
Repository log: 15 records carry an 1800s timeout, every one reading
`step_exit=1, verdict='fail', fails=['attack suites failed']`.

I HIT THIS TWICE ON 2026-08-07. The audit matched 181 suites because db.py and
ml_data_common.py are imported nearly everywhere, blew the ceiling, and told me my tests
had failed. They had not — re-running the same 181 suites directly gave 23 failed / 2307
passed, none of them mine.

WHY IT BELONGS TO THIS SESSION'S ROOT. Absence had no representation, so it was coerced
into the nearest available value. A NULL close became 0 dollars (RC-274). An undated
bundle became age 0.0 and read FRESH (RC-282). A run that produced no result became a
result that says FAILED. This one is the worst place for the class to live, because it is
the instrument that judges every other fix.

A timeout must still FAIL the turn — an unmeasured turn is not a clean one. What must
change is that the record stops asserting a measurement it never obtained.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import turn_self_audit as A  # noqa: E402


def test_a_timeout_is_not_reported_as_a_failure():
    """The defect, driven directly: a process that outlives its budget."""
    code, out, outcome = A._run(
        [sys.executable, "-c", "import time; time.sleep(30)"], timeout=1)
    assert outcome == A.OUTCOME_TIMEOUT, f"a timeout reported as {outcome!r}"
    assert code != 0, "a timeout must not read as success"
    assert "TIMED OUT" in out and "nothing was measured" in out.lower()


def test_a_launch_failure_is_its_own_outcome():
    """A command that cannot start produced no test result either."""
    _code, _out, outcome = A._run(["definitely_not_a_real_binary_rc284"], timeout=10)
    assert outcome == A.OUTCOME_LAUNCH_FAILURE, f"got {outcome!r}"


def test_an_ordinary_failure_is_still_an_ordinary_failure():
    """The negative control: typing the outcome must not blunt real failures."""
    code, _out, outcome = A._run([sys.executable, "-c", "raise SystemExit(3)"], timeout=30)
    assert outcome == A.OUTCOME_OK, "a process that ran and exited nonzero DID measure"
    assert code == 3


def test_success_is_success():
    code, out, outcome = A._run([sys.executable, "-c", "print('rc284-ok')"], timeout=30)
    assert (code, outcome) == (0, A.OUTCOME_OK)
    assert "rc284-ok" in out


def test_the_three_outcomes_are_distinct():
    assert len({A.OUTCOME_OK, A.OUTCOME_TIMEOUT, A.OUTCOME_LAUNCH_FAILURE}) == 3


def test_timeout_expired_is_caught_before_the_generic_handler():
    """Ordering matters: TimeoutExpired IS a SubprocessError, so a generic
    `except SubprocessError` placed first silently reclaims it and the type is lost again."""
    import inspect

    src = inspect.getsource(A._run)
    assert src.index("except subprocess.TimeoutExpired") < src.index(
        "except (OSError, subprocess.SubprocessError)"), (
        "the generic handler is catching timeouts again — TimeoutExpired is a subclass")
    assert issubclass(subprocess.TimeoutExpired, subprocess.SubprocessError), (
        "premise changed; re-derive the ordering requirement")


def test_the_verdict_text_distinguishes_the_three_cases():
    """The ledger is the artefact; a human-readable tail is not a structured record."""
    import inspect

    src = inspect.getsource(A.main) if hasattr(A, "main") else Path(
        REPO / "tools" / "turn_self_audit.py").read_text(encoding="utf-8")
    assert "TIMED OUT after 1800s" in src
    assert "NOTHING was measured" in src
    assert "could not be LAUNCHED" in src
    assert '"outcome": outcome' in src, "the step record carries no typed outcome"


def test_a_timeout_still_fails_the_turn():
    """Distinguishing a timeout must not downgrade it to a pass."""
    src = (REPO / "tools" / "turn_self_audit.py").read_text(encoding="utf-8")
    i = src.find("if outcome == OUTCOME_TIMEOUT:")
    assert i > 0
    assert "fails.append" in src[i:i + 300], (
        "a timeout no longer fails the turn — an unmeasured turn is not a clean one")
