"""The operator's five rules, put in front of the agent on every message he sends
(UserPromptSubmit). Wired by `.claude/settings.json`.

    python tools/wiring_rules.py < payload.json
Prints Claude Code's hook JSON with the rules as `additionalContext`. It refuses nothing: that they
were applied is the builder's audit (AGENTS.md rule 14).
"""

from __future__ import annotations

import json
import sys

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


def main() -> int:
    payload = json.load(sys.stdin)
    out = {"hookEventName": payload["hook_event_name"], "additionalContext": RULES}
    print(json.dumps({"hookSpecificOutput": out}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
