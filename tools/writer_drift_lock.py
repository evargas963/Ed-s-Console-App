"""Active-writer / one-canonical-worktree lock (RC-226, RC-452, RC-457).

The operator selects ACTIVE_WRITER per mission. Claude and Cursor may both
implement. Neither identity has permanent writer or auditor status.

Invariant: ONE CANONICAL WORKTREE TOTAL. ONE ACTIVE WRITER AT A TIME.
A second normal project worktree BLOCKS. When an in-progress mission assigns
active_writer≠current agent, the non-active agent must not mutate mission
scope_paths or hard-denylist product surfaces.

Fires:
  - PreToolUse via operating_process_lock.pm_mission_edit_violation
  - commit / pre-commit via writer_drift_violations on dirty paths
  - check_writer_no_drift / check_active_writer_law

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

#: Non-active-writer process surfaces (concurrency, not identity privilege).
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

#: Lock modules are ACTIVE_WRITER-editable. A non-active agent may encode locks only when
#: the mission grants non_writer_lock_encode_ok (or legacy cursor_lock_encode_ok).
LOCK_ENCODE_PATHS = frozenset({
    "tools/check_institutional_correctness.py",
    "tools/operating_process_lock.py",
    "tools/process_lock_guard.py",
    "tools/writer_drift_lock.py",
    "tools/rc_resolve_lock.py",
    "tools/operator_law_guard.py",
    "tools/honesty_guard.py",
    "tools/pretooluse_guard.py",
})

#: LOCK-1/LOCK-3: the ONLY pm_mission/sole_writer fields a non-operator agent may
#: change without an operator escape (status machinery — never the role split).
PM_STATUS_FIELDS = frozenset({
    "status", "note", "blocker", "updated_at", "held_commit",
    "approved_by", "approved_via", "approved_at",
})

#: LOCK-4 (RC-232): every SOD_DRIFT denial is recorded here; a denial without a same-window
#: OPEN RC row naming the mission_id + SOD_DRIFT owes a self-heal and BLOCKS further writes.
SOD_DRIFT_EVENTS_PATH = REPO / "governance" / "sod_drift_events.jsonl"


def hard_denylist_violation(rel: str, *, agent: str | None = None,
                            mission: dict | None = None,
                            sole: dict | None = None) -> str | None:
    """LOCK-1: non-writer touching the hard denylist BLOCKS regardless of scope."""
    try:
        from tools.hard_law_runtime import env_guard_is_disabled as _egd
    except ImportError:
        from hard_law_runtime import env_guard_is_disabled as _egd  # type: ignore
    if _egd("ED_WRITER_DRIFT_GUARD"):
        return None
    mission = mission if mission is not None else _load_json(PM_MISSION_PATH)
    if not mission_in_progress(mission):
        return None
    sole = sole if sole is not None else _load_json(SOLE_WRITER_PATH)
    writer = resolved_writer(mission, sole)
    agent = (agent or current_agent_role()).strip().lower()
    if not writer or agent == writer:
        return None
    rel = _norm(rel)
    if rel in HARD_DENYLIST_EXACT or rel in HARD_DENYLIST_TEST_MARKERS:
        return (f"SOD_DRIFT: hard-denylist surface {rel} — writer={writer!r}, agent={agent!r}. "
                f"Product/kill surfaces never open to the non-writer (LOCK-1/RC-232).")
    if rel in LOCK_ENCODE_PATHS and agent != writer:
        granted = (
            mission.get("non_writer_lock_encode_ok") is True
            or mission.get("cursor_lock_encode_ok") is True
        )
        if not granted:
            return (
                f"SOD_DRIFT: lock module {rel} — only ACTIVE_WRITER={writer!r} may encode locks "
                f"(agent={agent!r}). Operator may grant non_writer_lock_encode_ok."
            )
    return None


def pm_status_field_violations(rel: str, new_text: str, *, agent: str | None = None,
                               current_text: str | None = None) -> list[str]:
    """LOCK-1/LOCK-3: any non-operator agent may change ONLY status fields in
    pm_mission/sole_writer — role flips, scope expansion and remaining[] deletion
    BLOCK without an operator escape (# pm-status-ok: / # sod-role-ok:)."""
    rel = _norm(rel)
    if rel not in ("governance/pm_mission.json", "governance/sole_writer.json"):
        return []
    agent = (agent or current_agent_role()).strip().lower()
    if agent == "operator":
        return []
    if "# pm-status-ok:" in (new_text or "") or "# sod-role-ok:" in (new_text or ""):
        return []
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
    for role_field in ("writer", "active_writer", "pm", "auditor", "permanent_writer", "permanent_auditor"):
        if role_field in cur_doc and new_doc.get(role_field) != cur_doc.get(role_field):
            out.append(                    f"SOD_DRIFT: {rel} changes {role_field} "
                       f"{cur_doc.get(role_field)!r} -> {new_doc.get(role_field)!r} — ACTIVE_WRITER "
                       f"assignment is operator-only (escape: # sod-role-ok: in note).")
    old_scope = set(map(str, cur_doc.get("scope_paths") or []))
    new_scope = set(map(str, new_doc.get("scope_paths") or []))
    if new_scope - old_scope:
        out.append(f"SOD_DRIFT: {rel} expands scope_paths by {sorted(new_scope - old_scope)!r} "
                   f"— scope expansion is operator-only (escape: # pm-status-ok:).")
    if cur_doc.get("remaining") and not new_doc.get("remaining"):
        out.append(f"SOD_DRIFT: {rel} deletes remaining[] — dropping the work queue is "
                   f"operator-only (escape: # pm-status-ok:).")
    changed = {k for k in set(cur_doc) | set(new_doc)
               if cur_doc.get(k) != new_doc.get(k)}
    illegal = changed - PM_STATUS_FIELDS - {
        "writer", "active_writer", "pm", "auditor",
        "permanent_writer", "permanent_auditor", "scope_paths", "remaining",
    }
    if illegal:
        out.append(f"SOD_DRIFT: {rel} changes non-status fields {sorted(illegal)!r} — "
                   f"non-operator agents may touch status fields only "
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


def is_pm_allowlisted(rel: str) -> bool:
    """Process-surface allowlist — legal for the non-active agent (concurrency, not privilege)."""
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
    """Operator-selected ACTIVE_WRITER. `writer` is a synonym; `active_writer` wins."""
    m = mission if mission is not None else _load_json(PM_MISSION_PATH)
    s = sole if sole is not None else _load_json(SOLE_WRITER_PATH)
    return str(
        m.get("active_writer")
        or m.get("writer")
        or s.get("active_writer")
        or s.get("writer")
        or ""
    ).strip().lower()


_PERMANENT_IDENTITY_PHRASES = (
    "claude is sole writer",
    "cursor is an adversarial auditor only",
    "never writes feature/kill/implementation",
    "cursor=pm/auditor",
    "cursor = pm/auditor",
    "cursor prohibited from implementation",
    "claude as implementation authority",
)

#: Docs that materially control agent behavior — must not re-teach the superseded identity split.
_IDENTITY_DOC_SURFACES = (
    "AGENTS.md",
    "governance/AGENT_OPERATING_PROCESS_V1.md",
    "governance/PM_MANDATE.md",
    ".cursor/rules/07-cursor-pm.mdc",
    ".cursor/rules/08-no-writer-drift.mdc",
)


def permanent_identity_violations(
    *,
    sole: dict | None = None,
    mission: dict | None = None,
) -> list[str]:
    """Neither Claude nor Cursor may hold permanent writer or auditor privilege."""
    sole = sole if sole is not None else _load_json(SOLE_WRITER_PATH)
    mission = mission if mission is not None else _load_json(PM_MISSION_PATH)
    out: list[str] = []
    for doc, label in ((sole, "governance/sole_writer.json"), (mission, "governance/pm_mission.json")):
        if not isinstance(doc, dict):
            continue
        for field in ("permanent_writer", "permanent_auditor"):
            val = doc.get(field)
            if val not in (None, "", "null"):
                out.append(
                    f"ACTIVE_WRITER: {label} sets {field}={val!r} — no agent has permanent "
                    f"writer or auditor status. Operator selects ACTIVE_WRITER per mission."
                )
        text = " ".join(str(doc.get(k) or "") for k in ("standing_law", "note", "auditor")).lower()
        for phrase in _PERMANENT_IDENTITY_PHRASES:
            if phrase in text:
                out.append(
                    f"ACTIVE_WRITER: {label} still asserts identity-bound privilege {phrase!r} — "
                    f"superseded 2026-08-22. Use operator-selected ACTIVE_WRITER + "
                    f"one canonical worktree."
                )
                break
        aw = str(doc.get("active_writer") or "").strip().lower()
        wr = str(doc.get("writer") or "").strip().lower()
        if aw and wr and aw != wr:
            out.append(
                f"ACTIVE_WRITER: {label} active_writer={aw!r} disagrees with writer={wr!r} — "
                f"one assignment, no forked authority."
            )
    if str((sole or {}).get("pm") or "").strip().lower() not in ("", "operator"):
        out.append(
            "ACTIVE_WRITER: sole_writer.pm must be 'operator' — the operator remains "
            "governing authority."
        )
    if str((mission or {}).get("pm") or "").strip().lower() not in ("", "operator"):
        out.append(
            "ACTIVE_WRITER: pm_mission.pm must be 'operator' — the operator remains "
            "governing authority."
        )
    if sole.get("one_writer_per_worktree") is True:
        out.append(
            "ACTIVE_WRITER: sole_writer.one_writer_per_worktree=true permits multiple "
            "normal worktrees — operator law is ONE canonical worktree total "
            "(set one_canonical_worktree=true)."
        )
    if sole and sole.get("one_canonical_worktree") is not True:
        out.append(
            "ACTIVE_WRITER: sole_writer.one_canonical_worktree must be true — "
            "ONE canonical worktree total."
        )
    for rel in _IDENTITY_DOC_SURFACES:
        path = REPO / rel
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace").lower()
        except OSError:
            continue
        # Quoting the superseded sentence in order to void it is allowed.
        if "2026-08-22" in text and "supersede" in text:
            continue
        for phrase in _PERMANENT_IDENTITY_PHRASES:
            if phrase in text:
                out.append(
                    f"ACTIVE_WRITER: {rel} still teaches identity-bound privilege {phrase!r} — "
                    f"supersede it (operator 2026-08-22) or quote it only under a 2026-08-22 "
                    f"SUPERSEDED banner."
                )
                break
    return out


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
    try:
        from tools.hard_law_runtime import env_guard_is_disabled as _egd
    except ImportError:
        from hard_law_runtime import env_guard_is_disabled as _egd  # type: ignore
    if _egd("ED_WRITER_DRIFT_GUARD"):
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
                f"SOD_DRIFT: {writer} is ACTIVE_WRITER"
                if writer and agent != writer
                else "SOD_DRIFT: wrong-role edit"
            )
            out.append(
                f"{sod} — WRITER-DRIFT BLOCK: mission ACTIVE_WRITER={writer!r} but "
                f"agent={agent!r} touched scope path {rel} (mission_id={mid!r}) — "
                f"one canonical worktree; non-active agent cannot concurrently mutate it"
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


_DEFAULT_WORKTREE_EXCLUDES = (
    ".claude/worktrees",
    "/tmp/",
    "/var/tmp/",
    "tmp/",
    "deltagate-",
)


def _worktree_policy() -> dict:
    override = os.environ.get("ED_WORKTREE_POLICY_PATH", "").strip()
    path = Path(override) if override else REPO / "tools" / "agent_worktree_policy.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return doc if isinstance(doc, dict) else {}


def is_normal_project_worktree(path: Path | str, policy: dict | None = None) -> bool:
    """True for an ordinary project checkout. Measurement/tmp/.claude trees are not."""
    policy = policy if policy is not None else _worktree_policy()
    raw = str(Path(path).resolve() if isinstance(path, Path) else path)
    p = raw.replace("\\", "/")
    excludes = list(policy.get("exclude_path_substrings") or _DEFAULT_WORKTREE_EXCLUDES)
    for ex in excludes:
        if ex and ex.replace("\\", "/") in p:
            return False
    return True


def list_git_worktrees(repo: Path | None = None) -> list[Path]:
    """Return worktree paths. Tests may inject via ED_WORKTREE_LIST_PATH (JSON list)."""
    inject = os.environ.get("ED_WORKTREE_LIST_PATH", "").strip()
    if inject:
        try:
            raw = json.loads(Path(inject).read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return []
        if not isinstance(raw, list):
            return []
        return [Path(str(x)) for x in raw if str(x).strip()]
    root = repo or REPO
    try:
        r = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if r.returncode != 0:
        return []
    out: list[Path] = []
    for line in (r.stdout or "").splitlines():
        if line.startswith("worktree "):
            out.append(Path(line[len("worktree "):].strip()))
    return out


def canonical_worktree_violations(
    *,
    repo: Path | None = None,
    worktrees: list[Path] | None = None,
    policy: dict | None = None,
    require: bool | None = None,
) -> list[str]:
    """ONE canonical worktree total. Second normal project worktree → BLOCK.

    Zero / unreadable identity → BLOCK when execution requires one (canonical mode
    or sole_writer.one_canonical_worktree). Injected lists never touch live git.
    """
    policy = policy if policy is not None else _worktree_policy()
    mode = str(policy.get("mode") or "").strip().lower()
    sole = _load_json(SOLE_WRITER_PATH)
    needed = require
    if needed is None:
        needed = (
            mode == "canonical"
            or policy.get("canonical_worktree_required") is True
            or sole.get("one_canonical_worktree") is True
        )
    if not needed:
        return []
    trees = worktrees if worktrees is not None else list_git_worktrees(repo)
    if worktrees is None and not trees and not os.environ.get("ED_WORKTREE_LIST_PATH"):
        return [
            "CANONICAL_WORKTREE: zero/unreadable worktree identity — execution "
            "requires exactly one canonical project worktree"
        ]
    normal = [p for p in trees if is_normal_project_worktree(p, policy)]
    max_n = int(policy.get("max_normal_project_worktrees") or 1)
    if len(normal) == 0:
        return [
            "CANONICAL_WORKTREE: zero normal project worktrees — execution "
            "requires exactly one canonical identity"
        ]
    if len(normal) > max_n:
        shown = [str(p) for p in normal[:6]]
        return [
            f"CANONICAL_WORKTREE: {len(normal)} normal project worktrees {shown} — "
            f"ONE canonical worktree total (second normal worktree BLOCKS)"
        ]
    suffix = str(policy.get("claude_root_suffix") or "-Claude")
    if policy.get("claude_suffix_is_legacy_forbidden") is True:
        only = Path(normal[0])
        if only.name.endswith(suffix) and len(normal) == 1:
            return [
                "CANONICAL_WORKTREE: the only checkout ends with "
                f"{suffix!r} — leftover isolated architecture; the ACTIVE_WRITER "
                "uses the one canonical tree, not a sibling -Claude tree"
            ]
    return []
