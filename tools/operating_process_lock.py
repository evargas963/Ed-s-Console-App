"""Operating-process mechanical lock (RC-217).

Machine-checkable predicates for governance/AGENT_OPERATING_PROCESS_V1.md.
The charter is operator-facing; THIS module BLOCKs — .md alone is not a lock.

Child of RC-215 (index≠WT stash-strip), RC-216 (DISK_ONLY vs LIVE), RC-210 (dual-writer thrash).

Minimum BLOCK surfaces:
  (a) Write/Edit protected paths when sole_writer ≠ current agent
  (b) Stop on COMPLETE/LIVE/one-intentional-tree claims while index≠WT or live PID predates db.py gate
  (c) git commit when index≠WT on staged enforcement paths or staged CHECKS not on HEAD without operator GO
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

SOLE_WRITER_PATH = REPO / "governance" / "sole_writer.json"
OPERATOR_GO_PATH = REPO / "governance" / "operator_go.json"
PM_MISSION_PATH = REPO / "governance" / "pm_mission.json"
CHECKER_REL = "tools/check_institutional_correctness.py"
DB_REL = "db.py"

# writer_drift_lock does not import this module (no cycle).
from tools import writer_drift_lock as WDL  # noqa: E402

#: Paths where index≠WT is catastrophic (enforcement / collect seam / locks).
ENFORCEMENT_PATHS: tuple[str, ...] = (
    CHECKER_REL,
    DB_REL,
    "tools/honesty_guard.py",
    "tools/plus_player_locks.py",
    "tools/find_prove_locks.py",
    "tools/pretooluse_guard.py",
    "tools/operator_law_guard.py",
    "tools/stop_guard.py",
    "tools/operating_process_lock.py",
    "tools/process_lock_guard.py",
    "calibration/repair_canonical_1m_shared.py",
    "calibration/repair_canonical_1m_bars_for_outcomes.py",
)

#: Sole-writer dual-edit race — Cursor must not touch while another agent holds writer.
PROTECTED_PATHS: tuple[str, ...] = ENFORCEMENT_PATHS + (
    "calibration/build_trusted_anchor_proof_dataset.py",
    "calibration/run_production_accumulation_validation.py",
)

#: LOCK-2 (RC-231): the tree-destructive git CLASS, not just `reset --hard`. Three wipes on
#: 2026-08-03 (RC-210 x2, RC-229) used soft forms the literal-match ban never saw. A command
#: matching a destructive verb AND touching a protected/product path (or bare, whole-tree
#: forms) BLOCKS at PreToolUse in EVERY session wired to process_lock_guard.
_RESET_GUARD_RE = __import__("re").compile(
    r"\bgit\s+(?:-\S+\s+)*(reset\b|restore\b|checkout\s+(?:\S+\s+)*--\s|stash\b)", __import__("re").I)
_RESET_GUARD_SAFE_RE = __import__("re").compile(
    r"\bgit\s+(?:-\S+\s+)*(restore\s+--staged\b(?!.*--worktree)|stash\s+list\b|checkout\s+-b\b)",
    __import__("re").I)


def reset_guard_violations(command: str) -> list[str]:
    """LOCK-2: BLOCK tree-destructive git against protected/product scope (RC-231).

    Escapes: ED_RESET_GUARD=off (operator, visible) or operator_go scope git_reset_product.
    `git restore --staged` (index-only), `git stash list`, `git checkout -b` stay legal.
    """
    if os.environ.get("ED_RESET_GUARD", "").strip().lower() in ("off", "0", "false"):
        return []
    if operator_go_granted("git_reset_product"):
        return []
    cmd = command or ""
    if not _RESET_GUARD_RE.search(cmd) or _RESET_GUARD_SAFE_RE.search(cmd):
        return []
    touched = [p for p in PROTECTED_PATHS if p in cmd]
    mission = _load_json(PM_MISSION_PATH) or {}
    for sp in (mission.get("scope_paths") or []):
        if isinstance(sp, str) and sp.strip("*/") and sp in cmd:
            touched.append(sp)
    bare = not any(tok in cmd for tok in (" -- ", ".py", ".html", ".json"))
    if touched or bare:
        return [
            "RESET_GUARD (LOCK-2/RC-231): tree-destructive git "
            f"({'paths: ' + ', '.join(sorted(set(touched))[:4]) if touched else 'bare/whole-tree form'}) "
            "— three 2026-08-03 wipes used exactly this class. Escape: ED_RESET_GUARD=off "
            "(operator) or operator_go scope git_reset_product."
        ]
    return []

#: Process-lock edits to governance process files are always allowed (compliance path).
PROCESS_ALLOWED_PREFIXES = (
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
)

#: Product paths that require an active PM mission (RC-219) in addition to sole_writer.
MISSION_GATED_PREFIXES = (
    "db.py",
    "server.py",
    "time_et.py",
    "static/",
    "calibration/",
    "tools/check_institutional_correctness.py",
    "tools/honesty_guard.py",
    "tools/plus_player_locks.py",
    "tools/find_prove_locks.py",
    "tools/ui_mockup_lock.py",
    "tools/pretooluse_guard.py",
    "tools/operator_law_guard.py",
    "math_exposure_core.py",
    "math_levels.py",
    "liquidity_value_engine.py",
    "liquidity_models.py",
)

_COMPLETION_CLAIM = re.compile(
    r"\b("
    r"LIVE_ENFORCED|live write path gated|one intentional tree|iceberg ready|"
    r"index=worktree|index parity (?:clean|pass|ok)|ready to commit|all green|"
    r"mechanically locked and green|COMPLETE(?:/CLOSED)?(?:\s+for|\s+on|\s+—|\s+-|\s*:|\s+the|\s+collect|\s+live|\s+lock)"
    r")\b",
    re.I,
)
_LIVE_RC_CLAIM = re.compile(
    r"\b(LIVE_ENFORCED|live write path gated|live enforcement|runtime enforced)\b",
    re.I,
)
_DISK_ONLY_TOKEN = re.compile(r"\bDISK_ONLY_UNTIL_RESTART\b", re.I)


def _git(args: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd or REPO),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )


def _rel(p: str | Path) -> str:
    try:
        return Path(p).resolve().relative_to(REPO).as_posix()
    except (ValueError, OSError):
        return Path(p).as_posix().replace("\\", "/")


def current_agent_role() -> str:
    """Cursor hooks default to cursor; Claude should set ED_AGENT_ROLE=claude."""
    role = os.environ.get("ED_AGENT_ROLE", "").strip().lower()
    if role in ("cursor", "claude"):
        return role
    return "cursor"


def _load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def sole_writer_record() -> dict:
    doc = _load_json(SOLE_WRITER_PATH)
    return doc if isinstance(doc, dict) else {}


def operator_go_record() -> dict:
    doc = _load_json(OPERATOR_GO_PATH)
    return doc if isinstance(doc, dict) else {}


def operator_go_granted(scope: str | None = None) -> bool:
    doc = operator_go_record()
    if not doc.get("granted"):
        return False
    scopes = doc.get("scope") or []
    if not isinstance(scopes, list):
        return False
    if scope is None:
        return bool(scopes)
    norm = {str(s).strip().lower() for s in scopes}
    return scope.lower() in norm or "all" in norm or "staged_lock_surface" in norm


def enforcement_paths(repo: Path | None = None) -> list[str]:
    root = repo or REPO
    paths = list(ENFORCEMENT_PATHS)
    lock_dir = root / "tools"
    if lock_dir.is_dir():
        for p in sorted(lock_dir.glob("*_lock*.py")):
            rel = p.relative_to(root).as_posix()
            if rel not in paths:
                paths.append(rel)
    return paths


def _blob_hash(repo: Path, path: Path) -> str | None:
    if not path.is_file():
        return None
    r = subprocess.run(
        ["git", "hash-object", str(path)],
        cwd=str(repo),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
    )
    return r.stdout.strip() if r.returncode == 0 else None


def _index_hash(repo: Path, rel: str) -> str | None:
    r = _git(["ls-files", "-s", "--", rel], cwd=repo)
    if r.returncode != 0 or not r.stdout.strip():
        return None
    return r.stdout.strip().split()[1]


def index_worktree_mismatches(
    repo: Path | None = None,
    *,
    paths: list[str] | None = None,
    only_staged: bool = False,
) -> list[str]:
    """Return human-readable violations where WT blob ≠ index blob."""
    root = repo or REPO
    out: list[str] = []
    check = paths or enforcement_paths(root)
    if only_staged:
        sr = _git(["diff", "--cached", "--name-only"], cwd=root)
        if sr.returncode != 0:
            return ["git diff --cached unavailable"]
        staged = {ln.strip().replace("\\", "/") for ln in sr.stdout.splitlines() if ln.strip()}
        check = [p for p in check if p in staged]
    for rel in check:
        fp = root / rel
        idx = _index_hash(root, rel)
        if idx is None:
            continue
        wt = _blob_hash(root, fp)
        if wt is None:
            out.append(f"{rel}: tracked in index but missing from worktree")
            continue
        if wt != idx:
            out.append(f"{rel}: index={idx[:12]}… worktree={wt[:12]}… (index≠WT)")
    return out


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _head_text(repo: Path, rel: str) -> str | None:
    r = _git(["show", f"HEAD:{rel}"], cwd=repo)
    return r.stdout if r.returncode == 0 else None


def _parse_enforced_checks(source: str) -> set[str]:
    """Extract enforced check names from CHECKS = [...] in checker source."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "CHECKS":
                    if not isinstance(node.value, ast.List):
                        continue
                    names: set[str] = set()
                    for elt in node.value.elts:
                        if isinstance(elt, ast.Tuple) and len(elt.elts) >= 3:
                            name_node = elt.elts[0]
                            en_node = elt.elts[2]
                            if (
                                isinstance(name_node, ast.Constant)
                                and isinstance(name_node.value, str)
                                and isinstance(en_node, ast.Constant)
                                and en_node.value is True
                            ):
                                names.add(name_node.value)
                    return names
    return set()


