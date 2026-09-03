"""Operating-process mechanical lock (RC-217).

Machine-checkable predicates for governance/AGENT_OPERATING_PROCESS_V1.md.
The charter is operator-facing; THIS module BLOCKs — .md alone is not a lock.

Child of RC-215 (index≠WT stash-strip), RC-216 (DISK_ONLY vs LIVE), RC-210 (dual-writer thrash).

Minimum BLOCK surfaces (2026-08-24 teardown: the role/GO/mission rails are gone):
  (a) Stop on COMPLETE/LIVE/one-intentional-tree claims while index≠WT or live PID predates db.py gate
  (b) git commit when index≠WT on staged enforcement paths; tree-destructive/piped git blocked at PreToolUse
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

CHECKER_REL = "tools/check_institutional_correctness.py"
DB_REL = "db.py"


#: Paths where index≠WT is catastrophic (enforcement / collect seam / locks).
ENFORCEMENT_PATHS: tuple[str, ...] = (
    CHECKER_REL,
    DB_REL,
    "tools/honesty_guard.py",
    # RC-505: tools/plus_player_locks.py deleted — its catalog was archived and its one live
    # helper moved to tools/find_prove_locks.py, which is already listed below.
    "tools/find_prove_locks.py",
    "tools/mission_latch.py",
    "tools/pretooluse_guard.py",
    "tools/operator_law_guard.py",
    "tools/stop_guard.py",
    "tools/operating_process_lock.py",
    "tools/process_lock_guard.py",
    "calibration/repair_canonical_1m_shared.py",
    "calibration/repair_canonical_1m_bars_for_outcomes.py",
)

#: Wipe-protected paths (LOCK-2 reach): enforcement surfaces plus the calibration
#: producers below — role-free since the 2026-08-24 teardown.
PROTECTED_PATHS: tuple[str, ...] = ENFORCEMENT_PATHS + (
    "calibration/build_trusted_anchor_proof_dataset.py",
    "calibration/run_production_accumulation_validation.py",
)

#: LOCK-2 (RC-231): the tree-destructive git CLASS, not just `reset --hard`. Three wipes on
#: 2026-08-03 (RC-210 x2, RC-229) used soft forms the literal-match ban never saw. A command
#: matching a destructive verb AND touching a protected/product path (or bare, whole-tree
#: forms) BLOCKS at PreToolUse in EVERY session wired to process_lock_guard.
#: RC-505: this is now the ONE owner of "destructive git". It used to be two — a second regex
#: (`operator_law_guard._DESTRUCTIVE_GIT`) ran on the SAME PreToolUse(Bash) event through the
#: same chain, and a comment in both files called the split deliberate. MEASURED 2026-09-02
#: over 25 command forms: 8 blocked TWICE with two different messages, 2 only there, 6 only
#: here — and `git push -f origin main` blocked NOWHERE, because that regex spelled the force
#: flag `--force` only. A split predicate does not add coverage; it hides the gap between the
#: halves. The two forms unique to the other half are folded in below and the `-f` hole is
#: closed, so this file answers the question once.
#: git's GLOBAL options — the ones that sit between `git` and the subcommand. The first group
#: takes its value as a SEPARATE token, which is why they need their own alternative: a
#: `(?:-\S+\s+)*` prefix consumes `-C ` and then stalls on the path, so `git -C ../other reset
#: --hard` slipped past BOTH previous destructive-git regexes (MEASURED 2026-09-02 — it wipes
#: another checkout, which is the worst case, not an edge case). One definition, consumed by
#: the regex below and by process_lock_guard's token parser.
GIT_GLOBAL_WITH_ARG: tuple[str, ...] = (
    "-C", "-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix", "--exec-path",
)
_GIT_GLOBALS = (r"(?:(?:" + "|".join(__import__("re").escape(o) for o in GIT_GLOBAL_WITH_ARG)
                + r")\s+\S+\s+|-\S+\s+)*")

_RESET_GUARD_RE = __import__("re").compile(
    r"\bgit\s+" + _GIT_GLOBALS +
    r"(reset\b|restore\b|checkout\s+(?:\S+\s+)*--\s|clean\b|stash\b)",
    __import__("re").I)
_RESET_GUARD_SAFE_RE = __import__("re").compile(
    r"\bgit\s+" + _GIT_GLOBALS +
    r"(restore\s+--staged\b(?!.*--worktree)|stash\s+list\b|checkout\s+-b\b|clean\s+(?:-\S*n\S*\b|--dry-run\b))",
    __import__("re").I)

#: The UNIVERSAL hard forms: destructive whatever they name, so they never consult the
#: protected-path inventory below. `--force-with-lease` is excluded because it refuses to
#: overwrite work the pusher has not seen — that is the safe form, and banning it would push
#: people to the unsafe one. Both spellings of the force flag are here: the previous owner
#: matched `--force` only, so `git push -f` walked through every guard on the chain.
_HARD_WIPE_RE = __import__("re").compile(
    r"\bgit\s+" + _GIT_GLOBALS + r"(?:"
    r"reset\s+--hard"
    r"|checkout\s+--\s+\.(?:/)?(?:\s|$)"
    r"|clean\s+-[a-z]*f"
    r"|push\s+(?:[^|;&]*\s)?(?:--force(?!-with-lease)|-[a-zA-Z]*f[a-zA-Z]*(?=\s|$))"
    r")", __import__("re").I)

#: RC-252: the STATIC inventory of what must never be wiped, independent of any mission.
#: LOCK-2 originally drew its targeted reach from PROTECTED_PATHS plus the ACTIVE mission's
#: scope_paths — so protection contracted whenever a mission narrowed, which is what a good
#: mission does. Under axiom-brand-landing-v1 that left `git restore -- static/chart.html`,
#: `git checkout -- server.py` and `git restore -- math_levels.py` all silent. Mission scope
#: is gone (2026-08-24 teardown); this static inventory alone defines LOCK-2 reach.
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
    """LOCK-2: BLOCK destructive git — the ONE owner of that question (RC-231/RC-252/RC-505).

    Two clauses, one predicate. The HARD forms (`reset --hard`, `checkout -- .`, `clean -*f*`,
    `push --force`/`-f`) are destructive whatever they name, so they block on sight, anywhere,
    in any repository the session can reach. The CLASS forms (the wider
    reset/restore/checkout--/clean/stash family) block when they touch a protected/product
    path or take a bare whole-tree shape.

    Both clauses read the SAME payload-stripped command, so a commit message or a heredoc that
    merely quotes a wipe is still prose (RC-253) — which the previous second owner did not do.
    Not subject-disableable (RC-450): no env token or repo file can authorize a wipe.
    `git restore --staged` (index-only), `git stash list`, `git checkout -b` and
    `push --force-with-lease` stay legal.
    """
    cmd = _strip_command_payloads(command or "")
    if _HARD_WIPE_RE.search(cmd):
        return [
            "RESET_GUARD (LOCK-2/RC-231): destructive git — a hard form that discards work "
            "whatever it names (`reset --hard`, `checkout -- .`, `clean -f`, `push --force`/"
            "`-f`). Hand it to the operator. `push --force-with-lease` is the safe form and is "
            "allowed. Not subject-disableable (Architecture A / RC-450)."
        ]
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
# RC-462: PROCESS_ALLOWED_PREFIXES and MISSION_GATED_PREFIXES are gone. They
# described which paths a 'non-writer' could touch and which needed an in-progress
# mission - both concepts are retired. There are no designated roles: the operator
# says what they want done, and the only standing rule is that an acting AI cannot
# edit the files that decide who is in charge.


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
    qp = root / "reports" / "ed_server_warn_quiet_window_latest.json"
    try:
        qj = json.loads(qp.read_text(encoding="utf-8"))
        verdict = str(qj.get("verdict") or "")
    except (OSError, ValueError, json.JSONDecodeError):
        verdict = "MISSING"
    if verdict == "PASS":
        # A PASS measured BEFORE the claimed server.py/db.py change is not the live
        # quiet bar for that change (audit 2026-08-25: a 200-day-old PASS satisfied a
        # fresh claim). Comparator = the changed files' own worktree mtimes — no window
        # constant. Unreadable mtimes keep the PASS (fail-open HERE only; the
        # MISSING/FAIL branches below stay fail-closed).
        try:
            newest = max((root / rel).stat().st_mtime
                         for rel in ({"server.py", "db.py"} & touched)
                         if (root / rel).exists())
            if qp.stat().st_mtime >= newest:
                return []
            verdict = "STALE_PASS (quiet json predates the claimed server.py/db.py change)"
        except (OSError, ValueError):
            return []
    return [
        f"QUIET_PASS_REQUIRED: completion claim with server.py/db.py touched but "
        f"ed_server_warn_quiet_window_latest.json verdict={verdict!r} (LOCK-5/RC-232) — "
        f"run the gate to PASS, or state DISK_ONLY_UNTIL_RESTART / obtain '# quiet-bar-ok:'."
    ]




_RC_ROW_RE = re.compile(r"^\| (RC-\d+) \|")


def _rc_row_map(text: str) -> dict[str, tuple[str, str, str]]:
    """rc_id -> (status, due, full_row) for every RC row in a ledger text."""
    out: dict[str, tuple[str, str, str]] = {}
    for line in text.splitlines():
        m = _RC_ROW_RE.match(line)
        if not m:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 4:
            out[m.group(1)] = (cells[1], cells[3], line)
    return out


def rc_redate_violations(repo: Path | None = None) -> list[str]:
    """REDATE_LOCK: a due date the ledger already promised may move only when the row is
    BLOCKED on something the agent cannot fix in this repository, and the row records
    which: 'RE-DATED <old>-><new>: BLOCKED_ON_<CLASS> — <specifics>'.

    OPERATOR REQUIREMENT (audit round 3, 2026-08-25): "the real requirement is that
    fixable defects get fixed, not administratively postponed." A free-text reason no
    longer passes — 'need more time' and 'deprioritized' are exactly the administrative
    postponements the requirement bans. If the defect is fixable in-repo, the fix ships
    and the date never moves; a row that is late stays OVERDUE in plain sight, which is
    a signal, not something to re-date away. The declared blocker classes each name a
    dependency outside the agent's reach:
      BLOCKED_ON_OPERATOR      — needs an operator decision or an operator-run action
      BLOCKED_ON_LIVE_SESSION  — evidence observable only during a market session
      BLOCKED_ON_DATA_ACCRUAL  — needs more collected data before it can be judged
      BLOCKED_ON_EXTERNAL      — vendor/third-party dependency
    Specifics after the class token are mandatory (WHAT is awaited), so the class cannot
    become a rubber stamp. This forces the blocker claim to EXIST with correct lineage;
    it cannot prove the claim TRUE — a false BLOCKED_ON_* is a lie in a reviewed diff.

    Staged index vs HEAD — the same seam as the rest of this lock. New rows are free
    (opening a defect with a due date is honest tracking, RC-65); a row leaving OPEN is
    free (closing defers nothing). Repeat re-dates accumulate a visible chain in the row.
    MEASURED basis (audit 2026-08-25): 67 due-cell moves in history, 61 on already-overdue
    rows, 2 with no reason recorded anywhere (4ecb1cb7 RC-210, b13b117b RC-257).
    Deliberately NO extension ceiling and NO re-date count cap (RC-280: no ratchets) —
    a thrice-re-dated row visibly carries all three RE-DATED entries for operator review.
    Fail-closed: an unreadable staged side refuses the commit.
    HONEST LIMITS (red-team 2026-08-25): (a) binds at local pre-commit only — commits
    from unhooked checkouts or the GitHub web UI bypass it, and CI does not re-check
    lineage; (b) the close-then-reopen two-commit dance can move a due date without
    lineage — partially mitigated because the transient terminal row must satisfy the
    ledger's terminal-evidence gate; (c) governance/unproven_register.md due dates are
    out of scope. Extending any of these is the operator's call, not an auto-hardening."""
    root = repo or REPO
    rel = "governance/root_cause_log.md"
    sr = _git(["diff", "--cached", "--name-only", "--", rel], cwd=root)
    if sr.returncode != 0:
        return [f"REDATE_LOCK: git diff --cached unavailable for {rel} — refusing an "
                f"unverifiable ledger edit"]
    if rel not in sr.stdout:
        return []
    head = _git(["show", f"HEAD:{rel}"], cwd=root)
    staged = _git(["show", f":{rel}"], cwd=root)
    if head.returncode != 0:
        return []  # ledger new at HEAD — nothing already promised
    if staged.returncode != 0:
        return [f"REDATE_LOCK: cannot read staged {rel} — refusing an unverifiable ledger edit"]
    old_rows, new_rows = _rc_row_map(head.stdout), _rc_row_map(staged.stdout)
    out: list[str] = []
    for rc in sorted(set(old_rows) & set(new_rows)):
        _old_status, old_due, _ = old_rows[rc]
        new_status, new_due, new_line = new_rows[rc]
        if old_due == new_due or new_status != "OPEN":
            continue
        token = f"RE-DATED {old_due}->{new_due}:"
        i = new_line.find(token)
        rest = "" if i < 0 else new_line[i + len(token):].split("|", 1)[0].strip()
        m = re.match(
            r"BLOCKED_ON_(OPERATOR|LIVE_SESSION|DATA_ACCRUAL|EXTERNAL)\b[\s—:-]*(\S.*)?",
            rest)
        if i < 0 or m is None or not (m.group(2) or "").strip():
            out.append(
                f"REDATE_LOCK: {rc} due {old_due} -> {new_due} refused. Fixable defects "
                f"get FIXED, not administratively postponed (operator, 2026-08-25). A "
                f"promised date moves only when the row is blocked on something outside "
                f"this repository, recorded in the row as '{token} BLOCKED_ON_OPERATOR|"
                f"BLOCKED_ON_LIVE_SESSION|BLOCKED_ON_DATA_ACCRUAL|BLOCKED_ON_EXTERNAL "
                f"— <what is awaited>'. Otherwise ship the fix, or leave the row overdue "
                f"in plain sight (61 of 67 historical re-dates were on already-overdue "
                f"rows).")
    return out


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
    # SIMPLICITY REHAB 2026-08-24 (T2-6): the ban binds the OBSERVED defect class — a
    # commit piped into an output FILTER whose exit code replaces the commit's
    # (tail/head/cat/tee/grep/findstr/Out-Null/Select-Object were the measured maskers).
    # A pipe into anything else on the segment passes.
    masking_filter = re.compile(
        r"\|\s*(?:tail|head|cat|tee|grep|findstr|Out-Null|Select-Object)\b", re.I)
    for seg in re.split(r"&&|;|\n", stripped):
        if re.search(r"\bgit\s+commit\b", seg, re.I) and masking_filter.search(seg):
            return [
                "PIPE_MASKED_COMMIT: `git commit` piped into a filter — the filter's exit "
                "code replaces the commit's and hook failures vanish (RC-234). Run the "
                "commit UNPIPED (background task for long hooks), then verify via "
                "`git show --stat`. Escape: '# pipe-ok: <reason>'."
            ]
    return []




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
    # RC-463: saying "ready to commit" while a lock surface is staged is no longer a
    # blocked claim - the assistant commits its own work, so there is nothing to grant.
    return out


