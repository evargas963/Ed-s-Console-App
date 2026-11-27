"""tools.census.blinter: every finding Blinter prints is counted, at each place it names.

The lines are Blinter 1.1.68's own (tools/census/requirements.txt), as it printed them for the
daemon's window file while its comments ran past 100 columns and its stop message read the time
inside a parenthesized block: a finding seen at two places names both ("Line 5, 8"), and one seen
twice on one line names it twice ("Line 25, 25").
"""

from __future__ import annotations

import pytest

from tools.census.blinter import findings

pytestmark = pytest.mark.rail

OUTPUT = """\
Blinter v1.1.68 - Batch File Linter
 Batch File Analysis: start_capture_daemon.bat
===================================================================================================
DETAILED ISSUES:
----------------
WARNING LEVEL ISSUES:
=====================
Line 30: Potential infinite loop (W004)
- Explanation: Loop construct may run infinitely without proper exit conditions
- Recommendation: Add counter variables or proper exit conditions to prevent infinite loops
- Context: GOTO :loop may create an infinite loop without exit condition
Line 25, 25: Parse-time pseudo-variable inside a parenthesized block (W071)
- Explanation: cmd.exe expands %errorlevel%, %random%, %time%, and %date% once when it parses a \
parenthesized block, so later commands in that block do not update them
- Context: %date% is expanded once when the block is parsed; use !date! with EnableDelayedExpansion
- Context: %time% is expanded once when the block is parsed; use !time! with EnableDelayedExpansion
STYLE LEVEL ISSUES:
===================
Line 5, 8: Long line without continuation (S020)
- Explanation: Very long lines reduce readability and should be split
- Context: Line length 106 exceeds 100 characters
- Context: Line length 179 exceeds 100 characters
SEVERITY BREAKDOWN:
====================
Warning: 5 issues
"""


def test_each_finding_is_counted_at_each_place_blinter_names():
    """One finding at one line, one twice on a line and one at two lines: five places."""
    pseudo = "Parse-time pseudo-variable inside a parenthesized block"
    assert findings(OUTPUT) == [
        ("W004", "Potential infinite loop", 30),
        ("W071", pseudo, 25),
        ("W071", pseudo, 25),
        ("S020", "Long line without continuation", 5),
        ("S020", "Long line without continuation", 8),
    ]


def test_a_file_with_no_finding_has_none():
    """Blinter's answer for a clean file names no line."""
    assert findings("No issues found! Your batch file looks great!\n") == []