def staged_enforced_checks_not_on_head(repo: Path | None = None) -> list[str]:
    """CHECKS enforced in WT/index checker but absent from HEAD checker."""
    root = repo or REPO
    sr = _git(["diff", "--cached", "--name-only", "--", CHECKER_REL], cwd=root)
    if sr.returncode != 0 or CHECKER_REL not in sr.stdout:
        return []
    wt_text = _read_text(root / CHECKER_REL)
    head_text = _head_text(root, CHECKER_REL)
    if not wt_text:
        return [f"{CHECKER_REL} unreadable in worktree"]
    wt_checks = _parse_enforced_checks(wt_text)
    head_checks = _parse_enforced_checks(head_text or "")
    delta = sorted(wt_checks - head_checks)
    if not delta:
        return []
    return [f"staged-only ENFORCED check(s) not on HEAD: {', '.join(delta)}"]


def precommit_orphan_patch_warnings(repo: Path | None = None) -> list[str]:
    """Best-effort: pre-commit stash patch left in cache may mean incomplete restore (RC-215)."""
    warnings: list[str] = []
    candidates: list[Path] = []
    local = os.environ.get("LOCALAPPDATA")
    if local:
        cache = Path(local) / "pre-commit" / "patch"
        if cache.is_dir():
            candidates.extend(cache.glob("patch*"))
    home_cache = Path.home() / ".cache" / "pre-commit" / "patch"
    if home_cache.is_dir():
        candidates.extend(home_cache.glob("patch*"))
    recent: list[Path] = []
    now = datetime.now(timezone.utc).timestamp()
    for p in candidates:
        try:
            if now - p.stat().st_mtime < 24 * 3600:
                recent.append(p)
        except OSError:
            continue
    for p in sorted(recent)[-3:]:
        warnings.append(
            f"pre-commit orphan patch candidate {p.name} (mtime within 24h) — "
            f"verify index=WT before claiming green; see RC-215"
        )
    return warnings


