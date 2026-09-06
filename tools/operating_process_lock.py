"""Operating-process mechanical lock (RC-217).

Machine-checkable predicates for governance/AGENT_OPERATING_PROCESS_V1.md.
The charter is operator-facing; THIS module BLOCKs — .md alone is not a lock.

Child of RC-215 (index≠WT stash-strip), RC-210 (dual-writer thrash).

BLOCK surfaces (2026-08-24 teardown: the role/GO/mission rails are gone; BEDROCK 2026-09-06:
the completion-claim lock LOCK-5/RC-232 and the LIVE-vs-DISK probe RC-216 are gone — the
first matched COMPLETE/LIVE_ENFORCED words in prose, the second measured a running server's
start time from inside a governance hook; neither is a mechanism deciding a structural fact):
  (a) git commit when index≠WT on staged enforcement paths (pre-commit + PreToolUse)
  (b) tree-destructive git — THE one owner of that class, universal hard forms included —
      and pipe-masked commits, blocked at PreToolUse
  (c) RC re-dating without lineage, at pre-commit
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
#: BEDROCK 2026-09-06: ONE owner. The universal hard forms (reset --hard, checkout -- <any
#: path>, clean -f, push --force without lease) used to live as a second regex in
#: operator_law_guard, "deliberately split, both firing" — two rules answering one question.
#: They are `_UNIVERSAL_DESTRUCTIVE_RE` below and refuse regardless of target; the class rule
#: covers the full reset/restore/checkout--/clean/stash verb family on protected/bare targets.
_UNIVERSAL_DESTRUCTIVE_RE = __import__("re").compile(
    r"\bgit\s+(?:-\S+\s+)*(?:reset\s+--hard|checkout\s+--\s|clean\s+-[a-z]*f"
    r"|push\s+--force(?!-with-lease))",
    __import__("re").I)
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
    """LOCK-2: BLOCK tree-destructive git against protected/product scope (RC-231/RC-252).

    Not subject-disableable (RC-450): no env token or repo file can authorize a wipe.
    `git restore --staged` (index-only), `git stash list`, `git checkout -b` stay legal.
    The universal hard forms refuse on ANY target (host-wide; the checkout in front of the
    command is irrelevant — RC-258 kept these unscoped on purpose).
    """
    cmd = _strip_command_payloads(command or "")
    if _UNIVERSAL_DESTRUCTIVE_RE.search(cmd):
        return [
            "RESET_GUARD (LOCK-2/RC-231): destructive git can discard operator work — "
            "reset --hard / checkout -- <path> / clean -f / push --force are refused on any "
            "target. Hand it to the operator. Not subject-disableable (RC-450)."
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
    if v:
        for msg in v:
            print(msg, file=sys.stderr)
        return 1
    print("PASS operating_process_lock")
    return 0


if __name__ == "__main__":
    sys.exit(main())
