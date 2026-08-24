"""The one authority rule (RC-462).

There are NO designated writers, auditors or readers. The operator decides what an AI
does that day by asking it - the repo stores no role for anyone, and no field in any
tracked file grants permission to anything.

The single rule this module enforces: while an AI is acting (ED_AGENT_ROLE is set), it
may not edit the files that decide who is in charge. The operator (empty ED_AGENT_ROLE)
is unconstrained, and operator review at merge (CODEOWNERS + branch protection) is what
makes the rule durable.

This module BLOCKs only control-authority rewrites by an assigned principal
(ED_AGENT_ROLE set). Ordinary product paths are not vendor-gated.

Fires:
  - PreToolUse via process_lock_guard / control_authority_violation (in-process
    defense-in-depth). RC-470/RC-471: the commit-time backstop (check_writer_no_drift)
    is retired - the durable, subject-independent gate is operator review at MERGE
    (CODEOWNERS + require_code_owner_reviews + enforce_admins), and
    CONTROL_AUTHORITY_EXACT below mirrors CODEOWNERS exactly.

Empty ED_AGENT_ROLE is operator/CI (abstain), never a guessed vendor.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Mission COORDINATION metadata only (RC-461) - never authorization.
PM_MISSION_PATH = REPO / "governance" / "pm_mission.json"

#: Statuses that bind SoD — not only literal "active".
MISSION_IN_PROGRESS_STATUSES = frozenset({
    "active",
    "ready_for_writer",
    "ready_for_claude",
    "ready_for_cursor",
    "in_progress",
    "in-progress",
})

#: RC-471 (operator ruling 2026-08-24): this set mirrors .github/CODEOWNERS EXACTLY —
#: the files that decide WHO IS IN CHARGE, and nothing else. Approval binds at MERGE
#: (CODEOWNERS + require_code_owner_reviews + enforce_admins, server-side and
#: subject-independent); this declaration exists for the in-process PreToolUse rail
#: and for the tests that assert rail/CODEOWNERS parity. The pre-RC-471 set carried
#: the whole hook/pre-commit import closure here — quality-gate scripts, guard
#: helpers, conftest, venv wrappers — but every local rail is evadable by the subject
#: it constrains (measured under RC-470: the commit hook clears ED_AGENT_ROLE, CI
#: sets no role, and hooks run the production checkout's guards so worktree edits
#: never met this list). Quality/test gates are not authority.
CONTROL_AUTHORITY_EXACT = frozenset({
    ".github/CODEOWNERS",
    ".claude/settings.json",
    ".cursor/hooks.json",
    "governance/operator_go.json",
    "governance/operator_grants.json",
    "tools/writer_drift_lock.py",
    "tools/process_lock_guard.py",
    "tools/operating_process_lock.py",
    "tests/test_architecture_a_bypass_class_v1.py",
    "tests/test_writer_drift_lock_v1.py",
    "tests/test_control_authority_surfaces_v1.py",
    "tests/test_architecture_a_operator_writer_authority_v1.py",
    "tests/test_operating_process_lock_v1.py",
})
CONTROL_AUTHORITY_PREFIXES = (
    ".github/workflows/",
)

#: LOCK-4 (RC-232): every SOD_DRIFT denial is recorded here; a denial without a same-window
#: OPEN RC row naming the mission_id + SOD_DRIFT owes a self-heal and BLOCKS further writes.
SOD_DRIFT_EVENTS_PATH = REPO / "governance" / "sod_drift_events.jsonl"


def record_sod_drift(messages: list[str], *, agent: str | None = None,
                     mission: dict | None = None) -> None:
    """LOCK-4: persist every drift denial so the owed self-heal is checkable."""
    if not messages:
        return
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return  # synthetic test denials must never pollute the real self-heal ledger
    if mission is None:
        # RC-461: there is no executable mission any more. Before the simplification this
        # resolved executable_mission(), which returned {} on every host that lacked the
        # (now deleted) off-repo authority - i.e. mission_id was always None here. Keep
        # that exact behaviour: reading the coordination JSON instead would hand LOCK-4 a
        # real mission id and silently make the lock STRICTER than it was, which is a
        # governance change, not a simplification. Callers may still pass one explicitly.
        mission = {}
    try:
        import time as _t
        with SOD_DRIFT_EVENTS_PATH.open("a", encoding="utf-8") as fh:
            for m in messages:
                fh.write(json.dumps({
                    "ts": _t.time(),
                    "agent": (agent or current_agent_role()),
                    "mission_id": mission.get("mission_id"),
                    "message": str(m)[:300],
                    "healed": False,
                }) + "\n")
    except OSError:
        pass  # institutional-swallow-ok: the DENY itself already fired; ledger append is best-effort


def self_heal_owed_violations(*, rc_lines: list[str] | None = None) -> list[str]:
    """LOCK-4: unhealed drift events require an OPEN RC row naming mission_id + SOD_DRIFT.

    A denial with no same-window RC is the banned silent-drift state: BLOCK with
    SELF_HEAL_OWED until the row exists (auto-editing product to 'heal' stays banned)."""
    try:
        raw = SOD_DRIFT_EVENTS_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    events = []
    for ln in raw:
        try:
            e = json.loads(ln)
        except (ValueError, json.JSONDecodeError):
            continue
        if isinstance(e, dict) and not e.get("healed"):
            events.append(e)
    if not events:
        return []
    if rc_lines is None:
        try:
            rc_lines = (REPO / "governance" / "root_cause_log.md").read_text(
                encoding="utf-8").splitlines()
        except OSError:
            rc_lines = []
    out: list[str] = []
    for e in events:
        mid = str(e.get("mission_id") or "")
        healed = any(
            ln.startswith("| RC-") and "SOD_DRIFT" in ln and (not mid or mid in ln)
            and ln.split("|")[2].strip() in ("OPEN", "PARTIAL", "CLOSED")
            for ln in rc_lines
        )
        if not healed:
            out.append(
                f"SELF_HEAL_OWED: SOD_DRIFT denial for mission {mid!r} has no RC row naming "
                f"the mission + SOD_DRIFT (LOCK-4/RC-232) — open the row before further writes."
            )
            break
    return out


def _norm(rel: str) -> str:
    return rel.replace("\\", "/").strip()


def _load_json(path: Path) -> dict:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return doc if isinstance(doc, dict) else {}


def mission_in_progress(mission: dict | None) -> bool:
    if not mission:
        return False
    status = str(mission.get("status") or "idle").strip().lower()
    return status in MISSION_IN_PROGRESS_STATUSES


def is_control_authority_surface(rel: str) -> bool:
    """True for files that define CI/merge/hook/assignment rails.

    Derived from hook entrypoints, required workflow paths, and assignment JSON.
    Any assigned principal rewriting these can defeat the constraint.
    """
    rel = _norm(rel)
    if rel in CONTROL_AUTHORITY_EXACT:
        return True
    for p in CONTROL_AUTHORITY_PREFIXES:
        if rel.startswith(p):
            return True
    # RC-471: the *_guard.py/*_lock.py name rule and the check-script name set are
    # removed — membership is EXACT + the workflows prefix, mirroring CODEOWNERS.
    # Quality-gate scripts and non-rail guards are ordinary autonomous code.
    return False


def control_authority_violation(rel: str, *, agent: str | None = None) -> str | None:
    """BLOCK when an assigned principal touches a control-authority surface."""
    agent = (agent or current_agent_role()).strip().lower()
    if not agent:
        return None
    rel = _norm(rel)
    if not is_control_authority_surface(rel):
        return None
    return (
        f"SOD_DRIFT: control-authority surface {rel} — agent={agent!r} cannot "
        f"redefine the rails that constrain assigned principals (Architecture A / RC-453)."
    )


def current_agent_role() -> str:
    """Current principal from ED_AGENT_ROLE. Empty = operator/CI, not a vendor guess."""
    return os.environ.get("ED_AGENT_ROLE", "").strip().lower()


def writer_drift_violations(
    changed_paths: list[str],
    *,
    agent: str | None = None,
    mission: dict | None = None,
    sole_writer: dict | None = None,
) -> list[str]:
    """BLOCK control-authority rewrites by an assigned principal.

    mission/sole_writer writer fields are ignored — stale assignment metadata
    must not veto operator-selected ordinary product work (RC-454).
    """
    del mission, sole_writer  # not authorization
    agent = (agent or current_agent_role()).strip().lower()
    out: list[str] = []
    for raw in changed_paths:
        rel = _norm(raw)
        if not rel:
            continue
        auth = control_authority_violation(rel, agent=agent)
        if auth:
            out.append(auth)
    return out


def git_changed_paths(repo: Path | None = None, *, staged_only: bool = False) -> list[str]:
    root = repo or REPO
    paths: list[str] = []
    cmds: list[list[str]] = [["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"]]
    if not staged_only:
        cmds.append(["git", "diff", "--name-only", "--diff-filter=ACMR"])
        cmds.append(["git", "ls-files", "--others", "--exclude-standard"])
    for cmd in cmds:
        try:
            r = subprocess.run(
                cmd,
                cwd=str(root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if r.returncode != 0:
            continue
        for line in r.stdout.splitlines():
            p = _norm(line)
            if p and p not in paths:
                paths.append(p)
    return paths


def live_writer_drift_violations(
    repo: Path | None = None,
    *,
    agent: str | None = None,
    staged_only: bool = False,
    mission: dict | None = None,
    sole_writer: dict | None = None,
) -> list[str]:
    root = repo or REPO
    del mission, sole_writer  # RC-454: persisted assignment is not authorization
    paths = git_changed_paths(root, staged_only=staged_only)
    return writer_drift_violations(paths, agent=agent)
