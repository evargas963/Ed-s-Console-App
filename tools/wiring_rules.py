"""The operator's five rules, put in front of the agent on every message he sends
(UserPromptSubmit). Wired by `.claude/settings.json`.

    python -m tools.wiring_rules < payload.json
Prints Claude Code's hook JSON with the rules as `additionalContext`. It refuses nothing: that they
were applied is the builder's audit (AGENTS.md rule 14). It also records the message as the
session's next message (tools/keep_going.record_message), which the Stop hook holds the turn open
on until the agent reads it, and, read as an order, answers it; the session's standing orders come
with it, so a conflict with one is seen at once.
"""

from __future__ import annotations

import json
import sys

from tools.keep_going import record_message, standing_orders

RULES = (
    "The operator's five rules (they decide every question):\n"
    "1. This is a simple wiring job: Schwab -> program -> page, fewest hops, nothing extra.\n"
    "2. We use Schwab's data, as Schwab sends it; a value is derived only where Schwab does not"
    " send it.\n"
    "3. This is a financial app: answer each question by what a bank would do.\n"
    "4. Everything is repo wide: every rule, fix, check, test and answer covers every file of the"
    " repository and every ticker, never only the place a problem showed.\n"
    "5. Every repair is end to end: trace every link from cause to screen with evidence, repair"
    " each at its source, and test each way it can fail in real use (block, stall, crash,"
    " restart halfway, arrive late, twice or not at all); never a patch.\n"
    "They apply to all code in the repository and to every answer, proposal and change. For each,"
    " answer in one line each: Which"
    " Schwab field, or which registered derived value? What is the simplest direct wire? What"
    " would a bank do? Is it repo wide? Is every link repaired at its source?"
)

#: what the agent is told about the operator's message it is reading
MESSAGE = (
    "\nThis is MESSAGE {n}. Ask the operator whether it is an order, giving your reading, and if it"
    " is one, tell him at once whether it breaks anything or conflicts with an earlier order: a"
    " line `MESSAGE {n} READ: ORDER - <what it orders>; BREAKS: <what, or nothing>` or"
    " `MESSAGE {n} READ: NOT AN ORDER - <why>`. An order is done, not chosen: answer it with"
    " `ORDER {n} DONE: <evidence>`, or `ORDER {n} PUSHBACK: <reason>` only when it is not allowed"
    " or not possible."
)


def main() -> int:
    payload = json.load(sys.stdin)
    said = RULES
    n = record_message(payload)
    if n is not None:
        said += MESSAGE.format(n=n)
        said += "".join(
            f"\nStanding ORDER {k}: {text[:300]}" for k, text in standing_orders(payload)
        )
    out = {"hookEventName": payload["hook_event_name"], "additionalContext": said}
    print(json.dumps({"hookSpecificOutput": out}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
