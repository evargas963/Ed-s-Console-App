#!/usr/bin/env python3
"""Hook CLI for the mission authorization system (pre-commit + pre-push stages).

Usage:
  python tools/check_mission_authorization.py --pre-commit
  python tools/check_mission_authorization.py --pre-push   (git pre-push stdin)
  python tools/check_mission_authorization.py --pre-edit --mission <ID>
  python tools/check_mission_authorization.py --classify-push-output <file>

Mission selection: the ED_MISSION_ID environment variable names the active
contract. Absence of ED_MISSION_ID is fail-open ONLY for commits/pushes whose
destination is a non-main feature branch already covered by an active contract
matching the current branch; otherwise the gate refuses. Working on main
without a controlled_integration contract always refuses.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.mission_authorization import (  # noqa: E402
    ACTIVE_DIR,
    classify_push_output,
    detect_mission_overlap,
    load_contract,
    record_policy_violation,
    red_main_breaker_engaged,
    validate_push_destination,
    validate_workspace,
)


def _current_branch() -> str:
    import subprocess

    return subprocess.run(
        ["git", "branch", "--show-current"], cwd=REPO_ROOT,
        capture_output=True, text=True, timeout=30,
    ).stdout.strip()


def _resolve_contract() -> tuple[dict | None, str]:
    mid = os.environ.get("ED_MISSION_ID", "").strip()
    if mid:
        return load_contract(mid)
    # No explicit mission id: find an active contract matching this branch.
    branch = _current_branch()
    if branch == "main":
        return None, (
            "working on main requires an explicit controlled_integration "
            "authorization (ED_MISSION_ID) — a checked-out main is never permission"
        )
    if ACTIVE_DIR.is_dir():
        for p in sorted(ACTIVE_DIR.glob("*.json")):
            try:
                doc = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if doc.get("authorized_branch") == branch and doc.get("lease_state") == "active":
                return load_contract(doc["mission_id"])
    return None, (
        f"no active mission authorization covers branch {branch!r} — "
        "declare one under governance/mission_authorization/active/"
    )


def main(argv: list[str]) -> int:
    engaged, why = red_main_breaker_engaged()
    if engaged:
        print(f"mission-authorization: RED-MAIN CIRCUIT BREAKER — {why}")
        return 1

    contract, reason = _resolve_contract()
    if contract is None:
        print(f"mission-authorization: REFUSED — {reason}")
        return 1

    errors: list[str] = []
    errors += validate_workspace(contract, cwd=REPO_ROOT)
    errors += detect_mission_overlap(contract)

    if "--pre-push" in argv:
        stdin_lines = [ln.strip() for ln in sys.stdin.read().splitlines() if ln.strip()]
        if not stdin_lines:
            # pre-commit consumes git's pre-push stdin and re-exposes the refs
            # as env vars (PRE_COMMIT_LOCAL_BRANCH / PRE_COMMIT_REMOTE_BRANCH /
            # PRE_COMMIT_FROM_REF / PRE_COMMIT_TO_REF). Reconstruct the ref
            # line from that channel; absence of BOTH channels still refuses.
            lref = os.environ.get("PRE_COMMIT_LOCAL_BRANCH", "").strip()
            rref = os.environ.get("PRE_COMMIT_REMOTE_BRANCH", "").strip()
            lsha = os.environ.get("PRE_COMMIT_FROM_REF", "").strip() or "0" * 40
            rsha = os.environ.get("PRE_COMMIT_TO_REF", "").strip() or "0" * 40
            if lref and rref:
                stdin_lines = [f"{lref} {lsha} {rref} {rsha}"]
        errors += validate_push_destination(
            contract,
            stdin_lines=stdin_lines,
            remote_url=os.environ.get("PRE_COMMIT_REMOTE_URL"),
        )

    if "--classify-push-output" in argv:
        f = argv[argv.index("--classify-push-output") + 1]
        hits = classify_push_output(Path(f).read_text(encoding="utf-8", errors="replace"))
        if hits:
            record_policy_violation(
                contract["mission_id"], "bypass_warning", {"lines": hits}
            )
            print("mission-authorization: BYPASS WARNING = POLICY_VIOLATION (closure blocked)")
            for h in hits:
                print(" -", h)
            return 1

    if errors:
        print("mission-authorization: REFUSED")
        for e in errors:
            print(" -", e)
        return 1
    print(
        f"mission-authorization: ok mission={contract['mission_id']} "
        f"branch={contract['authorized_branch']} type={contract['mission_type']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
