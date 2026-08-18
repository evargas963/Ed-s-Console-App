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
    # RC-246: the blocking path runs ENFORCED checks only. Advisory checks cannot fail this
    # gate by construction, and charging every commit 153s of a 244s wall for verdicts that
    # can never veto made the gate expensive enough to route around — a cost this repo has
    # already paid in piped commits and hooks killed mid-run. Advisory debt is not dropped:
    # it runs via `--advisory` on the scheduled/rehab path and is recorded in
    # reports/advisory_debt_latest.json.
    #
    # RC-391: this used to run check_institutional_correctness.py directly, which demands
    # ABSOLUTE ZERO enforced violations. The repo carries ~70 inherited ones, so every
    # commit was blocked for debt it did not create — including the commits paying that
    # debt down. A gate no honest change can pass is not enforcement; it is a permanent
    # --no-verify generator, which is exactly what it became. The question a pre-commit
    # gate can actually answer is DELTA: does what I am about to commit carry an enforced
    # violation the base did not, or remove an enforced check? So the decision is delegated
    # to the existing delta owner, run in --index mode so the thing measured is the exact
    # staged commit rather than HEAD (which predates the change) or the working tree (which
    # carries unstaged scratch that is not part of it). Fail-closed is not weakened
    # anywhere: the delta tool raises rather than reporting a count whenever either side
    # cannot be measured, and any non-zero return here still blocks the commit.
    gate = REPO / "tools" / "check_delta_adds_no_debt.py"
    base = _base_ref()
    # RC-254: was os.execv, which on Windows spawns a detached child and returns 0 to
    # pre-commit immediately — this hook reported "Passed" without the gate's verdict ever
    # reaching it. The gate's exit code must BE this hook's exit code.
    return subprocess.run(
        [sys.executable, str(runner), str(gate), "--index", "--base", base], cwd=str(REPO)
    ).returncode


def _base_ref() -> str:
    """The trunk this commit is measured against. An unresolvable base means NO commit.

    ONE MAIN: main is the sole accepted trunk, so the base is the remote trunk when it is
    known locally and the local one otherwise. If NEITHER resolves there is nothing to
    compare against, and "no baseline" must never quietly become "nothing is new debt".
    """
    for ref in ("origin/main", "main"):
        probe = subprocess.run(
            ["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
            cwd=str(REPO), capture_output=True, text=True)
        if probe.returncode == 0 and probe.stdout.strip():
            return ref
    raise SystemExit(
        "institutional gate: cannot resolve a base trunk (tried origin/main, main). The "
        "delta cannot be measured, so this commit is refused rather than waved through "
        "unmeasured.")


if __name__ == "__main__":
    raise SystemExit(main())
