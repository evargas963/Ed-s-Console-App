#!/usr/bin/env python3
"""RC-321 — a five-why must terminate on a DEFECT, never on an EXPLANATION.

OPERATOR LAW (2026-08-09, non-negotiable): "we do 5 whys to bedrock."

WHAT WAS OBSERVED. RC-315's chain was five levels deep, ended `ROOT: TERMINAL` with a real
justification, and passed `five_why_recursive_lock` — and its level (4) read "because the
operator's instruction to research and DECIDE rather than ask removed the one check that had
been catching me". That is not a cause of my defect. It is a description of the
circumstances around it. Cursor's audit rejected it in one line: being asked to decide never
suspended the repository's evidence-before-assertion law. Causation had been handed to
another actor's request and the chain stopped there, because an explanation feels like an
endpoint.

WHY THE EXISTING LOCK CANNOT SEE IT. `five_why_recursive_lock` enforces the SHAPE of a
chain: five levels, and a root that is either TERMINAL with a justification or SPAWNS a named
child that exists. Every one of those held. Shape was enforced; ownership of the cause was
not. A chain can satisfy every structural rule and still stop one step short by blaming
somebody.

THE RULE. Not "is this root correct" — no static check can know that. The rule is narrower,
and it is the one difference between a defect and an explanation that is mechanically
identifiable: a why-step may not attribute causation to ANOTHER ACTOR'S instruction, request
or message. The operator asking for something, Cursor reporting something, a reviewer wanting
something — none of those are defects this repository can repair, and a chain resting on one
has located a circumstance rather than a cause.

QUOTING A BLAME-SHIFT IN ORDER TO REJECT IT IS REQUIRED, NOT FORBIDDEN. A corrected row must
be able to say "I blamed the operator's instruction and that was wrong" — which is exactly
what RC-315 now says — so a rejection marker in the same cell clears it.

HOW IT WAS VALIDATED. Prototyped over all 290 rows BEFORE wiring. A first pattern also
matched bare "time pressure" and produced one hit, RC-290 — a FALSE POSITIVE: that row uses
pressure to describe an incentive gradient, and its root correctly names my own defect ("an
escape hatch whose correctness depends on my own diligence"). Describing an incentive is
analysis; blaming a person is the stop-short. The pattern was narrowed to actor-attribution
and the repository reached zero on merit, with the false positive repaired by narrowing the
RULE rather than exempting the ROW. Then tested against the real historical text rather than
a reconstruction — `git show e1bc6793:governance/root_cause_log.md` — where it fires on
RC-315 as first written and stays silent on RC-315 as corrected. RC-317 records what happens
when a negative control is built from the author's memory of a defect instead of the defect.

    .venv/Scripts/python.exe tools/check_five_why_reaches_bedrock.py
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

#: Rows opened before the rule existed. Frozen: a lock binds new work, and rewriting history
#: is not enforcement — the same design the numeric-citation rule records for itself.
BEDROCK_CUTOVER = "2026-08-09"

#: Causation handed to ANOTHER ACTOR'S instruction, request or message.
#:
#: Deliberately NOT "time pressure" or "deadline". A first pass matched those and flagged
#: RC-290, whose root correctly names my own defect and which uses pressure to describe the
#: mechanism by which a cheap wrong option beats an expensive right one. Describing an
#: incentive is analysis. Blaming a person is the stop-short.
_BLAME_RE = re.compile(
    r"\b(?:because|since|as)\s+(?:the\s+)?"
    r"(?:operator|user|cursor|bugbot|reviewer|auditor)\b[^.]{0,120}?"
    r"\b(?:instruct\w+|told|asked|said|order\w*|request\w+|removed|wanted)\b"
    r"|\bthe\s+(?:operator|user|cursor)'?s?\s+(?:instruction|request|order|message)\b"
    r"|\bI\s+was\s+(?:asked|told|instructed)\s+to\b",
    re.I,
)

#: Quoting the blame-shift in order to REJECT it is what a corrected row must do.
_REJECTION_RE = re.compile(
    r"\b(?:correctly\s+rejected|rejected|is\s+not\s+a\s+valid\s+root|was\s+deflection"
    r"|never\s+suspended|wrongly\s+blamed|is\s+not\s+an\s+excuse|does\s+not\s+excuse"
    r"|not\s+itself\s+a\s+blame-shift)\b",
    re.I,
)


def violations(log_path: Path | None = None) -> list[str]:
    path = log_path or (REPO / "governance" / "root_cause_log.md")
    out: list[str] = []
    if not path.exists():
        return out
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.startswith("| RC-"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 7:
            continue                      # schema breakage is rc_log_rows_keep_schema's job
        rc_id, opened, why = cells[0], cells[2], cells[5]
        if opened < BEDROCK_CUTOVER:
            continue
        hit = _BLAME_RE.search(why)
        if not hit or _REJECTION_RE.search(why):
            continue
        out.append(
            f"{path.name}:{n}  {rc_id} hands causation to another actor "
            f"({hit.group(0).strip()!r}) and stops there. That is an EXPLANATION, not a "
            f"defect, and a five-why terminates on a defect. RC-315 ended exactly this way "
            f"— five levels, a clean TERMINAL root, blaming the operator's instruction — "
            f"and an outside audit rejected it in one line: being asked to decide never "
            f"suspended the evidence-before-assertion law. Ask the next why: what did I do, "
            f"or fail to build, that let that circumstance produce a defect? If you are "
            f"QUOTING a blame-shift in order to reject it, say so in the same cell.")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)
    v = violations()
    if v:
        print("check_five_why_reaches_bedrock: FAIL — chains that stop at an explanation:")
        for line in v:
            print("  " + line)
        return 1
    if not args.quiet:
        print("check_five_why_reaches_bedrock: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
