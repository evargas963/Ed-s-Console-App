"""Blinter's findings as the census counts them: each finding at each place Blinter names."""

from __future__ import annotations

import re

#: Blinter's line for one finding, its places first: "Line 5, 8: Long line without continuation
#: (S020)" is one finding seen at lines 5 and 8
FINDING = re.compile(r"Line (\d+(?:, \d+)*): (.+) \(([A-Z]\d+)\)$")


def findings(output: str) -> list[tuple[str, str, int]]:
    """Return each finding in Blinter's `output` at each place it names: (rule, message, line)."""
    return [
        (m.group(3), m.group(2), int(n))
        for ln in output.splitlines()
        if (m := FINDING.match(ln.strip()))
        for n in m.group(1).split(", ")
    ]
