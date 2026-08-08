"""RC-299 — negative control for the RECURSIVE five-why lock.

WHAT WAS MISSING. The existing lock required the literal token ROOT in a why-chain, that
any `RC-\\d+` it cited resolved, and that the chain was >= 5 levels deep. None of those asks
whether the ROOT is IRREDUCIBLE. A chain could therefore name a NEW DEFECT at why-2, -3 or
-4 and keep going in prose, and nothing fired.

MEASURED on my own work: RC-298's why-4 states that the RC-49 co-staged-test gate ACCEPTS a
prose-only file as a lock — a distinct defect in a different control — and I spawned no row
for it. The lock stayed silent because RC-49 exists. The log's own law, quoted in
`check_root_cause_log`'s docstring, is "a cause found at why-2 is not the root — it is a new
defect that gets its own five whys", and that sentence had never been machine-checked.

THE RULE (operator, 2026-08-08, non-negotiable): a chain must end
`ROOT: TERMINAL — <why it is irreducible>` or `ROOT: SPAWNS RC-nnn — <the child defect>`,
and a spawned child must have its own row, which the dangling-reference rule then subjects
to the same requirement. Recursive by construction: at the terminus the author either
justifies bedrock or names the child, with no third option to drift into.

Every test here CALLS the validator and asserts on what it returns (RC-298).
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.check_institutional_correctness import (  # noqa: E402
    FIVE_WHY_RECURSION_CUTOVER,
    _five_why_lock_violations,
)

_HDR = "| id | status | opened | due | defect | why | fix |"
_SEP = "|---|---|---|---|---|---|---|"


def _row(rc: str, why: str, *, opened: str = "2026-08-09", status: str = "OPEN") -> str:
    fix = "FIXED: END-TO-END producer -> consumer; VIOLATION: none. TIGHTENED: none."
    return f"| {rc} | {status} | {opened} | 2026-08-20 | a defect | {why} | {fix} |"


def _run(rows: list[str]):
    return _five_why_lock_violations([_HDR, _SEP, *rows], REPO / "governance" / "x.md", "", "")


def _msgs(rows: list[str]) -> str:
    return " ".join(v.msg for v in _run(rows))


CHAIN = "(1) a -> (2) b -> (3) c -> (4) d -> (5) "


def test_a_bare_root_is_refused():
    """The defect: a chain that names a ROOT without saying if it is bedrock or a pointer."""
    out = _msgs([_row("RC-9001", CHAIN + "ROOT: the repo does not enforce X.")])
    assert "BEDROCK or a POINTER" in out, (
        "a bare ROOT passed — the recursion rule is not binding")


def test_terminal_with_a_real_justification_passes():
    out = _msgs([_row("RC-9002", CHAIN + "ROOT: TERMINAL — no further why exists because "
                                         "the format records no such distinction at all.")])
    assert "BEDROCK or a POINTER" not in out
    assert "TERMINAL with no justification" not in out


def test_terminal_without_a_justification_is_refused():
    """Otherwise TERMINAL is just the word ROOT again."""
    out = _msgs([_row("RC-9003", CHAIN + "ROOT: TERMINAL — obvious.")])
    assert "TERMINAL with no justification" in out


def test_spawns_passes_when_the_child_row_exists():
    rows = [
        _row("RC-9004", CHAIN + "ROOT: SPAWNS RC-9005 — the child defect."),
        _row("RC-9005", CHAIN + "ROOT: TERMINAL — bedrock because the mechanism has no "
                                "further input to interrogate here at all."),
    ]
    out = _msgs(rows)
    assert "BEDROCK or a POINTER" not in out
    assert "has no row" not in out


def test_spawns_is_refused_when_the_child_does_not_exist():
    """A promise of a child is not a child."""
    out = _msgs([_row("RC-9006", CHAIN + "ROOT: SPAWNS RC-9999 — a child never written.")])
    assert "has no row" in out, "a dangling SPAWNS passed — the recursion is a promise chain"


def test_rows_opened_before_the_cutover_are_untouched():
    """A new requirement must not retroactively invalidate rows written before it existed."""
    out = _msgs([_row("RC-9007", CHAIN + "ROOT: the repo does not enforce X.",
                      opened="2026-07-30")])
    assert "BEDROCK or a POINTER" not in out


def test_the_cutover_is_the_date_the_operator_set():
    assert FIVE_WHY_RECURSION_CUTOVER == "2026-08-08"


def test_the_live_log_satisfies_the_recursion_rule():
    """The repository itself must pass, not just synthetic rows."""
    log = REPO / "governance" / "root_cause_log.md"
    lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    recursion_hits = [v for v in _five_why_lock_violations(lines, log, "", "")
                      if "BEDROCK or a POINTER" in v.msg
                      or "TERMINAL with no justification" in v.msg]
    assert not recursion_hits, (
        f"live rows violate the recursion rule: {[v.msg[:90] for v in recursion_hits]}")
