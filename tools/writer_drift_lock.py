"""Architecture A control-authority lock (RC-226 remnant; RC-454 operator-writer).

Operator selects the working AI at the workflow boundary (which AI they run).
Persisted writer/auditor fields are history, not authorization.

This module BLOCKs only control-authority rewrites by an assigned principal
(ED_AGENT_ROLE set). Ordinary product paths are not vendor-gated.

Fires:
  - PreToolUse via process_lock_guard / control_authority_violation
  - commit / pre-commit via writer_drift_violations on dirty rails
  - check_writer_no_drift in check_institutional_correctness.py

Empty ED_AGENT_ROLE is operator/CI (abstain), never a guessed vendor.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

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

#: Non-writer may touch operational metadata only. Lock/guard/hook/CI files are
#: NOT on this list — those are control-authority surfaces denied to every agent.
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
    "tools/rehab_daily_scan.py",
    ".cursor/rules/07-cursor-pm.mdc",
    ".cursor/rules/08-no-writer-drift.mdc",
    "ACTIVE_PROGRAM.md",
    "AGENTS.md",
})

PM_ALLOWLIST_PREFIXES = (
    ".cursor/rules/",
)

#: Status-only keys an assigned principal may change on leftover mission JSON.
#: writer/auditor are not authorization; flipping them must not grant rails.
PM_STATUS_FIELDS = frozenset({
    "status", "note", "blocker", "updated_at", "held_commit",
    "approved_by", "approved_via", "approved_at",
})

#: Files that define CI/merge/hook/assignment rails. Derived from actual call
#: paths (hooks.json, settings.json, required workflows, assignment JSON).
CONTROL_AUTHORITY_EXACT = frozenset({
    ".github/CODEOWNERS",
    ".pre-commit-config.yaml",
    ".cursor/hooks.json",
    ".claude/settings.json",
    "governance/operator_go.json",
    "governance/operator_grants.json",
    "tools/check_institutional_correctness.py",
    "tools/check_delta_adds_no_debt.py",
    "tools/precommit_institutional.py",
    "tools/check_market_correctness.py",
    "tools/check_institutional_closure_gate.py",
    "tools/check_no_grep_subprocess.py",
    "tests/test_architecture_a_bypass_class_v1.py",
    "tests/test_writer_drift_lock_v1.py",
    "tests/test_control_authority_surfaces_v1.py",
    "tests/test_architecture_a_operator_writer_authority_v1.py",
})
CONTROL_AUTHORITY_PREFIXES = (
    ".github/workflows/",
)

#: LOCK-4 (RC-232): every SOD_DRIFT denial is recorded here; a denial without a same-window
#: OPEN RC row naming the mission_id + SOD_DRIFT owes a self-heal and BLOCKS further writes.
SOD_DRIFT_EVENTS_PATH = REPO / "governance" / "sod_drift_events.jsonl"


def hard_denylist_violation(rel: str, *, agent: str | None = None,
                            mission: dict | None = None,
                            sole: dict | None = None) -> str | None:
    """Product hard-denylist retired (RC-454). Rails still BLOCK via control_authority."""
    return control_authority_violation(rel, agent=agent)


def pm_status_field_violations(rel: str, new_text: str, *, agent: str | None = None,
                               current_text: str | None = None) -> list[str]:
    """Leftover mission JSON: assigned agents may not steal pm or expand scope.

    writer/auditor flips are not authorization and are not blocked here — setting
    writer to self must not grant control-authority privilege (proven at the rail seam).
    pm=operator is operator authority and cannot be changed by an assigned AI.
    """
    rel = _norm(rel)
    if rel not in ("governance/pm_mission.json", "governance/sole_writer.json"):
        return []
    agent = (agent or current_agent_role()).strip().lower()
    try:
        new_doc = json.loads(new_text)
    except (ValueError, json.JSONDecodeError):
        return [f"SOD_DRIFT: {rel} proposed content is not valid JSON — a corrupt role file "
                f"is how three mid-write deaths poisoned SoD on 2026-08-03."]
    if not agent:
        return []
    cur_text = current_text
    if cur_text is None:
        try:
            cur_text = (REPO / rel).read_text(encoding="utf-8")
        except OSError:
            cur_text = "{}"
    try:
        cur_doc = json.loads(cur_text)
    except (ValueError, json.JSONDecodeError):
        cur_doc = {}
    out: list[str] = []
    cur_pm = str(cur_doc.get("pm") or "").strip().lower()
    new_pm = str(new_doc.get("pm") or "").strip().lower()
    if cur_pm == "operator" and new_pm != "operator":
        out.append(
            f"SOD_DRIFT: {rel} changes pm={cur_pm!r} to {new_pm!r} — "
            f"pm=operator is operator authority and cannot be reassigned by agent={agent!r}."
        )
    old_scope = set(map(str, cur_doc.get("scope_paths") or []))
    new_scope = set(map(str, new_doc.get("scope_paths") or []))
    if new_scope - old_scope:
        out.append(f"SOD_DRIFT: {rel} expands scope_paths by {sorted(new_scope - old_scope)!r} "
                   f"— scope expansion is operator-only and cannot be self-granted.")
    if cur_doc.get("remaining") and not new_doc.get("remaining"):
        out.append(f"SOD_DRIFT: {rel} deletes remaining[] — dropping the work queue is "
                   f"operator-only and cannot be self-granted.")
    return out


def record_sod_drift(messages: list[str], *, agent: str | None = None,
                     mission: dict | None = None) -> None:
    """LOCK-4: persist every drift denial so the owed self-heal is checkable."""
    if not messages:
        return
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return  # synthetic test denials must never pollute the real self-heal ledger
    mission = mission if mission is not None else _load_json(PM_MISSION_PATH)
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
    name = rel.rsplit("/", 1)[-1]
    if rel.startswith("tools/") and (
        name.endswith("_guard.py")
        or name.endswith("_lock.py")
        or name in {
            "check_institutional_correctness.py",
            "precommit_institutional.py",
            "operating_process_lock.py",
            "check_delta_adds_no_debt.py",
            "check_market_correctness.py",
            "check_institutional_closure_gate.py",
            "check_no_grep_subprocess.py",
        }
    ):
        return True
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


def is_pm_allowlisted(rel: str) -> bool:
    """Operational metadata the non-writer may touch. Not a control-authority grant."""
    rel = _norm(rel)
    if is_control_authority_surface(rel):
        return False
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
