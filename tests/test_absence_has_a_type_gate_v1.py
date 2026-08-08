"""RC-301 — negative control for the `absence_has_a_type` enforced check.

THE CLASS IT GUARDS. `absence-coerced-to-a-value`, found SEVEN times in three days:
RC-274 (NULL close summed as 0 dollars), RC-277 (my own regression), RC-282 (undated bundle
published age 0.0 and read FRESH), RC-284 (a timed-out run reported as "tests failed"),
RC-285 (an unscored model published edge 0), RC-289 (a stale artefact rendered as current),
RC-301 (a parity residual of 0.0 asserting the forward equals spot). Six repairs fixed
values; none removed the ability to write the shape.

WHERE IT LIVES. Not in an expression — `no_fake_defaults` already matches those — but in the
RETURN TYPE. `-> float` declares absence inexpressible, so `return 0.0` in an except handler
presents as the only way to honour the signature.

Every test here CALLS the checker and asserts on what it returns (RC-298).
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))

import check_absence_has_a_type as C  # noqa: E402

FABRICATES = '''
def rate() -> float:
    try:
        return compute()
    except Exception:
        return 0.0
'''

HONEST_OPTIONAL = '''
def rate() -> float | None:
    try:
        return compute()
    except Exception:
        return None
'''

MARKED = '''
def rate() -> float:
    try:
        return compute()
    except Exception:
        return 0.0  # absence-ok: the caller guarantees a value; zero is unreachable here
'''

BARE_MARKER = '''
def rate() -> float:
    try:
        return compute()
    except Exception:
        return 0.0  # absence-ok:
'''

PREDICATE = '''
def is_ready() -> bool:
    try:
        return check()
    except Exception:
        return False
'''

EXIT_CODE = '''
def main() -> int:
    try:
        return run()
    except Exception:
        return 2
'''


def _hits(src: str, tmp_path: Path) -> list:
    p = tmp_path / "m.py"
    p.write_text(src, encoding="utf-8")
    return C.fabricated_absence_returns(p)


def test_it_fires_on_a_fabricated_float(tmp_path):
    """The injected violation. If this passes silently the gate is inert."""
    assert _hits(FABRICATES, tmp_path), "a fabricated 0.0 measurement was not flagged"


def test_an_optional_return_is_accepted(tmp_path):
    """The honest form — the type can say 'no answer'."""
    assert _hits(HONEST_OPTIONAL, tmp_path) == []


def test_a_marker_with_a_reason_suppresses(tmp_path):
    assert _hits(MARKED, tmp_path) == []


def test_a_marker_without_a_reason_does_not_suppress(tmp_path):
    """RC-281: a marker you can type without saying anything is an allowlist per line."""
    assert _hits(BARE_MARKER, tmp_path), "a reasonless absence-ok marker suppressed"


def test_a_predicate_returning_false_is_not_flagged(tmp_path):
    """False IS the answer for a predicate. The 78-to-2 prototype turned on this."""
    assert _hits(PREDICATE, tmp_path) == []


def test_a_cli_exit_code_is_not_flagged(tmp_path):
    """`main() -> int` returning 2 is a process result, not a measurement."""
    assert _hits(EXIT_CODE, tmp_path) == []


def test_the_live_repository_passes_on_merit():
    assert C.violations() == [], f"fabricated absence in the money path: {C.violations()}"


def test_the_parity_function_now_reports_absence():
    """The RC-301 repair, executed rather than read."""
    from math_levels import parity_f_minus_spot_from_contracts as P

    assert P([], spot="abc") is None, "unparseable spot still yields a residual"
    assert P([], spot=100.0) is None, "an empty chain still yields a residual"


def test_the_gate_is_registered_as_enforced():
    src = (REPO / "tools" / "check_institutional_correctness.py").read_text(
        encoding="utf-8", errors="replace")
    assert '("absence_has_a_type", check_absence_has_a_type, True)' in src
