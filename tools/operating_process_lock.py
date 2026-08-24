"""Operating-process mechanical lock (RC-217).

Machine-checkable predicates for governance/AGENT_OPERATING_PROCESS_V1.md.
The charter is operator-facing; THIS module BLOCKs — .md alone is not a lock.

Child of RC-215 (index≠WT stash-strip), RC-216 (DISK_ONLY vs LIVE), RC-210 (dual-writer thrash).

Minimum BLOCK surfaces:
  (a) Write/Edit control-authority surfaces when ED_AGENT_ROLE is set (RC-454)
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

SOLE_WRITER_PATH = REPO / "governance" / "sole_writer.json"  # NON-AUTHORITATIVE tombstone (RC-456)
OPERATOR_GO_PATH = REPO / "governance" / "operator_go.json"
# Mission COORDINATION metadata only (RC-461) - never authorization.
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
    r"\bgit\s+(?:-\S+\s+)*(reset\b|restore\b|checkout\s+(?:\S+\s+)*--\s|clean\b|stash\b)",
    __import__("re").I)
_RESET_GUARD_SAFE_RE = __import__("re").compile(
    r"\bgit\s+(?:-\S+\s+)*(restore\s+--staged\b(?!.*--worktree)|stash\s+list\b|checkout\s+-b\b|clean\s+(?:-\S*n\S*\b|--dry-run\b))",
    __import__("re").I)

#: RC-252: the STATIC inventory of what must never be wiped, independent of any mission.
#: LOCK-2 originally drew its targeted reach from PROTECTED_PATHS plus the ACTIVE mission's
#: scope_paths — so protection contracted whenever a mission narrowed, which is what a good
#: mission does. Under axiom-brand-landing-v1 that left `git restore -- static/chart.html`,
#: `git checkout -- server.py` and `git restore -- math_levels.py` all silent. Mission scope
#: is still consulted below, but only ever ADDS reach; it can no longer define it.
PRODUCT_WIPE_PROTECTED: tuple[str, ...] = (
    "db.py",
    "server.py",
    "time_et.py",
    "math_exposure_core.py",
    "math_levels.py",
    "liquidity_value_engine.py",
    "liquidity_models.py",
    "ml_predict.py",
    "ml_data_common.py",
    "static/",
    "calibration/",
    "features/",
    "tools/",
)


#: RC-253: a command that pipes its heredoc INTO an interpreter is one where the body IS the
#: instruction, so the body must still be judged. Everywhere else a heredoc is data.
_INTERPRETER_RE = __import__("re").compile(
    r"(?:^|[|;&]\s*)(?:bash|sh|zsh|pwsh|powershell|cmd|eval|xargs|source|\.)\b",
    __import__("re").I)
_HEREDOC_RE = __import__("re").compile(
    r"<<-?\s*(['\"]?)([A-Za-z_]\w*)\1\s*?\n.*?^\2\s*$",
    __import__("re").S | __import__("re").M)
_MESSAGE_PAYLOAD_RE = __import__("re").compile(
    r"(-m|--message|--file|-F)\s+('[^']*'|\"[^\"]*\")")


def _strip_command_payloads(cmd: str) -> str:
    """RC-253: judge the ACTION, not the data the command carries (RC-93).

    A commit message that quotes `git reset --hard` is prose about an incident; the command
    itself touches nothing. Left unstripped, LOCK-2 fired hardest on the most precise incident
    write-ups — taxing exactly the honesty the ledger depends on. Heredoc bodies handed to an
    interpreter are NOT stripped: there the body is the instruction.
    """
    if _INTERPRETER_RE.search(cmd):
        return cmd
    return _MESSAGE_PAYLOAD_RE.sub(r"\1 <payload>", _HEREDOC_RE.sub("<heredoc>", cmd))


def reset_guard_violations(command: str) -> list[str]:
    """LOCK-2: BLOCK tree-destructive git against protected/product scope (RC-231/RC-252).

    Architecture A (RC-450): not subject-disableable. ED_RESET_GUARD and
    operator_go scope git_reset_product cannot authorize a wipe.
    `git restore --staged` (index-only), `git stash list`, `git checkout -b` stay legal.
    """
    cmd = _strip_command_payloads(command or "")
    if not _RESET_GUARD_RE.search(cmd) or _RESET_GUARD_SAFE_RE.search(cmd):
        return []
    touched = [p for p in PROTECTED_PATHS + PRODUCT_WIPE_PROTECTED if p in cmd]
    bare = not any(tok in cmd for tok in (" -- ", ".py", ".html", ".json"))
    if touched or bare:
        return [
            "RESET_GUARD (LOCK-2/RC-231): tree-destructive git "
            f"({'paths: ' + ', '.join(sorted(set(touched))[:4]) if touched else 'bare/whole-tree form'}) "
            "— three 2026-08-03 wipes used exactly this class. Not subject-disableable "
            "(Architecture A / RC-450)."
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
    """Delegate to writer_drift_lock: empty = operator/CI, never a vendor guess."""
    return WDL.current_agent_role()


def _load_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def sole_writer_record() -> dict:
    """Tombstone only (RC-454/RC-456). Not executable authorization."""
    return {"_authority": "NON-AUTHORITATIVE", "pm": "operator", "retired": True}


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
    # RC-402: `staged_lock_surface` is a NORMAL scope token, matched only when a caller
    # queries it. It used to appear here as a third disjunct — `or 'staged_lock_surface'
    # in norm` — which made ANY scope query return True whenever the grant carried that
    # token, silently disarming reset_guard_violations("git_reset_product") and every
    # other held-surface gate. A grant that includes X must not thereby permit everything.
    return scope.lower() in norm or "all" in norm


_WORKTREE_POLICY_PATH = REPO / "tools" / "agent_worktree_policy.json"


def _worktree_policy() -> dict:
    try:
        return json.loads(_WORKTREE_POLICY_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def claude_isolated_edit_violation(
    target_path: str,
    repo: Path | None = None,
    env: dict | None = None,
    policy: dict | None = None,
) -> str | None:
    """Isolated-worktree boundary (operator 2026-08-20): in `mode: isolated`, a claude-role
    edit whose TARGET is inside the PRODUCTION (primary) checkout is BLOCKED. Claude mutates
    application source only in its own `<primary>-Claude` worktree; the primary is
    production-only. Returns a block message, or None when allowed.

    Shared-root mode (RC-129 legacy) returns None — the boundary is not enforced there.
    The guard runs from whichever checkout invoked the hook (REPO); when that checkout IS a
    -Claude worktree, edits under it are allowed (Claude editing its own tree). When the
    hook runs from the primary, a target under the primary root blocks; a target under the
    sibling -Claude worktree (not relative to the primary) is allowed.
    """
    env = env if env is not None else os.environ
    policy = policy if policy is not None else _worktree_policy()
    if str(policy.get("mode") or "isolated").strip().lower() != "isolated":
        return None
    role_var = str(policy.get("env_role_var") or "ED_AGENT_ROLE")
    role = str(env.get(role_var) or "").strip().lower()
    if role != "claude":
        return None
    suffix = str(policy.get("claude_root_suffix") or "-Claude")
    root = (repo or REPO).resolve()
    # The hook running FROM a -Claude worktree: edits under it are Claude's own tree → allow.
    if root.name.endswith(suffix):
        return None
    if not target_path:
        return None
    try:
        tgt = Path(target_path)
        tgt = tgt if tgt.is_absolute() else (root / tgt)
        tgt = tgt.resolve()
    except (OSError, ValueError):
        return None
    # Under the PRODUCTION checkout (path-component containment, not string prefix, so the
    # sibling `<primary>-Claude` is correctly excluded) → BLOCK.
    if tgt == root or tgt.is_relative_to(root):
        return (
            f"ACTION BLOCKED (isolated worktree, operator 2026-08-20): ED_AGENT_ROLE=claude "
            f"may not mutate '{tgt}' inside the PRODUCTION checkout '{root}'. The primary is "
            f"production-only; edit application source only in the '{root.name}{suffix}' "
            f"worktree. (RC-125 probe-live runs against the Claude proof server; RC-350 keeps "
            f"the primary on clean main.)"
        )
    return None


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
    # RC-370: parity is a CONTENT property under git's text semantics, not a raw-byte
    # property. This repo's history swapped effective autocrlf true->false, leaving
    # CRLF worktree files over LF index blobs — raw hashing read that config artifact
    # as permanent enforcement drift on 16 paths while `git status` called the tree
    # clean. CRLF is normalized to LF before hashing (the committed blobs are LF), so
    # EOL noise clears while ANY real edit — one changed byte of content — still
    # produces a different blob hash and trips the lock.
    if not path.is_file():
        return None
    try:
        data = path.read_bytes().replace(b"\r\n", b"\n")
    except OSError:
        return None
    import hashlib

    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def _index_hash(repo: Path, rel: str) -> str | None:
    # RC-370: some blobs in this repo's history were COMMITTED with CRLF (i/crlf in
    # `git ls-files --eol`), so parity must normalize the INDEX side too — both sides
    # hash over CRLF->LF-normalized content, and only real content edits differ.
    r = _git(["ls-files", "-s", "--", rel], cwd=repo)
    if r.returncode != 0 or not r.stdout.strip():
        return None
    sha = r.stdout.strip().split()[1]
    blob = subprocess.run(
        ["git", "cat-file", "blob", sha],
        cwd=str(repo),
        capture_output=True,
        timeout=15,
    )
    if blob.returncode != 0:
        return None
    data = blob.stdout.replace(b"\r\n", b"\n")
    import hashlib

    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


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
            # RC-374: an enforcement path present in the WORKTREE but absent from the
            # index is a planted/untracked enforcement surface — fail closed, never
            # invisible (idx-None used to mean skip, which hid exactly that plant).
            if fp.is_file():
                out.append(f"{rel}: exists in worktree but not in the index (untracked enforcement surface)")
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
    # RC-373: a probe must type its own absence — a host without iproute2 (`ss`)
    # answers "cannot determine" (None), never FileNotFoundError up through
    # completion_claim_violations / measure_report.
    try:
        r = subprocess.run(
            ["ss", "-ltnp", f"sport = :{port}"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    m = re.search(r"pid=(\d+)", r.stdout)
    return int(m.group(1)) if m else None


def _process_start_epoch(pid: int) -> float | None:
    # RC-438: read start-time in-process via psutil (robust, cross-platform, epoch
    # seconds) BEFORE any interpreter shell-out. The prior win32 path cold-started
    # powershell, importing every powershell/CLR/AMSI failure mode into a check that
    # measures process identity — a host powershell hang made a provably-clean runtime
    # unmeasurable. Check LOGIC (fail if start < db_mtime) is unchanged.
    try:
        import psutil  # already a venv dependency
        return float(psutil.Process(pid).create_time())
    except Exception:  # institutional-swallow-ok: psutil missing/unreadable -> fall through to the win32/proc readers below (RC-438)
        pass
    if sys.platform == "win32":
        # Fallback only if psutil is unavailable (see RC-438).
        try:
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
        except (subprocess.SubprocessError, OSError):
            return None
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


def _db_content_change_epoch(root: Path, db_path: Path) -> float | None:
    """When db.py's CONTENT last changed. For a db.py that is CLEAN vs HEAD, this is its git
    COMMIT time — NOT the filesystem mtime, which a fresh `git worktree add`/checkout stamps to
    "now" even though the content did not change (that artifact created a FALSE DISK_ONLY when
    auditing an isolated worktree: the checkout mtime was newer than a legitimately-current
    console). For a db.py that is locally MODIFIED, the fs mtime is correct — a real local edit
    is newer than any commit. This keeps real DISK_ONLY detection intact (a console predating
    db.py's true change still flags) while removing the checkout artifact."""
    try:
        fs_mtime = db_path.stat().st_mtime
    except OSError:
        return None
    try:
        dirty = subprocess.run(
            ["git", "diff", "--quiet", "HEAD", "--", DB_REL],
            cwd=str(root), timeout=15,
        ).returncode != 0
        if not dirty:
            r = subprocess.run(
                ["git", "log", "-1", "--format=%ct", "HEAD", "--", DB_REL],
                cwd=str(root), capture_output=True, text=True, timeout=15,
            )
            if r.returncode == 0 and r.stdout.strip():
                return float(r.stdout.strip())
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return fs_mtime


def live_collect_disk_only(repo: Path | None = None, port: int = 8000) -> str | None:
    """Return violation message when disk has gate but live process predates db.py's change."""
    root = repo or REPO
    if not db_has_collect_window_gate(root):
        return None
    db_path = root / DB_REL
    db_mtime = _db_content_change_epoch(root, db_path)
    if db_mtime is None:
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
    """Mission COORDINATION metadata (RC-461) - NOT authorization.

    governance/pm_mission.json is ordinary coordination state. It supplies mission_id
    for the RC-228 linkage check and nothing else: no writer/auditor/vendor field in it
    grants authority, and no gate consults it to decide what an agent may edit. Authority
    is CODEOWNERS + branch protection (durable) plus the control-authority rail
    (tools/writer_drift_lock.control_authority_violation, in-process defense-in-depth).
    """
    return _load_json(PM_MISSION_PATH) or {}


# RC-461: the PM-mission EDIT GATE (pm_mission_edit_violation / sole_writer_edit_violation
# and their _mission_gates_path / _mission_scope_allows helpers) is REMOVED. The operator
# requirement is that the coding AI does ordinary repo work AUTONOMOUSLY; gating product
# edits on an in-progress mission was the overbuilt half of Architecture A and it depended
# on the deleted external authority reader. What remains constrains AUTHORITY only:
# writer_drift_lock.control_authority_violation denies an assigned principal any edit to
# the files that decide who may do what, and CODEOWNERS + branch protection make that
# durable at merge.


def _git_diff_names(root: Path, a: str | None, b: str | None) -> list[str]:
    """Changed path names between two revs (or worktree-vs-HEAD when both None)."""
    args = ["git", "diff", "--name-only"]
    if a and b:
        args.append(f"{a}..{b}")
    else:
        args.append("HEAD")
    try:
        r = subprocess.run(args, cwd=str(root), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=30)
    except (OSError, subprocess.SubprocessError):
        return []
    if r.returncode != 0:
        return []
    return [ln.replace("\\", "/").strip() for ln in r.stdout.splitlines() if ln.strip()]


def _quiet_pass_required_violations(text: str, root: Path) -> list[str]:
    """LOCK-5 (RC-232): COMPLETE / LIVE_ENFORCED / mission-complete claims require the
    live quiet bar when the landing touched server.py/db.py — the quiet-window JSON must
    read PASS. Honest escapes only: the DISK_ONLY_UNTIL_RESTART token in the same claim,
    or an explicit operator '# quiet-bar-ok:' waiver."""
    if not re.search(r"\b(COMPLETE\b|LIVE_ENFORCED\b|mission[- ]complete)\b", text):
        return []
    if _DISK_ONLY_TOKEN.search(text) or "# quiet-bar-ok:" in text:
        return []
    touched = set(_git_diff_names(root, "HEAD~1", "HEAD")) | set(
        _git_diff_names(root, None, None))
    if not ({"server.py", "db.py"} & touched):
        return []
    try:
        qj = json.loads((root / "reports" /
                         "ed_server_warn_quiet_window_latest.json").read_text(
                             encoding="utf-8"))
        verdict = str(qj.get("verdict") or "")
    except (OSError, ValueError, json.JSONDecodeError):
        verdict = "MISSING"
    if verdict == "PASS":
        return []
    return [
        f"QUIET_PASS_REQUIRED: completion claim with server.py/db.py touched but "
        f"ed_server_warn_quiet_window_latest.json verdict={verdict!r} (LOCK-5/RC-232) — "
        f"run the gate to PASS, or state DISK_ONLY_UNTIL_RESTART / obtain '# quiet-bar-ok:'."
    ]


#: RC-241: phrasings that ASSERT the operator GO has been consumed / closed.
_GO_CLOSED_CLAIM_RE = re.compile(
    r"\boperator_go\b[^.\n]{0,90}?\b(?:closed|consumed|granted=false|set to false)\b"
    r"|\bGO\s+(?:consumed|closed)\b"
    r"|\b(?:closed|consumed)\s+(?:the\s+)?GO\b",
    re.I,
)


def go_closeout_violations(commit_message: str, repo: Path | None = None) -> list[str]:
    """RC-241: a commit that CLAIMS the GO was closed must actually ship it closed.

    The GO protocol was enforced only on the way IN (staged ENFORCED checks require
    granted=true) and nothing checked the way OUT. I told the operator the GO was "closed
    back to false in this commit" while the committed blob carried granted=true — the claim
    rested on my discipline, not on a check, and the PM had to catch it. A GO left open on
    HEAD is a standing authorisation nobody granted for the NEXT commit, which is precisely
    the self-approval hazard the file exists to prevent.

    Fires ONLY when the message makes the claim: leaving a GO open without saying otherwise
    is a process matter for the PM, not a lie, and is not this lock's business.
    """
    root = repo or REPO
    if not commit_message or not _GO_CLOSED_CLAIM_RE.search(commit_message):
        return []
    try:
        r = subprocess.run(
            ["git", "show", ":governance/operator_go.json"],
            cwd=str(root), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if r.returncode != 0:
        return [
            "GO_CLOSEOUT: the commit message claims the operator GO was closed/consumed, but "
            "governance/operator_go.json is NOT staged — the claim and the artifact must "
            "agree at the moment of commit (RC-241)."
        ]
    try:
        granted = bool(json.loads(r.stdout).get("granted"))
    except (ValueError, json.JSONDecodeError):
        return [
            "GO_CLOSEOUT: staged governance/operator_go.json does not parse, so a closure "
            "claim cannot be verified — unmeasurable is never a pass (RC-241)."
        ]
    if granted:
        return [
            "GO_CLOSEOUT: the commit message claims the operator GO was closed/consumed while "
            "the STAGED governance/operator_go.json still reads granted=true (RC-241). Either "
            "set granted=false and stage it, or stop claiming the closure."
        ]
    return []


_QUOTED_STRING_RE = re.compile(r"\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*'")


def commit_pipe_violations(cmd: str) -> list[str]:
    """RC-234: a `git commit` piped into a filter (tail/head/grep/Out-Null/...) reports
    the FILTER's exit code and truncates hook output — twice this masked a failed landing
    as exit 0 (F401 hidden, t6+t12 slice silently not on HEAD). Commits run UNPIPED;
    long hooks go to a background task whose full output is read back. Escape:
    '# pipe-ok: <reason>' (operator-reviewed). Pipes inside the quoted -m message are
    legal — quoted strings are stripped before the scan."""
    if not cmd or "# pipe-ok:" in cmd:
        return []
    stripped = _QUOTED_STRING_RE.sub("", cmd).replace("||", "&&")
    for seg in re.split(r"&&|;|\n", stripped):
        if re.search(r"\bgit\s+commit\b", seg, re.I) and "|" in seg:
            return [
                "PIPE_MASKED_COMMIT: `git commit` piped into a filter — the filter's exit "
                "code replaces the commit's and hook failures vanish (RC-234). Run the "
                "commit UNPIPED (background task for long hooks), then verify via "
                "`git show --stat`. Escape: '# pipe-ok: <reason>'."
            ]
    return []


_PM_DISPOSITION_RE = re.compile(r"\b(VERIFIED|ACCEPTED|REJECTED|QUEUED|BLOCKED)\b")
_PM_ISSUE_BULLET_RE = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s+(\S.{14,})", re.M)
_PM_ISSUE_LABEL_RE = re.compile(r"\b(ISSUE|BLOCKER|RESIDUAL|P0)\b")
# Named process tokens from the RC-233 encode addendum. Tokens alone form issue units
# only when >=3 DISTINCT ones appear — the false-positive control the addendum demands
# ("single-question operator chats do not BLOCK"): a casual sentence like "after restart
# it went quiet" carries two tokens but is one question, not a multi-issue paste.
_PM_PROCESS_TOKEN_RES = {
    "sole_writer": re.compile(r"\bsole_writer\b"),
    "operator_go": re.compile(r"\boperator_go\b"),
    "pm_mission": re.compile(r"\bpm_mission\b"),
    "PDL": re.compile(r"\bPDL\b"),
    "PDH": re.compile(r"\bPDH\b"),
    "DISK_ONLY": re.compile(r"\bDISK_ONLY\b"),
    "LIVE_ENFORCED": re.compile(r"\bLIVE_ENFORCED\b"),
    "quiet": re.compile(r"\bquiet\b", re.I),
    "restart": re.compile(r"\brestart\b", re.I),
    "lock remainder": re.compile(r"\block remainder\b", re.I),
    "LOCK-": re.compile(r"\bLOCK-\d"),
}


def pm_coverage_issue_units(user_text: str) -> list[str]:
    """RC-233: extract distinct issue units from an operator paste. A unit is a
    substantive bullet/numbered line, an ISSUE/BLOCKER/RESIDUAL/P0-labeled line, or
    (when >=3 distinct ones appear) a named process token not already inside a unit."""
    units: list[str] = []
    for m in _PM_ISSUE_BULLET_RE.finditer(user_text):
        units.append(m.group(1).strip()[:60])
    for ln in user_text.splitlines():
        if _PM_ISSUE_LABEL_RE.search(ln) and not any(
                ln.strip()[:60].startswith(u[:20]) for u in units):
            units.append(ln.strip()[:60])
    tok_hits = [name for name, rx in _PM_PROCESS_TOKEN_RES.items()
                if rx.search(user_text)]
    if len(tok_hits) >= 3:
        covered = "\n".join(units)
        for name in tok_hits:
            if not _PM_PROCESS_TOKEN_RES[name].search(covered):
                units.append(name)
    return units


def pm_coverage_violations(user_text: str | None, assistant_text: str) -> list[str]:
    """LOCK RC-233 (PM full-prompt coverage, operator law 2026-08-04): a multi-issue
    operator paste (>=2 distinct units) requires the reply to disposition EVERY unit —
    VERIFIED/ACCEPTED/REJECTED/QUEUED/BLOCKED, at least one token per unit. Escape:
    operator '# pm-coverage-ok:' naming the waived items. Deny prefix: PM_COVERAGE:."""
    u = user_text or ""
    a = assistant_text or ""
    if "# pm-coverage-ok:" in u:
        return []
    units = pm_coverage_issue_units(u)
    if len(units) < 2:
        return []
    dispositions = len(_PM_DISPOSITION_RE.findall(a))
    if dispositions >= len(units):
        return []
    unaddressed = [s for s in units
                   if not re.search(re.escape(s.split()[0][:12]), a, re.I)][:5]
    return [
        f"PM_COVERAGE: operator paste carries {len(units)} distinct issue units but the "
        f"reply holds only {dispositions} disposition token(s) "
        f"(VERIFIED/ACCEPTED/REJECTED/QUEUED/BLOCKED) — every item gets a per-item "
        f"disposition + one-line note (RC-233). Units with no echo in the reply: "
        + ("; ".join(unaddressed) if unaddressed else "(all echoed, dispositions missing)")
        + ". Escape: operator '# pm-coverage-ok:' naming the waived items."
    ]


def completion_claim_violations(text: str, repo: Path | None = None) -> list[str]:
    """BLOCK COMPLETE/LIVE/parity claims while measurable preconditions fail."""
    if not text:
        return []
    root = repo or REPO
    out: list[str] = []
    # LOCK-5 (RC-232) triggers on its OWN claim regex — the legacy _COMPLETION_CLAIM tails
    # missed plain forms like 'Mission COMPLETE: ...' (measured by its own fixture).
    out.extend(_quiet_pass_required_violations(text, root))
    if not _COMPLETION_CLAIM.search(text):
        return out
    mism = index_worktree_mismatches(root)
    if mism:
        out.append(
            "completion claim while index≠WT on enforcement paths: "
            + "; ".join(mism[:5])
        )
    disk = live_collect_disk_only(root)
    if disk and _LIVE_RC_CLAIM.search(text) and not _DISK_ONLY_TOKEN.search(text):
        out.append(f"completion claim LIVE_ENFORCED while {disk}")
    # (LOCK-5 runs above via _quiet_pass_required_violations — independent trigger.)
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
    # RC-454: assigned principal staging control-authority rails → commit BLOCK.
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