def commit_violations(repo: Path | None = None) -> list[str]:
    """Predicates for git commit PreToolUse / pre-commit."""
    root = repo or REPO
    out: list[str] = []
    mism = index_worktree_mismatches(root, only_staged=True)
    if mism:
        out.append("commit BLOCKED: staged enforcement path index≠WT — " + "; ".join(mism))
    out.extend(precommit_orphan_patch_warnings(root))
    # RC-463/RC-475: no PERMISSION gate here. Authority changes are approved by the
    # operator's explicit word in chat; required CI is the machine gate at merge. Only
    # mechanical integrity is checked above.
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
        "index_worktree_mismatches": index_worktree_mismatches(root),
        "staged_checks_not_on_head": staged_enforced_checks_not_on_head(root),
        "live_collect_disk_only": live_collect_disk_only(root),
        "enforcement_hashes": rows,
        "orphan_patch_warnings": precommit_orphan_patch_warnings(root),
    }


def all_precommit_violations(repo: Path | None = None) -> list[str]:
    root = repo or REPO
    out = index_worktree_mismatches(root)
    out.extend(precommit_orphan_patch_warnings(root))
    out.extend(rc_redate_violations(root))
    # RC-463: permission is a merge-review question, not a pre-commit question.
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
        v = index_worktree_mismatches(REPO)
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
