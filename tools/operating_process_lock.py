"""Operating-process mechanical lock (RC-217): two predicates, one owner each.

  (a) index≠WT parity on the enforcement paths, at the `operating-process` pre-commit hook —
      a pre-commit stash strip (RC-215) once committed a checker the working tree did not hold;
  (b) tree-destructive git — THE one owner of that class, universal hard forms included —
      and pipe-masked commits (RC-234), consumed by tools/process_lock_guard.py at PreToolUse.

DELETED 2026-09-10 (KEEP/MERGE/DELETE): the re-date rule (`RE-DATED old->new: BLOCKED_ON_*`
lineage on ledger rows — prose policing of a bookkeeping field; an overdue row is already
visible debt to `check_root_cause_log`), the orphan-patch heuristic (blocked commits on
stale pre-commit cache files), and the PreToolUse copy of the index-parity check (the
pre-commit hook in the target tree is the one owner).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

# The ONE shell segmenter (tools/shell_parse.py, stdlib-only, BEDROCK 2026-09-06): the class
# rule below judges each chained statement on its own (RC-525), and a second splitter here
# would be one truth with two answers.
from tools.shell_parse import iter_command_segments  # noqa: E402

CHECKER_REL = "tools/check_institutional_correctness.py"
DB_REL = "db.py"


#: Paths where index≠WT is catastrophic (enforcement / collect seam / locks).
ENFORCEMENT_PATHS: tuple[str, ...] = (
    CHECKER_REL,
    DB_REL,
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
#:
#: RC-525 (ported from #221's row 508, re-measured on ac3f78fb 2026-09-06): three holes and one
#: over-block. `git -C <other> reset --hard` passed because the global-option skip admitted
#: only flags, not a flag WITH its argument; `git push -f` passed because only the long
#: spelling was named; `git restore --staged x && git reset --mixed HEAD~1` passed because the
#: safe list was searched across the WHOLE command, so one safe statement exempted everything
#: chained after it; and `git reset --soft`, which moves HEAD and leaves index and worktree
#: untouched, was refused although the repository's own merge authority runs it. The globals
#: prefix admits an option with its argument; the push clause admits flags after the refspec
#: and the short `-f`; the class rule is judged PER SEGMENT (below); `--soft` is safe.
_GIT_GLOBAL_WITH_ARG: tuple[str, ...] = (
    "-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env")
_GIT_GLOBALS = (
    r"(?:(?:" + "|".join(__import__("re").escape(o) for o in _GIT_GLOBAL_WITH_ARG)
    + r")(?:=\S+|\s+\S+)\s+|-\S+\s+)*")
_UNIVERSAL_DESTRUCTIVE_RE = __import__("re").compile(
    r"\bgit\s+" + _GIT_GLOBALS + r"(?:"
    r"reset\s+--hard"
    r"|checkout\s+--\s"
    r"|clean\s+-[a-z]*f"
    r"|push\s+(?:[^|;&]*\s)?(?:--force(?!-with-lease)|-[a-zA-Z]*f[a-zA-Z]*(?=\s|$))"
    r")",
    __import__("re").I)
_RESET_GUARD_RE = __import__("re").compile(
    r"\bgit\s+" + _GIT_GLOBALS
    + r"(reset\b|restore\b|checkout\s+(?:\S+\s+)*--\s|clean\b|stash\b)",
    __import__("re").I)
_RESET_GUARD_SAFE_RE = __import__("re").compile(
    r"\bgit\s+" + _GIT_GLOBALS
    + r"(reset\s+--soft\b|restore\s+--staged\b(?!.*--worktree)|stash\s+list\b|checkout\s+-b\b"
    r"|clean\s+(?:-\S*n\S*\b|--dry-run\b))",
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


def _judged_segments(cmd: str) -> list[str]:
    """The statements of a payload-stripped command, each judged on its own (RC-525).

    `iter_command_segments` is the ONE splitter; it drops heredoc bodies as data. When the
    command hands a heredoc to an interpreter, `_strip_command_payloads` has already kept the
    body because there the body IS the instruction (RC-253), so its lines are segmented too.
    Falls back to the whole command, which fails CLOSED: one big segment blocks at least as
    much as its parts.
    """
    try:
        segs = [seg for _cwd, seg in iter_command_segments(cmd, "")]
        if _INTERPRETER_RE.search(cmd):
            for line in cmd.splitlines():
                segs.extend(seg for _cwd, seg in iter_command_segments(line, ""))
    except (OSError, ValueError):
        segs = []
    return segs or [cmd]


def _reset_class_violation(seg: str) -> list[str]:
    """The CLASS rule for ONE statement (RC-525): a chain cannot launder a later wipe."""
    if not _RESET_GUARD_RE.search(seg) or _RESET_GUARD_SAFE_RE.search(seg):
        return []
    touched = [p for p in PROTECTED_PATHS + PRODUCT_WIPE_PROTECTED if p in seg]
    bare = not any(tok in seg for tok in (" -- ", ".py", ".html", ".json"))
    if touched or bare:
        return [
            "RESET_GUARD (LOCK-2/RC-231): tree-destructive git "
            f"({'paths: ' + ', '.join(sorted(set(touched))[:4]) if touched else 'bare/whole-tree form'}) "
            "— three 2026-08-03 wipes used exactly this class. Not subject-disableable "
            "(Architecture A / RC-450)."
        ]
    return []


def reset_guard_violations(command: str) -> list[str]:
    """LOCK-2: BLOCK tree-destructive git — the ONE owner of that question (RC-231/RC-252).

    Two clauses, one predicate. The HARD forms (`reset --hard`, `checkout -- <any path>`,
    `clean -f`, `push --force`/`-f`) discard work whatever they name, so they refuse on sight,
    on ANY target (host-wide; the checkout in front of the command is irrelevant — RC-258 kept
    these unscoped on purpose). The CLASS forms (the wider reset/restore/checkout--/clean/stash
    family) refuse when they touch a protected/product path or take a bare whole-tree shape,
    judged PER STATEMENT (RC-525) so a safe first statement cannot launder a later one.

    Not subject-disableable (RC-450): no env token or repo file can authorize a wipe.
    `git reset --soft`, `git restore --staged` (index-only), `git stash list`,
    `git checkout -b` and `push --force-with-lease` stay legal.
    """
    cmd = _strip_command_payloads(command or "")
    if _UNIVERSAL_DESTRUCTIVE_RE.search(cmd):
        return [
            "RESET_GUARD (LOCK-2/RC-231): destructive git can discard operator work — "
            "reset --hard / checkout -- <path> / clean -f / push --force or -f are refused on "
            "any target (`--force-with-lease` is the safe form). Hand it to the operator. Not "
            "subject-disableable (RC-450)."
        ]
    for seg in _judged_segments(cmd):
        hit = _reset_class_violation(seg)
        if hit:
            return hit
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


# The enforced-check ROSTER has ONE static reader: tools/check_delta_adds_no_debt.py (the
# required hardening check compares base vs candidate roster there). The second parser of
# the same CHECKS literal that lived here had no caller but the measure report — removed
# 2026-09-10 (KEEP/MERGE/DELETE).


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
        "enforcement_hashes": rows,
    }


def all_precommit_violations(repo: Path | None = None) -> list[str]:
    return index_worktree_mismatches(repo or REPO)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Operating process lock (RC-217)")
    p.add_argument("--pre-commit", action="store_true", help="pre-commit mode: exit 1 on violation")
    p.add_argument("--measure", action="store_true", help="print JSON measure report")
    args = p.parse_args(argv)
    if args.measure:
        print(json.dumps(measure_report(), indent=2))
        return 0
    v = all_precommit_violations(REPO)
    if v:
        for msg in v:
            print(msg, file=sys.stderr)
        return 1
    print("PASS operating_process_lock")
    return 0


if __name__ == "__main__":
    sys.exit(main())
