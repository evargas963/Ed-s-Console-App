"""Writer no-drift mechanical lock (RC-226).

When an in-progress PM mission (or sole_writer) assigns writer≠current agent,
the non-writer must not modify mission scope_paths. Cursor=PM/auditor;
Claude=sole writer is the standing model — drift into writer work is a BLOCK,
not a chat reminder.

Fires:
  - PreToolUse via operating_process_lock.pm_mission_edit_violation
  - commit / pre-commit via writer_drift_violations on dirty paths
  - check_writer_no_drift in check_institutional_correctness.py

Escape: ED_WRITER_DRIFT_GUARD=off (operator only, visible).
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

SOLE_WRITER_PATH = REPO / "governance" / "sole_writer.json"
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

#: Cursor (PM/auditor) may touch these while writer is another agent.
#: Product / scope_paths outside this list → WRITER-DRIFT BLOCK.
PM_ALLOWLIST_EXACT = frozenset({
    "governance/AGENT_OPERATING_PROCESS_V1.md",
    "governance/PM_MANDATE.md",
    "governance/REHAB_PROGRAM.md",
    "governance/sole_writer.json",
    "governance/operator_go.json",
    "governance/pm_mission.json",
    "governance/root_cause_log.md",
    "reports/process_mechanical_locks_v1.md",
    "reports/rehab_latest.md",
    "reports/rehab_latest.json",
    "reports/rehab_queue.jsonl",
    "tests/test_operating_process_lock_v1.py",
    "tests/test_rehab_daily_scan_v1.py",
    "tests/test_writer_drift_lock_v1.py",
    "tools/operating_process_lock.py",
    "tools/process_lock_guard.py",
    "tools/pretooluse_guard.py",
    "tools/rehab_daily_scan.py",
    "tools/writer_drift_lock.py",
    "tools/rc_resolve_lock.py",
    "tools/check_institutional_correctness.py",
    "tests/test_rc_document_without_resolve_v1.py",
    ".cursor/rules/07-cursor-pm.mdc",
    ".cursor/rules/08-no-writer-drift.mdc",
    "ACTIVE_PROGRAM.md",
    "AGENTS.md",
})

PM_ALLOWLIST_PREFIXES = (
    ".cursor/rules/",
)


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


def is_pm_allowlisted(rel: str) -> bool:
    """PM/auditor compliance surfaces — legal for Cursor when writer≠cursor."""
    rel = _norm(rel)
    if rel in PM_ALLOWLIST_EXACT:
        return True
    for p in PM_ALLOWLIST_PREFIXES:
        if rel.startswith(p):
            return True
    if rel.startswith("reports/"):
        name = rel.lower()
        if (
            "audit" in name
            or "handoff" in name
            or "/rehab_" in name
            or "rc_open_drain" in name
            or name.endswith("rehab_queue.jsonl")
        ):
            return True
    return False


def path_in_mission_scope(rel: str, scope_paths: list | None) -> bool:
    rel = _norm(rel)
    if not scope_paths:
        return False
    norms = [str(s).replace("\\", "/").strip() for s in scope_paths if str(s).strip()]
    if "*" in norms or "all" in {s.lower() for s in norms}:
        return True
    for s in norms:
        if s.endswith("/"):
            if rel.startswith(s):
                return True
        elif rel == s or rel.startswith(s.rstrip("/") + "/"):
            return True
    return False


def resolved_writer(mission: dict | None = None, sole: dict | None = None) -> str:
    m = mission if mission is not None else _load_json(PM_MISSION_PATH)
    s = sole if sole is not None else _load_json(SOLE_WRITER_PATH)
    return str(m.get("writer") or s.get("writer") or "").strip().lower()


def current_agent_role() -> str:
    role = os.environ.get("ED_AGENT_ROLE", "").strip().lower()
    if role in ("cursor", "claude"):
        return role
    return "cursor"


def writer_drift_violations(
    changed_paths: list[str],
    *,
    agent: str | None = None,
    mission: dict | None = None,
    sole_writer: dict | None = None,
) -> list[str]:
    """Return BLOCK messages when non-writer dirty paths hit mission scope."""
    if os.environ.get("ED_WRITER_DRIFT_GUARD", "").strip().lower() in ("off", "0", "false"):
        return []
    mission = mission if mission is not None else _load_json(PM_MISSION_PATH)
    sole = sole_writer if sole_writer is not None else _load_json(SOLE_WRITER_PATH)
    if not mission_in_progress(mission):
        return []
    writer = resolved_writer(mission, sole)
    if not writer:
        return []
    agent = (agent or current_agent_role()).strip().lower()
    if agent == writer:
        return []
    if sole.get("cursor_edit_ok") is True and agent == "cursor":
        return []
    scopes = mission.get("scope_paths") or ["*"]
    if not isinstance(scopes, list):
        scopes = ["*"]
    mid = mission.get("mission_id")
    out: list[str] = []
    for raw in changed_paths:
        rel = _norm(raw)
        if not rel or is_pm_allowlisted(rel):
            continue
        if path_in_mission_scope(rel, scopes):
            sod = (
                f"SOD_DRIFT: {writer} is sole writer"
                if writer and agent != writer
                else "SOD_DRIFT: wrong-role edit"
            )
            out.append(
                f"{sod} — WRITER-DRIFT BLOCK: mission writer={writer!r} but agent={agent!r} "
                f"touched scope path {rel} (mission_id={mid!r}) — Cursor=PM/auditor only; "
                f"sole writer owns scope_paths"
            )
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
    # Load mission/sole from the target repo so tmp-repo tests and alternate trees
    # do not inherit the ambient live pm_mission.json.
    if mission is None:
        mission = _load_json(root / "governance" / "pm_mission.json")
    if sole_writer is None:
        sole_writer = _load_json(root / "governance" / "sole_writer.json")
    paths = git_changed_paths(root, staged_only=staged_only)
    return writer_drift_violations(
        paths, agent=agent, mission=mission, sole_writer=sole_writer
    )
