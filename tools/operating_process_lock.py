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

# The ONE shell reader (tools/shell_parse.py, stdlib-only): the rules below judge each git
# statement a command runs on its own words.
from tools.shell_parse import git_subcommand, read  # noqa: E402

#: Paths where index≠WT is catastrophic: the one writer and the guards.
ENFORCEMENT_PATHS: tuple[str, ...] = (
    "db.py",
    "tools/hook_chain.py",
    "tools/pretooluse_guard.py",
    "tools/operator_law_guard.py",
    "tools/operating_process_lock.py",
    "tools/process_lock_guard.py",
)

#: Wipe-protected paths (LOCK-2 reach).
PROTECTED_PATHS: tuple[str, ...] = ENFORCEMENT_PATHS

#: LOCK-2: the tree-destructive git class, not just `reset --hard`. The hard forms (reset --hard,
#: checkout -- <any path>, clean -f, push --force without lease, short -f included) are `_hard`
#: below and refuse on any target. The class rule covers the reset/restore/checkout--/clean/stash
#: family: a statement running a destructive verb AND touching a protected/product path (or a
#: bare, whole-tree form) is refused at PreToolUse in every session wired to process_lock_guard.
#: git's global options (`git -C <other> ...`) are skipped; the class rule is judged per
#: statement, so a safe first statement exempts nothing chained after it; `git reset --soft`
#: (HEAD only) is safe.

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
    "static/",
    "calibration/",
    "features/",
    "tools/",
)


def _hard(sub: str, args: list[str]) -> bool:
    """A git subcommand that discards work whatever it names."""
    return ((sub == "reset" and "--hard" in args)
            or (sub == "checkout" and args[:1] == ["--"] and len(args) > 1)
            or (sub == "clean" and any(re.match(r"-[a-z]*f", a, re.I) for a in args))
            or (sub == "push" and any((a.startswith("--force") and not a.startswith("--force-with-lease"))
                                      or re.fullmatch(r"-[a-zA-Z]*f[a-zA-Z]*", a) for a in args)))


def _safe(sub: str, args: list[str]) -> bool:
    """A form of the class that cannot reach the index or the worktree, or only reads."""
    first = args[0] if args else ""
    return ((sub == "reset" and first == "--soft")
            or (sub == "restore" and first == "--staged" and "--worktree" not in args)
            or (sub == "stash" and first == "list")
            or (sub == "checkout" and first == "-b")
            or (sub == "clean" and bool(re.match(r"-\S*n", first))))


def _reset_class_violation(words: tuple[str, ...]) -> list[str]:
    """The CLASS rule for ONE statement (RC-525): a chain cannot launder a later wipe."""
    sub, args = git_subcommand(words)
    if not (sub in ("reset", "restore", "clean", "stash") or (sub == "checkout" and "--" in args[:-1])) \
            or _safe(sub, args):
        return []
    seg = " ".join(words)
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


def reset_guard_violations(command: str, powershell: bool = False) -> list[str]:
    """LOCK-2: BLOCK tree-destructive git — the ONE owner of that question (RC-231/RC-252).

    Two clauses, one predicate. The HARD forms (`reset --hard`, `checkout -- <any path>`,
    `clean -f`, `push --force`/`-f`) discard work whatever they name, so they refuse on sight,
    on ANY target (host-wide; the checkout in front of the command is irrelevant — RC-258 kept
    these unscoped on purpose). The CLASS forms (the wider reset/restore/checkout--/clean/stash
    family) refuse when they touch a protected/product path or take a bare whole-tree shape,
    judged PER STATEMENT (RC-525) so a safe first statement cannot launder a later one.

    Not subject-disableable (RC-450): no env token or repo file can authorize a wipe.
    `git reset --soft`, `git restore --staged` (index-only), `git stash list`,
    `git checkout -b` and `push --force-with-lease` stay legal. Text a command only carries (a
    commit message, a heredoc nothing runs) is not a statement.
    """
    gits = [st.words for st in read(command or "", powershell=powershell) if st.program == "git"]
    if any(_hard(*git_subcommand(words)) for words in gits):
        return [
            "RESET_GUARD (LOCK-2/RC-231): destructive git can discard operator work — "
            "reset --hard / checkout -- <path> / clean -f / push --force or -f are refused on "
            "any target (`--force-with-lease` is the safe form). Hand it to the operator. Not "
            "subject-disableable (RC-450)."
        ]
    for words in gits:
        hit = _reset_class_violation(words)
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


#: the output filters whose exit code replaced a commit's (the measured maskers); a pipe into
#: anything else passes
_MASKING_FILTERS = frozenset({"tail", "head", "cat", "tee", "grep", "findstr", "out-null", "select-object"})


def commit_pipe_violations(cmd: str, powershell: bool = False) -> list[str]:
    """RC-234: a `git commit` piped into a filter (tail/head/grep/Out-Null/...) reports
    the FILTER's exit code and truncates hook output — twice this masked a failed landing
    as exit 0 (F401 hidden, t6+t12 slice silently not on HEAD). Commits run UNPIPED;
    long hooks go to a background task whose full output is read back. Escape:
    '# pipe-ok: <reason>' (operator-reviewed). A `|` inside a quoted -m message is not a pipe."""
    if not cmd or "# pipe-ok:" in cmd:
        return []
    for st in read(cmd, powershell=powershell):
        up = st.upstream if st.program in _MASKING_FILTERS else None
        while up is not None and git_subcommand(up.words)[0] != "commit":
            up = up.upstream
        if up is not None:
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
