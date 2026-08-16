#!/usr/bin/env python3
"""Pre-commit entry: institutional gate, run under the AMBIENT agent identity.

Local pre-commit hooks do not honor an ``env:`` map on ``repo: local`` entries
(pre-commit warns and ignores it), which is why this wrapper exists at all.

RC-240: it used to HARDCODE ``ED_AGENT_ROLE=cursor``. That was a fabricated identity, and
the identity-sensitive backstop believed it: on the sole writer's own commit the gate
reported "mission writer='claude' but agent='cursor' touched scope path …" and BLOCKED the
writer for being himself (MEASURED on the LOG LAW arming commit, 2026-08-04). A check whose
verdict depends on who is acting must never be handed an invented actor — the only honest
inputs are the real ambient identity, or none at all.

So: pass an already-set identity through untouched, and when the environment carries none,
leave it unset. `check_writer_no_drift` documents exactly that contract — with no identity
it abstains and the PreToolUse layer (which always has a real one from each agent's own hook
env) carries the enforcement. Abstaining is correct here; guessing is not.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def main() -> int:
    # RC-240: never fabricate an actor. Pass a real ambient identity through; otherwise
    # leave it absent so the identity-sensitive backstop abstains instead of judging a
    # commit against an invented agent.
    ambient = os.environ.get("ED_AGENT_ROLE", "").strip().lower()
    if ambient not in ("cursor", "claude"):
        os.environ.pop("ED_AGENT_ROLE", None)
    runner = REPO / "tools" / "run_with_repo_venv.py"
    # RC-389: the blocking path is DELTA vs origin/main, not "enforced must be 0".
    # Standing backlog (~100) made every honest commit fail, which made --no-verify
    # the default and hid NEW violations (five_why 0→4 on 1294781a) inside the red.
    # Fail-closed if origin/main cannot be resolved — missing base is not a pass.
    verify = subprocess.run(
        ["git", "rev-parse", "--verify", "origin/main"],
        cwd=str(REPO), capture_output=True, text=True,
    )
    if verify.returncode != 0:
        print("RC-389: origin/main is not available; refusing to commit fail-open.",
              file=sys.stderr)
        return 2
    delta = REPO / "tools" / "check_delta_adds_no_debt.py"
    return subprocess.run(
        [sys.executable, str(runner), str(delta), "--base", "origin/main", "--staged"],
        cwd=str(REPO),
    ).returncode


if __name__ == "__main__":
    raise SystemExit(main())