def db_has_collect_window_gate(repo: Path | None = None) -> bool:
    root = repo or REPO
    text = _read_text(root / DB_REL) or ""
    return "is_collect_window_bar_end_ts_utc" in text and "RC-183" in text


def _listening_pid(port: int = 8000) -> int | None:
    if sys.platform == "win32":
        r = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
        )
        if r.returncode != 0:
            return None
        for line in r.stdout.splitlines():
            if f":{port}" in line and "LISTENING" in line.upper():
                parts = line.split()
                try:
                    return int(parts[-1])
                except (ValueError, IndexError):
                    continue
        return None
    r = subprocess.run(
        ["ss", "-ltnp", f"sport = :{port}"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if r.returncode != 0:
        return None
    m = re.search(r"pid=(\d+)", r.stdout)
    return int(m.group(1)) if m else None


def _process_start_epoch(pid: int) -> float | None:
    if sys.platform == "win32":
        r = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                f"(Get-Process -Id {pid} -ErrorAction SilentlyContinue).StartTime.ToUniversalTime().Subtract([datetime]'1970-01-01').TotalSeconds",
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        if r.returncode != 0 or not r.stdout.strip():
            return None
        try:
            return float(r.stdout.strip())
        except ValueError:
            return None
    proc = Path(f"/proc/{pid}")
    if not proc.is_dir():
        return None
    try:
        stat = proc.stat()
        return float(stat.st_mtime)
    except OSError:
        return None


def live_collect_disk_only(repo: Path | None = None, port: int = 8000) -> str | None:
    """Return violation message when disk has gate but live process predates db.py mtime."""
    root = repo or REPO
    if not db_has_collect_window_gate(root):
        return None
    db_path = root / DB_REL
    try:
        db_mtime = db_path.stat().st_mtime
    except OSError:
        return None
    pid = _listening_pid(port)
    if pid is None:
        return None
    start = _process_start_epoch(pid)
    if start is None:
        return f":{port} listener PID {pid} found but start time unreadable — treat collect gate as DISK_ONLY_UNTIL_RESTART"
    if start < db_mtime - 1.0:
        return (
            f"DISK_ONLY: db.py gate mtime newer than :{port} PID {pid} start "
            f"(process predates collect-window seam — restart required for LIVE_ENFORCED)"
        )
    return None


def pm_mission_record() -> dict:
    doc = _load_json(PM_MISSION_PATH)
    return doc if isinstance(doc, dict) else {}


def _mission_gates_path(rel: str) -> bool:
    rel = rel.replace("\\", "/")
    for p in MISSION_GATED_PREFIXES:
        if p.endswith("/"):
            if rel.startswith(p):
                return True
        elif rel == p:
            return True
    if rel in PROTECTED_PATHS or rel.startswith("calibration/repair_"):
        return True
    return False


def _mission_scope_allows(rel: str, scope_paths: list) -> bool:
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


def pm_mission_edit_violation(rel: str, agent: str | None = None) -> str | None:
    """RC-219 + RC-226: product edits need an in-progress mission; non-writer cannot touch scope."""
    if os.environ.get("ED_PM_MISSION_GUARD", "").strip().lower() in ("off", "0", "false"):
        return None
    rel = rel.replace("\\", "/")
    if rel in PROCESS_ALLOWED_PREFIXES or WDL.is_pm_allowlisted(rel):
        return None
    mission = pm_mission_record()
    status = str(mission.get("status") or "idle").strip().lower()
    agent = (agent or current_agent_role()).lower()
    writer = str(mission.get("writer") or sole_writer_record().get("writer") or "").strip().lower()
    scopes = mission.get("scope_paths") or ["*"]
    if not isinstance(scopes, list):
        scopes = ["*"]
    in_prog = WDL.mission_in_progress(mission)

    # RC-226: in-progress mission — non-writer blocked on scope_paths (and gated product).
    if in_prog and writer and agent != writer:
        if sole_writer_record().get("cursor_edit_ok") is True and agent == "cursor":
            return None
        if WDL.path_in_mission_scope(rel, scopes) or _mission_gates_path(rel):
            return (
                f"SOD_DRIFT: {writer} is sole writer — WRITER-DRIFT BLOCK: "
                f"mission writer={writer!r} but agent={agent!r} — "
                f"path {rel} blocked (mission_id={mission.get('mission_id')!r}; "
                f"status={status!r}). Cursor=PM/auditor; sole writer owns scope_paths."
            )
        return None

    # Idle / not in-progress: block mission-gated product for everyone (RC-219).
    if not in_prog:
        if rel.startswith("tests/") or rel.startswith("reports/"):
            return None
        if rel.startswith("governance/") and not _mission_gates_path(rel):
            return None
        if not _mission_gates_path(rel):
            return None
        return (
            f"PM-FIRST BLOCK: no in-progress mission (governance/pm_mission.json status={status!r}) — "
            f"run change requests through Cursor PM; do not edit {rel} until a mission is opened"
        )

    # Named writer on in-progress mission: stay inside scope_paths for gated surfaces.
    if rel.startswith("tests/") or rel.startswith("reports/"):
        if WDL.path_in_mission_scope(rel, scopes) or not _mission_gates_path(rel):
            return None
    if not _mission_gates_path(rel) and not WDL.path_in_mission_scope(rel, scopes):
        return None
    if not _mission_scope_allows(rel, scopes):
        return (
            f"PM-FIRST BLOCK: {rel} outside mission scope_paths={scopes!r} "
            f"(mission_id={mission.get('mission_id')!r})"
        )
    return None


def sole_writer_edit_violation(rel: str, agent: str | None = None) -> str | None:
    rel = rel.replace("\\", "/")
    pm_msg = pm_mission_edit_violation(rel, agent=agent)
    if pm_msg:
        return pm_msg
    if rel in PROCESS_ALLOWED_PREFIXES or rel.startswith("tests/"):
        return None
    if rel.startswith("governance/") and rel not in PROTECTED_PATHS:
        return None
    if rel.startswith("reports/"):
        return None
    writer = str(sole_writer_record().get("writer") or "").strip().lower()
    if not writer:
        return None
    agent = (agent or current_agent_role()).lower()
    if agent == writer:
        return None
    if rel not in PROTECTED_PATHS and not any(
        rel == p or rel.startswith(p.rstrip("/") + "/") for p in PROTECTED_PATHS
    ):
        # Prefix match for calibration/*
        if not rel.startswith("calibration/repair_"):
            return None
    if sole_writer_record().get("cursor_edit_ok") is True and agent == "cursor":
        return None
    return (
        f"sole_writer={writer!r} but current agent={agent!r} — "
        f"protected path {rel} is dual-edit BLOCKED (governance/sole_writer.json)"
    )


def completion_claim_violations(text: str, repo: Path | None = None) -> list[str]:
    """BLOCK COMPLETE/LIVE/parity claims while measurable preconditions fail."""
    if not text or not _COMPLETION_CLAIM.search(text):
        return []
    root = repo or REPO
    out: list[str] = []
    mism = index_worktree_mismatches(root)
    if mism:
        out.append(
            "completion claim while index≠WT on enforcement paths: "
            + "; ".join(mism[:5])
        )
    disk = live_collect_disk_only(root)
    if disk and _LIVE_RC_CLAIM.search(text) and not _DISK_ONLY_TOKEN.search(text):
        out.append(f"completion claim LIVE_ENFORCED while {disk}")
    staged_head = staged_enforced_checks_not_on_head(root)
    if staged_head and re.search(r"\b(iceberg ready|ready to commit|one intentional tree)\b", text, re.I):
        if not operator_go_granted("staged_lock_surface"):
            out.extend(staged_head)
    # RC-228: COMPLETE claims while the active mission still owns OPEN RC rows.
    if re.search(r"\b(mission\s+complete|done_criteria|COMPLETE(?:/CLOSED)?)\b", text, re.I):
        try:
            from tools.rc_resolve_lock import open_rcs_owned_by_mission
        except ImportError:
            from rc_resolve_lock import open_rcs_owned_by_mission  # type: ignore
        mission = pm_mission_record()
        mid = str(mission.get("mission_id") or "").strip()
        rc_path = root / "governance" / "root_cause_log.md"
        if mid and rc_path.is_file():
            open_ids = open_rcs_owned_by_mission(
                mid, rc_path.read_text(encoding="utf-8").splitlines()
            )
            if open_ids:
                out.append(
                    f"completion claim while OPEN RC(s) still name mission {mid!r}: "
                    f"{', '.join(open_ids)} (RC-228 — CLOSE or honest PARTIAL+OUT-OF-SCOPE first)"
                )
    return out


def commit_violations(repo: Path | None = None) -> list[str]:
    """Predicates for git commit PreToolUse / pre-commit."""
    root = repo or REPO
    out: list[str] = []
    mism = index_worktree_mismatches(root, only_staged=True)
    if mism:
        out.append("commit BLOCKED: staged enforcement path index≠WT — " + "; ".join(mism))
    staged_head = staged_enforced_checks_not_on_head(root)
    if staged_head and not operator_go_granted("staged_lock_surface"):
        out.extend(f"commit BLOCKED: {msg} — set governance/operator_go.json granted=true" for msg in staged_head)
    out.extend(precommit_orphan_patch_warnings(root))
    # RC-226: non-writer staging scope_paths → commit BLOCK (Shell-bypass backstop).
    out.extend(
        WDL.live_writer_drift_violations(
            root, agent=current_agent_role(), staged_only=True
        )
    )
    return out


def measure_report(repo: Path | None = None) -> dict:
    """MEASURE-before-claim artifact for operators."""
    root = repo or REPO
    paths = enforcement_paths(root)
    rows = []
    for rel in paths:
        fp = root / rel
        idx = _index_hash(root, rel)
        wt = _blob_hash(root, fp) if fp.is_file() else None
        head_r = _git(["rev-parse", "HEAD:" + rel], cwd=root) if idx else None
        head_hash = head_r.stdout.strip() if head_r and head_r.returncode == 0 else None
        rows.append({
            "path": rel,
            "index": idx,
            "worktree": wt,
            "head": head_hash,
            "index_eq_wt": idx == wt if idx and wt else None,
        })
    return {
        "sole_writer": sole_writer_record(),
        "operator_go": operator_go_record(),
        "pm_mission": pm_mission_record(),
        "index_worktree_mismatches": index_worktree_mismatches(root),
        "staged_checks_not_on_head": staged_enforced_checks_not_on_head(root),
        "live_collect_disk_only": live_collect_disk_only(root),
        "enforcement_hashes": rows,
        "orphan_patch_warnings": precommit_orphan_patch_warnings(root),
    }


def all_precommit_violations(repo: Path | None = None) -> list[str]:
    root = repo or REPO
    out = index_worktree_mismatches(root)
    out.extend(
        staged_enforced_checks_not_on_head(root)
        if not operator_go_granted("staged_lock_surface")
        else []
    )
    out.extend(precommit_orphan_patch_warnings(root))
    out.extend(
        WDL.live_writer_drift_violations(
            root, agent=current_agent_role(), staged_only=True
        )
    )
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Operating process lock (RC-217)")
    p.add_argument("--pre-commit", action="store_true", help="pre-commit mode: exit 1 on violation")
    p.add_argument("--measure", action="store_true", help="print JSON measure report")
    p.add_argument("--commit-check", action="store_true", help="commit-time predicates only")
    args = p.parse_args(argv)
    if args.measure:
        print(json.dumps(measure_report(), indent=2))
        return 0
    if args.commit_check:
        v = commit_violations(REPO)
    elif args.pre_commit:
        v = all_precommit_violations(REPO)
    else:
        v = index_worktree_mismatches(REPO) + staged_enforced_checks_not_on_head(REPO)
        if not operator_go_granted("staged_lock_surface"):
            pass
        disk = live_collect_disk_only(REPO)
        if disk:
            v.append(disk)
    if v:
        for msg in v:
            print(msg, file=sys.stderr)
        return 1
    print("PASS operating_process_lock")
    return 0


if __name__ == "__main__":
    sys.exit(main())
