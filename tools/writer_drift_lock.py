"""Writer no-drift mechanical lock (RC-226).

When an in-progress PM mission (or sole_writer) assigns writer≠current agent,
the non-writer must not modify mission scope_paths. Cursor=PM/auditor;
Claude=sole writer is the standing model — drift into writer work is a BLOCK,
not a chat reminder.

Fires:
  - PreToolUse via operating_process_lock.pm_mission_edit_violation
  - commit / pre-commit via writer_drift_violations on dirty paths
  - check_writer_no_drift in check_institutional_correctness.py

Architecture A (RC-450/RC-453): not subject-disableable. Privilege follows the current
assignment (writer / auditor), not a vendor string. Any assigned principal — including
the writer — cannot rewrite control-authority surfaces. Empty ED_AGENT_ROLE is
operator/CI (abstain), never a guessed vendor.
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

#: LOCK-1 HARD DENYLIST (RC-232): ALWAYS blocked for the non-writer while a mission is in
#: progress — regardless of scope_paths. These are the product/kill surfaces the 2026-08-03
#: pipeline collision destroyed.
HARD_DENYLIST_EXACT = frozenset({
    "static/chart.html",
    "server.py",
    "market_context.py",
    "db.py",
})
HARD_DENYLIST_TEST_MARKERS = (
    "tests/test_levels_single_producer_v1.py",
    "tests/test_market_context_fetch_fail_closed.py",
    "tests/test_collect_window_law_v1.py",
)

#: LOCK-1/LOCK-3: the ONLY pm_mission/sole_writer fields a non-operator principal
#: may change (status machinery — never the role split or the scope).
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
    """LOCK-1: non-writer touching the hard denylist BLOCKS regardless of scope.

    Control-authority surfaces BLOCK every assigned principal, including the writer.
    """
    agent = (agent or current_agent_role()).strip().lower()
    rel = _norm(rel)
    if agent:
        auth = control_authority_violation(rel, agent=agent)
        if auth:
            return auth
    mission = mission if mission is not None else _load_json(PM_MISSION_PATH)
    if not mission_in_progress(mission):
        return None
    sole = sole if sole is not None else _load_json(SOLE_WRITER_PATH)
    writer = resolved_writer(mission, sole)
    if not writer or not agent or agent == writer:
        return None
    if rel in HARD_DENYLIST_EXACT or rel in HARD_DENYLIST_TEST_MARKERS:
        return (f"SOD_DRIFT: hard-denylist surface {rel} — writer={writer!r}, agent={agent!r}. "
                f"Product/kill surfaces never open to the non-writer (LOCK-1/RC-232).")
    return None


def pm_status_field_violations(rel: str, new_text: str, *, agent: str | None = None,
                               current_text: str | None = None) -> list[str]:
    """LOCK-1/LOCK-3: Cursor may change ONLY status fields in pm_mission/sole_writer.
    Role flips, scope expansion and remaining[] deletion BLOCK. No comment marker
    and no JSON flag can authorize the subject to become writer."""
    rel = _norm(rel)
    if rel not in ("governance/pm_mission.json", "governance/sole_writer.json"):
        return []
    agent = (agent or current_agent_role()).strip().lower()
    try:
        new_doc = json.loads(new_text)
    except (ValueError, json.JSONDecodeError):
        return [f"SOD_DRIFT: {rel} proposed content is not valid JSON — a corrupt role file "
                f"is how three mid-write deaths poisoned SoD on 2026-08-03."]
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
    old_writer = str(cur_doc.get("writer") or "").strip().lower()
    new_writer = str(new_doc.get("writer") or "").strip().lower()
    if not agent:
        return []
    if new_writer and new_writer == agent and new_writer != old_writer:
        out.append(
            f"SOD_DRIFT: {rel} sets writer={new_writer!r} while agent={agent!r} — "
            f"the subject cannot authorize itself as writer (Architecture A / RC-450)."
        )
    for role_field in ("writer", "pm", "auditor"):
        if role_field in cur_doc and new_doc.get(role_field) != cur_doc.get(role_field):
            out.append(f"SOD_DRIFT: {rel} changes {role_field} "
                       f"{cur_doc.get(role_field)!r} -> {new_doc.get(role_field)!r} — role flips "
                       f"are operator-only and cannot be self-granted.")
    old_scope = set(map(str, cur_doc.get("scope_paths") or []))
    new_scope = set(map(str, new_doc.get("scope_paths") or []))
    if new_scope - old_scope:
        out.append(f"SOD_DRIFT: {rel} expands scope_paths by {sorted(new_scope - old_scope)!r} "
                   f"— scope expansion is operator-only and cannot be self-granted.")
    if cur_doc.get("remaining") and not new_doc.get("remaining"):
        out.append(f"SOD_DRIFT: {rel} deletes remaining[] — dropping the work queue is "
                   f"operator-only and cannot be self-granted.")
    changed = {k for k in set(cur_doc) | set(new_doc)
               if cur_doc.get(k) != new_doc.get(k)}
    illegal = changed - PM_STATUS_FIELDS - {"writer", "pm", "auditor", "scope_paths", "remaining"}
    if illegal:
        out.append(f"SOD_DRIFT: {rel} changes non-status fields {sorted(illegal)!r} — "
                   f"assigned principals may touch status fields only "
                   f"({sorted(PM_STATUS_FIELDS)!r}).")
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


def resolved_writer(mission: dict | None = None, sole: dict | None = None) -> str:
    m = mission if mission is not None else _load_json(PM_MISSION_PATH)
    s = sole if sole is not None else _load_json(SOLE_WRITER_PATH)
    return str(m.get("writer") or s.get("writer") or "").strip().lower()


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
    """Return BLOCK messages when non-writer dirty paths hit mission scope."""
    mission = mission if mission is not None else _load_json(PM_MISSION_PATH)
    sole = sole_writer if sole_writer is not None else _load_json(SOLE_WRITER_PATH)
    if not mission_in_progress(mission):
        return []
    writer = resolved_writer(mission, sole)
    if not writer:
        return []
    agent = (agent or current_agent_role()).strip().lower()
    if not agent:
        return []
    scopes = mission.get("scope_paths") or ["*"]
    if not isinstance(scopes, list):
        scopes = ["*"]
    mid = mission.get("mission_id")
    out: list[str] = []
    for raw in changed_paths:
        rel = _norm(raw)
        if not rel:
            continue
        auth = control_authority_violation(rel, agent=agent)
        if auth:
            out.append(auth)
            continue
        if agent == writer:
            continue
        if is_pm_allowlisted(rel):
            continue
        if path_in_mission_scope(rel, scopes):
            sod = (
                f"SOD_DRIFT: {writer} is sole writer"
                if writer and agent != writer
                else "SOD_DRIFT: wrong-role edit"
            )
            out.append(
                f"{sod} — WRITER-DRIFT BLOCK: mission writer={writer!r} but agent={agent!r} "
                f"touched scope path {rel} (mission_id={mid!r}) — assignment owns "
                f"scope_paths; privilege is not a vendor name"
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
