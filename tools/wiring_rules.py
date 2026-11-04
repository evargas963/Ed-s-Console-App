"""The operator's three rules, put in front of the agent on every message he sends
(UserPromptSubmit). Wired by `.claude/settings.json`.

    python tools/wiring_rules.py < payload.json
Prints Claude Code's hook JSON with the rules as `additionalContext`. It refuses nothing: whether a
change is simple is the reviewers' judgment (AGENTS.md rule 14).
"""

from __future__ import annotations

import json
import sys

RULES = (
    "The operator's three rules (they decide every question):\n"
    "1. This is a simple wiring job: Schwab -> program -> page, fewest hops, nothing extra.\n"
    "2. We use Schwab's data, as Schwab sends it; a value is derived only where Schwab does not"
    " send it.\n"
    "3. This is a financial app: answer each question by what a bank would do.\n"
    "Before any edit of product code (every file tools/check_end_to_end.is_product counts), answer"
    " in one line each: Which"
    " Schwab field, or which registered derived value? What is the simplest direct wire? What"
    " would a bank do?"
)


def main() -> int:
    payload = json.load(sys.stdin)
    out = {"hookEventName": payload["hook_event_name"], "additionalContext": RULES}
    print(json.dumps({"hookSpecificOutput": out}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
